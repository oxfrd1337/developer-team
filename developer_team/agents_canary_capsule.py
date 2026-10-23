"""DT-015 persistable dry-run capsule for exactly one future Agents API canary.

The state machine models intent, a structurally checked operator gate, one synthetic
submit attempt, reconciliation, terminal state and observed usage. It has no provider
adapter and cannot perform a real submission, cancellation, GitHub write or merge.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import time

MAX_AMOUNT_CENTS = 1_000_000_000
MAX_GRANT_TTL_SECONDS = 3600
MAX_FUTURE_SKEW_SECONDS = 60
MAX_JOURNAL_ENTRIES = 16

_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")

_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "intent_id",
        "idempotency_key",
        "project_ref",
        "plan_digest",
        "budget_cents",
        "created_at",
        "grant",
        "stage",
        "submit_attempts",
        "submission_uncertain",
        "session_id",
        "turn_id",
        "cancel_requested",
        "terminal_kind",
        "usage_cents",
        "real_submissions",
        "live_authorized",
        "github_write_authorized",
        "repository_write_authorized",
        "merge_authorized",
        "journal",
    }
)

_GRANT_FIELDS = frozenset(
    {
        "grant_id",
        "intent_id",
        "project_ref",
        "max_budget_cents",
        "issued_at",
        "expires_at",
        "mode",
        "source",
    }
)

_JOURNAL_FIELDS = frozenset({"event", "at"})

_TERMINALS = frozenset(
    {
        "agent.session.turn.completed",
        "agent.session.turn.failed",
        "agent.session.turn.cancelled",
    }
)

_STAGES = frozenset(
    {
        "PREPARED",
        "GRANT_RECORDED",
        "SYNTHETIC_SUBMIT_RECORDED",
        "SUBMISSION_UNCERTAIN",
        "SESSION_BOUND",
        "CANCEL_REQUESTED",
        "TERMINAL_OBSERVED",
        "USAGE_OBSERVED",
    }
)


class InvalidCanaryCapsule(ValueError):
    """Capsule state, transition, grant or binding is invalid."""


def _safe_ref(value: object) -> bool:
    return type(value) is str and _REF.fullmatch(value) is not None


def _positive_cents(value: object, reason: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_AMOUNT_CENTS:
        raise InvalidCanaryCapsule(reason)
    return value


def _timestamp(value: object, reason: str) -> int:
    if type(value) is not int or value < 0:
        raise InvalidCanaryCapsule(reason)
    return value


def _journal_entry(event: str, at: int) -> dict:
    return {"event": event, "at": at}


def _validate_journal(journal: object) -> None:
    if type(journal) is not list or not 1 <= len(journal) <= MAX_JOURNAL_ENTRIES:
        raise InvalidCanaryCapsule("invalid_journal")
    for entry in journal:
        if type(entry) is not dict or set(entry) != _JOURNAL_FIELDS:
            raise InvalidCanaryCapsule("invalid_journal_entry")
        if not _safe_ref(entry["event"]):
            raise InvalidCanaryCapsule("invalid_journal_event")
        _timestamp(entry["at"], "invalid_journal_time")


def _validate_grant(grant: object, state: dict, now: int) -> dict:
    if type(grant) is not dict:
        raise InvalidCanaryCapsule("invalid_grant_object")
    if len(grant) > len(_GRANT_FIELDS):
        raise InvalidCanaryCapsule("too_many_grant_fields")
    for key in grant:
        if type(key) is not str:
            raise InvalidCanaryCapsule("invalid_grant_key_type")
    if set(grant) != _GRANT_FIELDS:
        raise InvalidCanaryCapsule("missing_or_unexpected_grant_fields")

    if not _safe_ref(grant["grant_id"]):
        raise InvalidCanaryCapsule("invalid_grant_id")
    if grant["intent_id"] != state["intent_id"]:
        raise InvalidCanaryCapsule("grant_intent_mismatch")
    if grant["project_ref"] != state["project_ref"]:
        raise InvalidCanaryCapsule("grant_project_mismatch")
    if grant["mode"] != "single-canary-preauthorization":
        raise InvalidCanaryCapsule("invalid_grant_mode")
    if grant["source"] != "external-operator-gate":
        raise InvalidCanaryCapsule("invalid_grant_source")

    issued_at = _timestamp(grant["issued_at"], "invalid_grant_issue_time")
    expires_at = _timestamp(grant["expires_at"], "invalid_grant_expiry")
    if issued_at > now + MAX_FUTURE_SKEW_SECONDS:
        raise InvalidCanaryCapsule("grant_from_future")
    if expires_at <= now:
        raise InvalidCanaryCapsule("expired_grant")
    if expires_at <= issued_at or expires_at - issued_at > MAX_GRANT_TTL_SECONDS:
        raise InvalidCanaryCapsule("invalid_grant_ttl")

    max_budget = _positive_cents(grant["max_budget_cents"], "invalid_grant_budget")
    if state["budget_cents"] > max_budget:
        raise InvalidCanaryCapsule("capsule_budget_exceeds_grant")
    return grant


def validate_capsule(state: object) -> dict:
    """Validate a persisted V0.1 state without granting authority."""
    if type(state) is not dict:
        raise InvalidCanaryCapsule("invalid_state_object")
    if len(state) > len(_STATE_FIELDS):
        raise InvalidCanaryCapsule("too_many_state_fields")
    for key in state:
        if type(key) is not str:
            raise InvalidCanaryCapsule("invalid_state_key_type")
    if set(state) != _STATE_FIELDS:
        raise InvalidCanaryCapsule("missing_or_unexpected_state_fields")

    if type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise InvalidCanaryCapsule("unsupported_schema_version")
    for field in ("intent_id", "idempotency_key", "project_ref"):
        if not _safe_ref(state[field]):
            raise InvalidCanaryCapsule(f"invalid_{field}")
    if type(state["plan_digest"]) is not str or _DIGEST.fullmatch(state["plan_digest"]) is None:
        raise InvalidCanaryCapsule("invalid_plan_digest")
    _positive_cents(state["budget_cents"], "invalid_budget")
    _timestamp(state["created_at"], "invalid_created_at")

    if state["stage"] not in _STAGES:
        raise InvalidCanaryCapsule("invalid_stage")
    if type(state["submit_attempts"]) is not int or state["submit_attempts"] not in {0, 1}:
        raise InvalidCanaryCapsule("invalid_submit_attempt_count")
    if type(state["submission_uncertain"]) is not bool:
        raise InvalidCanaryCapsule("invalid_submission_uncertain")
    if type(state["cancel_requested"]) is not bool:
        raise InvalidCanaryCapsule("invalid_cancel_requested")
    if state["session_id"] is not None and not _safe_ref(state["session_id"]):
        raise InvalidCanaryCapsule("invalid_session_id")
    if state["turn_id"] is not None and not _safe_ref(state["turn_id"]):
        raise InvalidCanaryCapsule("invalid_turn_id")
    if (state["session_id"] is None) != (state["turn_id"] is None):
        raise InvalidCanaryCapsule("partial_session_binding")
    if state["terminal_kind"] is not None and state["terminal_kind"] not in _TERMINALS:
        raise InvalidCanaryCapsule("invalid_terminal_kind")
    if type(state["usage_cents"]) is not int or not 0 <= state["usage_cents"] <= MAX_AMOUNT_CENTS:
        raise InvalidCanaryCapsule("invalid_usage")

    if state["real_submissions"] != 0:
        raise InvalidCanaryCapsule("real_submission_not_allowed")
    for field in (
        "live_authorized",
        "github_write_authorized",
        "repository_write_authorized",
        "merge_authorized",
    ):
        if state[field] is not False:
            raise InvalidCanaryCapsule("authority_flag_must_remain_false")

    if state["grant"] is not None and type(state["grant"]) is not dict:
        raise InvalidCanaryCapsule("invalid_persisted_grant")
    _validate_journal(state["journal"])
    return state


def prepare_capsule(
    *,
    intent_id: str,
    idempotency_key: str,
    project_ref: str,
    plan_digest: str,
    budget_cents: int,
    created_at: int,
) -> dict:
    """Create a JSON-serializable dry-run capsule with no live authority."""
    state = {
        "schema_version": 1,
        "intent_id": intent_id,
        "idempotency_key": idempotency_key,
        "project_ref": project_ref,
        "plan_digest": plan_digest,
        "budget_cents": budget_cents,
        "created_at": created_at,
        "grant": None,
        "stage": "PREPARED",
        "submit_attempts": 0,
        "submission_uncertain": False,
        "session_id": None,
        "turn_id": None,
        "cancel_requested": False,
        "terminal_kind": None,
        "usage_cents": 0,
        "real_submissions": 0,
        "live_authorized": False,
        "github_write_authorized": False,
        "repository_write_authorized": False,
        "merge_authorized": False,
        "journal": [_journal_entry("prepared", created_at)],
    }
    return validate_capsule(state)


def _copy_for_transition(state: object) -> dict:
    validate_capsule(state)
    return copy.deepcopy(state)


def record_structural_grant(state: object, grant: object, *, now: int) -> dict:
    """Record a bounded grant claim; it is not cryptographic or live authority."""
    current = _copy_for_transition(state)
    _timestamp(now, "invalid_current_time")
    if current["stage"] != "PREPARED" or current["grant"] is not None:
        raise InvalidCanaryCapsule("grant_already_recorded_or_out_of_order")
    current["grant"] = copy.deepcopy(_validate_grant(grant, current, now))
    current["stage"] = "GRANT_RECORDED"
    current["journal"].append(_journal_entry("grant_recorded", now))
    return validate_capsule(current)


def record_synthetic_submit_attempt(state: object, *, now: int) -> dict:
    """Record one dry-run attempt; no provider call exists in this module."""
    current = _copy_for_transition(state)
    _timestamp(now, "invalid_current_time")
    if current["stage"] != "GRANT_RECORDED":
        raise InvalidCanaryCapsule("synthetic_submit_out_of_order")
    if current["submit_attempts"] != 0:
        raise InvalidCanaryCapsule("second_submit_forbidden")
    if current["grant"] is None:
        raise InvalidCanaryCapsule("missing_grant")
    _validate_grant(current["grant"], current, now)
    current["submit_attempts"] = 1
    current["stage"] = "SYNTHETIC_SUBMIT_RECORDED"
    current["journal"].append(_journal_entry("synthetic_submit_recorded", now))
    return validate_capsule(current)


def mark_submission_uncertain(state: object, *, now: int) -> dict:
    current = _copy_for_transition(state)
    _timestamp(now, "invalid_current_time")
    if current["stage"] != "SYNTHETIC_SUBMIT_RECORDED":
        raise InvalidCanaryCapsule("uncertain_out_of_order")
    current["submission_uncertain"] = True
    current["stage"] = "SUBMISSION_UNCERTAIN"
    current["journal"].append(_journal_entry("submission_uncertain", now))
    return validate_capsule(current)


def bind_synthetic_session(
    state: object,
    *,
    session_id: str,
    turn_id: str,
    now: int,
) -> dict:
    current = _copy_for_transition(state)
    _timestamp(now, "invalid_current_time")
    if current["stage"] not in {"SYNTHETIC_SUBMIT_RECORDED", "SUBMISSION_UNCERTAIN"}:
        raise InvalidCanaryCapsule("session_binding_out_of_order")
    if not _safe_ref(session_id) or not _safe_ref(turn_id):
        raise InvalidCanaryCapsule("invalid_session_binding")
    current["session_id"] = session_id
    current["turn_id"] = turn_id
    current["stage"] = "SESSION_BOUND"
    current["journal"].append(_journal_entry("session_bound", now))
    return validate_capsule(current)


def request_synthetic_cancel(state: object, *, now: int) -> dict:
    current = _copy_for_transition(state)
    _timestamp(now, "invalid_current_time")
    if current["stage"] != "SESSION_BOUND" or current["cancel_requested"]:
        raise InvalidCanaryCapsule("cancel_out_of_order")
    current["cancel_requested"] = True
    current["stage"] = "CANCEL_REQUESTED"
    current["journal"].append(_journal_entry("cancel_requested", now))
    return validate_capsule(current)


def observe_synthetic_terminal(state: object, *, terminal_kind: str, now: int) -> dict:
    current = _copy_for_transition(state)
    _timestamp(now, "invalid_current_time")
    if current["stage"] not in {"SESSION_BOUND", "CANCEL_REQUESTED"}:
        raise InvalidCanaryCapsule("terminal_out_of_order")
    if terminal_kind not in _TERMINALS:
        raise InvalidCanaryCapsule("invalid_terminal_kind")
    current["terminal_kind"] = terminal_kind
    current["stage"] = "TERMINAL_OBSERVED"
    current["journal"].append(_journal_entry("terminal_observed", now))
    return validate_capsule(current)


def observe_synthetic_usage(state: object, *, usage_cents: int, now: int) -> dict:
    current = _copy_for_transition(state)
    _timestamp(now, "invalid_current_time")
    if current["stage"] != "TERMINAL_OBSERVED":
        raise InvalidCanaryCapsule("usage_out_of_order")
    if type(usage_cents) is not int or not 0 <= usage_cents <= MAX_AMOUNT_CENTS:
        raise InvalidCanaryCapsule("invalid_usage")
    if usage_cents > current["budget_cents"]:
        raise InvalidCanaryCapsule("usage_exceeds_local_budget")
    current["usage_cents"] = usage_cents
    current["stage"] = "USAGE_OBSERVED"
    current["journal"].append(_journal_entry("usage_observed", now))
    return validate_capsule(current)


def capsule_report(state: object) -> dict:
    current = validate_capsule(state)
    return {
        "schema_version": 1,
        "mode": "dt-015-single-canary-dry-run-capsule",
        "stage": current["stage"],
        "submit_attempts": current["submit_attempts"],
        "submission_uncertain": current["submission_uncertain"],
        "cancel_requested": current["cancel_requested"],
        "terminal_kind": current["terminal_kind"],
        "usage_cents": current["usage_cents"],
        "budget_cents": current["budget_cents"],
        "operator_gate": (
            "STRUCTURALLY_RECORDED_NOT_AUTHORITY"
            if current["grant"] is not None
            else "MISSING"
        ),
        "live": "NO-GO",
        "provider_adapter_present": False,
        "provider_verified": False,
        "billing_verified": False,
        "cancel_verified": False,
        "real_submissions": 0,
        "live_authorized": False,
        "github_write_authorized": False,
        "repository_write_authorized": False,
        "merge_authorized": False,
        "next_action": "SEPARATE_DT016_AND_EXPLICIT_OPERATOR_APPROVAL_REQUIRED",
        "limitations": [
            "dry_run_state_machine_only",
            "operator_grant_is_structural_not_cryptographic",
            "no_provider_adapter",
            "no_real_submit_or_cancel",
            "local_budget_is_not_provider_hard_limit",
            "dry_run_pass_is_not_live_go",
        ],
    }


def synthetic_reference_capsule(now: int | None = None) -> dict:
    timestamp = int(time.time()) if now is None else now
    state = prepare_capsule(
        intent_id="synthetic-dt015-intent",
        idempotency_key="synthetic-dt015-key",
        project_ref="synthetic-test-project",
        plan_digest="a" * 64,
        budget_cents=5,
        created_at=timestamp,
    )
    grant = {
        "grant_id": "synthetic-dt015-grant",
        "intent_id": state["intent_id"],
        "project_ref": state["project_ref"],
        "max_budget_cents": 5,
        "issued_at": timestamp,
        "expires_at": timestamp + 300,
        "mode": "single-canary-preauthorization",
        "source": "external-operator-gate",
    }
    state = record_structural_grant(state, grant, now=timestamp)
    state = record_synthetic_submit_attempt(state, now=timestamp)
    state = bind_synthetic_session(
        state,
        session_id="synthetic-session",
        turn_id="synthetic-turn",
        now=timestamp,
    )
    state = observe_synthetic_terminal(
        state,
        terminal_kind="agent.session.turn.completed",
        now=timestamp,
    )
    return observe_synthetic_usage(state, usage_cents=1, now=timestamp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic-reference",
        action="store_true",
        help="run the bundled dry-run capsule; live remains NO-GO",
    )
    args = parser.parse_args(argv)
    if args.synthetic_reference:
        report = capsule_report(synthetic_reference_capsule())
    else:
        report = {
            "mode": "dt-015-single-canary-dry-run-capsule",
            "stage": "NOT_PREPARED",
            "live": "NO-GO",
            "live_authorized": False,
            "real_submissions": 0,
        }
    print(json.dumps(report, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
