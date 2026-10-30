"""`relay gate`: run the project's free gate on a clean task-branch commit and store the result as a gate log
(docs/plans/review-gate.md section 5).

The log `.relay/checks/<G>.gate.log` starts with `head <G>` (the commit the gate ran on, full sha), then `cmd <command>`,
`wait <seconds>` (the wait for a slot), the gate's output, and ends with `exit <n>`. The merge hook trusts it because this code, not a model, wrote it. The log
is committed alone, with the same commit path as check marks (`relay_marks.commit_file`).

A gate that has to run first takes the worktree's own lock (`<git dir>/relay-gate.lock`, waiting without a time limit, unless the gate that holds it was killed: then its command is stopped, see `reclaim`; the
lock file is passed to the gate command, so the lock lasts until the command's last process ends, even when `relay gate`
is killed). After the command it checks that the tested tree is still the gated commit. Then it takes one of a few slots shared by the whole machine (OS file locks under `$RELAY_HOME/gate-slots/`,
so a killed gate frees its slot by itself). The log's third line, `wait <seconds>`, is the time spent waiting for a slot and for the gate's test tokens.

Test tokens (lib/relay_tokens.py): after its slot, the gate takes its share of the machine-wide pool of test tokens
(`$RELAY_HOME/test-tokens/`, 4 by default, the file `per-gate` sets it) before its command starts, so the wait is outside the
command's own time limit. Only a worktree that has relay's test runners (a lib/relay_tokens.py) takes tokens: the command gets `RELAY_TEST_TOKENS` (what relay's own test runners read, none else); a project's own gate
takes its slot only and gets no variable: what its bin/ci checks and how parallel it runs stays the project's choice.
"""

from __future__ import annotations

import fcntl
import os
import shlex
import signal
import subprocess
import sys
import time
import re
from typing import IO, Any, Callable, Mapping, Optional, Sequence

import relay_config
import relay_git
import relay_inert
import relay_license
import relay_marks
import relay_tokens
import relay_procs
from relay_temp import prefixed_folders, temp_roots, under
import relay_toml

DEFAULT_CI = "bin/ci"
LIMIT_EXIT = 124        # bin/ci's exit when the quick gate stopped at its time limit (lib/relay_ci.py LIMIT_EXIT): not a test failure
STOPPED_LINE = "gate: stopped at the "   # the line bin/ci prints for it
FAILED_LINES = 8        # lines of the first failing step shown on the third output line
CORES_PER_SLOT = relay_tokens.CORES_PER_SLOT      # default slots = cores // CORES_PER_SLOT, at least 1 (measurement in lib/relay_tokens.py)
SLOT_POLL = 0.2         # seconds between looks at the slots (and at the worktree lock) while all are busy
ORPHAN_AGE = 600.0      # seconds: a parent-1 leftover running from a relay test folder that still exists is stopped after this age (the longest test limit is 200 s)
STOPPED = "gate: stopped"      # the start of every line the sweep and the reclaim add to the log (finished_red skips them)
LEFTOVER = STOPPED + " a leftover test process"      # the sweep's line: "<LEFTOVER> <pid> (<command>): <why>"
KILLED = STOPPED + " the command of a gate that was killed"      # the reclaim's line: "<KILLED> (group <group>, <command>): <why>"


class GateRefused(Exception):
    """The gate was not started; the text says why in one line."""


def quick_binding(worktree):
    """The command of the optional binding `gate.ci_quick` (the free mode of the gate), None when kit.toml names none."""
    try:
        with open(os.path.join(worktree, ".claude", "kit.toml"), "rb") as handle:
            data = relay_toml.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise GateRefused("cannot read .claude/kit.toml: %s" % exc)
    value = (data.get("gate") or {}).get("ci_quick")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GateRefused("gate.ci_quick in .claude/kit.toml is not a command")
    return value


