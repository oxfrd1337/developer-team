from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..config import ProjectConfig
from ..models import Architecture, Finding, Plan, Planning, PlatformSnapshot, PullRequest, Review
from ..workspace import GitWorkspace


@dataclass(frozen=True)
class AgentContext:
    requirement: str
    config: ProjectConfig
    instructions: dict[str, str]
    workspace: GitWorkspace


class AgentBackend(Protocol):
    developer_identity: str
    qa_identity: str
    security_identity: str
    simulated: bool

    def plan(self, context: AgentContext) -> Planning: ...

    def develop(
        self,
        context: AgentContext,
        plan: Plan,
        architecture: Architecture,
        findings: tuple[Finding, ...],
    ) -> None: ...

    def qa(self, context: AgentContext, plan: Plan, head_sha: str) -> Review: ...

    def security(self, context: AgentContext, plan: Plan, head_sha: str) -> Review: ...


class DeliveryBackend(Protocol):
    simulated: bool

    def open_pull_request(
        self, run_id: str, head_sha: str, base_sha: str, body: str
    ) -> PullRequest: ...

    def snapshot(self, pr: PullRequest) -> PlatformSnapshot: ...

    def merge(self, pr: PullRequest, expected_sha: str) -> None: ...
