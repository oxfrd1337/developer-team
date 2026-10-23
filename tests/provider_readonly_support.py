"""Synthetic-only DT-017A wire and independently authenticated scope fixtures."""

import io
from dataclasses import dataclass, replace
from unittest.mock import Mock

from developer_team.adapters.provider_readonly_https import AdminCredentialIdentity
from developer_team.provider_readonly import (
    AdminReadOnlyCollector,
    CanaryReadOnlyCollector,
    ProviderReadOnlyCollector,
)
from developer_team.scope_evidence import (
    EXPECTED_EFFECTIVE_PERMISSIONS,
    EXPECTED_KEY_PERMISSIONS,
    EXPECTED_PRINCIPAL_PERMISSIONS,
    ScopeAttestorIdentity,
    ScopeEvidence,
    ScopeVerifierIdentity,
)
from tests.acceptance_support import SYNTHETIC_SECRET, SyntheticStore, credential_identity
from tests.agents_api_support import NOW, binding

ADMIN_MARKER = "synthetic-admin-marker-never-a-real-key"


def admin_identity(**changes):
    return replace(
        AdminCredentialIdentity(
            binding().project_id,
            "admin_synthetic",
            "admin_handle",
            binding().digest,
            NOW,
            NOW + 300,
        ),
        **changes,
    )


@dataclass(frozen=True, repr=False)
class AdminStore:
    identity: AdminCredentialIdentity

    def with_authorization(self, identity, send):
        assert identity == self.identity
        return send("Bearer " + ADMIN_MARKER)


def attestor_identity():
    return ScopeAttestorIdentity("synthetic_attestor", "source_domain", "1" * 64)


def verifier_identity():
    return ScopeVerifierIdentity("synthetic_verifier", "verifier_domain", "2" * 64)


class ScopeSource:
    def __init__(self):
        self.identity = attestor_identity()
        self.evidence = ScopeEvidence(
            credential_identity(),
            NOW,
            NOW + 300,
            EXPECTED_KEY_PERMISSIONS,
            EXPECTED_PRINCIPAL_PERMISSIONS,
            EXPECTED_EFFECTIVE_PERMISSIONS,
            self.identity,
            verifier_identity(),
            b"synthetic-signature",
        )

    def read_scope(self, bound, identity):
        return self.evidence


class ScopeVerifier:
    def __init__(self):
        self.identity = verifier_identity()
        self.accept = True
        self.calls = 0

    def verify(self, evidence):
        # Synthetic verifier has no source reference or read/issue capability.
        # Production must authenticate ALL fields with independent trust roots.
        self.calls += 1
        return self.accept and evidence.signature == b"synthetic-signature"


class Connection:
    def __init__(self, harness, role):
        self.harness, self.role = harness, role
        self.sock = Mock()
        self.closed, self.sent = False, False

    def connect(self):
        if self.harness.fault:
            raise self.harness.fault

    def request(self, method, path, body, headers):
        h = self.harness
        assert method == "GET" and body is None
        expected = ADMIN_MARKER if self.role == "admin" else SYNTHETIC_SECRET
        assert headers["Authorization"] == "Bearer " + expected
        if self.role == "canary":
            assert headers["OpenAI-Beta"] == "agents=v1"
            assert headers["OpenAI-Project"] == binding().project_id
        else:
            assert path.startswith(h.root)
        self.sent = True
        h.calls.append((self.role, method, path))
        self.path = path

    def getresponse(self):
        import json

        h = self.harness
        value = h.responses.get(self.path)
        raw = io.BytesIO(h.body if h.body is not None else json.dumps(value).encode())
        raw.status = h.status
        raw.read1 = raw.read
        return raw

    def close(self):
        self.closed = True


class Harness:
    def __init__(self):
        self.bound, self.identity = binding(), credential_identity()
        self.clock = NOW
        self.calls, self.connections = [], []
        self.status, self.body, self.fault = 200, None, None
        b, c = self.bound, self.identity
        self.root = f"/v1/organization/projects/{b.project_id}"
        account = {
            "object": "organization.project.service_account",
            "id": c.service_account_ref,
            "created_at": NOW - 1,
            "name": "private-service-account-name",
            "role": "member",
        }
        key = {
            "object": "organization.project.api_key",
            "id": c.credential_ref,
            "redacted_value": "private-redacted-marker",
            "owner_project_access": "active",
            "owner": {"type": "service_account", "service_account": dict(account)},
        }
        agent = {"id": b.agent_id, "object": "agent", **b.agent_configuration}
        agent["multi_agent"] = {"enabled": False, "max_concurrent_subagents": None}
        self.responses = {
            self.root: {
                "id": b.project_id,
                "object": "organization.project",
                "status": "active",
                "name": "private-project-name",
            },
            self.root + "/service_accounts": {
                "object": "list",
                "data": [account],
                "has_more": False,
            },
            self.root + "/api_keys?owner_project_access=any": {
                "object": "list",
                "data": [key],
                "has_more": False,
            },
            self.root + "/spend_limit": {
                "object": "project.spend_limit",
                "currency": "USD",
                "interval": "month",
                "threshold_amount": b.budget_cents,
                "enforcement": {"status": "enforcing"},
            },
            "/v1/models": {
                "object": "list",
                "data": [
                    {
                        "id": b.model,
                        "object": "model",
                        "created": NOW - 1,
                        "owned_by": "private-owner",
                        "shutdown_date": None,
                    }
                ],
            },
            f"/v1/agents/{b.agent_id}": agent,
        }
        self.admin = AdminReadOnlyCollector(
            b,
            c,
            AdminStore(admin_identity()),
            now=lambda: self.clock,
            connection_factory=lambda timeout: self.factory("admin"),
        )
        self.canary = CanaryReadOnlyCollector(
            b,
            c,
            SyntheticStore(c),
            approved_models=frozenset({b.model}),
            now=lambda: self.clock,
            connection_factory=lambda timeout: self.factory("canary"),
        )
        self.scope_source = ScopeSource()
        self.scope_verifier = ScopeVerifier()
        self.collector = ProviderReadOnlyCollector(
            b,
            c,
            admin=self.admin,
            canary=self.canary,
            scope_source=self.scope_source,
            scope_verifier=self.scope_verifier,
            scope_attestor_identity=attestor_identity(),
            scope_verifier_identity=verifier_identity(),
            now=lambda: self.clock,
        )

    def factory(self, role):
        conn = Connection(self, role)
        self.connections.append(conn)
        return conn

    @property
    def account(self):
        return self.responses[self.root + "/service_accounts"]["data"][0]

    @property
    def key(self):
        return self.responses[self.root + "/api_keys?owner_project_access=any"]["data"][0]

    @property
    def agent(self):
        return self.responses[f"/v1/agents/{self.bound.agent_id}"]

    @property
    def spend(self):
        return self.responses[self.root + "/spend_limit"]

    def check(self, name):
        return self.collector.report()["checks"][name]
