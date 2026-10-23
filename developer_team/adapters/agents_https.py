"""DT-017 fixed-origin HTTPS wire boundary. No implicit credentials or live grants."""

from __future__ import annotations

import http.client
import math
import os
import queue
import re
import socket
import ssl
import stat
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.request import getproxies

from .agents_api_contracts import (
    CANARY_MESSAGE,
    PROVIDER_BASE,
    SESSIONS_PATH,
    AgentsAPIError,
    CanaryBinding,
    WireRequest,
    WireResponse,
    canonical,
    safe_ref,
)


class _HeaderReader:
    def __init__(self, stream, limit):
        self._stream, self._remaining = stream, limit

    def readline(self, limit):
        data = self._stream.readline(min(limit, self._remaining + 1))
        self._remaining -= len(data)
        if self._remaining < 0:
            raise AgentsAPIError("http_response_headers_too_large")
        return data

    def close(self):
        self._stream.close()


class BoundedHTTPResponse(http.client.HTTPResponse):
    """Bound status line and complete response headers before parsing any body."""

    def __init__(self, *args, header_limit=8192, **kwargs):
        super().__init__(*args, **kwargs)
        self._header_limit = header_limit

    def begin(self):
        stream = self.fp
        self.fp = _HeaderReader(stream, self._header_limit)
        try:
            super().begin()
        finally:
            self.fp = stream


class FDSecretStore:
    """External store supplies an already opened private, regular-file descriptor.

    No path/env lookup and no public method returns credential material. The owner
    must keep the descriptor outside chat, repositories, prompts and logs. A new
    bounded read occurs per exchange, before any socket is opened.
    """

    def __init__(self, descriptor: int, project_id: str):
        if type(descriptor) is not int or descriptor < 0 or not safe_ref(project_id):
            raise AgentsAPIError("external_secret_store_required")
        self._descriptor, self._project = descriptor, project_id

    def with_authorization(self, project_id: str, send: Callable) -> WireResponse:
        result = None
        try:
            info = os.fstat(self._descriptor)
            if (
                project_id != self._project
                or not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
                or info.st_uid != os.geteuid()
                or not 1 <= info.st_size <= 512
            ):
                raise ValueError
            secret = os.pread(self._descriptor, 513, 0)
            if re.fullmatch(rb"[A-Za-z0-9_-]{1,512}", secret) is None:
                raise ValueError
            result = send("Bearer " + secret.decode("ascii"))
        except Exception:
            result = None  # Never propagate/chain a secret-store or wire exception.
        if type(result) is not WireResponse:
            raise AgentsAPIError("secret_or_transport_unavailable")
        return result