def binding(worktree):
    """The command of the binding `gate.ci` in the worktree's `.claude/kit.toml`, `bin/ci` when it names none."""
    try:
        with open(os.path.join(worktree, ".claude", "kit.toml"), "rb") as handle:
            data = relay_toml.load(handle)
    except FileNotFoundError:
        return DEFAULT_CI
    except (OSError, ValueError) as exc:
        raise GateRefused("cannot read .claude/kit.toml: %s" % exc)
    value = (data.get("gate") or {}).get("ci")
    if value is None:
        return DEFAULT_CI
    if not isinstance(value, str) or not value.strip():
        raise GateRefused("gate.ci in .claude/kit.toml is not a command")
    return value


def check_ready(worktree):
    """Refuse (GateRefused) unless `worktree` is a clean task-branch checkout of a project with `.relay/`; returns HEAD."""
    main = relay_git.main_checkout(worktree)
    if main is None:
        raise GateRefused("%s is not in a git repository" % worktree)
    if relay_git.default_branch(main) is None or not relay_git.has_relay(main):
        raise GateRefused("the default branch has no .relay/ folder: run relay setup here first")
    rc, top = relay_git.git(worktree, "rev-parse", "--show-toplevel")
    if rc != 0 or os.path.realpath(top) == main:
        raise GateRefused("the gate runs on a task branch, not in the main checkout")
    rc, status = relay_git.git(worktree, "status", "--porcelain", raw=True)
    if rc != 0:
        raise GateRefused("git cannot read the state of %s" % worktree)
    dirty = [line[3:] for line in status.splitlines()]
    if dirty:
        raise GateRefused("commit first: the gate must run on a commit (%s%s)" % (
            ", ".join(dirty[:5]), " and %d more" % (len(dirty) - 5) if len(dirty) > 5 else ""))
    rc, head = relay_git.git(worktree, "rev-parse", "HEAD")
    if rc != 0 or not relay_marks.is_sha(head):
        raise GateRefused("%s has no commit to run the gate on" % worktree)
    return head


