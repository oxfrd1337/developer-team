"""Controller-owned subprocess simulator. Never invokes codex or a model."""

import difflib
import json
import sys
from pathlib import Path


def patch(path, old, new):
    header = f"diff --git a/{path} b/{path}\n"
    if old is None:
        header += "new file mode 100644\n"
    return header + "".join(
        difflib.unified_diff(
            [] if old is None else old.splitlines(True),
            new.splitlines(True),
            "/dev/null" if old is None else f"a/{path}",
            f"b/{path}",
        )
    )


assert sys.argv[1:8] == [
    "exec",
    "--ephemeral",
    "--ignore-user-config",
    "--sandbox",
    "read-only",
    "--cd",
    str(Path.cwd()),
]
assert sys.argv[8] == "--"
request = json.loads(sys.argv[9])
envelope = request["job"]
role = envelope["binding"]["role"]
mode = request["inputs"]["requirement"]
if mode == "mutate-review" and role == "qa":
    Path("calculator.py").write_text("tampered\n")
if role == "orchestrator":
    payload = {
        "criteria": [{"id": "AC-1", "description": "numeric addition"}],
        "tasks": ["Implement addition"],
        "architecture": {"summary": "single function", "dependencies": [], "risks": []},
    }
elif role == "developer":
    payload = {"summary": "Implemented synthetic addition"}
else:
    payload = {"outcome": "pass", "covered_criteria": ["AC-1"], "findings": []}
    if mode == "contradictory":
        payload["covered_criteria"] = []
result_envelope = envelope | {"payload": payload}
result = patch(".developer-team/cloud-result.json", None, json.dumps(result_envelope) + "\n")
if role == "developer":
    files = {
        "calculator.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calculator.py": "import unittest\nfrom calculator import add\n"
        "class TestAdd(unittest.TestCase):\n    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        "docs/usage.md": "# Synthetic addition\n",
    }
    if mode == "protected":
        files["AGENTS.md"] = "changed\n"
    for name, content in files.items():
        old = Path(name).read_text() if Path(name).exists() else None
        result += patch(name, old, content)
print(json.dumps(envelope | {"payload": {"patch": result}}))
