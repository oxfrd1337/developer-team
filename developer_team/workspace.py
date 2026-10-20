"""Local Git mechanics for trusted, disposable synthetic fixtures only."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import ProjectConfig, relative_path
from .models import TeamError, digest


def minimal_environment() -> dict[str, str]:
    """Do not give test processes GitHub/Codex credentials from the controller."""
    return {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")
        if key in os.environ
    } | {"PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1"}


class GitWorkspace:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not (self.root / ".git").is_dir():
            raise TeamError("Workspace must be a dedicated Git checkout")

    def git(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-c", "core.hooksPath=/dev/null", *args],
                cwd=self.root,
                env=minimal_environment(),
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise TeamError(f"Git operation failed: {type(exc).__name__}") from exc
        return result.stdout.strip()

    @property
    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def assert_clean(self, head: str | None = None) -> None:
        if self.git("status", "--porcelain", "--untracked-files=all"):
            raise TeamError("Checks or review mutated the checkout; evidence invalidated")
        if head is not None and self.head != head:
            raise TeamError("Commit changed during verification; evidence invalidated")

    def read(self, path: str) -> str:
        candidate = self.root / relative_path(path)
        # Reject even internal symlinks: instructions and executable fixtures are literal files.
        if any(
            part.is_symlink()
            for part in (candidate, *candidate.parents)
            if part != self.root.parent
        ):
            raise TeamError("Symlinks are not allowed in synthetic workspaces")
        if not candidate.resolve().is_relative_to(self.root) or not candidate.is_file():
            raise TeamError(f"Required project file missing: {path}")
        if candidate.stat().st_size > 65536:
            raise TeamError(f"Project instruction exceeds 64 KiB: {path}")
        return candidate.read_text(encoding="utf-8")

    def write(self, path: str, content: str) -> None:
        candidate = self.root / relative_path(path)
        if ".git" in candidate.relative_to(self.root).parts:
            raise TeamError("Writing Git internals is forbidden")
        if not candidate.resolve().is_relative_to(self.root):
            raise TeamError("Write outside synthetic workspace")
        if any(parent.is_symlink() for parent in (candidate, *candidate.parents)):
            raise TeamError("Symlink writes are forbidden")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content, encoding="utf-8")

    def changed_paths(self, base: str) -> tuple[str, ...]:
        # Disable rename detection to include BOTH the old and new path of moved controls.
        output = self.git("diff", "--name-only", "--no-renames", "-z", base, "HEAD", "--")
        return tuple(relative_path(path) for path in output.split("\0") if path)

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        if not self.git("diff", "--cached", "--name-only"):
            raise TeamError("Developer produced no changes")
        self.git(
            "-c",
            "user.name=Synthetic Developer",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-m",
            message,
        )
        self.assert_clean()
        return self.head

    def instructions(self, config: ProjectConfig) -> tuple[dict[str, str], str]:
        tracked = self.git("ls-files", "-z").split("\0")
        paths = set(config.instruction_files + config.security_files)
        paths.update(path for path in tracked if Path(path).name == "AGENTS.md")
        if len(paths) > 100:
            raise TeamError("Too many instruction files; split the project scope")
        documents = {path: self.read(path) for path in sorted(paths)}
        # Sorted paths retain scope. Child AGENTS.md apply to their own subtree only.
        return documents, digest({"project": config.digest, "instructions": documents})
