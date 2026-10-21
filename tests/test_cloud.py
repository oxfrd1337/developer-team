import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from developer_team.adapters.cloud_agents import CodexCloudAgents, cloud_authority
from developer_team.adapters.cloud_contracts import strict_json
from developer_team.adapters.codex_cloud import CodexCloudGateway, run_cli
from developer_team.adapters.github import GitHubCloudRefs
from developer_team.adapters.synthetic import REQUIREMENT
from developer_team.engine import Engine
from developer_team.models import (
    CloudPending,
    IntegrationUnavailable,
    Origin,
    PermissionDenied,
    Role,
    RunStatus,
    TeamError,
)
from developer_team.store import RunStore
from tests.cloud_support import cloud_harness, patch_for


class CloudLifecycleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.engine, self.cli, self.gateway, self.refs, self.clock, self.kwargs, self.context) = (
            cloud_harness(self.root)
        )
        self.job = self.kwargs["job"]
        self.approval = self.kwargs["approval"]

    def submit(self, **changes):
        return self.gateway.submit(**(self.kwargs | changes))

    def collect(self):
        return self.gateway.collect(self.job, self.approval)

    def test_successful_task_is_bound_and_result_is_not_attested(self):
        receipt = self.submit()
        self.assertFalse(receipt.verified_execution)
        patch_text = self.collect()
        self.assertIn(self.job.id, patch_text)
        record = self.gateway.store.cloud_task(self.job.id)
        self.assertEqual(record["task_id"], receipt.task_id)
        self.assertEqual(record["state"], "ready")
        self.assertTrue(record["result_digest"])
        self.assertEqual(
            self.cli.submissions[0][self.cli.submissions[0].index("--attempts") + 1], "1"
        )

    def test_failed_task_is_terminal_without_new_submission(self):
        self.cli.status = "error"
        self.submit()
        with self.assertRaisesRegex(TeamError, "failed"):
            self.collect()
        self.clock.advance()
        with self.assertRaises(TeamError):
            self.collect()
        self.assertEqual(len(self.cli.submissions), 1)

    def test_status_applied_outside_controller_blocks(self):
        self.cli.status = "applied"
        self.submit()
        with self.assertRaises(TeamError):
            self.collect()

    def test_read_timeout_resumes_same_task_after_process_restart(self):
        receipt = self.submit()
        self.cli.read_failure = IntegrationUnavailable("Controlled timeout")
        with self.assertRaises(CloudPending):
            self.collect()
        store = RunStore(self.gateway.store.path)
        gateway = CodexCloudGateway(self.cli, store=store, refs=self.refs, now=self.clock)
        self.clock.advance()
        second = gateway.submit(**self.kwargs)
        self.assertEqual(second.task_id, receipt.task_id)
        self.assertIn(self.job.id, gateway.collect(self.job, self.approval))
        self.assertEqual(len(self.cli.submissions), 1)

    def test_ambiguous_submit_is_never_repeated(self):
        self.cli.submit_failure = IntegrationUnavailable("Submit timed out")
        with self.assertRaises(IntegrationUnavailable):
            self.submit()
        self.cli.submit_failure = None
        with self.assertRaisesRegex(TeamError, "Ambiguous"):
            self.submit()
        self.assertEqual(len(self.cli.submissions), 1)

    def test_unknown_receipt_never_resubmits(self):
        self.cli.receipt = "Accepted; response changed"
        with self.assertRaises(IntegrationUnavailable):
            self.submit()
        with self.assertRaises(TeamError):
            self.submit()
        self.assertEqual(len(self.cli.submissions), 1)

    def test_duplicate_submission_returns_same_task(self):
        first = self.submit()
        self.assertEqual(self.submit(), first)
        self.assertEqual(len(self.cli.submissions), 1)
        with self.assertRaisesRegex(TeamError, "Conflicting duplicate"):
            self.submit(prompt="Changed content under the same job ID")

    def test_task_id_cannot_be_reused_for_another_role(self):
        receipt = self.submit()
        job = replace(self.job, role=Role.QA)
        self.cli.receipt = f"https://chatgpt.com/codex/tasks/{receipt.task_id}"
        with self.assertRaisesRegex(TeamError, "reused"):
            self.submit(job=job, role=job.role, branch=job.branch)

    def test_stale_commit_blocks_submission_and_collection(self):
        self.refs.stale = True
        with self.assertRaisesRegex(TeamError, "Stale"):
            self.submit()
        self.assertFalse(self.cli.submissions)

    def test_commit_moves_after_submission_blocks_result(self):
        self.submit()
        self.refs.stale = True
        with self.assertRaises(TeamError):
            self.collect()

    def test_missing_or_expired_approval_does_not_start_task(self):
        for approval in (
            None,
            replace(self.approval, expires_at=self.clock()),
            replace(self.approval, repository="other/project"),
        ):
            with self.subTest(approval=approval), self.assertRaises(PermissionDenied):
                self.submit(approval=approval)
        self.assertFalse(self.cli.calls)

    def test_invalid_task_budget_and_missing_permissions_block_before_cli(self):
        for approval in (
            replace(self.approval, max_tasks=True),
            replace(self.approval, max_polls=0),
        ):
            with self.subTest(approval=approval), self.assertRaises(PermissionDenied):
                self.submit(approval=approval)
        with self.assertRaises(PermissionDenied):
            self.submit(grant=replace(self.kwargs["grant"], capabilities=frozenset()))
        self.assertFalse(self.cli.calls)

    def test_shared_review_environments_block(self):
        grant = replace(
            self.kwargs["grant"], cloud_environments=tuple((r, "same-env") for r in Role)
        )
        with self.assertRaises(PermissionDenied):
            self.submit(grant=grant)
        self.assertFalse(self.cli.calls)

    def test_deadline_and_poll_limit_stop_without_claiming_remote_cancellation(self):
        self.submit()
        self.clock.advance(self.approval.task_timeout_seconds)
        with self.assertRaisesRegex(TeamError, "cancellation unavailable"):
            self.collect()
        self.assertEqual(self.gateway.store.cloud_task(self.job.id)["state"], "timed_out")
        self.assertEqual(len(self.cli.submissions), 1)

    def test_polling_is_rate_limited(self):
        self.cli.status = "pending"
        self.submit()
        with self.assertRaises(CloudPending):
            self.collect()
        calls = len(self.cli.calls)
        with self.assertRaises(CloudPending):
            self.collect()
        self.assertEqual(len(self.cli.calls), calls)
        self.assertEqual(self.gateway.store.cloud_task(self.job.id)["polls"], 1)

    def test_deadline_is_rechecked_after_slow_result_download(self):
        self.submit()

        def delayed(envelope):
            self.clock.advance(self.approval.task_timeout_seconds)
            return envelope

        self.cli.mutate = delayed
        with self.assertRaisesRegex(TeamError, "deadline reached"):
            self.collect()
        self.assertEqual(self.gateway.store.cloud_task(self.job.id)["state"], "timed_out")

    def test_read_retries_are_bounded(self):
        self.submit()
        for _ in range(self.approval.max_read_errors):
            self.cli.read_failure = IntegrationUnavailable("Timeout")
            with self.assertRaises(CloudPending):
                self.collect()
            self.clock.advance()
        self.cli.read_failure = IntegrationUnavailable("Timeout")
        with self.assertRaisesRegex(TeamError, "retry budget exhausted"):
            self.collect()

    def test_missing_duplicate_or_foreign_task_metadata_blocks(self):
        self.submit()
        for listing in (
            {"tasks": [], "cursor": None},
            {"tasks": {}, "cursor": None},
            {"tasks": [], "cursor": "repeated"},
        ):
            self.cli.list_override = json.dumps(listing)
            with self.subTest(listing=listing), self.assertRaises(TeamError):
                self.collect()
            self.clock.advance()
        self.cli.list_override = None
        self.cli.duplicate_metadata = True
        with self.assertRaisesRegex(TeamError, "duplicate"):
            self.collect()

    def test_stale_timestamp_wrong_environment_and_multiple_attempts_block(self):
        receipt = self.submit()
        task = self.cli.tasks[receipt.task_id]
        task["created_at"] = self.clock() - 100
        with self.assertRaisesRegex(TeamError, "provenance"):
            self.collect()

    def test_conflicting_statuses_block(self):
        self.submit()
        original = self.gateway.status
        self.gateway.status = lambda _: "[PENDING] Conflicting provider result"
        with self.assertRaisesRegex(TeamError, "conflicting"):
            self.collect()
        self.gateway.status = original

    def test_wrong_environment_or_missing_attempt_information_blocks(self):
        self.submit()
        for update in (
            {"environment_id": "foreign-environment"},
            {"attempt_total": None},
            {"attempt_total": 2},
            {"attempt_total": True},
            {"updated_at": "2026-10-21T00:00:00"},
        ):
            self.cli.metadata_overrides = update
            with self.subTest(update=update), self.assertRaises(TeamError):
                self.collect()
            self.clock.advance()

    def test_limits_cannot_be_increased_or_reset_during_resume(self):
        self.submit()
        with self.assertRaisesRegex(TeamError, "approval changed"):
            self.gateway.collect(self.job, replace(self.approval, max_tasks=100))
        self.clock.advance(self.approval.runtime_seconds)
        with self.assertRaisesRegex(TeamError, "runtime limit"):
            self.submit()

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(TeamError):
            strict_json('{"outcome":"fail","outcome":"pass"}')

    def test_changed_result_is_rejected(self):
        self.submit()
        self.collect()
        self.clock.advance()
        self.cli.mutate = lambda e: e | {"extra": True}
        with self.assertRaisesRegex(TeamError, "changed after"):
            self.collect()

    def test_pending_status_exit_one_is_a_valid_cli_observation(self):
        # Exercise the real process wrapper with a controlled executable, no network.
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "codex"
            binary.write_text('#!/bin/sh\nprintf "[PENDING] fixture\\n"\nexit 1\n')
            binary.chmod(0o700)
            import os

            with patch.dict(os.environ, {"PATH": directory}):
                self.assertTrue(
                    run_cli(["codex", "cloud", "status", "task_fixture"]).startswith("[PENDING]")
                )


class CloudEngineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.engine, self.cli, self.gateway, self.refs, self.clock, self.kwargs, self.context) = (
            cloud_harness(self.root)
        )

    def test_existing_engine_coordinates_five_roles_and_blocks_merge(self):
        with patch.object(
            self.engine.delivery, "merge", side_effect=AssertionError("must not merge")
        ) as merge:
            run = self.engine.execute(REQUIREMENT)
            self.assertEqual(run.status, RunStatus.BLOCKED, run.reasons)
            merge.assert_not_called()
        self.assertIn("cloud_pilot_requires_manual_merge", run.reasons)
        self.assertIn("live_integration_unverified", run.reasons)
        roles = [task["role"] for task in self.cli.tasks.values()]
        self.assertEqual(roles, [Role.ORCHESTRATOR, Role.DEVELOPER, Role.QA, Role.SECURITY])
        self.assertEqual(len({task["environment"] for task in self.cli.tasks.values()}), 4)
        jobs = self.gateway.store.cloud_tasks(run.id)
        self.assertEqual(len({job["task_id"] for job in jobs}), 4)
        self.assertTrue(
            all(
                job["job"]["head_sha"] == run.head_sha
                for job in jobs
                if job["job"]["role"] in ("qa", "security")
            )
        )
        self.assertIn("existing architecture", self.cli.submissions[0][-1])
        check_evidence = [e for e in run.evidence if e.kind.startswith("check:")]
        self.assertTrue(check_evidence)
        self.assertTrue(all(e.origin == Origin.LOCAL_EXECUTION for e in check_evidence))
        self.assertTrue(
            all(
                e.origin == Origin.CODEX_CLOUD
                for e in run.evidence
                if not e.kind.startswith("check:")
            )
        )
        self.assertEqual(run.pr.number, 0)  # A handoff preview, not a real PR.
        self.assertEqual(self.engine.execute(REQUIREMENT).status, RunStatus.BLOCKED)
        self.assertEqual(len(self.cli.submissions), 4)

    def test_wait_resumes_without_duplicate_submission_or_step_charge(self):
        self.cli.status = "pending"
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.PAUSED)
        self.assertEqual(run.steps, 0)
        for _ in range(3):
            run = self.engine.execute(REQUIREMENT, run_id=run.id)
            self.assertEqual(run.status, RunStatus.PAUSED)
        self.assertEqual(len(self.cli.submissions), 1)
        self.clock.advance()
        self.cli.status = "ready"
        run = self.engine.execute(REQUIREMENT, run_id=run.id)
        self.assertEqual(run.status, RunStatus.BLOCKED, run.reasons)
        self.assertEqual(len(self.cli.submissions), 4)

    def test_pending_review_survives_new_controller_and_fresh_evidence_authority(self):
        self.cli.status_by_role[Role.SECURITY] = "pending"
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.PAUSED)
        self.assertEqual(len(self.cli.submissions), 4)
        store = RunStore(self.engine.store.path)
        gateway = CodexCloudGateway(self.cli, store=store, refs=self.refs, now=self.clock)
        agents = CodexCloudAgents(
            gateway, self.engine.agents.approval, self.engine.grant, self.engine.policy
        )
        restarted = Engine(
            config=self.engine.config,
            workspace=self.engine.workspace,
            agents=agents,
            delivery=self.engine.delivery,
            store=store,
            authority=cloud_authority(self.engine.grant),
            grant=self.engine.grant,
            policy=self.engine.policy,
        )
        self.clock.advance()
        self.cli.status_by_role[Role.SECURITY] = "ready"
        resumed = restarted.execute(REQUIREMENT, run_id=run.id)
        self.assertEqual(resumed.status, RunStatus.BLOCKED, resumed.reasons)
        self.assertEqual(len(self.cli.submissions), 4)
        self.assertTrue(all(restarted.authority.verify(e) for e in resumed.evidence))

    def test_bad_result_import_never_mutates_workspace(self):
        head = self.engine.workspace.head
        self.cli.mutate = lambda e: e | {"binding": e["binding"] | {"head_sha": "0" * 40}}
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertIn("binding", " ".join(run.reasons))
        self.engine.workspace.assert_clean(head)

    def test_review_cannot_import_source_changes(self):
        self.cli.extra_review_patch = patch_for("injected.py", None, "raise RuntimeError\n")
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertFalse((self.engine.workspace.root / "injected.py").exists())

    def test_contradictory_pass_is_rejected(self):
        self.cli.mutate = (
            lambda e: e | {"payload": e["payload"] | {"covered_criteria": []}}
            if e["binding"]["role"] == "qa"
            else e
        )
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertIn("Contradictory PASS", " ".join(run.reasons))

    def test_qa_correction_restarts_development_and_all_reviews(self):
        self.cli.qa_failures = 1
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.BLOCKED, run.reasons)
        self.assertEqual(run.repairs, {"qa": 1})
        roles = [t["role"] for t in self.cli.tasks.values()]
        self.assertEqual(roles.count(Role.DEVELOPER), 2)
        self.assertEqual(roles.count(Role.QA), 2)
        self.assertEqual(roles.count(Role.SECURITY), 1)
        self.assertEqual(len(self.cli.tasks), 6)

    def test_agent_success_cannot_override_real_test_failure(self):
        self.cli.bad_developer = True
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED, run.reasons)
        self.assertEqual(run.repairs, {"test": 3})
        self.assertNotIn(Role.QA, [t["role"] for t in self.cli.tasks.values()])

    def test_review_symlink_patch_is_rejected_before_local_import(self):
        self.cli.extra_review_patch = (
            "diff --git a/evil b/evil\nnew file mode 120000\n"
            "--- /dev/null\n+++ b/evil\n@@ -0,0 +1 @@\n+/tmp\n"
        )
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertIn("unsupported file type", " ".join(run.reasons))
        self.assertFalse((self.engine.workspace.root / "evil").is_symlink())

    def test_persistent_qa_failure_escalates_after_bounded_repairs(self):
        # Explicitly enlarge only this controlled test's task budget.
        self.engine, self.cli, self.gateway, self.refs, self.clock, self.kwargs, self.context = (
            cloud_harness(self.root / "bounded", max_tasks=20)
        )
        self.cli.always_fail_qa = True
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED, run.reasons)
        self.assertEqual(run.repairs, {"qa": 3})
        self.assertIn("Repair limit reached", " ".join(run.reasons))
        self.assertEqual(len(self.cli.tasks), 9)

    def test_task_budget_does_not_reset_on_resume(self):
        self.engine, self.cli, self.gateway, self.refs, self.clock, self.kwargs, self.context = (
            cloud_harness(self.root / "budget", max_tasks=2)
        )
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertIn("budget exhausted", " ".join(run.reasons))
        self.assertEqual(len(self.cli.submissions), 2)
        self.engine.execute(REQUIREMENT, run_id=run.id)
        self.assertEqual(len(self.cli.submissions), 2)

    def test_interrupted_source_import_never_applies_twice(self):
        original = self.engine.agents.importer.apply
        self.engine.agents.importer.apply = Mock(side_effect=KeyboardInterrupt)
        run = self.engine.execute(REQUIREMENT)
        self.engine.agents.importer.apply = original
        if run.status == RunStatus.PAUSED:
            run = self.engine.execute(REQUIREMENT, run_id=run.id)
        self.assertIn(run.status, (RunStatus.INTERRUPTED, RunStatus.ESCALATED))
        self.assertEqual(len(self.cli.submissions), 2)
        self.assertEqual(self.gateway.store.cloud_tasks(run.id)[-1]["state"], "import_uncertain")

    def test_default_policy_cannot_activate_cloud_backend(self):
        with self.assertRaises(PermissionDenied):
            self.engine.agents.validate_session(
                self.engine.config,
                self.engine.effective_digest,
                self.engine.store,
                self.engine.grant,
                replace(self.engine.policy, safe_test_mode=True),
            )

    def test_protected_source_import_requires_manual_intervention(self):
        self.cli.extra_review_patch = patch_for(
            "SECURITY.md",
            "# Synthetic policy\nNo secrets or permission escalation.\n",
            "# Changed\n",
        )
        run = self.engine.execute(REQUIREMENT)
        self.assertEqual(run.status, RunStatus.ESCALATED)
        self.assertIn("protected", " ".join(run.reasons))


