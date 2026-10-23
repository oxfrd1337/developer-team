"""DT-014 read-only evidence verifier for a future Agents API live canary.

This module validates externally collected, sanitized evidence. It does not contain
a production provider adapter and cannot read credentials, call the network, submit
an Agents API turn, cancel a turn, write a repository, or authorize live execution.
"""

from __future__ import annotations

import argparse
import json
import re
import time

MAX_EVIDENCE_RECORDS = 8
MAX_TTL_SECONDS = 3600
MAX_FUTURE_SKEW_SECONDS = 60

_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_URL = re.compile(r"https://developers\.openai\.com/[A-Za-z0-9/?#._=-]{1,240}\Z")

_GATES = (
    "provider_project_binding",
    "credential_scope",
    "cancel_terminal_contract",
    "billing_controls",
)

_EXPECTED_CLAIMS = {
    "provider_project_binding": "project_binding_observed",
    "credential_scope": "read_only_scope_observed",
    "cancel_terminal_contract": "official_contract_observed",
    "billing_controls": "hard_limit_control_observed",
}

_EXPECTED_SOURCE_KINDS = {
    "provider_project_binding": "account_readonly_observation",
    "credential_scope": "account_readonly_observation",
    "cancel_terminal_contract": "official_documentation",
    "billing_controls": "account_readonly_observation",
}

_EXPECTED_VERIFIERS = {
    "provider_project_binding": "external-readonly-adapter",
    "credential_scope": "external-readonly-adapter",
    "cancel_terminal_contract": "official-docs-readonly-adapter",
    "billing_controls": "external-readonly-adapter",
}

_RECORD_FIELDS = frozenset(
    {
        "gate",
        "source_kind",
        "source_ref",
        "observed_at",
        "expires_at",
        "verifier",
        "claim",
        "project_ref",
    }
)


class InvalidReadOnlyEvidence(ValueError):
    """Evidence is malformed, stale, contradictory, or insufficient."""


def synthetic_reference_evidence(now: int | None = None) -> list[dict]:
    """Return non-secret fixtures for tests and documentation only."""
    observed = int(time.time()) if now is None else now
    expires = observed + 300
    project = "synthetic-test-project"
    return [
        {
            "gate": "provider_project_binding",
            "source_kind": "account_readonly_observation",
            "source_ref": "openai-account:project-settings",
            "observed_at": observed,
            "expires_at": expires,
            "verifier": "external-readonly-adapter",
            "claim": "project_binding_observed",
            "project_ref": project,
        },
        {
            "gate": "credential_scope",
            "source_kind": "account_readonly_observation",
            "source_ref": "openai-account:key-scope-summary",
            "observed_at": observed,
            "expires_at": expires,
            "verifier": "external-readonly-adapter",
            "claim": "read_only_scope_observed",
            "project_ref": project,
        },
        {
            "gate": "cancel_terminal_contract",
            "source_kind": "official_documentation",
            "source_ref": "https://developers.openai.com/api/docs/guides/agents-api/sessions",
            "observed_at": observed,
            "expires_at": expires,
            "verifier": "official-docs-readonly-adapter",
            "claim": "official_contract_observed",
            "project_ref": project,
        },
        {
            "gate": "billing_controls",
            "source_kind": "account_readonly_observation",
            "source_ref": "openai-account:project-spend-limit-summary",
            "observed_at": observed,
            "expires_at": expires,
            "verifier": "external-readonly-adapter",
            "claim": "hard_limit_control_observed",
            "project_ref": project,
        },
    ]


def _safe_ref(value: object) -> bool:
    return type(value) is str and _REF.fullmatch(value) is not None


def _validate_source(record: dict) -> None:
    gate = record["gate"]
    source_kind = record["source_kind"]
    source_ref = record["source_ref"]

    if source_kind != _EXPECTED_SOURCE_KINDS[gate]:
        raise InvalidReadOnlyEvidence("unexpected_source_kind")

    if source_kind == "official_documentation":
        if type(source_ref) is not str or _URL.fullmatch(source_ref) is None:
            raise InvalidReadOnlyEvidence("invalid_official_source")
        return

    if type(source_ref) is not str or not source_ref.startswith("openai-account:"):
        raise InvalidReadOnlyEvidence("invalid_account_source")
    if len(source_ref) > 160 or any(ch.isspace() for ch in source_ref):
        raise InvalidReadOnlyEvidence("invalid_account_source")


