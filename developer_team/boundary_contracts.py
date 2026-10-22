"""Model-free contract demos; never a broker service or production supervisor."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .host_readiness import ReadinessBinding, _time
from .models import PermissionDenied, TeamError
from .snapshot import SnapshotSeal
from .workspace import GitWorkspace


@dataclass(frozen=True)
class SyntheticPeer:
    client: str
    role: str
    binding: ReadinessBinding


class ContractOnlyBroker:
    """In-memory synthetic identity pinning, NOT authentication or model access.

    A future service must derive the peer outside the request (host credentials or
    mTLS), hold auth itself and expose no generic HTTP/exec/refresh/proxy method.
    This demo accepts only the exact controller-created peer object and a literal
    fake token. It has no socket, credentials, provider SDK or forwarding method.
    """

    def __init__(self, peer: SyntheticPeer):
        peer.binding.validate()
        if peer.role not in ("orchestrator", "developer", "qa", "security") or not peer.client:
            raise PermissionDenied("Invalid synthetic peer")
        self.peer = peer
        self.consumed = False

    def demonstrate(self, peer, binding, operation, fake_token, *, now):
        _time(now)
        if (
            peer is not self.peer
            or binding != self.peer.binding
            or now >= self.peer.binding.expires_at
            or operation != "synthetic-model-response"
            or fake_token != "DT007-NOT-A-CREDENTIAL"
            or self.consumed
        ):
            raise PermissionDenied("Contract-only broker rejected request")
        self.consumed = True
        return {"origin": "simulated", "execution_attested": False, "response": "CANARY"}


@dataclass(frozen=True)
class LeaseBudget:
    expires_at: float
    cpu_total_seconds: int
    memory_total_bytes: int
    pids_total: int

    def validate(self, now):
        _time(now)
        _time(self.expires_at)
        if not 0 < self.expires_at - now <= 3600:
            raise PermissionDenied("Expired or excessive absolute lease")
        for value, upper in (
            (self.cpu_total_seconds, 30),
            (self.memory_total_bytes, 1073741824),
            (self.pids_total, 16),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise PermissionDenied("Invalid aggregate contract budget")


def reserve_synthetic_intent(path: Path, binding: ReadinessBinding, budget: LeaseBudget, *, now):
    """Durable exclusive intent demo. NO process launch; never resume/refund it.

    The directory must be controller-owned. Same-UID unlink/tampering is NOT
    prevented. In production an independent supervisor must own this journal.
    Any incomplete write remains an uncertain consumed intent, not a retry permit.
    """
    binding.validate()
    budget.validate(now)
    if budget.expires_at != binding.expires_at:
        raise PermissionDenied("Lease binding mismatch")
    payload = {
        "diagnostic_only": True,
        "state": "uncertain",
        "reason": "No independent supervisor; no process started",
        "binding": asdict(binding),
        "budget": asdict(budget),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return payload


@dataclass(frozen=True)
class ReviewSourceContract:
    """Detect persistent changes in trusted copies; cannot enforce readonly mounts."""

    head_sha: str
    tree_sha: str
    content_digest: str

    @classmethod
    def capture(cls, controller: GitWorkspace, head_sha: str):
        seal = SnapshotSeal.capture(controller, head_sha)
        return cls(seal.head_sha, seal.tree_sha, seal.content_digest)

    def check_pair(self, qa: GitWorkspace, security: GitWorkspace):
        qa_root, security_root = qa.root.resolve(), security.root.resolve()
        if (
            qa_root == security_root
            or qa_root in security_root.parents
            or security_root in qa_root.parents
        ):
            raise TeamError("Review copies must be separate")
        seals = tuple(SnapshotSeal.capture(w, self.head_sha) for w in (qa, security))
        if any(
            (s.tree_sha, s.content_digest) != (self.tree_sha, self.content_digest)
            for s in seals
        ):
            raise TeamError("Review source differs from controller binding")
        return seals
