"""Codex backend for the existing Engine stages; deliberately no second orchestrator."""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from ..authority import EvidenceAuthority, ProjectGrant, RuntimePolicy
from ..models import (
    Architecture,
    Criterion,
    FailureClass,
    Finding,
    Origin,
    Outcome,
    PermissionDenied,
    Plan,
    Planning,
    PlatformSnapshot,
    PullRequest,
    Review,
    Role,
    TeamError,
    digest,
)
from .base import AgentContext
from .cloud_contracts import CloudApproval, CloudJob, fields, strings, text_value
from .cloud_results import CloudResultImporter
from .codex_cloud import CodexCloudGateway

PLANNING_SCHEMA = (
    'Payload: {"criteria":[{"id":"AC-1","description":"measurable criterion"}],'
    '"tasks":["concrete task"],"architecture":{"summary":"design",'
    '"dependencies":[],"risks":[]}}. Inspect the repository as orchestrator AND architect. '
    "Only write the result artifact, never repository source."
)
DEVELOPMENT_SCHEMA = (
    'Payload: {"summary":"implemented changes"}. Implement source, tests and documentation; '
    "do not change protected controls, instructions, automation or permissions."
)
REVIEW_SCHEMA = (
    'Payload: {"outcome":"pass|fail|unknown","covered_criteria":["AC-1"],'
    '"findings":[{"category":"qa|security","code":"stable-code","message":"finding",'
    '"suggestion":"concrete correction","blocking":true,"repairable":true}]}. '
    "PASS requires every acceptance criterion and no blocking finding. "
    "Read repository source without editing it; only write the result artifact. "
    "Report test claims separately; they are not controller test execution evidence."
)


def cloud_authority(grant: ProjectGrant) -> EvidenceAuthority:
    """Task-bound output receipts, explicitly NOT immutable runtime attestations."""
    issuers = {
        f"codex-cloud:{env}": (role, frozenset({Origin.CODEX_CLOUD}))
        for role, env in grant.cloud_environments
        if role != Role.ARCHITECT
    }
    issuers["local-check-runner"] = (Role.QA, frozenset({Origin.LOCAL_EXECUTION}))
    return EvidenceAuthority(issuers)


