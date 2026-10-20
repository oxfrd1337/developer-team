"""Deterministic agent actions on a disposable fixture; never cloud intelligence."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from ..config import Check
from ..execution import SyntheticCommandRunner
from ..models import (
    Architecture,
    Criterion,
    FailureClass,
    Finding,
    Outcome,
    Plan,
    Planning,
    PlatformSnapshot,
    PullRequest,
    Review,
    TeamError,
)
from ..workspace import GitWorkspace, minimal_environment
from .base import AgentContext

REQUIREMENT = (
    "Implementiere add(a, b) für int und float, einschließlich negativer Zahlen. "
    "Boolesche und andere nichtnumerische Eingaben müssen TypeError auslösen. "
    "Liefere Tests und eine Dokumentation im selben Pull Request."
)

SCENARIOS = (
    "happy",
    "test-fix",
    "qa-fix",
    "qa-fail",
    "security-fix",
    "security-conflict",
    "protected-change",
    "stale-evidence",
    "missing-permission",
    "interrupted",
    "repair-limit",
)

DEVELOPER_TESTS = """import unittest
from calculator import add

class AdditionTests(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_negative(self):
        self.assertEqual(add(-2, -3), -5)

    def test_float(self):
        self.assertEqual(add(1.5, 2), 3.5)

    def test_wrong_type(self):
        with self.assertRaises(TypeError):
            add("2", 3)
"""

QA_PROBE = """from calculator import add
assert add(2, 3) == 5
assert add(-2, -3) == -5
assert add(1.5, 2) == 3.5
for a, b in [(True, 2), (1, False), ("2", 3), (None, 1), ([], 1)]:
    try:
        add(a, b)
    except TypeError:
        pass
    else:
        raise AssertionError("Non-numeric input was accepted")
"""


def create_fixture(root: Path) -> GitWorkspace:
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise TeamError("Synthetic fixture destination must be empty")
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(root)],
        env=minimal_environment(),
        capture_output=True,
        check=True,
        timeout=15,
    )
    workspace = GitWorkspace(root)
    workspace.write(".gitignore", "__pycache__/\n*.pyc\n")
    workspace.write(
        "AGENTS.md", "# Synthetic project\nUse stdlib Python; no network or deployment.\n"
    )
    workspace.write("SECURITY.md", "# Synthetic policy\nNo secrets or permission escalation.\n")
    workspace.write("calculator.py", "def add(a, b):\n    raise NotImplementedError\n")
    workspace.write("README.md", "# Synthetic calculator\nPending implementation.\n")
    workspace.commit("Initialize disposable synthetic fixture")
    workspace.git("switch", "-c", "dt/synthetic-requirement")
    return workspace


class SyntheticAgents:
    simulated = True
    developer_identity = "synthetic-developer"
    qa_identity = "synthetic-qa"
    security_identity = "synthetic-security"

    def __init__(self, scenario: str = "happy"):
        if scenario not in SCENARIOS:
            raise TeamError("Unknown synthetic scenario")
        self.scenario = scenario
        self.calls: list[str] = []
        self.developments = 0

    def plan(self, context: AgentContext) -> Planning:
        if context.requirement != REQUIREMENT:
            raise TeamError(
                "The scripted fixture supports only its documented synthetic requirement"
            )
        self.calls.append("orchestrator+architect")
        return Planning(
            Plan(
                (
                    Criterion("AC-1", "Addition of integers and floats including negative values"),
                    Criterion("AC-2", "TypeError for boolean and other nonnumeric inputs"),
                    Criterion("AC-3", "Tests and usage documentation accompany the implementation"),
                ),
                ("Implement calculator.add", "Write unit tests", "Document usage"),
            ),
            Architecture(
                "A pure Python function with no external dependency or network access.",
                ("Python stdlib unittest",),
                ("bool is a subclass of int; reject it explicitly",),
            ),
        )

    def develop(
        self,
        context: AgentContext,
        plan: Plan,
        architecture: Architecture,
        findings: tuple[Finding, ...],
    ) -> None:
        self.calls.append("developer")
        self.developments += 1
        if self.scenario == "interrupted":
            raise KeyboardInterrupt
        broken_math = self.scenario == "repair-limit" or (
            self.scenario == "test-fix" and self.developments == 1
        )
        accepts_bool = self.scenario == "qa-fail" or (
            self.scenario == "qa-fix" and self.developments == 1
        )
        expression = "a - b" if broken_math else "a + b"
        validation = (
            "isinstance(value, (int, float))" if accepts_bool else ("type(value) in (int, float)")
        )
        source = (
            "def add(a, b):\n"
            f"    if not all({validation} for value in (a, b)):\n"
            '        raise TypeError("Expected int or float")\n'
            f"    return {expression}\n"
        )
        if self.scenario == "security-fix" and self.developments == 1:
            source += "\nUNSAFE_PERMISSION = True\n"
        context.workspace.write("calculator.py", source)
        context.workspace.write("tests/test_calculator.py", DEVELOPER_TESTS)
        context.workspace.write(
            "README.md",
            "# Synthetic calculator\n\n"
            "`add(a, b)` adds int/float values, including negative values.\n"
            "Boolean and other nonnumeric values raise TypeError.\n"
            "Run `python3 -m unittest discover -s tests -v`.\n",
        )
        if self.developments > 1:
            context.workspace.write(
                "docs/corrections.md",
                f"Correction {self.developments - 1}: "
                + ", ".join(f.code for f in findings)
                + "\n",
            )
        if self.scenario == "security-conflict":
            context.workspace.write(".env", "SYNTHETIC_TOKEN=not-a-real-credential\n")
        if self.scenario == "protected-change":
            context.workspace.write(
                "AGENTS.md",
                context.instructions["AGENTS.md"]
                + "\nSynthetic change to a protected component.\n",
            )

    def qa(self, context: AgentContext, plan: Plan, head_sha: str) -> Review:
        self.calls.append("qa")
        # This probe is independent of the developer's tests and runs in a fresh process.
        result = SyntheticCommandRunner().run(
            Check("independent-qa", "test", (sys.executable, "-c", QA_PROBE), 10, True),
            context.workspace.root,
        )
        docs_ok = "TypeError" in context.workspace.read("README.md")
        if result.outcome != Outcome.PASS or not docs_ok:
            return Review(
                Outcome.FAIL,
                (),
                (
                    Finding(
                        FailureClass.QA,
                        "independent-probe-failed",
                        "Independent edge-case probe failed",
                        "Reject bool in both operands and document the TypeError contract.",
                    ),
                ),
            )
        return Review(Outcome.PASS, tuple(c.id for c in plan.criteria))

    def security(self, context: AgentContext, plan: Plan, head_sha: str) -> Review:
        self.calls.append("security")
        if (context.workspace.root / ".env").exists():
            return Review(
                Outcome.FAIL,
                findings=(
                    Finding(
                        FailureClass.SECURITY,
                        "credential-file",
                        "Synthetic policy forbids .env files",
                        "Remove the credential file and use controller-side secret bindings.",
                        repairable=False,
                    ),
                ),
            )
        if "UNSAFE_PERMISSION = True" in context.workspace.read("calculator.py"):
            return Review(
                Outcome.FAIL,
                findings=(
                    Finding(
                        FailureClass.SECURITY,
                        "permission-escalation",
                        "Unsafe permission marker found",
                        "Remove the permission escalation from the implementation.",
                    ),
                ),
            )
        return Review(Outcome.PASS)


class LocalDelivery:
    simulated = True

    def __init__(self, workspace: GitWorkspace, repository: str, *, stale: bool = False):
        self.workspace, self.repository, self.stale = workspace, repository, stale
        self.prs: dict[str, PullRequest] = {}
        self.merge_calls = 0
        self.pr_calls = 0

    def open_pull_request(
        self, run_id: str, head_sha: str, base_sha: str, body: str
    ) -> PullRequest:
        self.pr_calls += 1
        if run_id not in self.prs:
            self.prs[run_id] = PullRequest(
                len(self.prs) + 1,
                self.repository,
                head_sha,
                base_sha,
                f"simulation://pulls/{run_id}",
                True,
            )
        return self.prs[run_id]

    def snapshot(self, pr: PullRequest) -> PlatformSnapshot:
        return PlatformSnapshot(
            self.repository,
            "f" * 40 if self.stale else self.workspace.head,
            pr.base_sha,
            self.workspace.changed_paths(pr.base_sha),
            True,
            True,
            True,
            False,
            time.time(),
            True,
        )

    def merge(self, pr: PullRequest, expected_sha: str) -> None:
        if not pr.simulated or self.workspace.head != expected_sha or pr.head_sha != expected_sha:
            raise TeamError("Simulated merge SHA mismatch")
        self.merge_calls += 1  # No git merge, remote API call or branch write occurs.
