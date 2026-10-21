"""Offline negative access probes. Never launches Codex or grants live authority.

Only temporary canaries, loopback listeners and controller-owned Python processes
are attacked. Missing boundaries produce UNSUPPORTED and an unconditional NO-GO.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import TeamError
from .pilot_runner import PilotCommandRunner

ROLES = ("orchestrator", "developer", "qa", "security")
NAMESPACES = ("user", "mnt", "pid", "net", "ipc", "uts")
ATTACKS = (
    "credential-read",
    "controller-write",
    "snapshot-write",
    "snapshot-delete",
    "snapshot-rename",
    "snapshot-chmod",
    "git-write",
    "host-proc-read",
    "role-signal",
    "supervisor-signal",
    "dns",
    "http",
    "tcp",
    "unix-socket",
    "abstract-socket",
    "private-output",
)

# Fixed trusted program; no project code, real credential paths or public network.
_CHILD = r"""
import errno, json, os, pathlib, signal, socket, sys
q = json.loads(sys.argv[1])
results = {}
file_denials = {errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT}
network_denials = {errno.EACCES, errno.EPERM, errno.ENETUNREACH,
                  errno.EHOSTUNREACH, errno.ECONNREFUSED, errno.ENOENT}
def attempt(name, action, denials=file_denials):
    try:
        action()
    except OSError as exc:
        status = 'PASS' if exc.errno in denials else 'UNSUPPORTED'
        results[name] = {'status': status, 'errno': exc.errno}
    else:
        results[name] = {'status': 'FAIL', 'reason': 'access allowed'}
def read(path):
    pathlib.Path(path).read_bytes()
def write(path):
    pathlib.Path(path).write_bytes(b'DT006 synthetic mutation')
attempt('credential-read', lambda: read(q['credential']))
attempt('controller-write', lambda: write(q['journal']))
for role, path in q['roles'].items():
    if role != q['role']:
        attempt('cross-role-read:' + role, lambda p=path: read(p))
        attempt('cross-role-write:' + role, lambda p=path: write(p))
source = pathlib.Path('/project/source.py')
attempt('snapshot-write', lambda: write(source))
attempt('snapshot-delete', pathlib.Path('/project/delete.py').unlink)
attempt('snapshot-rename', lambda: pathlib.Path('/project/rename.py').rename('/project/renamed.py'))
attempt('snapshot-chmod', lambda: pathlib.Path('/project/mode.py').chmod(0o777))
attempt('git-write', lambda: write('/project/.git/config'))
attempt('host-proc-read', lambda: read('/proc/%d/environ' % q['target_pid']))
for name, pid in [('role-signal', q['target_pid']),
                  ('supervisor-signal', q['supervisor_pid'])]:
    attempt(name, lambda p=pid: os.kill(p, signal.SIGCONT),
            {errno.EPERM, errno.ESRCH})
def connect(kind):
    family = socket.AF_UNIX if kind in ('unix-socket', 'abstract-socket') else socket.AF_INET
    type_ = socket.SOCK_DGRAM if kind == 'dns' else socket.SOCK_STREAM
    with socket.socket(family, type_) as s:
        s.settimeout(0.5)
        address = q['endpoints'][kind]
        s.connect(tuple(address) if isinstance(address, list) else address)
        if kind in ('http', 'dns'):
            s.sendall(b'GET /canary HTTP/1.0\r\n\r\n' if kind == 'http' else b'DT006 DNS canary')
            s.recv(1024)
for kind in ('dns', 'http', 'tcp', 'unix-socket', 'abstract-socket'):
    attempt(kind, lambda k=kind: connect(k), network_denials)
try:
    private = pathlib.Path('/tmp/dt006-output')
    private.write_text('synthetic private output')
    ok = private.read_text() == 'synthetic private output'
    results['private-output'] = {'status': 'PASS' if ok else 'FAIL'}
except OSError as exc:
    results['private-output'] = {'status': 'UNSUPPORTED', 'errno': exc.errno}
print(json.dumps({'namespaces': {n: os.readlink('/proc/self/ns/' + n) for n in q['namespaces']},
                  'pid': os.getpid(), 'uid': os.getuid(), 'results': results}))
