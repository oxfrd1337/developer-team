"""Bounded process execution. This is NOT a sandbox for arbitrary project code."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from .config import Check
from .models import CheckResult, Outcome
from .workspace import minimal_environment


class SyntheticCommandRunner:
    """Run only repository-owned synthetic commands, without shell or inherited secrets.

    A disposable OS/container boundary is required before adapting this to untrusted repos.
    Output is spooled to a temporary file. By default reports retain only a digest;
    an optional controller-owned sink retains bounded diagnostic excerpts.
    """

    def __init__(self, *, audit_directory: Path | None = None):
        self.audit_directory = audit_directory

    def run(self, check: Check, root: Path) -> CheckResult:
        with tempfile.TemporaryFile() as output:
            try:
                process = subprocess.Popen(
                    check.argv,
                    cwd=root,
                    env=minimal_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                return CheckResult(
                    check.name,
                    Outcome.UNKNOWN,
                    None,
                    "",
                    f"Command unavailable: {type(exc).__name__}",
                )
            timed_out = False
            try:
                process.wait(timeout=check.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # Kill descendants too, including a background child left by a successful parent.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            output.seek(0)
            hasher = hashlib.sha256()
            while chunk := output.read(65536):
                hasher.update(chunk)
            result = CheckResult(
                check.name,
                Outcome.FAIL if timed_out or process.returncode != 0 else Outcome.PASS,
                process.returncode,
                hasher.hexdigest(),
                "Command timed out" if timed_out else f"Exit code {process.returncode}",
            )
            if self.audit_directory is not None:
                self.audit_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                # Bounded output is available to the operator and to a corrective task.
                output.seek(max(0, output.tell() - 16000))
                excerpt = output.read(16000).decode("utf-8", errors="replace")
                result = CheckResult(
                    result.name,
                    result.outcome,
                    result.returncode,
                    result.output_digest,
                    result.detail + "\n" + excerpt,
                )
                path = self.audit_directory / f"{check.name}-{result.output_digest}.json"
                with path.open("w", encoding="utf-8") as stream:
                    path.chmod(0o600)
                    json.dump(asdict(result) | {"argv": check.argv}, stream, indent=2)
            return result
