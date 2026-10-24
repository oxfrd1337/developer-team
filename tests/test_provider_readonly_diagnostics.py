"""DT-017E diagnostics: synthetic wire only, with socket access denied."""

import contextlib
import http.client
import io
import json
import socket
import ssl
import traceback
import unittest
from copy import deepcopy
from unittest.mock import patch

from developer_team import provider_readonly_prepare as broker
from developer_team import provider_readonly_runner as runner
from developer_team.adapters.agents_api_contracts import AgentsAPIError
from developer_team.provider_readonly_diagnostics import (
    CODES,
    PROVIDER_GATES,
    STAGES,
    empty_diagnostics,
    sanitize_diagnostics,
)
from tests.acceptance_support import SYNTHETIC_SECRET
from tests.provider_readonly_support import ADMIN_MARKER, Connection, Harness


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.socket = self.enterContext(patch.object(socket, "socket", side_effect=AssertionError))
        self.h = Harness()
        # No external scope attestation is available in the official runner.
        self.h.collector._scope_source = None
        self.out, self.err = io.StringIO(), io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))
        self.enterContext(contextlib.redirect_stderr(self.err))

    def tearDown(self):
        self.socket.assert_not_called()
        self.assertEqual(self.out.getvalue(), "")
        self.assertEqual(self.err.getvalue(), "")

    def operations(self):
        h = self.h
        return (
            ("account_project_binding", "ADMIN_PROJECT", h.root),
            ("account_project_binding", "ADMIN_SERVICE_ACCOUNTS", h.root + "/service_accounts"),
            (
                "account_project_binding",
                "ADMIN_API_KEYS",
                h.root + "/api_keys?owner_project_access=any",
            ),
            ("spend_controls", "ADMIN_SPEND_LIMIT", h.root + "/spend_limit"),
            ("agent_configuration", "CANARY_MODELS", "/v1/models"),
            ("agent_configuration", "CANARY_AGENT", f"/v1/agents/{h.bound.agent_id}"),
        )

    def report(self):
        result = self.h.collector.report()
        diagnostics = result["provider_diagnostics"]
        self.assertEqual(sanitize_diagnostics(diagnostics), diagnostics)
        self.assertEqual(result["checks"]["credential_scope"], runner.MISSING)
        self.assertEqual(result["real_submissions"], 0)
        self.assertEqual(result["live"], "NO-GO")
        self.assertIs(result["live_authorized"], False)
        raw = json.dumps(result)
        for marker in (
            SYNTHETIC_SECRET,
            ADMIN_MARKER,
            "private-",
            "Bearer",
            "Traceback",
            self.h.bound.project_id,
            self.h.bound.agent_id,
        ):
            self.assertNotIn(marker, raw)
        self.assertTrue(all(method == "GET" for _, method, _ in self.h.calls))
        self.assertEqual(len(self.h.calls), len(set(self.h.calls)))
        self.assertLessEqual(len(self.h.calls), 6)
        return result

    def test_valid_reports_only_three_provider_passes_and_no_scope(self):
        report = self.report()
        self.assertEqual(len(self.h.calls), 6)
        for gate in PROVIDER_GATES:
            self.assertEqual(
                report["provider_diagnostics"][gate], {"stage": "FINAL_VALIDATION", "code": "PASS"}
            )
            self.assertEqual(report["checks"][gate], "PASS")

    def test_each_operation_http_status_and_redirect_without_error_body_read(self):
        original = Connection.getresponse
        for index in range(6):
            for status, code in (
                (401, "HTTP_401"),
                (403, "HTTP_403"),
                (429, "HTTP_429"),
                (500, "HTTP_5XX"),
                (599, "HTTP_5XX"),
                (302, "REDIRECT_BLOCKED"),
                (404, "HTTP_OTHER"),
                (204, "HTTP_OTHER"),
            ):
                self.h = Harness()
                self.h.collector._scope_source = None
                gate, stage, path = self.operations()[index]

                def response(conn, path=path, status=status):
                    if conn.path == path:

                        class ErrorResponse:
                            def read1(self, size):
                                raise AssertionError("error body must never be read")

                        raw = ErrorResponse()
                        raw.status = status
                        return raw
                    return original(conn)

                with (
                    self.subTest(stage=stage, status=status),
                    patch.object(Connection, "getresponse", response),
                ):
                    report = self.report()
                    self.assertEqual(
                        report["provider_diagnostics"][gate], {"stage": stage, "code": code}
                    )
                    self.assertEqual(report["checks"][gate], runner.MISSING)

    def test_each_operation_invalid_json_duplicate_keys_nonfinite_and_oversize(self):
        original = Connection.getresponse
        for index in range(6):
            for body, code in (
                (b"[]", "SCHEMA_MISMATCH"),
                (b'{"a":1,"a":2}', "SCHEMA_MISMATCH"),
                (b'{"x":NaN}', "SCHEMA_MISMATCH"),
                (b"\xff", "SCHEMA_MISMATCH"),
                (SYNTHETIC_SECRET.encode(), "SCHEMA_MISMATCH"),
                (b"x" * 65537, "RESPONSE_TOO_LARGE"),
            ):
                self.h = Harness()
                self.h.collector._scope_source = None
                gate, stage, path = self.operations()[index]

                def response(conn, path=path, body=body):
                    if conn.path == path:
                        raw = io.BytesIO(body)
                        raw.status, raw.read1 = 200, raw.read
                        return raw
                    return original(conn)

                with (
                    self.subTest(stage=stage, code=code),
                    patch.object(Connection, "getresponse", response),
                ):
                    report = self.report()
                    self.assertEqual(
                        report["provider_diagnostics"][gate], {"stage": stage, "code": code}
                    )

    def test_each_operation_schema_mismatch(self):
        for index in range(6):
            self.h = Harness()
            self.h.collector._scope_source = None
            gate, stage, path = self.operations()[index]
            self.h.responses[path] = {"unexpected": SYNTHETIC_SECRET}
            with self.subTest(stage=stage):
                self.assertEqual(
                    self.report()["provider_diagnostics"][gate],
                    {"stage": stage, "code": "SCHEMA_MISMATCH"},
                )

    def test_each_operation_transport_error_safe_classification(self):
        original = Connection.getresponse
        for index in range(6):
            for error, code in (
                (socket.gaierror(SYNTHETIC_SECRET), "DNS_FAILURE"),
                (ssl.SSLError(ADMIN_MARKER), "TLS_OR_PROXY_FAILURE"),
                (http.client.HTTPException(SYNTHETIC_SECRET), "TLS_OR_PROXY_FAILURE"),
                (TimeoutError(SYNTHETIC_SECRET), "TIMEOUT"),
                (ConnectionError(ADMIN_MARKER), "TRANSPORT_FAILURE"),
                (AgentsAPIError("unsupported_proxy_configuration"), "TLS_OR_PROXY_FAILURE"),
                (AgentsAPIError("http_response_headers_too_large"), "RESPONSE_TOO_LARGE"),
            ):
                self.h = Harness()
                self.h.collector._scope_source = None
                gate, stage, path = self.operations()[index]

                def response(conn, path=path, error=error):
                    if conn.path == path:
                        raise error
                    return original(conn)

                with (
                    self.subTest(stage=stage, code=code),
                    patch.object(Connection, "getresponse", response),
                ):
                    self.assertEqual(
                        self.report()["provider_diagnostics"][gate], {"stage": stage, "code": code}
                    )

    def test_connect_errors_do_not_send_and_exception_context_is_empty(self):
        for error, code in (
            (socket.gaierror(SYNTHETIC_SECRET), "DNS_FAILURE"),
            (ssl.SSLError(ADMIN_MARKER), "TLS_OR_PROXY_FAILURE"),
            (TimeoutError(SYNTHETIC_SECRET), "TIMEOUT"),
        ):
            self.h = Harness()
            self.h.fault = error
            for transport in (self.h.admin._transport, self.h.canary._transport):
                with self.assertRaises(AgentsAPIError) as caught:
                    transport.read(transport._allowed()[0][0])
                self.assertEqual(str(caught.exception), code)
                self.assertIsNone(caught.exception.__context__)
                formatted = "".join(traceback.format_exception(caught.exception))
                self.assertNotIn(SYNTHETIC_SECRET, formatted)
                self.assertNotIn(ADMIN_MARKER, formatted)
            self.assertEqual(self.h.calls, [])

    def test_missing_account_key_or_model_is_distinct_from_schema(self):
        for index in (1, 2, 4):
            self.h = Harness()
            self.h.collector._scope_source = None
            gate, stage, path = self.operations()[index]
            self.h.responses[path]["data"] = []
            self.assertEqual(
                self.report()["provider_diagnostics"][gate],
                {"stage": stage, "code": "EXPECTED_RECORD_MISSING"},
            )

    def test_agent_drift_and_budget_mismatch(self):
        self.h.agent["model"] = "unapproved-model"
        self.h.spend["threshold_amount"] = 101
        report = self.report()
        self.assertEqual(
            report["provider_diagnostics"]["agent_configuration"],
            {"stage": "CANARY_AGENT", "code": "CONFIGURATION_MISMATCH"},
        )
        self.assertEqual(
            report["provider_diagnostics"]["spend_controls"],
            {"stage": "ADMIN_SPEND_LIMIT", "code": "BUDGET_MISMATCH"},
        )

    def test_stale_diagnostics_reset_per_read(self):
        h = self.h
        self.assertIsNotNone(h.collector.read(h.bound, "agent_configuration"))
        h.status = 403
        self.assertIsNone(h.collector.read(h.bound, "agent_configuration"))
        self.assertEqual(
            h.collector.diagnostics()["agent_configuration"],
            {"stage": "CANARY_MODELS", "code": "HTTP_403"},
        )
        self.assertEqual(h.collector.diagnostics()["spend_controls"]["code"], "NOT_ATTEMPTED")

    def test_verifier_timestamp_rejection_does_not_report_diagnostic_pass(self):
        original = Connection.getresponse

        def response(conn):
            result = original(conn)
            self.h.clock += 1
            return result

        with patch.object(Connection, "getresponse", response):
            report = self.report()
        for gate in ("spend_controls", "agent_configuration"):
            self.assertEqual(report["checks"][gate], runner.MISSING)
            self.assertEqual(
                report["provider_diagnostics"][gate],
                {"stage": "FINAL_VALIDATION", "code": "OBSERVATION_INVALID"},
            )

    def test_role_swaps_remain_blocked_before_any_connection(self):
        h = self.h
        h.collector._admin, h.collector._canary = h.canary, h.admin
        report = self.report()
        self.assertEqual(h.calls, [])
        for gate in PROVIDER_GATES:
            self.assertEqual(
                report["provider_diagnostics"][gate],
                {"stage": "IDENTITY_VALIDATION", "code": "IDENTITY_OR_HANDLE_INVALID"},
            )

    def test_closed_vocabulary_no_extra_fields_or_dynamic_values(self):
        self.assertEqual(sanitize_diagnostics(empty_diagnostics()), empty_diagnostics())
        for gate in PROVIDER_GATES:
            for item in (
                {"stage": ADMIN_MARKER, "code": "HTTP_403"},
                {"stage": "NOT_ATTEMPTED", "code": SYNTHETIC_SECRET},
                {"stage": "NOT_ATTEMPTED", "code": "NOT_ATTEMPTED", "body": ADMIN_MARKER},
                {"stage": [], "code": "PASS"},
                {"stage": "FINAL_VALIDATION", "code": []},
                {"stage": "NOT_ATTEMPTED", "code": "PASS"},
            ):
                value = empty_diagnostics()
                value[gate] = item
                with self.assertRaises(AgentsAPIError):
                    sanitize_diagnostics(value)
            self.assertTrue(STAGES[gate])
        self.assertIn("PASS", CODES)

    def test_broker_schema_v2_roundtrip_and_inconsistent_reports_rejected(self):
        report = runner._report("READ_ONLY", "COLLECTED")
        self.assertEqual(broker._sanitize(json.dumps(report)), report)
        mutations = [
            report | {"schema_version": 1},
            report | {"schema_version": True},
            report | {"provider_observations": "SOME_VALID"},
            report | {"provider_diagnostics": {}},
            report | {"provider_diagnostics": ADMIN_MARKER},
        ]
        for gate in PROVIDER_GATES:
            changed = deepcopy(report)
            changed["checks"][gate] = "PASS"
            mutations.append(changed)
            changed = deepcopy(report)
            changed["provider_diagnostics"][gate] = {"stage": "FINAL_VALIDATION", "code": "PASS"}
            mutations.append(changed)
        for changed in mutations:
            with self.assertRaises(AgentsAPIError):
                broker._sanitize(json.dumps(changed))
        for gate in PROVIDER_GATES:
            report["checks"][gate] = "PASS"
            report["provider_diagnostics"][gate] = {"stage": "FINAL_VALIDATION", "code": "PASS"}
        report["provider_observations"] = "SOME_VALID"
        self.assertEqual(broker._sanitize(json.dumps(report)), report)
        report["outcome"] = "BLOCKED"
        with self.assertRaises(AgentsAPIError):
            broker._sanitize(json.dumps(report))
