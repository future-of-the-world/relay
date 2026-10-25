#!/usr/bin/env python3
"""The merge hook (design docs/plans/review-gate.md, section 11).

    merge.py     the hook JSON on stdin; `hook_event_name` picks the work:
                 PreToolUse = the merge gate (section 7: refuses the merge, exit 2, one line),
                 PostToolUse = the cleanup after `git merge --ff-only wt/<name>`.
    merge.py sweep   SessionStart (section 11.3): removes the merged worktrees no session needs.
    merge.py end     SessionEnd: unlocks this session's worktrees and removes the merged ones.
    merge.py remove <path> <branch>   the detached child both start for guards 6-7.

Only in a repository whose default branch has `.relay/`; elsewhere it exits 0 and prints nothing.
Cleanup checks git itself, never the tool's exit status, and never forces: no `worktree remove
--force`, no `branch -D`.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import kit_guard  # noqa: E402
import relay_git  # noqa: E402
import relay_inert  # noqa: E402
import relay_marks  # noqa: E402
import relay_queue  # noqa: E402

NAMES = 5          # files or paths named in a message, then "and N more"
LOG_RANGE = 50     # newest entries of the default branch's reflog searched for its state before a merge


def named(items):
    shown = ", ".join(items[:NAMES])
    return shown + (" and %d more" % (len(items) - NAMES) if len(items) > NAMES else "")


def under(child, parent):
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def has_own_commits(main, branch):
    return relay_git.has_own_commits(main, branch)


def merged_files(main, default, branch):
    """Files the branch brought: from the newest state of the default branch that lacked the branch, to the branch."""
    rc, out = relay_git.git(main, "reflog", "show", "--format=%H", "-n", str(LOG_RANGE), "refs/heads/" + default)
    if rc != 0:
        return []
    for sha in out.splitlines():
        if relay_git.git(main, "merge-base", "--is-ancestor", "refs/heads/" + branch, sha)[0] != 0:
            rc, names = relay_git.git(main, "diff", "--name-only", "--no-renames", sha, "refs/heads/" + branch)
            return names.splitlines() if rc == 0 else []
    return []


def notices(main, files):
    out = []
    if any((f.startswith("plugins/") and ("/agents/" in f or "/skills/" in f)) or f.startswith("roles/") for f in files):
        out.append("Agent and skill texts changed: open sessions keep the old texts until restarted or /reload-plugins.")
    if os.path.isfile(os.path.join(main, "bin", "relay")) and any(f.startswith(("rules/", "roles/")) for f in files):
        out.append("Run relay sync from the main checkout once the wave's paid run is green (it waits for it).")
    return out


def rel(main, path):
    return os.path.relpath(path, main)


def clean(main, default, branch, hook):
    """Remove the merged branch's worktree and branch where every guard passes; return the one-line message."""
    if relay_git.git(main, "merge-base", "--is-ancestor", "refs/heads/" + branch, "refs/heads/" + default)[0] != 0:
        return None                                                                   # 2: not merged
    if not has_own_commits(main, branch):
        return "kept %s: it has no commits of its own (a fresh worktree)" % branch    # 3
    files = merged_files(main, default, branch)
    tree = next((w for w in relay_git.worktrees(main) if w["branch"] == branch), None)  # 4
    gone, extra = "", ""
    if tree is not None:
        path, name = tree["path"], rel(main, tree["path"])
        sid = hook.get("session_id") or "unknown"
        here = [os.path.realpath(p) for p in (hook.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")) if p]
        if tree["locked"] is not None:                                                # locked, by anyone
            return "kept %s: locked%s" % (name, (" (" + tree["locked"] + ")") if tree["locked"] else "")
        if any(under(p, path) for p in here):                                         # 5
            rc, out = relay_git.git(main, "worktree", "lock", "--reason", "session " + sid, path)
            if rc != 0:
                return "kept %s: this session runs in it (it could not be locked)" % name
            return "kept %s: this session runs in it; locked until this session ends" % name
        rc, status = relay_git.git(path, "status", "--ignored", "--porcelain", raw=True)        # 6
        if rc != 0:
            return "kept %s: its state cannot be read" % name
        ignored = [l[3:] for l in status.splitlines() if l.startswith("!! ")]
        changed = [l[3:] for l in status.splitlines() if not l.startswith("!! ")]
        if changed:
            return "kept %s: it holds changes not in the branch (%s); branch %s kept" % (name, named(changed), branch)
        rc, _ = relay_git.git(main, "worktree", "remove", path)
        if rc != 0:
            return "kept %s: git refused to remove it; branch %s kept" % (name, branch)
        gone = name
        if ignored:
            extra = ", with %d ignored path%s gone: %s" % (len(ignored), "" if len(ignored) == 1 else "s", named(ignored))
    rc, _ = relay_git.git(main, "branch", "-d", branch)                               # 7
    if rc != 0:
        return "%sbranch kept: not merged into its upstream" % ("Removed %s, " % gone if gone else "")
    what = ("%s and branch %s" % (gone, branch)) if gone else "branch %s" % branch
    return " ".join(["Removed %s (merged)%s." % (what, extra)] + notices(main, files))


# ---- section 7: the merge gate (PreToolUse) ----

QUEUE_DIR = ".relay/queue/"
DONE_DIR = QUEUE_DIR + "done/"


class Refused(Exception):
    """The merge is refused; the text is the one line the hook prints."""


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def commit_list(main, args):
    rc, out = relay_git.git(main, *args)
    if rc != 0:
        raise ValueError("git %s failed" % " ".join(args))
    return out.splitlines()


def blob(main, ref, path):
    rc, out = relay_git.git(main, "show", "%s:%s" % (ref, path), raw=True)
    return out if rc == 0 else None


def closing_ref(main, default, ab, path):
    """The commit of the innermost absorbed branch whose range default...branch adds `path`, or None: the ref where a rider's own
    check is judged, the way merging that rider alone would."""
    adding = []
    for name, tip in ab.items():
        added = relay_git.git(main, "diff", "--name-only", "--no-renames", "--diff-filter=A", "-z", "refs/heads/%s...%s" % (default, tip))[1]
        if path in added.split("\0"):
            adding.append((int(relay_git.git(main, "rev-list", "--count", tip)[1]), name, tip))
    return min(adding)[2] if adding else None


def record_rules(main, ref):
    """The module that judges the records of `ref`: that tree's own lib/relay_queue.py, loaded from the commit (git show into a
    temporary file, so the tree is never checked out), else the hook's own copy where the tree has none (a project that is not relay).
    Loading beats a subprocess here: `parse` is the one call, it takes text and returns a dict, and the module's imports (relay_git,
    relay_verdict) are already on the hook's path."""
    source = blob(main, ref, "lib/relay_queue.py")
    if source is None:
        return relay_queue
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "relay_queue_incoming.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        spec = importlib.util.spec_from_file_location("relay_queue_incoming", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def step_queue(main, default, branch, ab=None):
    """7.1 step 2 (m-1): every queue item file the range adds or changes is well formed (an old-shape one is refused naming
    `relay queue migrate`); every queue file at the branch tip, whether the range touched it or not (one that came in by taking the
    default branch included), is well formed too; every `fix` item it moves into done/ (not dropped) passes `relay_queue.close_refusal`: its test exists and the branch's newest check
    with no own file changed since is of that item with Q1 MET. For a train (`ab`, the absorbed branches) the test is judged at the
    branch, the tree that lands, and the check at the absorbed branch whose range adds the item's done/ file."""
    ab = ab or {}
    changed_files = relay_git.git(main, "diff", "--name-only", "--no-renames", "--diff-filter=AM", "-z",
                                  "refs/heads/%s...refs/heads/%s" % (default, branch))[1]
    added = set(relay_git.git(main, "diff", "--name-only", "--no-renames", "--diff-filter=A", "-z",
                              "refs/heads/%s...refs/heads/%s" % (default, branch))[1].split("\0"))
    tip = relay_git.git(main, "ls-tree", "-r", "--name-only", "-z", "refs/heads/" + branch, "--", QUEUE_DIR)[1]
    files = set(changed_files.split("\0")) | set(tip.split("\0"))
    rules = record_rules(main, "refs/heads/" + branch)
    for path in sorted(p for p in files if p.endswith(".json") and os.path.dirname(p) in (QUEUE_DIR.rstrip("/"), DONE_DIR.rstrip("/"))):
        slug = os.path.basename(path)[:-5]
        in_done = path.startswith(DONE_DIR)
        meta = rules.parse(slug, blob(main, "refs/heads/" + branch, path) or "", "done" if in_done else "open")
        if meta["problems"]:
            raise Refused("queue item %s is malformed (%s); fix it before the merge" % (slug, "; ".join(meta["problems"])))
        if not in_done or path not in added or meta["kind"] != "fix" or meta["state"] == "dropped":
            continue
        closer = closing_ref(main, default, ab, path) or "refs/heads/" + branch
        reason = relay_queue.test_refusal(main, "refs/heads/" + branch, meta["test"]) or relay_queue.check_refusal(main, closer, slug)
        if reason:
            raise Refused("queue item %s is closed without a test or a check: %s" % (slug, reason))


def _dropped_after(main, default, commit, ref, ab):
    """The own files that a merge of the default branch (or of an absorbed branch) after `commit` threw the other side's change
    away from: a mark made before it did not see that."""
    fork = relay_git.git(main, "merge-base", "refs/heads/" + default, ref)[1]
    out = relay_git.git(main, "rev-list", "--merges", "%s..%s" % (commit, ref))[1].split()
    lost = set()
    own = None
    for merge in out:
        if relay_git.git(main, "rev-parse", "--verify", "-q", merge + "^2")[0] != 0:
            continue
        second = relay_git.git(main, "rev-parse", merge + "^2")[1]
        if relay_git.git(main, "merge-base", "--is-ancestor", second, "refs/heads/" + default)[0] != 0 and second not in ab.values():
            continue
        if own is None:
            own = relay_inert.changed(main, fork, ref, own=True, archive=True, absorbed=ab)
        lost.update(relay_inert.dropped(main, merge, own))
    return sorted(lost)


def step_mark(main, default, branch, ab=None):
    """7.1 steps 4-5: the newest mark on the branch (not on the default branch) whose own files are all unchanged since. `ab` is
    the branches the branch absorbs (`relay_inert.absorbed`): the files they cover are not the branch's own, and a branch whose
    own files are all covered (a train of ready changes with no shared file) needs no mark."""
    ab = ab or {}
    ref, base = "refs/heads/" + branch, "refs/heads/" + default
    left = []
    if ab:
        fork = relay_git.git(main, "merge-base", base, ref)[1]
        left = relay_inert.changed(main, fork, ref, own=True, archive=True, absorbed=ab)
        if not left:
            return
    stored = dict(relay_marks.marks(main, ref))
    order = relay_inert.own_marks(main, ref, base, ab, stored)        # a rider's own check never vouches for the combined tree
    if not order and left:
        raise Refused("no check of %s covers %s, which the ready changes it holds changed together or which it rewrote; "
                      "run relay gate, then delegate:checker" % (branch, named(left)))
    if not order:
        raise Refused("no check mark for %s (run relay gate, then delegate:checker on its head)" % branch)
    newest_list = None
    for commit in order:
        own = relay_inert.changed(main, commit, ref, own=True, archive=True, absorbed=ab)
        if not own:
            lost = _dropped_after(main, default, commit, ref, ab)
            if lost:
                raise Refused("after the check of %s, a merge into %s dropped the change a merged branch made to %s; "
                              "run relay gate, then delegate:checker" % (commit, branch, named(lost)))
            mark = stored[commit]
            if mark["verdict"]["open"] != 0:
                raise Refused("the check of %s left %s open, wrong inside the change or waiting for the owner's answer (report: .relay/checks/%s.check.json; relay check show prints it); "
                              "fix them or keep the owner's answer with relay check owner, run relay gate, then delegate:checker" % (commit, plural(mark["verdict"]["open"], "thing"), commit))
            return commit
        if newest_list is None:
            newest_list = (commit, own)
    commit, own = newest_list
    raise Refused("after the check of %s, %s changed %s, which %s not inert; run relay gate, then delegate:checker" % (
        commit, branch, named(own), "is" if len(own) == 1 else "are"))


def step_gate(main, branch, where):
    """7.1 step 6: the newest gate log for code that has not changed since (every non-inert file, no --own) must be green."""
    ref = "refs/heads/" + branch
    logs = dict(relay_marks.gate_logs(main, ref))
    order = [c for c in commit_list(main, ["rev-list", "--topo-order", ref]) if c in logs]
    reason = "no gate has run on it yet"
    for commit in order:                                        # newest first: the newest gate on unchanged code decides
        since = relay_inert.changed(main, commit, ref, archive=True)
        if logs[commit] != 0:
            if reason.startswith("no gate"):
                reason = "last gate %s: exit %d" % (commit, logs[commit])
            if not since:
                break                                           # a red gate on this code is never skipped for an older green one
            continue
        if not since:
            return
        if reason.startswith("no gate"):                       # a red newer log is the better answer
            reason = "code changed since: %s" % named(since)
        break
    raise Refused("no green gate for the code at %s's head: %s; run relay gate in %s" % (branch, reason, where))


def judge(main, default, branch):
    """The merge gate for one merge into the default branch; raises Refused with the line to print."""
    ref, base = "refs/heads/" + branch, "refs/heads/" + default
    if relay_git.git(main, "rev-parse", "--verify", "-q", ref)[0] != 0:
        return                                                   # no such branch: git itself will say so
    tree = next((w for w in relay_git.worktrees(main) if w["branch"] == branch), None)
    where = rel(main, tree["path"]) if tree else "its worktree"
    if relay_git.git(main, "merge-base", "--is-ancestor", base, ref)[0] != 0:                    # 1
        behind = len(commit_list(main, ["rev-list", ref + ".." + base]))
        raise Refused("%s is behind %s by %s; take %s first: git -C %s merge --no-edit %s (then relay gate if code came in)" % (
            branch, default, plural(behind, "commit"), default, where, default))
    ab = relay_inert.absorbed(main, ref)                                                        # the ready changes it holds
    step_queue(main, default, branch, ab)                                                       # 2
    rc, merge_base = relay_git.git(main, "merge-base", base, ref)
    if rc != 0:
        raise ValueError("no common commit with %s" % default)
    if not relay_inert.changed(main, merge_base, ref):                                          # 3
        return
    step_mark(main, default, branch, ab)                                                       # 4, 5
    step_gate(main, branch, where)                                                              # 6


def pre(hook):
    command = (hook.get("tool_input") or {}).get("command")
    cwd = hook.get("cwd") or os.getcwd()
    if not isinstance(command, str) or "merge" not in command or not os.path.isdir(cwd):
        return 0
    for directory, branch in kit_guard.allowed_merges(command, cwd):
        main = relay_git.main_checkout(directory) if os.path.isdir(directory) else None
        if main is None:
            continue
        default = relay_git.default_branch(main)
        if default is None or not relay_git.has_relay(main):
            continue
        top = relay_git.git(directory, "rev-parse", "--show-toplevel")[1]
        if not top or os.path.realpath(top) != main or relay_git.current_branch(directory) != default:
            continue                                             # not a merge into the default branch
        try:
            judge(main, default, branch)
        except Refused as exc:
            print("merge refused: %s" % exc, file=sys.stderr)
            return 2
        except Exception as exc:                                 # fail closed: a gate that cannot judge refuses (exit 1 would let the merge run)
            print("merge refused: the gate for %s could not be judged: %s" % (branch, exc), file=sys.stderr)
            return 2
    return 0


def riders(main, branch):
    """The other task branches whose tip is inside `branch` (now on the default branch with it: the ready changes a train held,
    or the branch a stacked one was made from). `clean` and its guards decide each removal; a branch with no commits of its
    own is left out, so an idle one is not named."""
    rc, out = relay_git.git(main, "for-each-ref", "--format=%(refname:short)", "refs/heads/wt/")
    return [b for b in (out.splitlines() if rc == 0 else [])
            if b != branch and not b.startswith("wt/queue-") and has_own_commits(main, b)
            and relay_git.git(main, "merge-base", "--is-ancestor", "refs/heads/" + b, "refs/heads/" + branch)[0] == 0]


def post(hook):
    command = (hook.get("tool_input") or {}).get("command")
    cwd = hook.get("cwd") or os.getcwd()
    if not isinstance(command, str) or "merge" not in command or not os.path.isdir(cwd):
        return 0
    lines = []
    for directory, branch in kit_guard.allowed_merges(command, cwd):
        main = relay_git.main_checkout(directory) if os.path.isdir(directory) else None   # "?" and gone folders are skipped
        if main is None:
            continue
        default = relay_git.default_branch(main)
        if default is None or not relay_git.has_relay(main):
            continue
        # 1: the merge ran in the main checkout, on the default branch
        top = relay_git.git(directory, "rev-parse", "--show-toplevel")[1]
        if not top or os.path.realpath(top) != main or relay_git.current_branch(directory) != default:
            continue
        for name in [branch] + riders(main, branch):
            line = clean(main, default, name, hook)
            if line:
                lines.append(line)
    if lines:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join(lines)}}))
    return 0


