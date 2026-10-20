"""Strict versioned TOML configuration; project preferences never grant authority."""

from __future__ import annotations

import fnmatch
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from .models import TeamError, digest

ALWAYS_PROTECTED = (
    ".github/**",
    ".developer-team/**",
    "**/.github/**",
    "**/.developer-team/**",
    "AGENTS.md",
    "**/AGENTS.md",
    "SECURITY.md",
    "**/SECURITY.md",
)


class ConfigError(TeamError):
    pass


def relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or PurePosixPath(value).is_absolute()
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ConfigError("Paths must be nonempty, relative POSIX paths without traversal")
    return value


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    relative_path(path)
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _keys(data: dict, allowed: set[str], required: set[str], label: str) -> None:
    if not isinstance(data, dict) or set(data) - allowed or required - set(data):
        raise ConfigError(f"Invalid or missing keys in {label}")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ConfigError(f"Invalid {label}")
    return value


def _strings(value: object, label: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ConfigError(f"Invalid {label}")
    result = tuple(_text(item, label) for item in value)
    if len(result) != len(set(result)):
        raise ConfigError(f"Duplicate entries in {label}")
    return result


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ConfigError(f"Invalid boolean: {label}")
    return value


@dataclass(frozen=True)
class Check:
    name: str
    kind: str
    argv: tuple[str, ...]
    timeout_seconds: int
    required: bool


@dataclass(frozen=True)
class ProjectConfig:
    schema_version: int
    id: str
    repository: str
    provider: str
    base_branch: str
    languages: tuple[str, ...]
    frameworks: tuple[str, ...]
    instruction_files: tuple[str, ...]
    security_files: tuple[str, ...]
    protected_paths: tuple[str, ...]
    checks: tuple[Check, ...]
    auto_merge: bool
    merge_method: str
    max_repairs: int
    max_steps: int
    test_paths: tuple[str, ...]
    documentation_paths: tuple[str, ...]

    @property
    def digest(self) -> str:
        return digest(asdict(self))

    def protected(self, path: str) -> bool:
        return matches(path, ALWAYS_PROTECTED + self.protected_paths) or path in (
            self.instruction_files + self.security_files
        )


def load_config(path: Path) -> ProjectConfig:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read project configuration: {type(exc).__name__}") from exc
    _keys(
        data,
        {
            "schema_version",
            "project",
            "instructions",
            "security",
            "checks",
            "merge",
            "limits",
            "delivery",
        },
        {"schema_version", "project", "checks"},
        "root",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ConfigError("Only schema_version = 1 is supported")
    project = data["project"]
    _keys(
        project,
        {"id", "repository", "provider", "base_branch", "languages", "frameworks"},
        {"id", "repository", "provider", "base_branch", "languages"},
        "project",
    )
    project_id = _text(project["id"], "project id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", project_id):
        raise ConfigError("Invalid project id")
    repository = _text(project["repository"], "repository")
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repository
    ) or repository.split("/")[-1] in (".", ".."):
        raise ConfigError("Repository must be owner/name without URL or credentials")
    provider = project["provider"]
    if provider not in ("local", "github"):
        raise ConfigError("Provider must be local or github")
    branch = _text(project["base_branch"], "base branch")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]*", branch) or "//" in branch:
        raise ConfigError("Invalid base branch")

    instructions = data.get("instructions", {})
    security = data.get("security", {})
    merge = data.get("merge", {})
    limits = data.get("limits", {})
    delivery = data.get("delivery", {})
    _keys(instructions, {"files"}, set(), "instructions")
    _keys(security, {"policy_files", "protected_paths"}, set(), "security")
    _keys(merge, {"enabled", "method"}, set(), "merge")
    _keys(limits, {"max_repairs_per_class", "max_steps"}, set(), "limits")
    _keys(delivery, {"test_paths", "documentation_paths"}, set(), "delivery")
    max_repairs = limits.get("max_repairs_per_class", 3)
    max_steps = limits.get("max_steps", 60)
    if type(max_repairs) is not int or not 0 <= max_repairs <= 3:
        raise ConfigError("max_repairs_per_class must be between 0 and 3")
    if type(max_steps) is not int or not 10 <= max_steps <= 100:
        raise ConfigError("max_steps must be between 10 and 100")
    method = merge.get("method", "squash")
    if method not in ("merge", "squash", "rebase"):
        raise ConfigError("Unsupported merge method")

    raw_checks = data["checks"]
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ConfigError("At least one required test is necessary")
    checks = []
    for check in raw_checks:
        _keys(
            check,
            {"name", "kind", "argv", "timeout_seconds", "required"},
            {"name", "kind", "argv"},
            "check",
        )
        name = _text(check["name"], "check name")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
            raise ConfigError("Invalid check name")
        if check["kind"] not in ("test", "build", "lint"):
            raise ConfigError("Check kind must be test, build or lint")
        timeout = check.get("timeout_seconds", 60)
        if type(timeout) is not int or not 1 <= timeout <= 1800:
            raise ConfigError("Check timeout must be between 1 and 1800 seconds")
        checks.append(
            Check(
                name,
                check["kind"],
                _strings(check["argv"], "argv"),
                timeout,
                _boolean(check.get("required", True), "required"),
            )
        )
    if len({c.name for c in checks}) != len(checks):
        raise ConfigError("Check names must be unique")
    if not any(c.required and c.kind == "test" for c in checks):
        raise ConfigError("At least one required test is necessary")

    def paths(values: object, label: str, *, nonempty: bool = True) -> tuple[str, ...]:
        return tuple(relative_path(p) for p in _strings(values, label, nonempty=nonempty))

    return ProjectConfig(
        1,
        project_id,
        repository,
        provider,
        branch,
        _strings(project["languages"], "languages"),
        _strings(project.get("frameworks", []), "frameworks", nonempty=False),
        paths(instructions.get("files", ["AGENTS.md"]), "instructions"),
        paths(security.get("policy_files", ["SECURITY.md"]), "policies"),
        paths(security.get("protected_paths", []), "protected_paths", nonempty=False),
        tuple(checks),
        _boolean(merge.get("enabled", False), "merge.enabled"),
        method,
        max_repairs,
        max_steps,
        paths(delivery.get("test_paths", ["tests/**"]), "test_paths"),
        paths(delivery.get("documentation_paths", ["docs/**", "README.md"]), "docs"),
    )
