"""Exec stage backend for the existing Engine, restricted to local simulations."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..authority import EvidenceAuthority
from ..models import Origin, PermissionDenied, Role, TeamError, digest
from ..roles import ROLE_INSTRUCTIONS
from ..workspace import GitWorkspace
from .cloud_contracts import fields, text_value
from .cloud_results import CloudResultImporter
from .codex_exec import CodexExecGateway, ExecJob
from .structured_agents import DEVELOPMENT_SCHEMA, StructuredAgents


def exec_authority():
    # Simulated output can never become a live review attestation.
    return EvidenceAuthority(
        {
            f"codex-exec-simulated:{role.value}": (role, frozenset({Origin.SIMULATED}))
            for role in (Role.ORCHESTRATOR, Role.DEVELOPER, Role.QA, Role.SECURITY)
        }
        | {"local-check-runner": (Role.QA, frozenset({Origin.LOCAL_EXECUTION}))}
    )


class CodexExecAgents(StructuredAgents):
    simulated = True
    review_origin = Origin.SIMULATED
    orchestrator_identity = "codex-exec-simulated:orchestrator"
    developer_identity = "codex-exec-simulated:developer"
    qa_identity = "codex-exec-simulated:qa"
    security_identity = "codex-exec-simulated:security"

    def __init__(self, gateway: CodexExecGateway, *, allowed_paths: tuple[str, ...]):
        self.gateway = gateway
        if not allowed_paths:
            raise PermissionDenied("Controller-owned source scope is required")
        self.importer = CloudResultImporter(allowed_paths=allowed_paths, simulated=True)

    def validate_session(self, config, effective_digest, store, grant, policy):
        self.gateway.require_simulation()
        if (
            self.gateway.store is not store
            or not policy.safe_test_mode
            or config.provider != "local"
            or config.auto_merge
            or grant.auto_merge_approved
            or "merge" in grant.capabilities
        ):
            raise PermissionDenied("Exec requires local safe mode and manual release")
        for capability in ("read", "develop", "exec_simulate"):
            grant.require(config, capability, effective_digest)

    def _result(self, context, role, inputs, schema):
        context.workspace.assert_clean()
        _, sealed = context.workspace.instructions(context.config)
        inputs = {
            "requirement": context.requirement,
            "instructions": context.instructions,
            "project": asdict(context.config),
            "base_sha": context.base_sha,
            **inputs,
        }
        job = ExecJob(
            context.run_id,
            context.config.repository,
            sealed,
            context.workspace.head,
            role,
            context.cycle,
            digest(inputs),
        )
        # Copies are separate per call, without shared Git objects or host credentials.
        # This is simulation hygiene, NOT an OS write boundary for hostile same-UID code.
        with tempfile.TemporaryDirectory(prefix=f"dt-exec-{role.value}-") as directory:
            checkout = Path(directory) / "checkout"
            context.workspace.git(
                "clone",
                "--quiet",
                "--no-hardlinks",
                "--no-checkout",
                "--",
                str(context.workspace.root),
                str(checkout),
            )
            snapshot = GitWorkspace(checkout)
            snapshot.git("checkout", "--detach", job.head_sha)
            snapshot.assert_clean(job.head_sha)
            instructions = ROLE_INSTRUCTIONS[role]
            if role == Role.ORCHESTRATOR:
                instructions += "\n" + ROLE_INSTRUCTIONS[Role.ARCHITECT]
            prompt = json.dumps(
                {
                    "job": job.envelope(),
                    "inputs": inputs,
                    "instructions": instructions,
                    "schema": schema,
                    "allowed_paths": self.importer.allowed_paths,
                    "transport": "Return envelope payload {patch: unified diff} "
                    "containing .developer-team/cloud-result.json with the "
                    "same envelope and the stage payload. Never edit the checkout.",
                },
                sort_keys=True,
            )
            result = self.gateway.execute(job, checkout, prompt)
            snapshot.assert_clean(job.head_sha)
            context.workspace.assert_clean(job.head_sha)
            fields(result, {"patch"})
            patch = result["patch"]
            if (
                not isinstance(patch, str)
                or not 1 <= len(patch.encode()) <= self.gateway.limits.output_bytes
            ):
                raise TeamError("Missing or oversized exec patch")
            payload, source = self.importer.extract(context.workspace, context.config, job, patch)
        return job, payload, source

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
        # Engine already journals DEVELOPMENT intent. A crash never repeats this import.
        if not source:
            raise TeamError("Exec developer produced no scoped patch")
        self.importer.apply(context.workspace, job, source)
