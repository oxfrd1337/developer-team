"""DT-017E: entirely synthetic diagnostic and leakage regressions."""

import contextlib
import io
import json
import queue
import socket
import ssl
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from developer_team import provider_readonly_prepare as broker
from developer_team import provider_readonly_runner as runner
from developer_team.adapters.agents_api_contracts import AgentsAPIError
from developer_team.provider_readonly_diagnostics import (
    PROVIDER_GATES,
    empty_diagnostics,
    valid_diagnostics,
)
from tests import test_provider_readonly_runner as runner_fixtures
from tests.provider_readonly_support import ADMIN_MARKER, Connection


class DiagnosticTests(unittest.TestCase):
    setUp = runner_fixtures.RunnerTests.setUp
    handle = runner_fixtures.RunnerTests.handle
    assert_halt = runner_fixtures.RunnerTests.assert_halt

    def collect(self, **changes):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = runner_fixtures.RunnerTests.run_runner(self, **changes)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")
        self.assertTrue(valid_diagnostics(
            result["provider_diagnostics"], result["checks"], result["provider_observations"]
        ))
        self.assertEqual(broker._sanitize(json.dumps(result)), result)
        return result

    def operations(self):
        root = self.h.root
        return [
            ("account_project_binding", "ADMIN_PROJECT", root),
            ("account_project_binding", "ADMIN_SERVICE_ACCOUNTS", root + "/service_accounts"),
            (
                "account_project_binding", "ADMIN_API_KEYS",
                root + "/api_keys?owner_project_access=any",
            ),
            ("spend_controls", "ADMIN_SPEND_LIMIT", root + "/spend_limit"),
            ("agent_configuration", "CANARY_MODELS", "/v1/models"),
            ("agent_configuration", "CANARY_AGENT", f"/v1/agents/{self.h.bound.agent_id}"),
        ]

    def test_valid_provider_observations_remain_only_three_gates(self):
        result = self.collect()
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["provider_observations"], 3)
        self.assertEqual(result["provider_diagnostics"], {
            gate: {"code": "PASS", "stage": "COMPLETE"} for gate in PROVIDER_GATES
        })
        self.assertEqual(result["checks"]["credential_scope"], runner.MISSING)
        self.assertEqual(len(self.h.calls), 6)

    def test_http_matrix_identifies_each_exact_operation_without_retry(self):
        original = Connection.getresponse
        for gate, stage, path in self.operations():
            for status, code in (
                (401, "HTTP_401"), (403, "HTTP_403"), (429, "HTTP_429"),
                (500, "HTTP_5XX"), (599, "HTTP_5XX"),
                (301, "HTTP_REDIRECT"), (302, "HTTP_REDIRECT"), (307, "HTTP_REDIRECT"),
                (308, "HTTP_REDIRECT"), (404, "HTTP_OTHER"), (201, "HTTP_OTHER"),
            ):
                with self.subTest(stage=stage, status=status):
                    def respond(conn, path=path, status=status):
                        response = original(conn)
                        if conn.path == path:
                            response.status = status
                            if not 200 <= status < 300:
                                response.read1 = lambda _: self.fail("error body was read")
                        return response
                    self.h.calls.clear()
                    with patch.object(Connection, "getresponse", respond):
                        result = self.collect()
                    self.assertEqual(result["provider_diagnostics"][gate], {
                        "code": code, "stage": stage,
                    })
                    self.assertEqual(result["checks"][gate], runner.MISSING)
                    self.assertEqual(result["provider_observations"], 2)
                    self.assertEqual(sum(p == path for _, _, p in self.h.calls), 1)
                    self.assertEqual(len(self.h.calls), len(set(self.h.calls)))
                    self.assertTrue(set(self.h.calls) <= {
                        ("canary" if s.startswith("CANARY") else "admin", "GET", p)
                        for _, s, p in self.operations()
                    })

    def test_all_missing_is_explicit_collection_attempt_with_zero_observations(self):
        self.h.status = 403
        result = self.collect()
        self.assertEqual(result["outcome"], "COLLECTED")
        self.assertEqual(result["provider_observations"], 0)
        self.assertEqual(set(result["checks"].values()), {runner.MISSING})
        for gate, stage in (("account_project_binding", "ADMIN_PROJECT"),
                            ("spend_controls", "ADMIN_SPEND_LIMIT"),
                            ("agent_configuration", "CANARY_MODELS")):
            self.assertEqual(result["provider_diagnostics"][gate], {
                "code": "HTTP_403", "stage": stage,
            })
        self.assertEqual(len(self.h.calls), 3)

    def test_transport_and_size_failure_at_each_operation_keep_exact_stage(self):
        original = Connection.getresponse
        for gate, stage, path in self.operations():
            for error, code in (
                (ssl.SSLError(ADMIN_MARKER), "TLS_OR_PROXY_FAILURE"),
                (TimeoutError(ADMIN_MARKER), "TIMEOUT"),
                (AgentsAPIError("http_response_headers_too_large"), "RESPONSE_TOO_LARGE"),
            ):
                def fail_at_stage(conn, path=path, error=error):
                    if conn.path == path:
                        raise error
                    return original(conn)
                with self.subTest(stage=stage, code=code), patch.object(
                    Connection, "getresponse", fail_at_stage
                ):
                    result = self.collect()
                self.assertEqual(result["provider_diagnostics"][gate], {
                    "code": code, "stage": stage,
                })
                self.assertEqual(result["provider_observations"], 2)

    def test_schema_matrix_identifies_each_operation(self):
        for gate, stage, path in self.operations():
            original = self.h.responses[path]
            for value in (None, [], {}, {"unexpected": ADMIN_MARKER}):
                with self.subTest(stage=stage, shape=type(value)):
                    self.h.responses[path] = value
                    result = self.collect()
                    self.assertEqual(result["provider_diagnostics"][gate], {
                        "code": "SCHEMA_MISMATCH", "stage": stage,
                    })
            self.h.responses[path] = original

    def test_missing_records_configuration_drift_and_budget_are_distinct(self):
        cases = [
            ("account_project_binding", "ADMIN_SERVICE_ACCOUNTS", "EXPECTED_RECORD_MISSING",
             self.h.responses[self.h.root + "/service_accounts"], "data", []),
            ("account_project_binding", "ADMIN_API_KEYS", "EXPECTED_RECORD_MISSING",
             self.h.responses[self.h.root + "/api_keys?owner_project_access=any"], "data", []),
            ("agent_configuration", "CANARY_MODELS", "EXPECTED_RECORD_MISSING",
             self.h.responses["/v1/models"], "data", []),
            ("agent_configuration", "CANARY_AGENT", "CONFIGURATION_MISMATCH",
             self.h.agent, "model", "synthetic_drift"),
            ("spend_controls", "ADMIN_SPEND_LIMIT", "CONFIGURATION_MISMATCH",
             self.h.spend, "threshold_amount", 101),
        ]
        for gate, stage, code, value, key, changed in cases:
            with self.subTest(stage=stage):
                previous = value[key]
                value[key] = changed
                self.assertEqual(self.collect()["provider_diagnostics"][gate], {
                    "code": code, "stage": stage,
                })
                value[key] = previous

    def test_transport_type_classification_never_uses_error_text(self):
        for error, code in (
            (socket.gaierror(ADMIN_MARKER), "DNS_FAILURE"),
            (ssl.SSLError(ADMIN_MARKER), "TLS_OR_PROXY_FAILURE"),
            (AgentsAPIError("unsupported_proxy_configuration"), "TLS_OR_PROXY_FAILURE"),
            (TimeoutError(ADMIN_MARKER), "TIMEOUT"),
            (ConnectionError(ADMIN_MARKER), "TRANSPORT_FAILURE"),
            (RuntimeError(ADMIN_MARKER), "TRANSPORT_FAILURE"),
        ):
            with self.subTest(error=type(error)):
                self.h.fault = error
                result = self.collect()
                self.assertEqual(result["provider_observations"], 0)
                self.assertEqual(
                    {v["code"] for v in result["provider_diagnostics"].values()}, {code}
                )
                self.assertEqual(self.h.calls, [])

    def test_caller_connect_and_read_deadlines_are_timeouts(self):
        for connected in (False, True):
            with (
                self.subTest(connected=connected),
                patch("threading.Thread.start"),
                patch("threading.Event.wait", return_value=connected),
                patch("queue.Queue.get", side_effect=queue.Empty),
            ):
                result = self.collect()
                self.assertEqual({v["code"] for v in result["provider_diagnostics"].values()},
                                 {"TIMEOUT"})
                self.assertEqual(self.h.calls, [])

    def test_bounded_header_failure_and_arbitrary_exception_arguments_are_safe(self):
        for error, code in (
            (AgentsAPIError("http_response_headers_too_large"), "RESPONSE_TOO_LARGE"),
            (AgentsAPIError([ADMIN_MARKER]), "TRANSPORT_FAILURE"),
        ):
            with self.subTest(code=code):
                self.h.fault = error
                result = self.collect()
                self.assertEqual({v["code"] for v in result["provider_diagnostics"].values()},
                                 {code})
                with self.assertRaises(AgentsAPIError) as caught:
                    self.h.admin._transport.read(self.h.root)
                self.assertIsNone(caught.exception.__context__)
                self.assertIsNone(caught.exception.__cause__)
                self.assertEqual(str(caught.exception), code)

    def test_oversized_malformed_duplicate_and_nonfinite_bodies_are_fixed_codes(self):
        for body, code in (
            (b"x" * 65537, "RESPONSE_TOO_LARGE"),
            (ADMIN_MARKER.encode(), "SCHEMA_MISMATCH"),
            (b'{"id":1,"id":2}', "SCHEMA_MISMATCH"),
            (b'{"value":NaN}', "SCHEMA_MISMATCH"),
        ):
            with self.subTest(code=code, size=len(body)):
                self.h.body = body
                result = self.collect()
                self.assertEqual(
                    {v["code"] for v in result["provider_diagnostics"].values()}, {code}
                )
                self.assertEqual(result["provider_observations"], 0)

    def test_fd_role_swap_has_no_provider_diagnostic_or_connection(self):
        result = self.collect(admin_fd=self.kw["canary_fd"], canary_fd=self.kw["admin_fd"])
        self.assertEqual(result["outcome"], "BLOCKED")
        self.assertEqual(result["provider_diagnostics"], empty_diagnostics())
        self.assertEqual(self.h.connections, [])

    def test_expiry_discards_diagnostics_along_with_observations(self):
        factory = self.h.factory
        def expire(role):
            self.h.clock += 100
            return factory(role)
        self.h.factory = expire
        result = self.collect()
        self.assertEqual(result["outcome"], "BLOCKED")
        self.assertEqual(result["provider_diagnostics"], empty_diagnostics())
        self.assertEqual(result["provider_observations"], 0)

    def test_unaccepted_observation_is_never_diagnostic_pass(self):
        with patch("developer_team.agents_acceptance._facts_match", return_value=False):
            result = self.collect()
        self.assertEqual(result["provider_observations"], 0)
        self.assertEqual(result["provider_diagnostics"], {
            gate: {"code": "OBSERVATION_REJECTED", "stage": "COMPLETE"} for gate in PROVIDER_GATES
        })

    def test_precondition_failure_has_no_invented_http_cause(self):
        self.h.admin._identity = replace(self.h.identity, expires_at=self.h.clock)
        result = self.h.collector.report()
        self.assertEqual(result["provider_diagnostics"]["account_project_binding"], {
            "code": "LOCAL_VALIDATION_FAILED", "stage": "PRECHECK",
        })
        self.assertEqual(result["checks"]["account_project_binding"], runner.MISSING)

    def test_broker_rejects_unknown_dynamic_nested_and_inconsistent_fields(self):
        report = self.collect()
        for mutation in (
            {"schema_version": 1}, {"schema_version": True},
            {"provider_observations": True}, {"provider_observations": 0},
            {"provider_observations": 4}, {"provider_observations": ADMIN_MARKER},
            {"provider_diagnostics": {}}, {"provider_diagnostics": []},
            {"provider_diagnostics": report["provider_diagnostics"] | {"extra": ADMIN_MARKER}},
            {"outcome": "BLOCKED"},
        ):
            with self.subTest(field=next(iter(mutation))):
                with self.assertRaises(AgentsAPIError):
                    broker._sanitize(json.dumps(report | mutation))
        for field, value in (("code", ADMIN_MARKER), ("stage", ADMIN_MARKER),
                             ("code", []), ("stage", {}), ("extra", ADMIN_MARKER),
                             ("stage", "ADMIN_PROJECT"), ("code", "HTTP_401")):
            bad = json.loads(json.dumps(report))
            bad["provider_diagnostics"]["agent_configuration"][field] = value
            with self.subTest(field=field, shape=type(value)):
                with self.assertRaises(AgentsAPIError):
                    broker._sanitize(json.dumps(bad))

    def test_production_runner_hash_is_not_renewed_and_blocks_before_release(self):
        self.assertEqual(broker.RUNNER_SHA256,
                         "41136330bdc37d0695d2ad262cd13e1ba7b0e88874949daf862847673d8dbd6e")
        with patch.object(broker, "verify_release") as verify, patch("os.pread") as read:
            with self.assertRaisesRegex(AgentsAPIError, "^runner_changed$"):
                broker._check_checkout()
        verify.assert_not_called()
        read.assert_not_called()
        self.assertNotIn("RUNNER_SHA256 =", Path(runner.__file__).read_text())
