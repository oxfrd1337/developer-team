"""DT-013 safety tests for the offline Agents live-canary preflight."""

import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

from developer_team.agents_live_preflight import (
    MAX_AMOUNT_CENTS,
    evaluate_agents_live_preflight,
    main,
    synthetic_reference_plan,
)


class AgentsLivePreflightTests(unittest.TestCase):
    def test_reference_plan_passes_offline_but_never_authorizes_live(self):
        report = evaluate_agents_live_preflight(synthetic_reference_plan())
        self.assertEqual(report["offline_preflight"], "PASS")
        self.assertEqual(report["live"], "NO-GO")
        self.assertEqual(report["real_submissions"], 0)
        self.assertEqual(
            report["next_action"],
            "MANUAL_EXTERNAL_VERIFICATION_AND_SEPARATE_APPROVAL_REQUIRED",
        )
        for flag in (
            "network_used",
            "credentials_read",
            "provider_verified",
            "billing_verified",
            "cancel_verified",
            "live_authorized",
            "github_write_authorized",
            "merge_authorized",
        ):
            self.assertIs(report[flag], False)

    def test_missing_field_blocks_without_defaults(self):
        plan = synthetic_reference_plan()
        plan.pop("provider_cancel_verification")
        report = evaluate_agents_live_preflight(plan)
        self.assertEqual(report["offline_preflight"], "BLOCKED")
        self.assertEqual(report["reasons"], ["missing_or_unexpected_fields"])

    def test_extra_secret_field_is_rejected_without_echoing_secret(self):
        plan = synthetic_reference_plan()
        secret = "sk-secret-value-must-not-leak"
        plan["api_key"] = secret
        report = evaluate_agents_live_preflight(plan)
        rendered = json.dumps(report)
        self.assertEqual(report["offline_preflight"], "BLOCKED")
        self.assertNotIn(secret, rendered)
        self.assertNotIn("api_key", rendered)

    def test_credential_material_is_forbidden(self):
        plan = synthetic_reference_plan()
        plan["credential_material_present"] = True
        report = evaluate_agents_live_preflight(plan)
        self.assertEqual(report["reasons"], ["credential_material_must_be_absent"])

    def test_sensitive_or_non_synthetic_data_blocks(self):
        for field, value, reason in (
            ("synthetic_data_only", False, "synthetic_data_required"),
            ("sensitive_data_allowed", True, "sensitive_data_must_be_forbidden"),
        ):
            with self.subTest(field=field):
                plan = synthetic_reference_plan()
                plan[field] = value
                report = evaluate_agents_live_preflight(plan)
                self.assertEqual(report["reasons"], [reason])

    def test_write_or_merge_capability_blocks(self):
        for field in ("github_write_allowed", "repository_write_allowed", "automatic_merge"):
            with self.subTest(field=field):
                plan = synthetic_reference_plan()
                plan[field] = True
                report = evaluate_agents_live_preflight(plan)
                self.assertEqual(report["offline_preflight"], "BLOCKED")

    def test_bool_does_not_satisfy_integer_limits(self):
        for field in ("max_submissions", "max_parallel_runs", "per_canary_budget_cents"):
            with self.subTest(field=field):
                plan = synthetic_reference_plan()
                plan[field] = True
                self.assertEqual(
                    evaluate_agents_live_preflight(plan)["offline_preflight"], "BLOCKED"
                )

    def test_single_submission_and_parallel_run_are_required(self):
        for field, value in (("max_submissions", 2), ("max_parallel_runs", 2)):
            with self.subTest(field=field):
                plan = synthetic_reference_plan()
                plan[field] = value
                self.assertEqual(
                    evaluate_agents_live_preflight(plan)["offline_preflight"], "BLOCKED"
                )

    def test_budget_must_be_positive_bounded_and_within_project_limit(self):
        cases = (
            ("per_canary_budget_cents", 0, "invalid_canary_budget"),
            ("project_hard_limit_cents", 0, "invalid_project_hard_limit"),
            ("per_canary_budget_cents", MAX_AMOUNT_CENTS + 1, "invalid_canary_budget"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field, value=value):
                plan = synthetic_reference_plan()
                plan[field] = value
                self.assertEqual(evaluate_agents_live_preflight(plan)["reasons"], [reason])
        plan = synthetic_reference_plan()
        plan["per_canary_budget_cents"] = 2
        self.assertEqual(
            evaluate_agents_live_preflight(plan)["reasons"],
            ["canary_budget_exceeds_project_limit"],
        )

    def test_external_checks_cannot_be_self_attested_as_verified(self):
        for field in (
            "provider_identity_verification",
            "provider_cancel_verification",
            "billing_limit_verification",
        ):
            with self.subTest(field=field):
                plan = synthetic_reference_plan()
                plan[field] = "verified"
                report = evaluate_agents_live_preflight(plan)
                self.assertEqual(
                    report["reasons"], ["external_verification_must_remain_pending"]
                )

    def test_wrong_residency_or_zdr_assumption_blocks(self):
        plan = synthetic_reference_plan()
        plan["data_residency"] = "eu"
        self.assertEqual(
            evaluate_agents_live_preflight(plan)["reasons"], ["unexpected_data_residency"]
        )
        plan = synthetic_reference_plan()
        plan["zero_data_retention"] = True
        self.assertEqual(
            evaluate_agents_live_preflight(plan)["reasons"], ["zero_data_retention_not_assumed"]
        )

    def test_invalid_plan_types_block_without_repr_or_callbacks(self):
        for value in (None, [], (), "GO", True, 1):
            with self.subTest(value=value):
                report = evaluate_agents_live_preflight(value)
                self.assertEqual(report["offline_preflight"], "BLOCKED")
                self.assertEqual(report["reasons"], ["invalid_plan_object"])

    def test_evaluation_does_not_touch_network_process_files_or_environment(self):
        with (
            patch("socket.socket") as socket_call,
            patch("subprocess.Popen") as process,
            patch("builtins.open") as open_file,
            patch("os.getenv") as getenv,
        ):
            report = evaluate_agents_live_preflight(synthetic_reference_plan())
        self.assertEqual(report["offline_preflight"], "PASS")
        socket_call.assert_not_called()
        process.assert_not_called()
        open_file.assert_not_called()
        getenv.assert_not_called()

    def test_cli_reference_is_offline_pass_but_exit_code_remains_no_go(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--synthetic-reference"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["offline_preflight"], "PASS")
        self.assertEqual(report["live"], "NO-GO")

    def test_cli_exposes_no_live_approval_or_secret_flags(self):
        for flag in ("--live", "--force", "--approval", "--api-key", "--credential"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main([flag, "value"])

    def test_mutating_fixture_does_not_change_fresh_reference_plan(self):
        plan = synthetic_reference_plan()
        copied = copy.deepcopy(plan)
        plan["automatic_merge"] = True
        self.assertEqual(synthetic_reference_plan(), copied)


if __name__ == "__main__":
    unittest.main()
