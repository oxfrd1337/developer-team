"""DT-004 contract tests. ALL provider responses here are explicitly test doubles."""

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from developer_team.adapters.cloud_contracts import CloudApproval
from developer_team.adapters.codex_cloud import CodexCloudGateway
from developer_team.adapters.pilot_fake import RehearsalCLI, RehearsalRefs, _patch
from developer_team.adapters.synthetic import create_fixture
from developer_team.authority import ProjectGrant
from developer_team.cli import main, parser
from developer_team.config import Check
from developer_team.execution import SyntheticCommandRunner
from developer_team.models import Origin, Outcome, Role, TeamError
from developer_team.pilot import write_json
from developer_team.pilot_runner import PilotCommandRunner
from developer_team.pilot_scope import PILOT_REPOSITORY, PILOT_WRITABLE
from developer_team.supervised_pilot import (
    CAPABILITIES,
    ROLES,
    PilotReadiness,
    _approved_engine,
    execute_supervised,
    prepare_supervised,
    read_preparation,
)
from developer_team.workspace import GitWorkspace
from tests.cloud_support import Clock

REPOSITORY = Path(__file__).resolve().parents[1]
PROBE = {
    "version": "codex-cli 0.163.0",
    **dict.fromkeys(
        (
            "chatgpt_login_reported",
            "submit_interface_present",
            "status_interface_present",
            "diff_interface_present",
            "list_json_interface_present",
        ),
        True,
    ),
}


class SupervisedPilotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = create_fixture(self.root / "source")
        for path in [
            REPOSITORY / "examples/project.pilot.toml",
            *sorted((REPOSITORY / "pilot_project").rglob("*")),
        ]:
            if path.is_file() and "__pycache__" not in path.parts:
                self.source.write(str(path.relative_to(REPOSITORY)), path.read_text())
        self.source.commit("Unchanged artificial pilot input")
        self.session = self.root / "session"
        self.preparation = prepare_supervised(self.source.root, self.session)
        p = self.preparation
        self.approval = CloudApproval(
            p["run_id"],
            PILOT_REPOSITORY,
            p["config_digest"],
            "test-operator",
            time.time() + 3600,
        )
        self.grant = ProjectGrant(
            "dt-003-pilot",
            PILOT_REPOSITORY,
            p["config_digest"],
            CAPABILITIES,
            approved_by="test-operator",
            cloud_environments=tuple((r, "test-env-" + r.value) for r in ROLES),
        )
        self.readiness = PilotReadiness(
            self.source.head, "test-only durable volume", "test-only isolation", "test quota"
        )
        self.clock = Clock()
        self.clock.value = time.time()

    def engine(self, approval=None, grant=None, readiness=None):
        return _approved_engine(
            self.session,
            read_preparation(self.session),
            approval or self.approval,
            grant or self.grant,
            readiness or self.readiness,
        )

    @contextlib.contextmanager
    def available_host(self):
        with (
            patch.object(CodexCloudGateway, "probe", return_value=PROBE),
            patch.object(PilotCommandRunner, "require_available"),
        ):
            yield

    def fake_gateway(self, *, store, refs):
        workspace = refs.workspace
        return CodexCloudGateway(
            RehearsalCLI(workspace, store, self.approval.run_id, self.scenario),
            store=store,
            refs=RehearsalRefs(workspace),
            now=self.clock,
        )

    def rehearsal(self, scenario="happy", ticks=20):
        self.scenario = scenario
        # Only provider interactions are faked. Python checks and Git import/commits
        # are real. Sandbox checks are tested separately; unavailable hosts block live.
        original_run = SyntheticCommandRunner.run

        def local_check(runner, check, root):
            return original_run(
                SyntheticCommandRunner(audit_directory=runner.artifacts), check, root
            )

        with (
            self.available_host(),
            patch(
                "developer_team.supervised_pilot.CodexCloudGateway", side_effect=self.fake_gateway
            ),
            patch.object(PilotCommandRunner, "run", local_check),
        ):
            for _ in range(ticks):
                report = execute_supervised(
                    self.session,
                    approval=self.approval,
                    grant=self.grant,
                    readiness=self.readiness,
                )
                if report["run"]["status"] not in ("running", "paused"):
                    return report
                self.clock.advance(10)
        return report

    def test_preparation_is_local_only_and_does_not_grant_dispatch(self):
        with patch("subprocess.Popen", side_effect=AssertionError("No CLI expected")):
            p = read_preparation(self.session)
        self.assertFalse(p["cloud_dispatch_authorized"])
        workspace = GitWorkspace(self.session / "project")
        self.assertEqual(workspace.head, self.source.head)
        self.assertEqual(workspace.git("remote"), "")
        self.assertEqual((self.session.stat().st_mode & 0o777), 0o700)
        self.assertEqual(
            workspace.read("pilot_project/requirement.txt"),
            self.source.read("pilot_project/requirement.txt"),
        )

    def test_cli_can_prepare_but_has_no_cloud_activation_or_live_mode(self):
        output = self.root / "cli-preparation"
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch.object(CodexCloudGateway, "submit") as submit,
        ):
            self.assertEqual(
                main(
                    [
                        "pilot-plan",
                        "--source",
                        str(self.source.root),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
        submit.assert_not_called()
        commands = parser()._subparsers._group_actions[0].choices
        self.assertFalse({"live", "activate", "force", "admin"} & set(commands))
        self.assertFalse(read_preparation(output)["cloud_dispatch_authorized"])

    def test_existing_state_and_dirty_source_are_never_overwritten(self):
        with self.assertRaises(TeamError):
            prepare_supervised(self.source.root, self.session)
        self.source.write("pilot_project/calculator.py", "uncommitted")
        with self.assertRaises(TeamError):
            prepare_supervised(self.source.root, self.root / "dirty")

    def test_saved_json_cannot_authorize_or_widen_scope(self):
        for changes in (
            {"cloud_dispatch_authorized": True},
            {"allowed_paths": ["**"]},
            {"mode": "test-adapters-only"},
            {"repository": "other/repository"},
        ):
            with self.subTest(changes=changes):
                write_json(self.session / "preparation.json", self.preparation | changes)
                with self.assertRaises(TeamError):
                    read_preparation(self.session)

    def test_grants_and_budgets_block_before_any_remote_call(self):
        bad = (
            {"approval": replace(self.approval, expires_at=time.time() - 1)},
            {"approval": replace(self.approval, max_tasks=9)},
            {"approval": replace(self.approval, poll_interval_seconds=1)},
            {"grant": replace(self.grant, capabilities=CAPABILITIES | {"merge"})},
            {"grant": replace(self.grant, capabilities=CAPABILITIES - {"develop"})},
            {"grant": replace(self.grant, repository="other/repository")},
            {"grant": replace(self.grant, cloud_environments=tuple((r, "shared") for r in ROLES))},
            {"grant": replace(self.grant, cloud_environments=self.grant.cloud_environments[:-1])},
            {"grant": replace(self.grant, auto_merge_approved=True)},
            {"readiness": replace(self.readiness, cloud_role_isolation_review="")},
            {"readiness": replace(self.readiness, controller_sha="f" * 40)},
        )
        with patch.object(CodexCloudGateway, "probe") as probe:
            for changes in bad:
                with self.subTest(changes=changes), self.assertRaises(TeamError):
                    self.engine(**changes)
        probe.assert_not_called()

    def test_missing_journal_blocks_without_recreating_it(self):
        (self.session / "state.sqlite3").unlink()
        with self.assertRaises(TeamError):
            execute_supervised(
                self.session,
                approval=self.approval,
                grant=self.grant,
                readiness=self.readiness,
            )
        self.assertFalse((self.session / "state.sqlite3").exists())

    def test_unrelated_sqlite_file_does_not_become_a_new_live_journal(self):
        path = self.session / "state.sqlite3"
        path.unlink()
        with contextlib.closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE unrelated (id TEXT)")
        with self.assertRaisesRegex(TeamError, "journal schema"):
            execute_supervised(
                self.session,
                approval=self.approval,
                grant=self.grant,
                readiness=self.readiness,
            )
        with contextlib.closing(sqlite3.connect(path)) as connection:
            names = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        self.assertEqual(names, [("unrelated",)])

    def test_lost_authorization_binding_after_submission_is_not_recreated(self):
        report = self.rehearsal(ticks=1)
        self.assertEqual(len(report["tasks"]), 1)
        (self.session / "authorization-binding.json").unlink()
        with self.available_host(), self.assertRaisesRegex(TeamError, "binding lost"):
            self.engine()
        self.assertFalse((self.session / "authorization-binding.json").exists())

    def test_symlinked_preparation_blocks(self):
        original = self.session / "preparation.json"
        moved = self.root / "moved.json"
        original.rename(moved)
        original.symlink_to(moved)
        with self.assertRaises(TeamError):
            read_preparation(self.session)

    def test_authority_seal_prevents_changed_grants_on_resume(self):
        with self.available_host():
            self.engine()
            with self.assertRaisesRegex(TeamError, "authorization changed"):
                self.engine(
                    grant=replace(
                        self.grant,
                        cloud_environments=tuple(
                            (r, env + "-new") for r, env in self.grant.cloud_environments
                        ),
                    )
                )
            with self.assertRaisesRegex(TeamError, "authorization changed"):
                self.engine(approval=replace(self.approval, max_tasks=7))

    def test_login_interface_version_or_sandbox_failure_never_submits(self):
        with patch.object(CodexCloudGateway, "submit") as submit:
            for change in ({"version": "codex-cli unknown"}, {"chatgpt_login_reported": False}):
                with (
                    patch.object(CodexCloudGateway, "probe", return_value=PROBE | change),
                    self.assertRaises(TeamError),
                ):
                    self.engine()
            with (
                patch.object(CodexCloudGateway, "probe", return_value=PROBE),
                patch.object(
                    PilotCommandRunner, "require_available", side_effect=TeamError("denied")
                ),
                self.assertRaises(TeamError),
            ):
                self.engine()
        submit.assert_not_called()

    def test_protected_control_change_blocks_before_cli(self):
        workspace = GitWorkspace(self.session / "project")
        workspace.write("SECURITY.md", "tampered")
        workspace.commit("Forbidden change")
        with patch.object(CodexCloudGateway, "probe") as probe, self.assertRaises(TeamError):
            self.engine()
        probe.assert_not_called()

    def test_scope_rejects_source_patch_outside_three_files(self):
        workspace = GitWorkspace(self.session / "project")
        with self.available_host():
            engine = self.engine()
        from developer_team.adapters.base import AgentContext
        from developer_team.adapters.cloud_contracts import RESULT_PATH

        context = AgentContext(
            "fixture", engine.config, engine.documents, workspace, self.approval.run_id
        )
        job = engine.agents.job(context, Role.DEVELOPER, {})
        artifact = _patch(RESULT_PATH, None, json.dumps(job.envelope()) + "\n")
        illegal = _patch("pilot_project/new.py", None, "unauthorized = True\n")
        with self.assertRaisesRegex(TeamError, "scope"):
            engine.agents.importer.extract(workspace, engine.config, job, artifact + illegal)
        self.assertEqual(workspace.head, self.source.head)
        workspace.assert_clean()

    def test_complete_double_run_retains_results_checks_statuses_and_manual_gate(self):
        report = self.rehearsal()
        self.assertEqual(report["run"]["status"], "blocked")
        self.assertEqual(report["agent_actions"], "simulated")
        self.assertEqual(report["agent_backend"], "test-adapter")
        self.assertFalse(report["cloud_execution_verified"])
        self.assertFalse(report["merge_enabled"])
        tasks = report["tasks"]
        self.assertEqual(len(tasks), 4)
        self.assertEqual(len({t["task_id"] for t in tasks}), 4)
        self.assertEqual(len({t["environment"] for t in tasks}), 4)
        self.assertTrue(all(t["provider_status"] == "ready" for t in tasks))
        self.assertTrue(all(t["result_digest"] for t in tasks))
        self.assertEqual(len(list((self.session / "results").glob("*.json"))), 4)
        self.assertTrue(
            all(
                json.loads(path.read_text())["origin"] == "simulated"
                for path in (self.session / "results").glob("*.json")
            )
        )
        checks = [json.loads(p.read_text()) for p in (self.session / "checks").glob("*.json")]
        # Fresh process-local evidence reruns checks. Python's timing output can
        # produce several digests for the same check; retain all of those logs.
        self.assertEqual({c["name"] for c in checks}, {"pilot-acceptance", "pilot-unit"})
        self.assertTrue(all(c["returncode"] == 0 and "OK" in c["detail"] for c in checks))
        for evidence in report["run"]["evidence"]:
            expected = (
                Origin.LOCAL_EXECUTION
                if evidence["kind"].startswith("check:")
                else Origin.SIMULATED
            )
            self.assertEqual(evidence["origin"], expected)
        self.assertEqual(
            set(GitWorkspace(self.session / "project").changed_paths(self.source.head)),
            set(PILOT_WRITABLE),
        )

    def test_real_python_failure_is_repaired_with_retained_diagnostics(self):
        report = self.rehearsal("test-fix")
        self.assertEqual(report["run"]["status"], "blocked")
        self.assertEqual(report["run"]["repairs"], {"test": 1})
        checks = [json.loads(p.read_text()) for p in (self.session / "checks").glob("*.json")]
        self.assertTrue(any(c["returncode"] != 0 and "FAIL" in c["detail"] for c in checks))
        self.assertTrue(any(c["returncode"] == 0 and "OK" in c["detail"] for c in checks))

    def test_failed_and_corrected_qa_results_both_survive_restart(self):
        report = self.rehearsal("qa-fix")
        self.assertEqual(report["run"]["status"], "blocked")
        self.assertEqual(report["run"]["repairs"], {"qa": 1})
        self.assertEqual(len({t["task_id"] for t in report["tasks"]}), 6)
        qa = [
            json.loads(p.read_text())
            for p in (self.session / "results").glob("*.json")
            if json.loads(p.read_text())["binding"]["role"] == "qa"
        ]
        self.assertEqual({r["payload"]["outcome"] for r in qa}, {"fail", "pass"})
        self.assertEqual(len({r["binding"]["head_sha"] for r in qa}), 2)


class PilotIsolationTests(unittest.TestCase):
    def test_missing_bubblewrap_has_no_host_fallback(self):
        with patch("shutil.which", return_value=None), self.assertRaises(TeamError):
            PilotCommandRunner.command(Path.cwd(), ("python3", "-c", "pass"))

    def test_output_retention_is_bounded_and_keeps_failure_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = SyntheticCommandRunner(audit_directory=root / "checks")
            result = runner.run(
                Check(
                    "failure",
                    "test",
                    (
                        "python3",
                        "-c",
                        "print('X' * 25000); print('assertion detail'); raise SystemExit(1)",
                    ),
                    10,
                    True,
                ),
                root,
            )
            self.assertEqual(result.outcome, Outcome.FAIL)
            self.assertIn("assertion detail", result.detail)
            self.assertLess(len(result.detail), 16100)
            self.assertEqual(len(list((root / "checks").glob("*.json"))), 1)

    def test_real_namespace_boundary_if_supported_by_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = create_fixture(root / "project")
            runner = PilotCommandRunner(root / "checks")
            try:
                runner.require_available(workspace.root)
            except TeamError as exc:
                self.skipTest(f"Host cannot provide the required boundary: {exc}")
            secret = root / "controller-secret.txt"
            secret.write_text("not-a-real-secret")
            script = (
                "import os, pathlib, socket; "
                f"assert not pathlib.Path({str(secret)!r}).exists(); "
                "assert not os.getenv('DT_TEST_CREDENTIAL'); "
                "assert not pathlib.Path('/root/.codex/auth.json').exists(); "
                "p = pathlib.Path('/project/forbidden'); "
                "\ntry: p.write_text('forbidden')\nexcept OSError: pass\n"
                "else: raise AssertionError('write allowed')\n"
                "s = socket.socket(); s.settimeout(1)\n"
                "try: s.connect(('192.0.2.1', 80))\nexcept OSError: pass\n"
                "else: raise AssertionError('network allowed')\n"
            )
            with patch.dict(os.environ, {"DT_TEST_CREDENTIAL": "never-export-this"}):
                result = runner.run(
                    Check("isolation", "test", ("python3", "-I", "-c", script), 10, True),
                    workspace.root,
                )
            self.assertEqual(result.outcome, Outcome.PASS, result.detail)
            workspace.assert_clean()
