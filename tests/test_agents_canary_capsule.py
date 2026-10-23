"""DT-015 safety tests for the persistable single-canary dry-run capsule."""

import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

from developer_team.agents_canary_capsule import (
    InvalidCanaryCapsule,
    bind_synthetic_session,
    capsule_report,
    main,
    mark_submission_uncertain,
    observe_synthetic_terminal,
    observe_synthetic_usage,
    prepare_capsule,
    record_structural_grant,
    record_synthetic_submit_attempt,
    request_synthetic_cancel,
    synthetic_reference_capsule,
    validate_capsule,
)

NOW = 1_800_000_000
PROJECT = "synthetic-test-project"
INTENT = "synthetic-dt015-intent"
KEY = "synthetic-dt015-key"
DIGEST = "a" * 64


def prepared():
    return prepare_capsule(
        intent_id=INTENT,
        idempotency_key=KEY,
        project_ref=PROJECT,
        plan_digest=DIGEST,
        budget_cents=5,
        created_at=NOW,
    )


def grant(**overrides):
    value = {
        "grant_id": "synthetic-grant",
        "intent_id": INTENT,
        "project_ref": PROJECT,
        "max_budget_cents": 5,
        "issued_at": NOW,
        "expires_at": NOW + 300,
        "mode": "single-canary-preauthorization",
        "source": "external-operator-gate",
    }
    value.update(overrides)
    return value


def with_grant():
    return record_structural_grant(prepared(), grant(), now=NOW)


def submitted():
    return record_synthetic_submit_attempt(with_grant(), now=NOW)


def session_bound():
    return bind_synthetic_session(
        submitted(),
        session_id="synthetic-session",
        turn_id="synthetic-turn",
        now=NOW,
    )


