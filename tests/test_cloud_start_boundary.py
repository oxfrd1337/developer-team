"""Production NO-GO regressions with otherwise valid, entirely synthetic approvals."""

import json
import tempfile
import unittest
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch

from developer_team.adapters import codex_cloud
from developer_team.adapters.codex_cloud import CodexCloudGateway, run_cli
from developer_team.adapters.offline_cloud import _OfflineCloudLifecycle
from developer_team.adapters.pilot_fake import RehearsalCloudGateway
from developer_team.models import PermissionDenied
from developer_team.pilot_scope import PILOT_REPOSITORY
from tests.cloud_support import cloud_harness


class ForwardingCallable:
    def __call__(self, argv):
        return codex_cloud.run_cli(argv)


class CloudStartBoundaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        engine, _, offline, refs, clock, kwargs, _ = cloud_harness(Path(directory.name))
        config = replace(kwargs["config"], repository=PILOT_REPOSITORY)
        _, sealed = engine.workspace.instructions(config)
        approval = replace(kwargs["approval"], repository=PILOT_REPOSITORY, config_digest=sealed)
        grant = replace(kwargs["grant"], repository=PILOT_REPOSITORY, config_digest=sealed)
        job = replace(kwargs["job"], repository=PILOT_REPOSITORY, config_digest=sealed)
        policy = replace(kwargs["policy"], controller_repository=PILOT_REPOSITORY)
        self.kwargs = kwargs | {
            "config": config,
            "effective_digest": sealed,
            "approval": approval,
            "grant": grant,
            "job": job,
            "branch": job.branch,
            "policy": policy,
        }
        # Prove the regression does not pass merely because the remaining grant,
        # job, environment, lease or policy would already have failed validation.
        self.assertEqual(
            offline._authorize(config, sealed, policy, grant, job.role, approval, job),
            "env-developer",
        )
        self.store, self.refs = Mock(wraps=engine.store), Mock(wraps=refs)
        self.gateway = CodexCloudGateway(store=self.store, refs=self.refs, now=clock)

    def assert_blocked(self, **changes):
        with (
            patch("subprocess.Popen", side_effect=AssertionError) as process,
            patch("developer_team.adapters.codex_cloud.run_cli") as cli,
        ):
            with self.assertRaisesRegex(PermissionDenied, "DT-008 NO-GO"):
                self.gateway.submit(**(self.kwargs | changes))
            process.assert_not_called()
            cli.assert_not_called()
        self.assertEqual(self.store.mock_calls, [])
        self.assertEqual(self.refs.mock_calls, [])

    def test_valid_approval_still_blocks_before_all_side_effects(self):
        self.assert_blocked()

    def test_constructor_rejects_all_callable_runner_forms(self):
        for runner in (run_cli, lambda argv: run_cli(argv), partial(run_cli), ForwardingCallable()):
            with (
                self.subTest(runner=type(runner).__name__),
                patch("subprocess.Popen", side_effect=AssertionError) as process,
            ):
                with self.assertRaises(TypeError):
                    CodexCloudGateway(runner, store=self.store, refs=self.refs)
                with self.assertRaises(TypeError):
                    CodexCloudGateway(runner=runner, store=self.store, refs=self.refs)
                process.assert_not_called()
        self.assertEqual(self.store.mock_calls, [])
        self.assertEqual(self.refs.mock_calls, [])

    def test_wrappers_partials_and_changed_labels_cannot_open_submission(self):
        for forward in (
            run_cli,
            lambda argv: run_cli(argv),
            partial(run_cli),
            ForwardingCallable(),
        ):
            for label in (True, False, None, "simulated"):
                with self.subTest(forward=type(forward).__name__, label=label):
                    runner = Mock(wraps=forward)
                    self.gateway.runner = runner
                    self.gateway._runner = runner
                    self.gateway.transport = runner
                    self.gateway.simulated = label
                    self.assert_blocked()
                    runner.assert_not_called()

    def test_fake_grants_and_approvals_do_not_open_submission(self):
        for changes in (
            {"grant": {"cloud_submit": True, "approved_by": "operator"}},
            {"approval": {"decision": "GO", "signature": "valid"}},
            {"job": {"repository": PILOT_REPOSITORY, "role": "developer"}},
        ):
            with self.subTest(changes=changes):
                self.assert_blocked(**changes)

    def test_production_collection_is_also_closed_before_journal_or_transport(self):
        with patch("subprocess.Popen", side_effect=AssertionError) as process:
            with self.assertRaisesRegex(PermissionDenied, "DT-008 NO-GO"):
                self.gateway.collect(self.kwargs["job"], self.kwargs["approval"])
            process.assert_not_called()
        self.assertEqual(self.store.mock_calls, [])
        self.assertEqual(self.refs.mock_calls, [])

    def test_offline_lifecycle_has_no_production_inheritance_or_runner_parameter(self):
        self.assertNotIsInstance(self.gateway, _OfflineCloudLifecycle)
        self.assertFalse(issubclass(RehearsalCloudGateway, CodexCloudGateway))
        with self.assertRaises(TypeError):
            _OfflineCloudLifecycle(runner=ForwardingCallable(), store=None, refs=None)
        with self.assertRaises(TypeError):
            RehearsalCloudGateway(runner=ForwardingCallable())
        with (
            self.assertRaises(TypeError),
            patch("subprocess.Popen", side_effect=AssertionError) as process,
        ):
            _OfflineCloudLifecycle(store=None, refs=None)
        process.assert_not_called()

    def test_rehearsal_remains_model_free_with_runner_attributes_and_changed_labels(self):
        fixture = RehearsalCloudGateway(
            Mock(), Mock(), self.kwargs["approval"].run_id, "happy", now=lambda: 1
        )
        prompt = json.dumps(self.kwargs["job"].envelope(), sort_keys=True)
        for forward in (
            run_cli,
            lambda argv: run_cli(argv),
            partial(run_cli),
            ForwardingCallable(),
        ):
            with (
                self.subTest(forward=type(forward).__name__),
                patch("subprocess.Popen", side_effect=AssertionError) as process,
                patch("developer_team.adapters.codex_cloud.run_cli") as cli,
            ):
                runner = Mock(wraps=forward)
                fixture.runner = runner
                fixture._runner = runner
                fixture.simulated = False
                receipt = fixture._request(["codex", "cloud", "exec", "--", prompt])
                self.assertEqual(
                    receipt,
                    "https://chatgpt.com/codex/tasks/task_simulated_" + self.kwargs["job"].id,
                )
                runner.assert_not_called()
                process.assert_not_called()
                cli.assert_not_called()
