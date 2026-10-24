"""Issue #36 negative matrix. No external credentials or real API requests."""

import copy
import json
import os
import socket
import sqlite3
import ssl
import tempfile
import threading
import time
import traceback
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, patch

from developer_team.adapters.agents_api_contracts import AgentsAPIError, WireRequest, WireResponse
from developer_team.adapters.agents_https import FDSecretStore, HardenedHTTPS
from developer_team.adapters.provider_readonly_https import (
    AdminFDSecretStore,
    AdminReadOnlyHTTPS,
    CanaryReadOnlyHTTPS,
)
from developer_team.agents_acceptance import AcceptanceController, ReadOnlyVerifier
from developer_team.provider_readonly import (
    AdminReadOnlyCollector,
    CanaryReadOnlyCollector,
    ProviderReadOnlyCollector,
)
from developer_team.scope_evidence import (
    EXPECTED_KEY_PERMISSIONS,
    EffectivePermission,
    KeyPermission,
    PrincipalPermission,
)
from tests.acceptance_support import SYNTHETIC_SECRET, SyntheticStore, credential_identity
from tests.agents_api_support import NOW, binding
from tests.provider_readonly_support import ADMIN_MARKER, AdminStore, Harness, admin_identity


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def assert_blocked(self, gate):
        self.assertEqual(self.h.check(gate), "MISSING_OR_INVALID")

    def test_valid_synthetic_evidence_feeds_existing_acceptance_gates(self):
        report = self.h.collector.report()
        for name in (
            "account_project_binding",
            "spend_controls",
            "agent_configuration",
            "credential_scope",
        ):
            self.assertEqual(report["checks"][name], "PASS")
        for name in (
            "provider_contract_current",
            "environment_configuration",
            "single_canary_grant",
            "real_transport",
            "secret_store",
        ):
            self.assertEqual(report["checks"][name], "MISSING_OR_INVALID")
        self.assertEqual(report["live"], "NO-GO")
        self.assertEqual(report["real_submissions"], 0)
        self.assertFalse(report["live_authorized"])
        self.assertEqual(len(self.h.calls), 6)
        self.assertTrue(all(method == "GET" for _, method, _ in self.h.calls))

    def test_default_disabled_no_secret_lookup_no_socket(self):
        b, c = binding(), credential_identity()
        with patch("socket.socket") as sock:
            collector = ProviderReadOnlyCollector(b, c)
            self.assertEqual(set(collector.report()["checks"].values()), {"MISSING_OR_INVALID"})
            admin = AdminReadOnlyCollector(b, c, now=lambda: NOW)
            canary = CanaryReadOnlyCollector(b, c, now=lambda: NOW)
            for call in (admin.account, admin.spend, canary.agent):
                with self.assertRaises(AgentsAPIError):
                    call()
            sock.assert_not_called()

    def test_account_foreign_project_archived_or_missing(self):
        for updates in (
            {"id": "foreign"},
            {"status": "archived"},
            {"status": None},
            {"object": "unexpected"},
        ):
            with self.subTest(updates=updates):
                self.h = Harness()
                self.h.responses[self.h.root].update(updates)
                self.assert_blocked("account_project_binding")

    def test_owner_service_account_mismatch_or_user_blocks(self):
        for owner in (
            {},
            {"type": "user", "user": {"email": "synthetic@example.invalid"}},
            {"type": "service_account", "service_account": {"id": "foreign"}},
            {
                "type": "service_account",
                "service_account": {"id": self.h.identity.service_account_ref},
                "user": {"id": "foreign"},
            },
        ):
            self.h.key["owner"] = owner
            self.assert_blocked("account_project_binding")

    def test_service_account_unknown_or_owner_role_conflict_blocks(self):
        for role in ("unknown", None):
            self.h.account["role"] = role
            self.assert_blocked("account_project_binding")
        self.h = Harness()
        self.h.key["owner"]["service_account"]["role"] = "owner"
        self.assert_blocked("account_project_binding")

    def test_inactive_owner_access_blocks(self):
        for value in ("inactive", None, True, "unknown"):
            self.h.key["owner_project_access"] = value
            self.assert_blocked("account_project_binding")

    def test_key_and_account_expiry_and_status_blocks(self):
        for target in ("account", "key", "principal"):
            for updates in (
                {"expires_at": NOW},
                {"expires_at": NOW - 1},
                {"expires_at": True},
                {"expires_at": "tomorrow"},
                {"status": "revoked"},
                {"project_id": "foreign"},
            ):
                self.h = Harness()
                item = (
                    self.h.key["owner"]["service_account"]
                    if target == "principal"
                    else getattr(self.h, target)
                )
                item.update(updates)
                self.assert_blocked("account_project_binding")

    def test_provider_expiry_caps_account_observation_for_each_owner_record(self):
        for target in ("account", "key", "principal"):
            self.h = Harness()
            item = (
                self.h.key["owner"]["service_account"]
                if target == "principal"
                else getattr(self.h, target)
            )
            item["expires_at"] = NOW + 2
            observation = self.h.collector.read(self.h.bound, "account_project_binding")
            self.assertIsNotNone(observation)
            self.assertEqual(observation.expires_at, NOW + 2)
            cached = Mock(read=Mock(return_value=observation))
            checks, _ = ReadOnlyVerifier(cached).inspect(self.h.bound, NOW + 2, self.h.identity)
            self.assertEqual(checks["account_project_binding"], "MISSING_OR_INVALID")

    def test_shortest_provider_expiry_wins_without_changing_public_account_facts(self):
        self.h.account["expires_at"] = NOW + 30
        self.h.key["expires_at"] = NOW + 20
        self.h.key["owner"]["service_account"]["expires_at"] = NOW + 10
        observation = self.h.collector.read(self.h.bound, "account_project_binding")
        self.assertEqual(observation.expires_at, NOW + 10)
        self.assertEqual(self.h.admin.account(), observation.facts)
        self.assertNotIn("expires_at", observation.facts)

    def test_provider_expiry_during_final_handle_check_blocks_account(self):
        self.h.key["expires_at"] = NOW + 1
        original = self.h.admin._validate
        calls = 0

        def delayed_validation():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.h.clock = NOW + 1
            return original()

        self.h.admin._validate = delayed_validation
        self.assertIsNone(self.h.collector.read(self.h.bound, "account_project_binding"))

    def test_scope_verifier_cannot_replace_actual_canary_handle(self):
        def replace_handle(evidence):
            self.h.canary._transport._store = SyntheticStore(
                credential_identity(handle_ref="foreign")
            )
            return True

        self.h.collector._scope_verifier = Mock(
            identity=self.h.scope_verifier.identity, verify=replace_handle
        )
        self.assertIsNone(self.h.collector.read(self.h.bound, "credential_scope"))
        self.assertEqual(self.h.calls, [])

    def test_changed_canary_handle_blocks_before_scope_source(self):
        source = Mock()
        self.h.collector._scope_source = source
        self.h.canary._transport._store = SyntheticStore(credential_identity(handle_ref="foreign"))
        self.assertIsNone(self.h.collector.read(self.h.bound, "credential_scope"))
        source.read_scope.assert_not_called()
        self.assertEqual(self.h.calls, [])

    def test_scope_remains_separately_attestable_without_canary_transport(self):
        self.h.collector._canary = None
        self.assertEqual(self.h.check("credential_scope"), "PASS")
        self.assertEqual(self.h.check("agent_configuration"), "MISSING_OR_INVALID")
        self.assertEqual(self.h.collector.report()["live"], "NO-GO")

    def test_missing_duplicate_or_incomplete_listing_blocks(self):
        for path in ("/service_accounts", "/api_keys?owner_project_access=any"):
            for change in ("missing", "duplicate", "pagination", "malformed", "too_many"):
                self.h = Harness()
                listing = self.h.responses[self.h.root + path]
                if change == "missing":
                    listing["data"] = []
                elif change == "duplicate":
                    listing["data"] *= 2
                elif change == "pagination":
                    listing["has_more"] = True
                elif change == "malformed":
                    listing["data"] = [None]
                else:
                    listing["data"] *= 101
                self.assert_blocked("account_project_binding")

    def test_missing_scope_readback_is_never_inferred_from_successful_gets(self):
        self.h.collector._scope_source = None
        report = self.h.collector.report()
        self.assertEqual(report["checks"]["account_project_binding"], "PASS")
        self.assertEqual(report["checks"]["agent_configuration"], "PASS")
        self.assertEqual(report["checks"]["credential_scope"], "MISSING_OR_INVALID")
        self.assertEqual(report["live"], "NO-GO")

    def test_provider_claimed_scopes_cannot_supply_attestation(self):
        self.h.key["scopes"] = sorted(p.value for p in EXPECTED_KEY_PERMISSIONS)
        self.h.collector._scope_source = None
        self.assert_blocked("credential_scope")

    def test_scope_attestation_each_identity_field_must_match(self):
        original = self.h.scope_source.evidence
        for field, value in (
            ("project_id", "foreign"),
            ("credential_ref", "foreign"),
            ("service_account_ref", "foreign"),
            ("handle_ref", "foreign"),
            ("binding_digest", "a" * 64),
            ("issued_at", NOW - 1),
            ("expires_at", NOW + 299),
        ):
            self.h.scope_source.evidence = replace(
                original, identity=replace(original.identity, **{field: value})
            )
            self.assert_blocked("credential_scope")

    def test_scope_attestation_stale_future_expired_or_overlong_blocks(self):
        original = self.h.scope_source.evidence
        for changes in (
            {"observed_at": NOW - 301},
            {"observed_at": NOW + 1},
            {"expires_at": NOW},
            {"expires_at": NOW + 301},
            {"observed_at": True},
            {"expires_at": True},
        ):
            self.h.scope_source.evidence = replace(original, **changes)
            self.assert_blocked("credential_scope")

    def test_scope_extra_or_missing_key_principal_effective_rights_blocks(self):
        original = self.h.scope_source.evidence
        for field, permission_type in (
            ("key_scopes", KeyPermission),
            ("principal_scopes", PrincipalPermission),
            ("effective_scopes", EffectivePermission),
        ):
            expected = getattr(original, field)
            for scopes in (
                expected | {permission_type.FILES_WRITE},
                expected | {"admin"},
                expected | {"all"},
                expected - {permission_type.RESPONSES_WRITE},
                list(expected),
            ):
                self.h.scope_source.evidence = replace(original, **{field: scopes})
                self.assert_blocked("credential_scope")

    def test_scope_untrusted_json_false_signature_missing_verifier_blocks(self):
        original = self.h.scope_source.evidence
        for evidence in (
            asdict(original),
            replace(original, signature=b"forged"),
            replace(original, signature=b""),
            replace(
                original,
                attestor_identity=replace(original.attestor_identity, subject_ref="foreign"),
            ),
        ):
            self.h.scope_source.evidence = evidence
            self.assert_blocked("credential_scope")
        self.h.scope_source.evidence = original
        self.h.scope_verifier.accept = False
        self.assert_blocked("credential_scope")
        self.h.scope_verifier.accept = True
        self.h.collector._scope_verifier = None
        self.assert_blocked("credential_scope")

    def test_scope_verifier_faults_and_non_boolean_result_are_sanitized(self):
        for result in (1, "PASS", None):
            self.h.collector._scope_verifier = Mock(
                identity=self.h.scope_verifier.identity, verify=Mock(return_value=result)
            )
            self.assert_blocked("credential_scope")
        self.h.collector._scope_verifier = Mock(
            identity=self.h.scope_verifier.identity,
            verify=Mock(side_effect=ValueError(SYNTHETIC_SECRET)),
        )
        self.assertNotIn(SYNTHETIC_SECRET, json.dumps(self.h.collector.report()))
        self.assert_blocked("credential_scope")

    def test_spend_missing_soft_unexpected_high_low_invalid_no_go(self):
        original = dict(self.h.spend)
        for changes in (
            {"object": "soft_limit"},
            {"threshold_amount": None},
            {"threshold_amount": 101},
            {"threshold_amount": self.h.bound.budget_cents - 1},
            {"threshold_amount": True},
            {"threshold_amount": 0.1},
            {"currency": "EUR"},
            {"interval": "day"},
            {"enforcement": {"status": "inactive"}},
            {"unexpected": True},
        ):
            self.h.responses[self.h.root + "/spend_limit"] = {**original, **changes}
            self.assert_blocked("spend_controls")
        for field in original:
            value = dict(original)
            del value[field]
            self.h.responses[self.h.root + "/spend_limit"] = value
            self.assert_blocked("spend_controls")

    def test_spend_delay_explicit_and_no_local_budget_or_grant_bypass(self):
        observation = self.h.collector.read(self.h.bound, "spend_controls")
        self.assertIs(observation.facts["enforcement_delayed"], True)
        self.assertEqual(observation.facts["project_limit_cents"], self.h.bound.budget_cents)
        self.assert_blocked("single_canary_grant")

    def test_models_missing_duplicate_shutdown_or_unexpected_no_go(self):
        path = "/v1/models"
        original = copy.deepcopy(self.h.responses[path])
        for data in (
            [],
            original["data"] * 2,
            [{**original["data"][0], "id": "unexpected"}],
            [{**original["data"][0], "status": "shutdown"}],
            [{**original["data"][0], "shutdown_at": NOW - 1}],
            [{**original["data"][0], "shutdown_date": "2026-10-23"}],
            [{**original["data"][0], "shutdown_date": "2099-01-01"}],
            [None],
        ):
            self.h.responses[path] = {"object": "list", "data": data}
            self.assert_blocked("agent_configuration")

    def test_model_availability_does_not_imply_approval(self):
        self.h.canary._approved = frozenset()
        self.assert_blocked("agent_configuration")
        self.assertEqual(
            self.h.calls,
            [
                ("admin", "GET", self.h.root),
                ("admin", "GET", self.h.root + "/service_accounts"),
                ("admin", "GET", self.h.root + "/api_keys?owner_project_access=any"),
                ("admin", "GET", self.h.root + "/spend_limit"),
            ],
        )

    def test_agent_missing_config_or_id_model_drift_no_go(self):
        original = copy.deepcopy(self.h.agent)
        path = f"/v1/agents/{self.h.bound.agent_id}"
        for field in ("id", "object", *self.h.bound.agent_configuration):
            self.h.responses[path] = {k: v for k, v in original.items() if k != field}
            self.assert_blocked("agent_configuration")
        for changes in (
            {"id": "foreign"},
            {"model": "unexpected"},
            {"instructions": "drift"},
            {"reasoning": {"effort": "high"}},
            {"service_tier": "priority"},
        ):
            self.h.responses[path] = {**original, **changes}
            self.assert_blocked("agent_configuration")

    def test_agent_tools_network_subagents_and_unknown_fields_block(self):
        original = copy.deepcopy(self.h.agent)
        path = f"/v1/agents/{self.h.bound.agent_id}"
        for changes in (
            {"tools": [{"type": "web_search"}]},
            {"tools": [{"type": "mcp"}]},
            {"network": {"access": "enabled"}},
            {"environment": {"network": "enabled"}},
            {"multi_agent": {"enabled": True, "max_concurrent_subagents": 1}},
            {"multi_agent": {"enabled": False, "max_concurrent_subagents": 1}},
            {"multi_agent": {"enabled": 0, "max_concurrent_subagents": None}},
            {"unexpected": False},
        ):
            self.h.responses[path] = {**original, **changes}
            self.assert_blocked("agent_configuration")

    def test_observations_and_reports_do_not_contain_names_emails_or_raw_responses(self):
        self.h.key["name"] = "synthetic@example.invalid"
        report = json.dumps(self.h.collector.report())
        _, observations = ReadOnlyVerifier(self.h.collector).inspect(
            self.h.bound, NOW, self.h.identity
        )
        rendered = report + json.dumps({k: asdict(v) for k, v in observations.items()})
        for marker in (
            SYNTHETIC_SECRET,
            ADMIN_MARKER,
            "private-",
            "synthetic@example.invalid",
            "redacted_value",
            "signature",
        ):
            self.assertNotIn(marker, rendered)
        self.assertFalse(any("response" in name for name in vars(self.h.admin)))
        self.assertFalse(any("response" in name for name in vars(self.h.canary)))

    def test_wrong_binding_and_collector_identity_block(self):
        self.assertIsNone(
            self.h.collector.read(
                replace(self.h.bound, project_id="foreign"), "account_project_binding"
            )
        )
        self.assertEqual(self.h.calls, [])
        self.h.admin._identity = credential_identity(credential_ref="foreign")
        self.assert_blocked("account_project_binding")
        self.h.canary._identity = credential_identity(credential_ref="foreign")
        self.assert_blocked("agent_configuration")

    def test_collector_expiry_during_reads_cannot_refresh_evidence(self):
        original = self.h.factory

        def expire(role):
            conn = original(role)
            previous = conn.getresponse

            def late():
                result = previous()
                self.h.clock = NOW + 301
                return result

            conn.getresponse = late
            return conn

        self.h.factory = expire
        self.assert_blocked("account_project_binding")
        self.assert_blocked("agent_configuration")

    def test_malformed_duplicate_nonfinite_or_nonobject_json_is_sanitized(self):
        for body in (
            b"{",
            b"[]",
            b"null",
            b'{"object":"list","object":"list"}',
            b'{"data":NaN}',
            b'{"x":Infinity}',
            b"\xff",
            b"[" * 2000,
        ):
            self.h.body = body
            report = self.h.collector.report()
            for gate in ("account_project_binding", "agent_configuration", "spend_controls"):
                self.assertEqual(report["checks"][gate], "MISSING_OR_INVALID")

    def test_failed_http_is_sanitized_without_retry_or_redirect(self):
        for status in (301, 302, 307, 308, 401, 403, 404, 429, 500, 502, 503):
            self.h.calls.clear()
            self.h.status, self.h.body = status, SYNTHETIC_SECRET.encode()
            self.assertIsNone(self.h.collector.read(self.h.bound, "account_project_binding"))
            self.assertEqual(len(self.h.calls), 1)
            self.assertTrue(self.h.connections[-1].closed)

    def test_acceptance_controller_remains_no_go_and_never_posts(self):
        with tempfile.TemporaryDirectory() as root:
            connection = sqlite3.connect(os.path.join(root, "state.sqlite3"))
            self.addCleanup(connection.close)
            controller = AcceptanceController(
                self.h.bound,
                connection,
                collector=self.h.collector,
                secret_store=SyntheticStore(),
                now=lambda: NOW,
            )
            controller.prepare()
            self.assertEqual(controller.report()["live"], "NO-GO")
            with self.assertRaises(AgentsAPIError):
                controller.review()
            with self.assertRaises(AgentsAPIError):
                controller.execute("create_session")
            self.assertTrue(all(method == "GET" for _, method, _ in self.h.calls))


class ReadOnlyWireTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def request(self, transport, **changes):
        paths, headers = transport._allowed()
        return replace(
            WireRequest(
                "GET",
                "https://api.openai.com" + paths[0],
                headers,
                None,
                time.monotonic() + 4,
                65536,
            ),
            **changes,
        )

    def transports(self):
        return (self.h.admin._transport, self.h.canary._transport)

    def test_only_whitelisted_get_paths_reach_wire(self):
        for transport in self.transports():
            for path in transport._allowed()[0]:
                self.assertEqual(transport.read(path).status, 200)
        self.assertEqual(len(self.h.calls), 7)

    def test_mutations_all_block_before_store_and_socket(self):
        for transport in self.transports():
            for method in (
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "HEAD",
                "OPTIONS",
                "get",
                "GET\r\nPOST",
            ):
                with self.assertRaises(AgentsAPIError):
                    transport.exchange(self.request(transport, method=method))
        self.assertEqual(self.h.connections, [])

    def test_wrong_origin_port_userinfo_path_query_encoding_blocks_before_socket(self):
        for transport in self.transports():
            valid = self.request(transport).url
            for url in (
                valid.replace("https:", "http:"),
                valid.replace("api.openai.com", "api.openai.com.evil"),
                valid.replace("api.openai.com", "api.openai.com:443"),
                valid.replace("api.openai.com", "user@api.openai.com"),
                valid + "#fragment",
                valid + "?extra=1",
                valid + "/../files",
                valid + "%2f..",
                "https://api.openai.com/v1/files",
                "https://api.openai.com/v1/agents/sessions",
                "https://api.openai.com/v1/responses",
            ):
                with self.assertRaises(AgentsAPIError):
                    transport.exchange(self.request(transport, url=url))
            with self.assertRaises(AgentsAPIError):
                transport.read("/unbound")
        self.assertEqual(self.h.connections, [])

    def test_cross_role_paths_and_foreign_project_agent_key_ids_block(self):
        admin, canary = self.transports()
        for path in canary._allowed()[0]:
            with self.assertRaises(AgentsAPIError):
                admin.exchange(self.request(admin, url="https://api.openai.com" + path))
        for path in admin._allowed()[0]:
            with self.assertRaises(AgentsAPIError):
                canary.exchange(self.request(canary, url="https://api.openai.com" + path))
        for transport, path in (
            (admin, self.h.root.replace(self.h.bound.project_id, "foreign")),
            (admin, self.h.root + "/api_keys/foreign"),
            (canary, "/v1/agents/foreign"),
        ):
            with self.assertRaises(AgentsAPIError):
                transport.exchange(self.request(transport, url="https://api.openai.com" + path))
        self.assertEqual(self.h.connections, [])

    def test_wrong_headers_bodies_or_limits_block_before_socket(self):
        for transport in self.transports():
            headers = self.request(transport).headers
            for changes in (
                {"headers": ()},
                {"headers": headers + (("Authorization", "bad"),)},
                {"headers": headers + (("OpenAI-Project", "foreign"),)},
                {"body": b"{}"},
                {"max_response_bytes": True},
                {"max_response_bytes": 65537},
                {"deadline": float("nan")},
                {"deadline": float("inf")},
                {"deadline": time.monotonic() - 1},
                {"deadline": time.monotonic() + 60},
            ):
                with self.assertRaises(AgentsAPIError):
                    transport.exchange(self.request(transport, **changes))
        self.assertEqual(self.h.connections, [])

    def test_wrong_credential_types_never_reach_socket(self):
        transports = (
            AdminReadOnlyHTTPS(
                binding(),
                credential_identity(),
                SyntheticStore(),
                connection_factory=Mock(),
                now=lambda: NOW,
            ),
            CanaryReadOnlyHTTPS(
                binding(), AdminStore(admin_identity()), connection_factory=Mock(), now=lambda: NOW
            ),
            HardenedHTTPS(
                binding(), AdminStore(admin_identity()), connection_factory=Mock(), now=lambda: NOW
            ),
        )
        for transport in transports:
            if type(transport) is HardenedHTTPS:
                request = WireRequest(
                    "GET",
                    "https://api.openai.com/v1/agents/sessions/synthetic",
                    (
                        ("OpenAI-Beta", "agents=v1"),
                        ("OpenAI-Project", binding().project_id),
                        ("Content-Type", "application/json"),
                    ),
                    None,
                    time.monotonic() + 4,
                    65536,
                )
            else:
                request = self.request(transport)
            with self.assertRaises(AgentsAPIError):
                transport.exchange(request)
            transport._factory.assert_not_called()

    def test_same_admin_canary_handle_or_ref_and_stale_admin_block(self):
        for changes in (
            {"handle_ref": self.h.identity.handle_ref},
            {"admin_ref": self.h.identity.credential_ref},
            {"project_id": "foreign"},
            {"binding_digest": "a" * 64},
            {"issued_at": NOW - 301},
            {"expires_at": NOW},
        ):
            transport = AdminReadOnlyHTTPS(
                binding(),
                credential_identity(),
                AdminStore(admin_identity(**changes)),
                connection_factory=Mock(),
                now=lambda: NOW,
            )
            with self.assertRaises(AgentsAPIError):
                transport.exchange(self.request(transport))
            transport._factory.assert_not_called()

    def test_canary_uses_same_immutable_identity_as_hardened_https(self):
        store = SyntheticStore(self.h.identity)
        readonly = CanaryReadOnlyHTTPS(binding(), store, now=lambda: NOW)
        hardened = HardenedHTTPS(binding(), store, now=lambda: NOW)
        self.assertIs(readonly.credential_identity, hardened.credential_identity)
        self.h.canary._transport._store = SyntheticStore(credential_identity(handle_ref="foreign"))
        self.assertIsNone(self.h.collector.read(self.h.bound, "agent_configuration"))
        self.assertEqual(self.h.connections, [])

    def test_dns_tls_timeout_errors_no_leak_retry_or_exception_context(self):
        for fault in (
            socket.gaierror(SYNTHETIC_SECRET),
            ssl.SSLError(SYNTHETIC_SECRET),
            TimeoutError(SYNTHETIC_SECRET),
            ConnectionError(SYNTHETIC_SECRET),
        ):
            self.h.fault = fault
            for transport in self.transports():
                before = len(self.h.connections)
                with self.assertRaises(AgentsAPIError) as caught:
                    transport.exchange(self.request(transport))
                self.assertNotIn(
                    SYNTHETIC_SECRET, "".join(traceback.format_exception(caught.exception))
                )
                self.assertIsNone(caught.exception.__context__)
                self.assertEqual(len(self.h.connections), before + 1)
                self.assertTrue(self.h.connections[-1].closed)
        self.assertEqual(self.h.calls, [])

    def test_response_limit_and_non_success_body_discard(self):
        for transport in self.transports():
            self.h.body = b"x" * 1024
            self.assertEqual(
                len(transport.exchange(self.request(transport, max_response_bytes=1024)).body), 1024
            )
            self.h.body = b"x" * 1025
            with self.assertRaises(AgentsAPIError):
                transport.exchange(self.request(transport, max_response_bytes=1024))
            for status in (301, 403, 429, 503):
                self.h.status, self.h.body = status, SYNTHETIC_SECRET.encode()
                self.assertEqual(transport.exchange(self.request(transport)), WireResponse(status))
            self.h.status = 200

    def test_dns_deadline_prevents_late_send_for_both_roles(self):
        for transport in self.transports():
            release, finished = threading.Event(), threading.Event()
            conn = self.h.factory("admin" if transport is self.h.admin._transport else "canary")

            def stalled_connect(release=release, finished=finished):
                release.wait(2)
                finished.set()

            conn.connect = stalled_connect
            transport._factory = Mock(return_value=conn)
            started = time.monotonic()
            with self.assertRaises(AgentsAPIError):
                transport.exchange(self.request(transport, deadline=started + 0.03))
            self.assertLess(time.monotonic() - started, 1)
            release.set()
            self.assertTrue(finished.wait(1))
            self.assertFalse(conn.sent)
            self.assertTrue(conn.closed)

    def test_read_deadline_bounds_stalled_response_for_both_roles(self):
        for transport in self.transports():
            release = threading.Event()
            conn = self.h.factory("admin" if transport is self.h.admin._transport else "canary")
            conn.getresponse = lambda release=release: release.wait(2)
            transport._factory = Mock(return_value=conn)
            with self.assertRaises(AgentsAPIError):
                transport.exchange(self.request(transport, deadline=time.monotonic() + 0.03))
            release.set()
            self.assertTrue(conn.closed)

    def test_header_limit_and_tls_proxy_are_inherited_without_override(self):
        # Existing test_agents_https tests the actual header parser and proxy/TLS.
        for transport in self.transports():
            self.assertIs(type(transport)._bounded, HardenedHTTPS._bounded)
            self.assertIs(type(transport)._connection, HardenedHTTPS._connection)

    def test_admin_private_fd_store_enforces_immutable_handle_and_sanitizes(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(ADMIN_MARKER.encode())
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            store = AdminFDSecretStore(stream.fileno(), admin_identity())
            self.assertEqual(
                store.with_authorization(admin_identity(), lambda _: WireResponse(204)),
                WireResponse(204),
            )
            self.assertNotIn(ADMIN_MARKER, repr(store))
            for identity in (credential_identity(), admin_identity(handle_ref="foreign")):
                with self.assertRaises(AgentsAPIError):
                    store.with_authorization(identity, lambda _: WireResponse(204))
            os.fchmod(stream.fileno(), 0o644)
            with self.assertRaises(AgentsAPIError):
                store.with_authorization(admin_identity(), lambda _: WireResponse(204))
            os.fchmod(stream.fileno(), 0o600)
            stream.seek(0)
            stream.write(b"changed")
            stream.flush()
            with self.assertRaises(AgentsAPIError):
                store.with_authorization(admin_identity(), lambda _: WireResponse(204))
        with self.assertRaises(AgentsAPIError):
            store.with_authorization(admin_identity(), lambda _: WireResponse(204))
        for descriptor in (-1, True, None):
            with self.assertRaises(AgentsAPIError):
                AdminFDSecretStore(descriptor, admin_identity())

    def test_admin_invalid_secret_material_or_store_callback_never_leaks(self):
        for data in (b"", b"x" * 513, b"invalid\r\nheader", b"\xff", ADMIN_MARKER.encode()):
            with tempfile.TemporaryFile() as stream:
                stream.write(data)
                stream.flush()
                store = AdminFDSecretStore(stream.fileno(), admin_identity())
                send = Mock(side_effect=ValueError(ADMIN_MARKER))
                with self.assertRaises(AgentsAPIError) as caught:
                    store.with_authorization(admin_identity(), send)
                self.assertNotIn(
                    ADMIN_MARKER, "".join(traceback.format_exception(caught.exception))
                )
                self.assertIsNone(caught.exception.__context__)
                if data != ADMIN_MARKER.encode():
                    send.assert_not_called()

    def test_two_roles_cannot_share_same_actual_fd(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(SYNTHETIC_SECRET.encode())
            stream.flush()
            self.h.admin._transport._store = AdminFDSecretStore(stream.fileno(), admin_identity())
            self.h.canary._transport._store = FDSecretStore(stream.fileno(), credential_identity())
            self.assertIsNone(self.h.collector.read(self.h.bound, "agent_configuration"))
            self.assertEqual(self.h.connections, [])
