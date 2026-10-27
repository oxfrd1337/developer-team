"""DT-017A credential-separated GET-only wire boundary; no session endpoints."""

from __future__ import annotations

import math
import os
import re
import socket
import ssl
import stat
from dataclasses import dataclass

from ..provider_readonly_diagnostics import WIRE_FAILURES, DiagnosticFailure
from .agents_api_contracts import (
    PROVIDER_BASE,
    AgentsAPIError,
    WireRequest,
    WireResponse,
    bounded_int,
    safe_ref,
)
from .agents_credentials import require_identity
from .agents_https import FDSecretStore, HardenedHTTPS, ResponseTooLarge


@dataclass(frozen=True, slots=True, repr=False)
class AdminCredentialIdentity:
    project_id: str
    admin_ref: str
    handle_ref: str
    binding_digest: str
    issued_at: int
    expires_at: int

    def validate(self, binding, now):
        if (
            self.project_id != binding.project_id
            or self.binding_digest != binding.digest
            or not all(safe_ref(v) for v in (self.project_id, self.admin_ref, self.handle_ref))
            or not bounded_int(self.issued_at, max(0, now - 300), now)
            or not bounded_int(self.expires_at, now + 1, self.issued_at + 300)
        ):
            raise AgentsAPIError("admin_identity_missing_or_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class AdminFDSecretStore:
    """Separate external admin handle; never accepted by the canary HTTPS transport."""

    _descriptor: int
    identity: AdminCredentialIdentity
    _snapshot: tuple

    def __init__(self, descriptor, identity):
        snapshot = None
        try:
            if type(descriptor) is int and descriptor >= 0:
                snapshot = FDSecretStore._file_identity(os.fstat(descriptor))
        except OSError:
            snapshot = None
        if snapshot is None or type(identity) is not AdminCredentialIdentity:
            raise AgentsAPIError("external_admin_secret_store_required")
        object.__setattr__(self, "_descriptor", descriptor)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "_snapshot", snapshot)

    def with_authorization(self, identity, send):
        result = None
        try:
            info = os.fstat(self._descriptor)
            if (
                type(identity) is not AdminCredentialIdentity
                or identity != self.identity
                or FDSecretStore._file_identity(info) != self._snapshot
                or not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
                or info.st_uid != os.geteuid()
                or not 1 <= info.st_size <= 512
            ):
                raise ValueError
            secret = os.pread(self._descriptor, 513, 0)
            if (
                FDSecretStore._file_identity(os.fstat(self._descriptor)) != self._snapshot
                or re.fullmatch(rb"[A-Za-z0-9_-]{1,512}", secret) is None
            ):
                raise ValueError
            result = send("Bearer " + secret.decode("ascii"))
        except Exception:
            result = None
        if type(result) is not WireResponse:
            raise AgentsAPIError("admin_secret_or_transport_unavailable")
        return result


class _ReadOnlyHTTPS(HardenedHTTPS):
    """Reuse bounded DNS/TCP/TLS/header/body handling, never mutation dispatch.

    No caller-selected URL or header in collector APIs. exchange additionally
    rejects all but the exact role-specific paths before any handle or socket use.
    The inherited worker receives operation=None; no gate can authorize a POST.
    """

    def exchange(self, request):
        result = super().exchange(request)
        if result.status in WIRE_FAILURES:
            raise DiagnosticFailure(WIRE_FAILURES[result.status])
        return result

    def _accept_status(self, status):
        return status == 200

    def _validate(self, request):
        if type(request) is not WireRequest:
            raise AgentsAPIError("invalid_readonly_request")
        paths, headers = self._allowed()
        if (
            request.method != "GET"
            or type(request.url) is not str
            or request.url not in {PROVIDER_BASE + p for p in paths}
            or request.body is not None
            or type(request.headers) is not tuple
            or request.headers != headers
            or type(request.max_response_bytes) is not int
            or not 1 <= request.max_response_bytes <= 65536
            or type(request.deadline) not in {int, float}
            or not math.isfinite(request.deadline)
            or not 0 < request.deadline - self._clock() <= 5
        ):
            raise AgentsAPIError("readonly_operation_blocked")
        self._validate_identity()
        return request.url[len(PROVIDER_BASE) :], None

    def read(self, operation):
        paths, headers = self._allowed()
        if operation not in paths:
            raise AgentsAPIError("readonly_operation_blocked")
        return self.exchange(
            WireRequest("GET", PROVIDER_BASE + operation, headers, None, self._clock() + 5, 65536)
        )

    def _failure_response(self, error):
        # Classify by type only, never exception text (which can contain secrets).
        if isinstance(error, TimeoutError):
            status = -1
        elif isinstance(error, ssl.SSLError):
            status = -2
        elif isinstance(error, socket.gaierror):
            status = -3
        elif isinstance(error, ResponseTooLarge):
            status = -4
        elif type(error) is AgentsAPIError and error.args == ("http_response_headers_too_large",):
            status = -4
        elif type(error) is AgentsAPIError and error.args == ("unsupported_proxy_configuration",):
            status = -2
        else:
            # HTTPException (including protocol errors/disconnects) proves
            # neither TLS nor proxy failure; retain the neutral transport code.
            status = -5
        return WireResponse(status)


class AdminReadOnlyHTTPS(_ReadOnlyHTTPS):
    def __init__(self, binding, canary_identity, secret_store=None, **kwargs):
        self._canary_identity = canary_identity
        super().__init__(binding, secret_store, **kwargs)

    def _validate_identity(self):
        now = int(self._now())
        canary = require_identity(self._canary_identity, self._binding, now)
        admin = self._identity
        if type(admin) is not AdminCredentialIdentity:
            raise AgentsAPIError("external_admin_secret_store_required")
        admin.validate(self._binding, now)
        if (
            self._store.identity != admin
            or admin.handle_ref == canary.handle_ref
            or admin.admin_ref == canary.credential_ref
        ):
            raise AgentsAPIError("admin_canary_identity_separation_required")
        return admin

    def _allowed(self):
        b, c = self._binding, self._canary_identity
        # Validate before interpolating references, even on direct exchange().
        require_identity(c, b, int(self._now()))
        root = f"/v1/organization/projects/{b.project_id}"
        return (
            (
                root,
                root + "/service_accounts",
                root + "/api_keys?owner_project_access=any",
                root + f"/api_keys/{c.credential_ref}",
                root + "/spend_limit",
            ),
            (("Content-Type", "application/json"),),
        )


class CanaryReadOnlyHTTPS(_ReadOnlyHTTPS):
    def _validate_identity(self):
        # Exact same immutable type and handle contract as DT-017 HardenedHTTPS.
        identity = require_identity(self._identity, self._binding, int(self._now()))
        if self._store.identity != identity:
            raise AgentsAPIError("credential_handle_changed")
        return identity

    def _allowed(self):
        b = self._binding
        return (
            ("/v1/models", f"/v1/agents/{b.agent_id}"),
            (
                ("OpenAI-Beta", "agents=v1"),
                ("OpenAI-Project", b.project_id),
                ("Content-Type", "application/json"),
            ),
        )