def default_slots(cores: int | None = None) -> int:
    """Gates that may run at once by default: the machine's cores divided by CORES_PER_SLOT, at least 1."""
    return max(1, (cores if cores is not None else os.cpu_count() or 1) // CORES_PER_SLOT)


def slot_count(home: str, cores: int | None = None) -> int:
    """How many gates may run at once on this machine: the number in the file `<home>/gate-slots/count` (one setting every gate
    reads from the same place, so gates cannot disagree), else default_slots(cores)."""
    path = os.path.join(home, "gate-slots", "count")
    try:
        with open(path) as handle:
            value = handle.read().strip()
    except FileNotFoundError:
        return default_slots(cores)
    except OSError as exc:
        raise GateRefused("cannot read the gate slot setting %s: %s" % (path, exc))
    if not value:
        return default_slots(cores)
    try:
        count = int(value)
    except ValueError:
        count = 0
    if count < 1:
        raise GateRefused("the gate slot setting %s must hold a whole number of 1 or more, not %r" % (path, value))
    return count


def take_slot(count, folder, notify=None):
    """Lock one of `count` slot files in `folder`, waiting for a free one without a time limit; returns (file object, seconds waited).

    Closing the file object (or the process dying, however it dies) frees the slot. `notify` is called once, before the wait, when all are busy."""
    os.makedirs(folder, exist_ok=True)
    handles = [open(os.path.join(folder, "slot-%d" % i), "a") for i in range(count)]
    started = time.monotonic()
    told = False
    try:
        while True:
            for handle in handles:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    continue
                for other in handles:
                    if other is not handle:
                        other.close()
                return handle, time.monotonic() - started
            if not told and notify is not None:
                notify("gate: waiting for a free gate slot (all %d busy; the limit stops gates slowing each other, the file $RELAY_HOME/gate-slots/count sets it)" % count)
            told = True
            time.sleep(SLOT_POLL)
    except BaseException:
        for handle in handles:
            handle.close()
        raise


def alive(pid, group=False):
    """Whether the process (or, with `group`, any process of the group) `pid` exists."""
    try:
        (os.killpg if group else os.kill)(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:      # exists, not ours to signal
        return True
    return True


def holder_words(text, path):
    """Name who holds the worktree lock from the lock file's text: "<relay pid>" or "<relay pid> <command group>"."""
    numbers = [int(word) for word in text.split() if word.isdigit()]
    if not numbers or numbers[0] <= 0:
        return "pid unknown"
    if alive(numbers[0]):
        return "pid %d" % numbers[0]
    if len(numbers) > 1 and numbers[1] > 0 and alive(numbers[1], group=True):
        return "pid %d, the gate command, whose gate process has ended" % numbers[1]
    return "pid %d has ended; a process outside the gate's process group still holds %s" % (numbers[0], path)


def reclaim(path: str, text: str, record: Callable[[str], None]) -> bool:
    """The lock file `path` is held and its text (`<gate pid> <command group>`) names a gate process that has ended: the gate command's
    processes that kept the file are then the only holders, their result can never be committed, and they run outside the slot limit.
    Stop that group (confirmed with one `lsof -t`: some holder is a member of the group), say so through `record`; True when stopped."""
    numbers = [int(word) for word in text.split() if word.isdigit()]
    if len(numbers) < 2 or numbers[0] <= 0 or numbers[1] <= 1 or alive(numbers[0]) or numbers[1] == os.getpgrp():
        return False
    group = numbers[1]
    holders = relay_procs.holders_of(path)
    if holders is None:      # lsof could not run: nobody can be named, so nothing is stopped; say why the wait goes on
        record("gate: cannot tell who holds %s: lsof could not run (install lsof; `relay doctor` checks it); stop group %d by hand if its command hangs" % (path, group))
        return False
    if not holders:
        return False
    try:
        members = {p.pid: p for p in relay_procs.read_procs() if p.pgid == group}
    except (OSError, subprocess.SubprocessError):
        return False
    held = [pid for pid in holders if pid in members]
    if not held:
        return False
    record("%s (group %d, %s): its gate process ended, so its result can never be committed" % (KILLED, group, members[held[0]].command[:120]))
    relay_procs.stop([(group, True)])
    return True


def take_worktree_lock(path: str, notify: Optional[Callable[[str], None]] = None, record: Optional[Callable[[str], None]] = None) -> IO[str]:
    """Lock the file `path` exclusively, waiting without a time limit; returns the open file, which holds the lock.

    The holder writes its pid into the file; `notify` is called once with the waiting line (naming that pid) when the lock is
    held by another process. The lock lasts as long as any process keeps the file open (closing it, or the process dying, frees it).
    The wait polls every SLOT_POLL and reads the holder's line each round: when the holder's gate process has ended and its command
    still holds the file, `reclaim` stops that command (once per dead gate pid) and the lock is taken; `record` gets that line."""
    handle = open(path, "a+")
    told = False
    tried = set()
    def line(text: str) -> None:
        if notify is not None:
            notify(text)
        if record is not None:
            record(text)
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                pass
            handle.seek(0)
            text = handle.read()
            words = [int(word) for word in text.split() if word.isdigit()]
            if words and words[0] not in tried and not alive(words[0]):
                tried.add(words[0])      # one lsof per dead gate pid
                if reclaim(path, text, line):
                    continue
            if not told and notify is not None:
                notify("gate: waiting for the gate already running in this worktree (%s)" % holder_words(text, path))
            told = True
            time.sleep(SLOT_POLL)
        handle.seek(0)
        handle.truncate()
        handle.write("%d\n" % os.getpid())
        handle.flush()
    except BaseException:
        handle.close()
        raise
    return handle


RELAY_COMMAND = re.compile(r"(^|[ /])relay( -\S+)* (gate|land)( |$)")


def sweep(roots: Sequence[str], read_procs: Callable[[], list[relay_procs.Proc]], read_cwds: Callable[[Sequence[int]], Optional[dict]],
          own: Sequence[int], _again: bool = True) -> list[str]:
    """Stop the leftovers of relay's own tests: processes whose parent is gone (parent 1) that run from a relay test folder under `roots`
    (their command names a path `<root>/../<prefix>..`, or they are a `relay gate`/`relay land` whose working folder lies in one) and
    whose test is over: a prefixed folder on that path no longer exists, or the process is older than ORPHAN_AGE. Nothing else is touched.

    A leftover that leads its own process group (pgid == pid) is stopped with that group, unless the group is the sweeping gate's own or
    an ancestor's; any other is stopped alone (a fixture `relay gate` shares the runner's group, which may hold a real gate's command).
    Returns one line per stop. `own` is the sweeping gate's pid; its ancestors are added here."""
    try:
        procs = read_procs()
    except (OSError, subprocess.SubprocessError):
        return []
    mine = set()
    for pid in own:
        mine |= relay_procs.ancestors(procs, pid)
    my_groups = {p.pgid for p in procs if p.pid in mine}
    first = [p for p in procs if p.ppid == 1 and p.pid not in mine]
    named = {p.pid: _command_folders(p.command, roots) for p in first}
    asked = [p.pid for p in first if not named[p.pid] and RELAY_COMMAND.search(p.command)]
    cwds = (read_cwds(asked) or {}) if asked else {}
    now = time.time()
    lines: list[str] = []
    targets: list[tuple[int, bool]] = []
    alone: dict[int, relay_procs.Proc] = {}
    for p in first:
        folders = named[p.pid] or (prefixed_folders(cwds[p.pid], roots) if p.pid in cwds else [])
        if not folders:
            continue
        gone = [f for f in folders if not os.path.exists(f)]
        if gone:
            why = "parent gone, folder deleted"
        elif now - p.started > ORPHAN_AGE:
            why = "parent gone, older than %d min" % (ORPHAN_AGE // 60)
        else:
            continue
        group = p.pgid == p.pid and p.pgid not in my_groups
        targets.append((p.pid if not group else p.pgid, group))
        if not group:
            alone[p.pid] = p
        lines.append("%s %d (%s): %s" % (LEFTOVER, p.pid, p.command[:120], why))
    if targets:
        killed = relay_procs.stop(targets)
        # a pid stopped alone and then killed may have left its own command as a leader of a group in a deleted folder: look once more
        if _again and any(not group and pid in alone for pid, group in killed):
            lines += sweep(roots, read_procs, read_cwds, own, _again=False)
    return lines


def _command_folders(command: str, roots: Sequence[str]) -> list[str]:
    found: list[str] = []
    for token in command.split():
        found += prefixed_folders(token, roots)
    return found


def tree_moved(worktree, head):
    """Why the tree the gate ran on is no longer the commit `head` (a sentence), else None.

    HEAD may differ from `head` only by inert files, and `git status` must be empty (a file edited, created or staged
    and left so means the tested tree was not the commit)."""
    rc, now = relay_git.git(worktree, "rev-parse", "HEAD")
    if rc != 0 or not relay_marks.is_sha(now):
        return "git cannot read HEAD"
    if now != head:
        code = relay_inert.changed(worktree, head, now)
        if code:
            return "HEAD moved to %s (files: %s)" % (now[:12], ", ".join(code[:5]))
    rc, status = relay_git.git(worktree, "status", "--porcelain", raw=True)
    if rc != 0:
        return "git cannot read the state of the worktree"
    dirty = [line[3:] for line in status.splitlines()]
    if dirty:
        return "files changed (%s%s)" % (", ".join(dirty[:5]), " and %d more" % (len(dirty) - 5) if len(dirty) > 5 else "")
    return None


def first_failure(output):
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


def reusable(worktree, head, command):
    """The path of a green gate log for the same command on a commit at or before `head` with only inert changes since, else None.

    Walks back from `head` along the branch's own line (first parents: a take of the default branch has the branch first, so
    master's newer commits are not walked) and stops at the first commit after which a non-inert file changed. A log counts only when its
    first line is `head <that commit>`, its `cmd` line is the command about to run and its last line is `exit 0`."""
    wanted = "cmd %s" % " ".join(shlex.quote(c) for c in command)
    rc, listing = relay_git.git(worktree, "rev-list", "--first-parent", head)
    if rc != 0:
        return None
    for commit in listing.split():
        if relay_inert.changed(worktree, commit, head):
            return None
        log = os.path.join(worktree, relay_marks.FOLDER, "%s.gate.log" % commit)
        try:
            with open(log, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        if len(lines) >= 3 and lines[0] == "head %s" % commit and lines[1] == wanted and lines[-1] == "exit 0":
            return log
    return None


def finished_red(worktree: str, head: str, command: Sequence[str], stopped: bool = False) -> Optional[tuple[int, str, list[str]]]:
    """(exit code, log path, failing lines) of a finished red gate log for the same command on a commit at or before
    `head`, when only relay's own record commits (files under .relay/checks/) lie between, else None.

    This is stricter than `reusable`: a red result must not stand for code that changed, so any file outside the
    checks folder (inert or not) ends the walk. A log counts only when its first line is `head <that commit>`, its
    `cmd` line is the command about to run and its last line is `exit <n>` with n not 0.
    `stopped=True` asks the other way round: the log of an EARLIER commit (not `head` itself) that ends `exit 124`, the gate
    stopped at its time limit on this same code."""
    wanted = "cmd %s" % " ".join(shlex.quote(c) for c in command)
    rc, listing = relay_git.git(worktree, "rev-list", head)
    if rc != 0:
        return None
    for commit in listing.split():
        rc, names = relay_git.git(worktree, "diff", "--name-only", "--no-renames", "%s..%s" % (commit, head))
        if rc != 0 or any(not name.startswith(relay_marks.FOLDER + "/") for name in names.splitlines()):
            return None
        log = os.path.join(worktree, relay_marks.FOLDER, "%s.gate.log" % commit)
        if stopped and commit == head:
            continue
        try:
            with open(log, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        lines = text.splitlines()
        if len(lines) < 3 or lines[0] != "head %s" % commit or lines[1] != wanted:
            continue
        last = lines[-1].split()
        if len(last) == 2 and last[0] == "exit" and last[1].isdigit() and (int(last[1]) == LIMIT_EXIT if stopped else 0 < int(last[1]) < 127 and int(last[1]) != LIMIT_EXIT):      # 127 (could not start), >= 128 (killed) and 124 (stopped at the time limit) came from outside the commit: not reused, the next gate runs
            return int(last[1]), log, first_failure("\n".join(l for l in lines[3:-1] if not l.startswith(STOPPED)))
    return None


def earlier_stop(worktree: str, head: str, quick: bool) -> Optional[list[str]]:
    """The failing lines of an earlier gate log for the same command and the same code that was stopped at the time limit
    (a second stop on the same code is a hang, not load), else None."""
    chosen = (quick_binding(worktree) if quick else None) or binding(worktree)
    found = finished_red(worktree, head, shlex.split(chosen), stopped=True)
    return found[2] if found else None


def reused_red(red: tuple[int, str, list[str]]) -> tuple[int, str, list[str]]:
    """Say on stderr that a red gate is reported, not run; hand the result back unchanged."""
    sha = os.path.basename(red[1])[:-len(".gate.log")]
    print("gate: the code is unchanged since the red gate of %s: reported, not run (relay gate --again runs it)" % sha,
          file=sys.stderr, flush=True)
    return red


def signal_line(number: int) -> str:
    """The gate log's line for a command ended by a signal; the sender is unknown (only the receiver can read si_pid)."""
    return "gate command ended by %s (sender unknown: the stop went to the command, not to the gate)" % {int(s): s.name for s in signal.Signals}.get(number, "signal %d" % number)


def hold_stops() -> tuple[list[int], Callable[[], None]]:
    """Hold SIGINT, SIGTERM and SIGHUP: arrivals are appended to the returned list instead of acting. The function returned
    puts the earlier handlers back. Not the main thread: nothing is held (the caller owns its signals)."""
    held: list[int] = []
    saved: dict[int, Any] = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            if signal.getsignal(sig) == signal.SIG_IGN:      # an ignored stop needs no hold, and the command must inherit the ignore
                continue
            saved[sig] = signal.signal(sig, lambda signum, frame: held.append(signum))
    except ValueError:
        pass

    def release() -> None:
        for sig, old in saved.items():
            signal.signal(sig, old)
    return held, release


def sweep_leftovers(worktree: str, env: Mapping[str, str]) -> list[str]:
    """B: at the start of a real gate, stop the leftovers of relay's tests (see `sweep`), printing each stop on stderr; returns the lines.
    A gate whose worktree or home lies in a temporary folder is itself a test's: it sweeps nothing, so no test stops another test's processes."""
    roots = temp_roots()
    if under(worktree, roots) or under(env.get("RELAY_HOME") or relay_config.home_dir(), roots):
        return []
    lines = sweep(roots, relay_procs.read_procs, relay_procs.working_folders, [os.getpid()])
    for line in lines:
        print(line, file=sys.stderr, flush=True)
    return lines


def run(worktree: str, args: Sequence[str] = (), environ: Optional[Mapping[str, str]] = None,
        quick: bool = False, again: bool = False) -> tuple[int, str, list[str]]:
    """Run the gate; write and commit its log; return (exit code, log path, output lines to show when red).
    `again` skips both reuses (a green and a finished red gate of the same code): the command runs."""
    worktree = os.path.realpath(worktree)
    head = check_ready(worktree)
    chosen = (quick_binding(worktree) if quick else None) or binding(worktree)
    command = shlex.split(chosen) + list(args)
    # the license check is the gate's own step when kit.toml has [license]; it runs every time (cheap), so a green log of
    # the same commit never stands for a license that has since broken (kit.toml and the license files are not inert)
    try:
        license_lines = relay_license.check(worktree)
    except (OSError, ValueError) as exc:
        license_lines = ["license: cannot check: %s" % exc]
    reuse = not license_lines and not again
    green = reusable(worktree, head, command) if reuse else None
    if green is not None:      # the same code already has a green gate: report it, run nothing
        return 0, green, []
    red = finished_red(worktree, head, command) if reuse else None
    if red is not None:      # the same code already has a finished red gate (only record commits since): report it, run nothing
        return reused_red(red)
    swept = sweep_leftovers(worktree, os.environ if environ is None else environ)
    # the output goes under the worktree's git dir, never into the tree: a project that does not ignore .ci/ would see
    # an untracked file and the next gate (and the merge cleanup) would refuse
    rc, git_path = relay_git.git(worktree, "rev-parse", "--path-format=absolute", "--git-path", "relay-gate.out")
    if rc != 0 or not git_path:
        raise GateRefused("git cannot tell where %s keeps its files" % worktree)
    out_path = git_path
    lock_path = os.path.join(os.path.dirname(git_path), "relay-gate.lock")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    os.makedirs(os.path.join(worktree, ".ci"), exist_ok=True)      # the gate command's own scratch folder (empty, so git sees nothing)
    env = dict(os.environ if environ is None else environ)
    env["RELAY_GATE"] = head
    home = env.get("RELAY_HOME") or relay_config.home_dir()
    # a stopped gate (SIGTERM, SIGHUP; SIGINT already raises) must end its command too, so it leaves through an exception
    saved = {}

    def stop(signum, frame):
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            saved[sig] = signal.signal(sig, stop)
        except ValueError:      # not the main thread: no handlers, the caller owns its signals
            break
    notify = lambda line: print(line, file=sys.stderr, flush=True)
    try:
        # one gate at a time per worktree, taken before the slot so a gate waiting for its worktree holds no slot
        lock = take_worktree_lock(lock_path, notify, swept.append)
        try:
            slot, waited = take_slot(slot_count(home), os.path.join(home, "gate-slots"), notify)
            tokens = relay_tokens.Held()      # the gate's test tokens; freed with the slot, whatever ends the gate
            try:
                # the waits can be long: the code may have moved, or the same code may have gone green meanwhile
                now = check_ready(worktree)
                try:      # the license check is a gate step: it runs inside the slot, on the files as they are after the wait
                    license_lines = relay_license.check(worktree)
                except (OSError, ValueError) as exc:
                    license_lines = ["license: cannot check: %s" % exc]
                reuse = not license_lines and not again
                green = reusable(worktree, now, command) if reuse else None      # (a gate log committed meanwhile moves HEAD, but only by inert files)
                if green is not None:
                    return 0, green, []
                red = finished_red(worktree, now, command) if reuse else None      # the gate we waited for may have gone red
                if red is not None:
                    return reused_red(red)
                if now != head:
                    raise GateRefused("%s moved to another commit while the gate waited: run it again" % worktree)
                if os.path.isfile(os.path.join(worktree, "lib", "relay_tokens.py")):      # only a worktree with relay's test runners uses tokens: a project's own gate takes its slot only and gets no variable
                    st = relay_tokens.settings(home, slot_count(home))
                    for text in st.notes:
                        notify("gate: test tokens: " + text)
                    tokens, token_wait = relay_tokens.take_base(home, st, relay_tokens.GATE, st.per_gate, lambda line: notify("gate: " + line))
                    waited += token_wait
                    env[relay_tokens.ENV_HOLD] = relay_tokens.hold_value(st.per_gate, home)
                proc, stopped_by = None, ""
                try:
                    with open(out_path, "wb") as sink:
                        # the lock file goes to the command: the OS keeps the lock until its last process ends, even if this process is killed
                        # a stop that lands while Popen is still returning (the command already runs, `proc` is not yet bound) would
                        # skip the kill below and orphan the command: hold it until `proc` is bound, then raise it
                        held, release = hold_stops()
                        try:
                            proc = subprocess.Popen(command, cwd=worktree, env=env, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
                                                    start_new_session=True, pass_fds=(lock.fileno(),))
                        finally:
                            release()
                            if held:      # also when Popen raised: a stop still stops the gate
                                os.kill(os.getpid(), held[0])      # the caller's own handler raises it now
                        # the lock file names the command's process group too: if this process is killed, the command holds the lock
                        lock.seek(0)
                        lock.truncate()
                        lock.write("%d %d\n" % (os.getpid(), proc.pid))
                        lock.flush()
                        returncode = proc.wait()
                    code = returncode if returncode >= 0 else 128 - returncode
                    stopped_by = signal_line(-returncode) if returncode < 0 else ""
                except OSError as exc:
                    with open(out_path, "w") as text_sink:
                        text_sink.write("gate command could not start: %s\n" % exc)
                    code = 127
                finally:
                    if proc is not None:      # the command's whole process group ends before the slot is freed
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except OSError:
                            pass
                        proc.wait()
                why = tree_moved(worktree, head)
                if why is not None:
                    raise GateRefused("the worktree changed while the gate ran (%s): commit, then run it again" % why)
            finally:
                tokens.release()
                slot.close()
            # the lock stays until the log is committed: a second gate of this worktree then finds the log
            with open(out_path, encoding="utf-8", errors="replace") as handle:
                output = handle.read()
            if stopped_by:
                output += ("" if output.endswith("\n") or not output else "\n") + stopped_by + "\n"
            if license_lines:
                output += ("" if output.endswith("\n") or not output else "\n") + "license check FAILED\n" + "".join("  %s\n" % line for line in license_lines)
                code = code or 1
            text = "head %s\ncmd %s\nwait %.1f\n%s%s%sexit %d\n" % (head, " ".join(shlex.quote(c) for c in command), waited, "".join(l + "\n" for l in swept), output, "" if output.endswith("\n") or not output else "\n", code)
            log = os.path.join(worktree, relay_marks.FOLDER, "%s.gate.log" % head)
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "w", encoding="utf-8") as handle:
                handle.write(text)
            try:
                relay_marks.commit_file(worktree, log, "relay: gate of %s" % head)
            except relay_marks.MarkError as exc:
                raise GateRefused("the gate exited %d but its log was not committed: %s" % (code, exc))
            return code, log, first_failure(output) if code != 0 else []
        finally:
            lock.close()
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)
