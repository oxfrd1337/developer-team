"""Local DT-017B one-shot runner; explicit GET consent never grants live authority."""

from __future__ import annotations

import argparse
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .adapters.agents_api_contracts import AgentsAPIError, CanaryBinding
from .adapters.agents_credentials import CredentialIdentity, require_identity
from .adapters.agents_https import FDSecretStore
from .adapters.provider_readonly_https import AdminCredentialIdentity, AdminFDSecretStore
from .agents_acceptance import ACCOUNT_CHECKS, ReadOnlyVerifier
from .provider_readonly import (
    AdminReadOnlyCollector,
    CanaryReadOnlyCollector,
    ProviderReadOnlyCollector,
)
from .provider_readonly_diagnostics import PROVIDER_GATES, empty_diagnostics

MISSING = "MISSING_OR_INVALID"
GATES = ACCOUNT_CHECKS + ("durable_journal", "fresh_create_approval", "fresh_submit_approval")
_OFFLINE_MARKERS = ("CI", "GITHUB_ACTIONS", "DT_PROVIDER_OFFLINE")
_UNSUPPORTED_SECRET_ENV = ("OPENAI_API_KEY", "OPENAI_ADMIN_API_KEY", "OPENAI_ADMIN_KEY")


@dataclass(frozen=True, slots=True, repr=False)
class ExternalFD:
    """Non-secret role pin supplied by the external credential-handle owner.

    snapshot = (device, inode, size, mtime_ns, ctime_ns), pinned independently of
    the descriptor selector. Never derive this pin from a selected FD in the runner.
    Provisioning must bind the correct credential to its immutable role identity.
    """

    descriptor: int
    identity: CredentialIdentity | AdminCredentialIdentity
    snapshot: tuple[int, int, int, int, int]

    def validate(self, identity):
        valid = False
        try:
            import fcntl

            if (
                type(self.descriptor) is int
                and self.descriptor >= 3
                and type(self.identity) is type(identity)
                and self.identity == identity
                and type(self.snapshot) is tuple
                and len(self.snapshot) == 5
                and all(type(v) is int and v >= 0 for v in self.snapshot)
            ):
                info = os.fstat(self.descriptor)
                valid = (
                    FDSecretStore._file_identity(info) == self.snapshot
                    and stat.S_ISREG(info.st_mode)
                    and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600
                    and 1 <= info.st_size <= 512
                    and fcntl.fcntl(self.descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
                )
        except Exception:
            valid = False
        if not valid:
            raise AgentsAPIError("external_role_bound_readonly_fd_required")


def _report(mode, outcome):
    return {
        "schema_version": 2,
        "mode": mode,
        "outcome": outcome,
        "checks": dict.fromkeys(GATES, MISSING),
        "provider_diagnostics": empty_diagnostics(),
        "provider_observations": "NONE_VALID",
        "LIVE": "NO-GO",
        "real_submissions": 0,
        "live_authorized": False,
        "validation": "OFFLINE/CI PASS IS NOT LIVE AGENTS-API VALIDATION.",
    }


def run_readonly(
    binding,
    identity,
    admin_identity,
    *,
    admin_fd=None,
    canary_fd=None,
    approved_models=frozenset(),
    execute_real_readonly=False,
    scope_source=None,
    scope_verifier=None,
    scope_attestor_identity=None,
    scope_verifier_identity=None,
    now=time.time,
):
    """Collect once, without credential discovery, raw persistence or live controller.

    Optional scope adapters are trusted local Python dependencies with independent
    pins, never import paths or attestations loaded from JSON. The CLI cannot set
    execute_real_readonly via its manifest, environment or a saved report.
    """
    report = _report("PLAN", "NOT_EXECUTED")
    try:
        if type(execute_real_readonly) is not bool:
            raise AgentsAPIError("explicit_boolean_consent_required")
        if type(binding) is not CanaryBinding:
            raise AgentsAPIError("binding_required")
        binding.validate()
        require_identity(identity, binding, int(now()))
        if type(admin_identity) is not AdminCredentialIdentity:
            raise AgentsAPIError("admin_identity_required")
        admin_identity.validate(binding, int(now()))
        if (
            admin_identity.handle_ref == identity.handle_ref
            or admin_identity.admin_ref == identity.credential_ref
        ):
            raise AgentsAPIError("separate_identities_required")
        if not execute_real_readonly:
            return report
        report = _report("READ_ONLY", "BLOCKED")
        if any(name in os.environ for name in _OFFLINE_MARKERS + _UNSUPPORTED_SECRET_ENV):
            return report
        if type(admin_fd) is not ExternalFD or type(canary_fd) is not ExternalFD:
            return report
        admin_fd.validate(admin_identity)
        canary_fd.validate(identity)
        if admin_fd.snapshot[:2] == canary_fd.snapshot[:2]:
            return report
        if type(approved_models) is not frozenset or approved_models != frozenset({binding.model}):
            return report
        admin_store = AdminFDSecretStore(admin_fd.descriptor, admin_identity)
        canary_store = FDSecretStore(canary_fd.descriptor, identity)
        # Recheck both pins after store construction and before any provider read.
        admin_fd.validate(admin_identity)
        canary_fd.validate(identity)
        collector = ProviderReadOnlyCollector(
            binding,
            identity,
            admin=AdminReadOnlyCollector(binding, identity, admin_store, now=now),
            canary=CanaryReadOnlyCollector(
                binding, identity, canary_store, approved_models=approved_models, now=now
            ),
            scope_source=scope_source,
            scope_verifier=scope_verifier,
            scope_attestor_identity=scope_attestor_identity,
            scope_verifier_identity=scope_verifier_identity,
            now=now,
        )
        checks, observations = ReadOnlyVerifier(collector).inspect(binding, int(now()), identity)
        # Earlier GETs must still be current when the complete report is emitted.
        final = int(now())
        require_identity(identity, binding, final)
        admin_identity.validate(binding, final)
        admin_fd.validate(admin_identity)
        canary_fd.validate(identity)
        for name, observation in observations.items():
            if final - 300 <= observation.observed_at <= final < observation.expires_at:
                report["checks"][name] = checks[name]
        report["outcome"] = "COLLECTED"
        report["provider_diagnostics"] = collector.diagnostics()
        for name in PROVIDER_GATES:
            if (
                report["checks"][name] != "PASS"
                and report["provider_diagnostics"][name]["code"] == "PASS"
            ):
                report["provider_diagnostics"][name] = {
                    "stage": "FINAL_VALIDATION",
                    "code": "OBSERVATION_INVALID",
                }
        if any(report["checks"][name] == "PASS" for name in PROVIDER_GATES):
            report["provider_observations"] = "SOME_VALID"
    except Exception:
        # No exception text, provider body, headers, secret digest or traceback.
        report = _report(report["mode"], "BLOCKED")
    return report


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default diagnostic echoes unrecognized argv, possibly secrets.
        raise AgentsAPIError("invalid_runner_arguments")


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AgentsAPIError("duplicate_manifest_field")
        value[key] = item
    return value


def _manifest(path):
    # Only non-secret metadata. No stdin, credential paths, URLs, methods or plugins.
    manifest = Path(path)
    if not stat.S_ISREG(manifest.lstat().st_mode):
        raise AgentsAPIError("regular_manifest_required")
    descriptor = os.open(manifest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AgentsAPIError("regular_manifest_required")
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise AgentsAPIError("manifest_too_large")
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict or set(value) != {
        "binding",
        "canary_identity",
        "admin_identity",
        "admin_fd_pin",
        "canary_fd_pin",
        "approved_models",
    }:
        raise AgentsAPIError("invalid_manifest_fields")
    binding = CanaryBinding(**value["binding"])
    identity = CredentialIdentity(**value["canary_identity"])
    admin = AdminCredentialIdentity(**value["admin_identity"])
    for name in ("admin_fd_pin", "canary_fd_pin"):
        pin = value[name]
        if type(pin) is not list or len(pin) != 5 or any(type(v) is not int or v < 0 for v in pin):
            raise AgentsAPIError("invalid_fd_pin")
    models = value["approved_models"]
    if type(models) is not list or models != [binding.model]:
        raise AgentsAPIError("invalid_model_approval")
    return value, binding, identity, admin


def main(argv=None):
    report = _report("PLAN", "BLOCKED")
    try:
        parser = _Parser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--admin-fd", type=int)
        parser.add_argument("--canary-fd", type=int)
        parser.add_argument("--execute-real-readonly", action="store_true")
        args = parser.parse_args(argv)
        value, binding, identity, admin = _manifest(args.manifest)
        report = run_readonly(
            binding,
            identity,
            admin,
            admin_fd=ExternalFD(args.admin_fd, admin, tuple(value["admin_fd_pin"])),
            canary_fd=ExternalFD(args.canary_fd, identity, tuple(value["canary_fd_pin"])),
            approved_models=frozenset(value["approved_models"]),
            execute_real_readonly=args.execute_real_readonly,
        )
    except Exception:
        report = _report("PLAN", "BLOCKED")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    # Evidence collection is never a successful live authorization.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
