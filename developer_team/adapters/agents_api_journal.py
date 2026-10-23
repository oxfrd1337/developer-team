"""DT-016 single-slot SQLite journal, owned and located by the external controller.

No path resolution, repository access, credential storage or implicit re-preparation.
The caller must preserve this database outside the target repository and must not
copy, reset, roll back or concurrently replace it. SQLite is not external authority.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, fields

from .agents_api_contracts import (
    CANARY_MESSAGE,
    AgentsAPIError,
    AgentsAPILimits,
    CanaryBinding,
    CanaryState,
    canonical,
    sha256,
)


class SQLiteCanaryJournal:
    def __init__(self, connection: sqlite3.Connection):
        if type(connection) is not sqlite3.Connection or connection.in_transaction:
            raise AgentsAPIError("exclusive_journal_connection_required")
        self._connection = connection
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS dt016_canary ("
                "slot INTEGER PRIMARY KEY CHECK (slot = 1), "
                "binding TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL)"
            )
            connection.commit()
        except sqlite3.Error:
            raise AgentsAPIError("journal_unavailable") from None

    def prepare(self, binding: CanaryBinding, limits: AgentsAPILimits | None = None) -> None:
        limits = AgentsAPILimits() if limits is None else limits
        if type(limits) is not AgentsAPILimits:
            raise AgentsAPIError("invalid_resource_limits")
        limits.validate()
        state = CanaryState(
            binding.digest, binding.idempotency_key, sha256(CANARY_MESSAGE), sha256(asdict(limits))
        )
        state.validate(binding)
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO dt016_canary VALUES (1, ?, 0, ?)",
                    (binding.digest, canonical(asdict(state)).decode()),
                )
        except sqlite3.Error:
            raise AgentsAPIError("journal_already_bound_or_unavailable") from None

    def load(self, binding: CanaryBinding) -> tuple[int, CanaryState]:
        def pairs(items):
            value = {}
            for key, entry in items:
                if key in value:
                    raise ValueError
                value[key] = entry
            return value

        try:
            row = self._connection.execute(
                "SELECT binding, revision, state FROM dt016_canary WHERE slot = 1"
            ).fetchone()
        except sqlite3.Error:
            raise AgentsAPIError("journal_unavailable") from None
        if row is None:
            raise AgentsAPIError("journal_missing")
        if row[0] != binding.digest:
            raise AgentsAPIError("journal_binding_mismatch")
        if type(row[1]) is not int or row[1] < 0 or type(row[2]) is not str or len(row[2]) > 4096:
            raise AgentsAPIError("invalid_journal_record")
        try:
            value = json.loads(row[2], object_pairs_hook=pairs)
            if type(value) is not dict or set(value) != {
                field.name for field in fields(CanaryState)
            }:
                raise ValueError
            state = CanaryState(**value)
        except (ValueError, TypeError, RecursionError):
            raise AgentsAPIError("invalid_journal_record") from None
        state.validate(binding)
        return row[1], state

    def replace(self, binding: CanaryBinding, revision: int, state: CanaryState) -> None:
        state.validate(binding)
        try:
            with self._connection:
                changed = self._connection.execute(
                    "UPDATE dt016_canary SET revision = revision + 1, state = ? "
                    "WHERE slot = 1 AND binding = ? AND revision = ?",
                    (canonical(asdict(state)).decode(), binding.digest, revision),
                ).rowcount
                if changed != 1:
                    raise AgentsAPIError("journal_conflict_or_missing")
        except sqlite3.Error:
            raise AgentsAPIError("journal_unavailable") from None
