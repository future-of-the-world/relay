"""Gate logs read back: which log stands for a commit (reuse of a green or finished red gate, the newest remote log, design 5.2).
Split out of relay_gate.py (module size limit); relay_gate re-exports every name here."""

from __future__ import annotations

import os
import shlex
from typing import TYPE_CHECKING, Optional, Sequence

import relay_git
import relay_inert
import relay_marks

if TYPE_CHECKING:
    from relay_gate import Remote


LIMIT_EXIT = 124        # bin/ci's exit when the quick gate stopped at its time limit (lib/relay_ci.py LIMIT_EXIT): not a test failure
STOPPED_LINE = "gate: stopped at the "   # the line bin/ci prints for it
FAILED_LINES = 8        # lines of the first failing step shown on the third output line
STOPPED = "gate: stopped"      # the start of every line the sweep and the reclaim add to the log (finished_red skips them)
MAC_SUFFIX = ".gate.log"
REMOTE_SUFFIX = ".remote.gate.log"      # a gate that ran on the VPS (docs/plans/vps-build-gates.md 5.1): no merge-path reader opens this name
TOOLCHAIN = ("container/Containerfile", "deps.toml", "install.sh")      # a branch that changes one gates on this Mac (design 5.4)

def log_sha_host(log: str) -> tuple[str, Optional[str]]:
    """(commit, host) of a gate log path: the host is read from the `host` line of a remote log, None for a Mac log."""
    name = os.path.basename(log)
    if not name.endswith(REMOTE_SUFFIX):
        return name[:-len(MAC_SUFFIX)], None
    host = None
    try:
        with open(log, encoding="utf-8", errors="replace") as handle:
            for line in handle.read().splitlines()[:6]:
                if line.startswith("host "):
                    host = line.split()[1] if len(line.split()) > 1 else None
                    break
    except OSError:
        pass
    return name[:-len(REMOTE_SUFFIX)], host or "the remote host"


