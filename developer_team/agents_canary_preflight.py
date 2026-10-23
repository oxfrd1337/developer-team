"""Fail-closed offline preflight for a later, separately approved Agents API canary."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys


MAX_APPROVAL_FIELDS = 24
MAX_APPROVAL_DICT_BYTES = 4096
MAX_APPROVAL_LIFETIME_SECONDS = 3600
MAX_REFERENCE_LENGTH = 128
_SUPPORTED_CPYTHON = {(3, 11), (3, 12), (3, 13)}
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{40}")

_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "approval_id",
        "canary_id",
        "controller_sha",
        "approved_by",
        "provider_path",
        "issued_at_epoch",
        "expires_at_epoch",
        "operator_budget_ceiling_usd_cents",
        "session_spend_limit_usd_cents",
        "project_hard_cap_usd_cents",
        "warning_threshold_usd_cents",
        "project_hard_cap_confirmed",
        "warning_threshold_confirmed",
        "synthetic_only",
        "us_residency_accepted",
        "no_zdr_accepted",
        "read_only",
        "single_session",
        "github_write_allowed",
        "subagents_allowed",
        "deployment_allowed",
        "merge_allowed",
        "credentials_outside_agent",
    }
)


class InvalidCanaryApproval(ValueError):
    """The operator approval cannot satisfy the offline canary preflight contract."""


def _runtime_supported() -> bool:
    return (
        platform.python_implementation() == "CPython"
        and sys.version_info[:2] in _SUPPORTED_CPYTHON
    )


def _bounded_native_dict(value: object) -> dict:
    if type(value) is not dict:
        raise InvalidCanaryApproval("invalid_approval_object")
    if not _runtime_supported():
        raise InvalidCanaryApproval("unsupported_dict_runtime")
    if len(value) > MAX_APPROVAL_FIELDS:
        raise InvalidCanaryApproval("too_many_approval_fields")
    if dict.__sizeof__(value) > MAX_APPROVAL_DICT_BYTES:
        raise InvalidCanaryApproval("approval_dict_too_large")
    for key in value:
        if type(key) is not str:
            raise InvalidCanaryApproval("invalid_approval_key_type")
    if set(value) != _REQUIRED_FIELDS:
        raise InvalidCanaryApproval("missing_or_extra_approval_fields")
    return value


def _reference(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) > MAX_REFERENCE_LENGTH
        or _REF.fullmatch(value) is None
    ):
        raise InvalidCanaryApproval(f"invalid_{label}")
    return value


def _positive_cents(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise InvalidCanaryApproval(f"invalid_{label}")
    return value


def _epoch(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 4_102_444_800:
        raise InvalidCanaryApproval(f"invalid_{label}")
    return value


def _required_bool(approval: dict, name: str, expected: bool) -> None:
    value = approval[name]
    if type(value) is not bool or value is not expected:
        raise InvalidCanaryApproval(f"invalid_{name}")


def _blocked(reason: str) -> dict:
    return {
        "status": "BLOCKED",
        "reason": reason,
        "approval_digest": None,
        "provider_verified": False,
        "billing_verified": False,
        "credentials_verified": False,
        "data_residency_verified": False,
        "remote_stop_verified": False,
        "live_authorized": False,
        "merge_authorized": False,
        "separate_live_approval_required": True,
        "one_use_consumption_required": True,
    }


def evaluate_canary_preflight(
    approval: object,
    *,
    expected_controller_sha: object,
    now_epoch: object,
    controller_max_session_usd_cents: object,
) -> dict:
    """Validate operator claims locally without granting or contacting any provider."""

    try:
        value = _bounded_native_dict(approval)
        if (
            type(expected_controller_sha) is not str
            or _SHA.fullmatch(expected_controller_sha) is None
        ):
            raise InvalidCanaryApproval("invalid_expected_controller_sha")
        if type(now_epoch) is not int or not 0 <= now_epoch <= 4_102_444_800:
            raise InvalidCanaryApproval("invalid_now_epoch")
        controller_max = _positive_cents(
            controller_max_session_usd_cents, "controller_max_session_usd_cents"
        )

        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise InvalidCanaryApproval("invalid_schema_version")
        approval_id = _reference(value["approval_id"], "approval_id")
        canary_id = _reference(value["canary_id"], "canary_id")
        approved_by = _reference(value["approved_by"], "approved_by")
        controller_sha = value["controller_sha"]
        if type(controller_sha) is not str or _SHA.fullmatch(controller_sha) is None:
            raise InvalidCanaryApproval("invalid_controller_sha")
        if controller_sha != expected_controller_sha:
            raise InvalidCanaryApproval("controller_sha_mismatch")
        if (
            type(value["provider_path"]) is not str
            or value["provider_path"] != "agents_api"
        ):
            raise InvalidCanaryApproval("invalid_provider_path")

        issued = _epoch(value["issued_at_epoch"], "issued_at_epoch")
        expires = _epoch(value["expires_at_epoch"], "expires_at_epoch")
        if not issued <= now_epoch <= expires:
            raise InvalidCanaryApproval("approval_not_current")
        if expires <= issued or expires - issued > MAX_APPROVAL_LIFETIME_SECONDS:
            raise InvalidCanaryApproval("approval_lifetime_exceeded")

        operator_ceiling = _positive_cents(
            value["operator_budget_ceiling_usd_cents"],
            "operator_budget_ceiling_usd_cents",
        )
        session_limit = _positive_cents(
            value["session_spend_limit_usd_cents"], "session_spend_limit_usd_cents"
        )
        project_cap = _positive_cents(
            value["project_hard_cap_usd_cents"], "project_hard_cap_usd_cents"
        )
        warning = _positive_cents(
            value["warning_threshold_usd_cents"], "warning_threshold_usd_cents"
        )
        if session_limit > operator_ceiling:
            raise InvalidCanaryApproval("session_limit_exceeds_operator_ceiling")
        if session_limit > controller_max:
            raise InvalidCanaryApproval("session_limit_exceeds_controller_ceiling")
        if session_limit > project_cap:
            raise InvalidCanaryApproval("session_limit_exceeds_project_cap")
        if warning > project_cap:
            raise InvalidCanaryApproval("warning_threshold_exceeds_project_cap")

        for name in (
            "project_hard_cap_confirmed",
            "warning_threshold_confirmed",
            "synthetic_only",
            "us_residency_accepted",
            "no_zdr_accepted",
            "read_only",
            "single_session",
            "credentials_outside_agent",
        ):
            _required_bool(value, name, True)
        for name in (
            "github_write_allowed",
            "subagents_allowed",
            "deployment_allowed",
            "merge_allowed",
        ):
            _required_bool(value, name, False)

        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        binding = {
            "approval": canonical,
            "expected_controller_sha": expected_controller_sha,
            "controller_max_session_usd_cents": controller_max,
        }
        approval_digest = hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()
        return {
            "status": "OFFLINE_PREFLIGHT_PASS",
            "reason": None,
            "approval_digest": approval_digest,
            "approval_id": approval_id,
            "canary_id": canary_id,
            "approved_by": approved_by,
            "controller_sha": controller_sha,
            "provider_path_claimed": "agents_api",
            "session_spend_limit_usd_cents_claimed": session_limit,
            "operator_budget_ceiling_usd_cents_claimed": operator_ceiling,
            "project_hard_cap_usd_cents_claimed": project_cap,
            "warning_threshold_usd_cents_claimed": warning,
            "provider_verified": False,
            "billing_verified": False,
            "credentials_verified": False,
            "data_residency_verified": False,
            "remote_stop_verified": False,
            "live_authorized": False,
            "merge_authorized": False,
            "separate_live_approval_required": True,
            "one_use_consumption_required": True,
        }
    except InvalidCanaryApproval as exc:
        return _blocked(str(exc))
