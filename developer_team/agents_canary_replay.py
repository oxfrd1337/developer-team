"""Offline-only replay of normalized synthetic Agents API canary lifecycle claims.

No provider client, credentials, filesystem, shell, socket or approval capability.
Input data is untrusted, and even a complete trace is not remote attestation.
"""

from __future__ import annotations

import re

MAX_EVENTS = 64
MAX_AMOUNT_CENTS = 1_000_000_000
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_FIELDS = {
    "intent_recorded": frozenset({"type", "intent_id", "idempotency_key"}),
    "submit_attempted": frozenset({"type", "intent_id", "idempotency_key"}),
    "submission_uncertain": frozenset({"type", "intent_id", "idempotency_key"}),
    "session_receipt": frozenset({"type", "session_id", "turn_id"}),
    "cancel_requested": frozenset({"type", "session_id", "turn_id"}),
    "agent.session.idle": frozenset({"type", "session_id", "turn_id"}),
    "agent.session.turn.completed": frozenset({"type", "session_id", "turn_id"}),
    "agent.session.turn.failed": frozenset({"type", "session_id", "turn_id"}),
    "agent.session.turn.cancelled": frozenset({"type", "session_id", "turn_id"}),
    "usage_observed": frozenset({"type", "session_id", "turn_id", "amount_usd_cents"}),
}
MAX_EVENT_FIELDS = max(len(fields) for fields in _FIELDS.values())
MAX_EVENT_KIND_LENGTH = max(map(len, _FIELDS))
_TERMINAL = frozenset(
    {
        "agent.session.turn.completed",
        "agent.session.turn.failed",
        "agent.session.turn.cancelled",
    }
)


class InvalidCanaryTrace(ValueError):
    """A locally supplied event trace is malformed or inconsistent."""


def _reference(value: object) -> bool:
    return type(value) is str and _REF.fullmatch(value) is not None


def _event(value: object) -> dict:
    if type(value) is not dict:
        raise InvalidCanaryTrace("invalid_event_object")
    if len(value) > MAX_EVENT_FIELDS:
        raise InvalidCanaryTrace("too_many_event_fields")
    # Native dict iteration does not hash or compare keys; reject custom keys first.
    for key in value:
        if type(key) is not str:
            raise InvalidCanaryTrace("invalid_event_key_type")
    kind = value.get("type")
    if type(kind) is not str or len(kind) > MAX_EVENT_KIND_LENGTH or kind not in _FIELDS:
        raise InvalidCanaryTrace("unsupported_event_kind")
    if set(value) != _FIELDS[kind]:
        raise InvalidCanaryTrace("missing_or_extra_event_fields")
    for key, field in value.items():
        if key == "type":
            continue
        if key == "amount_usd_cents":
            if type(field) is not int or not 0 <= field <= MAX_AMOUNT_CENTS:
                raise InvalidCanaryTrace("invalid_usage_amount")
        elif not _reference(field):
            raise InvalidCanaryTrace("invalid_reference")
    return value


