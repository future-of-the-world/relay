"""Git facts the hooks and commands of part 2 share: the default branch, the main checkout,
whether the project has a `.relay/` folder, and the worktrees.

The default branch is never the current branch (a worktree sits on `wt/...`): it is, in order,
the target of `refs/remotes/origin/HEAD`; the binding `project.default_branch` of the main
checkout's `.claude/kit.toml`, ignored when it names a `wt/` branch (or when the file cannot
be read); `master` if it is a local branch; `main` likewise; else None. None means "no
`.relay/`": the hooks then do nothing.
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import contextlib
import os
import re
import subprocess
from typing import Iterator, TypedDict

import relay_toml

TIMEOUT = 20


class Worktree(TypedDict):
    path: str              # real path
    branch: str | None     # short name, None when detached
    locked: str | None     # the reason ("" if none given); None when not locked
    prunable: bool         # git lists it but its folder is gone (git worktree prune would drop it)


class GitError(Exception):
    """git could not answer (it did not run or timed out): "git could not answer: <command>, <reason>"."""


# Reads that cannot change are asked of git once per process: a command whose every revision is a full commit sha
# (the object never changes) and which only reads. Anything else is asked each time, except inside `reading()`.
_PURE_COMMANDS = ("rev-parse", "merge-base", "rev-list", "diff", "show", "ls-tree", "cat-file")
_PURE_REV = re.compile(r"\^?[0-9a-f]{40}(\^[12]|\^\{commit\})*(\.\.[0-9a-f]{40})?(:.*)?\Z")
_PURE_LIMIT = 4000      # entries kept; a long process drops the oldest first, a short one never reaches it
_Key = tuple[str, tuple[str, ...]]
_pure: dict[_Key, tuple[int, str, str]] = {}
_window: dict[_Key, tuple[int, str, str]] | None = None      # the answers of the open `reading()`, else None


def _is_pure(args: tuple[str, ...]) -> bool:
    if not args or args[0] not in _PURE_COMMANDS:
        return False
    revs = 0
    for arg in args[1:]:
        if arg == "--":
            break
        if arg.startswith("-"):
            continue
        if not _PURE_REV.match(arg):
            return False
        revs += 1
    return revs > 0


@contextlib.contextmanager
def reading() -> Iterator[None]:
    """Inside, git is asked each distinct question once (refs, branches and the default branch included): for a read-only
    run (a check record, `relay check show`) that moves no ref. Not for code that commits and then reads again."""
    global _window
    outer = _window
    if outer is None:
        _window = {}
    try:
        yield
    finally:
        if outer is None:
            _window = None


def capture(repo: str, *args: str, timeout: float | None = None) -> tuple[int, str, str]:
    """(exit code, raw stdout, raw stderr) of `git -C repo args`; GitError when git cannot run or times out.
    Answers that cannot change (see above), and any answer inside `reading()`, are kept."""
    key = (os.path.realpath(repo), args)
    pure = _is_pure(args)
    kept = _pure if pure else _window
    if kept is not None and key in kept:
        return kept[key]
    command = ["git", "-C", repo, *args]
    limit = TIMEOUT if timeout is None else timeout      # read at call time, so a test can lower the module's limit
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        raise GitError("git could not answer: %s, no answer within %s s" % (" ".join(command), limit))
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError("git could not answer: %s, %s" % (" ".join(command), exc))
    answer = (done.returncode, done.stdout, done.stderr)
    final = done.returncode == 0 or (done.returncode == 1 and args[:2] == ("merge-base", "--is-ancestor"))      # "not an ancestor" is an answer
    if pure and final and len(_pure) >= _PURE_LIMIT:
        del _pure[next(iter(_pure))]
    if kept is not None and (final or not pure):      # a missing object may be made later: only its presence is kept
        kept[key] = answer
    return answer


def _run(repo: str, args: tuple[str, ...], timeout: float | None, raw: bool) -> tuple[int, str]:
    code, out, _ = capture(repo, *args, timeout=timeout)
    return code, out if raw else out.strip()


def git(repo: str, *args: str, timeout: float | None = None, raw: bool = False) -> tuple[int, str]:
    """(exit code, stdout stripped unless raw) of `git -C repo args`; (127, "") when git cannot run or times out
    (callers that must tell that from an empty answer use `git_strict`)."""
    try:
        return _run(repo, args, timeout, raw)
    except GitError:
        return 127, ""


def git_strict(repo: str, *args: str, timeout: float | None = None, raw: bool = False) -> tuple[int, str]:
    """Like `git`, but raises GitError when git cannot run or times out."""
    return _run(repo, args, timeout, raw)


_mains: dict[str, str] = {}


def main_checkout(repo: str) -> str | None:
    """The folder holding the repository's `.git` (parent of the git common dir), real path; None outside a repository."""
    key = os.path.realpath(repo)
    if key in _mains:
        return _mains[key]
    rc, out = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not out:
        return None
    _mains[key] = os.path.realpath(os.path.join(out, ".."))      # where a folder's repository is never changes; "none" is not kept
    return _mains[key]


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


def current_branch(directory: str, strict: bool = False) -> str | None:
    """The branch checked out in `directory`, None when detached or not a repository.
    With `strict`, GitError when git itself could not answer (timeout), instead of None."""
    rc, out = (git_strict if strict else git)(directory, "symbolic-ref", "--short", "-q", "HEAD")
    if strict and rc not in (0, 1):      # `symbolic-ref -q` exits 1 and only 1 for a detached HEAD; a signal (rc < 0) or a fatal 128 is no answer
        command = "git -C %s symbolic-ref --short -q HEAD" % directory
        why = "killed by signal %d" % -rc if rc < 0 else "exit %d" % rc
        raise GitError("git could not answer: %s, %s" % (command, why))
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
            cur = {"path": os.path.realpath(value), "branch": None, "locked": None, "prunable": False}
        elif cur is not None and key == "branch":
            cur["branch"] = value[len("refs/heads/"):] if value.startswith("refs/heads/") else value
        elif cur is not None and key == "locked":
            cur["locked"] = value
        elif cur is not None and key == "prunable":
            cur["prunable"] = True
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
