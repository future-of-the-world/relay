"""The inert list: files whose content never decides a check or a merge (state files, not code).

The list is fixed here, not a setting. A pattern matches a path relative to the repository root, with "/" as the
separator: "*" matches inside one path part (any characters but "/"), "**" matches any number of whole parts (zero
or more). `changed()` lists what changed since a commit and is not inert: it is the file list the checker works from.
With `own=True` it leaves out the files that only the default branch changed (design section 7.2).
"""

from __future__ import annotations

import re
import subprocess

import relay_git

INERT = (
    "docs/handover.md",
    ".relay/queue/**",
    ".relay/checks/**",
    ".relay/changes/**",
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


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TREES: dict[tuple[str, str], dict[str, str]] = {}      # (repo, commit sha) -> {path: blob id}: a commit's tree never changes, so one read serves a whole judge


def _blobs(repo, commit):
    """{path: blob id} of every file at `commit` (one `git ls-tree -r` call; kept per commit sha)."""
    key = (repo, commit)
    if _SHA.match(commit) and key in _TREES:
        return _TREES[key]
    out = _git(repo, "ls-tree", "-r", "-z", commit)
    blobs = {}
    for entry in out.split("\0"):
        if entry:
            meta, _, path = entry.partition("\t")
            blobs[path] = meta.split()[2]
    if _SHA.match(commit):
        _TREES[key] = blobs
    return blobs


def _sha(repo, rev):
    return _git(repo, "rev-parse", "--verify", rev + "^{commit}").strip()


def _is_ancestor(repo, older, newer):
    return relay_git.git(repo, "merge-base", "--is-ancestor", older, newer)[0] == 0


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


_ADDED_ARCHIVE = _regex("openspec/changes/archive/**")


def _archiving(paths, blobs_since, blobs_until):
    """The paths of `paths` that only archiving a change touches, or [] when the span does not archive: it must add a
    folder under openspec/changes/archive/ (the move). Then a path written under the archive or the main specs, or
    deleted from a change's folder, is part of it; an edit of the change's folder is not."""
    if not any(_ADDED_ARCHIVE.match(p) and p in blobs_until and p not in blobs_since for p in paths):
        return []
    return [p for p in paths
            if any(rx.match(p) for rx in _ARCHIVE) or (_MOVED_OUT.match(p) and p not in blobs_until)]


def _covered(repo, paths, until, default, absorbed):
    """The paths of `paths` that an absorbed branch covers (design docs/plans/review-gate.md section 7.7). With T the tree at
    `until`, M the default branch's head, X an absorbed branch and base(X) its merge-base with the default branch, a path p is
    covered by X when X changed it (X[p] != base(X)[p]), T[p] == X[p] (what lands is X's version), M[p] == base(X)[p] (the
    default branch did not change it since X left) and every other absorbed branch Y either did not change it or holds the same
    content. Blob comparisons only: a covered file is one that exactly one side changed and whose version is what lands."""
    tops, head = _blobs(repo, until), _blobs(repo, _sha(repo, default))
    sides = {}
    for branch, tip in absorbed.items():
        base = _git(repo, "merge-base", tip, default).strip()
        sides[branch] = (_blobs(repo, tip), _blobs(repo, base))
    covered = set()
    for p in paths:
        for branch, (tree, base) in sides.items():
            if tree.get(p) == base.get(p) or tops.get(p) != tree.get(p) or head.get(p) != base.get(p):
                continue
            if all(other.get(p) == obase.get(p) or other.get(p) == tree.get(p)
                   for name, (other, obase) in sides.items() if name != branch):
                covered.add(p)
                break
    return covered


def _patch_id(repo: str, base: str, commit: str) -> str | None:
    """The patch id (whitespace kept: re-indenting is a change) of the change from `base` to `commit`, leaving out the check files (`.relay/checks`); None when the
    change is empty or git cannot tell. The id is the same for a change a rebase moved onto a new base."""
    diff = subprocess.run(["git", "-C", repo, "diff", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color", "--binary", base, commit, "--", ".", ":(exclude).relay/checks"],
                          capture_output=True)
    if diff.returncode != 0 or not diff.stdout:
        return None
    done = subprocess.run(["git", "-C", repo, "patch-id", "--verbatim"], input=diff.stdout, capture_output=True)
    fields = done.stdout.split()
    return fields[0].decode() if done.returncode == 0 and fields else None


def twin(repo: str, old: str, ref: str) -> str | None:
    """The commit of the branch at `ref` that a rebase made of `old` (a commit no longer in `ref`'s history): the newest commit
    of the branch whose change from its merge-base with the default branch has the same patch id as `old`'s (the check files
    left out). None when `old` is not a commit here, is already in the history (then it is itself the answer, `old`), or no
    commit of the branch has that patch: a rebase that changed the patch has no twin."""
    if relay_git.git(repo, "cat-file", "-e", old + "^{commit}")[0] != 0:
        return None
    if _is_ancestor(repo, old, ref):
        return old
    default = _default_ref(repo)
    rc, base = relay_git.git(repo, "merge-base", old, default)
    wanted = _patch_id(repo, base, old) if rc == 0 else None
    if wanted is None:
        return None
    for commit in _git(repo, "rev-list", "--topo-order", ref, "^" + default).split():
        rc, fork = relay_git.git(repo, "merge-base", commit, default)
        if rc == 0 and _patch_id(repo, fork, commit) == wanted:
            # the default branch changed a file the branch also changed: the combined file was never checked (as by a merge)
            return None if changed(repo, old, commit, own=True) else commit
    return None


def own_marks(repo, tip, default, inner, stored):
    """The commits of the branch at `tip` that carry a mark in `stored`, newest first (topological), left out those inside a
    branch of `inner` ({branch: tip}): a rider's check judged its own side only, so it never vouches for the combined tree."""
    inside = set()
    for held in inner.values():
        inside.update(_git(repo, "rev-list", held, "^" + default).split())
    return [c for c in _git(repo, "rev-list", "--topo-order", tip, "^" + default).split() if c in stored and c not in inside]


def _passes(repo, tip, default, inner):
    """Whether the branch at `tip` would pass the merge hook's mark step on its own: nothing of its own is left once the files
    of `inner` are covered, or its newest mark (none inside `inner`) whose own files are unchanged up to the tip says `open 0`."""
    import relay_marks
    if inner:
        fork = _git(repo, "merge-base", default, tip).strip()
        if not changed(repo, fork, tip, own=True, archive=True, absorbed=inner):
            return True
    stored = dict(relay_marks.marks(repo, tip))
    for commit in own_marks(repo, tip, default, inner, stored):
        if not changed(repo, commit, tip, own=True, archive=True, absorbed=inner):
            return stored[commit]["verdict"]["open"] == 0
    return False


def absorbed(repo, ref):
    """{branch: tip} of the branches absorbed by `ref` (design section 7.7): a local `wt/*` branch (not `wt/queue-*`, not at the
    tip of `ref`) whose tip is an ancestor of `ref` and not of the default branch, and that would pass the mark step on its own.
    Computed once, inner branches first (an ancestor is judged before the branch that holds it, with the already accepted
    branches inside it), so each branch is judged once; computed from git each time, never stored."""
    default = _default_ref(repo)
    top = _sha(repo, ref)
    found = {}
    for line in _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/wt/").splitlines():
        name, _, tip = line.partition(" ")
        branch = name[len("refs/heads/"):]
        if branch.startswith("wt/queue-") or tip == top or not _is_ancestor(repo, tip, top) or _is_ancestor(repo, tip, default):
            continue
        found[branch] = tip
    size = {b: int(_git(repo, "rev-list", "--count", tip)) for b, tip in found.items()}    # an ancestor has strictly fewer commits
    accepted = {}
    for branch in sorted(found, key=lambda b: (size[b], b)):
        inner = {b: t for b, t in accepted.items() if _is_ancestor(repo, t, found[branch])}
        if _passes(repo, found[branch], default, inner):
            accepted[branch] = found[branch]
    return accepted


def dropped(repo, merge, names):
    """The files of `names` that the second parent of `merge` changed (since its merge-base with the first parent) and that the
    merge left exactly as the first parent had them: the other side's change thrown away, by a hand-resolved merge."""
    merge = _sha(repo, merge)
    first, second = _sha(repo, merge + "^1"), _sha(repo, merge + "^2")
    rc, fork = relay_git.git(repo, "merge-base", first, second)
    if rc != 0:
        return []
    t_fork, t_first, t_second = _blobs(repo, fork), _blobs(repo, first), _blobs(repo, second)
    t_merge = _blobs(repo, merge)
    return sorted(n for n in names if t_second.get(n) != t_fork.get(n) and t_merge.get(n) == t_first.get(n) != t_second.get(n))


def changed(repo, since, until="HEAD", own=False, archive=False, absorbed=None):
    """Files changed from `since` to `until` in `repo` that are not inert. A rename or copy counts as a delete plus an
    add (--no-renames), so a code file moved into an inert folder is still listed; -z keeps odd names unquoted.

    own=True (design section 7.2) leaves out a file the branch never touched at either end: with B_S the default
    branch's merge-base with `since` and B_U its merge-base with `until`, a file is left out exactly when it is equal
    at `since` and B_S and equal at `until` and B_U (missing on both sides counts as equal). So files that arrived
    from the default branch are not the branch's own; a checked fix that was reverted still is.

    archive=True also leaves out the paths a commit that only archives an OpenSpec change touches (see `_archiving`);
    code or any other file in the same span stays listed; a span that adds nothing under the archive is not archiving.

    absorbed (with own=True): the {branch: tip} that `absorbed()` returned for `until`; a file one of them covers is left
    out as well (`_covered`)."""
    since, until = _sha(repo, since), _sha(repo, until)
    out = _git(repo, "diff", "--name-only", "--no-renames", "-z", f"{since}..{until}")
    paths = [line for line in out.split("\0") if line and not matches(line)]
    if archive:
        gone = set(_archiving(paths, _blobs(repo, since), _blobs(repo, until)))
        paths = [p for p in paths if p not in gone]
    if not own or not paths:
        return paths
    default = _default_ref(repo)
    base_since = _git(repo, "merge-base", since, default).strip()
    base_until = _git(repo, "merge-base", until, default).strip()
    trees = {c: _blobs(repo, c) for c in {since, until, base_since, base_until}}
    paths = [p for p in paths
             if trees[since].get(p) != trees[base_since].get(p) or trees[until].get(p) != trees[base_until].get(p)]
    if absorbed and paths:
        gone = _covered(repo, paths, until, default, absorbed)
        paths = [p for p in paths if p not in gone]
    return paths


def resolved(repo: str, merge: str) -> list[str]:
    """The non-inert files a merge commit's author decided by hand (design relay-land 4.2): the paths git's own merge of the
    two parents reports as conflicted (`git merge-tree`, which also names a modify/delete conflict kept as one side) plus the
    paths where the merge commit's tree differs from the tree git's own merge wrote (a clean merge with a hand edit). A clean
    merge git did by itself, also of a file both sides changed, lists nothing."""
    merge = _sha(repo, merge)
    first, second = _sha(repo, merge + "^1"), _sha(repo, merge + "^2")
    rc, out = relay_git.git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", first, second, raw=True)
    if rc not in (0, 1):
        raise ValueError(f"git merge-tree failed in {repo} for {merge}")
    parts = [p for p in out.split("\0") if p]
    if not parts:
        raise ValueError(f"git merge-tree wrote no tree in {repo} for {merge}")
    tree, conflicted = parts[0], parts[1:] if rc == 1 else []
    diff = _git(repo, "diff", "--name-only", "--no-renames", "-z", tree, merge + "^{tree}")
    names = set(conflicted) | {p for p in diff.split("\0") if p}
    return sorted(p for p in names if not matches(p))


def own_since_mark(repo: str, mark: str, ref: str, absorbed: dict[str, str] | None = None) -> list[str]:
    """The one rule for "the branch's own files since a check" (design relay-land 4.2): `changed(..., own=True, archive=True)`
    from `mark` to `ref`, minus each file that no non-merge commit of the branch touched after the mark and that no merge after
    the mark resolved by hand. So a clean take of the default branch never asks for a new check, also for a file both sides
    changed; a commit of the branch after the mark, or a hand-resolved take, does."""
    own = changed(repo, mark, ref, own=True, archive=True, absorbed=absorbed)
    if not own:
        return []
    default = _default_ref(repo)
    touched: set[str] = set()
    log = _git(repo, "log", "--no-merges", "--no-renames", "--name-only", "--format=", "-z", f"{_sha(repo, mark)}..{_sha(repo, ref)}", "^" + default)
    touched.update(p for p in log.split("\0") if p.strip("\n"))
    touched = {p.strip("\n") for p in touched}
    by_hand: set[str] = set()
    for merge in _git(repo, "rev-list", "--merges", f"{_sha(repo, mark)}..{_sha(repo, ref)}", "^" + default).split():       # only this branch's own takes
        by_hand.update(resolved(repo, merge))
    return [p for p in own if p in touched or p in by_hand]
