"""Fail-closed offline preflight for one future synthetic Agents API canary.

This module validates an operator decision document only. It never starts a provider
session, reads credentials, performs I/O, or grants live/merge authority.
"""

from __future__ import annotations

import hashlib
import json
import re

MAX_PAYLOAD_CHARS = 8192
MAX_PAYLOAD_BYTES = 8192
MAX_BUDGET_CENTS = 1_000_000

_SCHEMA = frozenset(
    {
        "schema_version",
        "purpose",
        "provider",
        "api_project_reference",
        "operator_reference",
        "grant_reference",
        "synthetic_data_only",
        "repository_content_allowed",
        "github_write_allowed",
        "subagents_allowed",
        "deployment_allowed",
        "us_data_residency_acknowledged",
        "zero_data_retention_unavailable_acknowledged",
        "separate_api_billing_acknowledged",
        "credential_location",
        "canary_count",
        "project_hard_limit_claim_usd_cents",
        "session_spend_limit_usd_cents",
        "warning_threshold_claim_usd_cents",
        "live_start_authorized",
    }
)
_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}\Z")
_REQUIRED_TRUE = (
    "synthetic_data_only",
    "us_data_residency_acknowledged",
    "zero_data_retention_unavailable_acknowledged",
    "separate_api_billing_acknowledged",
)
_REQUIRED_FALSE = (
    "repository_content_allowed",
    "github_write_allowed",
    "subagents_allowed",
    "deployment_allowed",
    "live_start_authorized",
)


class InvalidCanaryPreflight(ValueError):
    """The offline operator decision is malformed or unsafe."""


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCanaryPreflight("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise InvalidCanaryPreflight("non_standard_json_number")


def _reference(value: object) -> bool:
    if type(value) is not str or _SAFE_REFERENCE.fullmatch(value) is None:
        return False
    lowered = value.lower()
    return not lowered.startswith("sk-") and "bearer " not in lowered


def _budget(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_BUDGET_CENTS


def _blocked(reason: str) -> dict[str, object]:
    return {
        "status": "BLOCKED",
        "reason": reason,
        "decision_digest": None,
        "decision_complete": False,
        "provider_verified": False,
        "billing_verified": False,
        "credentials_verified": False,
        "data_residency_verified": False,
        "remote_stop_verified": False,
        "live_authorized": False,
        "merge_authorized": False,
        "allowed_provider_starts": 0,
    }


def _ready(decision: dict[str, object]) -> dict[str, object]:
    canonical = json.dumps(decision, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "status": "READY_FOR_SEPARATE_LIVE_DECISION",
        "reason": None,
        "decision_digest": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "decision_complete": True,
        "provider_verified": False,
        "billing_verified": False,
        "credentials_verified": False,
        "data_residency_verified": False,
        "remote_stop_verified": False,
        "live_authorized": False,
        "merge_authorized": False,
        "allowed_provider_starts": 0,
    }


def evaluate_canary_preflight(payload: object) -> dict[str, object]:
    """Validate one bounded JSON operator decision without granting live authority."""

    if type(payload) is not str:
        return _blocked("payload_must_be_native_string")
    if len(payload) > MAX_PAYLOAD_CHARS:
        return _blocked("payload_too_large")
    try:
        encoded = payload.encode("utf-8")
    except UnicodeEncodeError:
        return _blocked("payload_not_utf8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        return _blocked("payload_too_large")

    try:
        decision = json.loads(
            payload,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except (InvalidCanaryPreflight, json.JSONDecodeError, ValueError, RecursionError):
        return _blocked("invalid_json")
    if type(decision) is not dict:
        return _blocked("top_level_object_required")
    if set(decision) != _SCHEMA:
        return _blocked("invalid_schema")

    if type(decision["schema_version"]) is not int or decision["schema_version"] != 1:
        return _blocked("unsupported_schema_version")
    if decision["purpose"] != "synthetic_read_only_canary":
        return _blocked("invalid_purpose")
    if decision["provider"] != "openai_agents_api":
        return _blocked("invalid_provider")

    for name in ("api_project_reference", "operator_reference", "grant_reference"):
        if not _reference(decision[name]):
            return _blocked("invalid_reference")

    for name in _REQUIRED_TRUE:
        if type(decision[name]) is not bool or decision[name] is not True:
            return _blocked(f"required_true:{name}")
    for name in _REQUIRED_FALSE:
        if type(decision[name]) is not bool or decision[name] is not False:
            return _blocked(f"required_false:{name}")

    if decision["credential_location"] != "external_controller":
        return _blocked("credential_location_must_be_external_controller")
    if type(decision["canary_count"]) is not int or decision["canary_count"] != 1:
        return _blocked("exactly_one_canary_required")

    project_limit = decision["project_hard_limit_claim_usd_cents"]
    session_limit = decision["session_spend_limit_usd_cents"]
    warning_limit = decision["warning_threshold_claim_usd_cents"]
    if not all(_budget(value) for value in (project_limit, session_limit, warning_limit)):
        return _blocked("invalid_budget")
    if not warning_limit <= session_limit <= project_limit:
        return _blocked("inconsistent_budget_order")

    return _ready(decision)
