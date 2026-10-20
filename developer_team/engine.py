"""Durable bounded workflow. DT-001 exposes this driver only for synthetic projects."""

from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from .adapters.base import AgentBackend, AgentContext, DeliveryBackend
from .authority import EvidenceAuthority, ProjectGrant, RuntimePolicy
from .config import ProjectConfig
from .execution import SyntheticCommandRunner
from .gate import MergeGate
from .models import (
    Binding,
    FailureClass,
    Finding,
    IntegrationUnavailable,
    Origin,
    Outcome,
    Role,
    Run,
    RunStatus,
    Stage,
    TeamError,
    digest,
)
from .store import RunStore
from .workspace import GitWorkspace


class Engine:
    def __init__(
        self,
        *,
        config: ProjectConfig,
        workspace: GitWorkspace,
        agents: AgentBackend,
        delivery: DeliveryBackend,
        store: RunStore,
        authority: EvidenceAuthority,
        grant: ProjectGrant,
        policy: RuntimePolicy | None = None,
        runner: SyntheticCommandRunner | None = None,
    ):
        policy = policy or RuntimePolicy()
        if not (
            agents.simulated
            and delivery.simulated
            and config.provider == "local"
            and policy.safe_test_mode
        ):
            raise IntegrationUnavailable(
                "Live end-to-end dispatch is not verified in DT-001. "
                "Implement isolated cloud results and trusted review attestations first."
            )
        self.config, self.workspace, self.agents, self.delivery = (
            config,
            workspace,
            agents,
            delivery,
        )
        self.store, self.authority, self.grant, self.policy = store, authority, grant, policy
        self.runner = runner or SyntheticCommandRunner()
        self.documents, self.effective_digest = workspace.instructions(config)
        self.gate = MergeGate(authority)

    def execute(
        self, requirement: str, *, run_id: str | None = None, pause_before: Stage | None = None
    ) -> Run:
        if not requirement.strip() or len(requirement) > 100_000:
            raise TeamError("A bounded, nonempty requirement is required")
        if run_id is None:
            self.workspace.assert_clean()
            run = Run(
                str(uuid4()),
                self.config.repository,
                self.effective_digest,
                digest(requirement),
                str(self.workspace.root),
                self.workspace.head,
                head_sha=self.workspace.head,
            )
        else:
            run = self.store.load(run_id)
        with self.store.lock(run.id):
            if run_id is not None:
                # Reload AFTER acquiring the lock; never act on a stale pre-lock snapshot.
                run = self.store.load(run.id)
                if run.status not in (RunStatus.PAUSED, RunStatus.RUNNING):
                    return run
                if run.in_flight:
                    return self._stop(
                        run,
                        RunStatus.INTERRUPTED,
                        f"Ambiguous interrupted action: {run.in_flight}",
                        "Inspect the checkout and external task/PR by run ID; reconcile the result "
                        "before starting a new run. No side effect was retried.",
                    )
                if (
                    run.repository != self.config.repository
                    or run.config_digest != self.effective_digest
                    or run.requirement_digest != digest(requirement)
                    or run.workspace != str(self.workspace.root)
                ):
                    return self._stop(
                        run,
                        RunStatus.ESCALATED,
                        "Resume binding mismatch",
                        "Restore the original configuration/requirement or start "
                        "a newly authorized run.",
                    )
                # JSON journal entries are not trusted proofs after a process restart.
                run.evidence = []
                if run.stage in (Stage.QA, Stage.SECURITY, Stage.PULL_REQUEST, Stage.RELEASE):
                    run.stage = Stage.TESTS
            run.status = RunStatus.RUNNING
            self.store.save(run, "start_or_resume")
            context = AgentContext(requirement, self.config, self.documents, self.workspace)
            try:
                self.grant.require(self.config, "read", self.effective_digest)
                identities = {
                    self.agents.developer_identity,
                    self.agents.qa_identity,
                    self.agents.security_identity,
                }
                if len(identities) != 3 or "" in identities:
                    raise TeamError("Development, QA and security identities must be independent")
                self.workspace.assert_clean(run.head_sha)
                while run.status == RunStatus.RUNNING:
                    if run.stage == pause_before:
                        run.status = RunStatus.PAUSED
                        self.store.save(run, "paused")
                        break
                    if run.steps >= self.config.max_steps:
                        return self._stop(
                            run,
                            RunStatus.ESCALATED,
                            "Workflow step limit reached",
                            "Split the requirement and inspect recurring failures.",
                        )
                    run.steps += 1
                    run.in_flight = run.stage.value
                    self.store.save(run, "action_intent")
                    self._step(run, context)
                    run.in_flight = None
                    self.store.save(run, "action_completed")
            except KeyboardInterrupt:
                self._stop(
                    run,
                    RunStatus.INTERRUPTED,
                    "Execution interrupted",
                    "Inspect the action intent and reconcile partial changes before rerun.",
                )
            except Exception as exc:  # A broken adapter must not bypass a gate or retry forever.
                self._stop(
                    run,
                    RunStatus.ESCALATED,
                    f"{type(exc).__name__}: {exc}",
                    "Inspect the failed adapter, grant or tool installation. Reconcile any "
                    "partial side effect before starting a new run.",
                )
            return run

    def _stop(self, run: Run, status: RunStatus, reason: str, suggestion: str) -> Run:
        run.status = status
        run.reasons.append(reason)
        run.suggestions.append(suggestion)
        self.store.save(run, status.value)
        return run

    def _binding(self, run: Run) -> Binding:
        if run.plan is None:
            raise TeamError("Plan missing")
        return Binding(
            run.repository, run.head_sha, run.base_sha, run.config_digest, run.plan.digest, run.id
        )

    def _evidence(
        self,
        run: Run,
        *,
        kind: str,
        issuer: str,
        role: Role,
        origin: Origin,
        outcome: Outcome,
        criteria: tuple[str, ...] = (),
        blockers: tuple[str, ...] = (),
        artifact: object = "",
    ) -> None:
        run.evidence.append(
            self.authority.issue(
                kind=kind,
                issuer=issuer,
                role=role,
                origin=origin,
                binding=self._binding(run),
                outcome=outcome,
                covered_criteria=criteria,
                blockers=blockers,
                artifact=artifact,
            )
        )

    def _repair(self, run: Run, category: FailureClass, findings: tuple[Finding, ...]) -> None:
        run.findings = list(findings)
        if any(not finding.repairable for finding in findings if finding.blocking):
            self._stop(
                run,
                RunStatus.ESCALATED,
                f"Non-repairable {category.value} finding",
                " ".join(f.suggestion for f in findings),
            )
            return
        count = run.repairs.get(category.value, 0)
        if count >= self.config.max_repairs:
            self._stop(
                run,
                RunStatus.ESCALATED,
                f"Repair limit reached: {category.value}",
                " ".join(f.suggestion for f in findings)
                or "Narrow the requirement or fix the underlying toolchain.",
            )
            return
        run.repairs[category.value] = count + 1
        run.evidence = []  # Every correction invalidates ALL checks and reviews.
        run.stage = Stage.DEVELOPMENT
        self.store.save(run, f"repair:{category.value}")

    def _step(self, run: Run, context: AgentContext) -> None:
        if run.stage == Stage.ANALYSIS:
            planning = self.agents.plan(context)
            self.workspace.assert_clean(run.head_sha)
            criteria = [criterion.id for criterion in planning.plan.criteria]
            if not criteria or len(set(criteria)) != len(criteria) or not all(criteria):
                raise TeamError("Orchestrator did not supply unique acceptance criteria")
            if not planning.plan.tasks or not planning.architecture.summary:
                raise TeamError("Planning or architecture analysis is incomplete")
            run.plan, run.architecture = planning.plan, planning.architecture
            run.stage = Stage.ARCHITECTURE
            return
        if run.stage == Stage.ARCHITECTURE:
            # The architect's independent logical output was batched with analysis.
            run.stage = Stage.DEVELOPMENT
            return
        if run.plan is None or run.architecture is None:
            raise TeamError("Cannot execute without plan and architecture")
        if run.stage == Stage.DEVELOPMENT:
            self.grant.require(self.config, "develop", self.effective_digest)
            self.workspace.assert_clean(run.head_sha)
            self.agents.develop(context, run.plan, run.architecture, tuple(run.findings))
            run.head_sha = self.workspace.commit(f"Implement synthetic requirement ({run.id})")
            run.evidence = []
            run.findings = []
            run.stage = Stage.TESTS
            return
        self.workspace.assert_clean(run.head_sha)
        if run.stage == Stage.TESTS:
            failures = []
            for check in self.config.checks:
                result = self.runner.run(check, self.workspace.root)
                self.workspace.assert_clean(run.head_sha)
                if check.required:
                    self._evidence(
                        run,
                        kind=f"check:{check.name}",
                        issuer="local-check-runner",
                        role=Role.QA,
                        origin=Origin.LOCAL_EXECUTION,
                        outcome=result.outcome,
                        artifact=asdict(result),
                    )
                    if result.outcome != Outcome.PASS:
                        failures.append(
                            Finding(
                                FailureClass.TEST,
                                f"check:{check.name}",
                                result.detail,
                                f"Fix {check.name} and rerun every mandatory check.",
                                repairable=result.outcome != Outcome.UNKNOWN,
                            )
                        )
            if failures:
                self._repair(run, FailureClass.TEST, tuple(failures))
            else:
                run.stage = Stage.QA
            return
        if run.stage in (Stage.QA, Stage.SECURITY):
            qa = run.stage == Stage.QA
            review = (self.agents.qa if qa else self.agents.security)(
                context,
                run.plan,
                run.head_sha,
            )
            self.workspace.assert_clean(run.head_sha)
            category = FailureClass.QA if qa else FailureClass.SECURITY
            findings = tuple(f for f in review.findings if f.blocking)
            criteria = {item.id for item in run.plan.criteria}
            if qa and set(review.covered_criteria) != criteria:
                findings += (
                    Finding(
                        category,
                        "unmet-criteria",
                        "Incomplete criterion coverage",
                        "Implement and prove every acceptance criterion.",
                    ),
                )
            if review.outcome != Outcome.PASS and not findings:
                findings = (
                    Finding(
                        category,
                        "review-not-passed",
                        "Review failed or unknown",
                        "Resolve the review and supply concrete evidence.",
                        repairable=review.outcome != Outcome.UNKNOWN,
                    ),
                )
            self._evidence(
                run,
                kind=category.value,
                issuer=self.agents.qa_identity if qa else self.agents.security_identity,
                role=Role.QA if qa else Role.SECURITY,
                origin=Origin.SIMULATED,
                outcome=review.outcome,
                criteria=review.covered_criteria,
                blockers=tuple(f.code for f in findings),
                artifact=asdict(review),
            )
            if findings:
                self._repair(run, category, findings)
            elif qa:
                self._evidence(
                    run,
                    kind="acceptance",
                    issuer="synthetic-orchestrator",
                    role=Role.ORCHESTRATOR,
                    origin=Origin.SIMULATED,
                    outcome=Outcome.PASS,
                    criteria=review.covered_criteria,
                    artifact={"qa": run.evidence[-1].id, "plan": run.plan.digest},
                )
                run.stage = Stage.SECURITY
            else:
                run.stage = Stage.RELEASE if run.pr else Stage.PULL_REQUEST
            return
        if run.stage == Stage.PULL_REQUEST:
            self.grant.require(self.config, "pull_request", self.effective_digest)
            run.pr = self.delivery.open_pull_request(
                run.id,
                run.head_sha,
                run.base_sha,
                f"DT-001 synthetic run {run.id}. Agent actions are SIMULATED. "
                "Includes implementation, tests and documentation; no cloud attestation.",
            )
            if (
                not run.pr.simulated
                or run.pr.repository != run.repository
                or run.pr.head_sha != run.head_sha
                or run.pr.base_sha != run.base_sha
            ):
                raise TeamError("Delivery returned a mismatched pull request")
            run.stage = Stage.RELEASE
            return
        if run.stage == Stage.RELEASE:
            if run.pr is None:
                raise TeamError("Pull request missing")
            snapshot = self.delivery.snapshot(run.pr)
            self.workspace.assert_clean(run.head_sha)
            if set(snapshot.changed_paths) != set(self.workspace.changed_paths(run.base_sha)):
                raise TeamError("Delivery omitted or changed the changed-file list")
            decision = self.gate.evaluate(
                config=self.config,
                effective_digest=self.effective_digest,
                policy=self.policy,
                grant=self.grant,
                binding=self._binding(run),
                plan=run.plan,
                evidence=run.evidence,
                snapshot=snapshot,
                developer=self.agents.developer_identity,
                qa=self.agents.qa_identity,
                security=self.agents.security_identity,
            )
            if not decision.allowed:
                run.status = RunStatus.BLOCKED
                run.reasons = list(decision.reasons)
                run.suggestions = [
                    "Inspect each blocking reason. Keep DT-001 in test mode; first review and "
                    "merge the bootstrap PR manually. Authorize each later project separately.",
                ]
                return
            self.delivery.merge(run.pr, run.head_sha)
            run.stage = Stage.DONE
            run.status = RunStatus.COMPLETED_SIMULATION
            return
        raise TeamError(f"Unsupported stage: {run.stage}")
