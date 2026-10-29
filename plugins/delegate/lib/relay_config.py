"""Where relay finds things, and the project bindings it reads.

- ROOT: this repository (RELAY_ROOT overrides).
- HOME_DIR: ~/.relay (RELAY_HOME overrides): the ledger, bench results, state.
- CLAUDE_DIR: ~/.claude (CLAUDE_CONFIG_DIR overrides): transcripts, settings, agents.
- A project's bindings: <project>/.claude/kit.toml (unchanged from the principles
  library, so nothing a migrated project already has breaks). Relay adds its own
  sections to that file: [flow], [delegate], [observe].
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import os
import subprocess
from typing import Any

import relay_toml

ROOT = os.environ.get("RELAY_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def projects_file() -> str:
    return os.environ.get("RELAY_PROJECTS") or os.path.join(ROOT, "projects.toml")


def home_dir() -> str:
    return os.path.expanduser(os.environ.get("RELAY_HOME") or "~/.relay")


def claude_dir() -> str:
    return os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")


def claude_json() -> str:
    """Claude Code's own state file: where it keeps /cost's per-session figures (`lastModelUsage`).
    With CLAUDE_CONFIG_DIR it sits inside that folder, else it is ~/.claude.json."""
    if os.environ.get("RELAY_CLAUDE_JSON"):
        return os.path.expanduser(os.environ["RELAY_CLAUDE_JSON"])
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return os.path.join(claude_dir(), ".claude.json")
    return os.path.expanduser("~/.claude.json")


def ledger_dir() -> str:
    return os.path.join(home_dir(), "ledger")


def bench_dir() -> str:
    return os.path.join(home_dir(), "bench")


def read_toml(path: str) -> dict[str, Any]:
    with open(path, "rb") as handle:
        return relay_toml.load(handle)


def project_root(cwd: str | None = None) -> str:
    """The git top-level of cwd (a worktree's own root inside a worktree), else cwd."""
    cwd = cwd or os.getcwd()
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return out or cwd


def main_checkout(cwd: str | None = None) -> str:
    """The main checkout of the repository cwd belongs to (worktrees share it)."""
    cwd = cwd or os.getcwd()
    try:
        common = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=False, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        common = ""
    if not common:
        return project_root(cwd)
    return os.path.realpath(os.path.join(common, ".."))


def bindings_path(root: str) -> str:
    return os.path.join(root, ".claude", "kit.toml")


def load_bindings(root: str) -> dict[str, Any]:
    """The project's kit.toml as a dict, or {} when the project has none."""
    path = bindings_path(root)
    if not os.path.isfile(path):
        return {}
    return read_toml(path)


def worktrees_folder(main: str) -> str:
    """The folder that holds the task worktrees: project.worktrees of kit.toml, default .worktrees.
    A relative value is under main; an absolute value stays where it is."""
    value = get(load_bindings(main), "project.worktrees")
    folder = value.rstrip("/") if isinstance(value, str) else ""
    return os.path.normpath(os.path.join(main, folder or ".worktrees"))


def get(cfg: Any, dotted: str, default: Any = None) -> Any:
    value = cfg
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def relay_defaults() -> dict[str, dict[str, Any]]:
    """Defaults for the relay sections of kit.toml (profiles/active.toml holds the policy)."""
    return {
        "flow": {"kind": "none"},
        "delegate": {
            "typed_only": True,
            "fork_limit": 100_000,
            "max_parallel": 4,
            "build_tier_opus": "escalate",   # escalate | allow | deny
        },
        "observe": {"enabled": True, "log_prompts": False},
    }


def active_profile() -> dict[str, Any]:
    path = os.path.join(ROOT, "profiles", "active.toml")
    return read_toml(path) if os.path.isfile(path) else {}
