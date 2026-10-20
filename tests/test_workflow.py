import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from developer_team.adapters.synthetic import REQUIREMENT, SyntheticAgents
from developer_team.authority import RuntimePolicy, synthetic_authority
from developer_team.cli import main
from developer_team.engine import Engine
from developer_team.execution import SyntheticCommandRunner
from developer_team.models import IntegrationUnavailable, Outcome, RunStatus, Stage

from .support import EXAMPLE, harness


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_full_cycle_uses_real_checks_and_only_simulates_merge(self):
        engine, workspace, agents, delivery, store = harness(self.path, simulate_activation=True)
        initial = workspace.head
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.COMPLETED_SIMULATION)
        self.assertNotEqual(initial, run.head_sha)
        self.assertEqual(delivery.merge_calls, 1)
        self.assertEqual(agents.calls, ["orchestrator+architect", "developer", "qa", "security"])
        self.assertTrue(all(e.outcome == Outcome.PASS for e in run.evidence))
        self.assertEqual(len(run.evidence), 5)
        self.assertTrue(all(e.binding.head_sha == run.head_sha for e in run.evidence))
        self.assertEqual(store.load(run.id), run)
        self.assertIn("action_intent", [e["kind"] for e in store.events(run.id)])
        self.assertEqual(workspace.git("rev-parse", "main"), initial)
        changed = workspace.changed_paths(initial)
        self.assertIn("tests/test_calculator.py", changed)
        self.assertIn("README.md", changed)

    def test_bootstrap_never_merges(self):
        engine, _, _, delivery, _ = harness(self.path)
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.BLOCKED)
        self.assertIsNotNone(run.pr)
        self.assertIn("bootstrap_requires_manual_merge", run.reasons)
        self.assertEqual(delivery.merge_calls, 0)

    def test_test_failure_is_repaired_and_reverified(self):
        engine, _, agents, delivery, store = harness(
            self.path, "test-fix", simulate_activation=True
        )
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.COMPLETED_SIMULATION)
        self.assertEqual(run.repairs, {"test": 1})
        self.assertEqual(agents.developments, 2)
        self.assertEqual(agents.calls.count("qa"), 1)
        self.assertEqual(delivery.merge_calls, 1)
        self.assertIn("repair:test", [e["kind"] for e in store.events(run.id)])

    def test_qa_catches_a_case_developer_tests_missed(self):
        engine, _, agents, _, _ = harness(self.path, "qa-fix", simulate_activation=True)
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.COMPLETED_SIMULATION)
        self.assertEqual(run.repairs, {"qa": 1})
        self.assertEqual(agents.calls.count("qa"), 2)
        self.assertEqual(agents.calls.count("security"), 1)

    def test_failed_qa_has_exactly_three_corrections_no_pr(self):
        engine, _, agents, delivery, _ = harness(self.path, "qa-fail", simulate_activation=True)
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertEqual(run.repairs, {"qa": 3})
        self.assertEqual(agents.developments, 4)
        self.assertEqual(agents.calls.count("qa"), 4)
        self.assertEqual(agents.calls.count("security"), 0)
        self.assertEqual(delivery.pr_calls, 0)
        self.assertEqual(delivery.merge_calls, 0)
        self.assertTrue(run.suggestions)

    def test_security_fix_reruns_qa_and_all_checks(self):
        engine, _, agents, _, _ = harness(self.path, "security-fix", simulate_activation=True)
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.COMPLETED_SIMULATION)
        self.assertEqual(run.repairs, {"security": 1})
        self.assertEqual(agents.calls.count("qa"), 2)
        self.assertEqual(agents.calls.count("security"), 2)

    def test_nonrepairable_security_conflict_stops_without_loop(self):
        engine, _, agents, delivery, _ = harness(self.path, "security-conflict")
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertEqual(agents.developments, 1)
        self.assertEqual(run.repairs, {})
        self.assertEqual(delivery.pr_calls, 0)

    def test_test_correction_budget_is_bounded(self):
        engine, _, agents, delivery, _ = harness(
            self.path, "repair-limit", simulate_activation=True
        )
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertEqual(run.repairs, {"test": 3})
        self.assertEqual(agents.developments, 4)
        self.assertEqual(delivery.merge_calls, 0)
        self.assertNotIn("qa", agents.calls)

    def test_missing_development_permission_prevents_writes(self):
        engine, workspace, agents, delivery, _ = harness(
            self.path,
            capabilities=frozenset({"read", "pull_request"}),
        )
        initial = workspace.head
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertEqual(workspace.head, initial)
        self.assertEqual(agents.developments, 0)
        self.assertEqual(delivery.pr_calls, 0)

    def test_missing_pr_permission_prevents_delivery(self):
        engine, _, _, delivery, _ = harness(self.path, capabilities=frozenset({"read", "develop"}))
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertEqual(delivery.pr_calls, 0)

    def test_changed_controls_cannot_self_approve(self):
        engine, _, _, delivery, _ = harness(self.path, "protected-change", simulate_activation=True)
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.BLOCKED)
        self.assertIn("protected_changes_require_manual_merge", run.reasons)
        self.assertEqual(delivery.merge_calls, 0)

    def test_stale_platform_head_blocks_release(self):
        engine, _, _, delivery, _ = harness(self.path, "stale-evidence", simulate_activation=True)
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.BLOCKED)
        self.assertIn("stale_platform_snapshot", run.reasons)
        self.assertEqual(delivery.merge_calls, 0)

    def test_interrupt_does_not_retry_or_open_pr(self):
        engine, _, agents, delivery, _ = harness(self.path, "interrupted")
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.INTERRUPTED)
        engine.execute(REQUIREMENT, run_id=run.id)
        self.assertEqual(agents.developments, 1)
        self.assertEqual(delivery.pr_calls, 0)

    def test_restart_with_ambiguous_intent_stops_without_repeating_effect(self):
        engine, _, agents, delivery, store = harness(self.path)
        run = engine.execute(REQUIREMENT, pause_before=Stage.DEVELOPMENT)
        run.status, run.in_flight = RunStatus.RUNNING, "development"
        store.save(run, "simulate_process_crash_after_intent")
        recovered = engine.execute(REQUIREMENT, run_id=run.id)
        self.assertEqual(recovered.status, RunStatus.INTERRUPTED)
        self.assertEqual(agents.developments, 0)
        self.assertEqual(delivery.pr_calls, 0)

    def test_resume_discards_saved_proofs_and_does_not_duplicate_pr(self):
        engine, workspace, agents, delivery, store = harness(self.path, simulate_activation=True)
        run = engine.execute(REQUIREMENT, pause_before=Stage.RELEASE)
        old_ids = {e.id for e in run.evidence}
        new_engine = Engine(
            config=engine.config,
            workspace=workspace,
            agents=agents,
            delivery=delivery,
            store=store,
            authority=synthetic_authority(),
            grant=engine.grant,
            policy=engine.policy,
        )
        resumed = new_engine.execute(REQUIREMENT, run_id=run.id)
        self.assertEqual(resumed.status, RunStatus.COMPLETED_SIMULATION)
        self.assertFalse(old_ids & {e.id for e in resumed.evidence})
        self.assertEqual(delivery.pr_calls, 1)
        self.assertEqual(agents.developments, 1)
        self.assertEqual(agents.calls.count("qa"), 2)

    def test_resume_rejects_changed_requirement(self):
        engine, _, agents, _, _ = harness(self.path)
        run = engine.execute(REQUIREMENT, pause_before=Stage.DEVELOPMENT)
        result = engine.execute(REQUIREMENT + " changed", run_id=run.id)
        self.assertEqual(result.status, RunStatus.ESCALATED)
        self.assertEqual(agents.developments, 0)

    def test_review_that_mutates_code_invalidates_proofs(self):
        class MutatingQA(SyntheticAgents):
            def qa(self, context, plan, head_sha):
                review = super().qa(context, plan, head_sha)
                context.workspace.write("calculator.py", "raise RuntimeError('unreviewed')\n")
                return review

        engine, _, _, delivery, _ = harness(self.path, agents=MutatingQA())
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertEqual(delivery.merge_calls, 0)

    def test_unavailable_test_executable_does_not_trigger_code_corrections(self):
        class Unavailable(SyntheticCommandRunner):
            def run(self, check, root):
                return super().run(replace(check, argv=("/nonexistent/dt-tool",)), root)

        engine, _, agents, _, _ = harness(self.path, runner=Unavailable())
        run = engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertEqual(agents.developments, 1)
        self.assertEqual(run.repairs, {})

    def test_live_driver_cannot_be_enabled_by_changing_policy(self):
        engine, workspace, agents, delivery, store = harness(self.path)
        with self.assertRaises(IntegrationUnavailable):
            Engine(
                config=engine.config,
                workspace=workspace,
                agents=agents,
                delivery=delivery,
                store=store,
                authority=synthetic_authority(),
                grant=engine.grant,
                policy=RuntimePolicy(
                    safe_test_mode=False, first_release_approved=True, bootstrap=False
                ),
            )

    def test_cli_demo_retains_auditable_artifacts_with_no_real_remote_writes(self):
        code = main(
            ["demo", "--config", str(EXAMPLE), "--scenario", "test-fix", "--output", str(self.path)]
        )
        self.assertEqual(code, 0)
        report = json.loads((self.path / "report.json").read_text())
        self.assertFalse(report["cloud_execution_verified"])
        self.assertEqual(report["real_remote_mutations"], 0)
        self.assertEqual(report["simulated_merge_calls"], 0)
        self.assertEqual(report["run"]["repairs"], {"test": 1})


if __name__ == "__main__":
    unittest.main()
