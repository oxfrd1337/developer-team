"""DT-007 local synthetic canaries. No external connections, auth reads or AI calls."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import platform
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from . import boundary_probe
from .models import TeamError

_DENIALS = (errno.EACCES, errno.EPERM, errno.ENETUNREACH, errno.EHOSTUNREACH,
            errno.ECONNREFUSED, errno.ENOENT, errno.EROFS, errno.EBADF)
_NETWORK = r"""
import json, socket, sys
q=json.loads(sys.argv[1])
try:
    with socket.socket(q['family'], q['type']) as s:
        s.settimeout(1)
        address=q['address']
        s.connect(tuple(address) if isinstance(address,list) else address)
        s.sendall(bytes.fromhex(q['message']))
        ok=s.recv(1024)==b'DT007-local-canary'
    print(json.dumps({'status':'FAIL' if ok else 'UNSUPPORTED',
                      'reason':'reachable' if ok else 'bad control'}))
except OSError as e:
    print(json.dumps({'status':'PASS' if e.errno in q['denials'] else 'UNSUPPORTED',
                      'errno':e.errno}))
"""
_CREDENTIAL = r"""
import json, os, pathlib, sys
q=json.loads(sys.argv[1]); results={}
for name,path in q['paths'].items():
    try:
        pathlib.Path(path).read_bytes()
        results[name]={'status':'FAIL','reason':'synthetic credential reachable'}
    except OSError as e:
        results[name]={'status':'PASS' if e.errno in q['denials'] else 'UNSUPPORTED',
                       'errno':e.errno}
try:
    os.pread(q['fd'],32,0)
    results['inherited-fd']={'status':'FAIL'}
except OSError as e:
    results['inherited-fd']={'status':'PASS' if e.errno==9 else 'UNSUPPORTED','errno':e.errno}
