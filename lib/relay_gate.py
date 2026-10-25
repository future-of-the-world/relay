"""`relay gate`: run the project's free gate on a clean task-branch commit and store the result as a gate log
(docs/plans/review-gate.md section 5).

The log `.relay/checks/<G>.gate.log` starts with `head <G>` (the commit the gate ran on, full sha), then `cmd <command>`,
`wait <seconds>` (the wait for a slot), the gate's output, and ends with `exit <n>`. The merge hook trusts it because this code, not a model, wrote it. The log
is committed alone, with the same commit path as check marks (`relay_marks.commit_file`).

A gate that has to run takes one of a few slots shared by the whole machine (OS file locks under `$RELAY_HOME/gate-slots/`,
so a killed gate frees its slot by itself). The log's third line, `wait <seconds>`, is the time spent waiting for a slot.
"""

import fcntl
import os
import shlex
import signal
import subprocess
import sys
import time

import relay_config
import relay_git
import relay_inert
import relay_marks
import relay_toml

DEFAULT_CI = "bin/ci"
FAILED_LINES = 8        # lines of the first failing step shown on the third output line
DEFAULT_SLOTS = 3       # gates that may run at once on the machine (RELAY_GATE_SLOTS overrides)
SLOT_POLL = 0.2         # seconds between looks at the slots while all are busy


class GateRefused(Exception):
    """The gate was not started; the text says why in one line."""


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


def slot_count(environ=None):
    """How many gates may run at once: RELAY_GATE_SLOTS, else DEFAULT_SLOTS."""
    value = (os.environ if environ is None else environ).get("RELAY_GATE_SLOTS")
    if value is None or not value.strip():
        return DEFAULT_SLOTS
    try:
        count = int(value)
    except ValueError:
        count = 0
    if count < 1:
        raise GateRefused("RELAY_GATE_SLOTS must be a whole number of 1 or more, not %r" % value)
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
                notify("gate: waiting for a free gate slot (%d busy)" % count)
            told = True
            time.sleep(SLOT_POLL)
    except BaseException:
        for handle in handles:
            handle.close()
        raise


def first_failure(output):
    """The first failing step's lines (the step line and its indented findings), else the last five lines."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if "FAILED" in line:
            block = [line]
            for more in lines[i + 1:i + FAILED_LINES]:
                if not more.startswith((" ", "\t")):
                    break
                block.append(more)
            return block
    return lines[-5:]


def reusable(worktree, head, command):
    """The path of a green gate log for the same command on a commit at or before `head` with only inert changes since, else None.

    Walks back from `head` and stops at the first commit after which a non-inert file changed. A log counts only when its
    first line is `head <that commit>`, its `cmd` line is the command about to run and its last line is `exit 0`."""
    wanted = "cmd %s" % " ".join(shlex.quote(c) for c in command)
    rc, listing = relay_git.git(worktree, "rev-list", head)
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


def run(worktree, args=(), environ=None):
    """Run the gate; write and commit its log; return (exit code, log path, output lines to show when red)."""
    worktree = os.path.realpath(worktree)
    head = check_ready(worktree)
    command = shlex.split(binding(worktree)) + list(args)
    green = reusable(worktree, head, command)
    if green is not None:      # the same code already has a green gate: report it, run nothing
        return 0, green, []
    # the output goes under the worktree's git dir, never into the tree: a project that does not ignore .ci/ would see
    # an untracked file and the next gate (and the merge cleanup) would refuse
    rc, git_path = relay_git.git(worktree, "rev-parse", "--path-format=absolute", "--git-path", "relay-gate.out")
    if rc != 0 or not git_path:
        raise GateRefused("git cannot tell where %s keeps its files" % worktree)
    out_path = git_path
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
    try:
        slot, waited = take_slot(slot_count(env), os.path.join(home, "gate-slots"), lambda line: print(line, file=sys.stderr, flush=True))
        try:
            # the wait can be long: the code may have moved, or the same code may have gone green meanwhile
            now = check_ready(worktree)
            green = reusable(worktree, now, command)      # (a gate log committed meanwhile moves HEAD, but only by inert files)
            if green is not None:
                return 0, green, []
            if now != head:
                raise GateRefused("%s moved to another commit while the gate waited for a slot: run it again" % worktree)
            proc = None
            try:
                with open(out_path, "wb") as sink:
                    proc = subprocess.Popen(command, cwd=worktree, env=env, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, start_new_session=True)
                    returncode = proc.wait()
                code = returncode if returncode >= 0 else 128 - returncode
            except OSError as exc:
                with open(out_path, "w") as sink:
                    sink.write("gate command could not start: %s\n" % exc)
                code = 127
            finally:
                if proc is not None:      # the command's whole process group ends before the slot is freed
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    proc.wait()
        finally:
            slot.close()
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)
    with open(out_path, encoding="utf-8", errors="replace") as handle:
        output = handle.read()
    text = "head %s\ncmd %s\nwait %.1f\n%s%sexit %d\n" % (head, " ".join(shlex.quote(c) for c in command), waited, output, "" if output.endswith("\n") or not output else "\n", code)
    log = os.path.join(worktree, relay_marks.FOLDER, "%s.gate.log" % head)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w", encoding="utf-8") as handle:
        handle.write(text)
    try:
        relay_marks.commit_file(worktree, log, "relay: gate of %s" % head)
    except relay_marks.MarkError as exc:
        raise GateRefused("the gate exited %d but its log was not committed: %s" % (code, exc))
    return code, log, first_failure(output) if code != 0 else []
