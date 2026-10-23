import copy
import unittest
import unittest.mock

from developer_team.agents_canary_preflight import (
    MAX_APPROVAL_DICT_BYTES,
    evaluate_canary_preflight,
)


SHA = "a" * 40
NOW = 1_800_000_000


def approval() -> dict:
    return {
        "schema_version": 1,
        "approval_id": "approval-1",
        "canary_id": "canary-1",
        "controller_sha": SHA,
        "approved_by": "operator-1",
        "provider_path": "agents_api",
        "issued_at_epoch": NOW - 60,
        "expires_at_epoch": NOW + 600,
        "operator_budget_ceiling_usd_cents": 500,
        "session_spend_limit_usd_cents": 200,
        "project_hard_cap_usd_cents": 1000,
        "warning_threshold_usd_cents": 750,
        "project_hard_cap_confirmed": True,
        "warning_threshold_confirmed": True,
        "synthetic_only": True,
        "us_residency_accepted": True,
        "no_zdr_accepted": True,
        "read_only": True,
        "single_session": True,
        "github_write_allowed": False,
        "subagents_allowed": False,
        "deployment_allowed": False,
        "merge_allowed": False,
        "credentials_outside_agent": True,
    }


def run(value=None, **kwargs):
    return evaluate_canary_preflight(
        approval() if value is None else value,
        expected_controller_sha=kwargs.get("expected_controller_sha", SHA),
        now_epoch=kwargs.get("now_epoch", NOW),
        controller_max_session_usd_cents=kwargs.get("controller_max_session_usd_cents", 300),
    )


