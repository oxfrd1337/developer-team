"""Negative and safety cases for DT-012 normalized synthetic canary traces."""

import copy
import unittest
from unittest.mock import patch

from developer_team.agents_canary_replay import MAX_EVENTS, replay_canary_trace

INTENT = "synthetic-dt012-run"
KEY = "synthetic-message-key"
SESSION = "synthetic-session"
TURN = "synthetic-turn"


def event(kind, **fields):
    return {"type": kind, **fields}


def pins():
    return {"intent_id": INTENT, "idempotency_key": KEY}


def cycle():
    return [
        event("intent_recorded", **pins()),
        event("submit_attempted", **pins()),
        event("session_receipt", session_id=SESSION, turn_id=TURN),
        event("agent.session.turn.completed", session_id=SESSION, turn_id=TURN),
        event("usage_observed", session_id=SESSION, turn_id=TURN, amount_usd_cents=4),
    ]


class CanaryReplayTests(unittest.TestCase):
    def replay(self, sequence, *, intent=INTENT, key=KEY):
        report = replay_canary_trace(
            sequence, expected_intent_id=intent, expected_idempotency_key=key
        )
        for flag in (
            "provider_verified",
            "cancel_verified",
            "billing_verified",
            "live_authorized",
            "merge_authorized",
        ):
            self.assertIs(report[flag], False)
        return report

    def blocked(self, sequence, **kwargs):
        report = self.replay(sequence, **kwargs)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["next_action"], "STOP_AND_RECONCILE_EXTERNALLY")
        return report

    def test_complete_claims_only_observe_synthetic_terminal(self):
        report = self.replay(cycle())
        self.assertEqual(report["status"], "SYNTHETIC_TERMINAL_OBSERVED")
        self.assertEqual(report["submit_attempts_observed"], 1)
        self.assertTrue(report["usage_claim_seen"])

    def test_empty_trace_is_blocked(self):
        self.blocked([])

    def test_nonlist_trace_is_blocked(self):
        for value in (None, {}, (), "PASS", True, 1):
            with self.subTest(value=value):
                self.blocked(value)

    def test_rejects_event_count_above_bound(self):
        self.blocked(
            [event("agent.session.idle", session_id=SESSION, turn_id=TURN)] * (MAX_EVENTS + 1)
        )

    def test_intent_only_is_incomplete(self):
        report = self.replay([cycle()[0]])
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["submit_attempts_observed"], 0)

    def test_submit_without_receipt_is_incomplete(self):
        report = self.replay(cycle()[:2])
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["submit_attempts_observed"], 1)

    def test_uncertain_submission_stops_without_retry(self):
        seq = cycle()[:2] + [event("submission_uncertain", **pins())]
        report = self.replay(seq)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertTrue(report["uncertain_submission_claimed"])
        self.assertEqual(report["next_action"], "STOP_AND_RECONCILE_EXTERNALLY")

    def test_recovered_receipt_is_only_a_claim(self):
        seq = cycle()[:2] + [event("submission_uncertain", **pins())] + cycle()[2:]
        report = self.replay(seq)
        self.assertEqual(report["status"], "SYNTHETIC_TERMINAL_OBSERVED")
        self.assertTrue(report["uncertain_submission_claimed"])

    def test_second_submit_is_blocked(self):
        seq = cycle()[:2] + [event("submit_attempted", **pins())] + cycle()[2:]
        self.blocked(seq)

    def test_retry_after_unknown_submission_is_blocked(self):
        seq = cycle()[:2] + [
            event("submission_uncertain", **pins()),
            event("submit_attempted", **pins()),
        ]
        self.blocked(seq)

    def test_submit_before_intent_is_blocked(self):
        self.blocked([cycle()[1], cycle()[0]])

    def test_second_intent_is_blocked(self):
        self.blocked([cycle()[0], cycle()[0]])

    def test_wrong_expected_operator_intent_is_blocked(self):
        self.blocked(cycle(), intent="different-intent")

    def test_wrong_expected_operator_key_is_blocked(self):
        self.blocked(cycle(), key="different-key")

    def test_invalid_operator_pin_is_blocked(self):
        for value in ("", "bad key", None, True, "x" * 129, "line\nbreak"):
            with self.subTest(value=value):
                self.blocked(cycle(), intent=value)

    def test_false_event_binding_is_blocked(self):
        seq = cycle()
        seq[1] = event("submit_attempted", intent_id=INTENT, idempotency_key="fake-key")
        self.blocked(seq)

    def test_receipt_without_submit_is_blocked(self):
        self.blocked([cycle()[0], cycle()[2]])

    def test_duplicate_receipt_is_blocked(self):
        self.blocked(cycle()[:3] + [cycle()[2], *cycle()[3:]])

    def test_cancel_request_without_receipt_is_blocked(self):
        self.blocked(cycle()[:2] + [event("cancel_requested", session_id=SESSION, turn_id=TURN)])

    def test_cancel_request_only_is_not_a_terminal_confirmation(self):
        seq = cycle()[:3] + [event("cancel_requested", session_id=SESSION, turn_id=TURN)]
        report = self.replay(seq)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertTrue(report["cancel_requested_claimed"])
        self.assertFalse(report["cancelled_terminal_claimed"])

    def test_cancel_then_cancelled_terminal_is_still_unverified(self):
        seq = cycle()[:3] + [
            event("cancel_requested", session_id=SESSION, turn_id=TURN),
            event("agent.session.turn.cancelled", session_id=SESSION, turn_id=TURN),
        ]
        report = self.replay(seq)
        self.assertEqual(report["status"], "SYNTHETIC_TERMINAL_OBSERVED")
        self.assertTrue(report["cancelled_terminal_claimed"])

    def test_cancel_then_completed_is_not_cancelled(self):
        seq = cycle()[:3] + [
            event("cancel_requested", session_id=SESSION, turn_id=TURN),
            cycle()[3],
        ]
        report = self.replay(seq)
        self.assertEqual(report["status"], "SYNTHETIC_TERMINAL_OBSERVED")
        self.assertFalse(report["cancelled_terminal_claimed"])

    def test_failed_turn_is_not_claimed_completed(self):
        seq = cycle()[:3] + [event("agent.session.turn.failed", session_id=SESSION, turn_id=TURN)]
        report = self.replay(seq)
        self.assertEqual(report["terminal_kind_claimed"], "agent.session.turn.failed")

    def test_idle_without_terminal_remains_incomplete(self):
        seq = cycle()[:3] + [event("agent.session.idle", session_id=SESSION, turn_id=TURN)]
        report = self.replay(seq)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertIsNone(report["terminal_kind_claimed"])

    def test_idle_after_cancel_does_not_ack_cancel(self):
        seq = cycle()[:3] + [
            event("cancel_requested", session_id=SESSION, turn_id=TURN),
            event("agent.session.idle", session_id=SESSION, turn_id=TURN),
        ]
        report = self.replay(seq)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertFalse(report["cancelled_terminal_claimed"])

    def test_wrong_session_binding_is_blocked(self):
        seq = cycle()
        seq[3] = event("agent.session.turn.completed", session_id="foreign", turn_id=TURN)
        self.blocked(seq)

    def test_wrong_turn_binding_is_blocked(self):
        seq = cycle()
        seq[3] = event("agent.session.turn.completed", session_id=SESSION, turn_id="foreign")
        self.blocked(seq)

    def test_conflicting_terminal_event_is_blocked(self):
        self.blocked(cycle()[:4] + [
            event("agent.session.turn.cancelled", session_id=SESSION, turn_id=TURN)
        ])

    def test_duplicate_terminal_is_blocked(self):
        self.blocked(cycle()[:4] + [cycle()[3]])

    def test_idle_after_terminal_keeps_terminal_claim_unverified(self):
        report = self.replay(
            cycle()[:4] + [event("agent.session.idle", session_id=SESSION, turn_id=TURN)]
        )
        self.assertEqual(report["status"], "SYNTHETIC_TERMINAL_OBSERVED")
        self.assertEqual(report["terminal_kind_claimed"], "agent.session.turn.completed")

    def test_idle_after_usage_keeps_terminal_claim(self):
        report = self.replay(
            cycle() + [event("agent.session.idle", session_id=SESSION, turn_id=TURN)]
        )
        self.assertEqual(report["status"], "SYNTHETIC_TERMINAL_OBSERVED")
        self.assertTrue(report["usage_claim_seen"])

    def test_usage_before_terminal_is_blocked(self):
        self.blocked(cycle()[:3] + [cycle()[4], cycle()[3]])

    def test_duplicate_usage_is_blocked(self):
        self.blocked(cycle() + [cycle()[4]])

    def test_usage_amount_bools_floats_negative_and_huge_block(self):
        for amount in (True, 1.5, -1, None, "0", 1_000_000_001):
            with self.subTest(amount=amount):
                seq = cycle()
                seq[4] = event(
                    "usage_observed", session_id=SESSION, turn_id=TURN, amount_usd_cents=amount
                )
                self.blocked(seq)

    def test_extra_forged_approval_field_is_blocked(self):
        for field in ("live_authorized", "merge_authorized", "approved_by", "api_key"):
            with self.subTest(field=field):
                seq = cycle()
                seq[1][field] = True
                self.blocked(seq)

    def test_unknown_event_kind_is_blocked(self):
        self.blocked(cycle()[:3] + [event("GO", session_id=SESSION, turn_id=TURN)])

    def test_missing_event_field_is_blocked(self):
        seq = cycle()
        del seq[2]["turn_id"]
        self.blocked(seq)

    def test_event_must_be_plain_object(self):
        self.blocked(cycle()[:2] + [42])

    def test_nested_event_payload_is_blocked(self):
        seq = cycle()
        seq[2]["session_id"] = {"session": SESSION}
        self.blocked(seq)

    def test_reference_is_bounded_and_ascii_safe(self):
        for value in ("x" * 129, "not ascii ä", "space value", "line\nbreak", ""):
            with self.subTest(value=value):
                seq = cycle()
                seq[2]["session_id"] = value
                self.blocked(seq)

    def test_fake_success_claims_are_never_authority(self):
        seq = cycle()
        seq[3]["provider_verified"] = True
        self.blocked(seq)

    def test_never_mutates_input(self):
        seq = cycle()
        previous = copy.deepcopy(seq)
        self.replay(seq)
        self.assertEqual(seq, previous)

    def test_no_filesystem_shell_or_network_called(self):
        with (
            patch("builtins.open") as file_open,
            patch("subprocess.Popen") as process,
            patch("socket.socket") as network,
        ):
            self.replay(cycle())
            file_open.assert_not_called()
            process.assert_not_called()
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
