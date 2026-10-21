"""Persistent, deterministic CLI/ref doubles for DT-003. Never invoke a provider."""

from __future__ import annotations

import difflib
import json
from datetime import UTC, datetime

from ..models import Role, TeamError
from .cloud_contracts import RESULT_PATH, CloudJob

PILOT_WRITABLE = (
    "pilot_project/calculator.py",
    "pilot_project/tests/test_calculator.py",
    "pilot_project/usage.md",
)


def _patch(path: str, old: str | None, new: str) -> str:
    if old == new:
        return ""
    header = f"diff --git a/{path} b/{path}\n"
    if old is None:
        header += "new file mode 100644\n"
    return header + "".join(
        difflib.unified_diff(
            (old or "").splitlines(True),
            new.splitlines(True),
            "/dev/null" if old is None else f"a/{path}",
            f"b/{path}",
        )
    )


class RehearsalRefs:
    """Only inspect the local synthetic checkout, without publishing a ref."""

    def __init__(self, workspace):
        self.workspace = workspace

    def prepare(self, job):
        self.verify(job)

    def verify(self, job):
        self.workspace.git("cat-file", "-e", f"{job.head_sha}^{{commit}}")


class RehearsalCLI:
    """Reconstruct fake provider state from the existing task journal after restart.

    Each task reports pending on its first poll. A later invocation returns its
    deterministic patch. These are test responses, never real Cloud observations.
    """

    def __init__(self, workspace, store, run_id: str, scenario: str):
        self.workspace, self.store = workspace, store
        self.run_id, self.scenario = run_id, scenario

    def _record(self, task_id):
        records = [r for r in self.store.cloud_tasks(self.run_id) if r["task_id"] == task_id]
        if len(records) != 1:
            raise TeamError("Unknown simulated task")
        return records[0]

    @staticmethod
    def _status(record):
        return "pending" if record["polls"] == 1 else "ready"

    def __call__(self, argv):
        if argv[:3] == ["codex", "cloud", "exec"]:
            envelope = next(
                json.loads(line) for line in argv[-1].splitlines() if line.startswith('{"binding":')
            )
            return "https://chatgpt.com/codex/tasks/task_simulated_" + envelope["job_id"]
        if argv[:3] == ["codex", "cloud", "list"]:
            environment = argv[argv.index("--env") + 1]
            return json.dumps(
                {
                    "tasks": [
                        {
                            "id": r["task_id"],
                            "status": self._status(r),
                            "environment_id": r["environment"],
                            "attempt_total": 1,
                            "updated_at": datetime.fromtimestamp(r["created_at"], UTC).isoformat(),
                        }
                        for r in self.store.cloud_tasks(self.run_id)
                        if r["environment"] == environment and r["task_id"]
                    ],
                    "cursor": None,
                }
            )
        if argv[:3] == ["codex", "cloud", "status"]:
            return f"[{self._status(self._record(argv[3])).upper()}] SIMULATED task\n"
        if argv[:3] == ["codex", "cloud", "diff"]:
            return self._diff(self._record(argv[3]))
        raise TeamError("Rehearsal adapter refuses all other CLI commands")

    def _diff(self, record):
        job = CloudJob(**(record["job"] | {"role": Role(record["job"]["role"])}))
        envelope = job.envelope() | {"payload": self._payload(job)}
        result = _patch(RESULT_PATH, None, json.dumps(envelope) + "\n")
        if job.role == Role.DEVELOPER:
            bad = self.scenario == "repair-limit" or (
                self.scenario == "test-fix" and job.cycle == 0
            )
            operation = "a - b" if bad else "a + b"
            files = {
                PILOT_WRITABLE[0]: (
                    '"""Addition für das künstliche Pilotprojekt."""\n\n'
                    "def add(a, b):\n"
                    "    for value in (a, b):\n"
                    "        if isinstance(value, bool) or not isinstance(value, (int, float)):\n"
                    "            raise TypeError('numeric inputs required')\n"
                    f"    return {operation}\n"
                ),
                PILOT_WRITABLE[1]: (
                    "import unittest\nfrom pilot_project.calculator import add\n\n"
                    "class AdditionTests(unittest.TestCase):\n"
                    "    def test_addition(self):\n"
                    "        self.assertEqual(add(2, 3), 5)\n"
                    "        self.assertEqual(add(-2, -3), -5)\n"
                    "        self.assertEqual(add(1.5, 2), 3.5)\n"
                    "    def test_boolean(self):\n"
                    "        with self.assertRaises(TypeError):\n"
                    "            add(True, 1)\n"
                ),
                PILOT_WRITABLE[2]: (
                    "# Künstliche Addition\n\n`add(2, 3)` liefert `5`. "
                    "Erlaubt sind int/float, einschließlich negativer Werte. "
                    "Boolesche und andere Eingaben lösen TypeError aus.\n\n"
                    f"Testadapter-Korrekturrunde: {job.cycle}. Keine echte Cloud-Ausführung.\n"
                ),
            }
            for path, new in files.items():
                old = self.workspace.git("show", f"{job.head_sha}:{path}", strip=False)
                result += _patch(path, old, new)
        return result

    def _payload(self, job):
        if job.role == Role.ORCHESTRATOR:
            return {
                "criteria": [
                    {"id": "AC-1", "description": "int/float korrekt addieren"},
                    {"id": "AC-2", "description": "Nichtnumerische Eingaben ablehnen"},
                    {"id": "AC-3", "description": "Tests und deutsche Dokumentation ergänzen"},
                ],
                "tasks": ["Funktion implementieren", "Tests ergänzen", "Benutzung dokumentieren"],
                "architecture": {
                    "summary": "Bestehende reine Python-Funktion ohne neue Abhängigkeiten",
                    "dependencies": [],
                    "risks": ["bool ist in Python eine int-Unterklasse"],
                },
            }
        if job.role == Role.DEVELOPER:
            return {"summary": "Künstliche Addition, Tests und Dokumentation ergänzt"}
        fail = job.role == Role.QA and job.cycle == 0 and self.scenario == "qa-fix"
        return {
            "outcome": "fail" if fail else "pass",
            "covered_criteria": ["AC-1", "AC-2", "AC-3"],
            "findings": [
                {
                    "category": "qa",
                    "code": "simulated-documentation-finding",
                    "message": "Absichtlich simulierter QA-Befund",
                    "suggestion": "Benutzungsdokumentation nach der QA ergänzen",
                    "blocking": True,
                    "repairable": True,
                }
            ]
            if fail
            else [],
        }
