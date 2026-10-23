"""DT-016 contract and negative matrix: all provider traffic is a wire fixture."""

import contextlib
import io
import json
import threading
import traceback
import unittest
from dataclasses import asdict
from unittest.mock import Mock, patch

from developer_team.adapters.agents_api import AgentsAPIAdapter
from developer_team.adapters.agents_api_contracts import (
    CANARY_MESSAGE,
    MINIMAL_CAPABILITIES,
    PROVIDER_BASE,
    AgentsAPIError,
    AgentsAPILimits,
    WireResponse,
    sha256,
)
from developer_team.agents_canary_capsule import synthetic_reference_capsule
from developer_team.agents_live_preflight import (
    evaluate_agents_live_preflight,
    synthetic_reference_plan,
)
from developer_team.agents_readonly_verification import (
    evaluate_readonly_evidence,
    synthetic_reference_evidence,
)
from tests.agents_api_support import (
    NOW,
    SESSION,
    TURN,
    FixtureGate,
    Harness,
    binding,
    page,
    permit,
    response,
)

MESSAGE = "agent.session.input.message"
CANCEL = "agent.session.input.cancel"
SENSITIVE_MARKER = "sk-sensitive-marker-must-never-leak"


class AgentsAPIContractTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.connection.close)

    def blocked(self, operation, reason=None):
        with self.assertRaises(AgentsAPIError) as caught:
            operation()
        if reason:
            self.assertIn(reason, str(caught.exception))
        self.assertNotIn(SENSITIVE_MARKER, str(caught.exception))
        return caught.exception

    def test_default_disables_every_provider_operation_before_journal_or_transport(self):
        journal = Mock()
        adapter = AgentsAPIAdapter(binding(), journal)
        adapter.enabled = True
        adapter.live_authorized = True
        for operation in (
            adapter.create_session,
            adapter.submit_canary,
            adapter.reconcile,
            adapter.cancel,
        ):
            self.blocked(operation, "disabled")
        journal.assert_not_called()
        self.assertEqual(journal.mock_calls, [])

    def test_missing_either_external_gate_or_transport_blocks(self):
        for changes in ({"gate": None}, {"transport": None}):
            with self.subTest(changes=list(changes)):
                self.blocked(self.h.restart(**changes).create_session, "disabled")
        self.assertEqual(self.h.transport.calls, [])

    def test_offline_reports_and_structural_capsule_are_not_external_authority(self):
        values = (
            synthetic_reference_capsule(NOW),
            evaluate_agents_live_preflight(synthetic_reference_plan()),
            evaluate_readonly_evidence(
                synthetic_reference_evidence(NOW),
                expected_project_ref="synthetic-test-project",
                now=NOW,
            ),
            {**asdict(permit()), "live_authorized": True},
        )
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                self.h.gate.value = value
                self.blocked(self.h.adapter.create_session, "external_authorization")
        self.assertEqual(self.h.transport.calls, [])

    def test_create_has_no_message_stream_or_undocumented_idempotency(self):
        report = self.h.adapter.create_session()
        request = self.h.transport.posts("create")[0]
        payload = json.loads(request.body)
        self.assertEqual(request.url, PROVIDER_BASE + "/v1/agents/sessions")
        self.assertNotIn("input", payload)
        self.assertNotIn("events", payload)
        self.assertIs(payload["stream"], False)
        self.assertNotIn("Idempotency-Key", dict(request.headers))
        self.assertEqual(payload["spend_control"], {"limit": 5})
        self.assertEqual(payload["agent_id"], self.h.binding.agent_id)
        self.assertEqual(payload["agent"]["tools"], [])
        self.assertFalse(payload["agent"]["multi_agent"]["enabled"])
        self.assertEqual(payload["metadata"], {"dt016_binding": self.h.binding.digest})
        self.assertEqual(report["phase"], "SESSION_READY")
        self.assertEqual(report["logical_message_attempts"], 0)
        self.assertEqual(self.h.state().session_id, SESSION)
        self.assertIsNone(self.h.state().turn_id)

    def test_message_is_separate_fixed_and_submitted_exactly_once_across_restart(self):
        self.h.adapter.create_session()
        self.assertEqual(self.h.transport.posts(MESSAGE), [])
        self.h.restart().submit_canary()
        request = self.h.transport.posts(MESSAGE)[0]
        self.assertEqual(dict(request.headers)["Idempotency-Key"], self.h.binding.idempotency_key)
        self.assertEqual(dict(request.headers)["OpenAI-Project"], self.h.binding.project_id)
        self.assertEqual(dict(request.headers)["OpenAI-Beta"], "agents=v1")
        self.assertEqual(
            json.loads(request.body),
            {
                "events": [
                    {
                        "type": MESSAGE,
                        "input": [
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": CANARY_MESSAGE}],
                            }
                        ],
                    }
                ]
            },
        )
        self.blocked(self.h.restart().submit_canary, "already_attempted")
        self.blocked(self.h.restart().create_session, "already_attempted")
        self.assertEqual(len(self.h.transport.posts(MESSAGE)), 1)
        self.assertEqual(len(self.h.transport.posts("create")), 1)

    def test_no_free_prompt_or_task_parameter_exists(self):
        for args in (
            {"prompt": SENSITIVE_MARKER},
            {"task": "different task"},
            {"message": "different message"},
        ):
            with self.assertRaises(TypeError):
                self.h.adapter.submit_canary(**args)
        self.assertEqual(self.h.transport.calls, [])

    def test_write_ahead_binding_and_counters_exist_before_each_mutation(self):
        observed = []

        def inspect(operation, request):
            state = self.h.state()
            if operation in {"create", "message", "cancel"}:
                observed.append(
                    (
                        operation,
                        state.phase,
                        state.session_id,
                        state.idempotency_key,
                        state.message_digest,
                        state.request_count,
                    )
                )

        self.h.transport.before_response = inspect
        self.h.active().cancel()
        self.assertEqual(
            [v[:2] for v in observed],
            [
                ("create", "SESSION_UNCERTAIN"),
                ("message", "MESSAGE_UNCERTAIN"),
                ("cancel", "CANCEL_UNCERTAIN"),
            ],
        )
        for operation, _, session, key, digest, count in observed:
            self.assertEqual(key, self.h.binding.idempotency_key)
            self.assertEqual(digest, sha256(CANARY_MESSAGE))
            self.assertGreater(count, 0)
            if operation != "create":
                self.assertEqual(session, SESSION)

    def test_session_timeout_never_recreates_and_recovers_read_only(self):
        self.h.transport.faults["create"].append(TimeoutError(SENSITIVE_MARKER))
        self.blocked(self.h.adapter.create_session)
        self.assertEqual(self.h.state().phase, "SESSION_UNCERTAIN")
        self.blocked(self.h.restart().create_session, "already_attempted")
        before = len(self.h.transport.calls)
        report = self.h.restart().reconcile()
        self.assertEqual(report["phase"], "SESSION_READY")
        self.assertTrue(all(r.method == "GET" for r in self.h.transport.calls[before:]))
        self.assertEqual(len(self.h.transport.posts("create")), 1)
        self.assertEqual(self.h.transport.posts(MESSAGE), [])
        self.h.restart().submit_canary()
        self.assertEqual(len(self.h.transport.posts(MESSAGE)), 1)

    def test_session_reconstruction_zero_or_duplicate_matches_requires_operator(self):
        self.h.transport.faults["create"].append(TimeoutError())
        self.blocked(self.h.adapter.create_session)
        for records in ([], [self.h.transport.session, self.h.transport.session]):
            self.h.transport.faults["list"].append(response(page(records)))
            self.blocked(self.h.restart().reconcile, "requires_operator")
            self.assertIsNone(self.h.state().session_id)
        self.blocked(self.h.restart().create_session)
        self.assertEqual(len(self.h.transport.posts("create")), 1)

    def test_unrelated_session_metadata_does_not_reconstruct(self):
        self.h.transport.faults["create"].append(TimeoutError())
        self.blocked(self.h.adapter.create_session)
        self.h.transport.session["metadata"] = {"dt016_binding": "b" * 64}
        self.blocked(self.h.adapter.reconcile, "requires_operator")

    def test_unknown_creation_with_an_existing_turn_never_binds(self):
        self.h.transport.faults["create"].append(TimeoutError())
        self.blocked(self.h.adapter.create_session)
        self.h.transport.turn_status = "in_progress"
        self.blocked(self.h.adapter.reconcile, "unexpected_or_multiple_turns")
        self.assertIsNone(self.h.state().session_id)

    def test_lost_message_response_reconciles_without_any_repeat(self):
        self.h.adapter.create_session()
        self.h.transport.faults["message"].append(TimeoutError(SENSITIVE_MARKER))
        self.blocked(self.h.adapter.submit_canary)
        self.assertEqual(self.h.state().phase, "MESSAGE_UNCERTAIN")
        self.blocked(self.h.restart().submit_canary, "already_attempted")
        before = len(self.h.transport.calls)
        report = self.h.restart().reconcile()
        self.assertEqual(report["phase"], "TURN_BOUND")
        self.assertEqual(self.h.state().turn_id, TURN)
        self.assertTrue(all(r.method == "GET" for r in self.h.transport.calls[before:]))
        self.assertEqual(len(self.h.transport.posts(MESSAGE)), 1)

    def test_missing_turn_after_lost_message_is_unknown_not_permission_to_resubmit(self):
        self.h.adapter.create_session()
        self.h.transport.faults["message"].append(ConnectionError(SENSITIVE_MARKER))
        self.blocked(self.h.adapter.submit_canary)
        self.h.transport.turn_status = None
        report = self.h.restart().reconcile()
        self.assertEqual(report["phase"], "MESSAGE_UNCERTAIN")
        self.assertIsNone(report["terminal_kind"])
        self.blocked(self.h.restart().submit_canary)

    def test_202_and_idle_without_turn_are_not_terminal_evidence(self):
        self.h.adapter.create_session()
        report = self.h.adapter.submit_canary()
        self.assertEqual(report["phase"], "MESSAGE_ACCEPTED")
        self.assertIsNone(report["terminal_kind"])
        self.h.transport.turn_status = None
        self.assertEqual(self.h.adapter.reconcile()["phase"], "MESSAGE_ACCEPTED")

    def test_all_three_terminal_kinds_remain_distinct(self):
        for status in ("completed", "failed", "cancelled"):
            with self.subTest(status=status):
                h = Harness()
                self.addCleanup(h.connection.close)
                h.adapter.create_session()
                h.adapter.submit_canary()
                h.transport.turn_status = status
                report = h.adapter.reconcile()
                self.assertEqual(report["terminal_kind"], "agent.session.turn." + status)
                self.assertEqual(report["phase"], "TERMINAL")
                self.assertEqual(report["live"], "NO-GO")

    def test_cancel_acceptance_is_not_cancel_confirmation(self):
        report = self.h.active().cancel()
        self.assertTrue(report["cancel_requested"])
        self.assertEqual(report["phase"], "CANCEL_REQUESTED")
        self.assertIsNone(report["terminal_kind"])
        request = self.h.transport.posts(CANCEL)[0]
        self.assertEqual(json.loads(request.body), {"events": [{"type": CANCEL}]})
        self.assertNotIn("Idempotency-Key", dict(request.headers))
        self.h.transport.turn_status = "completed"
        self.assertEqual(
            self.h.adapter.reconcile()["terminal_kind"], "agent.session.turn.completed"
        )

    def test_lost_cancel_response_is_not_retried_or_claimed_terminal(self):
        self.h.active()
        self.h.transport.faults["cancel"].append(TimeoutError(SENSITIVE_MARKER))
        self.blocked(self.h.adapter.cancel)
        self.assertEqual(self.h.state().phase, "CANCEL_UNCERTAIN")
        self.blocked(self.h.restart().cancel, "already_attempted")
        self.assertIsNone(self.h.adapter.reconcile()["terminal_kind"])
        self.h.transport.turn_status = "cancelled"
        self.assertEqual(
            self.h.adapter.reconcile()["terminal_kind"], "agent.session.turn.cancelled"
        )
        self.assertEqual(len(self.h.transport.posts(CANCEL)), 1)

    def test_cancel_requires_known_active_original_turn_and_is_not_sent_after_terminal(self):
        self.blocked(self.h.adapter.cancel, "out_of_order")
        self.h.active()
        self.h.transport.turn_status = "failed"
        self.blocked(self.h.adapter.cancel, "already_terminal")
        self.assertEqual(self.h.transport.posts(CANCEL), [])

    def test_changed_turn_session_agent_or_subagent_binding_blocks(self):
        self.h.active()
        original = dict(self.h.transport.turn)
        for field, value in (
            ("session_id", "session_foreign"),
            ("agent_id", "agent_foreign"),
            ("id", "turn_foreign"),
            ("subagent_id", "subagent_foreign"),
            ("object", "wrong"),
        ):
            with self.subTest(field=field):
                self.h.transport.turn = {**original, field: value}
                self.blocked(self.h.adapter.reconcile, "turn_binding")
        self.assertEqual(self.h.state().turn_id, TURN)

    def test_multiple_or_paginated_turns_cannot_pick_a_convenient_result(self):
        self.h.adapter.create_session()
        self.h.adapter.submit_canary()
        turn = {**self.h.transport.turn, "status": "completed"}
        for value in (page([turn, turn]), page([turn], has_more=True)):
            self.h.transport.faults["turns"].append(response(value))
            self.blocked(self.h.adapter.reconcile)
        self.assertIsNone(self.h.state().turn_id)

    def test_unknown_or_nonstring_turn_status_fails_closed(self):
        self.h.adapter.create_session()
        self.h.adapter.submit_canary()
        for status in ("idle", "succeeded", {}, None, True):
            self.h.transport.faults["turns"].append(
                response(page([{**self.h.transport.turn, "status": status}]))
            )
            self.blocked(self.h.adapter.reconcile, "turn_binding")

    def test_terminal_conflict_regression_or_disappearance_blocks(self):
        self.h.active()
        self.h.transport.turn_status = "completed"
        self.h.adapter.reconcile()
        self.assertEqual(
            self.h.adapter.reconcile()["terminal_kind"], "agent.session.turn.completed"
        )
        for status in ("failed", "in_progress", None):
            self.h.transport.turn_status = status
            self.blocked(self.h.adapter.reconcile)
        self.assertEqual(self.h.state().terminal_kind, "agent.session.turn.completed")

    def test_report_exposes_no_provider_text_headers_or_authority(self):
        self.h.active()
        self.h.transport.session["error"] = SENSITIVE_MARKER
        self.h.adapter.reconcile()
        rendered = json.dumps(self.h.adapter.report())
        for value in (
            SENSITIVE_MARKER,
            SESSION,
            TURN,
            self.h.binding.idempotency_key,
            "Authorization",
        ):
            self.assertNotIn(value, rendered)
        for key in (
            "live_authorized",
            "github_write_authorized",
            "repository_write_authorized",
            "merge_authorized",
        ):
            self.assertIs(self.h.adapter.report()[key], False)