results['inherited-env']={'status':'FAIL' if 'DT007_FAKE_TOKEN' in os.environ else 'PASS'}
print(json.dumps(results))
"""


def _result(status, reason):
    return {"status": status, "reason": reason}


def _host_python(source, request, **kwargs):
    result = subprocess.run(
        [sys.executable, "-I", "-c", source, json.dumps(request)],
        env={"PATH": "/usr/bin:/bin", "DT007_FAKE_TOKEN": "synthetic-only"},
        stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=True, **kwargs,
    )
    return json.loads(result.stdout)


@contextlib.contextmanager
def _listener(root, kind):
    family = socket.AF_UNIX if kind in ("unix", "abstract") else (
        socket.AF_INET6 if kind.startswith("ipv6") else socket.AF_INET
    )
    udp = kind in ("dns", "ipv4-udp", "ipv6-udp")
    socktype = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    listener = socket.socket(family, socktype)
    stop = threading.Event()
    thread = None
    try:
        if family == socket.AF_UNIX:
            address = "\0dt007-" + uuid4().hex if kind == "abstract" else str(root / "broker.sock")
        else:
            address = ("::1", 0) if family == socket.AF_INET6 else ("127.0.0.1", 0)
        listener.bind(address)
        if not udp:
            listener.listen(4)
        listener.settimeout(0.05)

        def serve():
            while not stop.is_set():
                try:
                    if udp:
                        _, peer = listener.recvfrom(1024)
                        listener.sendto(b"DT007-local-canary", peer)
                    else:
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(1)
                            connection.recv(1024)
                            connection.sendall(b"DT007-local-canary")
                except (OSError, TimeoutError):
                    continue

        thread = threading.Thread(target=serve)
        thread.start()
        bound = listener.getsockname()
        if isinstance(bound, bytes):
            bound = bound.decode()
        # Synthetic DNS wire query for canary.invalid, sent only to our own UDP echo.
        message = (
            bytes.fromhex("0007010000010000000000000663616e61727907696e76616c69640000010001")
            if kind == "dns"
            else b"GET / HTTP/1.0\r\n\r\n" if kind == "http" else b"DT007"
        )
        yield {"family": int(family), "type": int(socktype), "address": bound,
               "message": message.hex(), "denials": _DENIALS}
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=2)
        listener.close()
        if family == socket.AF_UNIX and kind == "unix":
            (root / "broker.sock").unlink(missing_ok=True)


def _available(project):
    try:
        host = boundary_probe._namespaces()
        actual = boundary_probe._run(
            project,
            "import os,json;print(json.dumps({n:os.readlink('/proc/self/ns/'+n) for n in "
            + repr(boundary_probe.NAMESPACES) + "}))", {},
        )
        if set(actual) != set(host) or any(actual[n] == host[n] for n in host):
            raise TeamError("Namespaces not independent from controller")
        return True, "Actual namespace prerequisite passed on current executor"
    except (OSError, subprocess.SubprocessError, TeamError) as exc:
        return False, f"Namespace prerequisite unavailable: {exc}"


def collect_access_probes():
    observations = {}
    with tempfile.TemporaryDirectory(prefix="dt007-access-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        available, reason = _available(project)
        observations["namespace-prerequisite"] = _result("PASS" if available else "UNSUPPORTED",
            reason)
        paths = {name: str(root / name) for name in (
            "auth-file", "refresh-file", "github-file", "proxy-file", "home-file", "ipc-file",
        )}
        for path in paths.values():
            Path(path).write_text("DT007-synthetic-only")
        # Deliberately high synthetic descriptor, never inspect inherited real descriptors.
        with Path(paths["auth-file"]).open("rb") as stream:
            fd = fcntl.fcntl(stream.fileno(), fcntl.F_DUPFD_CLOEXEC, 64)
            try:
                request = {"paths": paths, "fd": fd, "denials": _DENIALS}
                control = _host_python(_CREDENTIAL, request, pass_fds=(fd,))
                if set(control) != {*paths,
                    "inherited-fd",
                    "inherited-env"} or any(v["status"] != "FAIL" for v in control.values()):
                    raise TeamError("Credential positive control failed")
                observations["credential-positive-control"] = _result("PASS",
                    "Only artificial files/env/FD were reachable outside boundary")
                if available:
                    observed = boundary_probe._run(project, _CREDENTIAL, request)
                    for name in control:
                        observations["credential:" + name] = observed.get(name,
                            _result("UNSUPPORTED",
                            "Missing result"))
                else:
                    for name in control:
                        observations["credential:" + name] = _result("UNSUPPORTED", reason)
            finally:
                os.close(fd)
        for kind in ("dns",
            "http",
            "ipv4-tcp",
            "ipv4-udp",
            "ipv6-tcp",
            "ipv6-udp",
            "unix",
            "abstract"):
            try:
                with _listener(root, kind) as request:
                    before = _host_python(_NETWORK, request)
                    if before["status"] != "FAIL":
                        raise TeamError("Network positive control failed")
                    observations[kind + ":positive-control"] = _result("PASS",
                        "Own local listener reachable")
                    observed = boundary_probe._run(project,
                        _NETWORK,
                        request) if available else _result("UNSUPPORTED",
                        reason)
                    after = _host_python(_NETWORK, request)
                    if after["status"] != "FAIL":
                        raise TeamError("Listener disappeared during negative probe")
                    observations[kind + ":denial"] = observed
            except (OSError, subprocess.SubprocessError, TeamError) as exc:
                observations[kind + ":denial"] = _result("UNSUPPORTED", str(exc))
    return observations


_CONTROLLER = r"""
import json, signal, subprocess, sys, time
def stop(*args):
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(8)'],
    env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,start_new_session=True)
try:
    print(json.dumps({'pid':child.pid}),flush=True)
    time.sleep(8)
finally:
    child.kill()
    child.wait()