def replay_canary_trace(
    events: object, *, expected_intent_id: str, expected_idempotency_key: str
) -> dict:
    """Audit bounded synthetic claims, never attest or authorize a real turn.

    These events are a deliberately reduced local normalization contract, not
    raw webhook/API wire objects. A future adapter must independently verify
    provider identities, raw signatures and persistence before normalization.
    """
    reasons: list[str] = []
    stage = "empty"
    session_id: str | None = None
    turn_id: str | None = None
    terminal_kind: str | None = None
    submit_attempts = 0
    unknown_submit = False
    cancel_requested = False
    usage_seen = False

    try:
        if not _reference(expected_intent_id) or not _reference(expected_idempotency_key):
            raise InvalidCanaryTrace("invalid_operator_pins")
        if type(events) is not list or not 1 <= len(events) <= MAX_EVENTS:
            raise InvalidCanaryTrace("invalid_event_count")

        for position, raw in enumerate(events):
            try:
                event = _event(raw)
                kind = event["type"]
                if kind in {"intent_recorded", "submit_attempted", "submission_uncertain"}:
                    if (
                        event["intent_id"] != expected_intent_id
                        or event["idempotency_key"] != expected_idempotency_key
                    ):
                        raise InvalidCanaryTrace("unexpected_operator_binding")
                else:
                    if kind == "session_receipt":
                        if stage not in {"submitted", "uncertain"}:
                            raise InvalidCanaryTrace("receipt_out_of_order")
                        session_id = event["session_id"]
                        turn_id = event["turn_id"]
                        stage = "session"
                        continue
                    if event["session_id"] != session_id or event["turn_id"] != turn_id:
                        raise InvalidCanaryTrace("unexpected_session_or_turn")

                if kind == "intent_recorded":
                    if stage != "empty":
                        raise InvalidCanaryTrace("duplicate_or_late_intent")
                    stage = "intent"
                elif kind == "submit_attempted":
                    if stage != "intent":
                        raise InvalidCanaryTrace("multiple_or_unjournaled_submit")
                    submit_attempts += 1
                    stage = "submitted"
                elif kind == "submission_uncertain":
                    if stage != "submitted":
                        raise InvalidCanaryTrace("uncertain_without_submit")
                    unknown_submit = True
                    stage = "uncertain"
                elif kind == "cancel_requested":
                    if stage not in {"session", "idle"} or cancel_requested:
                        raise InvalidCanaryTrace("invalid_cancel_order")
                    cancel_requested = True
                    stage = "cancel"
                elif kind == "agent.session.idle":
                    if stage not in {"session", "idle", "cancel", "terminal", "usage"}:
                        raise InvalidCanaryTrace("invalid_idle_order")
                    # Idle may follow a terminal event; it never replaces that evidence.
                    if stage in {"session", "idle"}:
                        stage = "idle"
                elif kind in _TERMINAL:
                    if stage not in {"session", "idle", "cancel"}:
                        raise InvalidCanaryTrace("invalid_terminal_order")
                    terminal_kind = kind
                    stage = "terminal"
                elif kind == "usage_observed":
                    if stage != "terminal" or usage_seen:
                        raise InvalidCanaryTrace("invalid_usage_order")
                    usage_seen = True
                    stage = "usage"
                else:
                    raise InvalidCanaryTrace("unhandled_event_kind")
            except InvalidCanaryTrace as exc:
                raise InvalidCanaryTrace(f"event_{position}:{exc}") from None

        if stage == "empty":
            raise InvalidCanaryTrace("missing_intent")
    except InvalidCanaryTrace as exc:
        reasons.append(str(exc))

    if reasons:
        status = "BLOCKED"
    elif terminal_kind is None:
        status = "INCOMPLETE"
    else:
        status = "SYNTHETIC_TERMINAL_OBSERVED"

    return {
        "status": status,
        "reasons": reasons,
        "submit_attempts_observed": submit_attempts,
        "uncertain_submission_claimed": unknown_submit,
        "cancel_requested_claimed": cancel_requested,
        "cancelled_terminal_claimed": terminal_kind == "agent.session.turn.cancelled",
        "terminal_kind_claimed": terminal_kind,
        "usage_claim_seen": usage_seen,
        "provider_verified": False,
        "cancel_verified": False,
        "billing_verified": False,
        "live_authorized": False,
        "merge_authorized": False,
        "next_action": (
            "STOP_AND_RECONCILE_EXTERNALLY"
            if reasons or (unknown_submit and terminal_kind is None)
            else "EXTERNAL_VERIFICATION_REQUIRED"
        ),
        "limitations": [
            "normalized_synthetic_claims_only",
            "no_provider_session_or_identity_attestation",
            "no_remote_cancel_acknowledgement",
            "no_real_cost_cap_or_billing_attestation",
            "no_durable_controller_or_runstore_integration",
        ],
    }
