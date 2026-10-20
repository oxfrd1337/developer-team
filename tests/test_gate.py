import time
import unittest
from dataclasses import replace
from uuid import uuid4

from developer_team.authority import ProjectGrant, RuntimePolicy, synthetic_authority
from developer_team.config import load_config
from developer_team.gate import MergeGate
from developer_team.models import (
    Binding,
    Criterion,
    Origin,
    Outcome,
    Plan,
    PlatformSnapshot,
    Role,
)

from .support import EXAMPLE


class MergeGateTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(load_config(EXAMPLE), auto_merge=True)
        self.sealed = self.config.digest
        self.policy = RuntimePolicy(first_release_approved=True, bootstrap=False)
        self.grant = ProjectGrant(
            self.config.id,
            self.config.repository,
            self.sealed,
            frozenset({"merge"}),
            True,
            "synthetic-test-driver",
        )
        self.plan = Plan((Criterion("AC-1", "Synthetic acceptance"),), ("Implement",))
        self.binding = Binding(
            self.config.repository, "1" * 40, "2" * 40, self.sealed, self.plan.digest, str(uuid4())
        )
        self.authority = synthetic_authority()
        self.gate = MergeGate(self.authority)
        self.evidence = []
        for kind in ("check:unit", "check:build", "qa", "security", "acceptance"):
            issuer, role, origin = {
                "qa": ("synthetic-qa", Role.QA, Origin.SIMULATED),
                "security": ("synthetic-security", Role.SECURITY, Origin.SIMULATED),
                "acceptance": ("synthetic-orchestrator", Role.ORCHESTRATOR, Origin.SIMULATED),
            }.get(kind, ("local-check-runner", Role.QA, Origin.LOCAL_EXECUTION))
            self.evidence.append(
                self.authority.issue(
                    kind=kind,
                    issuer=issuer,
                    role=role,
                    origin=origin,
                    binding=self.binding,
                    outcome=Outcome.PASS,
                    covered_criteria=("AC-1",),
                    artifact={"kind": kind},
                )
            )
        self.snapshot = PlatformSnapshot(
            self.config.repository,
            self.binding.head_sha,
            self.binding.base_sha,
            ("calculator.py", "tests/test_calculator.py", "README.md"),
            True,
            True,
            True,
            False,
            time.time(),
            True,
        )

    def decide(self, **changes):
        arguments = dict(
            config=self.config,
            effective_digest=self.sealed,
            policy=self.policy,
            grant=self.grant,
            binding=self.binding,
            plan=self.plan,
            evidence=self.evidence,
            snapshot=self.snapshot,
            developer="synthetic-developer",
            qa="synthetic-qa",
            security="synthetic-security",
        )
        return self.gate.evaluate(**(arguments | changes))

    def reissue(self, index, **changes):
        old = self.evidence[index]
        kwargs = dict(
            kind=old.kind,
            issuer=old.issuer,
            role=old.role,
            origin=old.origin,
            binding=old.binding,
            outcome=old.outcome,
            covered_criteria=old.covered_criteria,
            blockers=old.blockers,
            artifact="probe",
        )
        self.evidence[index] = self.authority.issue(**(kwargs | changes))

    def assertBlocked(self, reason, **changes):
        decision = self.decide(**changes)
        self.assertFalse(decision.allowed)
        self.assertIn(reason, decision.reasons)

    def test_complete_explicitly_authorized_simulation_is_eligible(self):
        self.assertTrue(self.decide().allowed)

    def test_controller_repository_cannot_merge_itself_even_with_ordinary_paths(self):
        self.assertBlocked(
            "controller_changes_require_manual_merge",
            policy=replace(self.policy, controller_repository=self.config.repository),
        )

    def test_inconsistent_binding_or_malformed_commit_blocks(self):
        self.assertBlocked("binding_mismatch", effective_digest="different")
        self.assertBlocked("invalid_commit", binding=replace(self.binding, head_sha="unknown"))

    def test_empty_or_duplicate_criteria_block(self):
        for criteria in ((), self.plan.criteria + self.plan.criteria):
            with self.subTest(criteria=criteria):
                self.assertBlocked(
                    "acceptance_criteria_missing_or_ambiguous",
                    plan=replace(self.plan, criteria=criteria),
                )

    def test_no_file_inventory_and_mismatched_simulation_transport_block(self):
        self.assertBlocked(
            "changed_paths_missing", snapshot=replace(self.snapshot, changed_paths=())
        )
        self.assertBlocked(
            "simulation_transport_mismatch", policy=replace(self.policy, safe_test_mode=False)
        )

    def test_wrong_role_cannot_issue_a_review(self):
        self.reissue(2, issuer="synthetic-orchestrator", role=Role.ORCHESTRATOR)
        self.assertBlocked("wrong_evidence_role:qa")

    def test_simulated_test_receipt_cannot_replace_actual_local_execution(self):
        self.reissue(0, issuer="synthetic-qa", origin=Origin.SIMULATED)
        self.assertBlocked("test_execution_unverified:check:unit")

    def test_every_missing_required_proof_blocks(self):
        for index, proof in enumerate(self.evidence):
            with self.subTest(proof=proof.kind):
                self.assertBlocked(
                    f"missing_or_duplicate_evidence:{proof.kind}",
                    evidence=self.evidence[:index] + self.evidence[index + 1 :],
                )

    def test_every_proof_must_match_current_head(self):
        for index, proof in enumerate(self.evidence):
            with self.subTest(proof=proof.kind):
                original = self.evidence[index]
                self.reissue(index, binding=replace(self.binding, head_sha="3" * 40))
                self.assertBlocked(f"stale_evidence:{proof.kind}")
                self.evidence[index] = original

    def test_base_config_plan_and_run_changes_each_invalidate_proof(self):
        changes = [
            dict(base_sha="3" * 40),
            dict(config_digest="4" * 64),
            dict(plan_digest="5" * 64),
            dict(run_id=str(uuid4())),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.reissue(2, binding=replace(self.binding, **change))
                self.assertBlocked("stale_evidence:qa")

    def test_unknown_or_failed_review_never_counts_as_pass(self):
        for outcome in (Outcome.UNKNOWN, Outcome.FAIL):
            with self.subTest(outcome=outcome):
                self.reissue(2, outcome=outcome)
                self.assertBlocked("failed_or_unknown_evidence:qa")

    def test_a_forged_passing_receipt_is_rejected(self):
        forged = replace(self.evidence[2], id=str(uuid4()))
        self.assertBlocked(
            "untrusted_evidence:qa", evidence=self.evidence[:2] + [forged] + self.evidence[3:]
        )

    def test_duplicate_proofs_are_ambiguous(self):
        self.assertBlocked(
            "missing_or_duplicate_evidence:qa", evidence=self.evidence + [self.evidence[2]]
        )

    def test_unknown_extra_evidence_blocks(self):
        self.reissue(2, kind="surprise")
        self.assertBlocked("unknown_or_untrusted_evidence:surprise")

    def test_passing_status_does_not_hide_blocking_finding(self):
        self.reissue(3, blockers=("credential-leak",))
        self.assertBlocked("failed_or_unknown_evidence:security")

    def test_qa_and_orchestrator_must_cover_all_acceptance_criteria(self):
        for index in (2, 4):
            with self.subTest(index=index):
                original = self.evidence[index]
                self.reissue(index, covered_criteria=())
                self.assertBlocked(f"unmet_acceptance_criteria:{original.kind}")
                self.evidence[index] = original

    def test_project_authorization_cannot_be_inferred_from_project_file(self):
        for grant, reason in (
            (replace(self.grant, auto_merge_approved=False), "project_auto_merge_not_approved"),
            (replace(self.grant, project_id="other"), "missing_merge_permission"),
            (replace(self.grant, repository="synthetic/other"), "missing_merge_permission"),
            (replace(self.grant, config_digest="other"), "missing_merge_permission"),
            (replace(self.grant, approved_by=""), "missing_merge_permission"),
            (replace(self.grant, capabilities=frozenset()), "missing_merge_permission"),
        ):
            with self.subTest(reason=reason, grant=grant):
                self.assertBlocked(reason, grant=grant)

    def test_bootstrap_and_first_activation_each_block_independently(self):
        self.assertBlocked(
            "bootstrap_requires_manual_merge", policy=replace(self.policy, bootstrap=True)
        )
        self.assertBlocked(
            "first_release_not_approved", policy=replace(self.policy, first_release_approved=False)
        )

    def test_independent_roles_are_mandatory(self):
        self.assertBlocked("review_not_independent", qa="synthetic-developer")
        self.assertBlocked("review_not_independent", security="synthetic-qa")

    def test_unknown_permissions_or_github_protection_block(self):
        for field, reason in (
            ("protection_satisfied", "github_protection_unknown_or_blocked"),
            ("permissions_satisfied", "platform_permissions_unknown_or_blocked"),
        ):
            for value in (False, None, 1):
                with self.subTest(field=field, value=value):
                    self.assertBlocked(reason, snapshot=replace(self.snapshot, **{field: value}))

    def test_stale_or_future_snapshot_blocks(self):
        for observed in (time.time() - 61, time.time() + 10):
            self.assertBlocked(
                "platform_snapshot_expired", snapshot=replace(self.snapshot, observed_at=observed)
            )

    def test_draft_and_closed_pull_requests_block(self):
        self.assertBlocked("pull_request_not_ready", snapshot=replace(self.snapshot, draft=True))
        self.assertBlocked("pull_request_not_ready", snapshot=replace(self.snapshot, open=False))

    def test_control_and_security_changes_never_self_approve(self):
        for path in (
            "AGENTS.md",
            "src/AGENTS.md",
            "SECURITY.md",
            ".github/workflows/ci.yml",
            ".developer-team/project.toml",
            "automation/gate.py",
        ):
            with self.subTest(path=path):
                self.assertBlocked(
                    "protected_changes_require_manual_merge",
                    snapshot=replace(
                        self.snapshot,
                        changed_paths=self.snapshot.changed_paths + (path,),
                    ),
                )

    def test_implementation_tests_and_documentation_are_a_single_bundle(self):
        self.assertBlocked(
            "test_changes_missing",
            snapshot=replace(
                self.snapshot,
                changed_paths=("calculator.py", "README.md"),
            ),
        )
        self.assertBlocked(
            "documentation_changes_missing",
            snapshot=replace(
                self.snapshot,
                changed_paths=("calculator.py", "tests/test_calculator.py"),
            ),
        )

    def test_invalid_changed_paths_fail_closed(self):
        for path in ("../gate.py", "/etc/hosts", "src\\gate.py"):
            with self.subTest(path=path):
                self.assertBlocked(
                    "invalid_changed_paths",
                    snapshot=replace(
                        self.snapshot,
                        changed_paths=(path,),
                    ),
                )

    def test_simulated_proofs_can_never_authorize_live_merge(self):
        config = replace(self.config, provider="github")
        self.assertBlocked(
            "safe_test_mode", config=config, snapshot=replace(self.snapshot, simulated=False)
        )
        self.assertBlocked(
            "live_integration_unverified",
            config=config,
            policy=replace(self.policy, safe_test_mode=False),
            snapshot=replace(self.snapshot, simulated=False),
        )
        self.assertBlocked(
            "non_cloud_evidence:qa",
            config=config,
            policy=replace(self.policy, safe_test_mode=False),
            snapshot=replace(self.snapshot, simulated=False, integration_verified=True),
        )


if __name__ == "__main__":
    unittest.main()
