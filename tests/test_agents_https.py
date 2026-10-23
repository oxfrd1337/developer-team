"""Credential-free hardened HTTPS negative matrix; wire is always injected."""

import io
import os
import ssl
import tempfile
import threading
import time
import traceback
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from developer_team.adapters.agents_api_contracts import AgentsAPIError, WireRequest, WireResponse
from developer_team.adapters.agents_https import FDSecretStore, HardenedHTTPS
from tests.acceptance_support import SYNTHETIC_SECRET, SyntheticStore, WireConnection
from tests.agents_api_support import FixtureTransport, binding


class HTTPSTests(unittest.TestCase):
    def setUp(self):
        self.bound = binding()
        self.wire = FixtureTransport()
        self.conn = WireConnection(self.wire)
        self.factory = Mock(return_value=self.conn)
        self.gate = Mock()
        self.transport = HardenedHTTPS(
            self.bound, SyntheticStore(), mutation_gate=self.gate, connection_factory=self.factory
        )

    def request(self, **changes):
        return replace(
            WireRequest(
                "GET",
                "https://api.openai.com/v1/agents/sessions/session_synthetic",
                (
                    ("OpenAI-Beta", "agents=v1"),
                    ("OpenAI-Project", self.bound.project_id),
                    ("Content-Type", "application/json"),
                ),
                None,
                time.monotonic() + 5,
                65536,
            ),
            **changes,
        )

    def test_success_discards_response_headers_and_closes_connection(self):
        response = self.transport.exchange(self.request())
        self.assertEqual(response.status, 200)
        self.assertTrue(self.conn.closed)
        self.factory.assert_called_once()
        self.gate.assert_not_called()

    def test_wrong_origin_port_scheme_userinfo_path_query_fragment_blocks_before_store(self):
        for url in (
            "http://api.openai.com/v1/agents/sessions/session_synthetic",
            "https://api.openai.com.evil/v1/agents/sessions/session_synthetic",
            "https://api.openai.com:443/v1/agents/sessions/session_synthetic",
            "https://evil@api.openai.com/v1/agents/sessions/session_synthetic",
            "https://api.openai.com/v1/files",
            "https://api.openai.com/v1/agents/sessions/../files",
            "https://api.openai.com/v1/agents/sessions/session_synthetic#secret",
            "https://api.openai.com/v1/agents/sessions/session_synthetic?foo=bar",
            "https://api.openai.com/v1/agents/sessions/%2e%2e",
        ):
            with self.subTest(url=url), self.assertRaises(AgentsAPIError):
                self.transport.exchange(self.request(url=url))
        self.factory.assert_not_called()

    def test_wrong_project_duplicate_auth_or_extra_headers_block(self):
        headers = self.request().headers
        for value in (
            (),
            headers + (("Authorization", "Bearer " + SYNTHETIC_SECRET),),
            headers + (("OpenAI-Project", self.bound.project_id),),
            (headers[0], ("OpenAI-Project", "other"), headers[2]),
            headers + (("X-Anything", "\r\nsecret"),),
        ):
            with self.assertRaises(AgentsAPIError):
                self.transport.exchange(self.request(headers=value))
        self.factory.assert_not_called()

    def test_methods_free_bodies_and_oversized_limits_block(self):
        for changes in (
            {"method": "DELETE"},
            {"method": "PUT"},
            {"method": "post"},
            {"method": "POST", "body": b'{"prompt":"anything"}'},
            {"body": b"{}"},
            {"max_response_bytes": 65537},
            {"max_response_bytes": True},
            {"deadline": float("nan")},
            {"deadline": float("inf")},
            {"deadline": time.monotonic() - 1},
            {"deadline": time.monotonic() + 60},
        ):
            with self.assertRaises(AgentsAPIError):
                self.transport.exchange(self.request(**changes))
        self.factory.assert_not_called()

    def test_missing_store_blocks_before_connection(self):
        transport = HardenedHTTPS(self.bound, connection_factory=self.factory)
        with self.assertRaisesRegex(AgentsAPIError, "secret_store"):
            transport.exchange(self.request())
        self.factory.assert_not_called()

    def test_store_errors_are_sanitized_before_connection(self):
        store = Mock()
        store.with_authorization.side_effect = PermissionError(SYNTHETIC_SECRET)
        transport = HardenedHTTPS(self.bound, store, connection_factory=self.factory)
        with self.assertRaises(AgentsAPIError) as caught:
            transport.exchange(self.request())
        self.assertNotIn(SYNTHETIC_SECRET, str(caught.exception))
        self.assertIsNone(caught.exception.__context__)
        self.factory.assert_not_called()

    def test_redirects_and_401_403_429_5xx_never_follow_retry_or_return_body(self):
        for status in (301, 302, 303, 307, 308, 401, 403, 429, 500, 502, 503):
            with self.subTest(status=status):
                self.conn.status, self.conn.body = status, SYNTHETIC_SECRET.encode()
                response = self.transport.exchange(self.request())
                self.assertEqual(response, WireResponse(status))
        self.assertEqual(len(self.wire.calls), 11)

    def test_dns_tls_connection_timeout_exceptions_never_leak_or_retry(self):
        for fault in (
            OSError(SYNTHETIC_SECRET),
            ssl.SSLError(SYNTHETIC_SECRET),
            ConnectionError(SYNTHETIC_SECRET),
            TimeoutError(SYNTHETIC_SECRET),
        ):
            self.conn.fault = fault
            with self.assertRaises(AgentsAPIError) as caught:
                self.transport.exchange(self.request())
            rendered = "".join(traceback.format_exception(caught.exception))
            self.assertNotIn(SYNTHETIC_SECRET, rendered)
            self.assertIsNone(caught.exception.__context__)
        self.assertEqual(self.wire.calls, [])
        self.assertEqual(self.factory.call_count, 4)

    def test_response_size_incremental_limit_and_exact_boundary(self):
        self.conn.body = b"x" * 1024
        self.assertEqual(
            len(self.transport.exchange(self.request(max_response_bytes=1024)).body), 1024
        )
        self.conn.body = b"x" * 1025
        with self.assertRaises(AgentsAPIError):
            self.transport.exchange(self.request(max_response_bytes=1024))

    def test_total_deadline_bounds_dns_and_prevents_late_request(self):
        release = threading.Event()
        connected = threading.Event()

        def slow_connect():
            connected.set()
            release.wait(2)

        self.conn.connect = slow_connect
        started = time.monotonic()
        with self.assertRaises(AgentsAPIError):
            self.transport.exchange(self.request(deadline=started + 0.05))
        self.assertTrue(connected.is_set())
        self.assertLess(time.monotonic() - started, 1)
        release.set()
        self.assertFalse(self.conn.sent)

    def test_total_deadline_bounds_stalled_headers_and_read(self):
        for phase in ("headers", "read"):
            conn = WireConnection(self.wire)
            release = threading.Event()
            if phase == "headers":
                conn.getresponse = lambda release=release: release.wait(2)
            else:
                raw = io.BytesIO(b"x")
                raw.status = 200
                raw.read1 = lambda count, release=release: release.wait(2)
                conn.getresponse = lambda raw=raw: raw
            self.factory.return_value = conn
            started = time.monotonic()
            with self.assertRaises(AgentsAPIError):
                self.transport.exchange(self.request(deadline=started + 0.05))
            self.assertLess(time.monotonic() - started, 1)
            release.set()
            self.assertTrue(conn.closed)

    def test_read_timeout_and_connect_timeout_are_hard_bounded(self):
        self.transport.exchange(self.request())
        self.assertLessEqual(self.factory.call_args.args[0], 2)
        for call in self.conn.sock.settimeout.call_args_list:
            self.assertGreater(call.args[0], 0)
            self.assertLessEqual(call.args[0], 2)
        for value in (0, -1, 6, True, float("inf"), float("nan")):
            with self.assertRaises(AgentsAPIError):
                HardenedHTTPS(self.bound, connect_timeout=value)
            with self.assertRaises(AgentsAPIError):
                HardenedHTTPS(self.bound, read_timeout=value)

    def test_proxy_route_and_tls_validation_remain_enabled(self):
        with (
            patch(
                "developer_team.adapters.agents_https.getproxies",
                return_value={"https": "http://proxy:8080"},
            ),
            patch("http.client.HTTPSConnection") as factory,
        ):
            HardenedHTTPS._connection(2)
            factory.return_value.set_tunnel.assert_called_once_with("api.openai.com", 443)
            context = factory.call_args.kwargs["context"]
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        with (
            patch("developer_team.adapters.agents_https.getproxies", return_value={}),
            patch("http.client.HTTPSConnection") as factory,
        ):
            HardenedHTTPS._connection(2)
            self.assertEqual(factory.call_args.args[:2], ("api.openai.com", 443))

    def test_unsupported_proxy_refuses_without_direct_fallback(self):
        for proxy in (
            "https://proxy",
            "http://user:secret@proxy",
            "http://proxy/path",
            "http://proxy?q=x",
        ):
            with (
                patch(
                    "developer_team.adapters.agents_https.getproxies", return_value={"https": proxy}
                ),
                patch("http.client.HTTPSConnection") as factory,
            ):
                with self.assertRaises(AgentsAPIError):
                    HardenedHTTPS._connection(2)
                factory.assert_not_called()

    def test_external_store_fd_private_file_only_no_key_return(self):
        with tempfile.TemporaryFile() as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(SYNTHETIC_SECRET.encode())
            stream.flush()
            store = FDSecretStore(stream.fileno(), self.bound.project_id)
            result = store.with_authorization(
                self.bound.project_id, lambda value: WireResponse(204)
            )
            self.assertEqual(result, WireResponse(204))
            self.assertNotIn(SYNTHETIC_SECRET, repr(store))
            for project in ("other", None):
                with self.assertRaises(AgentsAPIError):
                    store.with_authorization(project, lambda value: WireResponse(204))
            os.fchmod(stream.fileno(), 0o644)
            with self.assertRaises(AgentsAPIError):
                store.with_authorization(self.bound.project_id, lambda value: WireResponse(204))

    def test_fd_store_missing_unreadable_or_invalid_material_blocks_before_send(self):
        with tempfile.TemporaryFile() as stream:
            store = FDSecretStore(stream.fileno(), self.bound.project_id)
            send = Mock(return_value=WireResponse(204))
            for data in (b"", b"x" * 513, b"Bearer secret", b"secret\r\nheader", b"\xff"):
                stream.seek(0)
                stream.truncate()
                stream.write(data)
                stream.flush()
                with self.assertRaises(AgentsAPIError):
                    store.with_authorization(self.bound.project_id, send)
            send.assert_not_called()
        with self.assertRaises(AgentsAPIError):
            store.with_authorization(self.bound.project_id, send)
        for descriptor in (-1, None, True):
            with self.assertRaises(AgentsAPIError):
                FDSecretStore(descriptor, self.bound.project_id)

    def test_header_limit_applies_to_status_line_and_cumulative_headers(self):
        from developer_team.adapters.agents_https import BoundedHTTPResponse

        for header in (b"X-Large: " + b"x" * 8192, b"X-A: y\r\n" * 100):
            sock = Mock()
            sock.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 OK\r\n" + header + b"\r\n\r\n")
            response = BoundedHTTPResponse(sock, header_limit=256)
            with self.assertRaises(AgentsAPIError):
                response.begin()
            response.close()
        sock = Mock()
        sock.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        response = BoundedHTTPResponse(sock, header_limit=256)
        response.begin()
        self.assertEqual(response.read(), b"{}")
        response.close()

    def test_no_implicit_reconnect_after_connection_is_closed(self):
        self.transport.exchange(self.request())
        self.assertEqual(self.conn.auto_open, 0)

    def test_complete_dns_tcp_tls_phase_has_its_own_absolute_deadline(self):
        release = threading.Event()
        self.conn.connect = lambda: release.wait(2)
        self.transport._connect_timeout = 0.03
        started = time.monotonic()
        with self.assertRaises(AgentsAPIError):
            self.transport.exchange(self.request())
        self.assertLess(time.monotonic() - started, 1)
        release.set()
        self.assertFalse(self.conn.sent)

    def test_complete_read_phase_has_its_own_absolute_deadline(self):
        release = threading.Event()
        self.conn.getresponse = lambda: release.wait(2)
        self.transport._read_timeout = 0.03
        started = time.monotonic()
        with self.assertRaises(AgentsAPIError):
            self.transport.exchange(self.request())
        self.assertLess(time.monotonic() - started, 1)
        release.set()
