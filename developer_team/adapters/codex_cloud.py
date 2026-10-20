"""Gateway for the observed experimental Codex Cloud CLI, not an invented Cloud REST API.

Task completion, immutable checkout extraction and independently attested reviews remain
integration work. A submission receipt is never accepted as QA, security or test evidence.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Protocol

from ..authority import ProjectGrant, RuntimePolicy
from ..config import ProjectConfig
from ..models import IntegrationUnavailable, PermissionDenied, Role
from ..roles import ROLE_INSTRUCTIONS


class CliRunner(Protocol):
    def __call__(self, argv: list[str]) -> str: ...


def run_cli(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=45)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise IntegrationUnavailable(
            f"Codex CLI failed ({type(exc).__name__}); a submission may be ambiguous. "
            "Inspect the cloud task list before any new submission."
        ) from exc


@dataclass(frozen=True)
class CloudSubmission:
    task_id: str
    expected_sha: str
    role: Role
    environment: str
    verified_execution: bool = False


class CodexCloudGateway:
    def __init__(self, runner: CliRunner = run_cli):
        self.runner = runner

    def probe(self) -> dict:
        version = self.runner(["codex", "--version"])
        help_text = self.runner(["codex", "cloud", "exec", "--help"])
        status_help = self.runner(["codex", "cloud", "status", "--help"])
        diff_help = self.runner(["codex", "cloud", "diff", "--help"])
        auth = self.runner(["codex", "login", "status"])
        return {
            "version": version,
            "submit_interface_present": all(flag in help_text for flag in ("--env", "--branch")),
            "status_interface_present": "TASK_ID" in status_help,
            "diff_interface_present": "TASK_ID" in diff_help,
            "chatgpt_login_reported": "ChatGPT" in auth,
            "remote_task_verified": False,
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
    ) -> CloudSubmission:
        if policy.safe_test_mode or not policy.first_release_approved or policy.bootstrap:
            raise PermissionDenied("Safe test mode forbids Codex Cloud task submission")
        grant.require(config, "cloud_submit", effective_digest)
        if config.provider != "github":
            raise PermissionDenied("Only individually authorized GitHub projects may use cloud")
        environments = dict(grant.cloud_environments)
        environment = environments.get(role, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", environment):
            raise PermissionDenied("A role-specific authorized cloud environment is required")
        review_environments = [
            environments.get(r) for r in (Role.DEVELOPER, Role.QA, Role.SECURITY)
        ]
        if not all(review_environments) or len(set(review_environments)) != 3:
            raise PermissionDenied(
                "Development, QA and security require separate cloud environments"
            )
        if (
            not re.fullmatch(r"dt/[A-Za-z0-9][A-Za-z0-9/_-]*", branch)
            or branch == config.base_branch
            or not re.fullmatch(r"[0-9a-f]{40}", expected_sha)
        ):
            raise PermissionDenied("Invalid cloud branch or expected commit")
        if not prompt.strip() or len(prompt) > 100_000:
            raise PermissionDenied("Invalid cloud prompt")
        task_prompt = (
            ROLE_INSTRUCTIONS[role]
            + f"\nRepository: {config.repository}\nExpected initial HEAD: {expected_sha}\n"
            + "Verify the exact HEAD before work; report a mismatch without editing.\n"
            + prompt
        )
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
        match = re.search(r"https://chatgpt\.com/codex/tasks/(task_[A-Za-z0-9_-]+)", receipt)
        if match is None:
            raise IntegrationUnavailable(
                "Cloud submission receipt format is unknown. Do not resubmit automatically; "
                "reconcile with codex cloud list."
            )
        return CloudSubmission(match.group(1), expected_sha, role, environment)

    @staticmethod
    def _task(task_id: str) -> str:
        if not re.fullmatch(r"task_[A-Za-z0-9_-]{1,200}", task_id):
            raise PermissionDenied("Invalid Codex task identifier")
        return task_id

    def status(self, task_id: str) -> str:
        return self.runner(["codex", "cloud", "status", self._task(task_id)])

    def diff(self, task_id: str) -> str:
        return self.runner(["codex", "cloud", "diff", self._task(task_id)])
