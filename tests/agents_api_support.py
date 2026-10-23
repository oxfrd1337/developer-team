"""Credential-free DT-016 wire fixtures; never construct an HTTP client."""

import copy
import sqlite3
from collections import defaultdict
from dataclasses import replace

from developer_team.adapters.agents_api import AgentsAPIAdapter
from developer_team.adapters.agents_api_contracts import (
    CANARY_INSTRUCTIONS,
    MINIMAL_CAPABILITIES,
    AgentsAPILimits,
    CanaryBinding,
    ExternalPermit,
    WireResponse,
    canonical,
)
from developer_team.adapters.agents_api_journal import SQLiteCanaryJournal

NOW = 1_800_000_000
SESSION = "session_synthetic"
TURN = "turn_synthetic"


def binding(**changes):
    return replace(
        CanaryBinding(
            project_id="proj_synthetic",
            agent_id="agent_synthetic",
            intent_id="intent_synthetic",
            idempotency_key="key_synthetic",
            plan_digest="a" * 64,
            budget_cents=5,
        ),
        **changes,
    )


def permit(bound=None, **changes):
    bound = binding() if bound is None else bound
    return replace(
        ExternalPermit(
            binding_digest=bound.digest,
            project_id=bound.project_id,
            credential_project_id=bound.project_id,
            agent_id=bound.agent_id,
            key_capabilities=MINIMAL_CAPABILITIES,
            project_capabilities=MINIMAL_CAPABILITIES,
            project_hard_limit_cents=5,
            observed_at=NOW,
            expires_at=NOW + 300,
            grant_binding_digest=bound.digest,
            grant_budget_cents=5,
            grant_issued_at=NOW,
            grant_expires_at=NOW + 300,
            submit_approved_at=NOW,
            secret_store_verified=True,
            spend_controls_verified=True,
            contract_verified=True,
            agent_configuration_verified=True,
            operator_grant_verified=True,
        ),
        **changes,
    )


class FixtureGate:
    def __init__(self, value=None):
        self.value = permit() if value is None else value
        self.calls = []

    def authorize(self, bound, operation, now):
        self.calls.append((bound.digest, operation, now))
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


def response(value, status=200):
    return WireResponse(status, canonical(value))


def page(records, **changes):
    return {"object": "list", "data": records, "has_more": False, **changes}


class FixtureTransport:
    """Simulated remote side effects can precede a lost wire response."""

    def __init__(self, bound=None):
        bound = binding() if bound is None else bound
        self.calls = []
        self.faults = defaultdict(list)
        self.created = False
        self.turn_status = None
        self.session = {
            "id": SESSION,
            "object": "agent.session",
            "status": "idle",
            "agent": {
                "id": bound.agent_id,
                "tools": [],
                "instructions": CANARY_INSTRUCTIONS,
                "multi_agent": {"enabled": False},
            },
            "environment": {"type": "openai_hosted"},
            "vault_ids": [],
            "required_actions": [],
            "metadata": {"dt016_binding": bound.digest},
            "spend_control": {"limit": bound.budget_cents, "consumed": 0},
        }
        self.turn = {
            "id": TURN,
            "object": "agent.session.turn",
            "session_id": SESSION,
            "agent_id": bound.agent_id,
            "subagent_id": None,
        }
        self.before_response = None

    def exchange(self, request):
        import json

        self.calls.append(request)
        path = request.url.split("https://api.openai.com/v1/agents/sessions", 1)[-1]
        if request.method == "POST" and not path:
            operation = "create"
            self.created = True
            result = response(self.session, 201)
        elif request.method == "POST":
            payload = json.loads(request.body)
            operation = "message" if payload["events"][0]["type"].endswith(".message") else "cancel"
            if operation == "message":
                self.turn_status = "in_progress"
            result = WireResponse(202)
        elif path.startswith("?"):
            operation = "list"
            result = response(page([self.session] if self.created else []))
        elif "/turns?" in path:
            operation = "turns"
            turns = [{**self.turn, "status": self.turn_status}] if self.turn_status else []
            result = response(page(turns))
        else:
            operation = "session"
            result = response(self.session)
        if self.before_response is not None:
            self.before_response(operation, request)
        if self.faults[operation]:
            fault = self.faults[operation].pop(0)
            if isinstance(fault, BaseException):
                raise fault
            return fault
        return result

    def posts(self, kind):
        import json

        result = []
        for request in self.calls:
            if request.method != "POST":
                continue
            value = json.loads(request.body)
            operation = value.get("events", [{"type": "create"}])[0]["type"]
            if operation == kind:
                result.append(request)
        return result


class Harness:
    def __init__(self, *, bound=None, limits=None):
        self.binding = binding() if bound is None else bound
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.journal = SQLiteCanaryJournal(self.connection)
        self.limits = AgentsAPILimits() if limits is None else limits
        self.journal.prepare(self.binding, self.limits)
        self.transport = FixtureTransport(self.binding)
        self.gate = FixtureGate(permit(self.binding))
        self.adapter = self.restart()

    def restart(self, **changes):
        return AgentsAPIAdapter(
            self.binding,
            self.journal,
            **{
                "transport": self.transport,
                "gate": self.gate,
                "limits": self.limits,
                "now": lambda: NOW,
                **changes,
            },
        )

    def active(self):
        self.adapter.create_session()
        self.adapter.submit_canary()
        self.adapter.reconcile()
        return self.adapter

    def state(self):
        return copy.deepcopy(self.journal.load(self.binding)[1])
