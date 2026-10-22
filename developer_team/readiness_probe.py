"""DT-007 local synthetic canaries. No external connections, auth reads or AI calls."""

from __future__ import annotations

import array
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

_DENIALS = (
    errno.EACCES,
    errno.EPERM,
    errno.ENETUNREACH,
    errno.EHOSTUNREACH,
    errno.ECONNREFUSED,
    errno.ENOENT,
    errno.EROFS,
    errno.EBADF,
)
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
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        check=True,
        **kwargs,
    )
    return json.loads(result.stdout)


@contextlib.contextmanager
def _listener(root, kind):
    family = (
        socket.AF_UNIX
        if kind in ("unix", "abstract")
        else (socket.AF_INET6 if kind.startswith("ipv6") else socket.AF_INET)
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
            else b"GET / HTTP/1.0\r\n\r\n"
            if kind == "http"
            else b"DT007"
        )
        yield {
            "family": int(family),
            "type": int(socktype),
            "address": bound,
            "message": message.hex(),
            "denials": _DENIALS,
        }
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
            + repr(boundary_probe.NAMESPACES)
            + "}))",
            {},
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
        observations["namespace-prerequisite"] = _result(
            "PASS" if available else "UNSUPPORTED", reason
        )
        paths = {
            name: str(root / name)
            for name in (
                "auth-file",
                "refresh-file",
                "github-file",
                "proxy-file",
                "home-file",
                "ipc-file",
            )
        }
        for path in paths.values():
            Path(path).write_text("DT007-synthetic-only")
        # Deliberately high synthetic descriptor, never inspect inherited real descriptors.
        with Path(paths["auth-file"]).open("rb") as stream:
            fd = fcntl.fcntl(stream.fileno(), fcntl.F_DUPFD_CLOEXEC, 64)
            try:
                request = {"paths": paths, "fd": fd, "denials": _DENIALS}
                control = _host_python(_CREDENTIAL, request, pass_fds=(fd,))
                if set(control) != {*paths, "inherited-fd", "inherited-env"} or any(
                    v["status"] != "FAIL" for v in control.values()
                ):
                    raise TeamError("Credential positive control failed")
                observations["credential-positive-control"] = _result(
                    "PASS", "Only artificial files/env/FD were reachable outside boundary"
                )
                if available:
                    observed = boundary_probe._run(project, _CREDENTIAL, request)
                    for name in control:
                        observations["credential:" + name] = observed.get(
                            name, _result("UNSUPPORTED", "Missing result")
                        )
                else:
                    for name in control:
                        observations["credential:" + name] = _result("UNSUPPORTED", reason)
            finally:
                os.close(fd)
        for kind in (
            "dns",
            "http",
            "ipv4-tcp",
            "ipv4-udp",
            "ipv6-tcp",
            "ipv6-udp",
            "unix",
            "abstract",
        ):
            try:
                with _listener(root, kind) as request:
                    before = _host_python(_NETWORK, request)
                    if before["status"] != "FAIL":
                        raise TeamError("Network positive control failed")
                    observations[kind + ":positive-control"] = _result(
                        "PASS", "Own local listener reachable"
                    )
                    observed = (
                        boundary_probe._run(project, _NETWORK, request)
                        if available
                        else _result("UNSUPPORTED", reason)
                    )
                    after = _host_python(_NETWORK, request)
                    if after["status"] != "FAIL":
                        raise TeamError("Listener disappeared during negative probe")
                    observations[kind + ":denial"] = observed
            except (OSError, subprocess.SubprocessError, TeamError) as exc:
                observations[kind + ":denial"] = _result("UNSUPPORTED", str(exc))
    return observations


_CONTROLLER = r"""
import array, json, os, pathlib, signal, socket, subprocess, sys, time
def stop(*args):
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
with socket.socket(fileno=int(sys.argv[1])) as channel:
    child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(8)'],
        env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,start_new_session=True)
    child_fd=None
    try:
        # This parent has not reaped its Popen child: its PID cannot be reused.
        if child.poll() is not None:
            raise RuntimeError('Synthetic child ended before pidfd acquisition')
        child_fd=os.pidfd_open(child.pid)
        fields=pathlib.Path('/proc/%d/stat' % child.pid).read_text().rsplit(')',1)[1].split()
        message={'pid':child.pid,'controller_pid':os.getpid(),'start_ticks':int(fields[19])}
        channel.sendmsg([json.dumps(message).encode()],
            [(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[child_fd]))])
        time.sleep(8)
    finally:
        if child_fd is not None:
            os.close(child_fd)
        child.kill()
        child.wait()
"""


