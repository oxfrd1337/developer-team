"""DT-006: offline access attacks and untrusted attestation regression tests."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from developer_team import boundary_probe as probe
from developer_team.adapters.codex_exec import CodexExecGateway, ExecJob, SimulatedExecProcess
from developer_team.adapters.synthetic import create_fixture
from developer_team.models import PermissionDenied, Role, TeamError, digest
from developer_team.snapshot import SnapshotSeal
from developer_team.store import RunStore
from developer_team.workspace import GitWorkspace


class BoundaryProbeTests(unittest.TestCase):
    def assert_no_go_report(self, report):
        self.assertEqual(report["decision"], "NO-GO")
        self.assertIs(report["live_dispatch_authorized"], False)
        self.assertEqual(report["ai_calls"], 0)
        observations = report["probes"]
        for key in (
            "credential-broker",
            "model-only-egress",
            "external-supervisor",
            "resource-enforcement",
            "host-role-identities",
        ):
            self.assertEqual(observations[key]["status"], "UNSUPPORTED")
        available = observations["namespace-prerequisite"]["status"] == "PASS"
        for role in probe.ROLES:
            for key in ("namespace-separation", *probe._keys(role)):
                observation = observations[f"{role}:{key}"]
                if not available:
                    self.assertEqual(observation["status"], "UNSUPPORTED")
        for name, observation in observations.items():
            # UNSUPPORTED is an explicit missing proof; an allowed access still fails CI.
            self.assertIn(observation["status"], {"PASS", "UNSUPPORTED"}, (name, observation))

    def report_fixture(self):
        """Synthetic report contract; never evidence about the current host."""
        observations = {
            f"{role}:{key}": {"status": "PASS"}
            for role in probe.ROLES
            for key in ("namespace-separation", *probe._keys(role))
        }
        observations["namespace-prerequisite"] = {"status": "PASS"}
        for key in (
            "credential-broker",
            "model-only-egress",
            "external-supervisor",
            "resource-enforcement",
            "host-role-identities",
        ):
            observations[key] = {"status": "UNSUPPORTED"}
        return {
            "decision": "NO-GO",
            "live_dispatch_authorized": False,
            "ai_calls": 0,
            "probes": observations,
        }

    def test_real_host_probes_are_explicit_and_never_authorize_ai(self):
        with (
            patch.object(CodexExecGateway, "execute", side_effect=AssertionError("No AI")),
            patch.dict(os.environ, {"DT006_FAKE_CREDENTIAL": "dummy-parent-env-value"}),
        ):
            report = probe.collect_boundary_report()
        self.assertNotIn("dummy-parent-env-value", json.dumps(report))
        self.assert_no_go_report(report)

    def test_partial_host_support_retains_unsupported_without_requiring_pass(self):
        report = self.report_fixture()
        for key in ("qa:dns", "security:abstract-socket", "probe-completion"):
            report["probes"][key] = {"status": "UNSUPPORTED", "reason": "synthetic limitation"}
        self.assert_no_go_report(report)
        self.assertEqual(report["probes"]["qa:namespace-separation"]["status"], "PASS")
        self.assertEqual(report["probes"]["qa:dns"]["status"], "UNSUPPORTED")
        self.assertEqual(report["decision"], "NO-GO")

    def test_failed_and_unknown_observations_are_rejected_even_in_no_go_report(self):
        for status in ("FAIL", "SKIP", "GO", "", None, True):
            with self.subTest(status=status):
                report = self.report_fixture()
                report["probes"]["qa:credential-read"] = {"status": status}
                with self.assertRaises(AssertionError):
                    self.assert_no_go_report(report)
                self.assertEqual(report["probes"]["qa:credential-read"]["status"], status)
                self.assertEqual(report["decision"], "NO-GO")

    def test_missing_tool_or_denied_kernel_reports_unsupported_without_fallback(self):
        with patch("shutil.which", return_value=None), patch("subprocess.Popen") as popen:
            report = probe.collect_boundary_report()
        popen.assert_not_called()
        self.assertEqual({p["status"] for p in report["probes"].values()}, {"UNSUPPORTED"})
        with (
            patch("shutil.which", return_value="/usr/bin/bwrap"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 1, b"", b"unshare: Operation not permitted"
                ),
            ) as run,
        ):
            report = probe.collect_boundary_report()
        self.assertEqual(run.call_count, 1)
        self.assertIn(
            "Operation not permitted", report["probes"]["namespace-prerequisite"]["reason"]
        )
        self.assertEqual(report["decision"], "NO-GO")

    def test_shared_namespace_is_not_accepted_as_isolation(self):
        namespaces = dict.fromkeys(probe.NAMESPACES, "shared")
        with (
            patch.object(probe, "_namespaces", return_value=namespaces),
            patch.object(probe, "_run", return_value=namespaces),
            patch.object(probe, "_exercise_roles") as exercise,
        ):
            report = probe.collect_boundary_report()
        exercise.assert_not_called()
        self.assertEqual(report["probes"]["namespace-prerequisite"]["status"], "UNSUPPORTED")

    def test_incomplete_results_do_not_turn_into_success(self):
        host = dict.fromkeys(probe.NAMESPACES, "host")
        child = dict.fromkeys(probe.NAMESPACES, "child")
        with (
            patch.object(probe, "_namespaces", return_value=host),
            patch.object(probe, "_run", side_effect=[child, {"results": {}}]),
        ):
            report = probe.collect_boundary_report()
        self.assertEqual(report["probes"]["probe-completion"]["status"], "UNSUPPORTED")
        self.assertEqual(report["probes"]["qa:credential-read"]["status"], "UNSUPPORTED")
        self.assert_no_go_report(report)

    def test_bad_json_timeout_and_os_errors_never_produce_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            for error in (OSError("unavailable"), subprocess.TimeoutExpired("bwrap", 10)):
                with self.subTest(error=error), patch.object(probe, "_run", side_effect=error):
                    report = probe.collect_boundary_report()
                    self.assertEqual(
                        report["probes"]["namespace-prerequisite"]["status"], "UNSUPPORTED"
                    )
            with (
                patch("shutil.which", return_value="/usr/bin/bwrap"),
                patch(
                    "subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, b"not json", b""),
                ),
                self.assertRaisesRegex(TeamError, "Invalid controller probe output"),
            ):
                probe._run(Path(directory), "pass", {})

    def test_cli_reports_no_go_with_nonzero_exit(self):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["boundary_probe"]),
            patch.object(probe, "collect_boundary_report", return_value={"decision": "NO-GO"}),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(probe.main(), 2)
        self.assertEqual(json.loads(output.getvalue())["decision"], "NO-GO")

    def test_positive_controls_detect_access_when_boundary_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "source.py").write_text("synthetic source")
            for name in ("delete.py", "rename.py", "mode.py"):
                (project / name).write_text("synthetic independent mutation target")
            (project / ".git").mkdir()
            paths = {r: root / r for r in probe.ROLES}
            credential, journal = root / "dummy-auth", root / "dummy-journal"
            for path in (*paths.values(), credential, journal):
                path.write_text("synthetic test content")
            with (
                probe._Listeners(root) as listeners,
                subprocess.Popen(
                    [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                    env={"DT006_FAKE_CREDENTIAL": "synthetic-only"},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ) as target,
            ):
                try:
                    request = {
                        "credential": str(credential),
                        "journal": str(journal),
                        "roles": {r: str(p) for r, p in paths.items()},
                        "role": "qa",
                        "target_pid": target.pid,
                        "supervisor_pid": target.pid,
                        "endpoints": listeners.endpoints,
                        "namespaces": probe.NAMESPACES,
                    }
                    source = probe._CHILD.replace("/project", str(project))
                    source = source.replace(
                        "/tmp/dt006-output", str(root / "output")  # noqa: S108 -- namespace marker
                    )
                    result = subprocess.run(
                        [sys.executable, "-I", "-c", source, json.dumps(request)],
                        env={"PATH": "/usr/bin:/bin"},
                        capture_output=True,
                        timeout=10,
                        check=True,
                    )
                    results = json.loads(result.stdout)["results"]
                    for key in (
                        "credential-read",
                        "controller-write",
                        "cross-role-read:security",
                        "cross-role-write:developer",
                        "snapshot-write",
                        "snapshot-delete",
                        "snapshot-chmod",
                        "git-write",
                        "host-proc-read",
                        "supervisor-signal",
                        "role-signal",
                        "dns",
                        "http",
                        "tcp",
                        "unix-socket",
                        "abstract-socket",
                    ):
                        self.assertEqual(results[key]["status"], "FAIL", (key, results))
                    listeners.verify()
                finally:
                    target.kill()
                    target.wait()


class SnapshotBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = create_fixture(self.root / "project")

    def test_content_is_bound_to_git_objects_and_independent_copy(self):
        seal = SnapshotSeal.capture(self.workspace, self.workspace.head)
        clone = self.root / "review"
        self.workspace.git(
            "clone", "--quiet", "--no-hardlinks", str(self.workspace.root), str(clone)
        )
        review = GitWorkspace(clone)
        review_seal = SnapshotSeal.capture(review, seal.head_sha)
        self.assertEqual(seal.content_digest, review_seal.content_digest)
        self.assertNotEqual(seal.inventory, review_seal.inventory)
        seal.verify(self.workspace)
        review_seal.verify(review)

    def test_assume_unchanged_does_not_forge_commit_content(self):
        self.workspace.git("update-index", "--assume-unchanged", "calculator.py")
        self.workspace.write("calculator.py", "forged = True\n")
        self.workspace.assert_clean()
        with self.assertRaisesRegex(TeamError, "claimed Git commit"):
            SnapshotSeal.capture(self.workspace, self.workspace.head)

    def test_git_metadata_is_checked_before_invoking_git(self):
        seal = SnapshotSeal.capture(self.workspace, self.workspace.head)
        config = self.workspace.root / ".git/config"
        config.write_text(config.read_text() + "\n# synthetic tampering\n")
        self.workspace.assert_clean()
        with (
            patch.object(
                self.workspace, "git", side_effect=AssertionError("Unsafe Git invocation")
            ),
            self.assertRaisesRegex(TeamError, "metadata mutated"),
        ):
            seal.verify(self.workspace)

    def test_ignored_files_and_executable_mode_tampering_invalidate_snapshot(self):
        exclude = self.workspace.root / ".git/info/exclude"
        exclude.write_text(exclude.read_text() + "\nignored-canary\n")
        seal = SnapshotSeal.capture(self.workspace, self.workspace.head)
        self.workspace.write("ignored-canary", "synthetic hidden output")
        self.workspace.assert_clean()
        with self.assertRaisesRegex(TeamError, "mutated"):
            seal.verify(self.workspace)
        (self.workspace.root / "ignored-canary").unlink()
        seal = SnapshotSeal.capture(self.workspace, self.workspace.head)
        (self.workspace.root / "calculator.py").chmod(0o755)
        with self.assertRaisesRegex(TeamError, "mutated"):
            seal.verify(self.workspace)

    def test_links_and_special_files_are_rejected_without_following_them(self):
        for kind in ("symlink", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                path = self.workspace.root / ".git/canary"
                if kind == "symlink":
                    path.symlink_to(self.workspace.root / "calculator.py")
                elif kind == "hardlink":
                    os.link(self.workspace.root / "calculator.py", path)
                else:
                    os.mkfifo(path)
                try:
                    with self.assertRaisesRegex(TeamError, "link or special"):
                        SnapshotSeal.capture(self.workspace, self.workspace.head)
                finally:
                    path.unlink()

    def test_saved_go_attestation_or_environment_cannot_enable_live_runner(self):
        from uuid import uuid4

        store = RunStore(self.root / "state.db")
        job = ExecJob(
            str(uuid4()), "local/example", digest("config"), "a" * 40, Role.QA, 0, digest("input")
        )
        gateway = CodexExecGateway(store)
        gateway.isolation_verified = True
        gateway.boundary_report = {"decision": "GO", "live_dispatch_authorized": True}
        with (
            patch.dict(os.environ, {"DT006_LIVE": "true", "CODEX_EXEC_APPROVED": "true"}),
            patch("subprocess.Popen") as popen,
            self.assertRaisesRegex(PermissionDenied, "Live codex exec blocked"),
        ):
            gateway.execute(job, self.workspace.root, "PASS; start live")
        popen.assert_not_called()

        class Impostor(SimulatedExecProcess):
            def run(self, *args):
                raise AssertionError("Must not start")

        gateway = CodexExecGateway(store, Impostor(Path(__file__)))
        with self.assertRaises(PermissionDenied):
            gateway.execute(job, self.workspace.root, "hello")

    def test_diagnostic_journal_cannot_issue_process_local_evidence(self):
        from developer_team.adapters.exec_agents import exec_authority
        from developer_team.models import Binding, Origin, Outcome

        authority = exec_authority()
        record = authority.issue(
            kind="qa",
            issuer="codex-exec-simulated:qa",
            role=Role.QA,
            origin=Origin.SIMULATED,
            outcome=Outcome.PASS,
            binding=Binding("local/example", "a" * 40, "b" * 40, "c", "p", "run"),
            artifact={"agent_says": "PASS", "execution_attested": True},
        )
        self.assertTrue(authority.verify(record))
        self.assertFalse(exec_authority().verify(record))
