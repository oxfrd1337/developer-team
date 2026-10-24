"""DT-017A real GET collectors. Disabled without externally provisioned handles.

Only normalized observations leave this module. No raw response cache, JSON
attestation loader, CLI activation, operator grant, session or submission method.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .adapters.agents_api_contracts import (
    bounded_int,
    safe_ref,
    sha256,
)
from .adapters.agents_credentials import require_identity
from .adapters.provider_readonly_https import AdminReadOnlyHTTPS, CanaryReadOnlyHTTPS
from .agents_acceptance import ACCOUNT_CHECKS, Observation, ReadOnlyVerifier
from .provider_readonly_diagnostics import PROVIDER_GATES, DiagnosticError, empty_diagnostics
from .scope_evidence import ScopeEvidence, validate_scope_subjects


def _require(condition, code="SCHEMA_MISMATCH"):
    if not condition:
        raise DiagnosticError(code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _get(transport, path):
    response = transport.read(path)
    status = response.status
    if status != 200:
        if status in {401, 403, 429}:
            code = {401: "HTTP_401", 403: "HTTP_403", 429: "HTTP_429"}[status]
        elif 500 <= status <= 599:
            code = "HTTP_5XX"
        elif 300 <= status <= 399:
            code = "HTTP_REDIRECT"
        else:
            code = "HTTP_OTHER"
        raise DiagnosticError(code)
    value = None
    try:
        value = json.loads(
            response.body, object_pairs_hook=_unique,
            parse_constant=lambda _: _require(False),
        )
    except Exception:
        value = None
    if type(value) is not dict:
        raise DiagnosticError("SCHEMA_MISMATCH")
    return value


class _StagedCollector:
    def _get(self, path, stage):
        self._stage = stage
        return _get(self._transport, path)


def _record(listing, reference):
    _require(listing.get("object") == "list" and listing.get("has_more") is False)
    records = listing.get("data")
    _require(type(records) is list and len(records) <= 100)
    _require(all(type(item) is dict and safe_ref(item.get("id")) for item in records))
    ids = [item["id"] for item in records]
    _require(len(ids) == len(set(ids)))
    matches = [item for item in records if item["id"] == reference]
    _require(len(matches) == 1, "EXPECTED_RECORD_MISSING")
    return matches[0]


def _not_expired(record, now):
    # These metadata fields are optional in the official API; absence is not a
    # scope proof. Explicit expiry/status/access claims must never be ignored.
    expiry = record.get("expires_at")
    _require(expiry is None or bounded_int(expiry, now + 1, 2**53))
    if "status" in record:
        _require(record["status"] == "active")
    if "owner_project_access" in record:
        _require(record["owner_project_access"] == "active")
    return expiry if expiry is not None else now + 300


@dataclass(frozen=True, slots=True, repr=False)
class SpendEvidence:
    project_limit_cents: int
    enforcement_delayed: bool = True

    @classmethod
    def from_provider(cls, value, binding):
        _require(
            set(value) == {"object", "currency", "interval", "threshold_amount", "enforcement"}
            and value.get("object") == "project.spend_limit"
            and value.get("currency") == "USD"
            and value.get("interval") == "month"
            and value.get("enforcement") == {"status": "enforcing"}
            and type(value.get("threshold_amount")) is int
        )
        _require(
            binding.budget_cents <= value["threshold_amount"] <= 100, "CONFIGURATION_MISMATCH"
        )
        # Delayed enforcement is never a per-request spending guarantee. DT-017's
        # independent local budget / exclusive single-canary grant stays required.
        return cls(value["threshold_amount"])


class AdminReadOnlyCollector(_StagedCollector):
    def __init__(self, binding, identity, secret_store=None, *, now=time.time, **wire_options):
        self._binding, self._identity, self._now = binding, identity, now
        self._transport = AdminReadOnlyHTTPS(
            binding, identity, secret_store, now=now, **wire_options
        )

    def _validate(self):
        return self._transport._validate_identity()

    def account(self):
        return self._account_evidence()[0]

    def _account_evidence(self):
        self._validate()
        expires_at = int(self._now()) + 300
        b, c = self._binding, self._identity
        root = f"/v1/organization/projects/{b.project_id}"
        project = self._get(root, "ADMIN_PROJECT")
        _require(
            project.get("id") == b.project_id
            and project.get("object") == "organization.project"
            and project.get("status") == "active"
        )
        account = _record(
            self._get(root + "/service_accounts", "ADMIN_SERVICE_ACCOUNTS"), c.service_account_ref
        )
        _require(account.get("object") == "organization.project.service_account")
        key = _record(
            self._get(root + "/api_keys?owner_project_access=any", "ADMIN_API_KEYS"),
            c.credential_ref,
        )
        _require(
            key.get("object") == "organization.project.api_key"
            and key.get("owner_project_access") == "active"
        )
        owner = key.get("owner")
        _require(type(owner) is dict and owner.get("type") == "service_account")
        principal = owner.get("service_account")
        _require(type(principal) is dict and principal.get("id") == c.service_account_ref)
        _require(owner.get("user") is None)
        # Default role is identity metadata, never proof of effective permissions.
        _require(account.get("role") in {"owner", "member", "none"})
        _require(principal.get("role") == account["role"])
        for item in (account, key, principal):
            if "project_id" in item:
                _require(item["project_id"] == b.project_id)
            expires_at = min(expires_at, _not_expired(item, int(self._now())))
        self._validate()
        _require(int(self._now()) < expires_at)
        facts = {
            "project_id": b.project_id,
            "credential_project_id": b.project_id,
            "credential_identity_digest": c.digest,
            "credential_ref": c.credential_ref,
            "service_account_ref": c.service_account_ref,
            "handle_ref": c.handle_ref,
        }
        return facts, expires_at

    def spend(self):
        self._validate()
        b = self._binding
        value = self._get(
            f"/v1/organization/projects/{b.project_id}/spend_limit", "ADMIN_SPEND_LIMIT"
        )
        evidence = SpendEvidence.from_provider(value, b)
        self._validate()
        return {
            "project_limit_cents": evidence.project_limit_cents,
            "enforcement_delayed": evidence.enforcement_delayed,
        }


class CanaryReadOnlyCollector(_StagedCollector):
    def __init__(
        self,
        binding,
        identity,
        secret_store=None,
        *,
        approved_models=frozenset(),
        now=time.time,
        **wire_options,
    ):
        require_identity(identity, binding, int(now()))
        self._binding, self._identity, self._now = binding, identity, now
        self._approved = approved_models
        self._transport = CanaryReadOnlyHTTPS(binding, secret_store, now=now, **wire_options)

    def _validate(self):
        _require(self._transport._validate_identity() == self._identity)

    def agent(self):
        self._validate()
        b = self._binding
        _require(type(self._approved) is frozenset and b.model in self._approved)
        models = self._get("/v1/models", "CANARY_MODELS")
        # No pagination or scope readback. Announced shutdowns block conservatively;
        # availability never constitutes permission attestation.
        _require(set(models) == {"object", "data"} and models["object"] == "list")
        data = models["data"]
        _require(type(data) is list and len(data) <= 1000)
        _require(all(type(m) is dict and type(m.get("id")) is str for m in data))
        matches = [m for m in data if m["id"] == b.model]
        _require(len(matches) == 1, "EXPECTED_RECORD_MISSING")
        model = matches[0]
        required = {"id", "object", "created", "owned_by"}
        _require(required <= set(model) <= required | {"shutdown_date"})
        _require(model.get("shutdown_date") is None, "CONFIGURATION_MISMATCH")
        _require(model["object"] == "model" and bounded_int(model["created"], 0, int(self._now())))
        saved = self._get(f"/v1/agents/{b.agent_id}", "CANARY_AGENT")
        expected = b.agent_configuration
        # The response resolves disabled max_concurrent_subagents to null.
        expected["multi_agent"] = {"enabled": False, "max_concurrent_subagents": None}
        metadata = {"id", "object", "created_at", "updated_at", "name", "metadata"}
        _require(set(saved) <= set(expected) | metadata)
        _require(saved.get("id") == b.agent_id and saved.get("object") == "agent")
        _require(all(key in saved for key in expected))
        _require(
            sha256({key: saved[key] for key in expected}) == sha256(expected),
            "CONFIGURATION_MISMATCH",
        )
        self._validate()
        return {
            "agent_id": b.agent_id,
            "model": b.model,
            "model_available": True,
            "model_approved": True,
            "configuration_digest": sha256(b.agent_configuration),
        }


class ProviderReadOnlyCollector:
    """Acceptance adapter for four provider-backed gates; all others remain absent.

    Trusted scope_source.read_scope(binding, identity), an independent verifier
    and controller-provisioned role-specific identity pins are required.
    Neither GET success nor an untrusted JSON/Observation grants scopes.
    No fallback to another account collector for these four checks.
    """

    def __init__(
        self,
        binding,
        identity,
        *,
        admin=None,
        canary=None,
        scope_source=None,
        scope_verifier=None,
        scope_attestor_identity=None,
        scope_verifier_identity=None,
        now=time.time,
    ):
        binding.validate()
        self._binding, self._identity, self._now = binding, identity, now
        self._admin, self._canary = admin, canary
        self._scope_source, self._scope_verifier = scope_source, scope_verifier
        self._attestor_pin = scope_attestor_identity
        self._verifier_pin = scope_verifier_identity
        self._diagnostics = empty_diagnostics()

    def _separation(self):
        if self._admin is None or self._canary is None:
            return
        _require(type(self._admin) is AdminReadOnlyCollector)
        _require(type(self._canary) is CanaryReadOnlyCollector)
        admin_store = self._admin._transport._store
        canary_store = self._canary._transport._store
        _require(admin_store is not canary_store)
        if hasattr(admin_store, "_snapshot") and hasattr(canary_store, "_snapshot"):
            _require(admin_store._snapshot[:2] != canary_store._snapshot[:2])

    def read(self, binding, check):
        observation = None
        provider_gate = check in PROVIDER_GATES
        role = self._canary if check == "agent_configuration" else self._admin
        if provider_gate:
            self._diagnostics[check] = {"code": "LOCAL_VALIDATION_FAILED", "stage": "PRECHECK"}
            if type(role) in {AdminReadOnlyCollector, CanaryReadOnlyCollector}:
                role._stage = "PRECHECK"
        failure = "LOCAL_VALIDATION_FAILED"
        try:
            _require(binding == self._binding)
            self._separation()
            start = int(self._now())
            c = require_identity(self._identity, binding, start)
            observed_at, expires_at = start, min(start + 300, c.expires_at)
            if check in {"account_project_binding", "spend_controls"}:
                _require(type(self._admin) is AdminReadOnlyCollector)
                _require(self._admin._binding == binding and self._admin._identity == c)
                if check == "account_project_binding":
                    facts, provider_expiry = self._admin._account_evidence()
                    expires_at = min(expires_at, provider_expiry)
                else:
                    facts = self._admin.spend()
                expires_at = min(expires_at, self._admin._validate().expires_at)
            elif check == "agent_configuration":
                _require(type(self._canary) is CanaryReadOnlyCollector)
                _require(self._canary._binding == binding and self._canary._identity == c)
                facts = self._canary.agent()
            elif check == "credential_scope":
                self._validate_canary_handle(binding, c)
                source, verifier = self._scope_source, self._scope_verifier
                attestor_pin, verifier_pin = self._attestor_pin, self._verifier_pin
                validate_scope_subjects(source, verifier, attestor_pin, verifier_pin)
                evidence = source.read_scope(binding, c)
                _require(type(evidence) is ScopeEvidence)
                facts = evidence.validate(
                    binding, c, int(self._now()), source, verifier, attestor_pin, verifier_pin
                )
                _require(self._scope_source is source and self._scope_verifier is verifier)
                _require(self._attestor_pin == attestor_pin and self._verifier_pin == verifier_pin)
                self._validate_canary_handle(binding, c)
                observed_at, expires_at = evidence.observed_at, min(expires_at, evidence.expires_at)

            else:
                return None
            after = int(self._now())
            require_identity(c, binding, after)
            _require(start <= after < expires_at and after - observed_at <= 300)
            observation = Observation(
                check,
                binding.digest,
                observed_at,
                expires_at,
                "controlled_account_readonly",
                "dt017a_provider",
                facts,
            )
        except DiagnosticError as error:
            failure = error.code
        except Exception:
            observation = None
        if provider_gate:
            stage = role._stage if type(role) in {
                AdminReadOnlyCollector, CanaryReadOnlyCollector
            } else "PRECHECK"
            self._diagnostics[check] = {
                "code": "PASS" if observation is not None else (
                    "LOCAL_VALIDATION_FAILED" if stage == "PRECHECK" else failure
                ),
                "stage": "COMPLETE" if observation is not None else stage,
            }
        return observation

    def _validate_canary_handle(self, binding, identity):
        if self._canary is not None:
            _require(type(self._canary) is CanaryReadOnlyCollector)
            _require(self._canary._binding == binding and self._canary._identity == identity)
            self._canary._validate()

    def diagnostics(self, checks):
        result = empty_diagnostics()
        for gate in PROVIDER_GATES:
            item = self._diagnostics[gate]
            if item["code"] == "PASS" and checks[gate] != "PASS":
                item = {"code": "OBSERVATION_REJECTED", "stage": "COMPLETE"}
            result[gate] = dict(item)
        return result

    def report(self):
        checks, _ = ReadOnlyVerifier(self).inspect(self._binding, int(self._now()), self._identity)
        return {
            "mode": "dt017a-readonly-provider",
            "provider_diagnostics": self.diagnostics(checks),
            "checks": {name: checks[name] for name in ACCOUNT_CHECKS},
            "real_submissions": 0,
            "live": "NO-GO",
            "live_authorized": False,
            "validation": "OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.",
        }
