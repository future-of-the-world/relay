"""Check marks and gate logs in `.relay/checks/` (docs/plans/review-gate.md sections 4.1 and 6).

This module is the only code that reads or writes the folder `.relay/checks/` on a task branch:

    <commit>.json         the check mark: {"schema": 1, "commit", "verdict": {"open", "queued", "reviewed"},
                          "review", "check", "gate", "time"}; review and check name the two files below
    <commit>.check.json   the checker's data (relay_verdict.py; the only stored form of the check)
    <reviewed>.review.json  the review set: the review data of each findings file (the only stored form of the review)
    <commit>.gate.log     the gate log: first line `head <commit>`, last line `exit <n>`

Writes are git commits made with `add` then `commit --no-verify --only -- <files>`: other staged changes stay
staged and out of the commit, the project's commit hooks do not run, and the message carries no tool credit.
A locked index is retried `MARK_COMMIT_RETRIES` times, one second apart, then `MarkError("index busy")`.
"""

import json
import os
import re
import subprocess
import time

import relay_git
import relay_verdict

FOLDER = ".relay/checks"
SHA = re.compile(r"^[0-9a-f]{40}\Z")
# Retries of a commit that meets a locked index, one second apart (bound 1-8: at 8 the waits take 8 s, the most the
# check hook's 10 s timeout leaves room for).
MARK_COMMIT_RETRIES = 3
# `relay check show` waits at most this long for the worktree's index.lock to go (bound 0-30: at 0 it does not wait,
# at 30 a stuck lock holds the front 30 s).
CHECK_SHOW_WAIT_S = 10
POLL_S = 0.2


class MarkError(Exception):
    """A check file could not be written or committed; the text says why, in one line."""


def is_sha(value):
    return isinstance(value, str) and bool(SHA.match(value))


def _first_line(text):
    lines = text.strip().splitlines()
    return lines[0] if lines else "git failed"


def _git(worktree, *args):
    rc, out = relay_git.git(worktree, *args, raw=True)
    return rc, out


def _git_err(worktree, *args):
    """(exit code, stderr's first line) of a git write; stderr is what tells a locked index."""
    try:
        done = subprocess.run(["git", "-C", worktree, *args], capture_output=True, text=True, timeout=relay_git.TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return done.returncode, _first_line(done.stderr or done.stdout)


def _commit(worktree, relpaths, message, sleep=time.sleep, remove=False):
    """add (or rm) then commit exactly `relpaths`, retrying a locked index; MarkError when it cannot."""
    attempts = MARK_COMMIT_RETRIES + 1
    for attempt in range(attempts):
        if remove:
            rc, err = _git_err(worktree, "rm", "-q", "-f", "--", *relpaths)
        else:
            rc, err = _git_err(worktree, "add", "--", *relpaths)
        if rc == 0:
            rc, err = _git_err(worktree, "commit", "-q", "--no-verify", "--only", "-m", message, "--", *relpaths)
        if rc == 0:
            return
        if "index.lock" not in err:
            raise MarkError("git could not commit: %s" % err)
        if attempt < attempts - 1:
            sleep(1)
    raise MarkError("index busy")


def commit_file(worktree, path, message, sleep=time.sleep):
    """Commit one file (an absolute path inside the worktree) alone, e.g. a gate log."""
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(worktree))
    _commit(worktree, [rel], message, sleep)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def put(worktree, commit, mark, files, sleep=time.sleep):
    """Write `<commit>.json` from `mark` and every `files` entry (name -> text) into `.relay/checks/`; commit them in one
    commit "relay: check of <commit>". An unchanged file is not a change; when nothing differs no commit is made."""
    if not is_sha(commit):
        raise MarkError("the mark's commit is not a full sha: %s" % commit)
    folder = os.path.join(worktree, FOLDER)
    names = {"%s.json" % commit: json.dumps(mark, indent=2, sort_keys=True) + "\n"}
    for name, text in files.items():
        if os.path.basename(name) != name or not name:
            raise MarkError("a check file name has no folder part: %s" % name)
        names[name] = text
    for name, text in names.items():
        _write(os.path.join(folder, name), text)
    rel = [FOLDER + "/" + name for name in names]
    _commit(worktree, rel, "relay: check of %s" % commit, sleep)