"""


def collect_supervisor_probes():
    result = {}
    cgroup = Path("/sys/fs/cgroup")
    try:
        result["cgroup-v2"] = _result(
            "PASS" if (cgroup / "cgroup.controllers").is_file() else "UNSUPPORTED",
            "Read-only filesystem capability inspection; no cgroup changes")
        delegated = os.access(cgroup / "cgroup.subtree_control", os.W_OK)
        result["aggregate-enforcement"] = _result("UNSUPPORTED",
            "Delegation and independent service not attested; writable indicator=" + str(delegated))
    except OSError as exc:
        result["aggregate-enforcement"] = _result("UNSUPPORTED", str(exc))
    result["external-cleanup"] = _result("UNSUPPORTED", "No independent supervisor owns this run")
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        result["controller-sigkill-detached-child"] = _result("UNSUPPORTED",
            "Safe owned-process pidfd signaling unavailable")
        return result
    # Only descendants created by this fixed synthetic controller are addressed.
    child_fd = None
    with subprocess.Popen(
        [sys.executable, "-I", "-c", _CONTROLLER],
        env={"PATH": "/usr/bin:/bin"}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
    ) as controller:
        try:
            if not select.select([controller.stdout], [], [], 3)[0]:
                raise TeamError("Synthetic child handshake missing")
            child = json.loads(controller.stdout.readline())["pid"]
            child_fd = os.pidfd_open(child)
            # Check ownership/ancestry before signaling, while controller remains alive.
            status = Path(f"/proc/{child}/status").read_text()
            if f"PPid:\t{controller.pid}\n" not in status or os.getsid(child) != child:
                raise TeamError("Synthetic child ownership or detached session unconfirmed")
            controller.kill()
            controller.wait(timeout=2)
            survived = not select.select([child_fd], [], [], 0.1)[0]
            result["controller-sigkill-detached-child"] = _result(
                "PASS" if survived else "UNSUPPORTED",
                "Synthetic detached child survived controller SIGKILL; "
                "demonstrates missing hard boundary")
        except (OSError, ValueError, subprocess.SubprocessError, TeamError) as exc:
            result["controller-sigkill-detached-child"] = _result("UNSUPPORTED", str(exc))
        finally:
            if child_fd is not None:
                with contextlib.suppress(ProcessLookupError):
                    signal.pidfd_send_signal(child_fd, signal.SIGKILL)
                cleaned = bool(select.select([child_fd], [], [], 2)[0])
                result["harness-cleanup"] = _result("PASS" if cleaned else "FAIL",
                    "Harness cleaned its synthetic child; NOT independent supervisor cleanup")
                os.close(child_fd)
            if controller.poll() is None:
                controller.terminate()
                controller.wait(timeout=2)
    try:
        subprocess.run([sys.executable, "-I", "-c", "import time;time.sleep(8)"],
                       env={"PATH": "/usr/bin:/bin"}, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=0.1,
                           check=True)
    except subprocess.TimeoutExpired:
        result["synthetic-runtime-exceeded"] = _result("PASS",
            "Bounded direct synthetic process timed out and was reaped; no aggregate guarantee")
    return result


def collect_report():
    observations = {}
    for name, collect in (("access",
        collect_access_probes),
        ("supervisor",
        collect_supervisor_probes)):
        try:
            observations[name] = collect()
        except (OSError, subprocess.SubprocessError, TeamError) as exc:
            observations[name] = {"collection": _result("UNSUPPORTED", str(exc))}
    return {
        "schema_version": 1, "diagnostic_only": True, "decision": "NO-GO",
        "live_dispatch_authorized": False, "ai_calls": 0,
        "scope": "current Codex worker; not historical Codespace or live attestation",
        "host": {"system": platform.system(), "kernel": platform.release(), "uid": os.getuid()},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "collected_at": datetime.now(UTC).isoformat(),
        **observations,
    }


def main():
    print(json.dumps(collect_report(), indent=2, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
