"""DT-016 bounded Agents API wire adapter; default-disabled, no credential access.

No HTTP client is installed or constructed implicitly. A separately reviewed
controller must supply an external authorization gate, a durable exclusive journal,
and a deadline/size-enforcing transport. This module does not issue live approval.
Session creation, one fixed message, read-only reconciliation and cancel are separate.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import asdict, replace
from decimal import Decimal

from .agents_api_contracts import (
    CANARY_MESSAGE,
    PROVIDER_BASE,
    SESSIONS_PATH,
    AgentsAPIError,
    AgentsAPILimits,
    AgentsAPITransport,
    CanaryBinding,
    CanaryJournal,
    CanaryState,
    ExternalGate,
    ExternalPermit,
    WireRequest,
    WireResponse,
    bounded_int,
    canonical,
    safe_ref,
    sha256,
)


def _json(raw: bytes) -> dict:
    def invalid_constant(_):
        raise ValueError

    def pairs(items):
        if len(items) > 64:
            raise ValueError
        result = {}
        for key, value in items:
            if key in result or len(key) > 128:
                raise ValueError
            result[key] = value
        return result

    value = None
    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_float=Decimal,
            parse_constant=invalid_constant,
        )
    except (ValueError, RecursionError, ArithmeticError, UnicodeError):
        value = None
    if type(value) is not dict:
        raise AgentsAPIError("invalid_provider_json")
    return value


def _report(state: CanaryState) -> dict:
    # Never expose provider text, IDs, keys, metadata, headers, or gate evidence.
    return {
        "mode": "dt-016-bounded-provider-adapter",
        "phase": state.phase,
        "session_create_attempts": state.session_attempts,
        "logical_message_attempts": state.message_attempts,
        "cancel_requested": state.cancel_attempts == 1,
        "request_count": state.request_count,
        "terminal_kind": state.terminal_kind,
        "consumed_usd_cents_best_effort": state.consumed_cents,
        "budget_exceeded": state.budget_exceeded,
        "live": "NO-GO",
        "live_authorized": False,
        "github_write_authorized": False,
        "repository_write_authorized": False,
        "merge_authorized": False,
        "next_action": "EXTERNAL_RECONCILIATION_AND_SEPARATE_OPERATOR_DECISION",
    }


def _matches_configuration(actual: object, expected: object) -> bool:
    """Compare native JSON shapes strictly, including false versus 0 and missing versus null."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(
            _matches_configuration(actual[key], value) for key, value in expected.items()
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _matches_configuration(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


class AgentsAPIAdapter:
    def __init__(
        self,
        binding: CanaryBinding,
        journal: CanaryJournal,
        *,
        transport: AgentsAPITransport | None = None,
        gate: ExternalGate | None = None,
        limits: AgentsAPILimits | None = None,
        now=time.time,
        monotonic=time.monotonic,
    ):
        if type(binding) is not CanaryBinding:
            raise AgentsAPIError("invalid_binding")
        binding.validate()
        limits = AgentsAPILimits() if limits is None else limits
        if type(limits) is not AgentsAPILimits:
            raise AgentsAPIError("invalid_resource_limits")
        limits.validate()
        self._binding, self._journal = binding, journal
        self._transport, self._gate, self._limits = transport, gate, limits
        self._now, self._monotonic = now, monotonic

    def _authorize(self, operation: str) -> None:
        if self._transport is None or self._gate is None:
            raise AgentsAPIError("provider_adapter_disabled")
        permit = None
        try:
            now = int(self._now())
            permit = self._gate.authorize(self._binding, operation, now)
            now = int(self._now())  # A slow verifier must not validate against its old start time.
        except Exception:
            permit = None
        if type(permit) is not ExternalPermit:
            raise AgentsAPIError("external_authorization_required")
        permit.validate(self._binding, operation, now)

    def _load(self) -> tuple[int, CanaryState]:
        result = None
        try:
            result = self._journal.load(self._binding)
        except Exception:
            result = None
        if (
            type(result) is not tuple
            or len(result) != 2
            or not bounded_int(result[0], 0, 1000)
            or type(result[1]) is not CanaryState
        ):
            raise AgentsAPIError("journal_unavailable_or_invalid")
        result[1].validate(self._binding)
        if result[1].limits_digest != sha256(asdict(self._limits)):
            raise AgentsAPIError("journal_resource_limits_mismatch")
        return result

    def _commit(self, revision: int, state: CanaryState) -> tuple[int, CanaryState]:
        state.validate(self._binding)
        committed = False
        try:
            self._journal.replace(self._binding, revision, state)
            committed = True
        except Exception:
            committed = False
        if not committed:
            raise AgentsAPIError("journal_commit_failed")
        return revision + 1, state

    def _request(
        self,
        revision: int,
        state: CanaryState,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        message_key: bool = False,
        expected_status: int = 200,
    ) -> tuple[int, CanaryState, WireResponse]:
        if state.request_count >= self._limits.max_requests:
            raise AgentsAPIError("request_budget_exhausted")
        revision, state = self._commit(
            revision, replace(state, request_count=state.request_count + 1)
        )
        headers = (
            ("OpenAI-Beta", "agents=v1"),
            ("OpenAI-Project", self._binding.project_id),
            ("Content-Type", "application/json"),
        )
        if message_key:
            headers += (("Idempotency-Key", state.idempotency_key),)
        if method == "POST":
            # Final check AFTER durable writes: journal delays must not extend an approval.
            # Cancel has its own fresh approval, independent of expired start grants.
            # Every POST re-enters the external gate.
            operation = "submit_canary" if message_key else (
                "create_session" if path == SESSIONS_PATH else "cancel"
            )
            self._authorize(operation)
        started = self._monotonic()
        request = WireRequest(
            method,
            PROVIDER_BASE + path,
            headers,
            None if body is None else canonical(body),
            started + self._limits.timeout_seconds,
            self._limits.response_bytes,
        )
        results = queue.Queue(maxsize=1)
        transport = self._transport

        def exchange():
            response = None
            try:
                response = transport.exchange(request)
            except BaseException:
                # Never retain/chain a transport exception or print its message.
                response = None
            results.put(response)

        # Bound the caller's wait even if an injected transport fails its deadline.
        # Daemon execution is not a remote cancellation or a sandbox for transport code.
        launched = False
        try:
            threading.Thread(target=exchange, daemon=True).start()
            launched = True
        except Exception:
            launched = False
        if not launched:
            raise AgentsAPIError("transport_worker_unavailable")
        response = None
        timed_out = False
        try:
            response = results.get(timeout=self._limits.timeout_seconds)
        except queue.Empty:
            timed_out = True
        if timed_out or self._monotonic() >= request.deadline:
            raise AgentsAPIError("transport_timeout_reconcile_required")
        if type(response) is not WireResponse:
            raise AgentsAPIError("transport_failed_reconcile_required")
        if type(response.body) is not bytes or len(response.body) > request.max_response_bytes:
            raise AgentsAPIError("provider_response_size_exceeded")
        if type(response.status) is not int or response.status != expected_status:
            reason = {
                401: "provider_unauthorized",
                403: "provider_forbidden",
                429: "provider_rate_or_spend_limited",
            }.get(response.status if type(response.status) is int else 0, "provider_http_refused")
            raise AgentsAPIError(reason)
        return revision, state, response

    @property
    def _metadata(self) -> dict:
        return {"dt016_binding": self._binding.digest}

    def _record(self, value: object) -> dict:
        if (
            type(value) is not dict
            or len(json.dumps(value, default=str).encode()) > self._limits.event_bytes
        ):
            raise AgentsAPIError("provider_event_size_exceeded")
        return value

    def _page(self, raw: bytes) -> list[dict]:
        value = _json(raw)
        records = value.get("data")
        if value.get("object") != "list" or value.get("has_more") is not False:
            raise AgentsAPIError("incomplete_reconciliation_page")
        if type(records) is not list or len(records) > self._limits.max_records:
            raise AgentsAPIError("provider_record_limit_exceeded")
        return [self._record(record) for record in records]

    def _session(self, value: dict, state: CanaryState) -> tuple[str, str, str, bool]:
        self._record(value)
        identifier, agent = value.get("id"), value.get("agent")
        environment = value.get("environment")
        status = value.get("status")
        if (
            value.get("object") != "agent.session"
            or not safe_ref(identifier)
            or (state.session_id is not None and identifier != state.session_id)
            or value.get("metadata") != self._metadata
            or value.get("project_id", self._binding.project_id) != self._binding.project_id
            or type(agent) is not dict
            or agent.get("id") != self._binding.agent_id
            or value.get("vault_ids") != []
            or type(status) is not str
            or status not in {"idle", "in_progress", "requires_action", "failed"}
        ):
            raise AgentsAPIError("provider_session_binding_mismatch")
        expected_agent = self._binding.agent_configuration
        expected_agent["multi_agent"]["max_concurrent_subagents"] = None
        if (
            set(agent) - {"id", "name"} != set(expected_agent)
            or not _matches_configuration(
                {key: agent[key] for key in expected_agent}, expected_agent
            )
        ):
            raise AgentsAPIError("provider_effective_agent_mismatch")
        expected_environment = self._binding.environment_configuration
        del expected_environment["env"]  # The public response omits environment-variable values.
        if (
            type(environment) is not dict
            or not safe_ref(environment.get("id"))
            or (
                state.environment_id is not None
                and environment["id"] != state.environment_id
            )
            or set(environment) - {"id"} != set(expected_environment)
            or not _matches_configuration(
                {key: environment[key] for key in expected_environment}, expected_environment
            )
        ):
            raise AgentsAPIError("provider_effective_environment_mismatch")
        spend = value.get("spend_control")
        if (
            type(spend) is not dict
            or type(spend.get("limit")) is not int
            or spend["limit"] != self._binding.budget_cents
        ):
            raise AgentsAPIError("provider_spend_control_mismatch")
        consumed = spend.get("consumed")
        if (
            type(consumed) not in {int, Decimal}
            or not Decimal(consumed).is_finite()
            or not 0 <= consumed <= 1_000_000_000
        ):
            raise AgentsAPIError("invalid_provider_spend_observation")
        return (
            identifier, environment["id"], str(consumed), consumed > self._binding.budget_cents
        )

    def _read_session(self, revision: int, state: CanaryState) -> tuple[int, CanaryState, dict]:
        revision, state, response = self._request(
            revision, state, "GET", f"{SESSIONS_PATH}/{state.session_id}"
        )
        value = _json(response.body)
        _, _, consumed, exceeded = self._session(value, state)
        revision, state = self._commit(
            revision,
            replace(
                state, consumed_cents=consumed, budget_exceeded=state.budget_exceeded or exceeded
            ),
        )
        return revision, state, value

    def _read_turns(
        self, revision: int, state: CanaryState, session_id: str
    ) -> tuple[int, CanaryState, list[dict]]:
        revision, state, response = self._request(
            revision,
            state,
            "GET",
            f"{SESSIONS_PATH}/{session_id}/turns?limit={self._limits.max_records}&order=asc",
        )
        turns = self._page(response.body)
        if len(turns) > 1 or (turns and state.message_attempts == 0):
            raise AgentsAPIError("unexpected_or_multiple_turns")
        return revision, state, turns

    def create_session(self) -> dict:
        self._authorize("create_session")
        revision, state = self._load()
        if state.phase != "PREPARED":
            raise AgentsAPIError("session_create_already_attempted")
        revision, state = self._commit(
            revision, replace(state, phase="SESSION_UNCERTAIN", session_attempts=1)
        )
        revision, state, response = self._request(
            revision,
            state,
            "POST",
            SESSIONS_PATH,
            {
                "agent_id": self._binding.agent_id,
                "agent": self._binding.agent_configuration,
                "environment": self._binding.environment_configuration,
                "metadata": self._metadata,
                "spend_control": {"limit": self._binding.budget_cents},
                "stream": False,
            },
            expected_status=201,
        )
        value = _json(response.body)
        identifier, environment_id, consumed, exceeded = self._session(value, state)
        if value.get("status") != "idle" or value.get("required_actions") != []:
            raise AgentsAPIError("session_not_empty_and_idle")
        _, state = self._commit(
            revision,
            replace(
                state,
                phase="SESSION_READY",
                session_id=identifier,
                environment_id=environment_id,
                consumed_cents=consumed,
                budget_exceeded=exceeded,
            ),
        )
        return _report(state)

    def submit_canary(self) -> dict:
        self._authorize("submit_canary")
        revision, state = self._load()
        if state.phase != "SESSION_READY" or state.message_attempts != 0:
            raise AgentsAPIError("message_submit_already_attempted_or_out_of_order")
        revision, state, session = self._read_session(revision, state)
        revision, state, _ = self._read_turns(revision, state, state.session_id)
        if (
            session.get("status") != "idle"
            or session.get("required_actions") != []
            or state.budget_exceeded
            or Decimal(state.consumed_cents) >= self._binding.budget_cents
        ):
            raise AgentsAPIError("session_not_empty_idle_or_within_budget")
        # Recheck immediately before reserving the first logical message.
        self._authorize("submit_canary")
        revision, state = self._commit(
            revision, replace(state, phase="MESSAGE_UNCERTAIN", message_attempts=1)
        )
        revision, state, _ = self._request(
            revision,
            state,
            "POST",
            f"{SESSIONS_PATH}/{state.session_id}/events",
            {
                "events": [
                    {
                        "type": "agent.session.input.message",
                        "input": [
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": CANARY_MESSAGE}],
                            }
                        ],
                    }
                ]
            },
            message_key=True,
            expected_status=202,
        )
        _, state = self._commit(revision, replace(state, phase="MESSAGE_ACCEPTED"))
        return _report(state)

    def _reconcile_turn(self, revision: int, state: CanaryState) -> tuple[int, CanaryState]:
        revision, state, _ = self._read_session(revision, state)
        revision, state, turns = self._read_turns(revision, state, state.session_id)
        if not turns:
            if state.turn_id is not None:
                raise AgentsAPIError("previous_turn_missing")
            return revision, state
        turn = turns[0]
        identifier, status = turn.get("id"), turn.get("status")
        if (
            turn.get("object") != "agent.session.turn"
            or not safe_ref(identifier)
            or turn.get("session_id") != state.session_id
            or turn.get("agent_id") != self._binding.agent_id
            or turn.get("subagent_id") is not None
            or (state.turn_id is not None and identifier != state.turn_id)
            or type(status) is not str
            or status
            not in {"queued", "in_progress", "waiting", "completed", "failed", "cancelled"}
        ):
            raise AgentsAPIError("provider_turn_binding_mismatch")
        terminal = (
            f"agent.session.turn.{status}"
            if status in {"completed", "failed", "cancelled"}
            else None
        )
        if state.terminal_kind is not None and terminal != state.terminal_kind:
            raise AgentsAPIError("conflicting_or_regressed_terminal")
        phase = "TERMINAL" if terminal else (state.phase if state.cancel_attempts else "TURN_BOUND")
        return self._commit(
            revision, replace(state, turn_id=identifier, terminal_kind=terminal, phase=phase)
        )

    def reconcile(self) -> dict:
        self._authorize("reconcile")
        revision, state = self._load()
        if state.phase == "PREPARED":
            raise AgentsAPIError("no_session_attempt_to_reconcile")
        if state.session_id is None:
            revision, state, response = self._request(
                revision,
                state,
                "GET",
                f"{SESSIONS_PATH}?limit={self._limits.max_records}&order=desc",
            )
            candidates = [
                record
                for record in self._page(response.body)
                if record.get("metadata") == self._metadata
            ]
            if len(candidates) != 1:
                raise AgentsAPIError("session_reconstruction_requires_operator")
            identifier, environment_id, consumed, exceeded = self._session(candidates[0], state)
            if candidates[0].get("status") != "idle" or candidates[0].get("required_actions") != []:
                raise AgentsAPIError("session_not_empty_and_idle")
            revision, state, _ = self._read_turns(revision, state, identifier)
            _, state = self._commit(
                revision,
                replace(
                    state,
                    session_id=identifier,
                    environment_id=environment_id,
                    phase="SESSION_READY",
                    consumed_cents=consumed,
                    budget_exceeded=exceeded,
                ),
            )
        else:
            _, state = self._reconcile_turn(revision, state)
        return _report(state)

    def cancel(self) -> dict:
        self._authorize("cancel")
        revision, state = self._load()
        if state.phase != "TURN_BOUND" or state.cancel_attempts != 0:
            raise AgentsAPIError("cancel_out_of_order_or_already_attempted")
        revision, state = self._reconcile_turn(revision, state)
        if state.terminal_kind is not None:
            raise AgentsAPIError("turn_already_terminal")
        revision, state = self._commit(
            revision, replace(state, phase="CANCEL_UNCERTAIN", cancel_attempts=1)
        )
        revision, state, _ = self._request(
            revision,
            state,
            "POST",
            f"{SESSIONS_PATH}/{state.session_id}/events",
            {"events": [{"type": "agent.session.input.cancel"}]},
            expected_status=202,
        )
        _, state = self._commit(revision, replace(state, phase="CANCEL_REQUESTED"))
        return _report(state)

    def report(self) -> dict:
        return _report(self._load()[1])
