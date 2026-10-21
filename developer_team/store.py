"""Transactional SQLite run journal with exclusive process locks (Linux/macOS)."""

from __future__ import annotations

import fcntl
import json
import sqlite3
from collections.abc import Iterator
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
                CREATE TABLE IF NOT EXISTS cloud_tasks (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    task_id TEXT UNIQUE, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cloud_limits (
                    run_id TEXT PRIMARY KEY, digest TEXT NOT NULL, started_at REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            # sqlite3.Connection.__exit__ commits/rolls back but does not close.
            # Repeated polls/checkpoints must not rely on garbage collection.
            connection.close()

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

    def has_run(self, run_id: str) -> bool:
        with self.connect() as connection:
            return (
                connection.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
                is not None
            )

    def events(self, run_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT sequence, kind, created_at FROM events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [{"sequence": row[0], "kind": row[1], "created_at": row[2]} for row in rows]

    def cloud_task(self, job_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM cloud_tasks WHERE id = ?", (job_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def reserve_cloud_task(
        self, record: dict, limits_digest: str, max_tasks: int, now: float, runtime: int
    ) -> bool:
        """Persist intent and charge the task budget BEFORE any external write."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            limit = connection.execute(
                "SELECT digest, started_at FROM cloud_limits WHERE run_id = ?", (record["run_id"],)
            ).fetchone()
            if limit and (limit[0] != limits_digest or now - limit[1] >= runtime):
                raise TeamError("Cloud approval changed or total runtime limit reached")
            if not limit:
                connection.execute(
                    "INSERT INTO cloud_limits VALUES (?, ?, ?)",
                    (record["run_id"], limits_digest, now),
                )
            if connection.execute(
                "SELECT 1 FROM cloud_tasks WHERE id = ?", (record["id"],)
            ).fetchone():
                return False
            count = connection.execute(
                "SELECT count(*) FROM cloud_tasks WHERE run_id = ?", (record["run_id"],)
            ).fetchone()[0]
            if count >= max_tasks:
                raise TeamError("Cloud task budget exhausted; manual escalation required")
            connection.execute(
                "INSERT INTO cloud_tasks VALUES (?, ?, NULL, ?)",
                (record["id"], record["run_id"], json.dumps(record, sort_keys=True)),
            )
            return True

    def save_cloud_task(self, record: dict, event: str) -> None:
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    "UPDATE cloud_tasks SET task_id = ?, payload = ? WHERE id = ?",
                    (record.get("task_id"), json.dumps(record, sort_keys=True), record["id"]),
                )
            except sqlite3.IntegrityError as exc:
                raise TeamError("Cloud task ID reused for another job or role") from exc
            if cursor.rowcount != 1:
                raise TeamError("Cloud job intent missing")
            connection.execute(
                "INSERT INTO events(run_id, kind, payload) VALUES (?, ?, ?)",
                (record["run_id"], "cloud:" + event, json.dumps(record, sort_keys=True)),
            )

    def cloud_tasks(self, run_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM cloud_tasks WHERE run_id = ? ORDER BY rowid", (run_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def check_cloud_limits(self, run_id: str, limits_digest: str, now: float, runtime: int) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT digest, started_at FROM cloud_limits WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None or row[0] != limits_digest or not 0 <= now - row[1] < runtime:
            raise TeamError("Cloud approval changed or total runtime limit reached")

    def initialize_exec_journal(self) -> None:
        # Keep the Cloud checkpoint schema unchanged; exec journals are not portable
        # Cloud sessions and must be rejected by the existing Cloud import checks.
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS exec_calls ("
                "id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def reserve_exec_call(self, record: dict, now: float) -> None:
        """Atomic exec intent + total call/runtime budget, separate from Cloud."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT payload FROM exec_calls WHERE run_id = ?", (record["run_id"],)
            ).fetchall()
            previous = [json.loads(row[0]) for row in rows]
            limits = record["limits"]
            if previous and (
                any(p["limits"] != limits for p in previous)
                or not 0 <= now - min(p["created_at"] for p in previous) < limits["runtime_seconds"]
            ):
                raise TeamError("Exec limits changed or runtime exhausted")
            if len(previous) >= limits["max_calls"]:
                raise TeamError("Exec call budget exhausted")
            try:
                connection.execute(
                    "INSERT INTO exec_calls VALUES (?, ?, ?)",
                    (record["id"], record["run_id"], json.dumps(record, sort_keys=True)),
                )
            except sqlite3.IntegrityError as exc:
                raise TeamError(
                    "Exec intent already exists; reconcile manually, never retry"
                ) from exc
            connection.execute(
                "INSERT INTO events(run_id, kind, payload) VALUES (?, 'exec:intent', ?)",
                (record["run_id"], json.dumps(record, sort_keys=True)),
            )

    def finish_exec_call(self, record: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE exec_calls SET payload = ? WHERE id = ?",
                (json.dumps(record, sort_keys=True), record["id"]),
            )
            connection.execute(
                "INSERT INTO events(run_id, kind, payload) VALUES (?, ?, ?)",
                (record["run_id"], "exec:" + record["state"], json.dumps(record, sort_keys=True)),
            )

    def exec_calls(self, run_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM exec_calls WHERE run_id = ? ORDER BY rowid", (run_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_exec_verification(self, job_id: str, verification: dict) -> None:
        """Diagnostic provenance only; this journal cannot issue trusted receipts."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM exec_calls WHERE id = ?", (job_id,)
            ).fetchone()
            record = json.loads(row[0]) if row else {}
            if record.get("state") != "completed" or "controller_verification" in record:
                raise TeamError("Exec verification requires a unique completed transport")
            record["controller_verification"] = verification
            payload = json.dumps(record, sort_keys=True)
            connection.execute(
                "UPDATE exec_calls SET payload = ? WHERE id = ?", (payload, job_id)
            )
            connection.execute(
                "INSERT INTO events(run_id, kind, payload) VALUES (?, 'exec:controller-verified', ?)",
                (record["run_id"], payload),
            )

    def check_exec_runtime(self, run_id: str, now: float) -> None:
        records = self.exec_calls(run_id)
        if not records or not (
            0 <= now - records[0]["created_at"] < records[0]["limits"]["runtime_seconds"]
        ):
            raise TeamError("Exec total runtime exhausted; discard output")
