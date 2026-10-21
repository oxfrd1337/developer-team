"""Safe operator interface: synthetic demos, config validation and read-only CLI probes."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from .adapters.codex_cloud import CodexCloudGateway
from .adapters.synthetic import (
    REQUIREMENT,
    SCENARIOS,
    LocalDelivery,
    SyntheticAgents,
    create_fixture,
)
from .authority import ProjectGrant, synthetic_authority
from .config import load_config
from .engine import Engine
from .models import RunStatus, TeamError
from .store import RunStore


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
