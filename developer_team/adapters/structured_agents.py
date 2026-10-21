"""Shared strict payload parsing for stage backends; no scheduling or execution."""

from __future__ import annotations

from dataclasses import asdict

from ..models import (
    Architecture,
    Criterion,
    FailureClass,
    Finding,
    Outcome,
    Plan,
    Planning,
    Review,
    Role,
    TeamError,
)
from .base import AgentContext
from .cloud_contracts import fields, strings, text_value

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


class StructuredAgents:
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
