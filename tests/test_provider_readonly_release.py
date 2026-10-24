"""Synthetic external approvals; real disposable Git repos, never credentials."""

import contextlib
import json
import os
import subprocess
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from developer_team import provider_readonly_prepare as broker
from developer_team import provider_readonly_release as release
from developer_team.adapters.agents_api_contracts import AgentsAPIError
from tests.agents_api_support import binding


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name).resolve()
        self.root = self.parent / "repo"
        self.root.mkdir()
        self.pin = self.parent / "approval.json"
        source = Path(broker.__file__).resolve().parent
        for path in source.rglob("*.py"):
            destination = self.root / "developer_team" / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
        (self.root / "README.md").write_text("synthetic release\n")
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "synthetic independent review")
        candidate, _ = release._inventory(self.root)
        self.pin.write_text(json.dumps(candidate))
        self.pin.chmod(0o400)
        self.enterContext(patch.object(release, "_approval_path", return_value=self.pin))
        self.enterContext(
            patch.object(
                broker, "__file__", str(self.root / "developer_team/provider_readonly_prepare.py")
            )
        )

    def git(self, *args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=Synthetic",
                "-c",
                "user.email=synthetic@example.invalid",
                *args,
            ],
            cwd=self.root,
            stderr=subprocess.DEVNULL,
        )

    def blocked_before_credentials(self):
        # Both interactive selection and inherited FD validation must remain unused.
        for descriptors in ((None, None), (999998, 999999)):
            with contextlib.ExitStack() as stack:
                guards = [
                    stack.enter_context(patch.object(broker, name))
                    for name in (
                        "_read_path",
                        "_open_private",
                        "_checked_fd",
                        "_invoke",
                    )
                ]
                guards.append(stack.enter_context(patch("os.dup")))
                with self.assertRaises(AgentsAPIError):
                    broker._execute({}, binding(), *descriptors, None)
                for guard in guards:
                    guard.assert_not_called()

    def test_exact_clean_independently_pinned_release_allowed(self):
        self.assertEqual(broker._check_checkout(), self.root)
        sources = release.verify_release(self.root)
        self.assertIn("developer_team/provider_readonly_prepare.py", sources)
        self.assertIn("developer_team/provider_readonly_release.py", sources)

    def test_changed_broker_blocks_before_credentials(self):
        path = self.root / "developer_team/provider_readonly_prepare.py"
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
        self.blocked_before_credentials()

    def test_changed_collector_blocks_before_credentials(self):
        path = self.root / "developer_team/provider_readonly.py"
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
        self.blocked_before_credentials()

    def test_changed_https_credential_contract_scope_and_verifier_block(self):
        for relative in (
            "adapters/provider_readonly_https.py",
            "adapters/agents_https.py",
            "adapters/agents_credentials.py",
            "adapters/agents_api_contracts.py",
            "scope_evidence.py",
            "provider_readonly_release.py",
        ):
            with self.subTest(module=relative):
                path = self.root / "developer_team" / relative
                original = path.read_bytes()
                path.write_bytes(original + b"\n# changed\n")
                self.blocked_before_credentials()
                path.write_bytes(original)

    def test_dirty_tracked_worktree_blocks(self):
        (self.root / "README.md").write_text("dirty\n")
        self.blocked_before_credentials()

    def test_staged_change_blocks_even_after_worktree_restored(self):
        path = self.root / "README.md"
        path.write_text("staged\n")
        self.git("add", "README.md")
        path.write_text("synthetic release\n")
        self.blocked_before_credentials()

    def test_untracked_shadowing_modules_and_packages_block(self):
        for name in ("json.py", "sitecustomize.py", "developer_team/adapters/shadow.py"):
            path = self.root / name
            path.write_text("raise RuntimeError('synthetic shadow')\n")
            self.blocked_before_credentials()
            path.unlink()

    def test_ignored_bytecode_native_modules_and_import_hooks_block(self):
        ignore = self.root / ".git/info/exclude"
        ignore.write_text("*.pyc\n*.so\n*.pth\n")
        for name in ("developer_team/__init__.pyc", "json.so", "startup.pth"):
            path = self.root / name
            path.write_bytes(b"synthetic shadow")
            self.blocked_before_credentials()
            path.unlink()

    def test_later_descendant_without_new_independent_pin_blocks(self):
        path = self.root / "developer_team/provider_readonly.py"
        path.write_bytes(path.read_bytes() + b"\n# descendant\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "unapproved descendant")
        self.blocked_before_credentials()

    def test_empty_descendant_with_identical_tree_still_blocks(self):
        self.git("commit", "--quiet", "--allow-empty", "-m", "unapproved metadata")
        self.blocked_before_credentials()

    def test_assume_unchanged_cannot_hide_source_drift(self):
        relative = "developer_team/adapters/agents_https.py"
        self.git("update-index", "--assume-unchanged", relative)
        path = self.root / relative
        path.write_bytes(path.read_bytes() + b"\n# hidden dirty source\n")
        self.blocked_before_credentials()

    def test_missing_or_writable_approval_blocks(self):
        self.pin.chmod(0o600)
        self.blocked_before_credentials()
        self.pin.unlink()
        self.blocked_before_credentials()

    def test_approval_inside_checkout_is_not_trusted(self):
        path = self.root / "approval.json"
        path.write_bytes(self.pin.read_bytes())
        path.chmod(0o400)
        with patch.object(release, "_approval_path", return_value=path):
            self.blocked_before_credentials()

    def test_wrong_inventory_and_tree_pins_block(self):
        original = json.loads(self.pin.read_text())
        self.pin.chmod(0o600)
        for name in ("tree", "inventory_sha256"):
            value = original | {name: "0" * len(original[name])}
            self.pin.write_text(json.dumps(value))
            self.pin.chmod(0o400)
            self.blocked_before_credentials()
            self.pin.chmod(0o600)

    def test_symlink_source_blocks(self):
        path = self.root / "developer_team/scope_evidence.py"
        copy = self.parent / "outside.py"
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
        self.blocked_before_credentials()

    def test_snapshot_uses_verified_bytes_after_worktree_drift_and_is_removed(self):
        with release.verified_snapshot(self.root) as snapshot:
            relative = "developer_team/provider_readonly.py"
            expected = (snapshot / relative).read_bytes()
            (self.root / relative).write_text("changed after verification\n")
            self.assertEqual((snapshot / relative).read_bytes(), expected)
            self.assertEqual(list(snapshot.rglob("*.pyc")), [])
        self.assertFalse(snapshot.exists())

    def test_real_isolated_snapshot_child_stays_offline(self):
        bound = binding()
        values = asdict(bound) | {
            "admin_ref": "admin_synthetic",
            "credential_ref": "key_synthetic",
            "service_account_ref": "sa_synthetic",
        }
        with contextlib.ExitStack() as stack:
            handles = []
            for role in ("admin", "canary"):
                path = self.parent / role
                path.write_text("synthetic_material")
                path.chmod(0o600)
                handles.append(stack.enter_context(broker._open_private(str(path))))
            manifest = self.parent / "manifest.json"
            manifest.write_text(
                json.dumps(
                    broker._manifest(
                        values,
                        bound,
                        handles[0][1],
                        handles[1][1],
                        now=int(time.time()),
                    )
                )
            )
            with patch.dict(os.environ, {"DT_PROVIDER_OFFLINE": "1"}):
                report = broker._invoke(self.root, manifest, handles[0][0], handles[1][0])
            self.assertEqual(report["outcome"], "BLOCKED")
            self.assertEqual(report["real_submissions"], 0)
            self.assertIs(report["live_authorized"], False)

    def test_plan_does_not_read_release_approval_or_repository(self):
        with (
            patch.object(broker, "_check_checkout", side_effect=AssertionError),
            patch("builtins.open", side_effect=AssertionError),
            patch("os.open", side_effect=AssertionError),
        ):
            self.assertEqual(broker.prepare([])["mode"], "PLAN")


if __name__ == "__main__":
    unittest.main()
