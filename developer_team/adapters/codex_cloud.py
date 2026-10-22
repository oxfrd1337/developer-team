"""Observed Codex Cloud CLI lifecycle; no private or hypothetical REST endpoints.

DT-008 permanently denies submissions in this version, independent of transports,
labels, grants and approvals. Offline lifecycle fixtures live in a separate module.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Protocol

from ..authority import ProjectGrant, RuntimePolicy
from ..config import ProjectConfig
from ..models import IntegrationUnavailable, PermissionDenied, Role
from ..store import RunStore
from .cloud_contracts import CloudApproval, CloudJob


class CliRunner(Protocol):
    def __call__(self, argv: list[str]) -> str: ...


class CloudRefs(Protocol):
    def prepare(self, job: CloudJob) -> None: ...

    def verify(self, job: CloudJob) -> None: ...


def run_cli(argv: list[str]) -> str:
    # Do not use check=True: cloud status deliberately exits 1 for PENDING/ERROR/APPLIED.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, start_new_session=True
            )
            try:
                process.wait(timeout=45)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            if output.tell() + errors.tell() > 2_000_000:
                raise IntegrationUnavailable("Codex CLI output limit exceeded")
            output.seek(0)
            errors.seek(0)
            stdout, stderr = output.read().decode(), errors.read().decode()
            status_exit = argv[:3] == ["codex", "cloud", "status"] and re.match(
                r"^\[(PENDING|READY|ERROR|APPLIED)\] ", stdout
            )
            if process.returncode != 0 and not (process.returncode == 1 and status_exit):
                raise IntegrationUnavailable("Cloud CLI refused the operation; inspect permissions")
            return stdout or stderr
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            raise IntegrationUnavailable(
                f"Cloud CLI failed ({type(exc).__name__}); never retry ambiguous submissions"
            ) from exc


@dataclass(frozen=True)
class CloudSubmission:
    task_id: str
    expected_sha: str
    role: Role
    environment: str
    verified_execution: bool = False


class CodexCloudGateway:
    """Production inspection only. No injectable transport and no submission path."""

    simulated = False

    def __init__(
        self,
        *,
        store: RunStore | None = None,
        refs: CloudRefs | None = None,
        now=time.time,
    ):
        self.store, self.refs, self.now = store, refs, now

    def probe(self) -> dict:
        version = run_cli(["codex", "--version"])
        help_text = run_cli(["codex", "cloud", "exec", "--help"])
        status_help = run_cli(["codex", "cloud", "status", "--help"])
        diff_help = run_cli(["codex", "cloud", "diff", "--help"])
        list_help = run_cli(["codex", "cloud", "list", "--help"])
        try:
            auth = run_cli(["codex", "login", "status"])
        except IntegrationUnavailable:
            auth = ""
        # Never return raw login output: API-key login status can include key fragments.
        return {
            "version": version.strip(),
            "submit_interface_present": all(flag in help_text for flag in ("--env", "--branch")),
            "status_interface_present": "TASK_ID" in status_help,
            "diff_interface_present": "TASK_ID" in diff_help,
            "list_json_interface_present": "--json" in list_help,
            "chatgpt_login_reported": "ChatGPT" in auth,
            "unattended_cloud_auth_verified": False,
            "account_quota_remaining": None,
            "remote_task_verified": False,
            "provider_cost_limit_available": False,
            "provider_cancel_available": False,
            "checkout_attestation_available": False,
        }

    def submit(
        self,
        *,
        config: ProjectConfig,
        effective_digest: str,
        policy: RuntimePolicy,
        grant: ProjectGrant,
        role: Role,
        branch: str,
        expected_sha: str,
        prompt: str,
        approval: CloudApproval | None = None,
        job: CloudJob | None = None,
    ) -> CloudSubmission:
        raise PermissionDenied(
            "DT-008 NO-GO: real Cloud submission unsupported; "
            "independent role controls and remote stop contract missing"
        )

    def collect(self, job: CloudJob, approval: CloudApproval) -> str:
        raise PermissionDenied("DT-008 NO-GO: production Cloud collection unavailable")
