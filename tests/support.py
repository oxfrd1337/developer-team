from dataclasses import replace
from pathlib import Path

from developer_team.adapters.synthetic import LocalDelivery, SyntheticAgents, create_fixture
from developer_team.authority import ProjectGrant, RuntimePolicy, synthetic_authority
from developer_team.config import load_config
from developer_team.engine import Engine
from developer_team.store import RunStore

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/project.synthetic.toml"


def harness(
    directory: Path,
    scenario: str = "happy",
    *,
    simulate_activation: bool = False,
    capabilities: frozenset[str] | None = None,
    config=None,
    agents=None,
    runner=None,
):
    config = config or load_config(EXAMPLE)
    if simulate_activation:
        config = replace(config, auto_merge=True)
    workspace = create_fixture(directory / "project")
    _, sealed = workspace.instructions(config)
    grant = ProjectGrant(
        config.id,
        config.repository,
        sealed,
        capabilities
        if capabilities is not None
        else frozenset({"read", "develop", "pull_request", "merge"}),
        auto_merge_approved=simulate_activation,
        approved_by="synthetic-test-driver",
    )
    backend = agents or SyntheticAgents(scenario)
    delivery = LocalDelivery(workspace, config.repository, stale=scenario == "stale-evidence")
    store = RunStore(directory / "state.sqlite3")
    authority = synthetic_authority()
    policy = RuntimePolicy(
        first_release_approved=simulate_activation, bootstrap=not simulate_activation
    )
    engine = Engine(
        config=config,
        workspace=workspace,
        agents=backend,
        delivery=delivery,
        store=store,
        authority=authority,
        grant=grant,
        policy=policy,
        runner=runner,
    )
    return engine, workspace, backend, delivery, store
