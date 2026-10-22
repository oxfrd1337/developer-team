"""Read-only DT-008 operating-route inspection; never an execution authority.

No supplied report, task receipt, signature or operator text is accepted here.
The observed Cloud interface lacks critical controls, so there is no GO path.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path
from uuid import uuid4

from .adapters.codex_cloud import CodexCloudGateway
from .config import load_config
from .models import TeamError
from .pilot_scope import PILOT_REPOSITORY, PILOT_WRITABLE
from .workspace import GitWorkspace

BLOCKERS = {
    "role-boundaries": "Independent repo/secret/network/write controls per role not attested",
    "external-controller": "Controller, grant, journal and collector outside agent reach unproved",
    "review-snapshot": "QA/Security immutable same-HEAD sources and separate identities unproved",
    "provider-stop": "CLI 0.163.0 exposes no remote cancel or authoritative stop acknowledgement",
    "provider-idempotency": "No provider idempotency key; unknown submission must never retry",
    "usage-limit": "No independently verified remaining quota or enforced provider cost cap",
    "github-protection": "Effective strict branch/ruleset protection requires independent API proof",
    "cloud-runtime": "Published role environment IDs and enforced current setup not verified",
}
BASE_SHA = "799f6719dc7c39d64f8738023e4f8fec851ddd21"


def inspect(source: Path) -> dict:
    """Read the checkout and bounded CLI help/status only; no task listing or writes.

    Local hashes bind diagnostics, never authenticate remote evidence. The exact
    effective config digest includes the existing controller instruction/policy seal.
    """
    workspace = GitWorkspace(source)
    config = load_config(source / "examples/project.pilot.toml")
    _, sealed = workspace.instructions(config)
    now = time.time()
    blockers = dict(BLOCKERS)
    try:
        workspace.git("merge-base", "--is-ancestor", BASE_SHA, workspace.head)
    except TeamError:
        blockers["basis"] = "Confirmed main after PR #9 is not an ancestor"
    if config.repository != PILOT_REPOSITORY or config.auto_merge:
        blockers["scope"] = "Unexpected repository or automatic merge enabled"
    try:
        workspace.assert_clean()
    except TeamError:
        blockers["checkout"] = "Controller checkout is dirty or cannot be verified"
    try:
        probe = CodexCloudGateway().probe()
    except TeamError:
        probe = {"status": "UNSUPPORTED", "reason": "CLI help/auth inspection unavailable"}
    return {
        "schema_version": 1,
        "mode": "read-only-preflight",
        "decision": "BLOCKED",
        "live": "NO-GO",
        "cloud_dispatch_authorized": False,
        "repository": config.repository,
        "run_id": str(uuid4()),
        "controller_sha": workspace.head,
        "base_sha": BASE_SHA,
        "base_observation": "GitHub main confirmed 2026-10-22; not a fresh remote HEAD query",
        "head_sha": workspace.head,
        "tree_sha": workspace.git("rev-parse", "HEAD^{tree}").strip(),
        "config_digest": sealed,
        "observed_at": now,
        "expires_at": now + 300,
        "lease_authority": False,
        "versions": {"python": platform.python_version(), "codex": probe},
        "roles": ["orchestrator/architecture", "developer", "qa", "security"],
        "allowed_paths": list(PILOT_WRITABLE),
        "cloud_environment_ids": None,
        "host_identities": None,
        "task_status": "UNSUPPORTED: no task submitted or account tasks listed",
        "stop_contract": "UNSUPPORTED: local timeout does not cancel remote work or billing",
        "submission_recovery": "Unknown receipt: stop, reconcile externally, never resubmit",
        "source_test_reviewer_attestation": "UNSUPPORTED: no independent provider attestation",
        "github_protection": "UNSUPPORTED: not queried by this offline command",
        "usage_budget": None,
        "observations": [
            {"control": key, "status": "UNSUPPORTED", "reason": reason}
            for key, reason in blockers.items()
        ],
        "operator_decision": "Decide external managed runner architecture and its cost envelope",
        "decision_record": {
            "state": "awaiting-architecture-decision",
            "pilot_approval": "NOT-GRANTED",
            "real_submissions": 0,
            "automatic_merge": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        report = inspect(args.source.resolve())
    except (TeamError, OSError):
        report = {"decision": "BLOCKED", "live": "NO-GO", "reason": "Inspection unavailable"}
    print(json.dumps(report, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