class CanaryCapsuleTests(unittest.TestCase):
    def assert_no_authority(self, state):
        report = capsule_report(state)
        self.assertEqual(report["live"], "NO-GO")
        self.assertFalse(report["provider_adapter_present"])
        self.assertFalse(report["provider_verified"])
        self.assertFalse(report["billing_verified"])
        self.assertFalse(report["cancel_verified"])
        self.assertFalse(report["live_authorized"])
        self.assertFalse(report["github_write_authorized"])
        self.assertFalse(report["repository_write_authorized"])
        self.assertFalse(report["merge_authorized"])
        self.assertEqual(report["real_submissions"], 0)
        return report

    def test_reference_capsule_reaches_usage_without_live_authority(self):
        state = synthetic_reference_capsule(NOW)
        report = self.assert_no_authority(state)
        self.assertEqual(report["stage"], "USAGE_OBSERVED")
        self.assertEqual(report["submit_attempts"], 1)
        self.assertEqual(report["usage_cents"], 1)

    def test_prepared_state_is_json_roundtrip_persistable(self):
        state = prepared()
        restored = json.loads(json.dumps(state))
        self.assertEqual(validate_capsule(restored), state)
        self.assertEqual(self.assert_no_authority(restored)["stage"], "PREPARED")

    def test_grant_is_structural_not_authority(self):
        state = with_grant()
        report = self.assert_no_authority(state)
        self.assertEqual(report["operator_gate"], "STRUCTURALLY_RECORDED_NOT_AUTHORITY")
        self.assertEqual(report["stage"], "GRANT_RECORDED")

    def test_wrong_or_expired_grant_blocks(self):
        cases = (
            ({"intent_id": "other-intent"}, "grant_intent_mismatch"),
            ({"project_ref": "other-project"}, "grant_project_mismatch"),
            ({"expires_at": NOW}, "expired_grant"),
            ({"mode": "live"}, "invalid_grant_mode"),
            ({"source": "local-json"}, "invalid_grant_source"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(InvalidCanaryCapsule, reason):
                    record_structural_grant(prepared(), grant(**overrides), now=NOW)

    def test_grant_budget_must_cover_capsule_budget(self):
        with self.assertRaisesRegex(InvalidCanaryCapsule, "capsule_budget_exceeds_grant"):
            record_structural_grant(
                prepared(),
                grant(max_budget_cents=4),
                now=NOW,
            )

    def test_duplicate_grant_is_blocked(self):
        state = with_grant()
        with self.assertRaisesRegex(
            InvalidCanaryCapsule,
            "grant_already_recorded_or_out_of_order",
        ):
            record_structural_grant(state, grant(grant_id="second-grant"), now=NOW)

    def test_exactly_one_synthetic_submit_attempt(self):
        state = submitted()
        self.assertEqual(state["submit_attempts"], 1)
        self.assertEqual(state["real_submissions"], 0)
        with self.assertRaisesRegex(InvalidCanaryCapsule, "synthetic_submit_out_of_order"):
            record_synthetic_submit_attempt(state, now=NOW)

    def test_expired_grant_blocks_synthetic_submit(self):
        state = with_grant()
        with self.assertRaisesRegex(InvalidCanaryCapsule, "expired_grant"):
            record_synthetic_submit_attempt(state, now=NOW + 301)

    def test_uncertain_submission_blocks_resubmit_and_allows_reconciliation(self):
        state = mark_submission_uncertain(submitted(), now=NOW)
        self.assertTrue(state["submission_uncertain"])
        with self.assertRaisesRegex(InvalidCanaryCapsule, "synthetic_submit_out_of_order"):
            record_synthetic_submit_attempt(state, now=NOW)
        reconciled = bind_synthetic_session(
            state,
            session_id="synthetic-session",
            turn_id="synthetic-turn",
            now=NOW,
        )
        self.assertEqual(reconciled["stage"], "SESSION_BOUND")
        self.assertEqual(reconciled["submit_attempts"], 1)

    def test_cancel_request_is_not_terminal_confirmation(self):
        state = request_synthetic_cancel(session_bound(), now=NOW)
        report = self.assert_no_authority(state)
        self.assertTrue(report["cancel_requested"])
        self.assertIsNone(report["terminal_kind"])
        self.assertEqual(report["stage"], "CANCEL_REQUESTED")

    def test_terminal_kinds_remain_distinct(self):
        for terminal in (
            "agent.session.turn.completed",
            "agent.session.turn.failed",
            "agent.session.turn.cancelled",
        ):
            with self.subTest(terminal=terminal):
                state = observe_synthetic_terminal(
                    session_bound(),
                    terminal_kind=terminal,
                    now=NOW,
                )
                self.assertEqual(state["terminal_kind"], terminal)
                self.assertEqual(state["stage"], "TERMINAL_OBSERVED")

    def test_invalid_or_duplicate_terminal_blocks(self):
        with self.assertRaisesRegex(InvalidCanaryCapsule, "invalid_terminal_kind"):
            observe_synthetic_terminal(
                session_bound(),
                terminal_kind="agent.session.idle",
                now=NOW,
            )
        terminal = observe_synthetic_terminal(
            session_bound(),
            terminal_kind="agent.session.turn.completed",
            now=NOW,
        )
        with self.assertRaisesRegex(InvalidCanaryCapsule, "terminal_out_of_order"):
            observe_synthetic_terminal(
                terminal,
                terminal_kind="agent.session.turn.failed",
                now=NOW,
            )

    def test_usage_is_separate_and_locally_bounded(self):
        terminal = observe_synthetic_terminal(
            session_bound(),
            terminal_kind="agent.session.turn.completed",
            now=NOW,
        )
        state = observe_synthetic_usage(terminal, usage_cents=5, now=NOW)
        self.assertEqual(state["usage_cents"], 5)
        with self.assertRaisesRegex(InvalidCanaryCapsule, "usage_exceeds_local_budget"):
            observe_synthetic_usage(terminal, usage_cents=6, now=NOW)

    def test_usage_before_terminal_blocks(self):
        with self.assertRaisesRegex(InvalidCanaryCapsule, "usage_out_of_order"):
            observe_synthetic_usage(session_bound(), usage_cents=1, now=NOW)

    def test_partial_session_binding_is_rejected_on_restore(self):
        state = submitted()
        state["session_id"] = "synthetic-session"
        with self.assertRaisesRegex(InvalidCanaryCapsule, "partial_session_binding"):
            validate_capsule(state)

    def test_tampered_authority_flags_and_real_submission_count_block(self):
        for field, value, reason in (
            ("live_authorized", True, "authority_flag_must_remain_false"),
            ("github_write_authorized", True, "authority_flag_must_remain_false"),
            ("repository_write_authorized", True, "authority_flag_must_remain_false"),
            ("merge_authorized", True, "authority_flag_must_remain_false"),
            ("real_submissions", 1, "real_submission_not_allowed"),
        ):
            with self.subTest(field=field):
                state = prepared()
                state[field] = value
                with self.assertRaisesRegex(InvalidCanaryCapsule, reason):
                    validate_capsule(state)

    def test_secret_like_extra_state_and_grant_fields_are_rejected_without_echo(self):
        marker = "sk-sensitive-marker-must-not-leak"
        state = prepared()
        state["api_key"] = marker
        with self.assertRaises(InvalidCanaryCapsule) as caught:
            validate_capsule(state)
        self.assertNotIn(marker, str(caught.exception))

        unsafe_grant = grant()
        unsafe_grant["token"] = marker
        with self.assertRaises(InvalidCanaryCapsule) as caught:
            record_structural_grant(prepared(), unsafe_grant, now=NOW)
        self.assertNotIn(marker, str(caught.exception))

    def test_transitions_do_not_mutate_input_state(self):
        original = with_grant()
        before = copy.deepcopy(original)
        record_synthetic_submit_attempt(original, now=NOW)
        self.assertEqual(original, before)

    def test_state_machine_does_not_touch_network_process_files_or_environment(self):
        with (
            patch("socket.socket") as socket_call,
            patch("subprocess.Popen") as process,
            patch("builtins.open") as open_file,
            patch("os.getenv") as getenv,
        ):
            state = synthetic_reference_capsule(NOW)
            self.assertEqual(capsule_report(state)["stage"], "USAGE_OBSERVED")
        socket_call.assert_not_called()
        process.assert_not_called()
        open_file.assert_not_called()
        getenv.assert_not_called()

    def test_cli_reference_is_no_go_and_exposes_no_live_flags(self):
        output = io.StringIO()
        with (
            patch("developer_team.agents_canary_capsule.time.time", return_value=NOW),
            contextlib.redirect_stdout(output),
        ):
            code = main(["--synthetic-reference"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["live"], "NO-GO")
        self.assertEqual(report["real_submissions"], 0)

        for flag in (
            "--live",
            "--force",
            "--approval",
            "--api-key",
            "--credential",
            "--submit",
            "--cancel",
        ):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main([flag, "value"])


if __name__ == "__main__":
    unittest.main()
