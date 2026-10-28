"""Git facts the hooks and commands of part 2 share: the default branch, the main checkout,
whether the project has a `.relay/` folder, and the worktrees.

The default branch is never the current branch (a worktree sits on `wt/...`): it is, in order,
the target of `refs/remotes/origin/HEAD`; the binding `project.default_branch` of the main
checkout's `.claude/kit.toml`, ignored when it names a `wt/` branch (or when the file cannot
be read); `master` if it is a local branch; `main` likewise; else None. None means "no
`.relay/`": the hooks then do nothing.
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import os
import subprocess
from typing import TypedDict

import relay_toml

TIMEOUT = 20


class Worktree(TypedDict):
    path: str              # real path
    branch: str | None     # short name, None when detached
    locked: str | None     # the reason ("" if none given); None when not locked


def git(repo: str, *args: str, timeout: float = TIMEOUT, raw: bool = False) -> tuple[int, str]:
    """(exit code, stdout stripped unless raw) of `git -C repo args`; (127, "") when git cannot run."""
    try:
        done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, done.stdout if raw else done.stdout.strip()


def main_checkout(repo: str) -> str | None:
    """The folder holding the repository's `.git` (parent of the git common dir), real path; None outside a repository."""
    rc, out = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not out:
        return None
    return os.path.realpath(os.path.join(out, ".."))


def _binding(main: str) -> str | None:
    path = os.path.join(main, ".claude", "kit.toml")
    try:
        with open(path, "rb") as handle:
            data = relay_toml.load(handle)
    except (OSError, ValueError):
        return None
    value = (data.get("project") or {}).get("default_branch")
    return value if isinstance(value, str) and value and not value.startswith("wt/") else None


def default_branch(repo: str) -> str | None:
    """The branch merges go into, or None when it cannot be told (see the module text)."""
    main = main_checkout(repo)
    if main is None:
        return None
    rc, out = git(main, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out:
        name = out[len("origin/"):] if out.startswith("origin/") else out
        if name and not name.startswith("wt/"):
            return name
    bound = _binding(main)
    if bound:
        return bound
    for name in ("master", "main"):
        if git(main, "show-ref", "--verify", "--quiet", "refs/heads/" + name)[0] == 0:
            return name
    return None


def current_branch(directory: str) -> str | None:
    """The branch checked out in `directory`, None when detached or not a repository."""
    rc, out = git(directory, "symbolic-ref", "--short", "-q", "HEAD")
    return out if rc == 0 and out else None


def has_relay(repo: str) -> bool:
    """True when the default branch's committed tree holds a `.relay/` folder."""
    main = main_checkout(repo)
    branch = default_branch(repo) if main else None
    if main is None or branch is None:
        return False
    for ref in ("refs/heads/" + branch, "refs/remotes/origin/" + branch):
        rc, out = git(main, "ls-tree", "-d", "--name-only", ref, ".relay")
        if rc == 0 and out == ".relay":
            return True
    return False


def worktrees(repo: str) -> list[Worktree]:
    """Every worktree: dicts with path (real), branch (short name or None), locked (reason, "" if none given; None if not locked)."""
    rc, out = git(repo, "worktree", "list", "--porcelain")
    if rc != 0:
        return []
    result: list[Worktree] = []
    cur: Worktree | None = None
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                result.append(cur)
            cur = None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            cur = {"path": os.path.realpath(value), "branch": None, "locked": None}
        elif cur is not None and key == "branch":
            cur["branch"] = value[len("refs/heads/"):] if value.startswith("refs/heads/") else value
        elif cur is not None and key == "locked":
            cur["locked"] = value
    return result


def has_own_commits(repo: str, branch: str) -> bool:
    """The branch's reflog holds an entry other than its creation, a fast-forward or a reset (a fresh worktree has none)."""
    rc, out = git(repo, "reflog", "show", "--format=%gs", "refs/heads/" + branch)
    if rc != 0:
        return False
    for subject in out.splitlines():
        if subject.startswith("branch: Created from") or subject.endswith("Fast-forward") or subject.startswith("reset: moving to"):
            continue
        return True
    return False
