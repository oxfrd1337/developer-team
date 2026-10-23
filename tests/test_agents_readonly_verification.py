"""DT-014 safety tests for sanitized read-only evidence verification."""

import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

from developer_team.agents_readonly_verification import (
    MAX_TTL_SECONDS,
    evaluate_readonly_evidence,
    main,
    synthetic_reference_evidence,
)

NOW = 1_800_000_000
PROJECT = "synthetic-test-project"


class AgentsReadOnlyVerificationTests(unittest.TestCase):
    def evaluate(self, evidence):
        return evaluate_readonly_evidence(
            evidence,
            expected_project_ref=PROJECT,
            now=NOW,
        )

    def test_complete_synthetic_evidence_is_read_only_verified_but_live_no_go(self):
        report = self.evaluate(synthetic_reference_evidence(NOW))
        self.assertEqual(report["decision"], "READ_ONLY_VERIFIED")
        self.assertEqual(report["live"], "NO-GO")
        self.assertEqual(report["operator_gate"], "PENDING_SEPARATE_APPROVAL")
        self.assertEqual(set(report["gate_results"].values()), {"READ_ONLY_VERIFIED"})
        self.assertEqual(report["real_submissions"], 0)
        for flag in (
            "provider_verified_for_live",
            "credentials_read",
            "network_used_by_verifier",
            "billing_verified_for_live",
            "cancel_verified_for_live",
            "live_authorized",
            "github_write_authorized",
            "repository_write_authorized",
            "merge_authorized",
        ):
            self.assertIs(report[flag], False)

    def test_missing_gate_blocks(self):
        evidence = synthetic_reference_evidence(NOW)[:-1]
        report = self.evaluate(evidence)
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertEqual(report["reasons"], ["missing_gate_evidence"])

    def test_duplicate_gate_blocks(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence.append(copy.deepcopy(evidence[0]))
        report = self.evaluate(evidence)
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertIn("duplicate_gate_evidence", report["reasons"][0])

    def test_wrong_project_binding_blocks(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[0]["project_ref"] = "other-project"
        report = self.evaluate(evidence)
        self.assertIn("project_binding_mismatch", report["reasons"][0])

    def test_stale_evidence_blocks(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[0]["expires_at"] = NOW
        report = self.evaluate(evidence)
        self.assertIn("stale_evidence", report["reasons"][0])

    def test_future_observation_blocks(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[0]["observed_at"] = NOW + 61
        evidence[0]["expires_at"] = NOW + 120
        report = self.evaluate(evidence)
        self.assertIn("evidence_from_future", report["reasons"][0])

    def test_excessive_ttl_blocks(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[0]["expires_at"] = evidence[0]["observed_at"] + MAX_TTL_SECONDS + 1
        report = self.evaluate(evidence)
        self.assertIn("invalid_evidence_ttl", report["reasons"][0])

    def test_self_asserted_provider_verifier_is_rejected(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[0]["verifier"] = "operator-text"
        report = self.evaluate(evidence)
        self.assertIn("unexpected_verifier", report["reasons"][0])

    def test_official_contract_requires_official_docs_source(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[2]["source_ref"] = "https://example.com/agents"
        report = self.evaluate(evidence)
        self.assertIn("invalid_official_source", report["reasons"][0])

    def test_account_gate_cannot_be_satisfied_by_public_documentation(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[3]["source_kind"] = "official_documentation"
        evidence[3]["source_ref"] = "https://developers.openai.com/api/docs/guides/spend-limits"
        report = self.evaluate(evidence)
        self.assertIn("unexpected_source_kind", report["reasons"][0])

    def test_unexpected_claim_blocks(self):
        evidence = synthetic_reference_evidence(NOW)
        evidence[1]["claim"] = "all_permissions_observed"
        report = self.evaluate(evidence)
        self.assertIn("unexpected_claim", report["reasons"][0])

    def test_secret_like_extra_field_is_rejected_without_echo(self):
        evidence = synthetic_reference_evidence(NOW)
        marker = "sk-sensitive-marker-must-not-leak"
        evidence[0]["api_key"] = marker
        report = self.evaluate(evidence)
        rendered = json.dumps(report)
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertNotIn(marker, rendered)
        self.assertNotIn("api_key", rendered)

    def test_invalid_expected_project_ref_blocks(self):
        report = evaluate_readonly_evidence(
            synthetic_reference_evidence(NOW),
            expected_project_ref="bad project ref",
            now=NOW,
        )
        self.assertEqual(report["reasons"], ["invalid_expected_project_ref"])

    def test_non_list_and_empty_evidence_block(self):
        for value in (None, {}, (), "", True, 1, []):
            with self.subTest(value=value):
                report = evaluate_readonly_evidence(
                    value,
                    expected_project_ref=PROJECT,
                    now=NOW,
                )
                self.assertEqual(report["decision"], "BLOCKED")

    def test_verifier_does_not_touch_network_process_files_or_environment(self):
        with (
            patch("socket.socket") as socket_call,
            patch("subprocess.Popen") as process,
            patch("builtins.open") as open_file,
            patch("os.getenv") as getenv,
        ):
            report = self.evaluate(synthetic_reference_evidence(NOW))
        self.assertEqual(report["decision"], "READ_ONLY_VERIFIED")
        socket_call.assert_not_called()
        process.assert_not_called()
        open_file.assert_not_called()
        getenv.assert_not_called()

    def test_cli_reference_never_returns_live_go(self):
        output = io.StringIO()
        with (
            patch("developer_team.agents_readonly_verification.time.time", return_value=NOW),
            contextlib.redirect_stdout(output),
        ):
            code = main(["--synthetic-reference"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["decision"], "READ_ONLY_VERIFIED")
        self.assertEqual(report["live"], "NO-GO")

    def test_cli_exposes_no_secret_or_live_authority_flags(self):
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
