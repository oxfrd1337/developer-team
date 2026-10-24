"""DT-017B synthetic-only runner tests. No OpenAI sockets or real credentials."""

import contextlib
import io
import json
import os
import socket
import ssl
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from developer_team.adapters.agents_api_contracts import AgentsAPIError
from developer_team.adapters.agents_https import FDSecretStore
from developer_team.adapters.provider_readonly_https import AdminReadOnlyHTTPS, CanaryReadOnlyHTTPS
from developer_team.provider_readonly_diagnostics import valid_diagnostics
from developer_team.provider_readonly_runner import ExternalFD, main, run_readonly
from tests.acceptance_support import SYNTHETIC_SECRET
from tests.provider_readonly_support import ADMIN_MARKER, Harness, admin_identity


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.files = []
        for name, marker in (("admin", ADMIN_MARKER), ("canary", SYNTHETIC_SECRET)):
            path = Path(self.tmp.name) / name
            path.write_text(marker)
            path.chmod(0o600)
            stream = path.open("rb")
            self.files.append(stream)
            self.addCleanup(stream.close)
        self.admin = admin_identity()
        self.kw = {
            "admin_fd": self.handle(0, self.admin),
            "canary_fd": self.handle(1, self.h.identity),
            "approved_models": frozenset({self.h.bound.model}),
            "now": lambda: self.h.clock,
        }
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.socket = self.enterContext(
            patch("socket.socket", side_effect=AssertionError("socket"))
        )
        self.enterContext(
            patch.object(
                AdminReadOnlyHTTPS,
                "_connection",
                staticmethod(lambda *a, **k: self.h.factory("admin")),
            )
        )
        self.enterContext(
            patch.object(
                CanaryReadOnlyHTTPS,
                "_connection",
                staticmethod(lambda *a, **k: self.h.factory("canary")),
            )
        )

    def handle(self, index, identity):
        fd = self.files[index].fileno()
        return ExternalFD(fd, identity, FDSecretStore._file_identity(os.fstat(fd)))

    def run_runner(self, execute=True, **changes):
        result = run_readonly(
            self.h.bound,
            self.h.identity,
            self.admin,
            execute_real_readonly=execute,
            **(self.kw | changes),
        )
        self.assert_halt(result)
        self.socket.assert_not_called()
        return result

    def assert_halt(self, report):
        self.assertTrue(valid_diagnostics(
            report["provider_diagnostics"], report["checks"], report["provider_observations"]
        ))
        self.assertEqual(report["real_submissions"], 0)
        self.assertEqual(report["LIVE"], "NO-GO")
        self.assertIs(report["live_authorized"], False)
        raw = json.dumps(report)
        for marker in (
            ADMIN_MARKER,
            SYNTHETIC_SECRET,
            "Bearer",
            "Authorization",
            "private-",
            "Traceback",
        ):
            self.assertNotIn(marker, raw)
        for gate in (
            "provider_contract_current",
            "environment_configuration",
            "secret_store",
            "real_transport",
            "durable_journal",
            "single_canary_grant",
            "fresh_create_approval",
            "fresh_submit_approval",
        ):
            self.assertEqual(report["checks"][gate], "MISSING_OR_INVALID")

    def test_plan_never_reads_fd_or_opens_connection(self):
        with patch("os.pread", side_effect=AssertionError("read")), patch("os.fstat") as fstat:
            self.assertEqual(self.run_runner(False)["outcome"], "NOT_EXECUTED")
        fstat.assert_not_called()
        self.assertEqual(self.h.connections, [])

    def test_explicit_consent_exactly_six_unique_gets_no_scope_inference(self):
        report = self.run_runner()
        self.assertEqual(report["outcome"], "COLLECTED")
        self.assertEqual(report["checks"]["credential_scope"], "MISSING_OR_INVALID")
        for check in ("account_project_binding", "spend_controls", "agent_configuration"):
            self.assertEqual(report["checks"][check], "PASS")
        root = self.h.root
        self.assertEqual(
            self.h.calls,
            [
                ("admin", "GET", root),
                ("admin", "GET", root + "/service_accounts"),
                ("admin", "GET", root + "/api_keys?owner_project_access=any"),
                ("admin", "GET", root + "/spend_limit"),
                ("canary", "GET", "/v1/models"),
                ("canary", "GET", f"/v1/agents/{self.h.bound.agent_id}"),
            ],
        )
        self.assertTrue(all(c.closed for c in self.h.connections))

    def test_non_boolean_consent_blocked(self):
        for consent in (1, "true", None):
            with self.subTest(consent=consent):
                self.assertEqual(self.run_runner(consent)["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_ci_and_secret_environment_never_execute(self):
        for name in (
            "CI",
            "GITHUB_ACTIONS",
            "DT_PROVIDER_OFFLINE",
            "OPENAI_API_KEY",
            "OPENAI_ADMIN_API_KEY",
            "OPENAI_ADMIN_KEY",
        ):
            with self.subTest(name=name), patch.dict(os.environ, {name: SYNTHETIC_SECRET}):
                self.assertEqual(self.run_runner()["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_missing_closed_negative_and_standard_fds(self):
        for fd in (None, -1, 0, 1, 2, 999999, True):
            with self.subTest(fd=fd):
                bad = replace(self.kw["admin_fd"], descriptor=fd)
                self.assertEqual(self.run_runner(admin_fd=bad)["outcome"], "BLOCKED")
        self.assertEqual(self.run_runner(canary_fd=None)["outcome"], "BLOCKED")
        self.files[1].close()
        self.assertEqual(self.run_runner()["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_swapped_descriptor_selectors_blocked_by_role_pins(self):
        self.assertEqual(
            self.run_runner(
                admin_fd=replace(self.kw["admin_fd"], descriptor=self.files[1].fileno()),
                canary_fd=replace(self.kw["canary_fd"], descriptor=self.files[0].fileno()),
            )["outcome"],
            "BLOCKED",
        )
        self.assertEqual(self.h.connections, [])

    def test_swapped_role_handles_blocked(self):
        self.assertEqual(
            self.run_runner(admin_fd=self.kw["canary_fd"], canary_fd=self.kw["admin_fd"])[
                "outcome"
            ],
            "BLOCKED",
        )
        self.assertEqual(self.h.connections, [])

    def test_same_underlying_file_blocked(self):
        same = replace(self.kw["admin_fd"], identity=self.h.identity)
        self.assertEqual(self.run_runner(canary_fd=same)["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_fd_replacement_after_pin_blocked(self):
        other = os.open(Path(self.tmp.name) / "canary", os.O_RDONLY)
        self.addCleanup(os.close, other)
        os.dup2(other, self.files[0].fileno())
        self.assertEqual(self.run_runner()["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_foreign_owner_and_insecure_mode_blocked(self):
        Path(self.tmp.name, "admin").chmod(0o644)
        self.assertEqual(self.run_runner()["outcome"], "BLOCKED")
        Path(self.tmp.name, "admin").chmod(0o600)
        self.kw["admin_fd"] = self.handle(0, self.admin)
        with patch("os.geteuid", return_value=os.geteuid() + 1):
            self.assertEqual(self.run_runner()["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_writable_fd_blocked(self):
        fd = os.open(Path(self.tmp.name) / "admin", os.O_RDWR)
        self.addCleanup(os.close, fd)
        self.assertEqual(
            self.run_runner(admin_fd=replace(self.kw["admin_fd"], descriptor=fd))["outcome"],
            "BLOCKED",
        )
        self.assertEqual(self.h.connections, [])

    def test_nonregular_fd_blocked(self):
        read, write = os.pipe()
        self.addCleanup(os.close, read)
        self.addCleanup(os.close, write)
        pin = FDSecretStore._file_identity(os.fstat(read))
        self.assertEqual(
            self.run_runner(admin_fd=ExternalFD(read, self.admin, pin))["outcome"], "BLOCKED"
        )
        self.assertEqual(self.h.connections, [])

    def test_invalid_identity_or_model_approval_blocked(self):
        self.admin = replace(self.admin, expires_at=self.h.clock)
        self.assertEqual(self.run_runner()["outcome"], "BLOCKED")
        self.admin = admin_identity()
        self.assertEqual(self.run_runner(approved_models=frozenset())["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_provider_errors_and_redirects_are_sanitized_without_retry(self):
        for status in (301, 302, 307, 308, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.h.status = status
                self.h.body = (ADMIN_MARKER + SYNTHETIC_SECRET).encode()
                self.h.calls.clear()
                report = self.run_runner()
                self.assertEqual(set(report["checks"].values()), {"MISSING_OR_INVALID"})
                self.assertEqual(len(self.h.calls), 3)
                self.assertEqual(len(set(self.h.calls)), 3)

    def test_dns_tls_timeout_errors_are_sanitized(self):
        for fault in (
            socket.gaierror(ADMIN_MARKER),
            ssl.SSLError(SYNTHETIC_SECRET),
            TimeoutError(ADMIN_MARKER),
            ConnectionError(SYNTHETIC_SECRET),
        ):
            with self.subTest(fault=type(fault)):
                self.h.fault = fault
                self.assertEqual(set(self.run_runner()["checks"].values()), {"MISSING_OR_INVALID"})
                self.assertEqual(self.h.calls, [])

    def test_raw_malformed_and_oversized_responses_never_escape(self):
        for body in (SYNTHETIC_SECRET.encode(), b"{" * 65537, b'{"object":NaN}'):
            with self.subTest(size=len(body)):
                self.h.body = body
                self.assertEqual(set(self.run_runner()["checks"].values()), {"MISSING_OR_INVALID"})

    def test_report_deterministic(self):
        self.assertEqual(self.run_runner(), self.run_runner())

    def test_independent_scope_adapter_can_prove_only_scope(self):
        report = self.run_runner(
            scope_source=self.h.scope_source,
            scope_verifier=self.h.scope_verifier,
            scope_attestor_identity=self.h.scope_source.identity,
            scope_verifier_identity=self.h.scope_verifier.identity,
        )
        self.assertEqual(report["checks"]["credential_scope"], "PASS")

    def test_scope_source_verifier_self_attestation_blocked(self):
        report = self.run_runner(
            scope_source=self.h.scope_source,
            scope_verifier=self.h.scope_source,
            scope_attestor_identity=self.h.scope_source.identity,
            scope_verifier_identity=self.h.scope_source.identity,
        )
        self.assertEqual(report["checks"]["credential_scope"], "MISSING_OR_INVALID")

    def manifest(self):
        return {
            "binding": asdict(self.h.bound),
            "canary_identity": asdict(self.h.identity),
            "admin_identity": asdict(self.admin),
            "admin_fd_pin": list(self.kw["admin_fd"].snapshot),
            "canary_fd_pin": list(self.kw["canary_fd"].snapshot),
            "approved_models": [self.h.bound.model],
        }

    def cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assert_halt(report)
        return report

    def test_cli_default_plan_no_stdin_secret_discovery(self):
        self.refresh_identities()
        path = Path(self.tmp.name) / "manifest.json"
        path.write_text(json.dumps(self.manifest()))
        with patch("sys.stdin", side_effect=AssertionError("stdin")):
            result = self.cli(["--manifest", str(path)])
        self.assertEqual(result["outcome"], "NOT_EXECUTED")
        self.assertEqual(self.h.connections, [])

    def refresh_identities(self):
        current = int(time.time())
        self.h.clock = current
        self.admin = replace(self.admin, issued_at=current, expires_at=current + 300)
        self.h.identity = replace(self.h.identity, issued_at=current, expires_at=current + 300)
        self.h.responses["/v1/models"]["data"][0]["created"] = current - 1
        self.kw["admin_fd"] = self.handle(0, self.admin)
        self.kw["canary_fd"] = self.handle(1, self.h.identity)

    def test_cli_explicit_switch_with_inherited_fds(self):
        self.refresh_identities()
        path = Path(self.tmp.name) / "manifest.json"
        path.write_text(json.dumps(self.manifest()))
        result = self.cli(
            [
                "--manifest",
                str(path),
                "--admin-fd",
                str(self.files[0].fileno()),
                "--canary-fd",
                str(self.files[1].fileno()),
                "--execute-real-readonly",
            ]
        )
        self.assertEqual(result["outcome"], "COLLECTED")
        self.assertEqual(result["checks"]["account_project_binding"], "PASS")
        self.assertEqual(len(self.h.calls), 6)

    def test_cli_no_switch_never_consumes_even_valid_fds(self):
        self.refresh_identities()
        path = Path(self.tmp.name) / "manifest.json"
        path.write_text(json.dumps(self.manifest()))
        with patch("os.pread", side_effect=AssertionError("read")):
            result = self.cli(
                [
                    "--manifest",
                    str(path),
                    "--admin-fd",
                    str(self.files[0].fileno()),
                    "--canary-fd",
                    str(self.files[1].fileno()),
                ]
            )
        self.assertEqual(result["outcome"], "NOT_EXECUTED")
        self.assertEqual(self.h.connections, [])

    def test_expiry_during_collection_invalidates_earlier_evidence(self):
        original = self.h.factory

        def factory(role):
            self.h.clock += 100
            return original(role)

        self.h.factory = factory
        result = self.run_runner()
        self.assertEqual(result["outcome"], "BLOCKED")
        self.assertEqual(set(result["checks"].values()), {"MISSING_OR_INVALID"})

    def test_cli_rejects_stdin_symlink_and_oversized_manifest(self):
        path = Path(self.tmp.name) / "manifest.json"
        path.symlink_to("/dev/stdin")
        self.assertEqual(self.cli(["--manifest", str(path)])["outcome"], "BLOCKED")
        path.unlink()
        path.write_text(" " * 8193)
        self.assertEqual(self.cli(["--manifest", str(path)])["outcome"], "BLOCKED")

    def test_cli_rejects_secret_arguments_without_echo(self):
        for option in ("--api-key", "--admin-secret", "--url", "--method", "--prompt", "--execute"):
            with self.subTest(option=option):
                self.assertEqual(self.cli([option, SYNTHETIC_SECRET])["outcome"], "BLOCKED")

    def test_cli_rejects_extra_secret_json_fields(self):
        path = Path(self.tmp.name) / "manifest.json"
        value = self.manifest() | {"secret": SYNTHETIC_SECRET}
        path.write_text(json.dumps(value))
        self.assertEqual(self.cli(["--manifest", str(path)])["outcome"], "BLOCKED")
        self.assertEqual(self.h.connections, [])

    def test_cli_duplicate_json_fields_blocked(self):
        path = Path(self.tmp.name) / "manifest.json"
        path.write_text('{"binding":{},"binding":{}}')
        self.assertEqual(self.cli(["--manifest", str(path)])["outcome"], "BLOCKED")

    def test_external_fd_repr_does_not_expose_identity(self):
        self.assertNotIn(self.admin.admin_ref, repr(self.kw["admin_fd"]))

    def test_wrong_handle_identity_raises_fixed_error(self):
        with self.assertRaisesRegex(AgentsAPIError, "^external_role_bound_readonly_fd_required$"):
            self.kw["admin_fd"].validate(self.h.identity)