def _receive_child(channel):
    """Accept one kernel-transferred handle, never reopen a reported PID."""
    handles = []
    accepted = False
    try:
        payload, ancillary, flags, _ = channel.recvmsg(
            1024, socket.CMSG_SPACE(4 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC
        )
        unexpected = False
        for level, kind, data in ancillary:
            if (level, kind) != (socket.SOL_SOCKET, socket.SCM_RIGHTS):
                unexpected = True
                continue
            descriptors = array.array("i")
            descriptors.frombytes(data[: len(data) - len(data) % descriptors.itemsize])
            handles.extend(descriptors)
        if unexpected or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(handles) != 1:
            raise TeamError("Synthetic child handle transfer incomplete or ambiguous")
        message = json.loads(payload)
        if type(message) is not dict or set(message) != {"pid", "controller_pid", "start_ticks"}:
            raise TeamError("Invalid synthetic child identity schema")
        if any(type(value) is not int or value <= 0 for value in message.values()):
            raise TeamError("Invalid synthetic child identity values")
        accepted = True
        return handles[0], message
    finally:
        if not accepted:
            for descriptor in handles:
                os.close(descriptor)


def _process_identity(pid):
    """Read only our reported child's process metadata; reject malformed/dead targets."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        prefix, fields = raw.rsplit(")", 1)
        actual_pid = int(prefix.split("(", 1)[0])
        fields = fields.split()
        state, parent, session, started = fields[0], int(fields[1]), int(fields[3]), int(fields[19])
        if actual_pid != pid or state not in {"R", "S", "D", "T", "t", "I"} or started <= 0:
            raise ValueError("Unexpected process identity")
    except (ValueError, IndexError) as exc:
        raise TeamError("Invalid or ended synthetic process identity") from exc
    return parent, session, started


def _verify_child(controller, child_fd, message):
    """Bind SCM_RIGHTS pidfd, two live snapshots and unreaped parent-owned lifetime."""
    child = message["pid"]
    expected = (controller.pid, child, message["start_ticks"])
    if message["controller_pid"] != controller.pid or controller.poll() is not None:
        raise TeamError("Synthetic child controller identity unconfirmed")
    before = _process_identity(child)
    fdinfo = Path(f"/proc/self/fdinfo/{child_fd}").read_text().splitlines()
    identities = [line.split() for line in fdinfo if line.startswith("Pid:")]
    if identities != [["Pid:", str(child)]]:
        raise TeamError("Transferred pidfd does not bind the synthetic child")
    if (
        before != expected
        or os.getsid(child) != child
        or _process_identity(child) != before
        or select.select([child_fd], [], [], 0)[0]
        or controller.poll() is not None
    ):
        raise TeamError("Synthetic child ownership or stable identity unconfirmed")


def collect_supervisor_probes():
    result = {}
    cgroup = Path("/sys/fs/cgroup")
    try:
        result["cgroup-v2"] = _result(
            "PASS" if (cgroup / "cgroup.controllers").is_file() else "UNSUPPORTED",
            "Read-only filesystem capability inspection; no cgroup changes",
        )
        delegated = os.access(cgroup / "cgroup.subtree_control", os.W_OK)
        result["aggregate-enforcement"] = _result(
            "UNSUPPORTED",
            "Delegation and independent service not attested; writable indicator=" + str(delegated),
        )
    except OSError as exc:
        result["aggregate-enforcement"] = _result("UNSUPPORTED", str(exc))
    result["external-cleanup"] = _result("UNSUPPORTED", "No independent supervisor owns this run")
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        result["controller-sigkill-detached-child"] = _result(
            "UNSUPPORTED", "Safe owned-process pidfd signaling unavailable"
        )
        return result
    child_fd = None
    child_verified = False
    try:
        receiver, sender = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    except OSError as exc:
        result["controller-sigkill-detached-child"] = _result("UNSUPPORTED", str(exc))
        return result
    with receiver, sender:
        receiver.settimeout(3)
        with subprocess.Popen(
            [sys.executable, "-I", "-c", _CONTROLLER, str(sender.fileno())],
            env={"PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(sender.fileno(),),
        ) as controller:
            sender.close()
            try:
                child_fd, message = _receive_child(receiver)
                _verify_child(controller, child_fd, message)
                child_verified = True
                controller.kill()
                controller.wait(timeout=2)
                survived = not select.select([child_fd], [], [], 0.1)[0]
                result["controller-sigkill-detached-child"] = _result(
                    "PASS" if survived else "UNSUPPORTED",
                    "Synthetic detached child survived controller SIGKILL; "
                    "demonstrates missing hard boundary",
                )
            except (OSError, ValueError, subprocess.SubprocessError, TeamError) as exc:
                result["controller-sigkill-detached-child"] = _result("UNSUPPORTED", str(exc))
            finally:
                try:
                    if child_fd is not None:
                        try:
                            if child_verified:
                                with contextlib.suppress(ProcessLookupError):
                                    signal.pidfd_send_signal(child_fd, signal.SIGKILL)
                                cleaned = bool(select.select([child_fd], [], [], 2)[0])
                                result["harness-cleanup"] = _result(
                                    "PASS" if cleaned else "FAIL",
                                    "Verified synthetic child cleanup; not an external supervisor",
                                )
                            else:
                                result["harness-cleanup"] = _result(
                                    "UNSUPPORTED", "Unverified handle closed without signaling"
                                )
                        except OSError as exc:
                            result["harness-cleanup"] = _result("UNSUPPORTED", str(exc))
                        finally:
                            os.close(child_fd)
                finally:
                    if controller.poll() is None:
                        controller.terminate()
                        controller.wait(timeout=2)
    try:
        subprocess.run(
            [sys.executable, "-I", "-c", "import time;time.sleep(8)"],
            env={"PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=0.1,
            check=True,
        )
    except subprocess.TimeoutExpired:
        result["synthetic-runtime-exceeded"] = _result(
            "PASS",
            "Bounded direct synthetic process timed out and was reaped; no aggregate guarantee",
        )
    return result


def collect_report():
    observations = {}
    for name, collect in (
        ("access", collect_access_probes),
        ("supervisor", collect_supervisor_probes),
    ):
        try:
            observations[name] = collect()
        except (OSError, subprocess.SubprocessError, TeamError) as exc:
            observations[name] = {"collection": _result("UNSUPPORTED", str(exc))}
    return {
        "schema_version": 1,
        "diagnostic_only": True,
        "decision": "NO-GO",
        "live_dispatch_authorized": False,
        "ai_calls": 0,
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
