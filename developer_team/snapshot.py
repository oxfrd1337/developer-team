"""Controller-side content checks for trusted simulations, never OS attestations."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass

from .config import relative_path
from .models import TeamError, digest
from .workspace import GitWorkspace


def _inventory(workspace: GitWorkspace) -> tuple[tuple[str, int, str], ...]:
    """Include ignored files and Git metadata; never follow links or special files."""
    result = []
    total = 0

    def unreadable(error):
        raise TeamError("Snapshot cannot be fully inventoried") from error

    for directory, directories, files in os.walk(
        workspace.root, followlinks=False, onerror=unreadable
    ):
        for name in sorted(directories + files):
            path = workspace.root / os.path.relpath(os.path.join(directory, name), workspace.root)
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise TeamError("Snapshot contains a link or special file")
            total += info.st_size
            if total > 64 * 1024 * 1024 or len(result) >= 4096:
                raise TeamError("Snapshot inventory exceeds the controller budget")
            content = path.read_bytes()
            result.append(
                (
                    path.relative_to(workspace.root).as_posix(),
                    stat.S_IMODE(info.st_mode),
                    hashlib.sha256(content).hexdigest(),
                )
            )
    return tuple(sorted(result))


@dataclass(frozen=True)
class SnapshotSeal:
    """In-memory baseline from Git objects AND actual bytes, held by the controller.

    Detects persistent tampering, including assume-unchanged/ignored files and Git
    metadata. Same-UID write-and-restore attacks still require an external boundary.
    No saved manifest can be loaded as authority or unlock an execution path.
    """

    head_sha: str
    tree_sha: str
    content: tuple[tuple[str, str, str], ...]
    inventory: tuple[tuple[str, int, str], ...]

    @property
    def content_digest(self) -> str:
        return digest({"head": self.head_sha, "tree": self.tree_sha, "files": self.content})

    @classmethod
    def capture(cls, workspace: GitWorkspace, head_sha: str) -> SnapshotSeal:
        workspace.assert_clean(head_sha)
        content = []
        for entry in workspace.git("ls-tree", "-r", "-z", head_sha, strip=False).split("\0"):
            if not entry:
                continue
            metadata, path = entry.split("\t", 1)
            mode, kind, blob = metadata.split()
            path = relative_path(path)
            if kind != "blob" or mode not in ("100644", "100755"):
                raise TeamError("Snapshot requires literal regular Git files")
            candidate = workspace.root / path
            if any(p.is_symlink() for p in (candidate, *candidate.parents)):
                raise TeamError("Snapshot file traverses a symlink")
            raw = candidate.read_bytes()
            # Git object identity uses SHA-1; SHA-256 separately binds the content.
            actual = hashlib.sha1(
                f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False
            ).hexdigest()
            executable = bool(candidate.stat().st_mode & 0o111)
            if actual != blob or executable != (mode == "100755"):
                raise TeamError("Snapshot bytes or mode differ from the claimed Git commit")
            content.append((path, mode, hashlib.sha256(raw).hexdigest()))
        return cls(
            head_sha,
            workspace.git("rev-parse", f"{head_sha}^{{tree}}"),
            tuple(content),
            _inventory(workspace),
        )

    def verify(self, workspace: GitWorkspace) -> None:
        # Check Git metadata before invoking Git again; it is also untrusted output.
        if _inventory(workspace) != self.inventory:
            raise TeamError("Snapshot content or Git metadata mutated; evidence invalidated")
        workspace.assert_clean(self.head_sha)

