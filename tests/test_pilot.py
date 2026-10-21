"""DT-003: real local changes/checks, fake agents, portable state and fail-closed restore."""

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from developer_team.adapters.codex_cloud import CodexCloudGateway
from developer_team.adapters.pilot_fake import PILOT_WRITABLE, RehearsalCLI, _patch
from developer_team.adapters.synthetic import create_fixture
from developer_team.checkpoints import (
    check_artifact_source,
    checkpoint,
    restore_checkpoint,
    validate_artifact_source,
)
from developer_team.cli import main
from developer_team.execution import SyntheticCommandRunner
from developer_team.models import IntegrationUnavailable, TeamError
from developer_team.pilot import (
    PILOT_REPOSITORY,
    prepare_session,
    read_session,
    rehearsal_engine,
    step_rehearsal,
    write_json,
)
from developer_team.store import RunStore
from developer_team.workspace import GitWorkspace

REPOSITORY = Path(__file__).resolve().parents[1]


class PilotTests(unittest.TestCase):
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
        self.source.commit("Prepare artificial DT-003 fixture")
        self.session = self.root / "session"
        self.report = prepare_session(self.source.root, self.session)
        self.run_id = self.report["run_id"]

    def restore(self, saved=None, destination=None, **kwargs):
        saved = saved or self.root / "checkpoint"
        destination = destination or self.root / "resumed"
        return restore_checkpoint(
            saved,
            destination,
            **({"controller_sha": self.source.head, "run_id": self.run_id} | kwargs),
        )

    def test_complete_rehearsal_uses_existing_engine_and_retains_manual_gate(self):
        with (
            patch("developer_team.adapters.codex_cloud.run_cli") as live_cli,
            patch("developer_team.adapters.github.GhCliTransport.request") as remote_api,
        ):
            report = step_rehearsal(self.session, ticks=24)
        live_cli.assert_not_called()
        remote_api.assert_not_called()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["repairs"], {"qa": 1})
        self.assertEqual(len(report["tasks"]), 6)
        self.assertEqual(len({t["task_id"] for t in report["tasks"]}), 6)
        self.assertEqual(set(report["checks"].values()), {"pass"})
        self.assertEqual(set(report["changed_paths"]), set(PILOT_WRITABLE))
        self.assertEqual(report["real_cloud_submissions"], 0)
        self.assertEqual(report["agent_actions"], "simulated")
        self.assertFalse(report["cloud_execution_verified"])
        reviews = report["tasks"][-2:]
        self.assertEqual([t["role"] for t in reviews], ["qa", "security"])
        self.assertEqual(reviews[0]["head_sha"], reviews[1]["head_sha"])
        run = RunStore(self.session / "state.sqlite3").load(self.run_id)
        self.assertIsNotNone(run.plan)
        self.assertIsNotNone(run.architecture)
        self.assertEqual(run.pr.number, 0)

    def test_initial_acceptance_fails_and_is_executed_after_real_local_change(self):
        session = read_session(self.session)
        engine = rehearsal_engine(self.session, session)
        result = SyntheticCommandRunner().run(engine.config.checks[0], engine.workspace.root)
        self.assertNotEqual(result.returncode, 0)
        report = step_rehearsal(self.session, ticks=24)
        self.assertEqual(report["checks"]["check:pilot-acceptance"], "pass")
        self.assertNotEqual(report["head_sha"], self.source.head)
        self.source.assert_clean()

    def test_pending_task_and_budgets_survive_new_checkout_and_controller(self):
        first = step_rehearsal(self.session)
        self.assertEqual(first["status"], "paused")
        self.assertEqual(len(first["tasks"]), 1)
        store = RunStore(self.session / "state.sqlite3")
        with store.connect() as connection:
            limits = connection.execute("SELECT * FROM cloud_limits").fetchall()
        checkpoint(self.session, self.root / "checkpoint")
        self.restore()
        # The old runner and its checkout are gone; only the verified checkpoint survives.
        shutil.rmtree(self.session)
        report = step_rehearsal(self.root / "resumed", ticks=24)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["tasks"][0]["task_id"], first["tasks"][0]["task_id"])
        self.assertEqual(len(report["tasks"]), 6)
        with RunStore(self.root / "resumed/state.sqlite3").connect() as connection:
            self.assertEqual(connection.execute("SELECT * FROM cloud_limits").fetchall(), limits)

    def test_imported_commit_and_pending_review_survive_runner_replacement(self):
        before = step_rehearsal(self.session, ticks=3)
        self.assertEqual(before["stage"], "qa")
        self.assertNotEqual(before["head_sha"], self.source.head)
        checkpoint(self.session, self.root / "checkpoint")
        self.restore()
        after = step_rehearsal(self.root / "resumed", ticks=24)
        self.assertEqual(after["status"], "blocked")
        self.assertEqual(before["tasks"][-1]["task_id"], after["tasks"][2]["task_id"])
        self.assertEqual(len(after["tasks"]), 6)

    def test_terminal_resume_does_not_start_new_tasks_or_consume_ticks(self):
        before = step_rehearsal(self.session, ticks=24)
        after = step_rehearsal(self.session, ticks=24)
        self.assertEqual(before["tasks"], after["tasks"])
        self.assertEqual(before["ticks"], after["ticks"])

    def test_real_test_failure_enters_bounded_correction(self):
        prepare_session(self.source.root, self.root / "test-fix", scenario="test-fix")
        report = step_rehearsal(self.root / "test-fix", ticks=24)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["repairs"], {"test": 1})
        self.assertEqual(set(report["checks"].values()), {"pass"})
        self.assertEqual(len(report["tasks"]), 5)

    def test_repair_limit_escalates_without_merge(self):
        prepare_session(self.source.root, self.root / "limit", scenario="repair-limit")
        report = step_rehearsal(self.root / "limit", ticks=24)
        self.assertEqual(report["status"], "escalated")
        self.assertEqual(report["repairs"], {"test": 1})
        self.assertEqual(len(report["tasks"]), 3)

    def test_task_budget_cannot_reset_on_resume(self):
        prepare_session(self.source.root, self.root / "budget", max_tasks=2)
        report = step_rehearsal(self.root / "budget", ticks=24)
        self.assertEqual(report["status"], "escalated")
        self.assertEqual(len(report["tasks"]), 2)
        again = step_rehearsal(self.root / "budget", ticks=24)
        self.assertEqual(report["tasks"], again["tasks"])

    def test_edited_budget_after_first_submission_cannot_authorize_more_tasks(self):
        step_rehearsal(self.session)
        session = read_session(self.session)
        session["runtime_seconds"] += 10
        write_json(self.session / "session.json", session)
        report = step_rehearsal(self.session)
        self.assertEqual(report["status"], "escalated")
        self.assertEqual(len(report["tasks"]), 1)

    def test_invalid_limits_and_reused_output_are_rejected(self):
        with self.assertRaises(TeamError):
            prepare_session(self.source.root, self.root / "bad", max_tasks=True)
        with self.assertRaises(TeamError):
            prepare_session(self.source.root, self.session)
        with self.assertRaises(TeamError):
            step_rehearsal(self.session, ticks=25)

    def test_changed_controller_scope_and_agent_attempt_to_edit_acceptance_block(self):
        original = RehearsalCLI._diff

        def malicious(cli, record):
            result = original(cli, record)
            if record["job"]["role"] == "developer":
                path = "pilot_project/acceptance.py"
                old = cli.workspace.git("show", record["job"]["head_sha"] + ":" + path, strip=False)
                result += _patch(path, old, "# removed tests\n")
            return result

        with patch.object(RehearsalCLI, "_diff", malicious):
            report = step_rehearsal(self.session, ticks=24)
        self.assertEqual(report["status"], "escalated")
        self.assertEqual(report["head_sha"], self.source.head)
        self.assertIn("pilot scope", " ".join(report["reasons"]))

    def test_checkpoint_excludes_git_credentials_configuration_and_untracked_data(self):
        workspace = GitWorkspace(self.session / "project")
        workspace.git("config", "credential.helper", "deliberately-sensitive-placeholder")
        checkpoint(self.session, self.root / "checkpoint")
        self.restore()
        restored = GitWorkspace(self.root / "resumed/project")
        self.assertNotIn(
            "deliberately-sensitive-placeholder", (restored.root / ".git/config").read_text()
        )
        workspace.write("untracked.txt", "not exported")
        with self.assertRaises(TeamError):
            checkpoint(self.session, self.root / "dirty-checkpoint")

    def test_checkpoint_corruption_wrong_run_and_wrong_controller_block(self):
        checkpoint(self.session, self.root / "checkpoint")
        for changes in ({"controller_sha": "0" * 40}, {"run_id": "foreign"}):
            with self.subTest(changes=changes), self.assertRaises(TeamError):
                self.restore(**changes)
        with (self.root / "checkpoint/checkout.bundle").open("ab") as stream:
            stream.write(b"corruption")
        with self.assertRaisesRegex(TeamError, "integrity"):
            self.restore()

    def test_checkpoint_missing_state_has_no_silent_fresh_start(self):
        checkpoint(self.session, self.root / "checkpoint")
        (self.root / "checkpoint/state.sqlite3").unlink()
        with self.assertRaises(TeamError):
            self.restore()

    def test_missing_local_journal_cannot_silently_resubmit(self):
        step_rehearsal(self.session)
        (self.session / "state.sqlite3").unlink()
        with self.assertRaisesRegex(TeamError, "journal is missing"):
            step_rehearsal(self.session)

    def test_empty_or_replaced_local_journal_cannot_silently_resubmit(self):
        step_rehearsal(self.session)
        path = self.session / "state.sqlite3"
        path.write_bytes(b"")
        with self.assertRaisesRegex(TeamError, "journal is missing"):
            step_rehearsal(self.session)
        RunStore(path)
        with self.assertRaisesRegex(TeamError, "disappeared"):
            step_rehearsal(self.session)

    def test_valid_checksum_does_not_authorize_empty_or_malformed_sqlite(self):
        for content in (b"", b"not sqlite"):
            saved = self.root / ("empty" if not content else "malformed")
            checkpoint(self.session, saved)
            (saved / "state.sqlite3").write_bytes(content)
            manifest = json.loads((saved / "manifest.json").read_text())
            manifest["files"]["state.sqlite3"] = hashlib.sha256(content).hexdigest()
            write_json(saved / "manifest.json", manifest)
            with self.subTest(content=content), self.assertRaisesRegex(TeamError, "SQLite"):
                self.restore(saved, self.root / (saved.name + "-restored"))

    def test_checkpoint_symlink_is_rejected(self):
        checkpoint(self.session, self.root / "checkpoint")
        path = self.root / "checkpoint/session.json"
        data = path.read_bytes()
        path.unlink()
        (self.root / "elsewhere").write_bytes(data)
        path.symlink_to(self.root / "elsewhere")
        with self.assertRaises(TeamError):
            self.restore()

    def test_extra_runs_in_valid_sqlite_checkpoint_are_rejected(self):
        with RunStore(self.session / "state.sqlite3").connect() as connection:
            connection.execute("INSERT INTO runs VALUES ('unrelated', '{}')")
        checkpoint(self.session, self.root / "checkpoint")
        with self.assertRaisesRegex(TeamError, "unrelated"):
            self.restore()

    def test_manifest_relabeling_cannot_enable_live_dispatch(self):
        checkpoint(self.session, self.root / "checkpoint")
        session_path = self.root / "checkpoint/session.json"
        session = json.loads(session_path.read_text())
        session["mode"] = "live"
        write_json(session_path, session)
        manifest_path = self.root / "checkpoint/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["session.json"] = hashlib.sha256(session_path.read_bytes()).hexdigest()
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(TeamError, "non-rehearsal"):
            self.restore()

    def test_unknown_or_missing_receipt_cannot_be_resubmitted_after_checkpoint(self):
        with patch.object(
            RehearsalCLI, "__call__", side_effect=IntegrationUnavailable("lost receipt")
        ):
            report = step_rehearsal(self.session)
        self.assertEqual(report["status"], "escalated")
        checkpoint(self.session, self.root / "checkpoint")
        self.restore()
        resumed = step_rehearsal(self.root / "resumed", ticks=24)
        self.assertEqual(len(resumed["tasks"]), 1)
        self.assertIsNone(resumed["tasks"][0]["task_id"])

    def test_cli_preparation_and_resume_summary_remain_explicitly_simulated(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["pilot-step", "--session", str(self.session)]), 0)
        self.assertFalse(json.loads(output.getvalue())["cloud_execution_verified"])


class ArtifactSourceTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.run = {
            "id": 123,
            "run_attempt": 1,
            "repository": {"full_name": PILOT_REPOSITORY},
            "head_sha": self.sha,
            "event": "workflow_dispatch",
            "path": ".github/workflows/cloud-pilot.yml",
            "status": "completed",
            "conclusion": "success",
        }
        self.artifact = {
            "id": 456,
            "expired": False,
            "name": "dt-003-checkpoint-123-1",
            "workflow_run": {"id": 123, "head_sha": self.sha},
        }

    def validate(self, run=None, artifact=None):
        validate_artifact_source(
            run or self.run, artifact or self.artifact, repository=PILOT_REPOSITORY, sha=self.sha
        )

    def test_exact_successful_manual_producer_and_artifact_are_accepted(self):
        self.validate()

    def test_untrusted_failed_or_stale_producer_is_rejected(self):
        for change in (
            {"repository": {"full_name": "foreign/project"}},
            {"head_sha": "b" * 40},
            {"event": "pull_request"},
            {"path": ".github/workflows/ci.yml"},
            {"status": "in_progress"},
            {"conclusion": "failure"},
            {"run_attempt": 2},
        ):
            with self.subTest(change=change), self.assertRaises(TeamError):
                self.validate(run=self.run | change)
        for change in (
            {"expired": True},
            {"name": "other"},
            {"workflow_run": {"id": 99, "head_sha": self.sha}},
            {"workflow_run": {"id": 123, "head_sha": "b" * 40}},
        ):
            with self.subTest(change=change), self.assertRaises(TeamError):
                self.validate(artifact=self.artifact | change)

    def test_source_lookup_is_read_only_and_rejects_ambiguous_ids_before_request(self):
        transport = Mock()
        transport.request.side_effect = [self.run, self.artifact]
        kwargs = dict(
            repository=PILOT_REPOSITORY, sha=self.sha, source_run="123", artifact_id="456"
        )
        check_artifact_source(transport, **kwargs)
        self.assertTrue(all(c.args[0] == "GET" for c in transport.request.call_args_list))
        transport.reset_mock()
        for changes in (
            {"source_run": "123;echo nope"},
            {"artifact_id": "latest"},
            {"repository": "foreign/project"},
        ):
            with self.subTest(changes=changes), self.assertRaises(TeamError):
                check_artifact_source(transport, **(kwargs | changes))
        transport.request.assert_not_called()


class CodexProbeTests(unittest.TestCase):
    def runner(self, argv):
        if argv == ["codex", "--version"]:
            return "codex-cli 0.163.0"
        if argv == ["codex", "login", "status"]:
            return "Logged in using an API key: sensitive-key-fragment"
        return "--env --branch --json TASK_ID"

    def test_login_output_is_never_included_in_probe_report(self):
        report = CodexCloudGateway(self.runner).probe()
        self.assertNotIn("sensitive-key-fragment", json.dumps(report))
        self.assertFalse(report["chatgpt_login_reported"])
        self.assertFalse(report["unattended_cloud_auth_verified"])
        self.assertIsNone(report["account_quota_remaining"])

    def test_missing_login_on_actions_does_not_hide_interface_probe(self):
        def missing_login(argv):
            if argv == ["codex", "login", "status"]:
                raise IntegrationUnavailable("No login")
            return self.runner(argv)

        report = CodexCloudGateway(missing_login).probe()
        self.assertTrue(report["submit_interface_present"])
        self.assertFalse(report["chatgpt_login_reported"])
        self.assertFalse(report["remote_task_verified"])
