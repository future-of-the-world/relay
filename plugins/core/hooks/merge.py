#!/usr/bin/env python3
"""The merge hook (design docs/plans/review-gate.md, section 11).

    merge.py     the hook JSON on stdin; `hook_event_name` picks the work:
                 PreToolUse = the merge gate (part B5; nothing yet),
                 PostToolUse = the cleanup after `git merge --ff-only wt/<name>`.

Only in a repository whose default branch has `.relay/`; elsewhere it exits 0 and prints nothing.
Cleanup checks git itself, never the tool's exit status, and never forces: no `worktree remove
--force`, no `branch -D`.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import kit_guard  # noqa: E402
import relay_git  # noqa: E402

NAMES = 5          # files or paths named in a message, then "and N more"
LOG_RANGE = 50     # newest entries of the default branch's reflog searched for its state before a merge


def named(items):
    shown = ", ".join(items[:NAMES])
    return shown + (" and %d more" % (len(items) - NAMES) if len(items) > NAMES else "")


def under(child, parent):
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def has_own_commits(main, branch):
    """The branch's reflog holds an entry other than its creation, a fast-forward or a reset."""
    rc, out = relay_git.git(main, "reflog", "show", "--format=%gs", "refs/heads/" + branch)
    if rc != 0:
        return False
    for subject in out.splitlines():
        if subject.startswith("branch: Created from") or subject.endswith("Fast-forward") or subject.startswith("reset: moving to"):
            continue
        return True
    return False


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
        out.append("Run relay sync once from the main checkout.")
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
        line = clean(main, default, branch, hook)
        if line:
            lines.append(line)
    if lines:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join(lines)}}))
    return 0


def main():
    try:
        hook = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(hook, dict):
        return 0
    event = hook.get("hook_event_name")
    if event == "PostToolUse" and hook.get("tool_name") == "Bash":
        return post(hook)
    return 0     # PreToolUse: the merge gate is part B5


if __name__ == "__main__":
    sys.exit(main())