def _validate_record(record: object, *, expected_project_ref: str, now: int) -> dict:
    if type(record) is not dict:
        raise InvalidReadOnlyEvidence("invalid_record_object")
    if len(record) > len(_RECORD_FIELDS):
        raise InvalidReadOnlyEvidence("too_many_record_fields")
    for key in record:
        if type(key) is not str:
            raise InvalidReadOnlyEvidence("invalid_record_key_type")
    if set(record) != _RECORD_FIELDS:
        raise InvalidReadOnlyEvidence("missing_or_unexpected_record_fields")

    gate = record["gate"]
    if type(gate) is not str or gate not in _GATES:
        raise InvalidReadOnlyEvidence("unknown_gate")
    if record["claim"] != _EXPECTED_CLAIMS[gate]:
        raise InvalidReadOnlyEvidence("unexpected_claim")
    if record["verifier"] != _EXPECTED_VERIFIERS[gate]:
        raise InvalidReadOnlyEvidence("unexpected_verifier")
    if record["project_ref"] != expected_project_ref:
        raise InvalidReadOnlyEvidence("project_binding_mismatch")

    observed_at = record["observed_at"]
    expires_at = record["expires_at"]
    if type(observed_at) is not int or type(expires_at) is not int:
        raise InvalidReadOnlyEvidence("invalid_evidence_time")
    if observed_at > now + MAX_FUTURE_SKEW_SECONDS:
        raise InvalidReadOnlyEvidence("evidence_from_future")
    if expires_at <= now:
        raise InvalidReadOnlyEvidence("stale_evidence")
    if expires_at <= observed_at or expires_at - observed_at > MAX_TTL_SECONDS:
        raise InvalidReadOnlyEvidence("invalid_evidence_ttl")

    _validate_source(record)
    return record


def evaluate_readonly_evidence(
    evidence: object, *, expected_project_ref: str, now: int | None = None
) -> dict:
    """Validate sanitized external evidence without creating any authority."""
    timestamp = int(time.time()) if now is None else now
    reasons: list[str] = []
    verified: dict[str, bool] = dict.fromkeys(_GATES, False)

    try:
        if not _safe_ref(expected_project_ref):
            raise InvalidReadOnlyEvidence("invalid_expected_project_ref")
        if type(timestamp) is not int or timestamp < 0:
            raise InvalidReadOnlyEvidence("invalid_current_time")
        if type(evidence) is not list or not 1 <= len(evidence) <= MAX_EVIDENCE_RECORDS:
            raise InvalidReadOnlyEvidence("invalid_evidence_count")

        seen: set[str] = set()
        for position, raw in enumerate(evidence):
            try:
                record = _validate_record(
                    raw,
                    expected_project_ref=expected_project_ref,
                    now=timestamp,
                )
                gate = record["gate"]
                if gate in seen:
                    raise InvalidReadOnlyEvidence("duplicate_gate_evidence")
                seen.add(gate)
                verified[gate] = True
            except InvalidReadOnlyEvidence as exc:
                raise InvalidReadOnlyEvidence(f"record_{position}:{exc}") from None

        missing = [gate for gate in _GATES if gate not in seen]
        if missing:
            raise InvalidReadOnlyEvidence("missing_gate_evidence")
    except InvalidReadOnlyEvidence as exc:
        reasons.append(str(exc))

    gate_results = {
        gate: ("READ_ONLY_VERIFIED" if verified[gate] and not reasons else "UNVERIFIED")
        for gate in _GATES
    }
    overall = "READ_ONLY_VERIFIED" if all(verified.values()) and not reasons else "BLOCKED"

    return {
        "schema_version": 1,
        "mode": "dt-014-readonly-evidence-verification",
        "decision": overall,
        "live": "NO-GO",
        "reasons": reasons,
        "gate_results": gate_results,
        "operator_gate": "PENDING_SEPARATE_APPROVAL",
        "provider_verified_for_live": False,
        "credentials_read": False,
        "network_used_by_verifier": False,
        "billing_verified_for_live": False,
        "cancel_verified_for_live": False,
        "live_authorized": False,
        "github_write_authorized": False,
        "repository_write_authorized": False,
        "merge_authorized": False,
        "real_submissions": 0,
        "next_action": (
            "SEPARATE_OPERATOR_DECISION_REQUIRED"
            if overall == "READ_ONLY_VERIFIED"
            else "REPAIR_OR_REFRESH_READ_ONLY_EVIDENCE"
        ),
        "limitations": [
            "sanitized_evidence_validation_only",
            "no_production_provider_adapter",
            "no_secret_or_credential_access",
            "no_live_agents_api_call",
            "no_cancel_or_write_action",
            "read_only_verified_is_not_live_go",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic-reference",
        action="store_true",
        help="evaluate bundled non-secret evidence; still exits with live NO-GO",
    )
    args = parser.parse_args(argv)
    now = int(time.time())
    evidence = synthetic_reference_evidence(now) if args.synthetic_reference else None
    report = evaluate_readonly_evidence(
        evidence,
        expected_project_ref="synthetic-test-project",
        now=now,
    )
    print(json.dumps(report, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
