"""Linux-only isolated Python checks for the artificial supervised Cloud pilot."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from .config import Check
from .execution import SyntheticCommandRunner
from .models import Outcome, TeamError
from .workspace import GitWorkspace


class PilotCommandRunner(SyntheticCommandRunner):
    """Reuse bounded execution, with no host home, network or writable source mount.

    bubblewrap and enabled unprivileged namespaces are host prerequisites, not
    installed or enabled by the controller. Failure never falls back to host Python.
    """

    def __init__(self, audit_directory: Path):
        super().__init__()
        self.artifacts = audit_directory

    @staticmethod
    def command(root: Path, argv: tuple[str, ...]) -> tuple[str, ...]:
        binary = shutil.which("bwrap")
        if binary is None:
            raise TeamError("bubblewrap is required; host execution is forbidden")
        mounts = []
        for name in ("usr", "bin", "lib", "lib64"):
            path = Path("/") / name
            if path.is_symlink():
                mounts.extend(("--symlink", str(path.readlink()), str(path)))
            elif path.is_dir():
                mounts.extend(("--ro-bind", str(path), str(path)))
        return (
            binary,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            *mounts,
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",  # noqa: S108 -- new private tmpfs inside the namespace, never host /tmp
            "--ro-bind",
            str(root.resolve()),
            "/project",
            "--chdir",
            "/project",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--",
            *argv,
        )

    def run(self, check: Check, root: Path):
        # A commit-specific location preserves failures across corrections/restarts.
        directory = self.artifacts / GitWorkspace(root).head
        runner = SyntheticCommandRunner(audit_directory=directory)
        return runner.run(replace(check, argv=self.command(root, check.argv)), root)

    def require_available(self, root: Path) -> None:
        probe = Check(
            "sandbox-probe",
            "test",
            ("python3", "-I", "-c", "import sys; assert sys.version_info >= (3, 11)"),
            10,
            True,
        )
        if self.run(probe, root).outcome != Outcome.PASS:
            raise TeamError(
                "Isolated Python probe failed; enabled Linux namespaces and Python 3.11+ "
                "in /usr/bin are required. No Cloud task may start."
            )