def drop(worktree, commit, sleep=time.sleep):
    """Remove the mark and the check data of `commit` (tracked files only) in one commit; True when it removed any."""
    tracked = []
    for name in ("%s.json" % commit, "%s.check.json" % commit):
        rel = FOLDER + "/" + name
        if _git(worktree, "ls-files", "--error-unmatch", "--", rel)[0] == 0:
            tracked.append(rel)
    if not tracked:
        return False
    _commit(worktree, tracked, "relay: no check of %s" % commit, sleep, remove=True)
    return True


def _show(repo, ref, name):
    rc, out = relay_git.git(repo, "show", "%s:%s/%s" % (ref, FOLDER, name), raw=True)
    return out if rc == 0 else None


def _names(repo, ref):
    rc, out = relay_git.git(repo, "ls-tree", "--name-only", ref, FOLDER + "/")
    if rc != 0:
        return []
    return sorted(os.path.basename(line) for line in out.splitlines())


def _valid(mark, commit):
    verdict = mark.get("verdict") if isinstance(mark, dict) else None
    return (
        isinstance(verdict, dict)
        and mark.get("commit") == commit
        and isinstance(verdict.get("open"), int) and not isinstance(verdict.get("open"), bool)
        and isinstance(verdict.get("queued"), int) and not isinstance(verdict.get("queued"), bool)
        and is_sha(verdict.get("reviewed"))
    )


def get(repo, ref, commit):
    """The mark of `commit` stored at `ref`, or None when there is none or it is not a well-formed mark."""
    text = _show(repo, ref, "%s.json" % commit)
    if text is None:
        return None
    try:
        mark = json.loads(text)
    except ValueError:
        return None
    return mark if _valid(mark, commit) else None


def marks(repo, ref):
    """[(commit, mark)] for every well-formed mark at `ref`, sorted by commit."""
    found = []
    for name in _names(repo, ref):
        if name.endswith(".json") and is_sha(name[:-5]):
            mark = get(repo, ref, name[:-5])
            if mark is not None:
                found.append((name[:-5], mark))
    return found


def gate_logs(repo, ref):
    """[(commit, exit)] for every gate log at `ref` whose first line is `head <commit>` and whose last line is
    `exit <n>`, sorted by commit; a log that is not in that form is not a gate result and is left out."""
    found = []
    for name in _names(repo, ref):
        if not (name.endswith(".gate.log") and is_sha(name[:-9])):
            continue
        text = _show(repo, ref, name)
        lines = text.splitlines() if text else []
        if not lines or lines[0].strip() != "head " + name[:-9]:
            continue
        match = re.match(r"^exit (\d+)$", lines[-1].strip())
        if match:
            found.append((name[:-9], int(match.group(1))))
    return found


def newest(repo, ref, items):
    """The item of `items` ((commit, value) pairs) whose commit is the newest ancestor of `ref` (git's own order from
    `ref` back), or None."""
    by_commit = dict(items)
    rc, out = relay_git.git(repo, "rev-list", ref)
    if rc != 0:
        return None
    for sha in out.splitlines():
        if sha in by_commit:
            return sha, by_commit[sha]
    return None


def review_set(repo, ref, name):
    """The stored review set `name` at `ref` (relay_verdict.load_set); None when the file is not stored; MarkError when it
    is stored but not valid (never a guess)."""
    text = _show(repo, ref, name)
    if text is None:
        return None
    try:
        return relay_verdict.load_set(text, "the review data %s" % name)
    except relay_verdict.VerdictError as exc:
        raise MarkError(str(exc))


