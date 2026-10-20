"""Real GitHub REST command construction with separate PR and merge capabilities.

No workflow or CLI in DT-001 instantiates these write adapters. Live evidence collection
is deliberately incomplete, so the shipped merger always blocks live dispatch.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from ..authority import ProjectGrant, RuntimePolicy
from ..config import ProjectConfig
from ..gate import MergeGate
from ..models import (
    Binding,
    Evidence,
    IntegrationUnavailable,
    PermissionDenied,
    Plan,
    PlatformSnapshot,
    TeamError,
)


class GitHubTransport(Protocol):
    def request(self, method: str, path: str, payload: dict | None = None) -> Any: ...


class GhCliTransport:
    """Uses gh's existing external credential store; never accepts a token in a project file."""

    def request(self, method: str, path: str, payload: dict | None = None) -> Any:
        if method not in ("GET", "POST", "PUT") or not path.startswith("repos/"):
            raise PermissionDenied("Unsupported GitHub operation")
        args = ["gh", "api", "--method", method, path, "-H", "Accept: application/vnd.github+json"]
        if payload is not None:
            args += ["--input", "-"]
        try:
            result = subprocess.run(
                args,
                input=json.dumps(payload) if payload is not None else None,
                text=True,
                capture_output=True,
                check=True,
                timeout=45,
            )
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            # Do not copy authentication headers, provider output or private file content into logs.
            raise IntegrationUnavailable(
                f"GitHub request failed ({type(exc).__name__}); reconcile before retrying writes"
            ) from exc


@dataclass(frozen=True)
class RequiredGitHubCheck:
    name: str
    app_id: int


def _live_permission(
    config: ProjectConfig,
    effective_digest: str,
    grant: ProjectGrant,
    policy: RuntimePolicy,
    capability: str,
) -> None:
    if policy.safe_test_mode or not policy.first_release_approved or policy.bootstrap:
        raise PermissionDenied("DT-001 safe mode/first-release lock forbids GitHub writes")
    if config.provider != "github":
        raise PermissionDenied("GitHub transport cannot serve a local project")
    grant.require(config, capability, effective_digest)


class GitHubReader:
    """Bounded read-only collector. Unknown protection or provenance never becomes success."""

    def __init__(
        self,
        config: ProjectConfig,
        transport: GitHubTransport,
        required_checks: tuple[RequiredGitHubCheck, ...],
    ):
        self.config, self.transport, self.required_checks = config, transport, required_checks
        self.prefix = f"repos/{config.repository}"

    def _get(self, suffix: str) -> Any:
        return self.transport.request("GET", f"{self.prefix}/{suffix}")

    def _pages(self, suffix: str, *, key: str | None = None, max_pages: int = 30) -> list:
        items = []
        for page in range(1, max_pages + 1):
            separator = "&" if "?" in suffix else "?"
            response = self._get(f"{suffix}{separator}per_page=100&page={page}")
            batch = response[key] if key else response
            if not isinstance(batch, list) or len(batch) > 100:
                raise TeamError("Invalid GitHub page")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise TeamError("GitHub pagination limit reached; evidence is incomplete")

    def pull_request(self, number: int) -> dict:
        if type(number) is not int or number <= 0:
            raise TeamError("Invalid pull request number")
        return self._get(f"pulls/{number}")

    def snapshot(self, number: int) -> PlatformSnapshot:
        pr = self.pull_request(number)
        head, base = pr["head"], pr["base"]
        if (
            base["repo"]["full_name"] != self.config.repository
            or head["repo"]["full_name"] != self.config.repository
            or base["ref"] != self.config.base_branch
        ):
            raise PermissionDenied("Cross-project, fork or base-branch mismatch")
        if not all(re.fullmatch(r"[0-9a-f]{40}", item["sha"]) for item in (head, base)):
            raise TeamError("Invalid GitHub commit")
        files = self._pages(f"pulls/{number}/files")
        if type(pr.get("changed_files")) is not int or len(files) != pr["changed_files"]:
            raise TeamError("Incomplete GitHub changed-file list")
        paths = set()
        for item in files:
            paths.add(item["filename"])
            if "previous_filename" in item:
                paths.add(item["previous_filename"])
        checks = self._pages(f"commits/{head['sha']}/check-runs?filter=latest", key="check_runs")
        expected_names = {c.name for c in self.required_checks}
        mandatory_names = {c.name for c in self.config.checks if c.required} | {
            "qa",
            "security",
            "acceptance",
        }
        checks_passed = bool(self.required_checks) and mandatory_names <= expected_names
        for expected in self.required_checks:
            candidates = [check for check in checks if check.get("name") == expected.name]
            checks_passed &= len(candidates) == 1 and all(
                check.get("head_sha") == head["sha"]
                and check.get("app", {}).get("id") == expected.app_id
                and check.get("status") == "completed"
                and check.get("conclusion") == "success"
                for check in candidates
            )
        protection_ok = None
        try:
            protection = self._get(f"branches/{quote(base['ref'], safe='')}/protection")
            required = protection.get("required_status_checks") or {}
            pins = {(c.get("context"), c.get("app_id")) for c in required.get("checks", [])}
            protection_ok = (
                required.get("strict") is True
                and protection.get("enforce_admins", {}).get("enabled") is True
                and {(c.name, c.app_id) for c in self.required_checks} <= pins
                and checks_passed
                and pr.get("mergeable") is True
                and pr.get("mergeable_state") == "clean"
            )
        except IntegrationUnavailable:
            pass  # 403, 404, unsupported plan, rulesets-only: remain unknown and block.
        repo = self.transport.request("GET", self.prefix)
        permissions = repo.get("permissions", {})
        # Broad administrator credentials are not suitable for this merger.
        permission_ok = permissions.get("push") is True and permissions.get("admin") is False
        fresh = self.pull_request(number)
        if fresh["head"]["sha"] != head["sha"] or fresh["base"]["sha"] != base["sha"]:
            raise TeamError("PR changed during GitHub evidence collection")
        return PlatformSnapshot(
            self.config.repository,
            head["sha"],
            base["sha"],
            tuple(sorted(paths)),
            protection_ok,
            permission_ok,
            pr.get("state") == "open",
            pr.get("draft") is not False,
            time.time(),
            False,
            # A check-run success alone does not prove an isolated review or criteria coverage.
            # A future collector must verify trusted per-role attestations and workflow provenance.
            integration_verified=False,
        )


