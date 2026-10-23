"""DT-017 synthetic account, broker, secret and HTTPS fixtures. No network."""

import io
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from developer_team.adapters.agents_api_contracts import MINIMAL_CAPABILITIES, WireRequest, sha256
from developer_team.agents_acceptance import AcceptanceController, Observation, OperatorApproval
from tests.agents_api_support import NOW, FixtureTransport, binding

SYNTHETIC_SECRET = "synthetic-wire-marker-never-a-real-key"


class Collector:
    def __init__(self, bound=None):
        b = bound or binding()
        facts = {
            "provider_contract_current": {
                "contract": "dt016-agents-v1", "origin": "https://developers.openai.com",
                "session_creation_billable": True, "spend_enforcement_delayed": True,
            },
            "account_project_binding": {
                "project_id": b.project_id, "credential_project_id": b.project_id,
                "service_account_ref": "sa_synthetic", "credential_ref": "key_synthetic",
            },
            "credential_scope": {
                "key_capabilities": sorted(MINIMAL_CAPABILITIES),
                "principal_capabilities": sorted(MINIMAL_CAPABILITIES),
                "effective_capabilities": sorted(MINIMAL_CAPABILITIES),
                "additional_permissions": [],
            },
            "spend_controls": {"project_limit_cents": b.budget_cents, "enforcement_delayed": True},
            "secret_store": {
                "external": True, "readable": True, "excluded_from_chat_git_prompts_logs": True,
            },
            "agent_configuration": {
                "agent_id": b.agent_id, "model": b.model, "model_available": True,
                "model_approved": True, "configuration_digest": sha256(b.agent_configuration),
            },
            "environment_configuration": {
                "configuration_digest": sha256(b.environment_configuration),
                "network": "disabled", "container_size": "small",
            },
            "single_canary_grant": {
                "binding_digest": b.digest, "budget_cents": b.budget_cents,
                "max_sessions": 1, "max_messages": 1, "exclusive_external_ownership": True,
                "grant_ref": "grant_synthetic",
            },
        }
        self.observations = {
            name: Observation(
                name, b.digest, NOW, NOW + 300,
                "official_documentation" if name == "provider_contract_current"
                else "controlled_account_readonly", "verifier_synthetic", value,
            ) for name, value in facts.items()
        }

    def read(self, bound, check):
        return self.observations.get(check)

    def drift(self, check, **changes):
        old = self.observations[check]
        self.observations[check] = replace(old, facts={**old.facts, **changes})


class Broker:
    def __init__(self):
        self.approval = None

    def read_approval(self, bound, operation, challenge):
        return self.approval

    def confirm(self, controller, operation):
        review = controller.review(operation)
        slot = controller._slot()
        self.approval = OperatorApproval(
            controller._binding.digest, operation, review["challenge"], slot[4], NOW, NOW + 60, True
        )
        return review


class SyntheticStore:
    def with_authorization(self, project, send):
        return send("Bearer " + SYNTHETIC_SECRET)


class WireConnection:
    def __init__(self, wire, *, fault=None, status=None, body=None):
        self.wire, self.fault, self.status, self.body = wire, fault, status, body
        self.sock = Mock()
        self.response = None
        self.sent = False
        self.closed = False

    def connect(self):
        if self.fault:
            raise self.fault

    def request(self, method, path, body, headers):
        assert headers.pop("Authorization") == "Bearer " + SYNTHETIC_SECRET
        headers.pop("Accept-Encoding")
        order = ("OpenAI-Beta", "OpenAI-Project", "Content-Type", "Idempotency-Key")
        request = WireRequest(method, "https://api.openai.com" + path,
                              tuple((k, headers[k]) for k in order if k in headers), body, 0, 65536)
        self.sent = True
        self.response = self.wire.exchange(request)

    def getresponse(self):
        raw = io.BytesIO(self.response.body if self.body is None else self.body)
        raw.status = self.response.status if self.status is None else self.status
        raw.read1 = raw.read
        return raw

    def close(self):
        self.closed = True


class AcceptanceHarness:
    def __init__(self, root):
        self.bound = binding()
        self.path = Path(root) / "synthetic-journal.sqlite3"
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.collector, self.broker = Collector(), Broker()
        self.wire = FixtureTransport()
        self.connections = []
        self.fault, self.status, self.body = None, None, None
        self.clock = NOW
        self.controller = self.restart()
        self.controller.prepare()

    def factory(self, timeout):
        conn = WireConnection(self.wire, fault=self.fault, status=self.status, body=self.body)
        self.connections.append(conn)
        return conn

    def restart(self):
        return AcceptanceController(
            self.bound, self.connection, collector=self.collector, secret_store=SyntheticStore(),
            operator_broker=self.broker, connection_factory=self.factory, now=lambda: self.clock,
        )

    def create(self):
        self.broker.confirm(self.controller, "create_session")
        return self.controller.execute("create_session")

    def submit(self):
        self.broker.confirm(self.controller, "submit_canary")
        return self.controller.execute("submit_canary")

    def state(self):
        return self.controller._journal.load(self.bound)[1]

    def count_posts(self):
        return sum(request.method == "POST" for request in self.wire.calls)

    def report_json(self):
        return json.dumps(self.controller.report())
