"""Controlled Cloud CLI/ref test doubles; never start a remote task."""

import difflib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from developer_team.adapters.base import AgentContext
from developer_team.adapters.cloud_agents import (
    CloudPreviewDelivery,
    CodexCloudAgents,
    cloud_authority,
)
from developer_team.adapters.cloud_contracts import RESULT_PATH, CloudApproval
from developer_team.adapters.offline_cloud import _OfflineCloudLifecycle
from developer_team.adapters.synthetic import DEVELOPER_TESTS, REQUIREMENT, create_fixture
from developer_team.authority import ProjectGrant, RuntimePolicy
from developer_team.config import load_config
from developer_team.engine import Engine
from developer_team.models import Role, TeamError
from developer_team.store import RunStore
from tests.support import EXAMPLE


class FixtureCloudGateway(_OfflineCloudLifecycle):
    """Test-source-only scripted transport; never wired by the production API."""

    def __init__(self, responses, *, store, refs, now):
        super().__init__(store=store, refs=refs, now=now)
        self._responses = responses

    def _request(self, argv):
        return self._responses(argv)


class Clock:
    value = 1792540800.0

    def __call__(self):
        return self.value

    def advance(self, seconds=10):
        self.value += seconds


class FakeRefs:
    def __init__(self):
        self.prepared = []
        self.stale = False

    def prepare(self, job):
        self.prepared.append(job)
        self.verify(job)

    def verify(self, job):
        if self.stale:
            raise TeamError("Stale cloud commit binding")


def patch_for(path, old, new):
    if old is None:
        header = f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        return header + "".join(
            difflib.unified_diff([], new.splitlines(True), "/dev/null", f"b/{path}")
        )
    return f"diff --git a/{path} b/{path}\n" + "".join(
        difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}")
    )


class FakeCloudCLI:
    def __init__(self, workspace, clock):
        self.workspace, self.clock = workspace, clock
        self.calls, self.tasks = [], {}
        self.status = "ready"
        self.status_by_role = {}
        self.read_failure = None
        self.submit_failure = None
        self.receipt = None
        self.mutate = lambda envelope: envelope
        self.extra_review_patch = ""
        self.qa_failures = 0
        self.always_fail_qa = False
        self.bad_developer = False
        self.duplicate_metadata = False
        self.list_override = None
        self.metadata_overrides = {}

    @property
    def submissions(self):
        return [c for c in self.calls if c[:3] == ["codex", "cloud", "exec"]]

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:3] == ["codex", "cloud", "exec"]:
            if self.submit_failure:
                raise self.submit_failure
            prompt = argv[-1]
            envelope = next(
                json.loads(line) for line in prompt.splitlines() if line.startswith('{"binding":')
            )
            binding = envelope["binding"]
            task_id = f"task_controlled_{len(self.tasks)}"
            self.tasks[task_id] = {
                "envelope": envelope,
                "role": Role(binding["role"]),
                "environment": argv[argv.index("--env") + 1],
                "created_at": self.clock(),
            }
            return self.receipt or f"https://chatgpt.com/codex/tasks/{task_id}\n"
        if self.read_failure:
            exc, self.read_failure = self.read_failure, None
            raise exc
        if argv[:3] == ["codex", "cloud", "list"]:
            if self.list_override is not None:
                return self.list_override
            tasks = [
                {
                    "id": task_id,
                    "status": self.status_by_role.get(t["role"], self.status),
                    "environment_id": t["environment"],
                    "attempt_total": 1,
                    "updated_at": datetime.fromtimestamp(t["created_at"], UTC).isoformat(),
                }
                for task_id, t in self.tasks.items()
                if t["environment"] == argv[argv.index("--env") + 1]
            ]
            tasks = [task | self.metadata_overrides for task in tasks]
            return json.dumps(
                {"tasks": tasks * (2 if self.duplicate_metadata else 1), "cursor": None}
            )
        if argv[:3] == ["codex", "cloud", "status"]:
            task = self.tasks[argv[3]]
            status = self.status_by_role.get(task["role"], self.status)
            return f"[{status.upper()}] Controlled task\n"
        if argv[:3] == ["codex", "cloud", "diff"]:
            task = self.tasks[argv[3]]
            envelope = task["envelope"] | {"payload": self.payload(task)}
            envelope = self.mutate(envelope)
            result = patch_for(RESULT_PATH, None, json.dumps(envelope) + "\n")
            if task["role"] == Role.DEVELOPER:
                sha = task["envelope"]["binding"]["head_sha"]
                files = {
                    "calculator.py": (
                        "def add(a, b):\n"
                        "    if (isinstance(a, bool) or isinstance(b, bool)\n"
                        "        or not isinstance(a, (int, float))\n"
                        "        or not isinstance(b, (int, float))):\n"
                        "        raise TypeError('numeric inputs required')\n"
                        "    return a + b\n"
                    ),
                    "tests/test_calculator.py": DEVELOPER_TESTS,
                    "docs/usage.md": (
                        f"# Addition\nCloud fixture cycle {task['envelope']['binding']['cycle']}.\n"
                    ),
                }
                if self.bad_developer:
                    files["calculator.py"] = "def add(a, b):\n    return a - b\n"
                for path, new in files.items():
                    try:
                        old = self.workspace.git("show", f"{sha}:{path}") + "\n"
                    except TeamError:
                        old = None
                    if old != new:
                        result += patch_for(path, old, new)
            elif task["role"] in (Role.QA, Role.SECURITY):
                result += self.extra_review_patch
            return result
        raise AssertionError(argv)

    def payload(self, task):
        role = task["role"]
        if role == Role.ORCHESTRATOR:
            return {
                "criteria": [{"id": "AC-1", "description": "Adds numeric values"}],
                "tasks": ["Implement add with tests and documentation"],
                "architecture": {
                    "summary": "Keep the existing function",
                    "dependencies": [],
                    "risks": [],
                },
            }
        if role == Role.DEVELOPER:
            return {"summary": "Implement add and its tests"}
        failed = role == Role.QA and (self.always_fail_qa or self.qa_failures > 0)
        if failed:
            self.qa_failures -= 1
        return {
            "outcome": "fail" if failed else "pass",
            "covered_criteria": ["AC-1"],
            "findings": [
                {
                    "category": role.value,
                    "code": "edge-case",
                    "message": "An edge case fails",
                    "suggestion": "Fix the edge case",
                    "blocking": True,
                    "repairable": True,
                }
            ]
            if failed
            else [],
        }


