"""Strict offline diagnostics. No evidence authority, grant or execution interface."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from .models import TeamError

CAPABILITIES = (
    "credential-broker",
    "model-only-egress",
    "external-supervisor",
    "resource-enforcement",
    "host-role-identities",
    "immutable-review",
    "protected-collector",
)
STATUSES = ("PASS", "FAIL", "UNSUPPORTED", "UNKNOWN")


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise TeamError("Readiness requires an exact primitive schema")


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise TeamError("Invalid readiness text")


def _hash(value, length):
    if type(value) is not str or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        raise TeamError("Invalid readiness digest")


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise TeamError("Invalid readiness time")


@dataclass(frozen=True)
class ReadinessBinding:
    run_id: str
    repository: str
    config_digest: str
    base_sha: str
    head_sha: str
    tree_sha: str
    content_digest: str
    controller_commit: str
    check_version: str
    expires_at: float

    def validate(self):
        for value in (self.run_id, self.repository, self.check_version):
            _text(value)
        for value in (self.base_sha, self.head_sha, self.tree_sha, self.controller_commit):
            _hash(value, 40)
        for value in (self.config_digest, self.content_digest):
            _hash(value, 64)
        _time(self.expires_at)

    @classmethod
    def parse(cls, value):
        _fields(value, cls.__dataclass_fields__)
        binding = cls(**value)
        binding.validate()
        return binding


@dataclass(frozen=True)
class CapabilityObservation:
    capability: str
    status: str
    source: str
    artifact_digest: str
    observed_at: float
    reason: str

    @classmethod
    def parse(cls, value):
        _fields(value, cls.__dataclass_fields__)
        result = cls(**value)
        if type(result.capability) is not str or result.capability not in CAPABILITIES:
            raise TeamError("Unknown readiness capability")
        if type(result.status) is not str or result.status not in STATUSES:
            raise TeamError("Unknown readiness status")
        for text in (result.source, result.reason):
            _text(text)
        _hash(result.artifact_digest, 64)
        _time(result.observed_at)
        return result


@dataclass(frozen=True)
class HostReadinessReport:
    binding: ReadinessBinding
    observations: tuple[CapabilityObservation, ...]

    @classmethod
    def parse(cls, value):
        _fields(value, ("schema_version", "diagnostic_only", "binding", "observations"))
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise TeamError("Unknown readiness version")
        if value["diagnostic_only"] is not True or type(value["observations"]) is not list:
            raise TeamError("Readiness is diagnostic only")
        if len(value["observations"]) > 64:
            raise TeamError("Readiness observation budget exceeded")
        return cls(
            ReadinessBinding.parse(value["binding"]),
            tuple(CapabilityObservation.parse(o) for o in value["observations"]),
        )

    def blockers(self, expected: ReadinessBinding, now: float) -> tuple[str, ...]:
        """A claimed PASS is never independent proof; this API cannot return GO."""
        expected.validate()
        _time(now)
        reasons = ["live-exec-unavailable", "independent-attestation-not-implemented"]
        if self.binding != expected:
            reasons.append("binding-mismatch")
        if now >= self.binding.expires_at:
            reasons.append("lease-expired")
        for capability in CAPABILITIES:
            matches = [o for o in self.observations if o.capability == capability]
            if len(matches) != 1:
                reasons.append(f"missing-or-conflicting:{capability}")
            for observation in matches:
                if observation.status != "PASS":
                    reasons.append(f"{observation.status}:{capability}")
                if not 0 <= now - observation.observed_at <= 300:
                    reasons.append(f"stale-observation:{capability}")
                reasons.append(f"unverified-source:{capability}")
        return tuple(reasons)

    def to_dict(self):
        return {
            "schema_version": 1,
            "diagnostic_only": True,
            "binding": asdict(self.binding),
            "observations": [asdict(o) for o in self.observations],
        }
