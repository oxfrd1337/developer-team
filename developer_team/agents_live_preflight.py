"""DT-013 offline-only structural preflight for a future Agents API canary.

The module validates an operator-authored plan without reading credentials,
environment variables, files, provider state or the network. A passing offline
report never authorizes a live call, repository write, merge or spend.
"""

from __future__ import annotations

import argparse
import json
import re

MAX_PLAN_FIELDS = 19
MAX_AMOUNT_CENTS = 1_000_000_000
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_EXPECTED_FIELDS = frozenset(
    {
        "schema_version",
        "purpose",
        "api_project_ref",
        "credential_source",
        "credential_material_present",
        "synthetic_data_only",
        "sensitive_data_allowed",
        "data_residency",
        "zero_data_retention",
        "max_submissions",
        "max_parallel_runs",
        "github_write_allowed",
        "repository_write_allowed",
        "automatic_merge",
        "per_canary_budget_cents",
        "project_hard_limit_cents",
        "provider_identity_verification",
        "provider_cancel_verification",
        "billing_limit_verification",
    }
)

_EXTERNAL_GATES = (
    "provider_identity_and_project_binding",
    "credential_scope_and_secret_store",
    "provider_cancel_and_terminal_reconciliation",
    "provider_billing_limit_and_usage_observation",
    "operator_single_live_start_approval",
)


class InvalidLiveCanaryPlan(ValueError):
    """The local structural plan is missing, malformed or unsafe."""


def synthetic_reference_plan() -> dict:
    """Return a non-secret fixture for offline tests and documentation only."""
    return {
        "schema_version": 1,
        "purpose": "single-synthetic-readonly-canary",
        "api_project_ref": "synthetic-test-project",
        "credential_source": "external-secret-store",
        "credential_material_present": False,
        "synthetic_data_only": True,
        "sensitive_data_allowed": False,
        "data_residency": "us",
        "zero_data_retention": False,
        "max_submissions": 1,
        "max_parallel_runs": 1,
        "github_write_allowed": False,
        "repository_write_allowed": False,
        "automatic_merge": False,
        "per_canary_budget_cents": 1,
        "project_hard_limit_cents": 1,
        "provider_identity_verification": "required-before-live",
        "provider_cancel_verification": "required-before-live",
        "billing_limit_verification": "required-before-live",
    }


def _native_bool(value: object, expected: bool, reason: str) -> None:
    if type(value) is not bool or value is not expected:
        raise InvalidLiveCanaryPlan(reason)


def _positive_cents(value: object, reason: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_AMOUNT_CENTS:
        raise InvalidLiveCanaryPlan(reason)
    return value


def _validate(plan: object) -> None:
    if type(plan) is not dict:
        raise InvalidLiveCanaryPlan("invalid_plan_object")
    if len(plan) > MAX_PLAN_FIELDS:
        raise InvalidLiveCanaryPlan("too_many_plan_fields")
    for key in plan:
        if type(key) is not str:
            raise InvalidLiveCanaryPlan("invalid_plan_key_type")
    if set(plan) != _EXPECTED_FIELDS:
        raise InvalidLiveCanaryPlan("missing_or_unexpected_fields")

    if type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
        raise InvalidLiveCanaryPlan("unsupported_schema_version")
    if plan["purpose"] != "single-synthetic-readonly-canary":
        raise InvalidLiveCanaryPlan("unsafe_or_unknown_purpose")
    if type(plan["api_project_ref"]) is not str or _REF.fullmatch(plan["api_project_ref"]) is None:
        raise InvalidLiveCanaryPlan("invalid_api_project_reference")
    if plan["credential_source"] != "external-secret-store":
        raise InvalidLiveCanaryPlan("unsafe_credential_source")

    _native_bool(plan["credential_material_present"], False, "credential_material_must_be_absent")
    _native_bool(plan["synthetic_data_only"], True, "synthetic_data_required")
    _native_bool(plan["sensitive_data_allowed"], False, "sensitive_data_must_be_forbidden")
    if plan["data_residency"] != "us":
        raise InvalidLiveCanaryPlan("unexpected_data_residency")
    _native_bool(plan["zero_data_retention"], False, "zero_data_retention_not_assumed")

    if type(plan["max_submissions"]) is not int or plan["max_submissions"] != 1:
        raise InvalidLiveCanaryPlan("single_submission_required")
    if type(plan["max_parallel_runs"]) is not int or plan["max_parallel_runs"] != 1:
        raise InvalidLiveCanaryPlan("single_parallel_run_required")
    _native_bool(plan["github_write_allowed"], False, "github_write_must_be_forbidden")
    _native_bool(plan["repository_write_allowed"], False, "repository_write_must_be_forbidden")
    _native_bool(plan["automatic_merge"], False, "automatic_merge_must_be_forbidden")

    per_canary = _positive_cents(plan["per_canary_budget_cents"], "invalid_canary_budget")
    hard_limit = _positive_cents(plan["project_hard_limit_cents"], "invalid_project_hard_limit")
    if per_canary > hard_limit:
        raise InvalidLiveCanaryPlan("canary_budget_exceeds_project_limit")

    for field in (
        "provider_identity_verification",
        "provider_cancel_verification",
        "billing_limit_verification",
    ):
        if plan[field] != "required-before-live":
            raise InvalidLiveCanaryPlan("external_verification_must_remain_pending")


def evaluate_agents_live_preflight(plan: object) -> dict:
    """Return a sanitized offline report. It never returns live authorization."""
    reasons: list[str] = []
    try:
        _validate(plan)
    except InvalidLiveCanaryPlan as exc:
        reasons.append(str(exc))

    offline_status = "PASS" if not reasons else "BLOCKED"
    return {
        "schema_version": 1,
        "mode": "dt-013-offline-agents-canary-preflight",
        "offline_preflight": offline_status,
        "live": "NO-GO",
        "reasons": reasons,
        "network_used": False,
        "credentials_read": False,
        "provider_verified": False,
        "billing_verified": False,
        "cancel_verified": False,
        "live_authorized": False,
        "github_write_authorized": False,
        "merge_authorized": False,
        "real_submissions": 0,
        "external_gates": list(_EXTERNAL_GATES),
        "next_action": (
            "MANUAL_EXTERNAL_VERIFICATION_AND_SEPARATE_APPROVAL_REQUIRED"
            if not reasons
            else "FIX_PLAN_AND_RERUN_OFFLINE"
        ),
        "limitations": [
            "structural_plan_validation_only",
            "no_provider_or_project_attestation",
            "no_secret_store_or_credential_attestation",
            "no_network_or_api_call",
            "no_billing_or_hard_limit_attestation",
            "no_remote_cancel_attestation",
            "offline_pass_is_not_live_go",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic-reference",
        action="store_true",
        help="evaluate the bundled non-secret reference plan; still exits NO-GO",
    )
    args = parser.parse_args(argv)
    plan = synthetic_reference_plan() if args.synthetic_reference else None
    print(json.dumps(evaluate_agents_live_preflight(plan), indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
