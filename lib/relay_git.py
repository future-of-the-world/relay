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
import select
import subprocess
import time
from typing import Iterator, Optional, TypedDict

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


# Options that pull in refs, the index or the working tree: the answer then depends on more than the shas named.
_IMPURE_OPTIONS = frozenset(("--all", "--branches", "--tags", "--remotes", "--glob", "--cached", "--staged", "--stdin", "--no-index"))


def _is_pure(args: tuple[str, ...]) -> bool:
    if not args or args[0] not in _PURE_COMMANDS:
        return False
    revs = 0
    for arg in args[1:]:
        if arg == "--":
            break
        if arg.startswith("-"):
            if arg.split("=", 1)[0] in _IMPURE_OPTIONS:
                return False
            continue
        if not _PURE_REV.match(arg):
            return False
        revs += 2 if ".." in arg else 1
    return revs >= (2 if args[0] == "diff" else 1)      # `git diff <one revision>` compares with the working tree


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
            for opened in list(_objects.values()):
                opened.close()
            _objects.clear()


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


# ---------------------------------------------------------------- object reads without a process each
#
# Inside `reading()` no ref moves, so the commit graph and every object can be read once and then answered in Python: one
# `git rev-list --parents --all` for the graph and one long-lived `git cat-file --batch` for commits, trees and files, per
# repository folder. A question about a merge, a commit's tree or a stored mark then costs no process, so the number of git
# processes of a run does not grow with the number of merges, commits or marks. Outside `reading()` (a hook that commits and
# reads again) these helpers ask git one question per call, as before.

_OBJECT_HEADER = re.compile(rb"[0-9a-f]{40,64} (blob|tree|commit|tag) (\d+)\Z")
_TREE = "40000"
_Entries = dict[str, tuple[str, str]]


class _Graph:
    """The commits of a repository with their parents, in git's topological order (children first)."""

    def __init__(self, text: str) -> None:
        self.parents: dict[str, tuple[str, ...]] = {}
        self.rank: dict[str, int] = {}
        for line in text.splitlines():
            shas = line.split()
            if shas:
                self.rank[shas[0]] = len(self.rank)
                self.parents[shas[0]] = tuple(shas[1:])
        self._ancestors: dict[str, frozenset[str]] = {}

    def ancestors(self, tip: str) -> Optional[frozenset[str]]:
        """`tip` and everything behind it; None when `tip` is not in the graph."""
        if tip not in self.parents:
            return None
        if tip not in self._ancestors:
            seen: set[str] = set()
            todo = [tip]
            while todo:
                commit = todo.pop()
                if commit not in seen:
                    seen.add(commit)
                    todo.extend(self.parents.get(commit, ()))
            self._ancestors[tip] = frozenset(seen)
        return self._ancestors[tip]


class _Tree:
    """The files of one commit, read on demand: `get(path)` is the blob id, `entry(path)` the (mode, blob id), None if absent."""

    def __init__(self, objects: "_Objects", commit: str) -> None:
        self._objects, self._commit = objects, commit
        self._seen: dict[str, Optional[tuple[str, str]]] = {}

    def entry(self, path: str) -> Optional[tuple[str, str]]:
        if path not in self._seen:
            self._seen[path] = self._objects.entry(self._commit, path)
        return self._seen[path]

    def get(self, path: str) -> Optional[str]:
        found = self.entry(path)
        return found[1] if found else None

    def __contains__(self, path: str) -> bool:
        return self.entry(path) is not None


