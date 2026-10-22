"""Offline consistency checks only; no authority, execution or provider integration."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SECURITY_CHECKS = frozenset(
    {"secrets", "permissions", "dependencies", "deployment", "role_isolation",
     "remote_stop", "budgets", "branch_protection"}
)
BINDING_FIELDS = {"repo", "issue", "branch", "base_sha", "pr", "head_sha"}


class InvalidHandoff(ValueError):
    """Malformed or ambiguous local input."""


def _object(value: object, fields: set[str]) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise InvalidHandoff("missing_or_unknown_fields")
    return value


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and all(ord(c) >= 32 for c in value)


def _paths(value: object) -> list[str]:
    if type(value) is not list or not value:
        raise InvalidHandoff("missing_paths")
    for path in value:
        if not _text(path) or not re.fullmatch(r"[A-Za-z0-9_./-]+", path):
            raise InvalidHandoff("invalid_path")
        if any(p in ("", ".", "..", ".git") for p in path.split("/")):
            raise InvalidHandoff("invalid_path")
    if len(set(value)) != len(value):
        raise InvalidHandoff("duplicate_path")
    return value


def _binding(value: object) -> dict:
    item = _object(value, BINDING_FIELDS)
    if not _text(item["repo"]) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", item["repo"]
    ):
        raise InvalidHandoff("invalid_repository")
    if any(type(item[key]) is not int or item[key] <= 0 for key in ("issue", "pr")):
        raise InvalidHandoff("missing_issue_or_pr")
    if not _text(item["branch"]):
        raise InvalidHandoff("missing_branch")
    for key in ("base_sha", "head_sha"):
        if type(item[key]) is not str or not re.fullmatch(r"[0-9a-f]{40}", item[key]):
            raise InvalidHandoff("missing_or_invalid_commit")
        if item[key] == "0" * 40:
            raise InvalidHandoff("null_commit")
    return item


def _strings(value: object) -> list[str]:
    if type(value) is not list or not all(_text(v) for v in value):
        raise InvalidHandoff("invalid_list")
    return value


def _result(value: object, reasons: list[str], label: str) -> None:
    item = _object(value, {"status", "evidence"})
    if item["status"] != "PASS" or not _text(item["evidence"]):
        reasons.append(f"missing_or_nonpass:{label}")


def check_handoff(data: object, *, expected: dict, allowed_files: list[str]) -> dict:
    """Compare untrusted claims to separately supplied operator pins, never approve."""
    reasons: list[str] = []
    try:
        pins = _binding(expected)
        allowed = _paths(allowed_files)
        item = _object(data, {"version", "binding", "allowed_files", "changed_files", "developer",
                              "ci", "qa", "security", "risks", "unknown_checks", "blockers"})
        if type(item["version"]) is not int or item["version"] != 1:
            raise InvalidHandoff("unsupported_version")
        if _binding(item["binding"]) != pins:
            reasons.append("unexpected_binding")
        if set(_paths(item["allowed_files"])) != set(allowed):
            reasons.append("unexpected_scope")
        if not set(_paths(item["changed_files"])) <= set(allowed):
            reasons.append("forbidden_changed_files")
        if not _text(item["developer"]):
            reasons.append("missing_developer")
        for key in ("risks", "unknown_checks", "blockers"):
            if _strings(item[key]):
                reasons.append(f"open:{key}")
        ci = _object(item["ci"], {"binding", "run_url", "jobs"})
        if _binding(ci["binding"]) != pins:
            reasons.append("stale_ci")
        if type(ci["run_url"]) is not str or not re.fullmatch(
            rf"https://github\.com/{re.escape(pins['repo'])}/actions/runs/[1-9][0-9]*",
            ci["run_url"],
        ):
            reasons.append("missing_ci_run")
        if type(ci["jobs"]) is not dict or not ci["jobs"]:
            reasons.append("missing_ci_jobs")
        else:
            for name, result in ci["jobs"].items():
                if not _text(name):
                    raise InvalidHandoff("invalid_job_name")
                _result(result, reasons, "ci_job")
        reviewers = [item["developer"]]
        for role in ("qa", "security"):
            fields = {"binding", "reviewer", "task_ref", "status", "evidence"}
            review = _object(item[role], fields | ({"checks"} if role == "security" else set()))
            if _binding(review["binding"]) != pins:
                reasons.append(f"stale_review:{role}")
            if not _text(review["reviewer"]) or not _text(review["task_ref"]):
                reasons.append(f"missing_review_provenance:{role}")
            reviewers.append(review["reviewer"])
            _result({k: review[k] for k in ("status", "evidence")}, reasons, role)
            if role == "security":
                checks = _object(review["checks"], set(SECURITY_CHECKS))
                for name, result in checks.items():
                    _result(result, reasons, f"security:{name}")
        if not all(type(v) is str for v in reviewers) or len(set(reviewers)) != 3:
            reasons.append("roles_not_distinct")
        if item["qa"]["task_ref"] == item["security"]["task_ref"]:
            reasons.append("review_tasks_not_distinct")
    except InvalidHandoff as exc:
        reasons.append(str(exc))
    return {
        "status": "BLOCKED" if reasons else "MANUAL_REVIEW_REQUIRED",
        "reasons": sorted(set(reasons)),
        "merge_authorized": False,
        "cloud_authorized": False,
        "provenance_verified": False,
        "limitations": ["offline_claims_only", "commit_existence_unverified",
                        "live_ci_and_scope_unverified", "role_attestation_unverified"],
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidHandoff("duplicate_json_key")
        result[key] = value
    return result


def load_handoff(path: Path) -> object:
    """Read a bounded UTF-8 JSON file; duplicate keys are rejected at every level."""
    with path.open("rb") as source:
        raw = source.read(1_000_001)
    if len(raw) > 1_000_000:
        raise InvalidHandoff("input_too_large")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lokaler DT-010-Abgleich; keine Freigabe")
    parser.add_argument("manifest", type=Path)
    for name in ("repo", "issue", "branch", "base-sha", "pr", "head-sha"):
        parser.add_argument(
            f"--{name}", required=True, type=int if name in ("issue", "pr") else str
        )
    parser.add_argument("--allowed-file", action="append", required=True)
    args = parser.parse_args(argv)
    expected = {key: getattr(args, key) for key in BINDING_FIELDS}
    try:
        data = load_handoff(args.manifest)
    except (OSError, ValueError, UnicodeError, RecursionError):
        data = None
    report = check_handoff(data, expected=expected, allowed_files=args.allowed_file)
    print(json.dumps(report, indent=2))
    # Even complete claims require external, human review. Never a success/approval token.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