def first_failure(output: str) -> list[str]:
    """The first failing step's lines (the step line and its indented findings), else the last five lines. The line of a gate
    stopped at its time limit counts as a failing line in its place in the output, so a step that FAILED before the stop comes first."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if "FAILED" in line or line.startswith(STOPPED_LINE):
            block = [line]
            for more in lines[i + 1:i + FAILED_LINES]:
                if not more.startswith((" ", "\t")):
                    break
                block.append(more)
            return block
    return lines[-5:]


def _log_lines(worktree: str, commit: str, suffix: str) -> Optional[list[str]]:
    try:
        with open(os.path.join(worktree, relay_marks.FOLDER, commit + suffix), encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return None


def _exit_code(lines: Sequence[str]) -> Optional[int]:
    last = lines[-1].split() if lines else []
    return int(last[1]) if len(last) == 2 and last[0] == "exit" and last[1].isdigit() else None


def reusable(worktree: str, head: str, command: Sequence[str], host: str = "mac") -> Optional[str]:
    """The path of a green gate log for the same command on a commit at or before `head` with only inert changes since, else None.

    Walks back from `head` along the branch's own line (first parents: a take of the default branch has the branch first, so
    master's newer commits are not walked) and stops at the first commit after which a non-inert file changed. A log counts only when its
    first line is `head <that commit>`, its `cmd` line is the command about to run and its last line is `exit 0`.
    `host` is the deciding host (design 5.2): "mac" reads Mac logs only; "vps" lets the newest remote log of the stretch decide
    (a red one means None, whatever Mac logs lie in the stretch) and reads Mac logs only when the stretch holds no remote log."""
    wanted = "cmd %s" % " ".join(shlex.quote(c) for c in command)
    rc, listing = relay_git.git(worktree, "rev-list", "--first-parent", head)
    if rc != 0:
        return None
    stretch = []
    for commit in listing.split():
        if relay_inert.changed(worktree, commit, head):
            break
        stretch.append(commit)
    for suffix in ((REMOTE_SUFFIX, MAC_SUFFIX) if host == "vps" else (MAC_SUFFIX,)):
        for commit in stretch:
            lines = _log_lines(worktree, commit, suffix)
            if lines is None or len(lines) < 3 or lines[0] != "head %s" % commit or lines[1] != wanted or _exit_code(lines) is None:
                continue
            if lines[-1] == "exit 0":
                return os.path.join(worktree, relay_marks.FOLDER, commit + suffix)
            if suffix == REMOTE_SUFFIX:
                return None      # the newest remote log is red (or stopped): it decides
    return None


def finished_red(worktree: str, head: str, command: Sequence[str], stopped: bool = False, host: str = "mac") -> Optional[tuple[int, str, list[str]]]:
    """(exit code, log path, failing lines) of a finished red gate log for the same command on a commit at or before
    `head`, when only relay's own record commits (files under .relay/checks/) lie between, else None.

    This is stricter than `reusable`: a red result must not stand for code that changed, so any file outside the
    checks folder (inert or not) ends the walk. A log counts only when its first line is `head <that commit>`, its
    `cmd` line is the command about to run and its last line is `exit <n>` with n not 0.
    `stopped=True` asks the other way round: the log of an EARLIER commit (not `head` itself) that ends `exit 124`, the gate
    stopped at its time limit on this same code (Mac logs only).
    `host="vps"`: the newest remote log of the stretch decides (a remote log that is not a reportable red means None), and Mac logs
    are read only when the stretch holds no remote log."""
    wanted = "cmd %s" % " ".join(shlex.quote(c) for c in command)
    rc, listing = relay_git.git(worktree, "rev-list", head)
    if rc != 0:
        return None
    stretch = []
    for commit in listing.split():
        rc, names = relay_git.git(worktree, "diff", "--name-only", "--no-renames", "%s..%s" % (commit, head))
        if rc != 0 or any(not name.startswith(relay_marks.FOLDER + "/") for name in names.splitlines()):
            break
        stretch.append(commit)
    for suffix in ((REMOTE_SUFFIX, MAC_SUFFIX) if host == "vps" and not stopped else (MAC_SUFFIX,)):
        for commit in stretch:
            if stopped and commit == head:
                continue
            lines = _log_lines(worktree, commit, suffix)
            if lines is None or len(lines) < 3 or lines[0] != "head %s" % commit or lines[1] != wanted:
                continue
            code = _exit_code(lines)
            if code is None:
                continue
            # 127 (could not start), >= 128 (killed) and 124 (stopped at the time limit) came from outside the commit: not reused, the next gate runs
            if (code == LIMIT_EXIT) if stopped else (0 < code < 127 and code != LIMIT_EXIT):
                return code, os.path.join(worktree, relay_marks.FOLDER, commit + suffix), first_failure("\n".join(l for l in lines[3:-1] if not l.startswith(STOPPED)))
            if suffix == REMOTE_SUFFIX:
                return None      # the newest remote log is not a reportable red: it decides
    return None


def _last_mac_red(worktree: str) -> bool:
    """Whether the branch's newest Mac gate log on its own line since the default branch is red (design 5.2: the gate that failed
    is the gate that confirms the fix)."""
    main = relay_git.main_checkout(worktree)
    base = relay_git.default_branch(main) if main else None
    args = ["rev-list", "--first-parent", "HEAD"] + (["^" + base] if base else [])
    rc, listing = relay_git.git(worktree, *args)
    if rc != 0:
        return False
    for commit in listing.split():
        lines = _log_lines(worktree, commit, MAC_SUFFIX)
        code = _exit_code(lines) if lines and lines[0] == "head %s" % commit else None
        if code is not None and (code == 0 or 0 < code < 127 and code != LIMIT_EXIT):      # a stop (124), a failed start (127) or a kill (>= 128) is no verdict on the code: walk on
            return code != 0
    return False


def _toolchain_changed(worktree: str) -> list[str]:
    """The toolchain files the branch itself changed since it forked from the default branch (three-dot diff; design 5.4: no branch recipe runs with network on the VPS)."""
    main = relay_git.main_checkout(worktree)
    base = relay_git.default_branch(main) if main else None
    if not base:
        return []
    rc, out = relay_git.git(worktree, "diff", "--name-only", "--no-renames", base + "...HEAD", "--", *TOOLCHAIN)
    return out.splitlines() if rc == 0 else []


def deciding_host(worktree: str, remote: Optional[Remote], quick: bool) -> tuple[str, str]:
    """("vps", "") or ("mac", line): the host whose result a build-time gate takes (design 5.2), in the table's order. `line` is the
    sentence to print (without `gate: ` and the closing "this gate runs on this Mac") when the Mac decides for a reason the owner
    should see; "" when the Mac decides silently. A landing passes no `remote`; a paid or argument gate is not `quick`."""
    if remote is None or not quick:
        return "mac", ""
    if not os.path.isfile(os.path.join(worktree, "container", "Containerfile")):
        return "mac", ""
    if _last_mac_red(worktree):
        return "mac", "the last gate of this branch on this Mac is red"
    if remote.default_red and not remote.holds_fix:
        return "mac", "the default branch is red on %s %s" % (remote.host, remote.default_red)
    changed = _toolchain_changed(worktree)
    if changed:
        return "mac", "this branch changes relay's toolchain (%s)" % ", ".join(changed)
    return "vps", ""
