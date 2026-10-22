from __future__ import annotations

import json
import unittest

from developer_team.agents_canary_preflight import (
    MAX_BUDGET_CENTS,
    MAX_PAYLOAD_BYTES,
    evaluate_canary_preflight,
)


def valid_decision() -> dict[str, object]:
    return {
        "schema_version": 1,
        "purpose": "synthetic_read_only_canary",
        "provider": "openai_agents_api",
        "api_project_reference": "project-test-001",
        "operator_reference": "operator-test",
        "grant_reference": "dt013-test-grant",
        "synthetic_data_only": True,
        "repository_content_allowed": False,
        "github_write_allowed": False,
        "subagents_allowed": False,
        "deployment_allowed": False,
        "us_data_residency_acknowledged": True,
        "zero_data_retention_unavailable_acknowledged": True,
        "separate_api_billing_acknowledged": True,
        "credential_location": "external_controller",
        "canary_count": 1,
        "project_hard_limit_claim_usd_cents": 500,
        "session_spend_limit_usd_cents": 200,
        "warning_threshold_claim_usd_cents": 100,
        "live_start_authorized": False,
    }


def payload(decision: dict[str, object] | None = None) -> str:
    return json.dumps(decision or valid_decision(), separators=(",", ":"))


class CanaryPreflightTests(unittest.TestCase):
    def assert_blocked(self, value: object) -> dict[str, object]:
        report = evaluate_canary_preflight(value)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["decision_complete"])
        self.assertIsNone(report["decision_digest"])
        self.assertEqual(report["allowed_provider_starts"], 0)
        self.assert_authority_false(report)
        return report

    def assert_authority_false(self, report: dict[str, object]) -> None:
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

    def test_valid_decision_is_ready_only_for_separate_live_decision(self):
        report = evaluate_canary_preflight(payload())
        self.assertEqual(report["status"], "READY_FOR_SEPARATE_LIVE_DECISION")
        self.assertTrue(report["decision_complete"])
        self.assertRegex(str(report["decision_digest"]), r"^[0-9a-f]{64}$")
        self.assertEqual(report["allowed_provider_starts"], 0)
        self.assert_authority_false(report)

    def test_digest_is_stable_across_json_key_order(self):
        decision = valid_decision()
        reversed_payload = json.dumps(dict(reversed(list(decision.items()))))
        self.assertEqual(
            evaluate_canary_preflight(payload())["decision_digest"],
            evaluate_canary_preflight(reversed_payload)["decision_digest"],
        )

    def test_non_string_payload_is_blocked(self):
        for value in (None, {}, [], b"{}", 1, True):
            with self.subTest(value=value):
                self.assert_blocked(value)

    def test_malformed_json_is_blocked(self):
        for value in ("", "{", "not json", '{"schema_version":1'):
            with self.subTest(value=value):
                self.assert_blocked(value)

    def test_top_level_must_be_object(self):
        for value in ("[]", '"text"', "1", "true", "null"):
            with self.subTest(value=value):
                self.assert_blocked(value)

    def test_duplicate_json_key_is_blocked(self):
        raw = payload()
        duplicate = raw[:-1] + ',"schema_version":1}'
        self.assert_blocked(duplicate)

    def test_non_standard_json_number_is_blocked(self):
        decision = valid_decision()
        raw = payload(decision).replace('"canary_count":1', '"canary_count":NaN')
        self.assert_blocked(raw)

    def test_payload_character_limit_is_fail_closed(self):
        self.assert_blocked(" " * (MAX_PAYLOAD_BYTES + 1))

    def test_payload_utf8_byte_limit_is_fail_closed(self):
        raw = '"' + ("€" * 3000) + '"'
        self.assertLess(len(raw), MAX_PAYLOAD_BYTES)
        self.assertGreater(len(raw.encode("utf-8")), MAX_PAYLOAD_BYTES)
        self.assert_blocked(raw)

    def test_missing_field_is_blocked(self):
        decision = valid_decision()
        decision.pop("grant_reference")
        self.assert_blocked(payload(decision))

    def test_extra_field_is_blocked(self):
        decision = valid_decision()
        decision["api_key"] = "not-allowed"
        self.assert_blocked(payload(decision))

    def test_schema_version_requires_exact_integer_one(self):
        for value in (0, 2, True, "1", 1.0):
            decision = valid_decision()
            decision["schema_version"] = value
            with self.subTest(value=value):
                self.assert_blocked(payload(decision))

    def test_provider_and_purpose_are_pinned(self):
        for name, value in (
            ("provider", "codex_cloud"),
            ("provider", "openai"),
            ("purpose", "production"),
            ("purpose", "synthetic_write_canary"),
        ):
            decision = valid_decision()
            decision[name] = value
            with self.subTest(name=name, value=value):
                self.assert_blocked(payload(decision))

    def test_references_are_compact_non_secret_identifiers(self):
        for name in ("api_project_reference", "operator_reference", "grant_reference"):
            for value in ("", " space", "has space", "x" * 129, "sk-secret", "Bearer token"):
                decision = valid_decision()
                decision[name] = value
                with self.subTest(name=name, value=value[:20]):
                    self.assert_blocked(payload(decision))

    def test_required_true_boundaries_are_fail_closed(self):
        names = (
            "synthetic_data_only",
            "us_data_residency_acknowledged",
            "zero_data_retention_unavailable_acknowledged",
            "separate_api_billing_acknowledged",
        )
        for name in names:
            for value in (False, 1, "true", None):
                decision = valid_decision()
                decision[name] = value
                with self.subTest(name=name, value=value):
                    self.assert_blocked(payload(decision))

    def test_write_and_live_capabilities_must_remain_false(self):
        names = (
            "repository_content_allowed",
            "github_write_allowed",
            "subagents_allowed",
            "deployment_allowed",
            "live_start_authorized",
        )
        for name in names:
            for value in (True, 0, "false", None):
                decision = valid_decision()
                decision[name] = value
                with self.subTest(name=name, value=value):
                    self.assert_blocked(payload(decision))

    def test_credentials_must_remain_external(self):
        for value in ("agent_workspace", "repository", "environment", "", True):
            decision = valid_decision()
            decision["credential_location"] = value
            with self.subTest(value=value):
                self.assert_blocked(payload(decision))

    def test_exactly_one_canary_is_required(self):
        for value in (0, 2, -1, True, "1", 1.0):
            decision = valid_decision()
            decision["canary_count"] = value
            with self.subTest(value=value):
                self.assert_blocked(payload(decision))

    def test_budget_fields_require_exact_positive_integers(self):
        names = (
            "project_hard_limit_claim_usd_cents",
            "session_spend_limit_usd_cents",
            "warning_threshold_claim_usd_cents",
        )
        for name in names:
            for value in (0, -1, True, "100", 1.0, MAX_BUDGET_CENTS + 1):
                decision = valid_decision()
                decision[name] = value
                with self.subTest(name=name, value=value):
                    self.assert_blocked(payload(decision))

    def test_budget_order_is_warning_session_project(self):
        cases = (
            (100, 200, 50),
            (100, 300, 200),
            (500, 100, 200),
        )
        for project, session, warning in cases:
            decision = valid_decision()
            decision["project_hard_limit_claim_usd_cents"] = project
            decision["session_spend_limit_usd_cents"] = session
            decision["warning_threshold_claim_usd_cents"] = warning
            with self.subTest(project=project, session=session, warning=warning):
                self.assert_blocked(payload(decision))

    def test_equal_budget_boundaries_are_allowed(self):
        decision = valid_decision()
        decision["project_hard_limit_claim_usd_cents"] = 100
        decision["session_spend_limit_usd_cents"] = 100
        decision["warning_threshold_claim_usd_cents"] = 100
        report = evaluate_canary_preflight(payload(decision))
        self.assertEqual(report["status"], "READY_FOR_SEPARATE_LIVE_DECISION")
        self.assert_authority_false(report)

    def test_maximum_local_budget_bound_is_allowed_but_not_authorized(self):
        decision = valid_decision()
        decision["project_hard_limit_claim_usd_cents"] = MAX_BUDGET_CENTS
        decision["session_spend_limit_usd_cents"] = MAX_BUDGET_CENTS
        decision["warning_threshold_claim_usd_cents"] = MAX_BUDGET_CENTS
        report = evaluate_canary_preflight(payload(decision))
        self.assertEqual(report["status"], "READY_FOR_SEPARATE_LIVE_DECISION")
        self.assertEqual(report["allowed_provider_starts"], 0)
        self.assert_authority_false(report)

    def test_unknown_nested_objects_cannot_enter_exact_schema(self):
        decision = valid_decision()
        decision["api_project_reference"] = {"id": "project"}
        self.assert_blocked(payload(decision))

    def test_valid_report_never_claims_external_attestation(self):
        report = evaluate_canary_preflight(payload())
        self.assert_authority_false(report)
        self.assertNotIn("api_key", report)
        self.assertNotIn("session_id", report)
        self.assertNotIn("provider_start", report)


if __name__ == "__main__":
    unittest.main()