class CanaryPreflightTests(unittest.TestCase):
    def test_valid_approval_passes_without_authority(self):
        report = run()
        self.assertEqual(report["status"], "OFFLINE_PREFLIGHT_PASS")
        self.assertRegex(report["approval_digest"], r"^[0-9a-f]{64}$")
        for name in (
            "provider_verified",
            "billing_verified",
            "credentials_verified",
            "data_residency_verified",
            "remote_stop_verified",
            "live_authorized",
            "merge_authorized",
        ):
            self.assertIs(report[name], False)
        self.assertIs(report["separate_live_approval_required"], True)
        self.assertIs(report["one_use_consumption_required"], True)

    def test_digest_is_deterministic_and_bound_to_controller_ceiling(self):
        first = run()["approval_digest"]
        second = run()["approval_digest"]
        third = run(controller_max_session_usd_cents=301)["approval_digest"]
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)

    def test_non_dict_and_dict_subclass_blocked(self):
        class D(dict):
            pass

        self.assertEqual(run([])["reason"], "invalid_approval_object")
        self.assertEqual(run(D(approval()))["reason"], "invalid_approval_object")

    def test_missing_and_extra_fields_blocked(self):
        value = approval()
        value.pop("read_only")
        self.assertEqual(run(value)["reason"], "missing_or_extra_approval_fields")
        value = approval()
        value["api_key"] = "secret"
        self.assertEqual(run(value)["status"], "BLOCKED")

    def test_non_native_key_blocked_without_callback(self):
        calls = []

        class K(str):
            def __hash__(self):
                calls.append("hash")
                return super().__hash__()

            def __eq__(self, other):
                calls.append("eq")
                return super().__eq__(other)

        value = approval()
        original = value.pop("approval_id")
        value[K("approval_id")] = original
        calls.clear()
        report = run(value)
        self.assertEqual(report["reason"], "invalid_approval_key_type")
        self.assertEqual(calls, [])

    def test_sparse_large_dict_blocked(self):
        value = {f"gone-{i}": None for i in range(4096)}
        value.update(approval())
        for i in range(4096):
            del value[f"gone-{i}"]
        self.assertGreater(dict.__sizeof__(value), MAX_APPROVAL_DICT_BYTES)
        self.assertEqual(run(value)["reason"], "approval_dict_too_large")

    def test_invalid_controller_bindings_blocked(self):
        value = approval()
        value["controller_sha"] = "b" * 40
        self.assertEqual(run(value)["reason"], "controller_sha_mismatch")
        self.assertEqual(
            run(expected_controller_sha="notsha")["reason"],
            "invalid_expected_controller_sha",
        )

    def test_provider_must_be_agents_api(self):
        value = approval()
        value["provider_path"] = "codex_cloud"
        self.assertEqual(run(value)["reason"], "invalid_provider_path")

    def test_time_window_must_be_current_and_short(self):
        self.assertEqual(run(now_epoch=NOW + 1000)["reason"], "approval_not_current")
        value = approval()
        value["expires_at_epoch"] = value["issued_at_epoch"] + 3601
        self.assertEqual(run(value)["reason"], "approval_lifetime_exceeded")
        value = approval()
        value["expires_at_epoch"] = value["issued_at_epoch"]
        self.assertEqual(run(value)["reason"], "approval_not_current")

    def test_session_limit_cannot_exceed_any_ceiling(self):
        value = approval()
        value["session_spend_limit_usd_cents"] = 501
        self.assertEqual(
            run(value, controller_max_session_usd_cents=1000)["reason"],
            "session_limit_exceeds_operator_ceiling",
        )
        value = approval()
        value["session_spend_limit_usd_cents"] = 301
        self.assertEqual(run(value)["reason"], "session_limit_exceeds_controller_ceiling")
        value = approval()
        value["project_hard_cap_usd_cents"] = 100
        self.assertEqual(run(value)["reason"], "session_limit_exceeds_project_cap")

    def test_warning_must_not_exceed_project_cap(self):
        value = approval()
        value["warning_threshold_usd_cents"] = 1001
        self.assertEqual(run(value)["reason"], "warning_threshold_exceeds_project_cap")

    def test_cents_reject_bool_zero_negative_and_strings(self):
        for field in (
            "operator_budget_ceiling_usd_cents",
            "session_spend_limit_usd_cents",
            "project_hard_cap_usd_cents",
            "warning_threshold_usd_cents",
        ):
            for bad in (True, 0, -1, "10"):
                value = approval()
                value[field] = bad
                self.assertEqual(run(value)["status"], "BLOCKED", (field, bad))
        self.assertEqual(
            run(controller_max_session_usd_cents=True)["reason"],
            "invalid_controller_max_session_usd_cents",
        )

    def test_required_true_flags_fail_closed(self):
        for field in (
            "project_hard_cap_confirmed",
            "warning_threshold_confirmed",
            "synthetic_only",
            "us_residency_accepted",
            "no_zdr_accepted",
            "read_only",
            "single_session",
            "credentials_outside_agent",
        ):
            value = approval()
            value[field] = False
            self.assertEqual(run(value)["reason"], f"invalid_{field}")

    def test_required_false_flags_fail_closed(self):
        for field in (
            "github_write_allowed",
            "subagents_allowed",
            "deployment_allowed",
            "merge_allowed",
        ):
            value = approval()
            value[field] = True
            self.assertEqual(run(value)["reason"], f"invalid_{field}")

    def test_flags_reject_non_bool_values(self):
        for field in (
            "read_only",
            "single_session",
            "github_write_allowed",
            "subagents_allowed",
        ):
            value = approval()
            value[field] = 1
            self.assertEqual(run(value)["status"], "BLOCKED")

    def test_references_are_short_ascii_identifiers(self):
        for field in ("approval_id", "canary_id", "approved_by"):
            for bad in ("", "space value", "x" * 129, 123):
                value = approval()
                value[field] = bad
                self.assertEqual(run(value)["status"], "BLOCKED", (field, bad))

    def test_schema_version_exact_int_one(self):
        for bad in (True, 0, 2, "1"):
            value = approval()
            value["schema_version"] = bad
            self.assertEqual(run(value)["reason"], "invalid_schema_version")

    def test_non_supported_runtime_blocks_before_key_iteration(self):
        value = approval()
        with unittest.mock.patch(
            "developer_team.agents_canary_preflight.platform.python_implementation",
            return_value="PyPy",
        ):
            report = run(value)
        self.assertEqual(report["reason"], "unsupported_dict_runtime")

    def test_no_mutation(self):
        value = approval()
        before = copy.deepcopy(value)
        run(value)
        self.assertEqual(value, before)

    def test_blocked_reports_never_grant_authority(self):
        value = approval()
        value["merge_allowed"] = True
        report = run(value)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIsNone(report["approval_digest"])
        for name in (
            "provider_verified",
            "billing_verified",
            "credentials_verified",
            "data_residency_verified",
            "remote_stop_verified",
            "live_authorized",
            "merge_authorized",
        ):
            self.assertIs(report[name], False)


if __name__ == "__main__":
    unittest.main()
