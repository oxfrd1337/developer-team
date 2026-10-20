"""One fail-closed merge policy, used by simulated and future live delivery."""

from __future__ import annotations

import re
import time

from .authority import EvidenceAuthority, ProjectGrant, RuntimePolicy
from .config import ConfigError, ProjectConfig, matches
from .models import (
    Binding,
    Evidence,
    GateDecision,
    Origin,
    Outcome,
    PermissionDenied,
    Plan,
    PlatformSnapshot,
    Role,
)


class MergeGate:
    def __init__(self, authority: EvidenceAuthority):
        self.authority = authority

    def evaluate(
        self,
        *,
        config: ProjectConfig,
        effective_digest: str,
        policy: RuntimePolicy,
        grant: ProjectGrant,
        binding: Binding,
        plan: Plan,
        evidence: list[Evidence],
        snapshot: PlatformSnapshot,
        developer: str,
        qa: str,
        security: str,
        now: float | None = None,
    ) -> GateDecision:
        reasons: list[str] = []
        now = time.time() if now is None else now
        if policy.bootstrap:
            reasons.append("bootstrap_requires_manual_merge")
        if config.repository == policy.controller_repository:
            reasons.append("controller_changes_require_manual_merge")
        if not policy.first_release_approved:
            reasons.append("first_release_not_approved")
        if not config.auto_merge or not grant.auto_merge_approved:
            reasons.append("project_auto_merge_not_approved")
        try:
            grant.require(config, "merge", effective_digest)
        except PermissionDenied:
            reasons.append("missing_merge_permission")
        if snapshot.simulated:
            if not policy.safe_test_mode or config.provider != "local":
                reasons.append("simulation_transport_mismatch")
        else:
            if not policy.controller_repository:
                reasons.append("controller_repository_unknown")
            if policy.safe_test_mode:
                reasons.append("safe_test_mode")
            if config.provider != "github" or not snapshot.integration_verified:
                reasons.append("live_integration_unverified")
        if binding.config_digest != effective_digest or binding.plan_digest != plan.digest:
            reasons.append("binding_mismatch")
        if not all(
            re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (binding.head_sha, binding.base_sha)
        ):
            reasons.append("invalid_commit")
        if (
            snapshot.repository != config.repository
            or binding.repository != config.repository
            or snapshot.head_sha != binding.head_sha
            or snapshot.base_sha != binding.base_sha
        ):
            reasons.append("stale_platform_snapshot")
        if not 0 <= now - snapshot.observed_at <= 60:
            reasons.append("platform_snapshot_expired")
        if snapshot.protection_satisfied is not True:
            reasons.append("github_protection_unknown_or_blocked")
        if snapshot.permissions_satisfied is not True:
            reasons.append("platform_permissions_unknown_or_blocked")
        if not snapshot.open or snapshot.draft:
            reasons.append("pull_request_not_ready")
        if len({developer, qa, security}) != 3 or not all((developer, qa, security)):
            reasons.append("review_not_independent")
        if not snapshot.changed_paths:
            reasons.append("changed_paths_missing")
        try:
            if any(config.protected(path) for path in snapshot.changed_paths):
                reasons.append("protected_changes_require_manual_merge")
            if not any(matches(path, config.test_paths) for path in snapshot.changed_paths):
                reasons.append("test_changes_missing")
            if not any(
                matches(path, config.documentation_paths) for path in snapshot.changed_paths
            ):
                reasons.append("documentation_changes_missing")
        except ConfigError:
            reasons.append("invalid_changed_paths")
        criteria = {item.id for item in plan.criteria}
        if not criteria or len(criteria) != len(plan.criteria) or not all(criteria):
            reasons.append("acceptance_criteria_missing_or_ambiguous")

        expected = {
            f"check:{check.name}": (
                Role.QA,
                "local-check-runner" if snapshot.simulated else None,
            )
            for check in config.checks
            if check.required
        }
        expected.update(
            {
                "qa": (Role.QA, qa),
                "security": (Role.SECURITY, security),
                "acceptance": (Role.ORCHESTRATOR, None),
            }
        )
        for kind, (role, issuer) in expected.items():
            records = [record for record in evidence if record.kind == kind]
            if len(records) != 1:
                reasons.append(f"missing_or_duplicate_evidence:{kind}")
                continue
            record = records[0]
            if not self.authority.verify(record):
                reasons.append(f"untrusted_evidence:{kind}")
            if record.role != role or (issuer is not None and record.issuer != issuer):
                reasons.append(f"wrong_evidence_role:{kind}")
            if record.binding != binding:
                reasons.append(f"stale_evidence:{kind}")
            if record.outcome != Outcome.PASS or record.blockers:
                reasons.append(f"failed_or_unknown_evidence:{kind}")
            if not snapshot.simulated and record.origin != Origin.GITHUB:
                reasons.append(f"non_cloud_evidence:{kind}")
            if (
                snapshot.simulated
                and kind.startswith("check:")
                and record.origin != Origin.LOCAL_EXECUTION
            ):
                reasons.append(f"test_execution_unverified:{kind}")
            if kind in ("qa", "acceptance") and set(record.covered_criteria) != criteria:
                reasons.append(f"unmet_acceptance_criteria:{kind}")
        # A stray blocking report may never be hidden by supplying another passing kind.
        for record in evidence:
            if record.kind not in expected or not self.authority.verify(record):
                reasons.append(f"unknown_or_untrusted_evidence:{record.kind}")
            if record.blockers or record.outcome != Outcome.PASS:
                reasons.append(f"blocking_evidence:{record.kind}")
            if record.binding != binding:
                reasons.append(f"stale_evidence:{record.kind}")
        return GateDecision(not reasons, tuple(dict.fromkeys(reasons)))