class HardenedHTTPS:
    """Only DT-016 requests; fresh authorization also at the final wire boundary.

    connection_factory is a trusted test seam, never configuration from a plan.
    No redirects, retries, cookies, response headers, error bodies or proxy fallback.
    """

    def __init__(
        self,
        binding: CanaryBinding,
        secret_store=None,
        *,
        mutation_gate=None,
        connection_factory=None,
        monotonic=time.monotonic,
        connect_timeout=2.0,
        read_timeout=2.0,
    ):
        binding.validate()
        for value in (connect_timeout, read_timeout):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 5:
                raise AgentsAPIError("invalid_transport_timeout")
        self._binding, self._store, self._gate = binding, secret_store, mutation_gate
        self._factory = connection_factory or self._connection
        self._clock = monotonic
        self._connect_timeout, self._read_timeout = connect_timeout, read_timeout

    @staticmethod
    def _connection(timeout):
        # Preserve configured proxy routing and system/SSL_CERT_FILE CA trust.
        proxy = getproxies().get("https")
        context = ssl.create_default_context()
        if proxy:
            parsed = urlsplit(proxy)
            if (
                parsed.scheme != "http"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise AgentsAPIError("unsupported_proxy_configuration")
            conn = http.client.HTTPSConnection(
                parsed.hostname, parsed.port or 8080, timeout=timeout, context=context
            )
            conn.set_tunnel("api.openai.com", 443)
            return conn
        return http.client.HTTPSConnection("api.openai.com", 443, timeout=timeout, context=context)

    def _validate(self, request):
        if type(request) is not WireRequest:
            raise AgentsAPIError("invalid_wire_request")
        b = self._binding
        base_headers = (
            ("OpenAI-Beta", "agents=v1"),
            ("OpenAI-Project", b.project_id),
            ("Content-Type", "application/json"),
        )
        if (
            type(request.url) is not str
            or not request.url.startswith(PROVIDER_BASE + SESSIONS_PATH)
            or type(request.max_response_bytes) is not int
            or not 1 <= request.max_response_bytes <= 65536
            or type(request.deadline) not in {int, float}
            or not math.isfinite(request.deadline)
            or not 0 < request.deadline - self._clock() <= 30
        ):
            raise AgentsAPIError("invalid_wire_binding_or_limits")
        path = request.url[len(PROVIDER_BASE) :]
        session = SESSIONS_PATH + r"/[A-Za-z0-9][A-Za-z0-9_-]{0,95}"
        listing = r"\?limit=(?:[1-9]|1[0-9]|20)&order=(?:asc|desc)"
        operation = None
        expected_headers = base_headers
        if request.method == "GET":
            valid = re.fullmatch(
                f"(?:{SESSIONS_PATH}{listing}|{session}|{session}/turns{listing})", path
            )
            if not valid or request.body is not None:
                raise AgentsAPIError("invalid_read_path")
        elif request.method == "POST" and path == SESSIONS_PATH:
            operation = "create_session"
            expected = {
                "agent_id": b.agent_id,
                "agent": b.agent_configuration,
                "environment": b.environment_configuration,
                "metadata": {"dt016_binding": b.digest},
                "spend_control": {"limit": b.budget_cents},
                "stream": False,
            }
            if request.body != canonical(expected):
                raise AgentsAPIError("invalid_create_body")
        elif request.method == "POST" and re.fullmatch(session + "/events", path):
            message = {
                "events": [
                    {
                        "type": "agent.session.input.message",
                        "input": [
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": CANARY_MESSAGE}],
                            }
                        ],
                    }
                ]
            }
            cancel = {"events": [{"type": "agent.session.input.cancel"}]}
            if request.body == canonical(message):
                operation = "submit_canary"
                expected_headers += (("Idempotency-Key", b.idempotency_key),)
            elif request.body == canonical(cancel):
                operation = "cancel"
            else:
                raise AgentsAPIError("invalid_event_body")
        else:
            raise AgentsAPIError("invalid_wire_operation")
        if type(request.headers) is not tuple or request.headers != expected_headers:
            raise AgentsAPIError("invalid_wire_headers")
        return path, operation

    def exchange(self, request: WireRequest) -> WireResponse:
        path, operation = self._validate(request)
        if self._store is None:
            raise AgentsAPIError("external_secret_store_required")
        if operation and self._gate is None:
            raise AgentsAPIError("fresh_operator_approval_required")
        result = None
        try:
            result = self._store.with_authorization(
                self._binding.project_id,
                lambda authorization: self._bounded(request, path, operation, authorization),
            )
        except Exception:
            result = None
        if type(result) is not WireResponse:
            raise AgentsAPIError("https_exchange_failed_reconcile_required")
        return result

    def _bounded(self, request, path, operation, authorization):
        if (
            type(authorization) is not str
            or re.fullmatch(r"Bearer [A-Za-z0-9_-]{1,512}", authorization) is None
        ):
            raise AgentsAPIError("invalid_external_authorization")
        remaining = request.deadline - self._clock()
        if remaining <= 0:
            raise AgentsAPIError("https_deadline_exceeded")
        results = queue.Queue(maxsize=1)
        stopped = threading.Event()
        connected = threading.Event()
        connect_deadline = min(request.deadline, self._clock() + self._connect_timeout)
        connections = []

        def abort():
            stopped.set()
            for conn in connections:
                try:
                    if conn.sock is not None:
                        conn.sock.shutdown(socket.SHUT_RDWR)
                    conn.close()
                except Exception:
                    stopped.set()

        def worker():
            response = None
            conn = None
            try:
                conn = self._factory(min(self._connect_timeout, remaining))
                connections.append(conn)
                conn.response_class = lambda *args, **kwargs: BoundedHTTPResponse(
                    *args, header_limit=min(8192, request.max_response_bytes), **kwargs
                )
                conn.auto_open = 0  # Never reconnect implicitly after a deadline closes the socket.
                conn.connect()  # The caller also bounds the complete DNS/TCP/TLS phase.
                if stopped.is_set() or self._clock() >= connect_deadline:
                    return
                connected.set()
                if stopped.is_set() or self._clock() >= request.deadline:
                    return
                conn.sock.settimeout(min(self._read_timeout, request.deadline - self._clock()))
                if operation:
                    self._gate(self._binding, operation, path)
                if stopped.is_set() or self._clock() >= request.deadline:
                    return
                headers = dict(request.headers)
                headers["Authorization"] = authorization
                headers["Accept-Encoding"] = "identity"
                conn.request(request.method, path, body=request.body, headers=headers)
                raw = conn.getresponse()
                if type(raw.status) is not int or not 200 <= raw.status < 300:
                    # Discard all error bodies and redirect locations without reading/following.
                    response = WireResponse(raw.status if type(raw.status) is int else 0)
                else:
                    chunks, size = [], 0
                    while True:
                        if stopped.is_set() or self._clock() >= request.deadline:
                            raise TimeoutError
                        conn.sock.settimeout(
                            min(self._read_timeout, request.deadline - self._clock())
                        )
                        chunk = raw.read1(min(4096, request.max_response_bytes + 1 - size))
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > request.max_response_bytes:
                            raise ValueError
                        chunks.append(chunk)
                    response = WireResponse(raw.status, b"".join(chunks))
            except Exception:
                response = None
            finally:
                connected.set()  # Wake the caller on an early connect failure, too.
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        response = None
                results.put(response)

        threading.Thread(target=worker, daemon=True).start()
        result = None
        try:
            if not connected.wait(timeout=max(0, connect_deadline - self._clock())):
                raise AgentsAPIError("https_connect_deadline_exceeded")
            result = results.get(
                timeout=max(0, min(self._read_timeout, request.deadline - self._clock()))
            )
        except queue.Empty:
            result = None
        finally:
            abort()
        if self._clock() >= request.deadline or type(result) is not WireResponse:
            raise AgentsAPIError("https_failed_or_timeout_reconcile_required")
        return result
