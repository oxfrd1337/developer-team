"""Safe operator interface: synthetic demos, config validation and read-only CLI probes."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from .adapters.codex_cloud import CodexCloudGateway
from .adapters.github import GhCliTransport
from .adapters.synthetic import (
    REQUIREMENT,
    SCENARIOS,
    LocalDelivery,
    SyntheticAgents,
    create_fixture,
)
from .authority import ProjectGrant, synthetic_authority
from .checkpoints import check_artifact_source, checkpoint, restore_checkpoint
from .config import load_config
from .engine import Engine
from .models import RunStatus, TeamError
from .pilot import SCENARIOS as PILOT_SCENARIOS
from .pilot import prepare_session, step_rehearsal
from .store import RunStore
from .supervised_pilot import prepare_supervised


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="DT-001 autonomous developer team: safe test mode")
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="Validate a project TOML without executing commands"
    )
    validate.add_argument("config", type=Path)
    demo = commands.add_parser(
        "demo", help="Run only a disposable synthetic project; no remote writes"
    )
    demo.add_argument("--config", type=Path, default=Path("examples/project.synthetic.toml"))
    demo.add_argument("--scenario", choices=SCENARIOS, default="happy")
    demo.add_argument(
        "--output", type=Path, help="Empty output directory for checkout, journal and report"
    )
    commands.add_parser(
        "probe-codex", help="Read installed CLI help/login status; never submit a task"
    )
    show = commands.add_parser(
        "show", help="Inspect the local audit journal (not trusted merge evidence)"
    )
    show.add_argument("--state", type=Path, required=True)
    show.add_argument("--run-id", required=True)
    prepare = commands.add_parser(
        "pilot-prepare", help="Prepare only a disposable pilot with test adapters; no cloud calls"
    )
    prepare.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--scenario", choices=PILOT_SCENARIOS, default="qa-fix")
    prepare.add_argument("--max-tasks", type=int, default=8)
    prepare.add_argument("--runtime-seconds", type=int, default=600)
    prepare.add_argument("--max-repairs", type=int, default=1)
    step = commands.add_parser("pilot-step", help="Resume the same test-adapter rehearsal")
    step.add_argument("--session", type=Path, required=True)
    step.add_argument("--ticks", type=int, default=1)
    save = commands.add_parser("pilot-checkpoint", help="Export rehearsal journal and Git commits")
    save.add_argument("--session", type=Path, required=True)
    save.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("pilot-restore", help="Restore an exact test-only checkpoint")
    restore.add_argument("--checkpoint", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    restore.add_argument("--controller-sha", required=True)
    restore.add_argument("--run-id", required=True)
    provenance = commands.add_parser(
        "pilot-check-source", help="Read GitHub producer metadata before downloading a checkpoint"
    )
    provenance.add_argument("--repository", required=True)
    provenance.add_argument("--sha", required=True)
    provenance.add_argument("--source-run", required=True)
    provenance.add_argument("--artifact-id", required=True)
    supervised = commands.add_parser(
        "pilot-plan", help="Prepare a supervised pilot locally; no login, remote writes or approval"
    )
    supervised.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    supervised.add_argument("--output", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            config = load_config(args.config)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "project": config.id,
                        "digest": config.digest,
                        "grants_authority": False,
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "probe-codex":
            print(json.dumps(CodexCloudGateway().probe(), indent=2))
            return 0
        if args.command == "pilot-plan":
            print(json.dumps(prepare_supervised(args.source, args.output), indent=2))
            return 0
        if args.command == "pilot-check-source":
            check_artifact_source(
                GhCliTransport(),
                repository=args.repository,
                sha=args.sha,
                source_run=args.source_run,
                artifact_id=args.artifact_id,
            )
            print(json.dumps({"producer_verified": True, "live_dispatch_authorized": False}))
            return 0
        if args.command == "pilot-checkpoint":
            print(json.dumps(checkpoint(args.session, args.output), indent=2))
            return 0
        if args.command in ("pilot-prepare", "pilot-step", "pilot-restore"):
            if args.command == "pilot-prepare":
                report = prepare_session(
                    args.source,
                    args.output,
                    scenario=args.scenario,
                    max_tasks=args.max_tasks,
                    runtime_seconds=args.runtime_seconds,
                    max_repairs=args.max_repairs,
                )
            elif args.command == "pilot-restore":
                report = restore_checkpoint(
                    args.checkpoint,
                    args.output,
                    controller_sha=args.controller_sha,
                    run_id=args.run_id,
                )
            else:
                report = step_rehearsal(args.session, ticks=args.ticks)
            print(
                json.dumps(
                    {key: report[key] for key in ("mode", "run_id", "status", "ticks")}
                    | {"cloud_execution_verified": False, "tasks": len(report["tasks"])},
                    indent=2,
                )
            )
            return int(report["status"] in ("escalated", "interrupted"))
        if args.command == "show":
            if not args.state.is_file():
                raise TeamError("State database does not exist")
            store = RunStore(args.state)
            print(
                json.dumps(
                    {
                        "run": asdict(store.load(args.run_id)),
                        "events": store.events(args.run_id),
                        "cloud_tasks": store.cloud_tasks(args.run_id),
                    },
                    indent=2,
                )
            )
            return 0
        config = load_config(args.config)
        if config.provider != "local" or not config.repository.startswith("synthetic/"):
            raise TeamError("Demo accepts only local repositories in the synthetic/ namespace")
        output = args.output or Path(tempfile.mkdtemp(prefix="developer-team-demo-"))
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            raise TeamError("Demo output directory must be empty")
        workspace = create_fixture(output / "project")
        _, effective_digest = workspace.instructions(config)
        capabilities = {"read", "develop", "pull_request"}
        if args.scenario == "missing-permission":
            capabilities.remove("develop")
        grant = ProjectGrant(
            config.id,
            config.repository,
            effective_digest,
            frozenset(capabilities),
            approved_by="synthetic-test-driver",
        )
        agents = SyntheticAgents(args.scenario)
        delivery = LocalDelivery(
            workspace, config.repository, stale=args.scenario == "stale-evidence"
        )
        store = RunStore(output / "state.sqlite3")
        run = Engine(
            config=config,
            workspace=workspace,
            agents=agents,
            delivery=delivery,
            store=store,
            authority=synthetic_authority(),
            grant=grant,
        ).execute(REQUIREMENT)
        report = {
            "mode": "safe_test_mode",
            "agent_actions": "simulated",
            "local_checks": "real subprocesses on synthetic code",
            "cloud_execution_verified": False,
            "real_remote_mutations": 0,
            "simulated_merge_calls": delivery.merge_calls,
            "agent_calls": agents.calls,
            "run": asdict(run),
        }
        report_path = output / "report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": run.status,
                    "report": str(report_path),
                    "repairs": run.repairs,
                    "merge_reasons": run.reasons,
                    "cloud_execution_verified": False,
                },
                indent=2,
            )
        )
        return 1 if run.status in (RunStatus.ESCALATED, RunStatus.INTERRUPTED) else 0
    except (TeamError, ValueError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, indent=2))
        return 1
