"""DT-016 controller-owned contracts. None of these values grants live authority.

The external authorization callback and wire transport are trusted dependencies,
not values loaded from a plan, a saved receipt, or the DT-013/014/015 fixtures.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Protocol

PROVIDER_BASE = "https://api.openai.com"
SESSIONS_PATH = "/v1/agents/sessions"
CANARY_MESSAGE = "Using only the synthetic numbers 2 and 2, reply with 4."
CANARY_INSTRUCTIONS = (
    "Answer this single synthetic arithmetic canary. Do not use tools, files, networks, "
    "repositories, credentials, or subagents. Do not change anything."
)
# Local capability names, NOT claimed OpenAI RBAC permission identifiers.
MINIMAL_CAPABILITIES = frozenset(
    {"session:create", "session:read", "message:submit", "turn:read", "cancel:request"}
)
TERMINALS = frozenset(
    {"agent.session.turn.completed", "agent.session.turn.failed", "agent.session.turn.cancelled"}
)
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


class AgentsAPIError(ValueError):
    """Only fixed, non-secret reason codes may cross the adapter boundary."""


def safe_ref(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= 96
        and _REF.fullmatch(value) is not None
        and not any(marker in value.lower() for marker in ("sk-", "sk_", "bearer", "token"))
    )


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def bounded_int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


@dataclass(frozen=True, repr=False)
class CanaryBinding:
    project_id: str
    agent_id: str
    intent_id: str
    idempotency_key: str
    plan_digest: str
    budget_cents: int
    model: str
    provider_base: str = PROVIDER_BASE

    def validate(self) -> None:
        if type(self.provider_base) is not str or self.provider_base != PROVIDER_BASE:
            raise AgentsAPIError("provider_base_mismatch")
        if not all(
            safe_ref(v)
            for v in (self.project_id, self.agent_id, self.intent_id, self.idempotency_key)
        ):
            raise AgentsAPIError("invalid_binding_reference")
        if type(self.plan_digest) is not str or _SHA256.fullmatch(self.plan_digest) is None:
            raise AgentsAPIError("invalid_plan_digest")
        if not bounded_int(self.budget_cents, 1, 100):
            raise AgentsAPIError("invalid_local_budget")
        if (
            type(self.model) is not str
            or not 1 <= len(self.model) <= 96
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.model) is None
            or any(marker in self.model.lower() for marker in ("sk-", "sk_", "bearer", "token"))
        ):
            raise AgentsAPIError("invalid_bound_model")

    @property
    def agent_configuration(self) -> dict:
        # Override every execution/cost-relevant saved-agent field, including nested defaults.
        # A disabled multi-agent response has max_concurrent_subagents=null per the contract.
        return {
            "model": self.model,
            "instructions": CANARY_INSTRUCTIONS,
            "tools": [],
            "multi_agent": {"enabled": False},
            "reasoning": {"effort": "low", "summary": None},
            "service_tier": "default",
            "text": {"format": {"type": "text"}, "verbosity": "low"},
        }

    @property
    def environment_configuration(self) -> dict:
        # This is a new inline sandbox, never an inherited template or prewarmed environment.
        return {
            "type": "openai_hosted",
            "container_size": "small",
            "network": {"access": "disabled", "allowed_domains": []},
            "desktop": {"enabled": False},
            "capability_directories": [],
            "env": {},
            "files": [],
            "packages": {"npm": [], "python": [], "system": []},
            "plugins": [],
            "skills": [],
        }

    @property
    def digest(self) -> str:
        self.validate()
        return sha256(
            {
                **asdict(self),
                "message": CANARY_MESSAGE,
                "agent": self.agent_configuration,
                "environment": self.environment_configuration,
            }
        )


@dataclass(frozen=True)
class AgentsAPILimits:
    timeout_seconds: int = 5
    response_bytes: int = 65536
    event_bytes: int = 8192
    max_records: int = 20
    max_requests: int = 16

    def validate(self) -> None:
        for value, low, high in (
            (self.timeout_seconds, 1, 30),
            (self.response_bytes, 1024, 65536),
            (self.event_bytes, 256, 8192),
            (self.max_records, 1, 20),
            (self.max_requests, 3, 32),
        ):
            if not bounded_int(value, low, high):
                raise AgentsAPIError("invalid_resource_limits")
        if self.event_bytes > self.response_bytes:
            raise AgentsAPIError("invalid_resource_limits")


@dataclass(frozen=True, repr=False)
class ExternalPermit:
    """Sanitized output of an independently trusted account/operator verifier.

    This is not a cryptographic attestation. There is deliberately no JSON loader,
    default verifier, credential resolver, or implementation issuing live permits.
    """

    binding_digest: str
    project_id: str
    credential_project_id: str
    agent_id: str
    key_capabilities: frozenset[str]
    project_capabilities: frozenset[str]
    project_hard_limit_cents: int
    observed_at: int
    expires_at: int
    grant_binding_digest: str
    grant_budget_cents: int
    grant_issued_at: int
    grant_expires_at: int
    create_approved_at: int | None = None
    create_approval_binding_digest: str | None = None
    submit_approved_at: int | None = None
    submit_approval_binding_digest: str | None = None
    cancel_approved_at: int | None = None
    cancel_approval_binding_digest: str | None = None
    provider_base: str = PROVIDER_BASE
    source: str = "controlled-account-readonly-verifier"
    secret_store_verified: bool = False
    spend_controls_verified: bool = False
    contract_verified: bool = False
    agent_configuration_verified: bool = False
    operator_grant_verified: bool = False

    def validate(self, binding: CanaryBinding, operation: str, now: int) -> None:
        if (
            type(self.provider_base) is not str
            or self.provider_base != PROVIDER_BASE
            or type(self.binding_digest) is not str
            or self.binding_digest != binding.digest
            or type(self.project_id) is not str
            or self.project_id != binding.project_id
            or type(self.credential_project_id) is not str
            or self.credential_project_id != binding.project_id
            or type(self.agent_id) is not str
            or self.agent_id != binding.agent_id
        ):
            raise AgentsAPIError("external_project_or_binding_mismatch")
        for capabilities in (self.key_capabilities, self.project_capabilities):
            if (
                type(capabilities) is not frozenset
                or len(capabilities) != len(MINIMAL_CAPABILITIES)
                or any(type(v) is not str for v in capabilities)
                or capabilities != MINIMAL_CAPABILITIES
            ):
                raise AgentsAPIError("minimal_effective_scope_required")
        if (
            type(self.source) is not str
            or self.source != "controlled-account-readonly-verifier"
            or self.secret_store_verified is not True
            or self.contract_verified is not True
            or self.agent_configuration_verified is not True
        ):
            raise AgentsAPIError("external_verification_required")
        if (
            not bounded_int(now, 0, 2**53)
            or not bounded_int(self.observed_at, max(0, now - 3600), now)
            or not bounded_int(self.expires_at, now + 1, self.observed_at + 3600)
        ):
            raise AgentsAPIError("stale_external_verification")
        if operation == "cancel" and (
            type(self.cancel_approval_binding_digest) is not str
            or self.cancel_approval_binding_digest != binding.digest
            or not bounded_int(self.cancel_approved_at, max(0, now - 60), now)
        ):
            raise AgentsAPIError("fresh_cancel_approval_required")
        # Read/stop operations remain available after start-grant expiry or budget exhaustion.
        if operation not in {"create_session", "submit_canary"}:
            return
        if self.spend_controls_verified is not True or not bounded_int(
            self.project_hard_limit_cents, binding.budget_cents, 100
        ):
            raise AgentsAPIError("external_spend_controls_required")
        if (
            self.operator_grant_verified is not True
            or type(self.grant_binding_digest) is not str
            or self.grant_binding_digest != binding.digest
            or not bounded_int(self.grant_budget_cents, binding.budget_cents, 100)
            or not bounded_int(self.grant_issued_at, max(0, now - 3600), now)
            or not bounded_int(self.grant_expires_at, now + 1, self.grant_issued_at + 3600)
        ):
            raise AgentsAPIError("external_single_canary_grant_required")
        if operation == "create_session" and (
            type(self.create_approval_binding_digest) is not str
            or self.create_approval_binding_digest != binding.digest
            or not bounded_int(self.create_approved_at, max(self.grant_issued_at, now - 60), now)
        ):
            raise AgentsAPIError("fresh_first_create_approval_required")
        if operation == "submit_canary" and (
            type(self.submit_approval_binding_digest) is not str
            or self.submit_approval_binding_digest != binding.digest
            or not bounded_int(self.submit_approved_at, max(self.grant_issued_at, now - 60), now)
        ):
            raise AgentsAPIError("fresh_first_submit_approval_required")


class ExternalGate(Protocol):
    def authorize(self, binding: CanaryBinding, operation: str, now: int) -> ExternalPermit: ...


@dataclass(frozen=True, repr=False)
class WireRequest:
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    body: bytes | None
    deadline: float
    max_response_bytes: int


@dataclass(frozen=True, repr=False)
class WireResponse:
    status: int
    body: bytes = b""


class AgentsAPITransport(Protocol):
    """Trusted transport: no redirects/retries; secret injection outside the adapter.

    Enforce request.deadline throughout connect/headers/body and stop reading at
    max_response_bytes. The adapter additionally bounds its own wait and checks
    returned bytes. A timed-out remote mutation can still have taken effect.
    """

    def exchange(self, request: WireRequest) -> WireResponse: ...


@dataclass(frozen=True, repr=False)
class CanaryState:
    binding_digest: str
    idempotency_key: str
    message_digest: str
    limits_digest: str
    phase: str = "PREPARED"
    session_attempts: int = 0
    message_attempts: int = 0
    cancel_attempts: int = 0
    request_count: int = 0
    session_id: str | None = None
    environment_id: str | None = None
    turn_id: str | None = None
    terminal_kind: str | None = None
    consumed_cents: str | None = None
    budget_exceeded: bool = False

    def validate(self, binding: CanaryBinding) -> None:
        if (
            type(self.binding_digest) is not str
            or self.binding_digest != binding.digest
            or type(self.idempotency_key) is not str
            or self.idempotency_key != binding.idempotency_key
            or type(self.message_digest) is not str
            or self.message_digest != sha256(CANARY_MESSAGE)
            or type(self.limits_digest) is not str
            or _SHA256.fullmatch(self.limits_digest) is None
        ):
            raise AgentsAPIError("journal_binding_mismatch")
        phases = {
            "PREPARED",
            "SESSION_UNCERTAIN",
            "SESSION_READY",
            "MESSAGE_UNCERTAIN",
            "MESSAGE_ACCEPTED",
            "TURN_BOUND",
            "CANCEL_UNCERTAIN",
            "CANCEL_REQUESTED",
            "TERMINAL",
        }
        if type(self.phase) is not str or self.phase not in phases:
            raise AgentsAPIError("invalid_journal_state")
        if not all(
            bounded_int(v, 0, 1)
            for v in (self.session_attempts, self.message_attempts, self.cancel_attempts)
        ) or not bounded_int(self.request_count, 0, 32):
            raise AgentsAPIError("invalid_journal_counters")
        for value in (self.session_id, self.environment_id, self.turn_id):
            if value is not None and not safe_ref(value):
                raise AgentsAPIError("invalid_journal_reference")
        if (
            (self.phase == "PREPARED") != (self.session_attempts == 0)
            or (self.phase in {"PREPARED", "SESSION_UNCERTAIN"}) != (self.session_id is None)
            or (self.session_id is None) != (self.environment_id is None)
            or (self.phase in {"PREPARED", "SESSION_UNCERTAIN", "SESSION_READY"})
            != (self.message_attempts == 0)
            or (self.phase in {"TURN_BOUND", "CANCEL_UNCERTAIN", "CANCEL_REQUESTED", "TERMINAL"})
            != (self.turn_id is not None)
            or (
                self.phase in {"CANCEL_UNCERTAIN", "CANCEL_REQUESTED"} and self.cancel_attempts != 1
            )
            or (
                self.cancel_attempts == 1
                and self.phase not in {"CANCEL_UNCERTAIN", "CANCEL_REQUESTED", "TERMINAL"}
            )
            or (self.phase == "TERMINAL") != (self.terminal_kind is not None)
        ):
            raise AgentsAPIError("inconsistent_journal_state")
        if self.terminal_kind is not None and (
            type(self.terminal_kind) is not str or self.terminal_kind not in TERMINALS
        ):
            raise AgentsAPIError("invalid_terminal_kind")
        if type(self.budget_exceeded) is not bool:
            raise AgentsAPIError("invalid_budget_observation")
        if self.consumed_cents is not None:
            if type(self.consumed_cents) is not str or len(self.consumed_cents) > 24:
                raise AgentsAPIError("invalid_budget_observation")
            try:
                amount = Decimal(self.consumed_cents)
            except ArithmeticError:
                raise AgentsAPIError("invalid_budget_observation") from None
            if not amount.is_finite() or not 0 <= amount <= 1_000_000_000:
                raise AgentsAPIError("invalid_budget_observation")


class CanaryJournal(Protocol):
    """One exclusive binding; durable CAS before ANY remote mutation or read."""

    def prepare(self, binding: CanaryBinding, limits: AgentsAPILimits | None = None) -> None: ...

    def load(self, binding: CanaryBinding) -> tuple[int, CanaryState]: ...

    def replace(self, binding: CanaryBinding, revision: int, state: CanaryState) -> None: ...
