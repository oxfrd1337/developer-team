"""DT-016 persistence, crash boundaries, tampering and competing-controller tests."""

import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

from developer_team.adapters.agents_api import AgentsAPIAdapter
from developer_team.adapters.agents_api_contracts import AgentsAPIError, AgentsAPILimits
from developer_team.adapters.agents_api_journal import SQLiteCanaryJournal
from tests.agents_api_support import NOW, FixtureGate, FixtureTransport, Harness, binding


class AgentsAPIJournalTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.connection.close)

    def test_journal_cannot_be_prepared_twice_even_for_same_binding(self):
        for bound in (self.h.binding, binding(intent_id="intent_other")):
            with self.assertRaises(AgentsAPIError):
                self.h.journal.prepare(bound)
        self.assertEqual(self.h.state().phase, "PREPARED")

    def test_all_binding_components_and_message_key_are_pinned_on_restart(self):
        for changes in (
            {"project_id": "proj_other"},
            {"agent_id": "agent_other"},
            {"intent_id": "intent_other"},
            {"idempotency_key": "key_other"},
            {"plan_digest": "b" * 64},
            {"budget_cents": 6},
        ):
            with self.subTest(changes=changes):
                bound = binding(**changes)
                adapter = AgentsAPIAdapter(
                    bound,
                    self.h.journal,
                    transport=self.h.transport,
                    gate=FixtureGate(),
                    now=lambda: NOW,
                )
                with self.assertRaises(AgentsAPIError):
                    adapter.create_session()
                with self.assertRaises(AgentsAPIError):
                    self.h.journal.load(bound)
        self.assertEqual(self.h.transport.calls, [])

    def test_resource_limits_cannot_be_changed_to_reset_or_raise_budget_on_restart(self):
        self.h.adapter.create_session()
        for limits in (AgentsAPILimits(max_requests=32), AgentsAPILimits(timeout_seconds=30)):
            with self.assertRaisesRegex(AgentsAPIError, "resource_limits_mismatch"):
                self.h.restart(limits=limits).reconcile()
        self.assertEqual(self.h.state().request_count, 1)

    def test_unprepared_or_deleted_journal_never_recreates_itself(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        journal = SQLiteCanaryJournal(connection)
        adapter = AgentsAPIAdapter(
            binding(), journal, transport=self.h.transport, gate=self.h.gate, now=lambda: NOW
        )
        with self.assertRaisesRegex(AgentsAPIError, "journal"):
            adapter.create_session()
        self.h.connection.execute("DELETE FROM dt016_canary")
        self.h.connection.commit()
        with self.assertRaisesRegex(AgentsAPIError, "journal"):
            self.h.adapter.create_session()
        self.assertEqual(self.h.transport.calls, [])

    def test_closed_or_busy_database_blocks_before_transport(self):
        connection = sqlite3.connect(":memory:")
        journal = SQLiteCanaryJournal(connection)
        journal.prepare(binding())
        connection.close()
        adapter = AgentsAPIAdapter(
            binding(), journal, transport=self.h.transport, gate=self.h.gate, now=lambda: NOW
        )
        with self.assertRaisesRegex(AgentsAPIError, "journal"):
            adapter.create_session()
        self.assertEqual(self.h.transport.calls, [])

    def test_failed_write_ahead_prevents_session_creation(self):
        with patch.object(self.h.journal, "replace", side_effect=OSError("sk-journal-secret")):
            with self.assertRaisesRegex(AgentsAPIError, "journal_commit_failed"):
                self.h.adapter.create_session()
        self.assertEqual(self.h.transport.calls, [])
        self.assertEqual(self.h.state().phase, "PREPARED")

    def test_failed_session_receipt_persistence_leaves_unknown_not_retryable(self):
        original = self.h.journal.replace

        def fail_receipt(bound, revision, state):
            if state.phase == "SESSION_READY":
                raise OSError("sk-receipt-secret")
            original(bound, revision, state)

        with patch.object(self.h.journal, "replace", side_effect=fail_receipt):
            with self.assertRaisesRegex(AgentsAPIError, "journal_commit_failed"):
                self.h.adapter.create_session()
        self.assertEqual(self.h.state().phase, "SESSION_UNCERTAIN")
        with self.assertRaises(AgentsAPIError):
            self.h.restart().create_session()
        self.assertEqual(self.h.restart().reconcile()["phase"], "SESSION_READY")
        self.assertEqual(len(self.h.transport.posts("create")), 1)

    def test_failed_message_write_ahead_prevents_submit(self):
        self.h.adapter.create_session()
        original = self.h.journal.replace

        def fail_intent(bound, revision, state):
            if state.phase == "MESSAGE_UNCERTAIN":
                raise OSError("sk-intent-secret")
            original(bound, revision, state)

        with patch.object(self.h.journal, "replace", side_effect=fail_intent):
            with self.assertRaisesRegex(AgentsAPIError, "journal_commit_failed"):
                self.h.adapter.submit_canary()
        self.assertEqual(self.h.transport.posts("agent.session.input.message"), [])
        self.assertEqual(self.h.state().message_attempts, 0)

    def test_failed_message_ack_persistence_never_resubmits(self):
        self.h.adapter.create_session()
        original = self.h.journal.replace

        def fail_ack(bound, revision, state):
            if state.phase == "MESSAGE_ACCEPTED":
                raise OSError("sk-ack-secret")
            original(bound, revision, state)

        with patch.object(self.h.journal, "replace", side_effect=fail_ack):
            with self.assertRaisesRegex(AgentsAPIError, "journal_commit_failed"):
                self.h.adapter.submit_canary()
        self.assertEqual(self.h.state().phase, "MESSAGE_UNCERTAIN")
        with self.assertRaises(AgentsAPIError):
            self.h.restart().submit_canary()
        self.assertEqual(self.h.restart().reconcile()["phase"], "TURN_BOUND")
        self.assertEqual(len(self.h.transport.posts("agent.session.input.message")), 1)

    def test_failed_cancel_ack_persistence_does_not_claim_confirmation(self):
        self.h.active()
        original = self.h.journal.replace

        def fail_ack(bound, revision, state):
            if state.phase == "CANCEL_REQUESTED":
                raise OSError("sk-cancel-secret")
            original(bound, revision, state)

        with patch.object(self.h.journal, "replace", side_effect=fail_ack):
            with self.assertRaises(AgentsAPIError):
                self.h.adapter.cancel()
        self.assertEqual(self.h.state().phase, "CANCEL_UNCERTAIN")
        self.assertIsNone(self.h.state().terminal_kind)
        with self.assertRaises(AgentsAPIError):
            self.h.restart().cancel()

    def test_worker_launch_failure_preserves_reserved_attempt(self):
        with patch(
            "developer_team.adapters.agents_api.threading.Thread.start",
            side_effect=RuntimeError("sk-thread-secret"),
        ):
            with self.assertRaisesRegex(AgentsAPIError, "worker_unavailable"):
                self.h.adapter.create_session()
        self.assertEqual(self.h.state().phase, "SESSION_UNCERTAIN")
        self.assertEqual(self.h.transport.calls, [])

    def test_compare_and_swap_rejects_stale_competing_writer(self):
        revision, state = self.h.journal.load(binding())
        self.h.journal.replace(binding(), revision, state)
        with self.assertRaisesRegex(AgentsAPIError, "conflict"):
            self.h.journal.replace(binding(), revision, state)

    def test_two_independent_connections_reserve_only_one_session_create(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "controller-journal.sqlite"
            connections = [sqlite3.connect(path, check_same_thread=False) for _ in range(2)]
            self.addCleanup(lambda: [connection.close() for connection in connections])
            journals = [SQLiteCanaryJournal(connection) for connection in connections]
            journals[0].prepare(binding())
            barrier = threading.Barrier(2)
            transport = FixtureTransport()
            errors = []

            def race(journal):
                original_load = journal.load

                def simultaneous_load(bound):
                    result = original_load(bound)
                    barrier.wait(timeout=3)
                    return result

                adapter = AgentsAPIAdapter(
                    binding(), journal, transport=transport, gate=FixtureGate(), now=lambda: NOW
                )
                try:
                    with patch.object(journal, "load", side_effect=simultaneous_load):
                        adapter.create_session()
                except AgentsAPIError as exc:
                    errors.append(str(exc))

            threads = [threading.Thread(target=race, args=(journal,)) for journal in journals]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors, ["journal_commit_failed"])
            self.assertEqual(len(transport.posts("create")), 1)
            self.assertEqual(journals[0].load(binding())[1].session_attempts, 1)

    def test_disk_journal_survives_connection_and_adapter_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journal.sqlite"
            connection = sqlite3.connect(path)
            journal = SQLiteCanaryJournal(connection)
            journal.prepare(binding())
            adapter = AgentsAPIAdapter(
                binding(), journal, transport=self.h.transport, gate=self.h.gate, now=lambda: NOW
            )
            adapter.create_session()
            connection.close()
            restored = sqlite3.connect(path)
            try:
                adapter = AgentsAPIAdapter(
                    binding(),
                    SQLiteCanaryJournal(restored),
                    transport=self.h.transport,
                    gate=self.h.gate,
                    now=lambda: NOW,
                )
                adapter.submit_canary()
                with self.assertRaises(AgentsAPIError):
                    adapter.submit_canary()
            finally:
                restored.close()
        self.assertEqual(len(self.h.transport.posts("create")), 1)
        self.assertEqual(len(self.h.transport.posts("agent.session.input.message")), 1)

    def test_tampered_fields_references_authority_and_counters_fail_closed_without_echo(self):
        original = asdict(self.h.state())
        for changes in (
            {"idempotency_key": "key_other"},
            {"message_digest": "b" * 64},
            {"binding_digest": "b" * 64},
            {"phase": "TERMINAL"},
            {"session_attempts": True},
            {"message_attempts": 2},
            {"cancel_attempts": 1},
            {"turn_id": "turn_without_session"},
            {"request_count": 33},
            {"terminal_kind": "agent.session.idle"},
            {"budget_exceeded": 1},
            {"consumed_cents": "NaN"},
            {"consumed_cents": "-1"},
            {"api_key": "sk-secret-marker"},
            {"live_authorized": True},
            {"real_submissions": 1},
        ):
            with self.subTest(fields=list(changes)):
                value = {**copy.deepcopy(original), **changes}
                self.h.connection.execute("UPDATE dt016_canary SET state = ?", (json.dumps(value),))
                self.h.connection.commit()
                with self.assertRaises(AgentsAPIError) as caught:
                    self.h.adapter.create_session()
                self.assertNotIn("sk-secret-marker", str(caught.exception))
        self.assertEqual(self.h.transport.calls, [])

    def test_duplicate_oversized_or_nonobject_journal_json_is_rejected(self):
        raw = json.dumps(asdict(self.h.state()))
        for value in ("[]", raw[:-1] + ', "phase":"PREPARED"}', "x" * 4097, "{"):
            self.h.connection.execute("UPDATE dt016_canary SET state = ?", (value,))
            self.h.connection.commit()
            with self.assertRaises(AgentsAPIError):
                self.h.adapter.create_session()
        self.assertEqual(self.h.transport.calls, [])

    def test_injected_journal_cannot_return_unvalidated_objects(self):
        for result in (
            None,
            {},
            (0, {}),
            (True, self.h.state()),
            (0, replace(self.h.state(), phase="GO")),
        ):
            adapter = self.h.restart()
            adapter._journal = Mock()
            adapter._journal.load.return_value = result
            with self.assertRaises(AgentsAPIError):
                adapter.create_session()
        self.assertEqual(self.h.transport.calls, [])
