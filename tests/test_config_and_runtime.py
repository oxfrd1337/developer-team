import os
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from developer_team.adapters.synthetic import create_fixture
from developer_team.config import Check, ConfigError, load_config
from developer_team.execution import SyntheticCommandRunner
from developer_team.models import Outcome, TeamError
from developer_team.store import RunStore

from .support import EXAMPLE, harness


class ConfigAndRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def config_text(self, text):
        path = self.path / "project.toml"
        path.write_text(text)
        return load_config(path)

    def test_project_config_does_not_depend_on_language(self):
        text = EXAMPLE.read_text().replace(
            'languages = ["python"]', 'languages = ["rust", "typescript"]'
        )
        text = text.replace('frameworks = ["unittest"]', 'frameworks = ["cargo", "vitest"]')
        text = text.replace(
            '["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]',
            '["cargo", "test", "--locked"]',
        )
        config = self.config_text(text)
        self.assertEqual(config.languages, ("rust", "typescript"))
        self.assertEqual(config.checks[0].argv, ("cargo", "test", "--locked"))
        self.assertFalse(config.auto_merge)

    def test_typos_ambiguous_types_and_unbounded_limits_are_rejected(self):
        original = EXAMPLE.read_text()
        changes = (
            ("schema_version = 1", "schema_version = 2"),
            ("enabled = false", 'enabled = "false"'),
            ("max_repairs_per_class = 3", "max_repairs_per_class = 4"),
            ("max_repairs_per_class = 3", "max_repairs_per_class = true"),
            ("max_steps = 60", "max_steps = 1000"),
            ("timeout_seconds = 15", "timeout_seconds = 0"),
            ('kind = "test"', 'kind = "unknown"'),
            ("required = true", "required = false"),
            ('repository = "synthetic/calculator"', 'repository = "https://token@github.com/a/b"'),
            ('repository = "synthetic/calculator"', 'repository = "../user"'),
            ('repository = "synthetic/calculator"', 'repository = "synthetic/.."'),
            ('files = ["AGENTS.md"]', 'files = ["../AGENTS.md"]'),
            ("enabled = false", "enabeld = false"),
            ('name = "build"', 'name = "unit"'),
            ('languages = ["python"]', "languages = []"),
            ('argv = ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]', "argv = []"),
        )
        for before, after in changes:
            with self.subTest(after=after), self.assertRaises(ConfigError):
                self.config_text(original.replace(before, after))

    def test_missing_security_policy_never_falls_back_to_an_empty_policy(self):
        workspace = create_fixture(self.path / "project")
        (workspace.root / "SECURITY.md").unlink()
        with self.assertRaises(TeamError):
            workspace.instructions(load_config(EXAMPLE))

    def test_nested_agents_have_paths_and_are_bound_into_effective_config(self):
        workspace = create_fixture(self.path / "project")
        config = load_config(EXAMPLE)
        _, first = workspace.instructions(config)
        workspace.write("src/AGENTS.md", "# Only applies to src\nKeep public APIs stable.\n")
        workspace.commit("Add scoped instructions")
        documents, second = workspace.instructions(config)
        self.assertNotEqual(first, second)
        self.assertIn("src/AGENTS.md", documents)

    def test_protected_rename_preserves_the_old_path(self):
        workspace = create_fixture(self.path / "project")
        base = workspace.head
        workspace.git("mv", "SECURITY.md", "security-renamed.md")
        workspace.commit("Rename security policy")
        paths = workspace.changed_paths(base)
        self.assertIn("SECURITY.md", paths)
        self.assertIn("security-renamed.md", paths)

    def test_symlinks_cannot_escape_the_workspace(self):
        workspace = create_fixture(self.path / "project")
        outside = self.path / "outside.txt"
        outside.write_text("untouched")
        (workspace.root / "escape").symlink_to(outside)
        with self.assertRaises(TeamError):
            workspace.write("escape", "changed")
        with self.assertRaises(TeamError):
            workspace.read("escape")
        self.assertEqual(outside.read_text(), "untouched")

    def test_no_shell_interpolation_and_no_inherited_controller_secret(self):
        sentinel = self.path / "should-not-exist"
        argument = f"$(touch {sentinel})"
        script = "import os, sys; assert 'DT_SYNTHETIC_SECRET' not in os.environ; "
        script += "assert sys.argv[1].startswith('$(touch ')"
        with patch.dict(os.environ, {"DT_SYNTHETIC_SECRET": "synthetic-test-marker"}):
            result = SyntheticCommandRunner().run(
                Check("isolation", "test", (sys.executable, "-c", script, argument), 5, True),
                self.path,
            )
        self.assertEqual(result.outcome, Outcome.PASS)
        self.assertFalse(sentinel.exists())

    def test_timeout_kills_descendants(self):
        sentinel = self.path / "child-survived"
        child = "import pathlib, sys, time; time.sleep(1.6); pathlib.Path(sys.argv[1]).touch()"
        parent = "import subprocess, sys, time; "
        parent += (
            "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); time.sleep(20)"
        )
        result = SyntheticCommandRunner().run(
            Check("timeout", "test", (sys.executable, "-c", parent, child, str(sentinel)), 1, True),
            self.path,
        )
        self.assertEqual(result.outcome, Outcome.FAIL)
        self.assertIn("timed out", result.detail)
        time.sleep(0.8)
        self.assertFalse(sentinel.exists())

    def test_arbitrary_custom_command_is_executed_without_language_assumptions(self):
        result = SyntheticCommandRunner().run(
            Check(
                "custom-build", "build", (sys.executable, "-c", "print('synthetic-build')"), 5, True
            ),
            self.path,
        )
        self.assertEqual(result.outcome, Outcome.PASS)
        self.assertEqual(len(result.output_digest), 64)
        self.assertNotIn("synthetic-build", result.detail)

    def test_run_lock_prevents_concurrent_controllers(self):
        from uuid import uuid4

        store = RunStore(self.path / "state.sqlite3")
        run_id = str(uuid4())
        with store.lock(run_id), self.assertRaises(TeamError), store.lock(run_id):
            self.fail("A second controller acquired the lock")

    def test_global_step_budget_survives_pause_and_resume(self):
        from developer_team.adapters.synthetic import REQUIREMENT
        from developer_team.models import RunStatus, Stage

        engine, _, _, delivery, store = harness(self.path)
        run = engine.execute(REQUIREMENT, pause_before=Stage.DEVELOPMENT)
        run.steps = engine.config.max_steps
        store.save(run, "exhaust_global_budget")
        resumed = engine.execute(REQUIREMENT, run_id=run.id)
        self.assertEqual(resumed.status, RunStatus.ESCALATED)
        self.assertIn("Workflow step limit reached", resumed.reasons)
        self.assertEqual(delivery.merge_calls, 0)

    def test_project_grant_cannot_be_reused_for_a_different_project(self):
        from developer_team.models import PermissionDenied

        engine, _, _, _, _ = harness(self.path)
        with self.assertRaises(PermissionDenied):
            engine.grant.require(
                replace(engine.config, id="other"), "develop", engine.effective_digest
            )


if __name__ == "__main__":
    unittest.main()
