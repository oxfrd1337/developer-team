"""Optional exec transport. Live execution is deliberately unavailable in DT-005.

Only controller-owned Python CLI simulators can run. A same-UID process, CLI sandbox
or checkout copy is not an isolation attestation and must never unlock live dispatch.
"""

from __future__ import annotations

import hashlib
import os
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..models import PermissionDenied, TeamError, digest
from ..store import RunStore
from .cloud_contracts import CloudJob, strict_json


@dataclass(frozen=True)
class ExecLimits:
    max_calls: int = 8
    runtime_seconds: int = 300
    timeout_seconds: int = 10
    output_bytes: int = 262144
    memory_bytes: int = 268435456
    cpu_seconds: int = 5

    def validate(self):
        for value, low, high in (
            (self.max_calls, 1, 32),
            (self.runtime_seconds, 1, 3600),
            (self.timeout_seconds, 1, 60),
            (self.output_bytes, 1024, 1000000),
            (self.memory_bytes, 67108864, 1073741824),
            (self.cpu_seconds, 1, 30),
        ):
            if type(value) is not int or not low <= value <= high:
                raise PermissionDenied("Invalid exec resource budget")


@dataclass(frozen=True)
class ExecJob(CloudJob):
    """Reuse the strict role/input/commit envelope, with a separate identity namespace."""

    @property
    def id(self):
        return digest({"adapter": "codex-exec-v1", **asdict(self)})


# Limits are applied in a fresh trusted Python interpreter, never preexec_fn.
_LAUNCH = """import os, resource, sys
memory, cpu = map(int, sys.argv[1:3])
resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
os.execv(sys.executable, [sys.executable, '-I', sys.argv[3], *sys.argv[4:]])
"""


class SimulatedExecProcess:
    """Bounded real subprocess mechanics for trusted synthetic fixtures ONLY.

    Does not enforce network, process count, credentials or same-UID write isolation.
    No production runner exists. Never point this at project-provided code.
    """

    def __init__(self, fixture: Path):
        self.fixture = fixture.resolve(strict=True)
        if self.fixture.suffix != ".py" or not self.fixture.is_file():
            raise PermissionDenied("A controller-owned Python simulator is required")

    def run(self, argv: list[str], root: Path, limits: ExecLimits) -> str:
        limits.validate()
        output = bytearray()
        deadline = time.monotonic() + limits.timeout_seconds
        with selectors.DefaultSelector() as selector:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    _LAUNCH,
                    str(limits.memory_bytes),
                    str(limits.cpu_seconds),
                    str(self.fixture),
                    *argv[1:],
                ],
                cwd=root,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            stdout = bytearray()
            try:
                for stream in (process.stdout, process.stderr):
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TeamError("Exec process deadline exceeded")
                    for key, _ in selector.select(min(remaining, 0.05)):
                        chunk = os.read(key.fd, 16384)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if len(output) + len(chunk) > limits.output_bytes:
                            raise TeamError("Exec combined output budget exceeded")
                        output.extend(chunk)
                        if key.fileobj is process.stdout:
                            stdout.extend(chunk)
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
                if process.returncode != 0:
                    raise TeamError(f"Exec process failed with exit code {process.returncode}")
                return stdout.decode("utf-8")
            except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
                raise TeamError(f"Exec process failed: {type(exc).__name__}") from exc
            finally:
                # Kill lingering children even when the parent exits successfully.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdout.close()
                process.stderr.close()


class CodexExecGateway:
    def __init__(
        self,
        store: RunStore,
        simulator: SimulatedExecProcess | None = None,
        limits: ExecLimits = ExecLimits(),
        *,
        now=time.time,
    ):
        limits.validate()
        self.store, self.simulator, self.limits, self.now = store, simulator, limits, now
        self.simulated = simulator is not None
        if simulator is not None:
            store.initialize_exec_journal()

    def require_simulation(self):
        if type(self.simulator) is not SimulatedExecProcess:
            raise PermissionDenied(
                "Live codex exec blocked: OS isolation, credential broker, network policy, "
                "immutable independent review mounts and cgroup cleanup are unverified"
            )

    def execute(self, job: ExecJob, root: Path, prompt: str) -> dict:
        self.require_simulation()
        job.validate()
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100000:
            raise PermissionDenied("Invalid exec prompt")
        # Use the verified interface only; never add bypass/auto-approve flags.
        argv = [
            "codex",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--cd",
            str(root),
            "--",
            prompt,
        ]
        record = {
            "id": job.id,
            "run_id": job.run_id,
            "job": asdict(job),
            "prompt_digest": digest(prompt),
            "state": "intent",
            "simulated": True,
            "limits": asdict(self.limits),
            "created_at": self.now(),
            "snapshot": str(root),
            "argv_digest": digest(argv),
        }
        self.store.reserve_exec_call(record, self.now())
        try:
            raw = self.simulator.run(argv, root, self.limits)
            if self.now() - record["created_at"] >= self.limits.timeout_seconds:
                raise TeamError("Exec result arrived after deadline")
            self.store.check_exec_runtime(job.run_id, self.now())
            payload = job.validate_result(strict_json(raw))
            record.update(state="completed", result_digest=hashlib.sha256(raw.encode()).hexdigest())
            self.store.finish_exec_call(record)
            return payload
        except BaseException:
            # Includes cancellation; SIGKILL leaves intent, which is also non-retryable.
            record["state"] = "uncertain"
            self.store.finish_exec_call(record)
            raise
