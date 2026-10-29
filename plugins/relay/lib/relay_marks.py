"""Check marks and gate logs in `.relay/checks/` (docs/plans/review-gate.md sections 4.1 and 6).

This module is the only code that reads or writes the folder `.relay/checks/` on a task branch:

    <commit>.json         the check mark: {"schema": 2, "commit", "verdict": {"open", "queued"}, "check", "gate", "time"};
                          check names the record below; the counts are the record's own (relay_verdict.open_of)
    <commit>.check.json   the check record (relay_verdict.py): the item's problem, the reviews' findings, one verdict for
                          each, the gate; the only stored form of a check, read by `relay_verdict.load_record`
    <commit>.gate.log     the gate log: first line `head <commit>`, last line `exit <n>`

Writes are git commits made with `add` then `commit --no-verify --only -- <files>`: other staged changes stay
staged and out of the commit, the project's commit hooks do not run, and the message carries no tool credit.
A locked index is retried `MARK_COMMIT_RETRIES` times, one second apart, then `MarkError("index busy")`.
"""

import datetime as dt
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


def write_check_mark(worktree, data):
    """Commit the mark and the stored record of the loaded check record `data` (its `head`, `gate`, findings) in `worktree`;
    returns the counts {"open", "queued"}. No rule of its own: the counts are the record's (`open_of`, `queued_of`). When the
    branch already holds the same mark of that head (the command made it, then the hook came) nothing is committed. Both the
    command `relay check record check` and the SubagentStop hook call this, so a mark does not depend on which one runs."""
    head = data["head"]
    gate = data["gate"] if data["gate"] and os.path.isfile(os.path.join(worktree, FOLDER, data["gate"])) else None
    counts = {"open": relay_verdict.open_of(data), "queued": relay_verdict.queued_of(data)}
    name = "%s.check.json" % head
    stored = json.dumps(relay_verdict.stored_record(data), indent=2, sort_keys=True) + "\n"
    have = get(worktree, "HEAD", head)
    if have is not None and have["verdict"] == counts and have["check"] == name and have.get("gate") == gate and _show(worktree, "HEAD", name) == stored:
        return counts
    mark = {
        "schema": MARK_SCHEMA,
        "commit": head,
        "verdict": counts,
        "check": name,
        "gate": gate,
        "time": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    put(worktree, head, mark, {name: stored})
    return counts


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


MARK_SCHEMA = 2


def _valid(mark, commit):
    verdict = mark.get("verdict") if isinstance(mark, dict) else None
    return (
        isinstance(verdict, dict)
        and mark.get("schema") == MARK_SCHEMA
        and mark.get("commit") == commit
        and isinstance(mark.get("check"), str)
        and isinstance(verdict.get("open"), int) and not isinstance(verdict.get("open"), bool)
        and isinstance(verdict.get("queued"), int) and not isinstance(verdict.get("queued"), bool)
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
    return found + rebased(repo, ref, {c for c, _ in found})


def rebased(repo, ref, have):
    """[(twin, mark)] for each mark the branch at `ref` holds of a commit a rebase replaced with one of the same patch
    (`relay_inert.twin`): the check and the review still count, only a new gate is needed. A mark whose commit is in the
    history, is on the default branch already, or has no twin is left out, and so is a twin that has a mark of its own."""
    import relay_inert
    name = relay_git.default_branch(repo)
    if name is None:
        return []
    merged = set(_names(repo, "refs/heads/" + name))
    found = []
    for commit in sorted(have):
        if "%s.json" % commit in merged:
            continue
        try:
            moved = relay_inert.twin(repo, commit, ref)
        except ValueError:
            continue
        mark = get(repo, ref, commit)
        if moved is not None and moved != commit and moved not in have and mark is not None:
            found.append((moved, mark))
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


def check_data(repo, ref, name):
    """The stored check record `name` at `ref`; None when it is not stored; MarkError when it is not valid (a schema-1 check
    is refused with a line that names `relay check migrate`)."""
    text = _show(repo, ref, name)
    if text is None:
        return None
    try:
        return relay_verdict.load_record(text, "the check data %s" % name, stored=True)
    except relay_verdict.VerdictError as exc:
        raise MarkError(str(exc))


def stored_texts(repo, sha):
    """The JSON text stored for commit `sha` (an abbreviation will do), found at HEAD or any local branch: its check record.
    MarkError when there is none (never a guess)."""
    rc, full = relay_git.git(repo, "rev-parse", "--verify", "-q", "%s^{commit}" % sha)
    if rc != 0 or not is_sha(full):
        raise MarkError("no commit %s" % sha)
    rc, out = relay_git.git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/")
    for ref in ["HEAD"] + (out.splitlines() if rc == 0 else []):
        text = _show(repo, ref, "%s.check.json" % full)
        if text is not None:
            return [text]
    raise MarkError("no stored check for %s" % full)


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
    import relay_inert
    try:
        default = relay_inert._default_ref(repo)
        ab = relay_inert.absorbed(repo, ref)
    except ValueError as exc:
        raise MarkError(str(exc))
    lines = ["gate %s: exit %d" % gate if gate else "gate: none yet"]
    fork = relay_git.git(repo, "merge-base", default, ref)[1].strip()
    if not relay_inert.changed(repo, fork, ref):    # the merge hook's step 3: nothing but inert files, no mark is asked for
        return lines + ["mark: none needed, no code changed", "outside: none to count"]
    if ab and not relay_inert.changed(repo, fork, ref, own=True, archive=True, absorbed=ab):
        return lines + ["mark: none needed, the ready changes it holds are checked", "outside: none to count"]    # the merge hook skips the mark step
    # the merge hook's own view (step_mark): only marks on the branch itself count, not ones that landed on the default branch,
    # and not a rider's mark inside an absorbed branch; read just those commits' marks, not every stored one
    candidates = relay_git.git(repo, "rev-list", "--topo-order", ref, "^" + default)[1].split()
    stored = {c: m for c in candidates for m in [get(repo, ref, c)] if m is not None}
    named = {n[:-5] for n in _names(repo, ref) if n.endswith(".json") and is_sha(n[:-5])}    # names only: no mark of another branch is read
    for moved, kept in rebased(repo, ref, named - set(candidates)):    # a rebase that left the patch alone
        stored.setdefault(moved, kept)
    own = relay_inert.own_marks(repo, ref, default, ab, stored)
    mark = (own[0], stored[own[0]]) if own else None
    if mark is None:
        return lines + ["mark: no mark yet", "outside: unknown (no mark yet)"]
    commit, data = mark
    verdict = data["verdict"]
    lines.append("mark %s: open %d, queued %d" % (commit, verdict["open"], verdict["queued"]))
    try:
        record = check_data(repo, ref, data["check"])
        lines.append("outside: %s" % ("check not stored" if record is None else "%d in the check" % relay_verdict.outside_of(record)))
    except MarkError as exc:
        lines.append("outside: unknown (%s)" % exc)
    try:
        later = relay_inert.own_since_mark(repo, commit, ref, ab)
    except ValueError as exc:
        lines.append("files changed after the mark: unknown (%s)" % exc)
        later = []
    if later:
        lines.append("%d non-inert file%s changed after the mark: %s; run relay gate, then delegate:checker" % (
            len(later), "" if len(later) == 1 else "s", ", ".join(later[:5]) + (" and %d more" % (len(later) - 5) if len(later) > 5 else "")))
    if gate:    # the merge hook's step_gate: the gate must cover the code at the head
        try:
            ungated = relay_inert.changed(repo, gate[0], ref, archive=True)
        except ValueError:
            ungated = []
        if ungated:
            lines.append("code changed since the gate: %s; run relay gate" % (", ".join(ungated[:5]) + (" and %d more" % (len(ungated) - 5) if len(ungated) > 5 else "")))
    return lines
