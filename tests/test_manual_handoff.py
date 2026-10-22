"""Offline handoff claims must never become merge or cloud authority."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from developer_team.manual_handoff import (
    SECURITY_CHECKS,
    InvalidHandoff,
    check_handoff,
    load_handoff,
    main,
)


def fixture():
    binding = {
        "repo": "synthetic/manual",
        "issue": 15,
        "branch": "dt-010/example",
        "base_sha": "a" * 40,
        "pr": 16,
        "head_sha": "b" * 40,
    }
    result = {"status": "PASS", "evidence": "synthetic evidence; not an attestation"}
    data = {
        "version": 1,
        "binding": binding,
        "allowed_files": ["src/example.py"],
        "changed_files": ["src/example.py"],
        "developer": "synthetic-dev",
        "ci": {
            "binding": copy.deepcopy(binding),
            "run_url": "https://github.com/synthetic/manual/actions/runs/123",
            "jobs": {"tests": copy.deepcopy(result)},
        },
        "risks": [],
        "unknown_checks": [],
        "blockers": [],
    }
    for role in ("qa", "security"):
        data[role] = {
            "binding": copy.deepcopy(binding),
            "reviewer": f"synthetic-{role}",
            "task_ref": f"synthetic-task-{role}",
            **copy.deepcopy(result),
        }
    data["security"]["checks"] = {key: copy.deepcopy(result) for key in SECURITY_CHECKS}
    return data, copy.deepcopy(binding), ["src/example.py"]


class ManualHandoffTests(unittest.TestCase):
    def setUp(self):
        self.data, self.pins, self.allowed = fixture()

    def check(self, data=None):
        report = check_handoff(
            self.data if data is None else data, expected=self.pins, allowed_files=self.allowed
        )
        self.assertIs(report["merge_authorized"], False)
        self.assertIs(report["cloud_authorized"], False)
        self.assertIs(report["provenance_verified"], False)
        return report

    def blocked(self, data=None):
        self.assertEqual(self.check(data)["status"], "BLOCKED")

    def test_complete_claims_only_request_manual_review(self):
        self.assertEqual(self.check()["status"], "MANUAL_REVIEW_REQUIRED")
        self.assertIn("commit_existence_unverified", self.check()["limitations"])

    def test_wrong_repository_issue_branch_pr_base_or_head(self):
        for key, value in (
            ("repo", "attacker/repo"),
            ("issue", 99),
            ("branch", "other"),
            ("pr", 99),
            ("base_sha", "c" * 40),
            ("head_sha", "d" * 40),
        ):
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                data["binding"][key] = value
                self.blocked(data)

    def test_missing_invalid_and_boolean_bindings(self):
        for key in self.pins:
            for value in (None, "", True, [], {}, "short"):
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(self.data)
                    data["binding"][key] = value
                    self.blocked(data)
        for key in ("base_sha", "head_sha"):
            for value in ("0" * 40, "A" * 40, "a" * 39, "a" * 41):
                data = copy.deepcopy(self.data)
                data["binding"][key] = value
                self.blocked(data)

    def test_untrusted_manifest_cannot_replace_operator_pins(self):
        for location in ("binding", "ci", "qa", "security"):
            data = copy.deepcopy(self.data)
            binding = data[location] if location == "binding" else data[location]["binding"]
            binding["head_sha"] = "c" * 40
            self.blocked(data)
        self.pins["head_sha"] = "e" * 40
        self.blocked()

    def test_revision_invalidates_both_reviews_and_ci(self):
        self.pins["head_sha"] = self.data["binding"]["head_sha"] = "e" * 40
        report = self.check()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(
            {"stale_ci", "stale_review:qa", "stale_review:security"} <= set(report["reasons"])
        )
        self.data["qa"]["binding"]["head_sha"] = "e" * 40
        self.blocked()

    def test_scopes_traversal_globs_and_command_injection(self):
        for path in (
            "../README.md",
            "/absolute/file",
            "src/../file",
            "src//file",
            "src/./file",
            ".git/config",
            "src\\file",
            "src/*",
            "$(touch hacked)",
            "`id`",
            "a\nb",
        ):
            with self.subTest(path=path):
                for key in ("allowed_files", "changed_files"):
                    data = copy.deepcopy(self.data)
                    data[key] = [path]
                    self.blocked(data)
        self.data["changed_files"] = ["AGENTS.md"]
        self.blocked()
        self.data["allowed_files"].append("AGENTS.md")
        self.blocked()

    def test_missing_or_duplicate_paths(self):
        for key in ("allowed_files", "changed_files"):
            for value in ([], None, ["src/example.py"] * 2):
                data = copy.deepcopy(self.data)
                data[key] = value
                self.blocked(data)

    def test_missing_reviews_and_ci(self):
        for key in ("qa", "security", "ci"):
            for value in (None, {}, [], "PASS"):
                data = copy.deepcopy(self.data)
                data[key] = value
                self.blocked(data)
            data = copy.deepcopy(self.data)
            del data[key]
            self.blocked(data)

    def test_fail_unsupported_unknown_and_missing_evidence(self):
        for role in ("qa", "security"):
            for status in ("FAIL", "UNSUPPORTED", "UNKNOWN", "", None, True, ["PASS"]):
                data = copy.deepcopy(self.data)
                data[role]["status"] = status
                self.blocked(data)
            self.data[role]["evidence"] = ""
            self.blocked()

    def test_security_overall_pass_cannot_hide_incomplete_checks(self):
        for check in SECURITY_CHECKS:
            for value in (
                {"status": "UNSUPPORTED", "evidence": "not readable"},
                {"status": "FAIL", "evidence": "violation"},
                {"status": "PASS", "evidence": ""},
                {},
            ):
                data = copy.deepcopy(self.data)
                data["security"]["checks"][check] = value
                self.blocked(data)
            data = copy.deepcopy(self.data)
            del data["security"]["checks"][check]
            self.blocked(data)

    def test_ci_no_jobs_missing_link_wrong_repo_nonpass(self):
        for value in ({}, None, []):
            data = copy.deepcopy(self.data)
            data["ci"]["jobs"] = value
            self.blocked(data)
        for value in (
            "",
            None,
            "https://github.com/attacker/repo/actions/runs/123",
            "https://github.com/synthetic/manual/actions/runs/123?fake=1",
        ):
            data = copy.deepcopy(self.data)
            data["ci"]["run_url"] = value
            self.blocked(data)
        for value in ("FAIL", "UNSUPPORTED", "skipped", "pending", "cancelled"):
            data = copy.deepcopy(self.data)
            data["ci"]["jobs"]["tests"]["status"] = value
            self.blocked(data)

    def test_identity_claims_do_not_establish_independence(self):
        self.data["security"]["reviewer"] = self.data["developer"]
        self.blocked()
        self.data["security"]["reviewer"] = self.data["qa"]["reviewer"]
        self.blocked()
        self.data, _, _ = fixture()
        self.data["security"]["task_ref"] = self.data["qa"]["task_ref"]
        self.blocked()
        for key in ("reviewer", "task_ref"):
            self.data, _, _ = fixture()
            self.data["security"][key] = ""
            self.blocked()

    def test_risks_unknown_checks_and_blockers_remain_blocking(self):
        for key in ("risks", "unknown_checks", "blockers"):
            data = copy.deepcopy(self.data)
            data[key] = ["operator accepted synthetic exception elsewhere"]
            self.blocked(data)

    def test_unknown_authority_fields_rejected(self):
        for key in ("merge_authorized", "cloud_authorized", "live", "force", "command"):
            data = copy.deepcopy(self.data)
            data[key] = True
            self.blocked(data)
        self.data["security"]["signature"] = "self-signed PASS"
        self.blocked()

    def test_invalid_shapes_and_pins(self):
        for value in ([], "PASS", 1, True):
            self.blocked(value)
        self.pins["pr"] = True
        self.blocked()
        self.pins["pr"] = 16
        self.allowed = ["../anything"]
        self.blocked()

    def test_duplicate_json_keys_at_all_levels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            for raw in ('{"version":1,"version":1}', '{"qa":{"status":"FAIL","status":"PASS"}}'):
                path.write_text(raw)
                with self.assertRaises(InvalidHandoff):
                    load_handoff(path)
            path.write_text(" " * 1_000_001)
            with self.assertRaises(InvalidHandoff):
                load_handoff(path)

    def test_cli_is_read_only_and_always_returns_nonapproval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            args = [str(path), "--allowed-file", self.allowed[0]]
            for key, value in self.pins.items():
                args.extend(["--" + key.replace("_", "-"), str(value)])
            with (
                patch("subprocess.Popen") as process,
                patch("socket.socket") as network,
                patch("urllib.request.urlopen") as urlopen,
            ):
                for raw in (json.dumps(self.data), '{"merge_authorized":true}', "invalid JSON"):
                    path.write_text(raw)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(main(args), 2)
                    report = json.loads(output.getvalue())
                    self.assertFalse(report["merge_authorized"] or report["cloud_authorized"])
                    self.assertEqual(path.read_text(), raw)
                process.assert_not_called()
                network.assert_not_called()
                urlopen.assert_not_called()
            path.unlink()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 2)

    def test_no_live_or_merge_cli_flags(self):
        for flag in ("--live", "--activate", "--merge", "--force", "--admin"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main([flag])
            self.assertEqual(error.exception.code, 2)

    def test_shipped_example_remains_blocked(self):
        path = Path(__file__).resolve().parents[1] / "examples/manual-handoff.synthetic.json"
        data = load_handoff(path)
        report = check_handoff(data, expected=data["binding"], allowed_files=data["allowed_files"])
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("missing_or_nonpass:security:deployment", report["reasons"])
        self.assertFalse(report["merge_authorized"] or report["cloud_authorized"])
