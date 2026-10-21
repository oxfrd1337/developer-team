import copy
import unittest
from dataclasses import replace
from unittest.mock import Mock

from developer_team.adapters.codex_cloud import CodexCloudGateway
from developer_team.adapters.github import (
    GitHubMerger,
    GitHubPRWriter,
    GitHubReader,
    RequiredGitHubCheck,
)
from developer_team.authority import ProjectGrant, RuntimePolicy, synthetic_authority
from developer_team.config import load_config
from developer_team.gate import MergeGate
from developer_team.models import (
    Binding,
    GateDecision,
    IntegrationUnavailable,
    PermissionDenied,
    Role,
)

from .support import EXAMPLE

HEAD = "1" * 40
BASE = "2" * 40


class FakeGitHub:
    """A transport fixture. None of these tests calls GitHub or Codex Cloud."""

    def __init__(self):
        self.calls = []
        self.pr = {
            "number": 1,
            "head": {
                "sha": HEAD,
                "ref": "dt/example",
                "repo": {"full_name": "synthetic/calculator"},
            },
            "base": {"sha": BASE, "ref": "main", "repo": {"full_name": "synthetic/calculator"}},
            "changed_files": 3,
            "state": "open",
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
        }
        self.files = [{"filename": p} for p in ("calculator.py", "tests/test_calc.py", "README.md")]
        self.pins = tuple(
            RequiredGitHubCheck(name, app)
            for name, app in (
                ("unit", 101),
                ("build", 102),
                ("qa", 103),
                ("security", 104),
                ("acceptance", 105),
            )
        )
        self.checks = [
            {
                "name": c.name,
                "head_sha": HEAD,
                "app": {"id": c.app_id},
                "status": "completed",
                "conclusion": "success",
            }
            for c in self.pins
        ]
        self.protection = {
            "required_status_checks": {
                "strict": True,
                "checks": [{"context": c.name, "app_id": c.app_id} for c in self.pins],
            },
            "enforce_admins": {"enabled": True},
        }
        self.permissions = {"push": True, "admin": False}
        self.existing = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "PUT":
            return {"merged": True, "sha": "3" * 40}
        if method == "POST":
            return {"number": 1, **payload}
        if "/pulls?" in path:
            return copy.deepcopy(self.existing)
        if "/git/ref/heads/" in path:
            return {"object": {"sha": HEAD}}
        if "/files?" in path:
            return copy.deepcopy(self.files)
        if "/check-runs?" in path:
            return {"total_count": len(self.checks), "check_runs": copy.deepcopy(self.checks)}
        if "/protection" in path:
            if isinstance(self.protection, Exception):
                raise self.protection
            return copy.deepcopy(self.protection)
        if path.endswith("/pulls/1"):
            return copy.deepcopy(self.pr)
        if path == "repos/synthetic/calculator":
            return {"permissions": copy.deepcopy(self.permissions)}
        raise AssertionError((method, path, payload))


class GitHubAdapterTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(load_config(EXAMPLE), provider="github", auto_merge=True)
        self.api = FakeGitHub()
        self.reader = GitHubReader(self.config, self.api, self.api.pins)
        self.grant = ProjectGrant(
            self.config.id,
            self.config.repository,
            self.config.digest,
            frozenset({"pull_request", "merge"}),
            True,
            "trusted-controller",
        )
        self.live_policy = RuntimePolicy(False, True, False)

    def test_read_collector_pins_checks_but_does_not_invent_review_attestation(self):
        snapshot = self.reader.snapshot(1)
        self.assertTrue(snapshot.protection_satisfied)
        self.assertTrue(snapshot.permissions_satisfied)
        self.assertFalse(snapshot.integration_verified)
        self.assertFalse(snapshot.simulated)
        self.assertTrue(all(call[0] == "GET" for call in self.api.calls))

    def test_wrong_app_id_and_skipped_checks_block(self):
        for update in (
            {"app": {"id": 999}},
            {"conclusion": "skipped"},
            {"head_sha": "9" * 40},
            {"status": "in_progress"},
        ):
            with self.subTest(update=update):
                original = self.api.checks[2]
                self.api.checks[2] = original | update
                self.assertFalse(self.reader.snapshot(1).protection_satisfied)
                self.api.checks[2] = original

    def test_duplicate_check_names_block(self):
        self.api.checks.append(copy.deepcopy(self.api.checks[0]))
        self.assertFalse(self.reader.snapshot(1).protection_satisfied)

    def test_unknown_branch_protection_blocks(self):
        self.api.protection = IntegrationUnavailable("403")
        self.assertIsNone(self.reader.snapshot(1).protection_satisfied)

    def test_admin_credentials_are_rejected_by_permission_snapshot(self):
        self.api.permissions["admin"] = True
        self.assertFalse(self.reader.snapshot(1).permissions_satisfied)

    def test_cross_project_pull_request_is_rejected(self):
        self.api.pr["head"]["repo"]["full_name"] = "synthetic/other"
        with self.assertRaises(PermissionDenied):
            self.reader.snapshot(1)

    def test_incomplete_file_list_fails_closed(self):
        from developer_team.models import TeamError

        self.api.pr["changed_files"] = 4
        with self.assertRaises(TeamError):
            self.reader.snapshot(1)

    def test_renamed_protected_file_includes_previous_name(self):
        self.api.files[0]["previous_filename"] = "SECURITY.md"
        self.assertIn("SECURITY.md", self.reader.snapshot(1).changed_paths)

    def test_safe_mode_pr_write_is_denied_before_any_api_call(self):
        writer = GitHubPRWriter(
            self.config, self.api, self.grant, RuntimePolicy(), self.config.digest
        )
        with self.assertRaises(PermissionDenied):
            writer.open(
                branch="dt/example", expected_sha=HEAD, title="Test", body="Test", run_id="one"
            )
        self.assertEqual(self.api.calls, [])

    def test_pr_creation_is_bound_to_remote_sha_and_idempotent_run_marker(self):
        writer = GitHubPRWriter(
            self.config, self.api, self.grant, self.live_policy, self.config.digest
        )
        pr = writer.open(
            branch="dt/example", expected_sha=HEAD, title="Test", body="Test", run_id="one"
        )
        self.assertIn("<!-- developer-team-run:one -->", pr["body"])
        self.api.existing = [pr]
        same = writer.open(
            branch="dt/example", expected_sha=HEAD, title="Test", body="Test", run_id="one"
        )
        self.assertEqual(pr, same)
        self.assertEqual(sum(c[0] == "POST" for c in self.api.calls), 1)

    def test_changed_remote_branch_prevents_pr_creation(self):
        from developer_team.models import TeamError

        writer = GitHubPRWriter(
            self.config, self.api, self.grant, self.live_policy, self.config.digest
        )
        with self.assertRaises(TeamError):
            writer.open(
                branch="dt/example", expected_sha="f" * 40, title="Test", body="Test", run_id="one"
            )
        self.assertFalse(any(c[0] == "POST" for c in self.api.calls))

    def test_even_activated_merger_blocks_unverified_live_integration(self):
        merger = GitHubMerger(self.reader, MergeGate(synthetic_authority()))
        from developer_team.models import Criterion, Plan

        plan = Plan((Criterion("AC-1", "Test"),), ("Test",))
        binding = Binding(
            self.config.repository, HEAD, BASE, self.config.digest, plan.digest, "run"
        )
        with self.assertRaisesRegex(PermissionDenied, "live_integration_unverified"):
            merger.merge_if_allowed(
                number=1,
                config=self.config,
                effective_digest=self.config.digest,
                policy=self.live_policy,
                grant=self.grant,
                binding=binding,
                plan=plan,
                evidence=[],
                developer="d",
                qa="q",
                security="s",
            )
        self.assertFalse(any(c[0] == "PUT" for c in self.api.calls))

    def test_safe_mode_merger_does_not_read_or_write_remote_state(self):
        merger = GitHubMerger(self.reader, MergeGate(synthetic_authority()))
        with self.assertRaises(PermissionDenied):
            merger.merge_if_allowed(
                number=1,
                config=self.config,
                effective_digest=self.config.digest,
                policy=RuntimePolicy(),
                grant=self.grant,
                binding=None,
                plan=None,
                evidence=[],
                developer="d",
                qa="q",
                security="s",
            )
        self.assertEqual(self.api.calls, [])

    def test_merge_request_always_carries_expected_sha_without_bypass(self):
        # An isolated transport contract test with a mocked gate; not a verified live merge.
        from developer_team.models import Criterion, Plan

        plan = Plan((Criterion("AC-1", "Test"),), ("Test",))
        binding = Binding(
            self.config.repository, HEAD, BASE, self.config.digest, plan.digest, "run"
        )
        gate = Mock()
        gate.evaluate.return_value = GateDecision(True, ())
        merger = GitHubMerger(self.reader, gate)
        result = merger.merge_if_allowed(
            number=1,
            config=self.config,
            effective_digest=self.config.digest,
            policy=self.live_policy,
            grant=self.grant,
            binding=binding,
            plan=plan,
            evidence=[],
            developer="d",
            qa="q",
            security="s",
        )
        self.assertTrue(result["merged"])
        writes = [c for c in self.api.calls if c[0] == "PUT"]
        self.assertEqual(writes[0][2], {"sha": HEAD, "merge_method": "squash"})

    def test_final_head_change_or_retargeting_blocks_even_after_a_passing_gate(self):
        from developer_team.models import Criterion, Plan

        for change in ("head", "base-ref"):
            with self.subTest(change=change):

                class MovingGitHub(FakeGitHub):
                    reads = 0
                    change_kind = change

                    def request(self, method, path, payload=None):
                        response = super().request(method, path, payload)
                        if method == "GET" and path.endswith("/pulls/1"):
                            self.reads += 1
                            if self.reads == 3:
                                if self.change_kind == "head":
                                    response["head"]["sha"] = "9" * 40
                                else:
                                    response["base"]["ref"] = "unapproved-branch"
                        return response

                api = MovingGitHub()
                gate = Mock()
                gate.evaluate.return_value = GateDecision(True, ())
                merger = GitHubMerger(GitHubReader(self.config, api, api.pins), gate)
                plan = Plan((Criterion("AC-1", "Test"),), ("Test",))
                binding = Binding(
                    self.config.repository, HEAD, BASE, self.config.digest, plan.digest, "run"
                )
                with self.assertRaisesRegex(PermissionDenied, "changed after merge approval"):
                    merger.merge_if_allowed(
                        number=1,
                        config=self.config,
                        effective_digest=self.config.digest,
                        policy=self.live_policy,
                        grant=self.grant,
                        binding=binding,
                        plan=plan,
                        evidence=[],
                        developer="d",
                        qa="q",
                        security="s",
                    )
                self.assertFalse(any(call[0] == "PUT" for call in api.calls))


class CodexCloudAdapterTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from uuid import uuid4

        from developer_team.adapters.cloud_contracts import CloudApproval, CloudJob
        from developer_team.models import digest
        from developer_team.store import RunStore
        from tests.cloud_support import FakeRefs

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = replace(load_config(EXAMPLE), provider="github")
        self.policy = RuntimePolicy(False, True, False)
        environments = tuple((role, f"env-{role.value}") for role in Role)
        self.grant = ProjectGrant(
            self.config.id,
            self.config.repository,
            self.config.digest,
            frozenset({"cloud_submit"}),
            False,
            "trusted-controller",
            environments,
        )
        self.runner = Mock(return_value="https://chatgpt.com/codex/tasks/task_fixture")
        self.approval = CloudApproval(
            str(uuid4()),
            self.config.repository,
            self.config.digest,
            "explicit-test-operator",
            10000,
        )
        self.job = CloudJob(
            self.approval.run_id,
            self.config.repository,
            self.config.digest,
            HEAD,
            Role.DEVELOPER,
            0,
            digest("controlled input"),
        )
        self.gateway = CodexCloudGateway(
            self.runner,
            store=RunStore(Path(directory.name) / "state.sqlite3"),
            refs=FakeRefs(),
            now=lambda: 1,
        )

    def submit(self, **changes):
        kwargs = dict(
            config=self.config,
            effective_digest=self.config.digest,
            policy=self.policy,
            grant=self.grant,
            role=Role.DEVELOPER,
            branch=self.job.branch,
            expected_sha=HEAD,
            prompt="Synthetic requirement",
            approval=self.approval,
            job=self.job,
        )
        return self.gateway.submit(**(kwargs | changes))

    def test_safe_mode_never_submits_cloud_task(self):
        with self.assertRaises(PermissionDenied):
            self.submit(policy=RuntimePolicy())
        self.runner.assert_not_called()

    def test_cloud_command_has_single_attempt_and_receipt_is_not_execution_proof(self):
        submission = self.submit()
        self.assertEqual(submission.task_id, "task_fixture")
        self.assertFalse(submission.verified_execution)
        args = self.runner.call_args.args[0]
        self.assertEqual(args[:3], ["codex", "cloud", "exec"])
        self.assertEqual(args[args.index("--attempts") + 1], "1")
        self.assertIn(HEAD, args[-1])
        self.assertEqual(args[-2], "--")

    def test_shared_development_and_review_environment_is_rejected(self):
        grant = replace(self.grant, cloud_environments=tuple((role, "same") for role in Role))
        with self.assertRaises(PermissionDenied):
            self.submit(grant=grant)
        self.runner.assert_not_called()

    def test_missing_project_grant_cannot_use_existing_chatgpt_login(self):
        with self.assertRaises(PermissionDenied):
            self.submit(grant=replace(self.grant, capabilities=frozenset()))
        self.runner.assert_not_called()

    def test_unknown_receipt_is_ambiguous_and_not_retried(self):
        self.runner.return_value = "Accepted, format changed"
        with self.assertRaises(IntegrationUnavailable):
            self.submit()
        self.assertEqual(self.runner.call_count, 1)

    def test_task_arguments_cannot_inject_options(self):
        for task in ("--help", "task_bad/../path", "https://other.example/task_1"):
            with self.subTest(task=task), self.assertRaises(PermissionDenied):
                self.gateway.status(task)
        self.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
