"""Local DT-017C broker. Explicit read-only consent never authorizes live work."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from . import provider_readonly_runner as runner
from .adapters.agents_api_contracts import AgentsAPIError, CanaryBinding, safe_ref
from .adapters.agents_credentials import CredentialIdentity
from .adapters.agents_https import FDSecretStore
from .adapters.provider_readonly_https import AdminCredentialIdentity

BASE = "abb3eed41c8e056c930ae3f46bf7affad741afae"
RUNNER_SHA256 = "41136330bdc37d0695d2ad262cd13e1ba7b0e88874949daf862847673d8dbd6e"
FIELDS = (
    "project_id",
    "service_account_ref",
    "credential_ref",
    "admin_ref",
    "agent_id",
    "model",
    "intent_id",
    "idempotency_key",
    "plan_digest",
    "budget_cents",
)
_ENV_MARKERS = ("KEY", "SECRET", "TOKEN", "CREDENTIAL", "PASSWORD")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AgentsAPIError("invalid_arguments")


def _halt(reason):
    return runner._report("PREPARE", "BLOCKED") | {"reason": reason}


def _environment_blocked():
    # Inspect names only; never consume an environment credential or path.
    return any(
        name in os.environ for name in ("CI", "GITHUB_ACTIONS", "DT_PROVIDER_OFFLINE")
    ) or any(
        name.startswith(("OPENAI_", "DT_", "ADMIN_", "CANARY_"))
        and any(marker in name.upper() for marker in _ENV_MARKERS)
        for name in os.environ
    )


def _binding(values):
    if (
        any(
            not safe_ref(values[name])
            for name in (
                "service_account_ref",
                "credential_ref",
                "admin_ref",
            )
        )
        or values["admin_ref"] == values["credential_ref"]
    ):
        raise AgentsAPIError("invalid_binding")
    bound = CanaryBinding(
        **{
            name: values[name]
            for name in (
                "project_id",
                "agent_id",
                "intent_id",
                "idempotency_key",
                "plan_digest",
                "budget_cents",
                "model",
            )
        }
    )
    bound.validate()
    return bound


def _check_checkout():
    root = Path(__file__).resolve().parent.parent
    digest = hashlib.sha256(
        (root / "developer_team/provider_readonly_runner.py").read_bytes()
    ).hexdigest()
    if digest != RUNNER_SHA256:
        raise AgentsAPIError("runner_changed")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASE, "HEAD"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
    )
    if result.returncode:
        raise AgentsAPIError("base_missing")
    return root


def _checked_fd(fd):
    import fcntl

    if type(fd) is not int or fd < 3:
        raise AgentsAPIError("private_readonly_file_required")
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or not 1 <= info.st_size <= 512
        or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
    ):
        raise AgentsAPIError("private_readonly_file_required")
    return FDSecretStore._file_identity(info)


@contextlib.contextmanager
def _open_private(path):
    # Walk each directory without following symlinks, including parent components.
    selected = Path(path)
    if not selected.is_absolute() or ".." in selected.parts:
        raise AgentsAPIError("absolute_private_file_required")
    with contextlib.ExitStack() as stack:
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, directory)
        for part in selected.parts[1:-1]:
            directory = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            stack.callback(os.close, directory)
        info = os.stat(selected.name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise AgentsAPIError("private_readonly_file_required")
        fd = os.open(
            selected.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        stack.callback(os.close, fd)
        pin = _checked_fd(fd)
        if pin != FDSecretStore._file_identity(info):
            raise AgentsAPIError("file_changed")
        yield fd, pin


def _manifest(values, bound, admin_pin, canary_pin, *, now):
    # Handles are role-specific metadata, never hashes of secret bytes.
    admin = AdminCredentialIdentity(
        bound.project_id,
        values["admin_ref"],
        "dt017c_admin",
        bound.digest,
        now,
        now + 300,
    )
    canary = CredentialIdentity(
        bound.project_id,
        values["credential_ref"],
        values["service_account_ref"],
        "dt017c_canary",
        bound.digest,
        now,
        now + 300,
    )
    admin.validate(bound, now)
    canary.validate(bound, now)
    return {
        "binding": asdict(bound),
        "admin_identity": asdict(admin),
        "canary_identity": asdict(canary),
        "admin_fd_pin": list(admin_pin),
        "canary_fd_pin": list(canary_pin),
        "approved_models": [bound.model],
    }


def _sanitize(raw):
    value = json.loads(raw, object_pairs_hook=runner._pairs)
    expected = runner._report("READ_ONLY", "BLOCKED")
    if (
        type(value) is not dict
        or set(value) != set(expected)
        or value["mode"] != "READ_ONLY"
        or value["outcome"] not in {"BLOCKED", "COLLECTED"}
        or type(value["checks"]) is not dict
        or set(value["checks"]) != set(runner.GATES)
        or any(v not in {"PASS", runner.MISSING} for v in value["checks"].values())
        or value["LIVE"] != "NO-GO"
        or type(value["real_submissions"]) is not int
        or value["real_submissions"] != 0
        or value["live_authorized"] is not False
        or value["validation"] != expected["validation"]
        or value["schema_version"] != 1
    ):
        raise AgentsAPIError("invalid_runner_report")
    # Reconstruct instead of forwarding any arbitrary runner output.
    expected["outcome"] = value["outcome"]
    expected["checks"] = {key: value["checks"][key] for key in runner.GATES}
    return expected


def _invoke(root, manifest, admin_fd, canary_fd):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "developer_team.provider_readonly_runner",
            "--manifest",
            str(manifest),
            "--admin-fd",
            str(admin_fd),
            "--canary-fd",
            str(canary_fd),
            "--execute-real-readonly",
        ],
        cwd=root,
        pass_fds=(admin_fd, canary_fd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=300,
        check=False,
    )
    if completed.returncode != 2 or len(completed.stdout) > 16384:
        raise AgentsAPIError("runner_failed")
    return _sanitize(completed.stdout)


def _execute(values, bound, admin_fd, canary_fd, tty):
    root = _check_checkout()
    with contextlib.ExitStack() as stack:
        handles = []
        for role, supplied, ref in (
            ("Admin", admin_fd, values["admin_ref"]),
            ("Canary", canary_fd, values["credential_ref"]),
        ):
            if supplied is None:
                path = _read_path(tty, role, ref)
                handles.append(stack.enter_context(_open_private(path)))
            else:
                # Duplicate only after explicit consent; retain caller ownership.
                original_pin = _checked_fd(supplied)
                duplicate = os.dup(supplied)
                stack.callback(os.close, duplicate)
                duplicate_pin = _checked_fd(duplicate)
                if original_pin != duplicate_pin:
                    raise AgentsAPIError("file_changed")
                handles.append((duplicate, duplicate_pin))
        (admin_fd, admin_pin), (canary_fd, canary_pin) = handles
        if admin_pin[:2] == canary_pin[:2]:
            raise AgentsAPIError("separate_role_files_required")
        value = _manifest(values, bound, admin_pin, canary_pin, now=int(time.time()))
        with tempfile.TemporaryDirectory(prefix="dt017c-") as directory:
            manifest = Path(directory) / "manifest.json"
            fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                json.dump(value, stream, separators=(",", ":"))
            if _checked_fd(admin_fd) != admin_pin or _checked_fd(canary_fd) != canary_pin:
                raise AgentsAPIError("file_changed")
            return _invoke(root, manifest, admin_fd, canary_fd)


def _read_field(tty, name):
    return _read_tty(tty, f"{name} (nicht geheim; leer = HALT): ", 256).strip()


def _read_path(tty, role, ref):
    return _read_tty(
        tty,
        f"{role} ({ref}): absoluter Pfad der vorhandenen privaten Datei: ",
        4096,
    )


def _read_tty(tty, prompt, limit):
    import termios

    if tty is None or not tty.isatty():
        raise AgentsAPIError("local_tty_required")
    tty.write(prompt)
    tty.flush()
    original = termios.tcgetattr(tty.fileno())
    hidden = original.copy()
    hidden[3] &= ~termios.ECHO
    try:
        termios.tcsetattr(tty.fileno(), termios.TCSAFLUSH, hidden)
        value = tty.readline(limit + 2)
    finally:
        termios.tcsetattr(tty.fileno(), termios.TCSAFLUSH, original)
        tty.write("\n")
        tty.flush()
    if len(value) > limit + 1 or not value.endswith("\n"):
        raise AgentsAPIError("invalid_selection")
    return value.rstrip("\n")


def prepare(argv=None):
    parser = _Parser(description=__doc__, allow_abbrev=False, add_help=False)
    parser.add_argument("--execute-real-readonly", action="store_true")
    parser.add_argument("--admin-fd", type=int)
    parser.add_argument("--canary-fd", type=int)
    for name in FIELDS:
        parser.add_argument("--" + name.replace("_", "-"))
    args = parser.parse_args(argv)
    values = {name: getattr(args, name) for name in FIELDS}
    missing = [name for name in FIELDS if values[name] in (None, "")]
    if _environment_blocked() and args.execute_real_readonly:
        return _halt("offline_or_secret_environment")
    if not args.execute_real_readonly:
        return runner._report("PLAN", "NOT_EXECUTED") | {"missing_bindings": missing}
    with contextlib.ExitStack() as stack:
        tty = None
        if missing or args.admin_fd is None or args.canary_fd is None:
            # Never read redirected stdin. getpass must have a genuine local TTY.
            try:
                raw_tty = stack.enter_context(open("/dev/tty", "rb+", buffering=0))
                tty = stack.enter_context(
                    io.TextIOWrapper(raw_tty, encoding="utf-8", write_through=True)
                )
            except OSError:
                return _halt("agent_id_missing" if "agent_id" in missing else "local_tty_required")
            if not tty.isatty():
                raise AgentsAPIError("local_tty_required")
            for name in missing:
                values[name] = _read_field(tty, name)
                if not values[name]:
                    return _halt("agent_id_missing" if name == "agent_id" else "binding_missing")
        if not values["agent_id"]:
            return _halt("agent_id_missing")
        try:
            values["budget_cents"] = int(values["budget_cents"])
            bound = _binding(values)
        except Exception:
            return _halt("invalid_binding")
        return _execute(values, bound, args.admin_fd, args.canary_fd, tty)


def main(argv=None):
    try:
        report = prepare(argv)
    except (Exception, KeyboardInterrupt):
        report = _halt("local_prepare_blocked")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
