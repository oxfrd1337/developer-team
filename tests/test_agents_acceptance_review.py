"""PR #35: immutable credential identity and independently supplied transport evidence."""

import contextlib
import io
import json
import os
import tempfile
import traceback
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from unittest.mock import Mock, patch

from developer_team.adapters.agents_api_contracts import AgentsAPIError, WireResponse
from developer_team.adapters.agents_credentials import CredentialIdentity
from developer_team.adapters.agents_https import FDSecretStore
from developer_team.agents_acceptance import AcceptanceController
from tests.acceptance_support import (
    SYNTHETIC_SECRET,
    AcceptanceHarness,
    SyntheticStore,
    bind_synthetic_route,
    credential_identity,
)
from tests.agents_api_support import NOW


class AcceptanceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = AcceptanceHarness(self.temp.name)
        self.addCleanup(self.h.connection.close)

    def use_store(self, store):
        self.h.controller = AcceptanceController(
            self.h.bound, self.h.connection, collector=self.h.collector, secret_store=store,
            operator_broker=self.h.broker, connection_factory=self.h.factory,
            now=lambda: self.h.clock,
        )
        bind_synthetic_route(self.h.collector, self.h.controller)

    def assert_blocked_before_network(self, check):
        report = self.h.controller.report()
        self.assertEqual(report["checks"][check], "MISSING_OR_INVALID")
        self.assertEqual(report["live"], "NO-GO")
        with self.assertRaises(AgentsAPIError):
            self.h.create()
        self.assertEqual(self.h.connections, [])
        self.assertEqual(self.h.count_posts(), 0)
        self.assertEqual(self.h.state().session_attempts, 0)

    def test_attested_key_a_cannot_authorize_store_key_b_in_same_project(self):
        self.use_store(SyntheticStore(credential_identity(credential_ref="key_other")))
        self.assert_blocked_before_network("account_project_binding")

    def test_matching_key_with_wrong_service_account_is_blocked(self):
        self.use_store(SyntheticStore(credential_identity(service_account_ref="sa_other")))
        self.assert_blocked_before_network("account_project_binding")

    def test_wrong_project_handle_or_binding_blocks(self):
        for changes in (
            {"project_id": "proj_other"}, {"handle_ref": "handle_other"},
            {"binding_digest": "b" * 64},
        ):
            with self.subTest(changes=changes):
                self.use_store(SyntheticStore(credential_identity(**changes)))
                self.assert_blocked_before_network("account_project_binding")

    def test_identity_missing_dict_with_extra_fields_or_subclass_is_rejected(self):
        class ExtendedIdentity(CredentialIdentity):
            extra = "unexpected"
        extra = {**asdict(credential_identity()), "extra": SYNTHETIC_SECRET}
        for identity in (None, extra, ExtendedIdentity(**asdict(credential_identity()))):
            self.use_store(SyntheticStore(identity))
            self.assert_blocked_before_network("account_project_binding")

    def test_old_future_expired_or_overlong_handle_identity_blocks(self):
        for changes in (
            {"issued_at": NOW - 301}, {"issued_at": NOW + 1}, {"issued_at": True},
            {"expires_at": NOW}, {"expires_at": NOW + 301},
        ):
            self.use_store(SyntheticStore(credential_identity(**changes)))
            self.assert_blocked_before_network("account_project_binding")

    def test_extra_or_old_account_identity_evidence_blocks(self):
        check = "account_project_binding"
        original = self.h.collector.observations[check]
        self.h.collector.drift(check, additional_credential_ref="key_other")
        self.assert_blocked_before_network(check)
        self.h.collector.observations[check] = replace(original, observed_at=NOW - 301)
        self.assert_blocked_before_network(check)

    def test_scope_and_store_evidence_are_bound_to_exact_handle_identity(self):
        for check in ("credential_scope", "secret_store"):
            original = self.h.collector.observations[check]
            self.h.collector.drift(check, credential_identity_digest="b" * 64)
            self.assert_blocked_before_network(check)
            self.h.collector.observations[check] = original

    def test_identity_and_fd_store_metadata_are_immutable(self):
        identity = credential_identity()
        with self.assertRaises(FrozenInstanceError):
            identity.credential_ref = "key_other"
        with tempfile.TemporaryFile() as stream:
            stream.write(SYNTHETIC_SECRET.encode())
            stream.flush()
            store = FDSecretStore(stream.fileno(), identity)
            with self.assertRaises(FrozenInstanceError):
                store.identity = credential_identity(credential_ref="key_other")
            with self.assertRaises(FrozenInstanceError):
                store._descriptor = -1

    def test_actual_fd_refuses_different_expected_credential_or_principal(self):
        with tempfile.TemporaryFile() as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(SYNTHETIC_SECRET.encode())
            stream.flush()
            store = FDSecretStore(stream.fileno(), credential_identity())
            send = Mock(return_value=WireResponse(204))
            for changes in ({"credential_ref": "key_other"}, {"service_account_ref": "sa_other"}):
                with self.assertRaises(AgentsAPIError):
                    store.with_authorization(credential_identity(**changes), send)
            send.assert_not_called()

    def test_fd_content_replacement_cannot_reuse_attested_handle_metadata(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(SYNTHETIC_SECRET.encode())
            stream.flush()
            store = FDSecretStore(stream.fileno(), credential_identity())
            stream.seek(0)
            stream.write(b"different-synthetic-key-material")
            stream.flush()
            send = Mock(return_value=WireResponse(204))
            with self.assertRaises(AgentsAPIError):
                store.with_authorization(credential_identity(), send)
            send.assert_not_called()

    def test_identity_expires_during_probe_and_blocks_gate(self):
        controller = self.h.controller
        class SlowStore:
            identity = credential_identity()
            def with_authorization(inner, identity, send):
                self.h.clock = NOW + 301
                return send("Bearer " + SYNTHETIC_SECRET)
        self.use_store(SlowStore())
        self.assert_blocked_before_network("account_project_binding")
        self.h.controller = controller

    def test_store_switch_after_review_blocks_before_any_create(self):
        self.h.broker.confirm(self.h.controller, "create_session")
        self.h.controller._transport._store = SyntheticStore(
            credential_identity(credential_ref="key_other")
        )
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("create_session")
        self.assertEqual(self.h.connections, [])

    def test_missing_real_transport_evidence_is_not_replaced_by_available_code(self):
        del self.h.collector.observations["real_transport"]
        self.assertEqual(self.h.controller.report()["checks"]["transport_implementation"], "PASS")
        self.assert_blocked_before_network("real_transport")

    def test_synthetic_readonly_transport_attestation_is_required_but_never_approval(self):
        report = self.h.controller.report()
        self.assertEqual(report["checks"]["real_transport"], "PASS")
        self.assertEqual(report["checks"]["fresh_create_approval"], "MISSING")
        self.assertEqual(report["checks"]["fresh_submit_approval"], "MISSING")
        self.assertEqual(report["live"], "NO-GO")
        self.assertEqual(self.h.connections, [])
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("create_session")
        self.assertEqual(self.h.count_posts(), 0)

    def test_transport_attestation_wrong_origin_project_key_principal_or_route_blocks(self):
        for changes in (
            {"origin": "https://other.example"}, {"origin": "http://api.openai.com"},
            {"project_id": "proj_other"}, {"credential_ref": "key_other"},
            {"service_account_ref": "sa_other"}, {"handle_ref": "handle_other"},
            {"credential_identity_digest": "b" * 64}, {"route_digest": "b" * 64},
        ):
            check = "real_transport"
            original = self.h.collector.observations[check]
            self.h.collector.drift(check, **changes)
            self.assert_blocked_before_network(check)
            self.h.collector.observations[check] = original

    def test_transport_attestation_tls_redirect_mutation_or_extra_claim_blocks(self):
        check = "real_transport"
        for changes in (
            {"tls_verified": False}, {"hostname_verified": False}, {"redirects_blocked": False},
            {"read_only": False}, {"probe_method": "POST"}, {"tls_verified": 1},
            {"response_text": SYNTHETIC_SECRET},
        ):
            original = self.h.collector.observations[check]
            self.h.collector.drift(check, **changes)
            self.assert_blocked_before_network(check)
            self.h.collector.observations[check] = original

    def test_transport_attestation_freshness_source_and_binding_are_required(self):
        check = "real_transport"
        original = self.h.collector.observations[check]
        for changes in (
            {"observed_at": NOW - 301}, {"expires_at": NOW}, {"observed_at": NOW + 1},
            {"source": "controlled_account_readonly"}, {"source": "local_implementation"},
            {"binding_digest": "b" * 64}, {"expires_at": NOW + 301},
        ):
            self.h.collector.observations[check] = replace(original, **changes)
            self.assert_blocked_before_network(check)
        self.h.collector.observations[check] = original

    def test_changed_transport_configuration_invalidates_route_attestation(self):
        self.h.controller._transport._connect_timeout = 1.0
        self.assert_blocked_before_network("real_transport")

    def test_revoked_transport_attestation_at_wire_blocks_first_post(self):
        self.h.broker.confirm(self.h.controller, "create_session")
        original = self.h.factory
        def make_connection(timeout):
            connection = original(timeout)
            def revoke():
                del self.h.collector.observations["real_transport"]
            connection.connect = revoke
            return connection
        self.h.controller._transport._factory = make_connection
        bind_synthetic_route(self.h.collector, self.h.controller)
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("create_session")
        self.assertEqual(self.h.count_posts(), 0)
        self.assertEqual(self.h.state().phase, "SESSION_UNCERTAIN")

    def test_invalid_identity_and_attestation_never_echo_secrets_or_logs(self):
        self.use_store(SyntheticStore({"unexpected_secret": SYNTHETIC_SECRET}))
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            report = json.dumps(self.h.controller.report())
            try:
                self.h.controller.execute("create_session")
            except AgentsAPIError as exc:
                error = "".join(traceback.format_exception(exc))
        for rendered in (report, error, stdout.getvalue(), stderr.getvalue()):
            self.assertNotIn(SYNTHETIC_SECRET, rendered)
            self.assertNotIn("Bearer ", rendered)
            self.assertNotIn("Authorization", rendered)
        self.assertEqual(self.h.connections, [])


    def test_fd_change_during_secret_read_is_detected_before_header_injection(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(SYNTHETIC_SECRET.encode())
            stream.flush()
            store = FDSecretStore(stream.fileno(), credential_identity())
            original = os.pread
            def changed(descriptor, size, offset):
                data = original(descriptor, size, offset)
                stream.seek(0)
                stream.write(b"different-synthetic-key-material")
                stream.flush()
                return data
            send = Mock(return_value=WireResponse(204))
            with patch("os.pread", side_effect=changed), self.assertRaises(AgentsAPIError):
                store.with_authorization(credential_identity(), send)
            send.assert_not_called()

    def test_different_wire_handle_requires_new_readonly_transport_attestation(self):
        self.h.controller._transport._factory = Mock()
        self.assert_blocked_before_network("real_transport")
