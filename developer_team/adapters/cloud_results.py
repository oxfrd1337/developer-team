"""Validate Cloud diffs in a disposable checkout before importing source changes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..config import ProjectConfig, matches, relative_path
from ..models import Role, TeamError
from ..workspace import GitWorkspace
from .cloud_contracts import RESULT_PATH, CloudJob, strict_json


class CloudResultImporter:
    def __init__(self, *, allowed_paths: tuple[str, ...] | None = None):
        # Controller-owned scope; project instructions cannot widen it.
        self.allowed_paths = allowed_paths

    def extract(
        self, workspace: GitWorkspace, config: ProjectConfig, job: CloudJob, patch: str
    ) -> tuple[dict, str]:
        workspace.assert_clean(job.head_sha)
        if (workspace.root / RESULT_PATH).exists():
            raise TeamError("Cloud result artifact must not exist in the input checkout")
        if any(
            marker in patch for marker in ("GIT binary patch", "Binary files ", "Subproject commit")
        ):
            raise TeamError("Binary and submodule cloud patches are unsupported")
        with tempfile.TemporaryDirectory(prefix="dt-cloud-import-") as directory:
            root = Path(directory)
            checkout = root / "checkout"
            workspace.git(
                "clone",
                "--quiet",
                "--no-hardlinks",
                "--no-checkout",
                "--",
                str(workspace.root),
                str(checkout),
            )
            staged = GitWorkspace(checkout)
            staged.git("checkout", "--detach", job.head_sha)
            patch_path = root / "result.patch"
            patch_path.write_text(patch, encoding="utf-8")
            staged.git("apply", "--check", "--index", str(patch_path))
            staged.git("apply", "--index", str(patch_path))
            # Reject every newly introduced symlink/gitlink, including the result artifact.
            raw = staged.git("diff", "--cached", "--raw", "--no-renames", strip=False).splitlines()
            if any(line.split()[1] not in ("000000", "100644", "100755") for line in raw):
                raise TeamError("Cloud patch introduces an unsupported file type")
            payload = job.validate_result(strict_json(staged.read(RESULT_PATH)))
            staged.git("rm", "--force", "--", RESULT_PATH)
            paths = tuple(
                p
                for p in staged.git(
                    "diff", "--cached", "--name-only", "--no-renames", "-z", strip=False
                ).split("\0")
                if p
            )
            for path in paths:
                relative_path(path)
                if self.allowed_paths is not None and not matches(path, self.allowed_paths):
                    raise TeamError("Cloud source import exceeds the controller's pilot scope")
                if ".git" in Path(path).parts or config.protected(path):
                    raise TeamError(
                        "Cloud source import touches protected controls; manual review required"
                    )
            if job.role != Role.DEVELOPER and paths:
                raise TeamError("Planning/QA/security task attempted to modify repository source")
            if job.role == Role.DEVELOPER and not paths:
                raise TeamError("Cloud developer produced no source changes")
            source_patch = staged.git(
                "diff", "--cached", "--no-ext-diff", "--no-textconv", strip=False
            )
            workspace.assert_clean(job.head_sha)
            return payload, source_patch

    def apply(self, workspace: GitWorkspace, job: CloudJob, patch: str) -> None:
        workspace.assert_clean(job.head_sha)
        with tempfile.TemporaryDirectory(prefix="dt-cloud-apply-") as directory:
            path = Path(directory) / "source.patch"
            path.write_text(patch, encoding="utf-8")
            workspace.git("apply", "--check", str(path))
            workspace.git("apply", str(path))