def cloud_harness(directory: Path, **approval_overrides):
    workspace = create_fixture(directory / "project")
    config = replace(load_config(EXAMPLE), provider="github")
    docs, sealed = workspace.instructions(config)
    clock = Clock()
    approval = CloudApproval(
        str(uuid4()),
        config.repository,
        sealed,
        "explicit-test-operator",
        clock() + 7200,
        **approval_overrides,
    )
    grant = ProjectGrant(
        config.id,
        config.repository,
        sealed,
        frozenset({"read", "develop", "pull_request", "cloud_submit", "cloud_publish"}),
        approved_by="test-controller",
        cloud_environments=tuple((r, "env-" + r.value) for r in Role),
    )
    policy = RuntimePolicy(False, False, True, config.repository)
    store = RunStore(directory / "state.sqlite3")
    refs = FakeRefs()
    cli = FakeCloudCLI(workspace, clock)
    gateway = FixtureCloudGateway(cli, store=store, refs=refs, now=clock)
    agents = CodexCloudAgents(gateway, approval, grant, policy)
    authority = cloud_authority(grant)
    delivery = CloudPreviewDelivery(workspace, config.repository)
    engine = Engine(
        config=config,
        workspace=workspace,
        agents=agents,
        delivery=delivery,
        store=store,
        authority=authority,
        grant=grant,
        policy=policy,
    )
    context = AgentContext(REQUIREMENT, config, docs, workspace, approval.run_id)
    job = agents.job(context, Role.DEVELOPER, {"test": True})
    kwargs = dict(
        config=config,
        effective_digest=sealed,
        policy=policy,
        grant=grant,
        role=job.role,
        branch=job.branch,
        expected_sha=job.head_sha,
        prompt="Controlled task",
        approval=approval,
        job=job,
    )
    return engine, cli, gateway, refs, clock, kwargs, context
