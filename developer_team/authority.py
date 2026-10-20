"""Controller-owned authority. None of these grants are read from project code."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from .config import ProjectConfig
from .models import Binding, Evidence, Origin, Outcome, PermissionDenied, Role, digest


@dataclass(frozen=True)
class RuntimePolicy:
    safe_test_mode: bool = True
    first_release_approved: bool = False
    bootstrap: bool = True
    controller_repository: str | None = None


@dataclass(frozen=True)
class ProjectGrant:
    project_id: str
    repository: str
    config_digest: str
    capabilities: frozenset[str] = frozenset()
    auto_merge_approved: bool = False
    approved_by: str = ""
    cloud_environments: tuple[tuple[Role, str], ...] = ()

    def require(self, config: ProjectConfig, capability: str, config_digest: str) -> None:
        if (
            self.project_id != config.id
            or self.repository != config.repository
            or self.config_digest != config_digest
            or capability not in self.capabilities
            or not self.approved_by
        ):
            raise PermissionDenied(f"Project-specific grant missing for {capability}")


@dataclass
class EvidenceAuthority:
    """In-memory receipts for the trusted synthetic driver, not cloud attestations.

    Saved run JSON is audit data only. A fresh process must rerun checks/reviews.
    Live evidence must come from a separately implemented trusted collector.
    """

    issuers: dict[str, tuple[Role, frozenset[Origin]]]
    _receipts: dict[str, Evidence] = field(default_factory=dict, init=False, repr=False)

    def issue(
        self,
        *,
        kind: str,
        issuer: str,
        role: Role,
        origin: Origin,
        binding: Binding,
        outcome: Outcome,
        covered_criteria: tuple[str, ...] = (),
        blockers: tuple[str, ...] = (),
        artifact: object = "",
    ) -> Evidence:
        allowed = self.issuers.get(issuer)
        if allowed is None or allowed[0] != role:
            raise PermissionDenied("Untrusted evidence issuer or wrong role")
        if origin not in self.issuers[issuer][1]:
            raise PermissionDenied("Untrusted evidence origin")
        record = Evidence(
            str(uuid4()),
            kind,
            issuer,
            role,
            origin,
            binding,
            outcome,
            covered_criteria,
            blockers,
            digest(artifact),
        )
        self._receipts[record.id] = record
        return record

    def verify(self, record: Evidence) -> bool:
        return self._receipts.get(record.id) == record and bool(record.artifact_digest)


def synthetic_authority() -> EvidenceAuthority:
    return EvidenceAuthority(
        {
            "synthetic-orchestrator": (Role.ORCHESTRATOR, frozenset({Origin.SIMULATED})),
            "synthetic-developer": (Role.DEVELOPER, frozenset({Origin.SIMULATED})),
            "local-check-runner": (Role.QA, frozenset({Origin.LOCAL_EXECUTION})),
            "synthetic-qa": (Role.QA, frozenset({Origin.SIMULATED})),
            "synthetic-security": (Role.SECURITY, frozenset({Origin.SIMULATED})),
        }
    )
