"""Controller-owned pilot approval and strict, untrusted agent result contracts."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from uuid import UUID

from ..models import PermissionDenied, Role, TeamError, digest

RESULT_PATH = ".developer-team/cloud-result.json"


def strict_json(raw: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TeamError("Duplicate JSON key in cloud result")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise TeamError("Malformed cloud JSON") from exc
    if not isinstance(value, dict):
        raise TeamError("Cloud JSON must be an object")
    return value


def fields(value: dict, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise TeamError("Missing or unknown cloud result fields")


def text_value(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise TeamError("Missing or invalid cloud result text")
    return value


def strings(value: object, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 100 or (nonempty and not value):
        raise TeamError("Invalid cloud result list")
    result = tuple(text_value(v) for v in value)
    if len(set(result)) != len(result):
        raise TeamError("Duplicate cloud result entries")
    return result


@dataclass(frozen=True)
class CloudApproval:
    """Supplied out of band by a trusted operator, never loaded from project TOML.

    This authorizes a bounded pilot only. It grants no release, merge or deployment.
    Task count is a usage ceiling, not a monetary/provider-side spending guarantee.
    """

    run_id: str
    repository: str
    config_digest: str
    approved_by: str
    expires_at: float
    max_tasks: int = 8
    task_timeout_seconds: int = 900
    runtime_seconds: int = 3600
    max_polls: int = 60
    poll_interval_seconds: int = 10
    max_read_errors: int = 3

    def validate(self, run_id: str, repository: str, config_digest: str, now: float) -> None:
        try:
            UUID(self.run_id)
        except ValueError as exc:
            raise PermissionDenied("Invalid cloud approval run ID") from exc
        if (
            self.run_id != run_id
            or self.repository != repository
            or self.config_digest != config_digest
            or not self.approved_by.strip()
            or not math.isfinite(self.expires_at)
            or now >= self.expires_at
        ):
            raise PermissionDenied("Explicit, current, run-bound cloud approval required")
        for value, low, high in (
            (self.max_tasks, 1, 100),
            (self.task_timeout_seconds, 1, 3600),
            (self.runtime_seconds, 1, 86400),
            (self.max_polls, 1, 1000),
            (self.poll_interval_seconds, 1, 60),
            (self.max_read_errors, 0, 5),
        ):
            if type(value) is not int or not low <= value <= high:
                raise PermissionDenied("Invalid cloud budget or deadline")


@dataclass(frozen=True)
class CloudJob:
    run_id: str
    repository: str
    config_digest: str
    head_sha: str
    role: Role
    cycle: int
    input_digest: str

    @property
    def id(self) -> str:
        return digest(asdict(self))

    @property
    def branch(self) -> str:
        # Dedicated, creation-only ref for each role/round/input; never the working branch.
        return f"dt/cloud/{self.run_id}/{self.role.value}-{self.id[:24]}"

    def envelope(self) -> dict:
        return {
            "schema_version": 1,
            "job_id": self.id,
            "binding": asdict(self),
            "payload": {},
        }

    def validate_result(self, value: dict) -> dict:
        fields(value, {"schema_version", "job_id", "binding", "payload"})
        expected = self.envelope()
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["job_id"] != self.id
            or value["binding"] != expected["binding"]
            or not isinstance(value["payload"], dict)
        ):
            raise TeamError("Stale or conflicting cloud result binding")
        return value["payload"]

    def validate(self) -> None:
        UUID(self.run_id)
        if (
            not re.fullmatch(r"[0-9a-f]{40}", self.head_sha)
            or type(self.cycle) is not int
            or self.cycle < 0
            or not re.fullmatch(r"[0-9a-f]{64}", self.input_digest)
        ):
            raise PermissionDenied("Invalid cloud job binding")
