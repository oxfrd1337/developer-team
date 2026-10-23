"""DT-017 controlled acceptance, with independent read-only and operator boundaries.

No credential lookup, guessed account API endpoints, CLI activation or default broker.
Collectors normalize official account/dashboard observations; they are trusted code,
not JSON receipts or an attestation supplied by the agent being tested.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass

from .adapters.agents_api import AgentsAPIAdapter
from .adapters.agents_api_contracts import (
    MINIMAL_CAPABILITIES,
    AgentsAPIError,
    AgentsAPILimits,
    CanaryBinding,
    ExternalPermit,
    WireResponse,
    bounded_int,
    safe_ref,
    sha256,
)
from .adapters.agents_api_journal import SQLiteCanaryJournal
from .adapters.agents_https import HardenedHTTPS

ACCOUNT_CHECKS = (
    "provider_contract_current",
    "account_project_binding",
    "credential_scope",
    "spend_controls",
    "secret_store",
    "agent_configuration",
    "environment_configuration",
    "single_canary_grant",
)
CHECKS = ACCOUNT_CHECKS[:-1] + ("real_transport", "durable_journal", ACCOUNT_CHECKS[-1])
APPROVALS = {"create_session": "fresh_create_approval", "submit_canary": "fresh_submit_approval"}


@dataclass(frozen=True, repr=False)
class Observation:
    check: str
    binding_digest: str
    observed_at: int
    expires_at: int
    source: str
    verifier_ref: str
    facts: dict


def _facts_match(check, facts, b):
    """Strict normalized schemas; never copy input values into diagnostics."""
    if type(facts) is not dict:
        return False
    expected = {
        "provider_contract_current": {
            "contract": "dt016-agents-v1",
            "origin": "https://developers.openai.com",
            "session_creation_billable": True,
            "spend_enforcement_delayed": True,
        },
        "account_project_binding": {
            "project_id": b.project_id,
            "credential_project_id": b.project_id,
        },
        "credential_scope": {
            "key_capabilities": sorted(MINIMAL_CAPABILITIES),
            "principal_capabilities": sorted(MINIMAL_CAPABILITIES),
            "effective_capabilities": sorted(MINIMAL_CAPABILITIES),
            "additional_permissions": [],
        },
        "spend_controls": {"project_limit_cents": b.budget_cents, "enforcement_delayed": True},
        "secret_store": {
            "external": True,
            "readable": True,
            "excluded_from_chat_git_prompts_logs": True,
        },
        "agent_configuration": {
            "agent_id": b.agent_id,
            "model": b.model,
            "model_available": True,
            "model_approved": True,
            "configuration_digest": sha256(b.agent_configuration),
        },
        "environment_configuration": {
            "configuration_digest": sha256(b.environment_configuration),
            "network": "disabled",
            "container_size": "small",
        },
        "single_canary_grant": {
            "binding_digest": b.digest,
            "budget_cents": b.budget_cents,
            "max_sessions": 1,
            "max_messages": 1,
            "exclusive_external_ownership": True,
        },
    }[check]
    if check == "account_project_binding":
        for key in ("service_account_ref", "credential_ref"):
            if not safe_ref(facts.get(key)):
                return False
            expected[key] = facts[key]
    if check == "single_canary_grant":
        if not safe_ref(facts.get("grant_ref")):
            return False
        expected["grant_ref"] = facts["grant_ref"]
    # canonical digest comparison includes JSON types (False is not 0).
    return sha256(facts) == sha256(expected)


class ReadOnlyVerifier:
    """Injected collector.read(binding, check) performs only controlled observations.

    RBAC names above are local normalizations, never invented provider permissions.
    Dashboard/admin evidence may require a separate read-only account identity;
    never broaden the canary credential to obtain it. No default network collector.
    """

    def __init__(self, collector=None):
        self._collector = collector

    def inspect(self, binding, now):
        binding.validate()
        checks, observations = {}, {}
        for check in ACCOUNT_CHECKS:
            observation = None
            try:
                observation = self._collector.read(binding, check)
                valid = (
                    type(observation) is Observation
                    and observation.check == check
                    and observation.binding_digest == binding.digest
                    and safe_ref(observation.verifier_ref)
                    and observation.source
                    == (
                        "official_documentation"
                        if check == "provider_contract_current"
                        else "controlled_account_readonly"
                    )
                    and bounded_int(now, 0, 2**53)
                    and bounded_int(observation.observed_at, max(0, now - 300), now)
                    and bounded_int(observation.expires_at, now + 1, observation.observed_at + 300)
                    and _facts_match(check, observation.facts, binding)
                )
            except Exception:
                valid = False
            checks[check] = "PASS" if valid else "MISSING_OR_INVALID"
            if valid:
                observations[check] = observation
        return checks, observations


@dataclass(frozen=True, repr=False)
class OperatorApproval:
    binding_digest: str
    operation: str
    challenge: str
    session_digest: str
    issued_at: int
    expires_at: int
    broker_verified: bool = False


class AcceptanceController:
    """One durable controller slot, no automatic approval and no implicit POST.

    review() always halts. A trusted operator broker must independently confirm the
    returned unpredictable challenge AFTER review. A saved report grants nothing.
    submit review is possible only after session/configuration readback, and uses
    a new session-bound challenge. execute() never falls through into another step.
    """

    def __init__(
        self,
        binding: CanaryBinding,
        connection: sqlite3.Connection,
        *,
        collector=None,
        secret_store=None,
        operator_broker=None,
        connection_factory=None,
        limits=None,
        now=time.time,
    ):
        binding.validate()
        self._binding, self._connection, self._now = binding, connection, now
        self._secret_store = secret_store
        self._verifier, self._broker = ReadOnlyVerifier(collector), operator_broker
        self._limits = limits or AgentsAPILimits()
        self._journal = SQLiteCanaryJournal(connection)
        self._transport = HardenedHTTPS(
            binding,
            secret_store,
            mutation_gate=self._wire_gate,
            connection_factory=connection_factory,
        )
        self._adapter = AgentsAPIAdapter(
            binding,
            self._journal,
            transport=self._transport,
            gate=self,
            limits=self._limits,
            now=now,
        )
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS dt017_control ("
                "slot INTEGER PRIMARY KEY CHECK(slot=1), binding TEXT NOT NULL, "
                "challenge TEXT, operation TEXT, reviewed_at INTEGER, session_digest TEXT, "
                "cleanup_requested INTEGER NOT NULL DEFAULT 0 CHECK(cleanup_requested IN (0,1)))"
            )
            connection.commit()
        except sqlite3.Error:
            raise AgentsAPIError("acceptance_journal_unavailable") from None

    def prepare(self):
        """Explicit trusted provisioning only; never repair/recreate a lost intent."""
        self._journal.prepare(self._binding, self._limits)
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO dt017_control(slot,binding) VALUES(1,?)", (self._binding.digest,)
                )
        except sqlite3.Error:
            raise AgentsAPIError("acceptance_slot_already_bound_or_unavailable") from None

    def _slot(self):
        try:
            row = self._connection.execute(
                "SELECT binding,challenge,operation,reviewed_at,session_digest,cleanup_requested "
                "FROM dt017_control WHERE slot=1"
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is None or row[0] != self._binding.digest:
            raise AgentsAPIError("acceptance_slot_missing_or_mismatched")
        return row

    def _durable(self):
        try:
            self._slot()
            self._journal.load(self._binding)
            databases = self._connection.execute("PRAGMA database_list").fetchall()
            return (
                any(row[1] == "main" and row[2] for row in databases)
                and self._connection.execute("PRAGMA synchronous").fetchone()[0] == 2
                and self._connection.execute("PRAGMA journal_mode").fetchone()[0]
                in {"delete", "wal"}
            )
        except Exception:
            return False

    def _inspect(self):
        now = int(self._now())
        checks, observations = self._verifier.inspect(self._binding, now)
        # Recheck freshness after a slow collector, never against its start time.
        after = int(self._now())
        for check, observation in observations.items():
            if after >= observation.expires_at or after - observation.observed_at > 300:
                checks[check] = "MISSING_OR_INVALID"
        # Validate the actual external handle without returning its header or opening a socket.
        secret_ready = False
        try:
            secret_ready = self._secret_store.with_authorization(
                self._binding.project_id, lambda _: WireResponse(204)
            ) == WireResponse(204)
        except Exception:
            secret_ready = False
        if not secret_ready:
            checks["secret_store"] = "MISSING_OR_INVALID"  # noqa: S105 - gate status, no secret
        checks["real_transport"] = "PASS" if type(self._transport) is HardenedHTTPS else "MISSING"
        checks["durable_journal"] = "PASS" if self._durable() else "MISSING"
        return checks, observations, after

    def report(self):
        checks, _, _ = self._inspect()
        return {
            "mode": "dt017-pre-live-acceptance",
            "checks": {
                **{name: checks[name] for name in CHECKS},
                "fresh_create_approval": "MISSING",
                "fresh_submit_approval": "MISSING",
            },
            "live": "NO-GO",
            "live_authorized": False,
            "operator_halt": "SEPARATE_FRESH_APPROVAL_REQUIRED_BEFORE_EACH_POST",
            "validation": "OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.",
        }

    def review(self, operation="create_session"):
        if operation not in {*APPROVALS, "cancel"}:
            raise AgentsAPIError("invalid_review_operation")
        _, state = self._journal.load(self._binding)
        expected = {
            "create_session": "PREPARED",
            "submit_canary": "SESSION_READY",
            "cancel": "TURN_BOUND",
        }
        if state.phase != expected[operation]:
            raise AgentsAPIError("review_out_of_order")
        # Reads before issuing the separate submit challenge verify effective config.
        if operation != "create_session":
            self._adapter.reconcile()
            _, state = self._journal.load(self._binding)
            if state.phase != expected[operation]:
                raise AgentsAPIError("review_state_changed")
        checks, _, now = self._inspect()
        required = set(CHECKS)
        if operation == "cancel":
            required -= {"spend_controls", "single_canary_grant"}
        if any(checks[key] != "PASS" for key in required):
            raise AgentsAPIError("pre_live_acceptance_blocked")
        challenge, session_digest = secrets.token_hex(32), sha256(state.session_id)
        self._slot()
        try:
            with self._connection:
                self._connection.execute(
                    "UPDATE dt017_control SET challenge=?,operation=?,reviewed_at=?,"
                    "session_digest=? "
                    "WHERE slot=1 AND binding=?",
                    (challenge, operation, now, session_digest, self._binding.digest),
                )
        except sqlite3.Error:
            raise AgentsAPIError("review_commit_failed") from None
        return {**self.report(), "challenge": challenge, "operation": operation}

    def _approval(self, operation, now):
        slot = self._slot()
        if slot[2] != operation or type(slot[1]) is not str or len(slot[1]) != 64:
            raise AgentsAPIError("fresh_operator_approval_required")
        _, state = self._journal.load(self._binding)
        if slot[4] != sha256(state.session_id):
            raise AgentsAPIError("approval_session_mismatch")
        approval = None
        try:
            approval = self._broker.read_approval(self._binding, operation, slot[1])
        except Exception:
            approval = None
        if (
            type(approval) is not OperatorApproval
            or approval.broker_verified is not True
            or approval.binding_digest != self._binding.digest
            or approval.operation != operation
            or approval.challenge != slot[1]
            or approval.session_digest != slot[4]
            or not bounded_int(slot[3], max(0, now - 60), now)
            or not bounded_int(approval.issued_at, slot[3], now)
            or not bounded_int(approval.expires_at, now + 1, approval.issued_at + 60)
        ):
            raise AgentsAPIError("fresh_operator_approval_required")
        return approval

    def authorize(self, binding, operation, now):
        if type(binding) is not CanaryBinding or binding != self._binding:
            raise AgentsAPIError("controller_binding_mismatch")
        if operation not in {*APPROVALS, "cancel", "reconcile"}:
            raise AgentsAPIError("invalid_controller_operation")
        checks, observations, after = self._inspect()
        required = set(CHECKS)
        if operation in {"reconcile", "cancel"}:
            required -= {"spend_controls", "single_canary_grant"}
        if any(checks[key] != "PASS" for key in required):
            raise AgentsAPIError("pre_live_acceptance_blocked")
        approval = self._approval(operation, after) if operation != "reconcile" else None
        b = self._binding
        earliest = min(o.observed_at for key, o in observations.items() if key in required)
        expiry = min(o.expires_at for key, o in observations.items() if key in required)
        grant = observations.get("single_canary_grant")
        permit = ExternalPermit(
            binding_digest=b.digest,
            project_id=b.project_id,
            credential_project_id=b.project_id,
            agent_id=b.agent_id,
            key_capabilities=MINIMAL_CAPABILITIES,
            project_capabilities=MINIMAL_CAPABILITIES,
            project_hard_limit_cents=b.budget_cents,
            observed_at=earliest,
            expires_at=expiry,
            grant_binding_digest=b.digest,
            grant_budget_cents=b.budget_cents,
            grant_issued_at=grant.observed_at if grant else 0,
            grant_expires_at=grant.expires_at if grant else 0,
            secret_store_verified=True,
            spend_controls_verified=checks["spend_controls"] == "PASS",
            contract_verified=True,
            agent_configuration_verified=True,
            operator_grant_verified=checks["single_canary_grant"] == "PASS",
            **(
                {
                    {"create_session": "create", "submit_canary": "submit", "cancel": "cancel"}[
                        operation
                    ]
                    + "_approved_at": approval.issued_at,
                    {"create_session": "create", "submit_canary": "submit", "cancel": "cancel"}[
                        operation
                    ]
                    + "_approval_binding_digest": b.digest,
                }
                if approval
                else {}
            ),
        )
        permit.validate(b, operation, int(self._now()))
        return permit

    def _wire_gate(self, binding, operation, path):
        self.authorize(binding, operation, int(self._now()))
        _, state = self._journal.load(binding)
        if (
            operation != "create_session"
            and path != f"/v1/agents/sessions/{state.session_id}/events"
        ):
            raise AgentsAPIError("wire_session_binding_mismatch")

    def execute(self, operation):
        if operation not in {*APPROVALS, "cancel"}:
            raise AgentsAPIError("invalid_controller_operation")
        try:
            return getattr(self._adapter, operation)()
        finally:
            # No reuse of a review/approval, including failed and uncertain attempts.
            try:
                with self._connection:
                    self._connection.execute(
                        "UPDATE dt017_control SET challenge=NULL,operation=NULL,reviewed_at=NULL,"
                        "session_digest=NULL WHERE slot=1 AND binding=?",
                        (self._binding.digest,),
                    )
            except sqlite3.Error:
                raise AgentsAPIError("approval_invalidation_failed") from None

    def reconcile(self):
        # Exactly one bounded poll; DT-016 journal enforces the total request budget.
        return self._adapter.reconcile()

    def request_cleanup(self):
        """Durable external cleanup outbox, no guessed DELETE or provider mutation.

        An operator must separately service this one request and attest completion.
        This is a request, never a claim that hosted resources have been deleted.
        """
        _, state = self._journal.load(self._binding)
        if state.phase != "TERMINAL" or state.consumed_cents is None:
            raise AgentsAPIError("terminal_and_cost_observation_required")
        self._slot()
        try:
            with self._connection:
                changed = self._connection.execute(
                    "UPDATE dt017_control SET cleanup_requested=1 WHERE slot=1 AND binding=? "
                    "AND cleanup_requested=0",
                    (self._binding.digest,),
                ).rowcount
            if changed != 1:
                raise AgentsAPIError("cleanup_already_requested")
        except sqlite3.Error:
            raise AgentsAPIError("cleanup_request_commit_failed") from None
        return {"cleanup": "REQUESTED_NOT_CONFIRMED", "live": "NO-GO"}
