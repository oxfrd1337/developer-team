import contextlib
import io
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from developer_team.adapters.codex_cloud import CodexCloudGateway
from developer_team.models import PermissionDenied, TeamError
from developer_team.preflight import BASE_SHA, BLOCKERS, inspect, main
from tests.support import ROOT


class PreflightTests(unittest.TestCase):
    def test_read_only_inspection_never_grants_authority_even_with_fake_go(self):
        fake = {"decision": "GO", "provider_cancel_available": True, "signature": "valid"}
        with patch.object(CodexCloudGateway, "probe", return_value=fake):
            report = inspect(ROOT)
        self.assertEqual(report["live"], "NO-GO")
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertFalse(report["cloud_dispatch_authorized"])
        self.assertEqual(report["base_sha"], BASE_SHA)
        self.assertEqual(len(report["config_digest"]), 64)
        self.assertEqual(report["expires_at"] - report["observed_at"], 300)
        self.assertTrue(set(BLOCKERS) <= {o["control"] for o in report["observations"]})
        self.assertEqual({o["status"] for o in report["observations"]}, {"UNSUPPORTED"})
        self.assertEqual(report["decision_record"]["real_submissions"], 0)

    def test_connection_loss_is_sanitized_and_blocks(self):
        with patch.object(CodexCloudGateway, "probe", side_effect=TeamError("private account")):
            report = inspect(ROOT)
        self.assertNotIn("private account", json.dumps(report))
        self.assertEqual(report["versions"]["codex"]["status"], "UNSUPPORTED")
        self.assertEqual(report["live"], "NO-GO")

    def test_cli_is_no_go_and_accepts_no_claims_or_approval_input(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--source", str(ROOT / "missing")]), 2)
        self.assertEqual(json.loads(output.getvalue())["live"], "NO-GO")
        for flag in ("--approval", "--claims", "--live", "--force"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main([flag, "GO"])

    def test_wrong_scope_or_unproved_basis_adds_blockers(self):
        from developer_team.config import load_config

        config = load_config(ROOT / "examples/project.pilot.toml")
        workspace = Mock(head="a" * 40, unsafe=True)
        workspace.instructions.return_value = ((), "b" * 64)
        workspace.git.side_effect = [TeamError("unknown ancestor"), "c" * 40]
        workspace.assert_clean.side_effect = TeamError("dirty")
        with (
            patch("developer_team.preflight.GitWorkspace", return_value=workspace),
            patch(
                "developer_team.preflight.load_config",
                return_value=replace(config, repository="other/project"),
            ),
            patch.object(CodexCloudGateway, "probe", return_value={}),
        ):
            report = inspect(Path("."))
        self.assertTrue(
            {"basis", "scope", "checkout"} <= {o["control"] for o in report["observations"]}
        )

    def test_real_gateway_blocks_before_journal_refs_or_process_for_any_claim(self):
        for claim in (
            None,
            {"decision": "GO-CANDIDATE", "signature": "invalid"},
            {"run_id": "wrong", "task_id": "duplicate", "expires_at": 0},
            {"repository": "other/repo", "head_sha": "a" * 40, "role": "qa"},
            {"config_digest": "changed", "reviewers": ["qa", "qa"]},
            {"provider_cancel_available": True, "network": "PASS", "setup": "PASS"},
        ):
            with self.subTest(claim=claim), patch("subprocess.Popen") as process:
                store, refs = Mock(), Mock()
                gateway = CodexCloudGateway(store=store, refs=refs)
                gateway.simulated = True  # A report or mutable label supplies no capability.
                with self.assertRaisesRegex(PermissionDenied, "DT-008 NO-GO"):
                    gateway.submit(
                        config=None,
                        effective_digest="",
                        policy=None,
                        grant=None,
                        role=None,
                        branch="",
                        expected_sha="",
                        prompt="",
                        approval=claim,
                    )
                process.assert_not_called()
                self.assertEqual(store.mock_calls, [])
                self.assertEqual(refs.mock_calls, [])