class GitHubPRWriter:
    def __init__(
        self,
        config: ProjectConfig,
        transport: GitHubTransport,
        grant: ProjectGrant,
        policy: RuntimePolicy,
        effective_digest: str,
    ):
        self.config, self.transport, self.grant = config, transport, grant
        self.policy, self.effective_digest = policy, effective_digest

    def open(self, *, branch: str, expected_sha: str, title: str, body: str, run_id: str) -> dict:
        _live_permission(
            self.config, self.effective_digest, self.grant, self.policy, "pull_request"
        )
        if not re.fullmatch(r"dt/[A-Za-z0-9][A-Za-z0-9/_-]*", branch):
            raise PermissionDenied("Only controller-owned dt/ branches may be submitted")
        if branch == self.config.base_branch or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
            raise PermissionDenied("Invalid PR branch or commit")
        prefix = f"repos/{self.config.repository}"
        ref = self.transport.request("GET", f"{prefix}/git/ref/heads/{quote(branch, safe='')}")
        if ref["object"]["sha"] != expected_sha:
            raise TeamError("Remote branch moved before PR creation")
        owner = self.config.repository.split("/")[0]
        existing = self.transport.request(
            "GET",
            f"{prefix}/pulls?state=open&head={quote(owner + ':' + branch, safe='')}"
            f"&base={quote(self.config.base_branch, safe='')}&per_page=100",
        )
        marker = f"<!-- developer-team-run:{run_id} -->"
        if existing:
            if len(existing) != 1 or marker not in (existing[0].get("body") or ""):
                raise TeamError("Branch already has an unrelated or ambiguous pull request")
            return existing[0]
        return self.transport.request(
            "POST",
            f"{prefix}/pulls",
            {
                "head": branch,
                "base": self.config.base_branch,
                "title": title,
                "body": body + "\n\n" + marker,
                "draft": False,
                "maintainer_can_modify": False,
            },
        )


class GitHubMerger:
    """No raw merge method: every write goes through the common gate and a fresh SHA check."""

    def __init__(self, reader: GitHubReader, gate: MergeGate):
        self.reader, self.gate = reader, gate

    def merge_if_allowed(
        self,
        *,
        number: int,
        config: ProjectConfig,
        effective_digest: str,
        policy: RuntimePolicy,
        grant: ProjectGrant,
        binding: Binding,
        plan: Plan,
        evidence: list[Evidence],
        developer: str,
        qa: str,
        security: str,
    ) -> dict:
        _live_permission(config, effective_digest, grant, policy, "merge")
        if config != self.reader.config:
            raise PermissionDenied("Merger is bound to a different project")
        snapshot = self.reader.snapshot(number)
        decision = self.gate.evaluate(
            config=config,
            effective_digest=effective_digest,
            policy=policy,
            grant=grant,
            binding=binding,
            plan=plan,
            evidence=evidence,
            snapshot=snapshot,
            developer=developer,
            qa=qa,
            security=security,
        )
        if not decision.allowed:
            raise PermissionDenied("Merge blocked: " + ", ".join(decision.reasons))
        fresh = self.reader.pull_request(number)
        if (
            fresh["head"]["sha"] != binding.head_sha
            or fresh["base"]["sha"] != binding.base_sha
            or fresh["base"]["ref"] != config.base_branch
            or fresh["base"]["repo"]["full_name"] != config.repository
            or fresh["head"]["repo"]["full_name"] != config.repository
            or fresh.get("mergeable") is not True
            or fresh.get("mergeable_state") != "clean"
            or fresh.get("state") != "open"
            or fresh.get("draft") is not False
        ):
            raise PermissionDenied("PR changed after merge approval")
        # Never bypass branch protections, enable auto-merge, or use administrator fallback.
        result = self.reader.transport.request(
            "PUT",
            f"{self.reader.prefix}/pulls/{number}/merge",
            {
                "sha": binding.head_sha,
                "merge_method": config.merge_method,
            },
        )
        if result.get("merged") is not True:
            raise TeamError("GitHub did not confirm a merge; reconcile before retry")
        return result