# ---- section 11.3: session start sweep, session end, and the detached removal ----

LOG_NAME = "relay-cleanup.log"


def log_file(main):
    rc, common = relay_git.git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.join(common, LOG_NAME) if rc == 0 and common else None


def log_line(main, text):
    path = log_file(main)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def last_line(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    line = lines[-1] if lines else "git gave no reason"
    return line[len("fatal: "):] if line.startswith("fatal: ") else line


def take_failures(main):
    """Failure lines the detached removals logged; the log is cleared (renamed first, so a late append is not lost)."""
    path = log_file(main)
    if not path or not os.path.isfile(path):
        return []
    mine = path + ".read"
    try:
        os.replace(path, mine)
        with open(mine, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        os.remove(mine)
    except OSError:
        return []
    return [l for l in lines if l.startswith("could not remove")]


def remove_child(path, branch):
    """Guards 6-7 for one merged worktree, run detached: `git worktree remove` (never --force), then `git branch -d`."""
    main = relay_git.main_checkout(path)
    if main is None:
        return 1
    name = rel(main, path)
    done = subprocess.run(["git", "-C", main, "worktree", "remove", path], capture_output=True, text=True)
    if done.returncode != 0:
        log_line(main, "could not remove %s: %s" % (name, last_line(done.stderr)))
        return 1
    done = subprocess.run(["git", "-C", main, "branch", "-d", branch], capture_output=True, text=True)
    if done.returncode != 0:
        log_line(main, "could not remove branch %s: %s" % (branch, last_line(done.stderr)))
        return 1
    log_line(main, "removed %s and branch %s" % (name, branch))
    return 0


def spawn_remove(path, branch):
    """Start the removal in a new process session, so the hook's own timeout cannot kill it halfway."""
    subprocess.Popen([sys.executable, "-I", os.path.realpath(__file__), "remove", path, branch],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def task_worktrees(main):
    """Worktrees of task branches (`wt/<name>`, not queue branches); never the main checkout."""
    return [w for w in relay_git.worktrees(main)
            if w["path"] != main and w["branch"] and w["branch"].startswith("wt/") and not w["branch"].startswith("wt/queue-")]


def is_clean(path):
    rc, status = relay_git.git(path, "status", "--porcelain", raw=True)
    return rc == 0 and not [l for l in status.splitlines() if not l.startswith("!! ")]


def removable(main, default, tree):
    """Guards 2, 3 and 6 (changes): merged, with commits of its own, nothing changed or untracked."""
    branch = tree["branch"]
    return (relay_git.git(main, "merge-base", "--is-ancestor", "refs/heads/" + branch, "refs/heads/" + default)[0] == 0
            and has_own_commits(main, branch) and is_clean(tree["path"]))


def repo_of(hook):
    """(main checkout, default branch) of the session's folder, or None where the hard rules do not act."""
    for candidate in (hook.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")):
        if candidate and os.path.isdir(candidate):
            main = relay_git.main_checkout(candidate)
            default = relay_git.default_branch(main) if main else None
            if main and default and relay_git.has_relay(main):
                return main, default
            return None
    return None


def say(event, lines):
    if lines:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n".join(lines)}}))


def sweep(hook):
    found = repo_of(hook)
    if found is None:
        return 0
    main, default = found
    sid = hook.get("session_id") or "unknown"
    here = [os.path.realpath(p) for p in (hook.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")) if p]
    lines = take_failures(main)
    going = []
    for tree in task_worktrees(main):
        path = tree["path"]
        mine = tree["locked"] == "session " + sid
        if tree["locked"] is not None and not mine:
            continue                                  # another session's lock, or a person's: never removed
        if any(under(p, path) for p in here):
            if tree["locked"] is None:                # the session runs in it: lock it so no other session's merge or sweep removes it
                relay_git.git(main, "worktree", "lock", "--reason", "session " + sid, path)
            continue                                  # (a lock of its own stays too; SessionEnd unlocks it)
        if not removable(main, default, tree):
            continue
        if mine and relay_git.git(main, "worktree", "unlock", path)[0] != 0:
            continue
        going.append((path, tree["branch"]))
    for path, branch in going:
        spawn_remove(path, branch)
    if going:
        lines.append("Removing %d merged worktree%s: %s" % (
            len(going), "" if len(going) == 1 else "s", ", ".join("%s (%s)" % (rel(main, p), b) for p, b in going)))
    say("SessionStart", lines)
    return 0


def end(hook):
    found = repo_of(hook)
    sid = hook.get("session_id")
    if found is None or not sid:
        return 0
    main, default = found
    for tree in task_worktrees(main):
        if tree["locked"] != "session " + sid:
            continue
        if relay_git.git(main, "worktree", "unlock", tree["path"])[0] != 0:
            continue
        if removable(main, default, tree):
            spawn_remove(tree["path"], tree["branch"])
    return 0


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "remove":
        return remove_child(sys.argv[2], sys.argv[3])
    try:
        hook = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(hook, dict):
        return 0
    event = hook.get("hook_event_name")
    if len(sys.argv) == 2 and sys.argv[1] == "sweep":
        return sweep(hook)
    if len(sys.argv) == 2 and sys.argv[1] == "end":
        return end(hook)
    if event == "PostToolUse" and hook.get("tool_name") == "Bash":
        return post(hook)
    if event == "PreToolUse" and hook.get("tool_name") == "Bash":
        return pre(hook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
