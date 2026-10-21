"""DT-004: concrete operator wiring, never a second workflow or a CLI activation flag.

Preparation is local only. Execution requires existing authority objects provided
out of band by the operator, not JSON/TOML, workflow inputs or agent output.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID, uuid4

from .adapters.cloud_agents import CloudPreviewDelivery, CodexCloudAgents, cloud_authority
from .adapters.cloud_contracts import CloudApproval, fields, strict_json, text_value
from .adapters.codex_cloud import CodexCloudGateway
from .adapters.github import GhCliTransport, GitHubCloudRefs
from .authority import ProjectGrant, RuntimePolicy
from .config import load_config
from .engine import Engine
from .models import Origin, Role, TeamError, digest
from .pilot import empty_directory, session_store, write_json
from .pilot_runner import PilotCommandRunner
from .pilot_scope import PILOT_REPOSITORY, PILOT_WRITABLE
from .workspace import GitWorkspace

MODE = "supervised-cloud-pilot"
ROLES = (Role.ORCHESTRATOR, Role.DEVELOPER, Role.QA, Role.SECURITY)
CAPABILITIES = frozenset({"read", "develop", "cloud_submit", "cloud_publish", "pull_request"})
OPERATOR_LOCK = "00000000-0000-0000-0000-000000000004"
PREPARATION_FIELDS = {
    "schema_version",
    "mode",
    "run_id",
    "repository",
    "controller_sha",
    "config_digest",
    "requirement_digest",
    "allowed_paths",
    "cloud_dispatch_authorized",
}


@dataclass(frozen=True)
class PilotReadiness:
    """Operator inspection references, never inferred runtime or Cloud attestations."""

    controller_sha: str
    durable_storage_review: str
    cloud_role_isolation_review: str
    account_quota_review: str


def _workspace(root: Path, preparation: dict):
    workspace = GitWorkspace(root / "project")
    workspace.assert_clean()
    workspace.git("merge-base", "--is-ancestor", preparation["controller_sha"], workspace.head)
    if any(p not in PILOT_WRITABLE for p in workspace.changed_paths(preparation["controller_sha"])):
        raise TeamError("Pilot checkout exceeds the fixed test-file scope")
    config = load_config(workspace.root / "examples/project.pilot.toml")
    requirement = workspace.read("pilot_project/requirement.txt")
    _, sealed = workspace.instructions(config)
    if (
        config.repository != PILOT_REPOSITORY
        or config.provider != "github"
        or config.auto_merge
        or config.max_repairs > 1
        or sealed != preparation["config_digest"]
        or digest(requirement) != preparation["requirement_digest"]
    ):
        raise TeamError("Pilot repository, controls or unchanged requirement binding mismatch")
    return workspace, config, requirement


def prepare_supervised(source: Path, output: Path) -> dict:
    """Clone an exact local commit; never probe, push, submit or manufacture approval."""
    workspace = GitWorkspace(source)
    workspace.assert_clean()
    config = load_config(source / "examples/project.pilot.toml")
    _, sealed = workspace.instructions(config)
    preparation = {
        "schema_version": 1,
        "mode": MODE,
        "run_id": str(uuid4()),
        "repository": PILOT_REPOSITORY,
        "controller_sha": workspace.head,
        "config_digest": sealed,
        "requirement_digest": digest(workspace.read("pilot_project/requirement.txt")),
        "allowed_paths": list(PILOT_WRITABLE),
        "cloud_dispatch_authorized": False,
    }
    if output.resolve().is_relative_to(workspace.root):
        raise TeamError("Supervised pilot state must be outside the controller checkout")
    destination = empty_directory(output)
    destination.chmod(0o700)
    workspace.git(
        "clone",
        "--quiet",
        "--no-hardlinks",
        "--",
        str(workspace.root),
        str(destination / "project"),
    )
    cloned = GitWorkspace(destination / "project")
    cloned.git("checkout", "--detach", preparation["controller_sha"])
    cloned.git("remote", "remove", "origin")
    _workspace(destination, preparation)
    write_json(destination / "preparation.json", preparation)
    from .store import RunStore

    RunStore(destination / "state.sqlite3")
    (destination / "state.sqlite3").chmod(0o600)
    return preparation


def read_preparation(root: Path) -> dict:
    if any(
        p.is_symlink()
        for p in (
            root,
            *root.parents,
            root / "preparation.json",
            root / "project",
            root / "authorization-binding.json",
            root / "checks",
            root / "results",
        )
    ):
        raise TeamError("Pilot state must not use symlinks")
    preparation = strict_json((root / "preparation.json").read_text(encoding="utf-8"))
    fields(preparation, PREPARATION_FIELDS)
    UUID(preparation["run_id"])
    if (
        type(preparation["schema_version"]) is not int
        or preparation["schema_version"] != 1
        or preparation["mode"] != MODE
        or preparation["repository"] != PILOT_REPOSITORY
        or preparation["allowed_paths"] != list(PILOT_WRITABLE)
        or preparation["cloud_dispatch_authorized"] is not False
        or any(
            not isinstance(preparation[key], str) or not re.fullmatch(pattern, preparation[key])
            for key, pattern in (
                ("controller_sha", r"[0-9a-f]{40}"),
                ("config_digest", r"[0-9a-f]{64}"),
                ("requirement_digest", r"[0-9a-f]{64}"),
            )
        )
    ):
        raise TeamError("Invalid supervised preparation; saved state never grants authority")
    return preparation


def _approved_engine(root, preparation, approval, grant, readiness):
    workspace, config, _ = _workspace(root, preparation)
    if readiness.controller_sha != preparation["controller_sha"]:
        raise TeamError("Pilot controller commit does not match the explicit operator approval")
    approval.validate(
        preparation["run_id"], PILOT_REPOSITORY, preparation["config_digest"], time.time()
    )
    environments = dict(grant.cloud_environments)
    if (
        grant.capabilities != CAPABILITIES
        or grant.auto_merge_approved
        or grant.approved_by != approval.approved_by
        or len(grant.cloud_environments) != 4
        or set(environments) != set(ROLES)
        or len(set(environments.values())) != 4
        or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", env) for env in environments.values())
        or approval.max_tasks > 8
        or approval.runtime_seconds > 3600
        or approval.task_timeout_seconds > 900
        or approval.poll_interval_seconds < 10
        or approval.max_polls > 60
        or approval.max_read_errors > 3
    ):
        raise TeamError(
            "Pilot requires four distinct environments, exact minimal grants and limits"
        )
    for capability in CAPABILITIES:
        grant.require(config, capability, preparation["config_digest"])
    for review in asdict(readiness).values():
        text_value(review)
    store = session_store(root)  # Missing journal must never silently recreate a live run.
    binding = {
        "authorization_digest": digest(
            {
                "approval": asdict(approval),
                "grant": asdict(grant) | {"capabilities": sorted(grant.capabilities)},
                "readiness": asdict(readiness),
            }
        )
    }
    seal = root / "authorization-binding.json"
    if seal.exists():
        if strict_json(seal.read_text(encoding="utf-8")) != binding:
            raise TeamError("Pilot authorization changed; restore the original approval and grants")
    else:
        if store.has_run(approval.run_id) or store.cloud_tasks(approval.run_id):
            raise TeamError("Authorization binding lost; reconcile instead of resealing a live run")
        write_json(seal, binding)
    policy = RuntimePolicy(False, False, True, PILOT_REPOSITORY)
    refs = GitHubCloudRefs(config, GhCliTransport(), workspace, grant, preparation["config_digest"])
    gateway = CodexCloudGateway(store=store, refs=refs)
    probe = gateway.probe()
    if probe["version"] != "codex-cli 0.163.0" or not all(
        probe[key]
        for key in (
            "chatgpt_login_reported",
            "submit_interface_present",
            "status_interface_present",
            "diff_interface_present",
            "list_json_interface_present",
        )
    ):
        raise TeamError("Pinned Codex CLI interfaces and existing ChatGPT login are required")
    runner = PilotCommandRunner(root / "checks")
    runner.require_available(workspace.root)
    agents = CodexCloudAgents(
        gateway,
        approval,
        grant,
        policy,
        allowed_paths=PILOT_WRITABLE,
        audit_directory=root / "results",
    )
    authority = cloud_authority(grant)
    if gateway.simulated:
        agents.simulated = True
        agents.review_origin = Origin.SIMULATED
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
        delivery=CloudPreviewDelivery(workspace, PILOT_REPOSITORY),
        store=store,
        authority=authority,
        grant=grant,
        policy=policy,
        runner=runner,
    )


def execute_supervised(
    root: Path,
    *,
    approval: CloudApproval,
    grant: ProjectGrant,
    readiness: PilotReadiness,
) -> dict:
    """ONE existing Engine invocation, only after separate explicit pilot approval.

    There is no scheduler, automatic retry, new UUID or approval-file loader here.
    Same path/authority objects/journal on resume. Never use rehearsal checkpoints.
    """
    preparation = read_preparation(root)
    with session_store(root).lock(OPERATOR_LOCK):
        engine = _approved_engine(root, preparation, approval, grant, readiness)
        run = engine.execute(engine.workspace.read("pilot_project/requirement.txt"))
        report = {
            "mode": MODE,
            "agent_backend": "test-adapter" if engine.agents.simulated else "codex-cloud-cli",
            "agent_actions": "simulated" if engine.agents.simulated else "cloud-agent-claims",
            "cloud_execution_verified": False,
            "checkout_attested": False,
            "merge_enabled": False,
            "controller_sha": preparation["controller_sha"],
            "allowed_paths": list(PILOT_WRITABLE),
            "run": asdict(run),
            "tasks": engine.store.cloud_tasks(run.id),
            "events": engine.store.events(run.id),
            "artifact_directories": ["checks/<head-sha>/", "results/"],
        }
        write_json(root / "report.json", report)
        return report
