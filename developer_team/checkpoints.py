"""Portable, integrity-checked rehearsal checkpoints. No live credential export."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from .adapters.cloud_contracts import fields, strict_json
from .models import TeamError
from .pilot import (
    empty_directory,
    read_session,
    rehearsal_engine,
    session_store,
    write_json,
    write_report,
)
from .store import RunStore
from .workspace import GitWorkspace

FILES = ("session.json", "state.sqlite3", "checkout.bundle")
OPERATOR_LOCK = "00000000-0000-0000-0000-000000000003"


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checkpoint(root: Path, output: Path) -> dict:
    session = read_session(root)
    store = session_store(root)
    with store.lock(OPERATOR_LOCK), store.lock(session["run_id"]):
        workspace = GitWorkspace(root / "project")
        workspace.assert_clean()
        destination = empty_directory(output)
        with store.connect() as source, sqlite3.connect(destination / "state.sqlite3") as target:
            source.backup(target)
        (destination / "session.json").write_bytes((root / "session.json").read_bytes())
        workspace.git("bundle", "create", str(destination / "checkout.bundle"), "HEAD")
        for name in FILES:
            (destination / name).chmod(0o600)
        manifest = {
            "schema_version": 1,
            "mode": "test-adapters-only",
            "run_id": session["run_id"],
            "controller_sha": session["controller_sha"],
            "head_sha": workspace.head,
            "files": {name: _sha(destination / name) for name in FILES},
        }
        write_json(destination / "manifest.json", manifest)
        return manifest


def restore_checkpoint(
    checkpoint_path: Path, output: Path, *, controller_sha: str, run_id: str
) -> dict:
    # A checksum establishes integrity, never authenticity or permission to dispatch.
    # The workflow separately verifies the exact producer run and artifact via GitHub.
    if set(p.name for p in checkpoint_path.iterdir()) != {*FILES, "manifest.json"}:
        raise TeamError("Checkpoint has missing or unexpected files")
    for path in checkpoint_path.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_000_000:
            raise TeamError("Unsupported checkpoint file type or size")
    manifest = strict_json((checkpoint_path / "manifest.json").read_text(encoding="utf-8"))
    fields(manifest, {"schema_version", "mode", "run_id", "controller_sha", "head_sha", "files"})
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["mode"] != "test-adapters-only"
        or manifest["controller_sha"] != controller_sha
        or manifest["run_id"] != run_id
        or not isinstance(manifest["head_sha"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", manifest["head_sha"])
        or not isinstance(manifest["files"], dict)
        or manifest["files"] != {name: _sha(checkpoint_path / name) for name in FILES}
    ):
        raise TeamError("Checkpoint integrity or controller/run binding mismatch")
    session = read_session(checkpoint_path)
    if session["controller_sha"] != controller_sha or session["run_id"] != run_id:
        raise TeamError("Checkpoint session binding mismatch")
    destination = empty_directory(output)
    for name in ("session.json", "state.sqlite3"):
        (destination / name).write_bytes((checkpoint_path / name).read_bytes())
        (destination / name).chmod(0o600)
    try:
        with sqlite3.connect(
            (destination / "state.sqlite3").as_uri() + "?mode=ro", uri=True
        ) as connection:
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise TeamError("Checkpoint SQLite integrity check failed")
            schema = connection.execute("SELECT type, name FROM sqlite_master").fetchall()
            tables = {name for kind, name in schema if kind == "table"}
            if tables != {
                "runs",
                "events",
                "cloud_tasks",
                "cloud_limits",
                "sqlite_sequence",
            } or any(kind not in ("table", "index") for kind, _ in schema):
                raise TeamError("Checkpoint SQLite schema is incomplete or unexpected")
            runs = connection.execute("SELECT id FROM runs").fetchall()
            task_runs = connection.execute("SELECT DISTINCT run_id FROM cloud_tasks").fetchall()
            limit_runs = connection.execute("SELECT run_id FROM cloud_limits").fetchall()
            event_runs = connection.execute("SELECT DISTINCT run_id FROM events").fetchall()
            if any(
                rows not in ([], [(run_id,)]) for rows in (runs, task_runs, limit_runs, event_runs)
            ):
                raise TeamError("Checkpoint contains unrelated runs")
    except sqlite3.Error as exc:
        raise TeamError("Checkpoint SQLite database is unreadable") from exc
    store = RunStore(destination / "state.sqlite3")
    # Use the existing GitWorkspace command runner: no shell, no inherited credentials.
    # An empty Git seed permits cloning without executing code from the bundle.
    import subprocess

    from .workspace import minimal_environment

    try:
        subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "clone",
                "--quiet",
                "--no-checkout",
                "--",
                str(checkpoint_path.resolve() / "checkout.bundle"),
                str(destination / "project"),
            ],
            env=minimal_environment(),
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TeamError("Checkpoint Git bundle could not be restored") from exc
    workspace = GitWorkspace(destination / "project")
    workspace.git("checkout", "--detach", manifest["head_sha"])
    workspace.git("remote", "remove", "origin")
    workspace.git("merge-base", "--is-ancestor", controller_sha, workspace.head)
    # Fixed test backend: restored JSON can never select a live gateway or grant.
    engine = rehearsal_engine(destination, session)
    changed = workspace.changed_paths(controller_sha)
    if any(path not in engine.agents.importer.allowed_paths for path in changed):
        raise TeamError("Checkpoint source exceeds the controller's pilot scope")
    if store.has_run(run_id):
        run = store.load(run_id)
        if (
            run.repository != session["repository"]
            or run.config_digest != session["config_digest"]
            or run.head_sha != workspace.head
        ):
            raise TeamError("Checkpoint journal and checkout disagree")
        # Only the checkout's absolute location changes. All task IDs, limits, SHAs,
        # requirements and audit events remain; Engine rechecks process-local proofs.
        run.workspace = str(workspace.root)
        store.save(run, "rehearsal_workspace_relocated")
    return write_report(destination)


def validate_artifact_source(run: dict, artifact: dict, *, repository: str, sha: str) -> None:
    """Accept only an exact successful manual producer at the same reviewed commit."""
    run_id = run.get("id")
    attempt = run.get("run_attempt")
    if (
        type(run_id) is not int
        or type(attempt) is not int
        or run.get("repository", {}).get("full_name") != repository
        or run.get("head_sha") != sha
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != ".github/workflows/cloud-pilot.yml"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or artifact.get("expired") is not False
        or artifact.get("name") != f"dt-003-checkpoint-{run_id}-{attempt}"
        or artifact.get("workflow_run", {}).get("id") != run_id
        or artifact.get("workflow_run", {}).get("head_sha") != sha
    ):
        raise TeamError("Checkpoint producer provenance is missing, stale or untrusted")


def check_artifact_source(transport, *, repository, sha, source_run, artifact_id) -> None:
    if repository != "oxfrd1337/developer-team" or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise TeamError("Artifact lookup is restricted to the pilot repository and exact commit")
    if any(not re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in (source_run, artifact_id)):
        raise TeamError("Exact numeric source run and artifact IDs are required")
    run = transport.request("GET", f"repos/{repository}/actions/runs/{source_run}")
    artifact = transport.request("GET", f"repos/{repository}/actions/artifacts/{artifact_id}")
    if run.get("id") != int(source_run) or artifact.get("id") != int(artifact_id):
        raise TeamError("Artifact lookup returned conflicting IDs")
    validate_artifact_source(run, artifact, repository=repository, sha=sha)
