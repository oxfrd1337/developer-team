"""Controlled offline DT-017 acceptance and operator-halt regression matrix."""

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from developer_team.adapters.agents_api_contracts import AgentsAPIError
from developer_team.agents_acceptance import ACCOUNT_CHECKS, AcceptanceController, ReadOnlyVerifier
from tests.acceptance_support import (
    SYNTHETIC_SECRET,
    AcceptanceHarness,
    Collector,
    bind_synthetic_route,
)
from tests.agents_api_support import NOW, binding


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.h = AcceptanceHarness(self.temp.name)
        self.addCleanup(self.h.connection.close)

    def test_all_preconditions_pass_but_both_approvals_missing_and_no_go(self):
        report = self.h.controller.report()
        self.assertEqual(report["live"], "NO-GO")
        self.assertFalse(report["live_authorized"])
        for name, value in report["checks"].items():
            self.assertEqual(value, "MISSING" if name.startswith("fresh_") else "PASS", name)
        self.assertEqual(self.h.count_posts(), 0)
        self.assertEqual(self.h.connections, [])

    def test_default_controller_without_collectors_or_broker_is_blocked(self):
        controller = AcceptanceController(binding(), self.h.connection)
        self.assertEqual(controller.report()["checks"]["credential_scope"], "MISSING_OR_INVALID")
        with self.assertRaises(AgentsAPIError):
            controller.execute("create_session")
        self.assertEqual(self.h.count_posts(), 0)

    def test_review_always_halts_without_post_and_does_not_auto_approve(self):
        review = self.h.controller.review()
        self.assertEqual(len(review["challenge"]), 64)
        self.assertEqual(review["live"], "NO-GO")
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("create_session")
        self.assertEqual(self.h.connections, [])
        self.assertEqual(self.h.state().session_attempts, 0)

    def test_fresh_create_does_not_submit_and_session_persists_across_restart(self):
        result = self.h.create()
        self.assertEqual(result["phase"], "SESSION_READY")
        self.assertEqual(self.h.count_posts(), 1)
        self.h.controller = self.h.restart()
        self.assertEqual(self.h.state().message_attempts, 0)
        self.assertEqual(self.h.state().session_id, "session_synthetic")
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("submit_canary")
        self.assertEqual(self.h.count_posts(), 1)

    def test_submit_requires_new_review_and_session_bound_challenge(self):
        first = self.h.broker.confirm(self.h.controller, "create_session")
        self.h.controller.execute("create_session")
        second = self.h.broker.confirm(self.h.controller, "submit_canary")
        self.assertNotEqual(first["challenge"], second["challenge"])
        self.assertEqual(self.h.count_posts(), 1)
        result = self.h.controller.execute("submit_canary")
        self.assertEqual(result["phase"], "MESSAGE_ACCEPTED")
        self.assertEqual(self.h.count_posts(), 2)

    def test_unknown_submit_never_retries(self):
        self.h.create()
        self.h.broker.confirm(self.h.controller, "submit_canary")
        self.h.wire.faults["message"].append(TimeoutError(SYNTHETIC_SECRET))
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("submit_canary")
        self.assertEqual(self.h.state().phase, "MESSAGE_UNCERTAIN")
        with self.assertRaises(AgentsAPIError):
            self.h.submit()
        self.assertEqual(self.h.count_posts(), 2)
        self.assertEqual(self.h.controller.reconcile()["phase"], "TURN_BOUND")

    def test_unknown_create_only_reconciles_without_second_post(self):
        self.h.wire.faults["create"].append(TimeoutError(SYNTHETIC_SECRET))
        with self.assertRaises(AgentsAPIError):
            self.h.create()
        self.assertEqual(self.h.state().phase, "SESSION_UNCERTAIN")
        with self.assertRaises(AgentsAPIError):
            self.h.create()
        self.assertEqual(self.h.controller.reconcile()["phase"], "SESSION_READY")
        self.assertEqual(self.h.count_posts(), 1)

    def test_each_missing_observation_blocks(self):
        for check in ACCOUNT_CHECKS:
            with self.subTest(check=check):
                collector = Collector()
                del collector.observations[check]
                checks, _ = ReadOnlyVerifier(collector).inspect(binding(), NOW)
                self.assertEqual(checks[check], "MISSING_OR_INVALID")

    def test_stale_future_wrong_binding_source_or_verifier_blocks(self):
        for changes in (
            {"observed_at": NOW - 301},
            {"observed_at": NOW + 1},
            {"expires_at": NOW},
            {"expires_at": NOW + 301},
            {"binding_digest": "b" * 64},
            {"source": "saved_json"},
            {"verifier_ref": "sk-secret"},
            {"observed_at": True},
        ):
            for check in ACCOUNT_CHECKS:
                collector = Collector()
                collector.observations[check] = replace(collector.observations[check], **changes)
                self.assertEqual(
                    ReadOnlyVerifier(collector).inspect(binding(), NOW)[0][check],
                    "MISSING_OR_INVALID",
                )

    def test_extra_or_missing_facts_and_secret_fields_never_echo(self):
        for check in ACCOUNT_CHECKS:
            self.h.collector = Collector()
            self.h.collector.drift(check, secret=SYNTHETIC_SECRET)
            self.h.controller = self.h.restart()
            report = self.h.report_json()
            self.assertNotIn(SYNTHETIC_SECRET, report)
            self.assertEqual(json.loads(report)["checks"][check], "MISSING_OR_INVALID")

    def test_wrong_project_service_account_or_credential_mapping_blocks(self):
        for key, value in (
            ("project_id", "proj_other"),
            ("credential_project_id", "proj_other"),
            ("service_account_ref", None),
            ("credential_ref", None),
        ):
            self.h.collector = Collector()
            self.h.collector.drift("account_project_binding", **{key: value})
            self.h.controller = self.h.restart()
            with self.assertRaises(AgentsAPIError):
                self.h.create()
        self.assertEqual(self.h.connections, [])

    def test_key_principal_effective_scope_and_unnecessary_rights_block(self):
        for key, value in (
            ("key_capabilities", []),
            ("principal_capabilities", []),
            ("effective_capabilities", []),
            ("additional_permissions", ["files:write"]),
            ("additional_permissions", ["admin"]),
            ("additional_permissions", ["web"]),
        ):
            self.h.collector = Collector()
            self.h.collector.drift("credential_scope", **{key: value})
            self.h.controller = self.h.restart()
            with self.assertRaises(AgentsAPIError):
                self.h.create()
        self.assertEqual(self.h.connections, [])

    def test_spend_missing_stale_wrong_or_zero_blocks(self):
        for value in (None, 0, True, 101, "5"):
            self.h.collector = Collector()
            self.h.collector.drift("spend_controls", project_limit_cents=value)
            self.h.controller = self.h.restart()
            with self.assertRaises(AgentsAPIError):
                self.h.create()
        self.assertEqual(self.h.connections, [])

    def test_wrong_model_agent_digest_or_unavailable_model_blocks(self):
        for changes in (
            {"model": "other"},
            {"agent_id": "agent_other"},
            {"configuration_digest": "b" * 64},
            {"model_available": False},
            {"model_approved": False},
        ):
            self.h.collector = Collector()
            self.h.collector.drift("agent_configuration", **changes)
            self.h.controller = self.h.restart()
            with self.assertRaises(AgentsAPIError):
                self.h.create()
        self.assertEqual(self.h.connections, [])

    def test_environment_network_size_or_digest_drift_blocks(self):
        for changes in (
            {"network": "enabled"},
            {"container_size": "large"},
            {"configuration_digest": "b" * 64},
        ):
            self.h.collector = Collector()
            self.h.collector.drift("environment_configuration", **changes)
            self.h.controller = self.h.restart()
            with self.assertRaises(AgentsAPIError):
                self.h.create()
        self.assertEqual(self.h.connections, [])

    def test_session_environment_and_agent_drift_block_submit_review(self):
        self.h.create()
        self.h.wire.session["environment"]["network"]["access"] = "enabled"
        with self.assertRaises(AgentsAPIError):
            self.h.submit()
        self.assertEqual(self.h.count_posts(), 1)

    def test_old_wrong_operation_session_or_unverified_approval_blocks(self):
        for changes in (
            {"issued_at": NOW - 61},
            {"issued_at": NOW + 1},
            {"expires_at": NOW},
            {"operation": "submit_canary"},
            {"challenge": "b" * 64},
            {"binding_digest": "b" * 64},
            {"session_digest": "b" * 64},
            {"broker_verified": False},
            {"issued_at": True},
        ):
            self.h.broker.confirm(self.h.controller, "create_session")
            self.h.broker.approval = replace(self.h.broker.approval, **changes)
            with self.assertRaises(AgentsAPIError):
                self.h.controller.execute("create_session")
        self.assertEqual(self.h.connections, [])

    def test_new_review_invalidates_previously_signed_challenge(self):
        self.h.broker.confirm(self.h.controller, "create_session")
        self.h.controller.review()
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("create_session")
        self.assertEqual(self.h.connections, [])

    def test_revoked_approval_at_final_wire_boundary_prevents_post(self):
        self.h.broker.confirm(self.h.controller, "create_session")
        original = self.h.factory

        def revoked(timeout):
            conn = original(timeout)
            self.h.broker.approval = None
            return conn

        self.h.controller._transport._factory = revoked
        bind_synthetic_route(self.h.collector, self.h.controller)
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("create_session")
        self.assertEqual(self.h.count_posts(), 0)
        self.assertEqual(self.h.state().phase, "SESSION_UNCERTAIN")

    def test_deadline_approval_expiry_after_journal_blocks(self):
        self.h.broker.confirm(self.h.controller, "create_session")
        original = self.h.controller._journal.replace

        def delayed(bound, revision, state):
            original(bound, revision, state)
            self.h.clock = NOW + 61

        with patch.object(self.h.controller._journal, "replace", side_effect=delayed):
            with self.assertRaises(AgentsAPIError):
                self.h.controller.execute("create_session")
        self.assertEqual(self.h.count_posts(), 0)

    def test_collector_errors_and_slow_observations_fail_closed_without_echo(self):
        def bad(bound, check):
            raise ValueError(SYNTHETIC_SECRET)

        with patch.object(self.h.collector, "read", side_effect=bad):
            self.assertNotIn(SYNTHETIC_SECRET, self.h.report_json())
            with self.assertRaises(AgentsAPIError):
                self.h.create()
        original = self.h.collector.read

        def slow(bound, check):
            result = original(bound, check)
            self.h.clock += 50
            return result

        with patch.object(self.h.collector, "read", side_effect=slow):
            with self.assertRaises(AgentsAPIError):
                self.h.create()

    def test_memory_or_nondurable_journal_never_passes_gate(self):
        memory = sqlite3.connect(":memory:")
        self.addCleanup(memory.close)
        controller = AcceptanceController(binding(), memory, collector=Collector())
        controller.prepare()
        self.assertEqual(controller.report()["checks"]["durable_journal"], "MISSING")
        self.h.connection.execute("PRAGMA synchronous=OFF")
        self.assertEqual(self.h.controller.report()["checks"]["durable_journal"], "MISSING")

    def test_lost_or_mismatched_acceptance_slot_blocks_without_repreparing(self):
        self.h.connection.execute("DELETE FROM dt017_control")
        self.h.connection.commit()
        self.assertEqual(self.h.controller.report()["checks"]["durable_journal"], "MISSING")
        with self.assertRaises(AgentsAPIError):
            self.h.create()
        with self.assertRaises(AgentsAPIError):
            self.h.controller.prepare()
        self.assertEqual(self.h.connections, [])

    def test_cleanup_is_separate_durable_bounded_request_after_terminal_cost(self):
        with self.assertRaises(AgentsAPIError):
            self.h.controller.request_cleanup()
        self.h.create()
        self.h.submit()
        self.h.wire.turn_status = "completed"
        result = self.h.controller.reconcile()
        self.assertEqual(result["terminal_kind"], "agent.session.turn.completed")
        self.assertEqual(result["consumed_usd_cents_best_effort"], "0")
        before = self.h.count_posts()
        self.assertEqual(self.h.controller.request_cleanup()["cleanup"], "REQUESTED_NOT_CONFIRMED")
        self.h.controller = self.h.restart()
        with self.assertRaises(AgentsAPIError):
            self.h.controller.request_cleanup()
        self.assertEqual(self.h.count_posts(), before)

    def test_reports_contain_no_secrets_headers_ids_or_raw_provider_text(self):
        self.h.create()
        report = self.h.report_json()
        for text in (
            SYNTHETIC_SECRET,
            "Authorization",
            "Bearer",
            "session_synthetic",
            "sa_synthetic",
            "key_synthetic",
            "proj_synthetic",
            "agent_synthetic",
        ):
            self.assertNotIn(text, report)

    def test_no_general_operations_or_live_flags(self):
        for operation in ("live", "force", "activate", "deploy", "merge", "prompt", "DELETE"):
            with self.assertRaises(AgentsAPIError):
                self.h.controller.execute(operation)
            with self.assertRaises(AgentsAPIError):
                self.h.controller.review(operation)
        self.assertEqual(self.h.connections, [])

    def test_budget_exhaustion_prevents_submit_but_read_stays_available(self):
        self.h.create()
        self.h.wire.session["spend_control"]["consumed"] = 5
        with self.assertRaises(AgentsAPIError):
            self.h.submit()
        self.assertEqual(self.h.count_posts(), 1)
        self.assertEqual(self.h.controller.reconcile()["phase"], "SESSION_READY")

    def test_actual_secret_handle_missing_blocks_even_with_positive_attestation(self):
        self.h.controller._secret_store = None
        self.assertEqual(self.h.controller.report()["checks"]["secret_store"], "MISSING_OR_INVALID")
        with self.assertRaises(AgentsAPIError):
            self.h.create()
        self.assertEqual(self.h.connections, [])

    def test_separate_cancel_approval_and_stop_after_expired_start_evidence(self):
        self.h.create()
        self.h.submit()
        self.h.controller.reconcile()
        for check in ("single_canary_grant", "spend_controls"):
            del self.h.collector.observations[check]
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("cancel")
        self.h.broker.confirm(self.h.controller, "cancel")
        self.assertEqual(self.h.controller.execute("cancel")["phase"], "CANCEL_REQUESTED")
        self.h.wire.turn_status = "cancelled"
        self.assertEqual(
            self.h.controller.reconcile()["terminal_kind"], "agent.session.turn.cancelled"
        )

    def test_agent_drift_between_submit_review_and_execution_blocks_post(self):
        self.h.create()
        self.h.broker.confirm(self.h.controller, "submit_canary")
        self.h.wire.session["agent"]["model"] = "synthetic-other-model"
        with self.assertRaises(AgentsAPIError):
            self.h.controller.execute("submit_canary")
        self.assertEqual(self.h.count_posts(), 1)

    def test_complete_read_poll_budget_remains_bounded(self):
        self.h.create()
        self.h.submit()
        for _ in range(20):
            try:
                self.h.controller.reconcile()
            except AgentsAPIError:
                break
        self.assertLessEqual(self.h.state().request_count, self.h.controller._limits.max_requests)
        self.assertEqual(self.h.count_posts(), 2)

    def test_fresh_observation_cannot_extend_expired_or_future_external_grant(self):
        for changes in ({"expires_at": NOW}, {"issued_at": NOW + 1}, {"issued_at": NOW - 3601}):
            self.h.collector = Collector()
            self.h.collector.drift("single_canary_grant", **changes)
            self.h.controller = self.h.restart()
            with self.assertRaises(AgentsAPIError):
                self.h.create()
        self.assertEqual(self.h.connections, [])

    def test_changed_limits_do_not_pass_durable_journal_gate(self):
        from developer_team.adapters.agents_api_contracts import AgentsAPILimits

        self.h.controller._limits = AgentsAPILimits(max_requests=20)
        self.assertEqual(self.h.controller.report()["checks"]["durable_journal"], "MISSING")
        with self.assertRaises(AgentsAPIError):
            self.h.create()
