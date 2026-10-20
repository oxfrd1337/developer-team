"""Transactional SQLite run journal with exclusive process locks (Linux/macOS)."""

from __future__ import annotations

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from .models import (
    Architecture,
    Binding,
    Criterion,
    Evidence,
    FailureClass,
    Finding,
    Origin,
    Outcome,
    Plan,
    PullRequest,
    Role,
    Run,
    RunStatus,
    Stage,
    TeamError,
)


class RunStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    @contextmanager
    def lock(self, run_id: str):
        UUID(run_id)
        lock_path = self.path.parent / f"{run_id}.lock"
        with lock_path.open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TeamError("Another controller owns this run") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def save(self, run: Run, kind: str) -> None:
        payload = json.dumps(asdict(run), sort_keys=True)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, payload) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (run.id, payload),
            )
            connection.execute(
                "INSERT INTO events(run_id, kind, payload) VALUES (?, ?, ?)",
                (run.id, kind, payload),
            )

    def load(self, run_id: str) -> Run:
        UUID(run_id)
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise TeamError("Unknown run")
        data = json.loads(row[0])
        if data["plan"] is not None:
            plan = data["plan"]
            data["plan"] = Plan(
                tuple(Criterion(**c) for c in plan["criteria"]), tuple(plan["tasks"])
            )
        if data["architecture"] is not None:
            item = data["architecture"]
            data["architecture"] = Architecture(
                item["summary"], tuple(item["dependencies"]), tuple(item["risks"])
            )
        data["findings"] = [
            Finding(**(f | {"category": FailureClass(f["category"])})) for f in data["findings"]
        ]
        data["evidence"] = [
            Evidence(
                **(
                    e
                    | {
                        "role": Role(e["role"]),
                        "origin": Origin(e["origin"]),
                        "outcome": Outcome(e["outcome"]),
                        "binding": Binding(**e["binding"]),
                        "covered_criteria": tuple(e["covered_criteria"]),
                        "blockers": tuple(e["blockers"]),
                    }
                )
            )
            for e in data["evidence"]
        ]
        if data["pr"] is not None:
            data["pr"] = PullRequest(**data["pr"])
        data["stage"] = Stage(data["stage"])
        data["status"] = RunStatus(data["status"])
        return Run(**data)

    def events(self, run_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT sequence, kind, created_at FROM events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [{"sequence": row[0], "kind": row[1], "created_at": row[2]} for row in rows]
