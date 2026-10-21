"""Immutable contracts shared by interchangeable agent and platform adapters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Role(str, Enum):
    ORCHESTRATOR = "orchestrator"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    QA = "qa"
    SECURITY = "security"


class FailureClass(str, Enum):
    IMPLEMENTATION = "implementation"
    TEST = "test"
    QA = "qa"
    SECURITY = "security"


class Origin(str, Enum):
    SIMULATED = "simulated"
    LOCAL_EXECUTION = "local_execution"
    GITHUB = "github"
    CODEX_CLOUD = "codex_cloud"  # Task-bound agent output, not an execution attestation.


class Outcome(str, Enum):
    PASS = "pass"  # noqa: S105 -- outcome label, not a credential
    FAIL = "fail"
    UNKNOWN = "unknown"


class Stage(str, Enum):
    ANALYSIS = "analysis"
    ARCHITECTURE = "architecture"
    DEVELOPMENT = "development"
    TESTS = "tests"
    QA = "qa"
    SECURITY = "security"
    PULL_REQUEST = "pull_request"
    RELEASE = "release"
    DONE = "done"


class RunStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    ESCALATED = "escalated"
    INTERRUPTED = "interrupted"
    BLOCKED = "blocked"
    COMPLETED_SIMULATION = "completed_simulation"


@dataclass(frozen=True)
class Criterion:
    id: str
    description: str


@dataclass(frozen=True)
class Plan:
    criteria: tuple[Criterion, ...]
    tasks: tuple[str, ...]

    @property
    def digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class Architecture:
    summary: str
    dependencies: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Planning:
    """Two logical roles can share one planning call; reviews never share development."""

    plan: Plan
    architecture: Architecture


@dataclass(frozen=True)
class Finding:
    category: FailureClass
    code: str
    message: str
    suggestion: str
    blocking: bool = True
    repairable: bool = True


@dataclass(frozen=True)
class Review:
    outcome: Outcome
    covered_criteria: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class Binding:
    repository: str
    head_sha: str
    base_sha: str
    config_digest: str
    plan_digest: str
    run_id: str


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    issuer: str
    role: Role
    origin: Origin
    binding: Binding
    outcome: Outcome
    covered_criteria: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    artifact_digest: str = ""


@dataclass(frozen=True)
class CheckResult:
    name: str
    outcome: Outcome
    returncode: int | None
    output_digest: str
    detail: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    repository: str
    head_sha: str
    base_sha: str
    url: str
    simulated: bool


@dataclass(frozen=True)
class PlatformSnapshot:
    repository: str
    head_sha: str
    base_sha: str
    changed_paths: tuple[str, ...]
    protection_satisfied: bool | None
    permissions_satisfied: bool | None
    open: bool
    draft: bool
    observed_at: float
    simulated: bool
    integration_verified: bool = False


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass
class Run:
    id: str
    repository: str
    config_digest: str
    requirement_digest: str
    workspace: str
    base_sha: str
    stage: Stage = Stage.ANALYSIS
    status: RunStatus = RunStatus.RUNNING
    head_sha: str = ""
    plan: Plan | None = None
    architecture: Architecture | None = None
    repairs: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    pr: PullRequest | None = None
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    in_flight: str | None = None
    steps: int = 0


class TeamError(Exception):
    """An expected failure that must stop the workflow safely."""


class PermissionDenied(TeamError):
    pass


class IntegrationUnavailable(TeamError):
    pass


class CloudPending(TeamError):
    """A known task needs another bounded, read-only poll; never resubmit it."""