class AgentsAPIGateTests(unittest.TestCase):
    def assert_gate_blocks(self, **changes):
        h = Harness()
        self.addCleanup(h.connection.close)
        h.gate.value = permit(**changes)
        with self.assertRaises(AgentsAPIError):
            h.adapter.create_session()
        self.assertEqual(h.transport.calls, [])
        self.assertEqual(h.state().phase, "PREPARED")

    def test_project_credential_agent_provider_and_intent_are_bound(self):
        for changes in (
            {"project_id": "proj_other"},
            {"credential_project_id": "proj_other"},
            {"agent_id": "agent_other"},
            {"provider_base": "https://example.com"},
            {"binding_digest": "b" * 64},
        ):
            with self.subTest(changes=changes):
                self.assert_gate_blocks(**changes)

    def test_key_permissions_and_project_rights_must_both_be_minimal(self):
        for field in ("key_capabilities", "project_capabilities"):
            for scope in (
                frozenset(),
                frozenset({"session:read"}),
                MINIMAL_CAPABILITIES | {"admin"},
                MINIMAL_CAPABILITIES - {"cancel:request"},
                set(MINIMAL_CAPABILITIES),
                True,
            ):
                with self.subTest(field=field, scope_type=type(scope).__name__):
                    self.assert_gate_blocks(**{field: scope})

    def test_spend_proof_and_positive_bounded_project_limit_are_required(self):
        self.assert_gate_blocks(spend_controls_verified=False)
        for limit in (None, 0, 4, True, 5.0, 101):
            with self.subTest(limit=limit):
                self.assert_gate_blocks(project_hard_limit_cents=limit)

    def test_account_source_secret_store_agent_safety_and_contract_are_required(self):
        self.assert_gate_blocks(source="official_documentation")
        for field in ("secret_store_verified", "contract_verified", "agent_configuration_verified"):
            with self.subTest(field=field):
                self.assert_gate_blocks(**{field: False})

    def test_stale_future_overlong_or_noninteger_evidence_blocks(self):
        for changes in (
            {"expires_at": NOW},
            {"observed_at": NOW + 1},
            {"observed_at": NOW - 3601},
            {"expires_at": NOW + 3601},
            {"observed_at": True},
            {"expires_at": None},
        ):
            with self.subTest(changes=changes):
                self.assert_gate_blocks(**changes)

    def test_missing_wrong_expired_or_excessive_operator_grant_blocks(self):
        for changes in (
            {"operator_grant_verified": False},
            {"grant_binding_digest": "b" * 64},
            {"grant_budget_cents": 4},
            {"grant_budget_cents": True},
            {"grant_expires_at": NOW},
            {"grant_issued_at": NOW + 1},
            {"grant_expires_at": NOW + 3601},
        ):
            with self.subTest(changes=changes):
                self.assert_gate_blocks(**changes)

    def test_submit_requires_renewed_immediate_approval_even_after_session_creation(self):
        for approval in (None, NOW - 61, NOW + 1, True):
            h = Harness()
            self.addCleanup(h.connection.close)
            h.adapter.create_session()
            h.gate.value = permit(submit_approved_at=approval)
            with self.assertRaisesRegex(AgentsAPIError, "fresh_first_submit_approval"):
                h.adapter.submit_canary()
            self.assertEqual(h.transport.posts(MESSAGE), [])
            self.assertEqual(h.state().message_attempts, 0)

    def test_submit_rechecks_authority_after_read_only_preparation(self):
        h = Harness()
        self.addCleanup(h.connection.close)
        h.adapter.create_session()

        def revoke(operation, request):
            if operation == "turns":
                h.gate.value = permit(submit_approved_at=None)

        h.transport.before_response = revoke
        with self.assertRaisesRegex(AgentsAPIError, "fresh_first_submit_approval"):
            h.adapter.submit_canary()
        self.assertEqual(h.transport.posts(MESSAGE), [])

    def test_local_budget_exhaustion_and_overspend_block_message(self):
        for consumed in (5, 6):
            h = Harness()
            self.addCleanup(h.connection.close)
            h.adapter.create_session()
            h.transport.session["spend_control"]["consumed"] = consumed
            with self.assertRaisesRegex(AgentsAPIError, "within_budget"):
                h.adapter.submit_canary()
            self.assertEqual(h.transport.posts(MESSAGE), [])

    def test_read_and_cancel_survive_expired_start_grant_and_budget_exhaustion(self):
        h = Harness()
        self.addCleanup(h.connection.close)
        h.active()
        h.gate.value = permit(
            grant_expires_at=NOW, submit_approved_at=None, spend_controls_verified=False
        )
        h.transport.session["spend_control"]["consumed"] = 6
        report = h.adapter.cancel()
        self.assertTrue(report["budget_exceeded"])
        self.assertIsNone(report["terminal_kind"])
        h.transport.turn_status = "cancelled"
        self.assertEqual(h.adapter.reconcile()["terminal_kind"], "agent.session.turn.cancelled")

    def test_budget_observation_is_best_effort_separate_from_terminal_and_tokens(self):
        h = Harness()
        self.addCleanup(h.connection.close)
        h.active()
        h.transport.session["spend_control"]["consumed"] = 0.25
        h.transport.session["usage"] = {"total_tokens": 999999}
        report = h.adapter.reconcile()
        self.assertEqual(report["consumed_usd_cents_best_effort"], "0.25")
        self.assertIsNone(report["terminal_kind"])


class AgentsAPITransportSafetyTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.connection.close)

    def test_401_403_429_and_5xx_never_retry_any_mutation(self):
        for operation in ("create", "message", "cancel"):
            for status in (401, 403, 429, 500, 503):
                with self.subTest(operation=operation, status=status):
                    h = Harness()
                    self.addCleanup(h.connection.close)
                    if operation == "message":
                        h.adapter.create_session()
                    elif operation == "cancel":
                        h.active()
                    h.transport.faults[operation].append(
                        WireResponse(status, SENSITIVE_MARKER.encode())
                    )
                    action = {
                        "create": h.adapter.create_session,
                        "message": h.adapter.submit_canary,
                        "cancel": h.adapter.cancel,
                    }[operation]
                    with self.assertRaises(AgentsAPIError) as caught:
                        action()
                    self.assertNotIn(SENSITIVE_MARKER, str(caught.exception))
                    before = len(h.transport.calls)
                    with self.assertRaises(AgentsAPIError):
                        action()
                    self.assertEqual(len(h.transport.calls), before)
                    self.assertTrue(h.state().phase.endswith("UNCERTAIN"))

    def test_read_failures_keep_binding_and_do_not_resubmit(self):
        self.h.active()
        for status in (401, 403, 429, 500, 503):
            self.h.transport.faults["session"].append(
                WireResponse(status, SENSITIVE_MARKER.encode())
            )
            with self.assertRaises(AgentsAPIError):
                self.h.adapter.reconcile()
        self.assertEqual(self.h.state().turn_id, TURN)
        self.assertEqual(len(self.h.transport.posts(MESSAGE)), 1)

    def test_raw_transport_gate_and_journal_exceptions_never_leak(self):
        operations = []
        self.h.transport.faults["create"].append(RuntimeError(SENSITIVE_MARKER))
        operations.append(self.h.adapter.create_session)
        gate_adapter = self.h.restart(gate=FixtureGate(RuntimeError(SENSITIVE_MARKER)))
        operations.append(gate_adapter.create_session)
        journal = Mock()
        journal.load.side_effect = RuntimeError(SENSITIVE_MARKER)
        operations.append(
            AgentsAPIAdapter(
                binding(), journal, transport=self.h.transport, gate=self.h.gate, now=lambda: NOW
            ).create_session
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            for operation in operations:
                try:
                    operation()
                except AgentsAPIError:
                    traceback.print_exc()
        self.assertNotIn(SENSITIVE_MARKER, output.getvalue())
        self.assertNotIn(SENSITIVE_MARKER, json.dumps(self.h.adapter.report()))

    def test_provider_response_and_event_byte_limits(self):
        for fault in (
            WireResponse(201, b"x" * 65537),
            response({**self.h.transport.session, "error": "x" * 8192}, 201),
        ):
            h = Harness()
            self.addCleanup(h.connection.close)
            h.transport.faults["create"].append(fault)
            with self.assertRaisesRegex(AgentsAPIError, "size_exceeded"):
                h.adapter.create_session()
            self.assertEqual(h.state().phase, "SESSION_UNCERTAIN")

    def test_invalid_utf8_json_duplicates_constants_and_nonobjects_are_sanitized(self):
        for raw in (
            b"\xff",
            b"{",
            b"[]",
            b"true",
            b'{"id":1,"id":2}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            ('{"error":"' + SENSITIVE_MARKER).encode(),
            b"[" * 1100,
        ):
            h = Harness()
            self.addCleanup(h.connection.close)
            h.transport.faults["create"].append(WireResponse(201, raw))
            with self.assertRaises(AgentsAPIError) as caught:
                h.adapter.create_session()
            self.assertNotIn(SENSITIVE_MARKER, str(caught.exception))

    def test_record_field_and_page_count_limits_are_enforced(self):
        self.h.transport.faults["create"].append(TimeoutError())
        with self.assertRaises(AgentsAPIError):
            self.h.adapter.create_session()
        for value in (
            page([{}] * 21),
            page([], has_more=True),
            {"object": "list", "data": {}, "has_more": False},
            {**page([]), **{f"extra_{i}": i for i in range(65)}},
        ):
            self.h.transport.faults["list"].append(response(value))
            with self.assertRaises(AgentsAPIError):
                self.h.adapter.reconcile()

    def test_malformed_session_binding_safety_or_spend_controls_never_unlock_message(self):
        cases = (
            {"id": SENSITIVE_MARKER},
            {"id": "bad/id"},
            {"metadata": {}},
            {"project_id": "proj_foreign"},
            {"agent": None},
            {"environment": None},
            {"status": {}},
            {"vault_ids": ["private"]},
            {"spend_control": None},
            {"spend_control": {"limit": 6, "consumed": 0}},
            {"spend_control": {"limit": True, "consumed": 0}},
            {"spend_control": {"limit": 5, "consumed": True}},
            {"spend_control": {"limit": 5, "consumed": -1}},
            {"spend_control": {"limit": 5, "consumed": "0"}},
        )
        for changes in cases:
            h = Harness()
            self.addCleanup(h.connection.close)
            h.transport.session.update(changes)
            with self.assertRaises(AgentsAPIError) as caught:
                h.adapter.create_session()
            self.assertNotIn(SENSITIVE_MARKER, str(caught.exception))
            self.assertEqual(h.transport.posts(MESSAGE), [])

    def test_enabled_tools_or_subagents_and_nonidle_creation_are_rejected(self):
        for changes in (
            {"tools": [{"type": "shell"}]},
            {"multi_agent": {"enabled": True}},
            {"multi_agent": None},
            {"instructions": "free task"},
            {"id": "agent_other"},
        ):
            h = Harness()
            self.addCleanup(h.connection.close)
            h.transport.session["agent"].update(changes)
            with self.assertRaises(AgentsAPIError):
                h.adapter.create_session()
        for changes in (
            {"status": "in_progress"},
            {"required_actions": [{"type": "function_call"}]},
        ):
            h = Harness()
            self.addCleanup(h.connection.close)
            h.transport.session.update(changes)
            with self.assertRaisesRegex(AgentsAPIError, "empty_and_idle"):
                h.adapter.create_session()

    def test_wrong_provider_ack_status_or_response_types_fail_closed(self):
        for fault in (
            WireResponse(200),
            WireResponse(True),
            WireResponse(302),
            WireResponse(201, SENSITIVE_MARKER),
            {"status": 201},
            None,
        ):
            h = Harness()
            self.addCleanup(h.connection.close)
            h.transport.faults["create"].append(fault)
            with self.assertRaises(AgentsAPIError):
                h.adapter.create_session()

    def test_late_response_fails_closed_and_propagates_deadline_and_byte_cap(self):
        adapter = self.h.restart(monotonic=Mock(side_effect=[100.0, 106.0]))
        with self.assertRaisesRegex(AgentsAPIError, "timeout"):
            adapter.create_session()
        request = self.h.transport.calls[0]
        self.assertEqual(request.deadline, 105.0)
        self.assertEqual(request.max_response_bytes, 65536)
        self.assertEqual(self.h.state().phase, "SESSION_UNCERTAIN")

    def test_stalled_injected_transport_has_a_hard_caller_wait_limit(self):
        released = threading.Event()
        finished = threading.Event()

        def stall(operation, request):
            released.wait(3)
            finished.set()

        h = Harness(limits=AgentsAPILimits(timeout_seconds=1))
        self.addCleanup(h.connection.close)
        h.transport.before_response = stall
        adapter = h.adapter
        try:
            with self.assertRaisesRegex(AgentsAPIError, "timeout"):
                adapter.create_session()
            self.assertFalse(finished.is_set())
            with self.assertRaises(AgentsAPIError):
                h.restart().create_session()
        finally:
            released.set()
            self.assertTrue(finished.wait(2))
        self.assertEqual(len(h.transport.calls), 1)

    def test_request_budget_is_persisted_and_not_reset_on_restart(self):
        h = Harness(limits=AgentsAPILimits(max_requests=7))
        self.addCleanup(h.connection.close)
        h.adapter.create_session()
        for _ in range(3):
            h.restart().reconcile()
        limited = h.restart()
        with self.assertRaisesRegex(AgentsAPIError, "budget_exhausted"):
            limited.reconcile()
        self.assertEqual(h.state().request_count, 7)
        self.assertEqual(len(h.transport.calls), 7)

    def test_invalid_limits_and_bindings_are_rejected_before_any_io(self):
        for changes in (
            {"timeout_seconds": 0},
            {"timeout_seconds": 31},
            {"timeout_seconds": True},
            {"response_bytes": 65537},
            {"event_bytes": 8193},
            {"max_records": 21},
            {"max_requests": 33},
            {"response_bytes": 1024, "event_bytes": 8192},
        ):
            with self.assertRaises(AgentsAPIError):
                self.h.restart(limits=AgentsAPILimits(**changes))
        for changes in (
            {"provider_base": "https://example.com"},
            {"project_id": SENSITIVE_MARKER},
            {"agent_id": "bad/id"},
            {"idempotency_key": "x" * 97},
            {"budget_cents": True},
            {"budget_cents": 101},
            {"plan_digest": "wrong"},
        ):
            with self.assertRaises(AgentsAPIError):
                AgentsAPIAdapter(binding(**changes), self.h.journal)
        self.assertEqual(self.h.transport.calls, [])

    def test_only_injected_fixture_is_used_no_network_process_files_or_environment(self):
        with (
            patch("socket.socket") as network,
            patch("subprocess.Popen") as process,
            patch("builtins.open") as files,
            patch("os.getenv") as env,
            patch("developer_team.adapters.github.GitHubPRWriter.open") as github_write,
        ):
            self.h.active().cancel()
            self.h.transport.turn_status = "cancelled"
            self.h.adapter.reconcile()
        for mock in (network, process, files, env, github_write):
            mock.assert_not_called()
        self.assertTrue(
            all(
                r.url.startswith(PROVIDER_BASE + "/v1/agents/sessions")
                for r in self.h.transport.calls
            )
        )
        self.assertTrue(all(r.method in {"GET", "POST"} for r in self.h.transport.calls))
