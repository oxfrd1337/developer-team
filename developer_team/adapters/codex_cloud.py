"""Observed Codex Cloud CLI lifecycle; no private or hypothetical REST endpoints.

Only an out-of-band, run-bound approval permits submission. Persisted intent prevents
ambiguous submissions from being retried. Receipts/results never attest test execution.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from ..authority import ProjectGrant, RuntimePolicy
from ..config import ProjectConfig
from ..models import CloudPending, IntegrationUnavailable, PermissionDenied, Role, TeamError, digest
from ..roles import ROLE_INSTRUCTIONS
from ..store import RunStore
from .cloud_contracts import RESULT_PATH, CloudApproval, CloudJob, strict_json


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
    def __init__(
        self,
        runner: CliRunner = run_cli,
        *,
        store: RunStore | None = None,
        refs: CloudRefs | None = None,
        now=time.time,
    ):
        self.runner, self.store, self.refs, self.now = runner, store, refs, now

    def probe(self) -> dict:
        version = self.runner(["codex", "--version"])
        help_text = self.runner(["codex", "cloud", "exec", "--help"])
        status_help = self.runner(["codex", "cloud", "status", "--help"])
        diff_help = self.runner(["codex", "cloud", "diff", "--help"])
        list_help = self.runner(["codex", "cloud", "list", "--help"])
        auth = self.runner(["codex", "login", "status"])
        return {
            "version": version.strip(),
            "submit_interface_present": all(flag in help_text for flag in ("--env", "--branch")),
            "status_interface_present": "TASK_ID" in status_help,
            "diff_interface_present": "TASK_ID" in diff_help,
            "list_json_interface_present": "--json" in list_help,
            "chatgpt_login_reported": "ChatGPT" in auth,
            "remote_task_verified": False,
            "provider_cost_limit_available": False,
            "provider_cancel_available": False,
            "checkout_attestation_available": False,
        }

    def _authorize(self, config, effective_digest, policy, grant, role, approval, job):
        if policy.safe_test_mode or approval is None or job is None:
            raise PermissionDenied(
                "Explicit cloud pilot approval required; safe test mode forbids it"
            )
        approval.validate(job.run_id, config.repository, effective_digest, self.now())
        job.validate()
        if (
            job.repository != config.repository
            or job.config_digest != effective_digest
            or job.role != role
        ):
            raise PermissionDenied("Cloud job does not match the project grant")
        grant.require(config, "cloud_submit", effective_digest)
        if config.provider != "github":
            raise PermissionDenied("Only individually authorized GitHub repositories may use cloud")
        if self.store is None or self.refs is None:
            raise PermissionDenied(
                "Durable task journal and trusted repository ref adapter required"
            )
        environments = dict(grant.cloud_environments)
        if len(environments) != len(grant.cloud_environments):
            raise PermissionDenied("Duplicate cloud role environment grants")
        environment = environments.get(role, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", environment):
            raise PermissionDenied("A role-specific authorized cloud environment is required")
        reviews = [environments.get(r) for r in (Role.DEVELOPER, Role.QA, Role.SECURITY)]
        if not all(reviews) or len(set(reviews)) != 3:
            raise PermissionDenied(
                "Development, QA and security require separate cloud environments"
            )
        return environment

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
        environment = self._authorize(config, effective_digest, policy, grant, role, approval, job)
        if branch != job.branch or expected_sha != job.head_sha or branch == config.base_branch:
            raise PermissionDenied("Cloud branch or commit does not match the durable job")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100_000:
            raise PermissionDenied("Invalid cloud prompt")
        # Both planning roles share this task; reviews always use separate tasks/environments.
        instructions = ROLE_INSTRUCTIONS[role]
        if role == Role.ORCHESTRATOR:
            instructions += "\n" + ROLE_INSTRUCTIONS[Role.ARCHITECT]
        task_prompt = (
            f"Job {job.id}\n{instructions}\nRepository: {config.repository}\n"
            f"Expected initial HEAD: {expected_sha}\n"
            "Verify the exact HEAD before work; on mismatch stop without source changes.\n"
            "Do not merge, deploy, push, access other projects or modify permissions.\n"
            f"Write the JSON result to {RESULT_PATH}. "
            "Use exactly this envelope, replacing payload:\n"
            + json.dumps(job.envelope(), sort_keys=True)
            + "\n"
            + prompt
        )
        with self.store.lock(str(uuid5(NAMESPACE_URL, job.id))):
            record = {
                "id": job.id,
                "run_id": job.run_id,
                "job": asdict(job),
                "prompt_digest": digest(task_prompt),
                "environment": environment,
                "state": "submitting",
                "task_id": None,
                "created_at": self.now(),
                "deadline": min(self.now() + approval.task_timeout_seconds, approval.expires_at),
                "polls": 0,
                "read_errors": 0,
                "next_poll_at": 0,
            }
            fresh = self.store.reserve_cloud_task(
                record,
                digest(asdict(approval)),
                approval.max_tasks,
                self.now(),
                approval.runtime_seconds,
            )
            if not fresh:
                record = self.store.cloud_task(job.id)
                if (
                    record["prompt_digest"] != digest(task_prompt)
                    or record["environment"] != environment
                    or record["job"] != json.loads(json.dumps(asdict(job)))
                ):
                    raise TeamError("Conflicting duplicate cloud submission")
                if not record["task_id"]:
                    raise TeamError(
                        "Ambiguous cloud submission; reconcile manually, never resubmit"
                    )
                self.refs.verify(job)
                return CloudSubmission(record["task_id"], expected_sha, role, environment)
            try:
                self.refs.prepare(job)
                self.refs.verify(job)
                self.ensure_current(job, approval)
                receipt = self.runner(
                    [
                        "codex",
                        "cloud",
                        "exec",
                        "--env",
                        environment,
                        "--branch",
                        branch,
                        "--attempts",
                        "1",
                        "--",
                        task_prompt,
                    ]
                )
                match = re.fullmatch(
                    r"https://chatgpt\.com/codex/tasks/(task_[A-Za-z0-9_-]{1,200})", receipt.strip()
                )
                if match is None:
                    raise IntegrationUnavailable("Unknown cloud receipt; reconcile manually")
                record.update(task_id=match.group(1), state="pending")
                self.store.save_cloud_task(record, "submitted")
            except BaseException:
                # Includes cancellation/crash windows: intent remains charged and never resubmits.
                record["state"] = "ambiguous"
                # A duplicate task ID must not overwrite the previously bound task record.
                if self.store.cloud_task(job.id).get("task_id") is None:
                    record["task_id"] = None
                self.store.save_cloud_task(record, "submission_uncertain")
                raise
            return CloudSubmission(record["task_id"], expected_sha, role, environment)

    @staticmethod
    def _task(task_id: str) -> str:
        if not re.fullmatch(r"task_[A-Za-z0-9_-]{1,200}", task_id):
            raise PermissionDenied("Invalid Codex task identifier")
        return task_id

    def status(self, task_id: str) -> str:
        return self.runner(["codex", "cloud", "status", self._task(task_id)])

    def diff(self, task_id: str) -> str:
        return self.runner(["codex", "cloud", "diff", self._task(task_id), "--attempt", "1"])

    def task_metadata(self, task_id: str, environment: str) -> dict:
        task_id = self._task(task_id)
        cursor = None
        cursors = set()
        matches = []
        for _ in range(10):
            argv = ["codex", "cloud", "list", "--json", "--env", environment, "--limit", "20"]
            if cursor:
                argv += ["--cursor", cursor]
            page = strict_json(self.runner(argv))
            if (
                set(page) != {"tasks", "cursor"}
                or not isinstance(page["tasks"], list)
                or len(page["tasks"]) > 20
            ):
                raise TeamError("Malformed cloud task page")
            matches.extend(
                t for t in page["tasks"] if isinstance(t, dict) and t.get("id") == task_id
            )
            cursor = page["cursor"]
            if cursor is None:
                if len(matches) != 1:
                    raise TeamError("Missing or duplicate cloud task metadata")
                return matches[0]
            if not isinstance(cursor, str) or not cursor or cursor in cursors or len(cursor) > 4096:
                raise TeamError("Invalid or repeated cloud pagination cursor")
            cursors.add(cursor)
        raise TeamError("Cloud pagination bound reached; incomplete results")

    def collect(self, job: CloudJob, approval: CloudApproval) -> str:
        """One bounded read cycle. No sleeps, background loops or submission retries."""
        with self.store.lock(str(uuid5(NAMESPACE_URL, job.id))):
            record = self.store.cloud_task(job.id)
            if record is None or not record.get("task_id"):
                raise TeamError("No unambiguous cloud task to collect")
            approval.validate(job.run_id, job.repository, job.config_digest, self.now())
            self.store.check_cloud_limits(
                job.run_id, digest(asdict(approval)), self.now(), approval.runtime_seconds
            )
            if record["state"] in ("failed", "timed_out", "import_uncertain"):
                raise TeamError("Cloud task stopped; manual escalation required")
            if self.now() >= record["deadline"] or record["polls"] >= approval.max_polls:
                record["state"] = "timed_out"
                self.store.save_cloud_task(record, "deadline_or_poll_limit")
                raise TeamError(
                    "Cloud deadline/poll limit reached; remote cancellation unavailable"
                )
            if self.now() < record["next_poll_at"]:
                raise CloudPending("Cloud task waiting for its next permitted poll")
            record["polls"] += 1
            record["next_poll_at"] = self.now() + approval.poll_interval_seconds
            self.store.save_cloud_task(record, "poll_intent")
            try:
                self.refs.verify(job)
                metadata = self.task_metadata(record["task_id"], record["environment"])
                timestamp = datetime.fromisoformat(metadata["updated_at"].replace("Z", "+00:00"))
                updated = timestamp.timestamp()
                status = metadata["status"]
                attempts = metadata.get("attempt_total")
                attempts_valid = (type(attempts) is int and attempts == 1) or (
                    status == "pending" and attempts is None
                )
                if (
                    metadata["environment_id"] != record["environment"]
                    or not attempts_valid
                    or timestamp.utcoffset() is None
                    or not record["created_at"] - 30 <= updated <= self.now() + 30
                ):
                    raise TeamError("Cloud task provenance, attempts or timestamp mismatch")
                status_text = self.status(record["task_id"])
                if status not in (
                    "pending",
                    "ready",
                    "applied",
                    "error",
                ) or not status_text.startswith(f"[{status.upper()}] "):
                    raise TeamError("Unknown or conflicting cloud statuses")
                if status in ("error", "applied"):
                    record["state"] = "failed"
                    self.store.save_cloud_task(record, "failed_or_externally_applied")
                    raise TeamError("Cloud task failed or was applied outside the controller")
                if status == "pending":
                    self.store.save_cloud_task(record, "pending")
                    raise CloudPending("Known cloud task is pending; resume the same run")
                patch = self.diff(record["task_id"])
                self.refs.verify(job)
                self.ensure_current(job, approval)
                if not patch or len(patch.encode()) > 1_000_000:
                    raise TeamError("Missing or oversized cloud diff")
                previous = record.get("result_digest")
                if previous and previous != digest(patch):
                    raise TeamError("Cloud result changed after collection")
                record.update(state="ready", result_digest=digest(patch), read_errors=0)
                self.store.save_cloud_task(record, "result_collected")
                return patch
            except IntegrationUnavailable as exc:
                record["read_errors"] += 1
                self.store.save_cloud_task(record, "read_error")
                if record["read_errors"] > approval.max_read_errors:
                    record["state"] = "failed"
                    self.store.save_cloud_task(record, "read_budget_exhausted")
                    raise TeamError("Cloud read retry budget exhausted") from exc
                raise CloudPending("Cloud read interrupted; retry only this known task") from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise TeamError("Malformed cloud task metadata") from exc

    def ensure_current(self, job: CloudJob, approval: CloudApproval) -> None:
        """Recheck after slow remote operations and before a local source import."""
        approval.validate(job.run_id, job.repository, job.config_digest, self.now())
        self.store.check_cloud_limits(
            job.run_id, digest(asdict(approval)), self.now(), approval.runtime_seconds
        )
        record = self.store.cloud_task(job.id)
        if record is None or self.now() >= record["deadline"]:
            if record is not None:
                record["state"] = "timed_out"
                self.store.save_cloud_task(record, "deadline_recheck")
            raise TeamError("Cloud deadline reached; no further submission or source import")
