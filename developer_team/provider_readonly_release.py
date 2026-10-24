"""Offline release integrity; approval is provisioned independently outside the checkout."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import tempfile
from pathlib import Path

from .adapters.agents_api_contracts import AgentsAPIError

_LIMIT = 16 * 1024 * 1024


def _blocked():
    return AgentsAPIError("release_integrity_required")


def _approval_path():
    # HOME/XDG/GIT environment values must not select the trust anchor.
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".config/developer-team/readonly-release.json"


def _git(root, *args):
    result = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            *args,
        ],
        cwd=root,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode or len(result.stdout) > _LIMIT:
        raise _blocked()
    return result.stdout


def _read_regular(path, limit):
    # Reject symlink directories as well as symlink files, before reading bytes.
    for parent in (path, *path.parents):
        if stat.S_ISLNK(parent.lstat().st_mode):
            raise _blocked()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise _blocked()
        raw = stream.read(limit + 1)
        final = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_uid")
    if len(raw) > limit or any(getattr(info, name) != getattr(final, name) for name in fields):
        raise _blocked()
    return raw, info


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _blocked()
        value[key] = item
    return value


def _approval(root):
    path = _approval_path()
    if path.is_relative_to(root):
        raise _blocked()
    raw, info = _read_regular(path, 1024)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o400:
        raise _blocked()
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict or set(value) != {"commit", "tree", "inventory_sha256"}:
        raise _blocked()
    for name, size in (("commit", 40), ("tree", 40), ("inventory_sha256", 64)):
        if (
            type(value[name]) is not str
            or re.fullmatch("[a-f0-9]{" + str(size) + "}", value[name]) is None
        ):
            raise _blocked()
    return value


def _inventory(root):
    if _git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root):
        raise _blocked()
    # Include ignored files: pyc, native modules, startup files and generated
    # packages must not shadow reviewed source. Use a dedicated release checkout.
    if _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored"):
        raise _blocked()
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    tree = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    entries = _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0")
    index = _git(root, "ls-files", "--stage", "-z").split(b"\0")
    expected_index, inventory, sources = [], [], {}
    for entry in filter(None, entries):
        metadata, name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.split(b" ")
        relative = name.decode("utf-8")
        if (
            mode not in {b"100644", b"100755"}
            or kind != b"blob"
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or Path(relative).suffix in {".pyc", ".pyo", ".so", ".pyd", ".pth"}
        ):
            raise _blocked()
        expected_index.append(mode + b" " + oid + b" 0\t" + name)
        raw, info = _read_regular(root / relative, _LIMIT)
        blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
        ).hexdigest()
        if blob != oid.decode():
            raise _blocked()
        executable = bool(info.st_mode & 0o111)
        if executable != (mode == b"100755"):
            raise _blocked()
        inventory.append([relative, mode.decode(), hashlib.sha256(raw).hexdigest()])
        if relative.startswith("developer_team/") and relative.endswith(".py"):
            sources[relative] = raw
    if sorted(filter(None, index)) != sorted(expected_index):
        raise _blocked()
    # Direct hashes also detect assume-unchanged/skip-worktree and stale stat caches.
    digest = hashlib.sha256(json.dumps(inventory, separators=(",", ":")).encode()).hexdigest()
    if _git(root, "rev-parse", "HEAD").decode().strip() != head:
        raise _blocked()
    return {"commit": head, "tree": tree, "inventory_sha256": digest}, sources


def verify_release(root):
    """No CLI/env approval override; no creation or update of the external pin."""
    try:
        expected = _approval(root)
        actual, sources = _inventory(root)
        if actual != expected:
            raise _blocked()
        return sources
    except Exception:
        raise _blocked() from None


@contextlib.contextmanager
def verified_snapshot(root):
    # Copy only already verified Python source bytes. No pyc, import hooks, site
    # packages or later worktree changes enter the isolated runner interpreter.
    sources = verify_release(root)
    with tempfile.TemporaryDirectory(prefix="dt017c-code-") as directory:
        destination = Path(directory)
        for relative, raw in sources.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        yield destination