class CodexCloudAgents:
    simulated = False
    review_origin = Origin.CODEX_CLOUD

    def __init__(
        self,
        gateway: CodexCloudGateway,
        approval: CloudApproval,
        grant: ProjectGrant,
        policy: RuntimePolicy,
        *,
        allowed_paths: tuple[str, ...] | None = None,
        audit_directory: Path | None = None,
    ):
        self.gateway, self.approval, self.grant, self.policy = gateway, approval, grant, policy
        environments = dict(grant.cloud_environments)
        self.orchestrator_identity = f"codex-cloud:{environments.get(Role.ORCHESTRATOR, '')}"
        self.developer_identity = f"codex-cloud:{environments.get(Role.DEVELOPER, '')}"
        self.qa_identity = f"codex-cloud:{environments.get(Role.QA, '')}"
        self.security_identity = f"codex-cloud:{environments.get(Role.SECURITY, '')}"
        self.importer = CloudResultImporter(
            allowed_paths=allowed_paths,
            audit_directory=audit_directory,
            simulated=gateway.simulated,
        )

    def validate_session(self, config, effective_digest, store, grant, policy) -> None:
        self.approval.validate(
            self.approval.run_id, config.repository, effective_digest, self.gateway.now()
        )
        if (
            self.gateway.store is not store
            or grant != self.grant
            or policy != self.policy
            or policy.safe_test_mode
            or not policy.bootstrap
            or policy.first_release_approved
            or policy.controller_repository != config.repository
            or config.provider != "github"
            or config.auto_merge
            or grant.auto_merge_approved
            or "merge" in grant.capabilities
        ):
            raise PermissionDenied("Cloud pilot must remain repository-bound and manually released")
        for capability in ("read", "develop", "cloud_submit", "cloud_publish"):
            grant.require(config, capability, effective_digest)

    def job(self, context: AgentContext, role: Role, inputs: dict) -> CloudJob:
        _, sealed = context.workspace.instructions(context.config)
        return CloudJob(
            context.run_id,
            context.config.repository,
            sealed,
            context.workspace.head,
            role,
            context.cycle,
            digest(inputs),
        )

    def _result(self, context: AgentContext, role: Role, inputs: dict, schema: str):
        import json

        inputs = {
            "requirement": context.requirement,
            "instructions": context.instructions,
            "project": asdict(context.config),
            "base_sha": context.base_sha,
            **inputs,
        }
        if self.importer.allowed_paths is not None:
            inputs["allowed_source_paths"] = self.importer.allowed_paths
            schema += (
                "\nThe controller permits developer source edits ONLY in allowed_source_paths. "
                "Planning and reviewers may only export the result artifact. "
                "Include the newly created result artifact in the exported task diff. "
                "Do not include it in the source implementation."
            )
        job = self.job(context, role, inputs)
        record = self.gateway.store.cloud_task(job.id)
        if record and record["state"] in ("import_uncertain", "imported"):
            raise TeamError(
                "Interrupted source import requires manual reconciliation; never apply twice"
            )
        self.gateway.submit(
            config=context.config,
            effective_digest=job.config_digest,
            policy=self.policy,
            grant=self.grant,
            role=role,
            branch=job.branch,
            expected_sha=job.head_sha,
            prompt=schema + "\n" + json.dumps(inputs, sort_keys=True),
            approval=self.approval,
            job=job,
        )
        patch = self.gateway.collect(job, self.approval)
        payload, source = self.importer.extract(context.workspace, context.config, job, patch)
        return job, payload, source

    def plan(self, context: AgentContext) -> Planning:
        _, payload, _ = self._result(context, Role.ORCHESTRATOR, {}, PLANNING_SCHEMA)
        fields(payload, {"criteria", "tasks", "architecture"})
        criteria = payload["criteria"]
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= 100:
            raise TeamError("Invalid cloud acceptance plan")
        parsed = []
        for item in criteria:
            fields(item, {"id", "description"})
            parsed.append(Criterion(text_value(item["id"]), text_value(item["description"])))
        if len({c.id for c in parsed}) != len(parsed):
            raise TeamError("Duplicate cloud acceptance criteria")
        arch = payload["architecture"]
        fields(arch, {"summary", "dependencies", "risks"})
        return Planning(
            Plan(tuple(parsed), strings(payload["tasks"], nonempty=True)),
            Architecture(
                text_value(arch["summary"]), strings(arch["dependencies"]), strings(arch["risks"])
            ),
        )

    def develop(self, context, plan, architecture, findings):
        job, payload, source = self._result(
            context,
            Role.DEVELOPER,
            {
                "plan": asdict(plan),
                "architecture": asdict(architecture),
                "findings": [asdict(f) for f in findings],
            },
            DEVELOPMENT_SCHEMA,
        )
        fields(payload, {"summary"})
        text_value(payload["summary"])
        self.gateway.ensure_current(job, self.approval)
        record = self.gateway.store.cloud_task(job.id)
        record["state"] = "import_uncertain"
        self.gateway.store.save_cloud_task(record, "source_import_intent")
        self.importer.apply(context.workspace, job, source)
        record["state"] = "imported"
        self.gateway.store.save_cloud_task(record, "source_imported")

    def _review(self, context, plan, head_sha, role):
        context.workspace.assert_clean(head_sha)
        _, payload, _ = self._result(
            context,
            role,
            {"plan": asdict(plan), "controller_checks": dict(context.checks)},
            REVIEW_SCHEMA,
        )
        fields(payload, {"outcome", "covered_criteria", "findings"})
        try:
            outcome = Outcome(payload["outcome"])
        except (ValueError, TypeError) as exc:
            raise TeamError("Unknown cloud review outcome") from exc
        covered = strings(payload["covered_criteria"])
        raw_findings = payload["findings"]
        if not isinstance(raw_findings, list) or len(raw_findings) > 100:
            raise TeamError("Invalid cloud findings")
        findings = []
        for item in raw_findings:
            fields(item, {"category", "code", "message", "suggestion", "blocking", "repairable"})
            if (
                item["category"] != role.value
                or type(item["blocking"]) is not bool
                or type(item["repairable"]) is not bool
            ):
                raise TeamError("Conflicting review category or finding flags")
            findings.append(
                Finding(
                    FailureClass(item["category"]),
                    text_value(item["code"]),
                    text_value(item["message"]),
                    text_value(item["suggestion"]),
                    item["blocking"],
                    item["repairable"],
                )
            )
        if outcome == Outcome.PASS and (
            any(f.blocking for f in findings) or set(covered) != {c.id for c in plan.criteria}
        ):
            raise TeamError("Contradictory PASS or missing criterion results")
        return Review(outcome, covered, tuple(findings))

    def qa(self, context, plan, head_sha):
        return self._review(context, plan, head_sha, Role.QA)

    def security(self, context, plan, head_sha):
        return self._review(context, plan, head_sha, Role.SECURITY)


class CloudPreviewDelivery:
    """A local handoff preview, with no remote PR, merge or activation side effects."""

    simulated = False

    def __init__(self, workspace, repository):
        self.workspace, self.repository = workspace, repository

    def open_pull_request(self, run_id, head_sha, base_sha, body):
        return PullRequest(0, self.repository, head_sha, base_sha, "", False)

    def snapshot(self, pr):
        return PlatformSnapshot(
            self.repository,
            self.workspace.head,
            pr.base_sha,
            self.workspace.changed_paths(pr.base_sha),
            None,
            None,
            False,
            True,
            time.time(),
            False,
            False,
        )

    def merge(self, pr, expected_sha):
        raise PermissionDenied("Cloud pilot requires manual merge; no merger is connected")