class CloudRefAdapterTests(unittest.TestCase):
    def test_ref_publication_is_creation_only_and_scope_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, _, _, _, _, kwargs, _ = cloud_harness(Path(directory))
            job = kwargs["job"]
            transport, runner = Mock(), Mock()
            ref = {
                "ref": "refs/heads/" + job.branch,
                "object": {"type": "commit", "sha": job.head_sha},
            }
            transport.request.side_effect = [[], [ref]]
            adapter = GitHubCloudRefs(
                engine.config,
                transport,
                engine.workspace,
                engine.grant,
                engine.effective_digest,
                runner,
            )
            adapter.prepare(job)
            argv = runner.call_args.args[0]
            self.assertIn(f"--force-with-lease=refs/heads/{job.branch}:", argv)
            self.assertIn(f"https://github.com/{engine.config.repository}.git", argv)
            self.assertNotIn("--force", argv)
            runner.reset_mock()
            transport.request.side_effect = None
            transport.request.return_value = [ref]
            adapter.prepare(job)
            runner.assert_not_called()
            with self.assertRaises(PermissionDenied):
                adapter.verify(replace(job, repository="foreign/repository"))

    def test_missing_publish_permission_never_pushes(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, _, _, _, _, kwargs, _ = cloud_harness(Path(directory))
            transport, runner = Mock(), Mock()
            grant = replace(engine.grant, capabilities=frozenset({"read"}))
            adapter = GitHubCloudRefs(
                engine.config, transport, engine.workspace, grant, engine.effective_digest, runner
            )
            with self.assertRaises(PermissionDenied):
                adapter.prepare(kwargs["job"])
            transport.request.assert_not_called()
            runner.assert_not_called()