def check_data(repo, ref, name):
    """The stored check data `name` at `ref`; None when it is not stored; MarkError when it is not valid."""
    text = _show(repo, ref, name)
    if text is None:
        return None
    try:
        return relay_verdict.load_check(text, "the check data %s" % name, stored=True)
    except relay_verdict.VerdictError as exc:
        raise MarkError(str(exc))


def review_outside(repo, ref, name):
    """Count of findings of kind `outside` in the stored review set `name`; None when it is not stored; MarkError when it
    is not valid."""
    data = review_set(repo, ref, name)
    return None if data is None else relay_verdict.outside_count(data)


def stored_texts(repo, sha):
    """The JSON texts stored for commit `sha` (an abbreviation will do), found at HEAD or any local branch: the check of
    that commit and the review set it covers; or, when no check is stored, the review set of that reviewed commit.
    MarkError when there is none (never a guess)."""
    rc, full = relay_git.git(repo, "rev-parse", "--verify", "-q", "%s^{commit}" % sha)
    if rc != 0 or not is_sha(full):
        raise MarkError("no commit %s" % sha)
    rc, out = relay_git.git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/")
    refs = ["HEAD"] + (out.splitlines() if rc == 0 else [])
    for name in ("%s.check.json" % full, "%s.review.json" % full):
        for ref in refs:
            text = _show(repo, ref, name)
            if text is None:
                continue
            if not name.endswith(".check.json"):
                return [text]
            texts = [text]
            try:
                review = json.loads(text).get("review")
            except ValueError:
                review = None
            if isinstance(review, list) and review and isinstance(review[0], str):
                more = _show(repo, ref, os.path.basename(review[0]))
                if more is not None:
                    texts.append(more)
            return texts
    raise MarkError("no stored check or review for %s" % full)


def lock_path(worktree):
    """The worktree's index.lock, absolute."""
    rc, out = relay_git.git(worktree, "rev-parse", "--path-format=absolute", "--git-path", "index.lock")
    return out if rc == 0 and out else None


def wait_for_lock(worktree, limit=None, sleep=time.sleep):
    """Wait while the worktree's index.lock exists, at most `limit` seconds (default CHECK_SHOW_WAIT_S), counted in
    polls so a driven `sleep` is the only clock. Returns True when the lock is gone, False when it outlasted the limit."""
    limit = CHECK_SHOW_WAIT_S if limit is None else limit
    path = lock_path(worktree)
    if path is None:
        return True
    polls = int(limit / POLL_S)
    for _ in range(polls):
        if not os.path.exists(path):
            return True
        sleep(POLL_S)
    return not os.path.exists(path)


def show(repo, branch, sleep=time.sleep):
    """The three lines of `relay check show`: gate, mark, outside items, read at `branch`'s head (after waiting for a
    mark commit in flight in the branch's worktree)."""
    tree = next((w for w in relay_git.worktrees(repo) if w["branch"] == branch), None)
    if tree is not None:
        wait_for_lock(tree["path"], sleep=sleep)
    ref = "refs/heads/" + branch
    if relay_git.git(repo, "rev-parse", "--verify", "-q", ref)[0] != 0:
        raise MarkError("no branch %s" % branch)
    gate = newest(repo, ref, gate_logs(repo, ref))
    mark = newest(repo, ref, marks(repo, ref))
    lines = ["gate %s: exit %d" % gate if gate else "gate: none yet"]
    if mark is None:
        return lines + ["mark: no mark yet", "outside: unknown (no mark yet)"]
    commit, data = mark
    verdict = data["verdict"]
    lines.append("mark %s: open %d, queued %d, reviewed %s" % (commit, verdict["open"], verdict["queued"], verdict["reviewed"]))
    try:
        outside = review_outside(repo, ref, str(data.get("review") or "%s.review.json" % verdict["reviewed"]))
        lines.append("outside: %s" % ("review not stored" if outside is None else "%d in the review" % outside))
    except MarkError as exc:
        lines.append("outside: unknown (%s)" % exc)
    return lines