class _Objects:
    def __init__(self, repo: str) -> None:
        self.repo = repo
        self._found: dict[str, Optional[tuple[str, str, bytes]]] = {}
        self._trees: dict[str, _Entries] = {}
        self._graph: Optional[_Graph] = None
        self._graph_tried = False
        try:
            self._proc: Optional[subprocess.Popen[bytes]] = subprocess.Popen(
                ["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as exc:
            raise GitError("git could not answer: git -C %s cat-file --batch, %s" % (repo, exc))

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            for pipe in (proc.stdin, proc.stdout):
                if pipe is not None:
                    pipe.close()
            proc.wait()

    def _read(self, size: int, deadline: float) -> bytes:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise GitError("git could not answer: git -C %s cat-file --batch, it has ended" % self.repo)
        data = b""
        while len(data) < size:
            if select.select([proc.stdout], [], [], max(0.0, deadline - time.monotonic()))[0] == []:
                self.close()
                raise GitError("git could not answer: git -C %s cat-file --batch, no answer within %s s" % (self.repo, TIMEOUT))
            chunk = proc.stdout.read(size - len(data))
            if not chunk:
                self.close()
                raise GitError("git could not answer: git -C %s cat-file --batch, it ended" % self.repo)
            data += chunk
        return data

    def get(self, spec: str) -> Optional[tuple[str, str, bytes]]:
        """(object id, type, content) of the object `spec` names, None when there is none. Kept for the window."""
        if spec in self._found:
            return self._found[spec]
        found: Optional[tuple[str, str, bytes]] = None
        if "\n" not in spec and self._proc is not None and self._proc.stdin is not None:
            deadline = time.monotonic() + TIMEOUT
            try:
                self._proc.stdin.write(spec.encode("utf-8", "surrogateescape") + b"\n")
            except OSError as exc:
                self.close()
                raise GitError("git could not answer: git -C %s cat-file --batch, %s" % (self.repo, exc))
            header = b""
            while not header.endswith(b"\n"):
                header += self._read(1, deadline)
            match = _OBJECT_HEADER.match(header[:-1])
            if match:
                data = self._read(int(match.group(2)) + 1, deadline)[:-1]
                found = (header.split()[0].decode(), match.group(1).decode(), data)
        self._found[spec] = found
        return found

    def commit(self, spec: str) -> Optional[str]:
        found = self.get(spec + "^{commit}")
        return found[0] if found else None

    def tree_of(self, commit: str) -> Optional[str]:
        found = self.get(commit)
        if not found or found[1] != "commit" or not found[2].startswith(b"tree "):
            return None
        return found[2][5:found[2].index(b"\n")].decode()

    def entries(self, tree: str) -> _Entries:
        if tree not in self._trees:
            found = self.get(tree)
            out: _Entries = {}
            if found and found[1] == "tree":
                width, data, at = len(found[0]) // 2, found[2], 0
                while at < len(data):
                    space, nul = data.index(b" ", at), data.index(b"\0", at)
                    out[data[space + 1:nul].decode("utf-8", "surrogateescape")] = (data[at:space].decode(), data[nul + 1:nul + 1 + width].hex())
                    at = nul + 1 + width
            self._trees[tree] = out
        return self._trees[tree]

    def entry(self, commit: str, path: str) -> Optional[tuple[str, str]]:
        tree = self.tree_of(commit)
        parts = path.split("/")
        for number, part in enumerate(parts):
            if tree is None:
                return None
            found = self.entries(tree).get(part)
            if found is None:
                return None
            if number == len(parts) - 1:
                return None if found[0] == _TREE else found       # a folder is no file (`ls-tree -r` lists files only)
            tree = found[1] if found[0] == _TREE else None
        return None

    def _walk(self, old: Optional[str], new: Optional[str], prefix: str, out: list[str]) -> None:
        before, after = (self.entries(old) if old else {}), (self.entries(new) if new else {})
        for name in sorted(set(before) | set(after)):
            x, y = before.get(name), after.get(name)
            if x == y:
                continue
            was, now = x is not None and x[0] == _TREE, y is not None and y[0] == _TREE
            if was or now:
                self._walk(x[1] if x is not None and was else None, y[1] if y is not None and now else None, prefix + name + "/", out)
            if (x is not None and not was) or (y is not None and not now):
                out.append(prefix + name)

    def changed(self, older: str, newer: str) -> Optional[list[str]]:
        """The files that differ between two commits (renames count as a delete and an add), sorted; None if a commit is unreadable."""
        a, b = self.tree_of(older), self.tree_of(newer)
        if a is None or b is None:
            return None
        out: list[str] = []
        self._walk(a, b, "", out)
        return sorted(out)

    def graph(self) -> Optional[_Graph]:
        if not self._graph_tried:
            self._graph_tried = True
            for tips in (["--all", "HEAD"], ["--all"]):
                code, out, _ = capture(self.repo, "rev-list", "--topo-order", "--parents", *tips)
                if code == 0:
                    self._graph = _Graph(out)
                    break
        return self._graph


_objects: dict[str, _Objects] = {}


def objects(repo: str) -> Optional[_Objects]:
    """The window's object reader for `repo`'s folder; None outside `reading()` (or when git cannot start)."""
    if _window is None:
        return None
    key = os.path.realpath(repo)
    if key not in _objects:
        try:
            _objects[key] = _Objects(repo)
        except GitError:
            return None
    return _objects[key]


def resolve_commit(repo: str, spec: str) -> Optional[str]:
    """The full sha of the commit `spec` names (a sha, a ref, `x^2`), None when there is none."""
    opened = objects(repo)
    if opened is not None:
        try:
            return opened.commit(spec)
        except GitError:
            return None
    code, out = git(repo, "rev-parse", "--verify", "-q", spec + "^{commit}")
    return out if code == 0 and out else None


def is_ancestor(repo: str, older: str, newer: str) -> bool:
    opened = objects(repo)
    if opened is not None:
        graph = opened.graph()
        a, b = resolve_commit(repo, older), resolve_commit(repo, newer)
        behind = graph.ancestors(b) if graph is not None and b is not None else None
        if behind is not None and a is not None:
            return a in behind
    return git(repo, "merge-base", "--is-ancestor", older, newer)[0] == 0


def merge_base(repo: str, one: str, other: str) -> Optional[str]:
    """A best common ancestor of two commits, None when they have none."""
    opened = objects(repo)
    if opened is not None:
        graph = opened.graph()
        a, b = resolve_commit(repo, one), resolve_commit(repo, other)
        left = graph.ancestors(a) if graph is not None and a is not None else None
        right = graph.ancestors(b) if graph is not None and b is not None else None
        if graph is not None and left is not None and right is not None:
            common = left & right
            return min(common, key=lambda c: graph.rank.get(c, len(graph.rank))) if common else None       # first in children-first order: no common descendant
    code, out = git(repo, "merge-base", one, other)
    return out if code == 0 and out else None


def changed_paths(repo: str, older: str, newer: str) -> Optional[list[str]]:
    """The files that differ between two commits (like `git diff --name-only --no-renames`), None when git cannot tell."""
    opened = objects(repo)
    if opened is not None:
        a, b = resolve_commit(repo, older), resolve_commit(repo, newer)
        try:
            found = opened.changed(a, b) if a is not None and b is not None else None
        except GitError:
            found = None
        if found is not None:
            return found
    code, out = git(repo, "diff", "--name-only", "--no-renames", "-z", older, newer, raw=True)
    return [name for name in out.split("\0") if name] if code == 0 else None


def tree_files(repo: str, commit: str) -> Optional[_Tree]:
    """The files of the commit `commit` (a full sha), read on demand; None outside `reading()`."""
    opened = objects(repo)
    return _Tree(opened, commit) if opened is not None else None


def stored_text(repo: str, spec: str) -> Optional[str]:
    """The content of the file `spec` names (`<ref>:<path>`), None when there is none."""
    opened = objects(repo)
    if opened is not None:
        try:
            found = opened.get(spec)
        except GitError:
            return None
        return found[2].decode("utf-8", "replace") if found and found[1] == "blob" else None
    code, out = git(repo, "show", spec, raw=True)
    return out if code == 0 else None


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
