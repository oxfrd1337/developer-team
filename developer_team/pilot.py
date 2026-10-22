"""DT-003 operator preparation and test-only wiring of the existing Engine."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from .adapters.cloud_agents import CloudPreviewDelivery, CodexCloudAgents, cloud_authority
from .adapters.cloud_contracts import CloudApproval, fields, strict_json
from .adapters.cloud_results import CloudResultImporter
from .adapters.pilot_fake import PILOT_WRITABLE, RehearsalCloudGateway
from .authority import ProjectGrant, RuntimePolicy
from .config import load_config
from .engine import Engine
from .models import Origin, Role, RunStatus, TeamError
from .pilot_scope import PILOT_REPOSITORY
from .store import RunStore
from .workspace import GitWorkspace

SCENARIOS = ("happy", "test-fix", "qa-fix", "repair-limit")
SESSION_FIELDS = {
    "schema_version",
    "mode",
    "run_id",
    "repository",
    "controller_sha",
    "config_digest",
    "scenario",
    "max_tasks",
    "runtime_seconds",
    "max_repairs",
    "created_at",
    "simulation_time",
    "ticks",
}


def empty_directory(path: Path) -> Path:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise TeamError("Pilot directories must not use symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(path.iterdir()):
        raise TeamError("Pilot destination must be empty; existing state is never overwritten")
    return path.resolve()


def write_json(path: Path, value: dict) -> None:
    # Atomic replacement ensures a cancelled runner cannot leave truncated JSON.
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        temporary.chmod(0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_session(root: Path) -> dict:
    session = strict_json((root / "session.json").read_text(encoding="utf-8"))
    fields(session, SESSION_FIELDS)
    try:
        UUID(session["run_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise TeamError("Invalid rehearsal run UUID") from exc
    if (
        type(session["schema_version"]) is not int
        or session["schema_version"] != 1
        or session["mode"] != "test-adapters-only"
        or session["repository"] != PILOT_REPOSITORY
        or not isinstance(session["controller_sha"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", session["controller_sha"])
        or not isinstance(session["config_digest"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", session["config_digest"])
        or session["scenario"] not in SCENARIOS
    ):
        raise TeamError("Invalid or non-rehearsal pilot session; live dispatch is unavailable")
    for key, low, high in (
        ("max_tasks", 1, 8),
        ("runtime_seconds", 60, 3600),
        ("max_repairs", 0, 3),
        ("ticks", 0, 32),
    ):
        if type(session[key]) is not int or not low <= session[key] <= high:
            raise TeamError("Invalid rehearsal budget")
    if (
        any(
            type(session[key]) not in (int, float) or not math.isfinite(session[key])
            for key in ("created_at", "simulation_time")
        )
        or session["simulation_time"] < session["created_at"]
    ):
        raise TeamError("Invalid rehearsal clock")
    return session


def session_store(root: Path) -> RunStore:
    path = root / "state.sqlite3"
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise TeamError("Pilot journal is missing; never start fresh under an existing run ID")
    # Read-only validation precedes RunStore's schema initialization. An unrelated
    # SQLite file must not silently become a fresh journal under a live session.
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            schema = connection.execute("SELECT type, name FROM sqlite_master").fetchall()
            if (
                connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]
                or {name for kind, name in schema if kind == "table"}
                != {
                    "runs",
                    "events",
                    "cloud_tasks",
                    "cloud_limits",
                    "sqlite_sequence",
                }
                or any(kind not in ("table", "index") for kind, _ in schema)
            ):
                raise TeamError("Pilot journal schema or integrity is invalid; reconcile manually")
    except sqlite3.Error as exc:
        raise TeamError("Pilot journal is unreadable; never recreate it automatically") from exc
    return RunStore(path)


def pilot_config(workspace: GitWorkspace, session: dict):
    config = replace(
        load_config(workspace.root / "examples/project.pilot.toml"),
        max_repairs=session["max_repairs"],
    )
    if config.repository != PILOT_REPOSITORY or config.auto_merge:
        raise TeamError("Pilot configuration changed repository or merge policy")
    return config


def prepare_session(
    source: Path,
    output: Path,
    *,
    scenario: str = "qa-fix",
    max_tasks: int = 8,
    runtime_seconds: int = 600,
    max_repairs: int = 1,
) -> dict:
    source_workspace = GitWorkspace(source)
    now = time.time()
    session = {
        "schema_version": 1,
        "mode": "test-adapters-only",
        "run_id": str(uuid4()),
        "repository": PILOT_REPOSITORY,
        "controller_sha": source_workspace.head,
        "config_digest": "0" * 64,
        "scenario": scenario,
        "max_tasks": max_tasks,
        "runtime_seconds": runtime_seconds,
        "max_repairs": max_repairs,
        "created_at": now,
        "simulation_time": now,
        "ticks": 0,
    }
    root = empty_directory(output)
    write_json(root / "session.json", session)
    read_session(root)  # Validate budgets before executing even local preparation.
    source_workspace.git(
        "clone", "--quiet", "--no-hardlinks", "--", str(source), str(root / "project")
    )
    workspace = GitWorkspace(root / "project")
    workspace.git("checkout", "--detach", session["controller_sha"])
    workspace.git("remote", "remove", "origin")
    config = pilot_config(workspace, session)
    workspace.read("pilot_project/requirement.txt")
    _, session["config_digest"] = workspace.instructions(config)
    write_json(root / "session.json", session)
    RunStore(root / "state.sqlite3")
    return write_report(root)


def rehearsal_engine(root: Path, session: dict) -> Engine:
    workspace = GitWorkspace(root / "project")
    config = pilot_config(workspace, session)
    _, sealed = workspace.instructions(config)
    if sealed != session["config_digest"]:
        raise TeamError("Pilot instructions/configuration changed; never reset the run budget")
    store = session_store(root)
    # These fixed fake environments and this approval can reach only the in-process double.
    approval = CloudApproval(
        session["run_id"],
        PILOT_REPOSITORY,
        sealed,
        "test-adapter-driver-only",
        session["created_at"] + session["runtime_seconds"],
        max_tasks=session["max_tasks"],
        runtime_seconds=session["runtime_seconds"],
        task_timeout_seconds=min(300, session["runtime_seconds"]),
    )
    grant = ProjectGrant(
        config.id,
        config.repository,
        sealed,
        frozenset({"read", "develop", "cloud_submit", "cloud_publish", "pull_request"}),
        approved_by="test-adapter-driver-only",
        cloud_environments=tuple((role, "simulated-" + role.value) for role in Role),
    )
    policy = RuntimePolicy(False, False, True, PILOT_REPOSITORY)
    gateway = RehearsalCloudGateway(
        workspace, store, session["run_id"], session["scenario"],
        now=lambda: session["simulation_time"],
    )
    agents = CodexCloudAgents(gateway, approval, grant, policy)
    # Even the raw audit evidence must identify fake provider responses as simulated.
    agents.simulated = True
    agents.review_origin = Origin.SIMULATED
    agents.importer = CloudResultImporter(allowed_paths=PILOT_WRITABLE)
    authority = cloud_authority(grant)
    authority.issuers = {
        issuer: (
            role,
            frozenset({Origin.SIMULATED}) if issuer.startswith("codex-cloud:") else origins,
        )
        for issuer, (role, origins) in authority.issuers.items()
    }
    return Engine(
        config=config,
        workspace=workspace,
        agents=agents,
        delivery=CloudPreviewDelivery(workspace, config.repository),
        store=store,
        authority=authority,
        grant=grant,
        policy=policy,
    )


def step_rehearsal(root: Path, *, ticks: int = 1) -> dict:
    if type(ticks) is not int or not 1 <= ticks <= 24:
        raise TeamError("A runner may execute between 1 and 24 bounded rehearsal ticks")
    session = read_session(root)
    with session_store(root).lock("00000000-0000-0000-0000-000000000003"):
        # Separate operator lock; Engine retains ownership of its own per-run lock.
        session = read_session(root)
        for _ in range(ticks):
            store = session_store(root)
            if store.has_run(session["run_id"]):
                run = store.load(session["run_id"])
                if run.status not in (RunStatus.RUNNING, RunStatus.PAUSED):
                    break
            elif session["ticks"]:
                raise TeamError("Pilot run disappeared from its journal; reconcile before resume")
            if session["ticks"] >= 32:
                raise TeamError("Persistent rehearsal invocation limit reached")
            session["ticks"] += 1
            session["simulation_time"] += 10
            write_json(root / "session.json", session)
            engine = rehearsal_engine(root, session)
            engine.execute(engine.workspace.read("pilot_project/requirement.txt"))
        return write_report(root)


def write_report(root: Path) -> dict:
    session = read_session(root)
    workspace = GitWorkspace(root / "project")
    store = session_store(root)
    run = store.load(session["run_id"]) if store.has_run(session["run_id"]) else None
    tasks = store.cloud_tasks(session["run_id"])
    report = {
        "mode": "test-adapters-only",
        "agent_actions": "simulated",
        "local_checks": "real subprocesses on synthetic code",
        "cloud_execution_verified": False,
        "real_cloud_submissions": 0,
        "real_remote_mutations": 0,
        "merge_enabled": False,
        "run_id": session["run_id"],
        "controller_sha": session["controller_sha"],
        "head_sha": workspace.head,
        "config_digest": session["config_digest"],
        "status": run.status.value if run else "prepared",
        "stage": run.stage.value if run else "analysis",
        "repairs": run.repairs if run else {},
        "budgets": {key: session[key] for key in ("max_tasks", "runtime_seconds", "max_repairs")},
        "ticks": session["ticks"],
        "checks": {e.kind: e.outcome.value for e in run.evidence if e.kind.startswith("check:")}
        if run
        else {},
        "changed_paths": list(workspace.changed_paths(session["controller_sha"])),
        "tasks": [
            {
                "job_id": t["id"],
                "task_id": t["task_id"],
                "role": t["job"]["role"],
                "head_sha": t["job"]["head_sha"],
                "state": t["state"],
                "polls": t["polls"],
                "read_errors": t["read_errors"],
            }
            for t in tasks
        ],
        "events": store.events(session["run_id"]),
        "reasons": run.reasons if run else ["Separate live approval has not been granted"],
    }
    write_json(root / "report.json", report)
    return report
