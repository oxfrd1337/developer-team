"""DT-017C contracts with disposable synthetic files; never provider access."""

import contextlib
import hashlib
import io
import json
import os
import pty
import select
import socket
import subprocess
import tempfile
import time
import unittest
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from unittest.mock import Mock, patch

from developer_team import provider_readonly_prepare as broker
from developer_team import provider_readonly_runner as runner
from developer_team.adapters.agents_api_contracts import AgentsAPIError
from developer_team.adapters.agents_credentials import CredentialIdentity
from developer_team.adapters.provider_readonly_https import (
    AdminCredentialIdentity,
    AdminReadOnlyHTTPS,
    CanaryReadOnlyHTTPS,
)
from tests.acceptance_support import SYNTHETIC_SECRET
from tests.agents_api_support import NOW, binding
from tests.provider_readonly_support import ADMIN_MARKER, Harness

ADMIN = ADMIN_MARKER
CANARY = SYNTHETIC_SECRET


class PrepareTests(unittest.TestCase):
    def setUp(self):
        # Synthetic fixture approval only. Production RUNNER_SHA256 stays unchanged;
        # the revised runner is deliberately blocked pending independent review.
        fixture_digest = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()
        self.enterContext(patch.object(broker, "RUNNER_SHA256", fixture_digest))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.paths = [self.root / "private-admin", self.root / "private-canary"]
        self.fds = []
        for path, value in zip(self.paths, (ADMIN, CANARY), strict=True):
            path.write_text(value)
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY)
            self.fds.append(fd)
            self.addCleanup(os.close, fd)
        self.values = asdict(binding())
        del self.values["provider_base"]
        self.values.update(
            admin_ref="admin_synthetic",
            credential_ref="key_synthetic",
            service_account_ref="sa_synthetic",
        )
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.socket = self.enterContext(patch.object(socket, "socket", side_effect=AssertionError))
        # Business-flow fixtures have no production release approval. Integrity
        # itself is exercised with real disposable Git repositories separately.
        self.enterContext(patch.object(broker, "verify_release", return_value={}))
        self.enterContext(
            patch.object(
                broker,
                "verified_snapshot",
                side_effect=lambda root: contextlib.nullcontext(root),
            )
        )

    def args(self, **changes):
        result = []
        for name, value in (self.values | changes).items():
            if value is not None:
                result.extend(("--" + name.replace("_", "-"), str(value)))
        return result

    def execute_args(self, **changes):
        return self.args(**changes) + [
            "--execute-real-readonly",
            "--admin-fd",
            str(self.fds[0]),
            "--canary-fd",
            str(self.fds[1]),
        ]

    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(broker.main(args), 2)
        self.assertEqual(err.getvalue(), "")
        raw = out.getvalue()
        for marker in (ADMIN, CANARY, str(self.root), "Traceback", "Authorization"):
            self.assertNotIn(marker, raw)
        result = json.loads(raw)
        self.assertEqual(result["real_submissions"], 0)
        self.assertEqual(result["LIVE"], "NO-GO")
        self.assertIs(result["live_authorized"], False)
        self.socket.assert_not_called()
        return result

    def test_default_opens_no_fds_reads_no_stdin_and_only_lists_missing(self):
        with (
            patch("builtins.open", side_effect=AssertionError),
            patch("os.open", side_effect=AssertionError),
            patch("os.pread", side_effect=AssertionError),
            patch("os.fstat", side_effect=AssertionError),
            patch("sys.stdin", Mock(read=Mock(side_effect=AssertionError))),
        ):
            result = self.cli([])
        self.assertEqual(result["missing_bindings"], list(broker.FIELDS))
        self.assertEqual(result["outcome"], "NOT_EXECUTED")

    def test_complete_plan_opens_nothing_and_does_not_inspect_supplied_fds(self):
        args = self.args() + ["--admin-fd", "999999", "--canary-fd", "999998"]
        with (
            patch("os.open", side_effect=AssertionError),
            patch("os.fstat", side_effect=AssertionError),
            patch.object(broker, "_check_checkout", side_effect=AssertionError),
        ):
            self.assertEqual(self.cli(args)["missing_bindings"], [])

    def test_argv_secret_paths_values_and_mutation_options_block_without_echo(self):
        for option in (
            "--api-key",
            "--admin-secret",
            "--canary-secret",
            "--admin-path",
            "--canary-path",
            "--manifest",
            "--url",
            "--method",
            "--live",
            "--execute",
        ):
            with self.subTest(option=option):
                self.assertEqual(self.cli([option, ADMIN])["outcome"], "BLOCKED")
        self.assertEqual(self.cli([str(self.paths[0])])["outcome"], "BLOCKED")

    def test_offline_ci_and_secret_environment_block_before_file_access(self):
        for name in (
            "CI",
            "GITHUB_ACTIONS",
            "DT_PROVIDER_OFFLINE",
            "OPENAI_API_KEY",
            "OPENAI_ADMIN_KEY",
            "DT_ADMIN_SECRET_PATH",
            "CANARY_CREDENTIAL",
            "ADMIN_TOKEN",
        ):
            with (
                self.subTest(name=name),
                patch.dict(os.environ, {name: ADMIN}),
                patch("os.dup", side_effect=AssertionError),
                patch.object(broker, "_check_checkout", side_effect=AssertionError),
            ):
                result = self.cli(self.execute_args())
                self.assertEqual(result["reason"], "offline_or_secret_environment")

    def test_piped_stdin_never_used_and_missing_agent_is_structured(self):
        with (
            patch("builtins.open", side_effect=OSError(ADMIN)),
            patch("sys.stdin", Mock(read=Mock(side_effect=AssertionError))),
            patch.object(broker, "_execute") as execute,
        ):
            result = self.cli(self.execute_args(agent_id=None))
        self.assertEqual(result["reason"], "agent_id_missing")
        execute.assert_not_called()

    def test_invalid_binding_fields_block_before_opening_secret_handles(self):
        for changes in (
            {"project_id": "../project"},
            {"agent_id": "sk-secret"},
            {"service_account_ref": "bad/ref"},
            {"credential_ref": "Bearer"},
            {"admin_ref": "key_synthetic"},
            {"model": "https://example.com"},
            {"intent_id": "bad/ref"},
            {"idempotency_key": "bad/ref"},
            {"plan_digest": "b" * 63},
            {"budget_cents": 0},
            {"budget_cents": 101},
        ):
            with self.subTest(changes=changes), patch.object(broker, "_execute") as execute:
                self.assertEqual(
                    self.cli(self.execute_args(**changes))["reason"], "invalid_binding"
                )
                execute.assert_not_called()

    def test_private_regular_files_open_readonly_without_reading_bytes(self):
        with patch("os.pread", side_effect=AssertionError):
            with broker._open_private(str(self.paths[0])) as (fd, pin):
                self.assertEqual(broker._checked_fd(fd), pin)
                self.assertEqual(pin, broker._checked_fd(self.fds[0]))
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_group_world_executable_and_other_modes_rejected(self):
        for mode in (0o644, 0o640, 0o604, 0o660, 0o6000, 0o400, 0o700):
            with self.subTest(mode=mode):
                self.paths[0].chmod(mode)
                with self.assertRaises((OSError, AgentsAPIError)):
                    with broker._open_private(str(self.paths[0])):
                        self.fail("accepted")

    def test_foreign_owner_rejected(self):
        with patch("os.geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(AgentsAPIError):
                broker._checked_fd(self.fds[0])

    def test_zero_and_oversized_files_rejected(self):
        for size in (0, 513):
            self.paths[0].write_bytes(b"x" * size)
            with self.assertRaises(AgentsAPIError):
                with broker._open_private(str(self.paths[0])):
                    self.fail("accepted")

    def test_boundary_file_sizes_accepted(self):
        for size in (1, 512):
            self.paths[0].write_bytes(b"x" * size)
            with broker._open_private(str(self.paths[0])) as (_, pin):
                self.assertEqual(pin[2], size)

    def test_symlink_fifo_device_directory_rejected_without_blocking(self):
        link = self.root / "symlink"
        link.symlink_to(self.paths[0])
        fifo = self.root / "fifo"
        os.mkfifo(fifo, 0o600)
        for path in (link, fifo, Path("/dev/null"), self.root):
            with self.subTest(kind=path.name), self.assertRaises((OSError, AgentsAPIError)):
                with broker._open_private(str(path)):
                    self.fail("accepted")

    def test_parent_symlinks_and_relative_paths_rejected(self):
        link = self.root / "directory-link"
        link.symlink_to(self.root, target_is_directory=True)
        for path in (link / self.paths[0].name, Path("relative")):
            with self.assertRaises((OSError, AgentsAPIError)):
                with broker._open_private(str(path)):
                    self.fail("accepted")

    def test_writable_standard_closed_and_pipe_fds_rejected(self):
        writable = os.open(self.paths[0], os.O_RDWR)
        self.addCleanup(os.close, writable)
        read, write = os.pipe()
        self.addCleanup(os.close, read)
        self.addCleanup(os.close, write)
        for fd in (writable, read, 0, 1, 2, -1, 999999, True):
            with self.subTest(fd=fd), self.assertRaises((OSError, AgentsAPIError)):
                broker._checked_fd(fd)

    def test_same_file_and_hardlink_rejected(self):
        hardlink = self.root / "hardlink"
        os.link(self.paths[0], hardlink)
        fd = os.open(hardlink, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        for canary in (self.fds[0], fd):
            with (
                patch.object(broker, "_check_checkout", return_value=self.root),
                patch.object(broker, "_invoke") as invoke,
            ):
                with self.assertRaises(AgentsAPIError):
                    broker._execute(self.values, binding(), self.fds[0], canary, None)
                invoke.assert_not_called()

    def test_manifest_pins_deterministic_role_bound_and_identity_immutable(self):
        pins = [broker._checked_fd(fd) for fd in self.fds]
        value = broker._manifest(self.values, binding(), *pins, now=NOW)
        self.assertEqual(value, broker._manifest(self.values, binding(), *pins, now=NOW))
        for role, cls in (("admin", AdminCredentialIdentity), ("canary", CredentialIdentity)):
            identity = cls(**value[role + "_identity"])
            identity.validate(binding(), NOW)
            self.assertEqual(identity.expires_at - identity.issued_at, 300)
            with self.assertRaises(FrozenInstanceError):
                identity.expires_at += 1
            index = 0 if role == "admin" else 1
            runner.ExternalFD(self.fds[index], identity, pins[index]).validate(identity)
            with self.assertRaises(AgentsAPIError):
                runner.ExternalFD(self.fds[1 - index], identity, pins[index]).validate(identity)
        raw = json.dumps(value)
        for marker in (ADMIN, CANARY, str(self.root)):
            self.assertNotIn(marker, raw)

    def test_manifest_and_duplicate_fds_removed_after_success_failure_and_interrupt(self):
        for fault in (None, OSError(ADMIN), KeyboardInterrupt()):
            seen = []

            def invoke(root, manifest, admin_fd, canary_fd, *, seen=seen, fault=fault):
                seen.append((manifest, admin_fd, canary_fd))
                value, bound, identity, admin = runner._manifest(manifest)
                runner.ExternalFD(admin_fd, admin, tuple(value["admin_fd_pin"])).validate(admin)
                runner.ExternalFD(canary_fd, identity, tuple(value["canary_fd_pin"])).validate(
                    identity
                )
                self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
                self.assertEqual(manifest.parent.stat().st_mode & 0o777, 0o700)
                if fault is not None:
                    raise fault
                return runner._report("READ_ONLY", "COLLECTED")

            with patch.object(broker, "_invoke", side_effect=invoke):
                result = self.cli(self.execute_args())
            self.assertEqual(result["outcome"], "COLLECTED" if fault is None else "BLOCKED")
            self.assertEqual(len(seen), 1)
            manifest, *duplicates = seen[0]
            self.assertFalse(manifest.exists())
            self.assertFalse(manifest.parent.exists())
            for fd in duplicates:
                with self.assertRaises(OSError):
                    os.fstat(fd)
            for fd in self.fds:
                broker._checked_fd(fd)

    def test_runner_report_is_strictly_sanitized(self):
        report = runner._report("READ_ONLY", "COLLECTED")
        self.assertEqual(broker._sanitize(json.dumps(report)), report)
        for value in (
            report | {"extra": ADMIN},
            report | {"outcome": CANARY},
            report | {"live_authorized": True},
            report | {"real_submissions": 1},
            report | {"checks": dict.fromkeys(runner.GATES, ADMIN)},
        ):
            with self.assertRaises(AgentsAPIError):
                broker._sanitize(json.dumps(value))

    def test_subprocess_inherits_only_selected_fds_and_no_stdin(self):
        result = subprocess.CompletedProcess(
            [], 2, json.dumps(runner._report("READ_ONLY", "BLOCKED")).encode()
        )
        with patch.object(subprocess, "run", return_value=result) as run:
            broker._invoke(self.root, self.root / "manifest.json", *self.fds)
        args, kw = run.call_args
        self.assertEqual(kw["pass_fds"], tuple(self.fds))
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["stderr"], subprocess.DEVNULL)
        self.assertNotIn("env", kw)
        self.assertIn("--execute-real-readonly", args[0])
        for flag in ("-I", "-S", "-B"):
            self.assertIn(flag, args[0])
        for marker in (ADMIN, CANARY):
            self.assertNotIn(marker, repr(run.call_args))

    def test_modified_runner_or_missing_release_blocks(self):
        with patch.object(broker, "RUNNER_SHA256", "0" * 64):
            with self.assertRaises(AgentsAPIError):
                broker._check_checkout()
        with patch.object(
            broker, "verify_release", side_effect=AgentsAPIError("release_integrity_required")
        ):
            with self.assertRaises(AgentsAPIError):
                broker._check_checkout()

    def test_synthetic_child_process_remains_offline(self):
        # Real fork/exec + FD inheritance; child is forced offline, no provider probe.
        with patch.dict(os.environ, {"DT_PROVIDER_OFFLINE": "1"}):
            with patch.object(broker, "_invoke", wraps=broker._invoke):
                result = broker._execute(self.values, binding(), *self.fds, None)
        self.assertEqual(result, runner._report("READ_ONLY", "BLOCKED"))

    def test_broker_manifest_drives_runner_only_six_synthetic_gets(self):
        harness = Harness()

        def invoke(root, manifest, admin_fd, canary_fd):
            value, bound, identity, admin = runner._manifest(manifest)
            return runner.run_readonly(
                bound,
                identity,
                admin,
                admin_fd=runner.ExternalFD(admin_fd, admin, tuple(value["admin_fd_pin"])),
                canary_fd=runner.ExternalFD(canary_fd, identity, tuple(value["canary_fd_pin"])),
                approved_models=frozenset(value["approved_models"]),
                execute_real_readonly=True,
                now=lambda: NOW,
            )

        with (
            patch.object(broker, "_invoke", side_effect=invoke),
            patch("developer_team.provider_readonly_prepare.time.time", return_value=NOW),
            patch.object(
                AdminReadOnlyHTTPS,
                "_connection",
                staticmethod(lambda *a, **k: harness.factory("admin")),
            ),
            patch.object(
                CanaryReadOnlyHTTPS,
                "_connection",
                staticmethod(lambda *a, **k: harness.factory("canary")),
            ),
        ):
            result = self.cli(self.execute_args())
            self.assertEqual(result["checks"]["agent_configuration"], "PASS")
            self.assertEqual(len(harness.calls), 6)
            self.assertTrue(all(method == "GET" for _, method, _ in harness.calls))
            harness.responses.pop("/v1/agents/agent_synthetic")
            result = self.cli(self.execute_args())
            self.assertEqual(result["checks"]["agent_configuration"], runner.MISSING)
            self.assertEqual(len(harness.calls), 12)
            self.assertTrue(all(method == "GET" for _, method, _ in harness.calls))

    def test_real_local_tty_dialog_reads_no_stdin_and_does_not_echo_selection(self):
        # A controlling PTY exercises the actual /dev/tty and termios code.
        pid, master = pty.fork()
        if pid == 0:
            try:
                with open("/dev/tty", "rb+", buffering=0) as raw:
                    with io.TextIOWrapper(raw, encoding="utf-8", write_through=True) as tty:
                        selected = broker._read_path(tty, "Admin", "admin_synthetic")
                        os._exit(0 if selected == str(self.paths[0]) else 1)
            except BaseException:
                os._exit(2)
        output = b""
        try:
            deadline = time.monotonic() + 5
            sent = False
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 8192)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                if b"Datei: " in output and not sent:
                    # Wait for echo to actually be disabled before sending.
                    import termios

                    if not termios.tcgetattr(master)[3] & termios.ECHO:
                        os.write(master, (str(self.paths[0]) + "\n").encode())
                        sent = True
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited == 0:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                self.fail("local tty timed out")
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            self.assertNotIn(str(self.paths[0]).encode(), output)
        finally:
            os.close(master)


if __name__ == "__main__":
    unittest.main()