"""


def _namespaces() -> dict[str, str]:
    return {name: os.readlink(f"/proc/self/ns/{name}") for name in NAMESPACES}


def _run(root: Path, source: str, request: dict) -> dict:
    command = PilotCommandRunner.command(root, ("python3", "-I", "-c", source, json.dumps(request)))
    result = subprocess.run(
        command,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        # Fixed-command stderr is bounded and contains no credentials or project output.
        reason = result.stderr[:1500].decode("utf-8", errors="replace").strip()
        raise TeamError(f"Namespace probe exit {result.returncode}: {reason}")
    try:
        data = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise TeamError("Invalid controller probe output") from exc
    if not isinstance(data, dict):
        raise TeamError("Invalid controller probe output")
    return data


class _Listeners:
    """Reachable host controls; a refused connection alone proves nothing."""

    def __init__(self, root: Path):
        self.root = root
        self.endpoints = {}
        self.stop = threading.Event()
        self.selector = selectors.DefaultSelector()
        self.thread = None

    def __enter__(self):
        try:
            for kind in ("dns", "http", "tcp", "unix-socket", "abstract-socket"):
                unix = kind in ("unix-socket", "abstract-socket")
                listener = socket.socket(
                    socket.AF_UNIX if unix else socket.AF_INET,
                    socket.SOCK_DGRAM if kind == "dns" else socket.SOCK_STREAM,
                )
                try:
                    address = (
                        "\0dt006-" + uuid4().hex
                        if kind == "abstract-socket"
                        else str(self.root / "control.sock")
                        if unix
                        else ("127.0.0.1", 0)
                    )
                    listener.bind(address)
                    if kind != "dns":
                        listener.listen(16)
                    self.selector.register(listener, selectors.EVENT_READ, kind)
                    bound = listener.getsockname()
                    self.endpoints[kind] = bound.decode() if isinstance(bound, bytes) else bound
                except BaseException:
                    listener.close()
                    raise
            self.thread = threading.Thread(target=self._serve)
            self.thread.start()
            self.verify()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def verify(self):
        if not self.thread.is_alive():
            raise TeamError("Host listener control stopped")
        for kind, address in self.endpoints.items():
            unix = kind in ("unix-socket", "abstract-socket")
            with socket.socket(
                socket.AF_UNIX if unix else socket.AF_INET,
                socket.SOCK_DGRAM if kind == "dns" else socket.SOCK_STREAM,
            ) as control:
                control.settimeout(2)
                control.connect(address)
                if kind == "dns":
                    control.sendall(b"DT006 DNS canary")
                expected = (
                    b"HTTP/1.0 200 OK\r\nContent-Length: 22\r\n\r\nDT006 listener control"
                    if kind == "http"
                    else b"DT006 listener control"
                )
                if control.recv(1024) != expected:
                    raise TeamError("Host listener positive control failed")

    def _serve(self):
        while not self.stop.is_set():
            for key, _ in self.selector.select(0.05):
                if key.data == "dns":
                    _, address = key.fileobj.recvfrom(1024)
                    key.fileobj.sendto(b"DT006 listener control", address)
                else:
                    connection, _ = key.fileobj.accept()
                    with connection, contextlib.suppress(OSError):
                        connection.sendall(
                            b"HTTP/1.0 200 OK\r\nContent-Length: 22\r\n\r\nDT006 listener control"
                            if key.data == "http"
                            else b"DT006 listener control"
                        )

    def __exit__(self, *args):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        for key in list(self.selector.get_map().values()):
            key.fileobj.close()
        self.selector.close()


def _keys(role: str) -> tuple[str, ...]:
    return ATTACKS + tuple(
        f"cross-role-{action}:{other}"
        for other in ROLES
        if other != role
        for action in ("read", "write")
    )


def collect_boundary_report() -> dict:
    """Collect observations on THIS executor, without modifying host security policy."""
    report = {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "current-executor-only; not a Codespaces attestation",
        "host": {"system": platform.system(), "kernel": platform.release()},
        "decision": "NO-GO",
        "live_dispatch_authorized": False,
        "ai_calls": 0,
        "probes": {},
    }
    probes = report["probes"]
    for name, reason in (
        ("credential-broker", "No verified ChatGPT credential broker separate from tool processes"),
        ("model-only-egress", "No external model-only policy or authenticated broker verified"),
        (
            "external-supervisor",
            "No independent kill/lease/cgroup cleanup after controller SIGKILL",
        ),
        ("resource-enforcement", "No externally bounded aggregate CPU/memory/PIDs verified"),
        (
            "host-role-identities",
            "User namespaces do not establish separate host UID/VM identities",
        ),
    ):
        probes[name] = {"status": "UNSUPPORTED", "reason": reason}
    for role in ROLES:
        for name in ("namespace-separation", *_keys(role)):
            probes[f"{role}:{name}"] = {
                "status": "UNSUPPORTED",
                "reason": "Required namespace boundary not established; no host fallback",
            }
    with tempfile.TemporaryDirectory(prefix="dt006-probes-") as directory:
        root = Path(directory)
        project = root / "snapshot"
        project.mkdir()
        source = project / "source.py"
        source.write_text("# synthetic immutable input\n")
        for name in ("delete.py", "rename.py", "mode.py"):
            (project / name).write_text("# synthetic independent mutation target\n")
        (project / ".git").mkdir()
        (project / ".git/config").write_text("# synthetic Git metadata canary\n")
        try:
            host_ns = _namespaces()
            # Probe kernel support before creating any targets or network listeners.
            initial = _run(
                project,
                "import json,os,sys; print(json.dumps({n:os.readlink('/proc/self/ns/'+n) "
                "for n in json.loads(sys.argv[1])['namespaces']}))",
                {"namespaces": NAMESPACES},
            )
            if set(initial) != set(host_ns) or any(initial[n] == host_ns[n] for n in host_ns):
                raise TeamError("Required namespaces are not separate from the controller")
        except (OSError, subprocess.SubprocessError, TeamError) as exc:
            probes["namespace-prerequisite"] = {"status": "UNSUPPORTED", "reason": str(exc)}
            return report
        probes["namespace-prerequisite"] = {"status": "PASS", "namespaces": initial}
        try:
            _exercise_roles(root, project, host_ns, probes)
        except (OSError, subprocess.SubprocessError, TeamError) as exc:
            probes["probe-completion"] = {"status": "UNSUPPORTED", "reason": str(exc)}
    return report


def _exercise_roles(root, project, host_ns, probes):
    paths = {role: root / f"{role}-output" for role in ROLES}
    credential, journal = root / "dummy-auth", root / "dummy-journal"
    for path in (*paths.values(), credential, journal):
        path.write_text("DT006 synthetic canary " + uuid4().hex)
        path.chmod(0o600)
    snapshot_files = tuple(p for p in project.rglob("*") if p.is_file())
    controls = {
        p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode)
        for p in (*paths.values(), credential, journal, *snapshot_files)
    }
    # Sole process-read target contains only an artificial environment credential.
    with (
        _Listeners(root) as listeners,
        subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
            env={"DT006_FAKE_CREDENTIAL": "synthetic-canary-only"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        ) as target,
    ):
        try:
            if min(target.pid, os.getpid()) <= 10:
                raise TeamError("Host PID collides with possible probe namespace PIDs")
            environment = Path(f"/proc/{target.pid}/environ").read_bytes()
            if b"DT006_FAKE_CREDENTIAL=synthetic-canary-only\0" not in environment:
                raise TeamError("Synthetic process credential positive control failed")
            for role in ROLES:
                os.kill(target.pid, signal.SIGCONT)
                if target.poll() is not None:
                    raise TeamError("Synthetic process target exited; denial cannot be established")
                result = _run(
                    project,
                    _CHILD,
                    {
                        "credential": str(credential),
                        "journal": str(journal),
                        "roles": {r: str(p) for r, p in paths.items()},
                        "role": role,
                        "target_pid": target.pid,
                        "supervisor_pid": os.getpid(),
                        "endpoints": listeners.endpoints,
                        "namespaces": NAMESPACES,
                    },
                )
                if (
                    not isinstance(result, dict)
                    or set(result) != {"namespaces", "pid", "uid", "results"}
                    or set(result["namespaces"]) != set(host_ns)
                    or any(result["namespaces"][n] == host_ns[n] for n in host_ns)
                    or set(result["results"]) != set(_keys(role))
                ):
                    raise TeamError("Incomplete or conflicting controller probe results")
                listeners.verify()
                if target.poll() is not None:
                    raise TeamError("Synthetic process target exited during access probes")
                probes[f"{role}:namespace-separation"] = {
                    "status": "PASS",
                    "namespaces": result["namespaces"],
                    "uid": result["uid"],
                }
                for name, observation in result["results"].items():
                    if observation.get("status") not in ("PASS", "FAIL", "UNSUPPORTED"):
                        raise TeamError("Unknown probe status")
                    probes[f"{role}:{name}"] = observation
                # Independently check persistent mutations; the child cannot attest itself.
                intact = all(
                    p.is_file()
                    and (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode) == d
                    for p, d in controls.items()
                ) and set(project.rglob("*")) == {*snapshot_files, project / ".git"}
                probes[f"{role}:canary-integrity"] = {"status": "PASS" if intact else "FAIL"}
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(target.pid, signal.SIGKILL)
            target.wait()


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = collect_boundary_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    # An offline report is never a GO exit code, even if every runnable probe passed.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
