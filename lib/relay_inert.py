"""The inert list: files whose content never decides a check or a merge (state files, not code).

The list is fixed here, not a setting. A pattern matches a path relative to the repository root, with "/" as the
separator: "*" matches inside one path part (any characters but "/"), "**" matches any number of whole parts (zero
or more). `changed()` lists what changed since a commit and is not inert: it is the file list the checker works from.
With `own=True` it leaves out the files that only the default branch changed (design section 7.2).
"""

import re
import subprocess

import relay_git

INERT = (
    "docs/handover.md",
    ".relay/queue/**",
    ".relay/checks/**",
)


def _regex(pattern):
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


_COMPILED = [_regex(p) for p in INERT]


def matches(path):
    """True when `path` (repository-relative) is on the inert list."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return any(rx.match(path) for rx in _COMPILED)


def _git(repo, *args):
    run = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if run.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed in {repo}: {run.stderr.strip()}")
    return run.stdout


def _blobs(repo, commit):
    """{path: blob id} of every file at `commit` (one `git ls-tree -r` call)."""
    out = _git(repo, "ls-tree", "-r", "-z", commit)
    blobs = {}
    for entry in out.split("\0"):
        if entry:
            meta, _, path = entry.partition("\t")
            blobs[path] = meta.split()[2]
    return blobs


def _default_ref(repo):
    """The default branch as a ref name; ValueError when it cannot be told (design section 1)."""
    name = relay_git.default_branch(repo)
    if name is None:
        raise ValueError("cannot tell the default branch: set project.default_branch in .claude/kit.toml")
    for ref in ("refs/heads/" + name, "refs/remotes/origin/" + name):
        if relay_git.git(repo, "rev-parse", "--verify", "-q", ref)[0] == 0:
            return ref
    raise ValueError(f"the default branch {name} has no commit in {repo}")


ARCHIVE = ("openspec/changes/archive/**", "openspec/specs/**")    # where archiving an OpenSpec change writes
_ARCHIVE = [_regex(p) for p in ARCHIVE]
_MOVED_OUT = _regex("openspec/changes/*/**")                      # the change's own folder: only its deletion is archiving


def _archiving(repo, until, path):
    """True when `path` is touched only the way archiving a change touches it: written under the archive or the main
    specs, or deleted from the change's folder (the move into the archive). An edit of the change's folder is not."""
    if any(rx.match(path) for rx in _ARCHIVE):
        return True
    return bool(_MOVED_OUT.match(path)) and relay_git.git(repo, "cat-file", "-e", f"{until}:{path}")[0] != 0


def changed(repo, since, until="HEAD", own=False, archive=False):
    """Files changed from `since` to `until` in `repo` that are not inert. A rename or copy counts as a delete plus an
    add (--no-renames), so a code file moved into an inert folder is still listed; -z keeps odd names unquoted.

    own=True (design section 7.2) leaves out a file the branch never touched at either end: with B_S the default
    branch's merge-base with `since` and B_U its merge-base with `until`, a file is left out exactly when it is equal
    at `since` and B_S and equal at `until` and B_U (missing on both sides counts as equal). So files that arrived
    from the default branch are not the branch's own; a checked fix that was reverted still is.

    archive=True also leaves out the paths a commit that only archives an OpenSpec change touches (see `_archiving`);
    code or any other file in the same span stays listed."""
    out = _git(repo, "diff", "--name-only", "--no-renames", "-z", f"{since}..{until}")
    paths = [line for line in out.split("\0") if line and not matches(line)]
    if archive:
        paths = [p for p in paths if not _archiving(repo, until, p)]
    if not own or not paths:
        return paths
    default = _default_ref(repo)
    base_since = _git(repo, "merge-base", since, default).strip()
    base_until = _git(repo, "merge-base", until, default).strip()
    trees = {c: _blobs(repo, c) for c in {since, until, base_since, base_until}}
    return [p for p in paths
            if trees[since].get(p) != trees[base_since].get(p) or trees[until].get(p) != trees[base_until].get(p)]
