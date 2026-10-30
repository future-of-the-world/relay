"""`relay land <branch>`: a program lands a ready change, no agent (design relay-land, reports/design-relay-land.md).

It takes the landing lock of the repository, merges the default branch into the branch (the take), runs the merge hook's
judge without its gate step, runs the quick gate on the result, runs the full judge and fast-forwards the default branch.
`relay land --stats` computes the comparison numbers from the dated events (`record`) and from git; nothing is stored
but the events. Settings, in the project's .claude/kit.toml under [land]: land_tries, land_inert_tries, land_ff_lock_tries.

Exit codes: 0 landed, 1 red gate, 2 refused (also a dirty main checkout), 3 take conflict, 4 handed back, 5 waits for the owner
(a hold or an unanswered question), 6 waits for the paid run. The waits are checked in lib/relay_land_waits.py.
Tests: tests/test_land.py
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import IO, Any, Callable, Optional

import relay_git
import relay_inert

SETTINGS = {"land_tries": (2, 1, 3), "land_inert_tries": (10, 3, 50), "land_ff_lock_tries": (3, 1, 10)}   # default, lowest, highest
FF_LOCK_WAIT_S = 1.0          # seconds between two fast-forwards refused by an index.lock (the count is the setting)
JUDGE_TIMEOUT_S = 300         # one judge reads git only; far above its seconds, finite so a stuck git cannot hold the lock forever
LANDED, RED, CONFLICT, REFUSED, HANDED_BACK, DIRTY = "landed", "red", "conflict", "refused", "handed_back", "dirty"
WAITS_OWNER, WAITS_PAID = "waits_owner", "waits_paid"
EXIT = {LANDED: 0, RED: 1, REFUSED: 2, DIRTY: 2, CONFLICT: 3, HANDED_BACK: 4, WAITS_OWNER: 5, WAITS_PAID: 6}
HOOK = next((h for n in (2, 4) if os.path.exists(h := os.path.join(os.path.realpath(__file__).rsplit("/", n)[0], "plugins", "relay", "hooks", "merge.py"))), os.path.join(os.path.realpath(__file__).rsplit("/", 2)[0], "plugins", "relay", "hooks", "merge.py"))   # the repository's merge hook: lib/ is 2 path parts below the root, plugins/<name>/lib/ copies 4


def setting(cfg: Any, key: str) -> int:
    """The setting `land.<key>` clamped to its bounds; the default when it is missing or not a whole number."""
    import relay_config      # not at the top: the merge hook's plugin folder carries this file without relay_config
    default, low, high = SETTINGS[key]
    value = relay_config.get(cfg, "land." + key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


@dataclass
class Event:
    kind: str                       # asked | locked | done | held | hold | release
    ts: str                         # ISO 8601 UTC
    branch: str = ""
    pid: int = 0
    outcome: str = ""               # done: landed | red | conflict | refused | handed_back | dirty
    before: Optional[str] = None    # done: the default branch's sha before the fast-forward
    sha: Optional[str] = None       # done: the landed head
    gates_run: int = 0
    gate_seconds: float = 0.0
    code_moves: int = 0
    inert_moves: int = 0
    slug: str = ""                  # held: the item held at start
    file: str = ""
    holder: str = ""
    words: str = ""                 # hold: the owner's words


KINDS = ("asked", "locked", "done", "held", "hold", "release")
OUTCOMES = (LANDED, RED, CONFLICT, REFUSED, HANDED_BACK, DIRTY, WAITS_OWNER, WAITS_PAID)
_TYPES = {f.name: f.type for f in fields(Event)}
_NUMBERS = ("pid", "gates_run", "code_moves", "inert_moves")


def parse_event(line: str) -> Optional[Event]:
    """The one checking parser: an Event, or None for a line that is not one (unknown kind, a missing or mistyped field)."""
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("kind") not in KINDS or not isinstance(data.get("ts"), str):
        return None
    try:
        datetime.fromisoformat(data["ts"])
    except ValueError:
        return None
    for key, value in data.items():
        if key not in _TYPES:
            return None
        if key in _NUMBERS and (isinstance(value, bool) or not isinstance(value, int)):
            return None
        if key == "gate_seconds" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return None
        if key in ("before", "sha") and value is not None and not isinstance(value, str):
            return None
        if key in ("kind", "ts", "branch", "outcome", "slug", "file", "holder", "words") and not isinstance(value, str):
            return None
    if data["kind"] == "done" and data.get("outcome") not in OUTCOMES:
        return None
    return Event(**data)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _common_dir(main: str) -> str:
    rc, out = relay_git.git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not out:
        raise ValueError(f"cannot find the git directory of {main}")
    return out


def events_path(main: str) -> str:
    return os.path.join(_common_dir(main), "relay-land", "events.jsonl")


def record(main: str, event: Event) -> None:
    """The one writer: append the event as a line under an exclusive lock, in the git common dir (outside the tree)."""
    path = events_path(main)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps({k: v for k, v in asdict(event).items() if v not in ("", None, 0, 0.0) or k in ("kind", "ts")}) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(line)
        handle.flush()


def read_events(main: str) -> tuple[list[Event], int]:
    """(events in file order, number of unreadable lines)."""
    try:
        with open(events_path(main), encoding="utf-8") as handle:
            lines = [l for l in handle.read().splitlines() if l.strip()]
    except OSError:
        return [], 0
    parsed = [parse_event(l) for l in lines]
    return [e for e in parsed if e is not None], sum(1 for e in parsed if e is None)


# ---- the landing lock ----

def lock_path(main: str) -> str:
    return os.path.join(_common_dir(main), "relay-land.lock")


def _holder_words(text: str) -> tuple[int, str, str]:
    parts = text.split()
    pid = int(parts[0]) if parts and parts[0].isdigit() else 0
    return pid, (parts[1] if len(parts) > 1 else "another branch"), (parts[2] if len(parts) > 2 else "")


def holder(main: str) -> Optional[tuple[int, str, str]]:
    """(pid, branch, started_at) of the lander that holds the landing lock, None when nobody does. Never waits."""
    try:
        with open(lock_path(main), "a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.seek(0)
                return _holder_words(handle.read())
            fcntl.flock(handle, fcntl.LOCK_UN)
    except (OSError, ValueError):
        return None
    return None


def lock(main: str, branch: str, notify: Callable[[str], None]) -> IO[str]:
    """Open and take the landing lock, waiting without a time limit; `notify` is told once who holds it. The holder writes
    "pid branch started_at" into the file. The OS frees the lock when the process ends, however it ends."""
    handle = open(lock_path(main), "a+", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        pid, other, since = _holder_words(handle.read())
        notify(f"waits for the landing of {other} (pid {pid}, since {since})")
        fcntl.flock(handle, fcntl.LOCK_EX)
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {branch} {now()}\n")
    handle.flush()
    return handle


# ---- git steps ----

class Stop(Exception):
    """The landing ends here with this outcome; `lines` are printed."""

    def __init__(self, outcome: str, lines: list[str], **fields_: Any) -> None:
        super().__init__(lines[0] if lines else outcome)
        self.outcome, self.lines, self.fields = outcome, lines, fields_


@dataclass
class Take:
    taken: bool                 # a merge commit was made
    conflicts: list[str]        # the conflicted files when git stopped (the merge is aborted)


def take(worktree: str, default: str) -> Take:
    """`git merge --no-edit <default>` in the branch's worktree when the default branch is not already inside it."""
    ref = "refs/heads/" + default
    if relay_git.git(worktree, "merge-base", "--is-ancestor", ref, "HEAD")[0] == 0:
        return Take(False, [])
    done = subprocess.run(["git", "-C", worktree, "merge", "--no-edit", default], capture_output=True, text=True)
    if done.returncode == 0:
        return Take(True, [])
    rc, names = relay_git.git(worktree, "diff", "--name-only", "--diff-filter=U")
    files = names.splitlines() if rc == 0 else []
    relay_git.git(worktree, "merge", "--abort")
    if not files:
        reason = (done.stderr.strip().splitlines() or done.stdout.strip().splitlines() or ["no reason given"])[-1]
        raise Stop(REFUSED, [f"land: git could not take {default} into the branch: {reason}"])
    return Take(False, sorted(files))


def blocking(main: str, branch: str) -> list[str]:
    """The files with uncommitted changes (or untracked) in the main checkout that the fast-forward would write."""
    rc, status = relay_git.git(main, "status", "--porcelain", "--untracked-files=all", "-z", raw=True)
    if rc != 0:
        raise Stop(REFUSED, [f"land: cannot read the state of {main}"])
    entries, dirty, i = status.split("\0"), set(), 0
    while i < len(entries):
        entry = entries[i]
        if len(entry) > 3:
            dirty.add(entry[3:])
            if entry[0] in "RC":
                i += 1
                if i < len(entries) and entries[i]:
                    dirty.add(entries[i])
        i += 1
    default = relay_git.current_branch(main) or ""
    rc, names = relay_git.git(main, "diff", "--name-only", "--no-renames", "-z", f"refs/heads/{default}...refs/heads/{branch}", raw=True)      # three dots: what the branch's side changed, not what master moved since the fork
    brought = {n for n in names.split("\0") if n} if rc == 0 else set()
    return sorted(dirty & brought)


def _sha(repo: str, ref: str) -> str:
    rc, out = relay_git.git(repo, "rev-parse", "--verify", "-q", ref)
    if rc != 0:
        raise Stop(REFUSED, [f"land: cannot read {ref} in {repo}"])
    return out


def _judge(main: str, branch: str, before_gate: bool) -> Optional[str]:
    """The merge hook's judge in its own process (the file the PreToolUse hook runs): None when it passes, else its line."""
    cmd = [sys.executable, "-I", HOOK, "judge", *(["--before-gate"] if before_gate else []), main, branch]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=JUDGE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"land: the judge of {branch} did not finish in {JUDGE_TIMEOUT_S} s"
    if done.returncode == 0:
        return None
    return (done.stderr.strip().splitlines() or done.stdout.strip().splitlines() or [f"merge refused: the judge of {branch} exited {done.returncode}"])[-1]


def _dirty_lines(files: list[str], branch: str) -> list[str]:
    return [f"land: the main checkout has uncommitted changes to {', '.join(files[:5])}, which landing {branch} would write: "
            f"commit or put aside {', '.join(files[:5])} in the main checkout, then relay land {branch} again"]


@dataclass
class Result:
    outcome: str
    lines: list[str]
    units: list[tuple[str, str]] = field(default_factory=list)     # LANDED: (item id, branch) of each item the fast-forward brought in

    @property
    def code(self) -> int:
        return EXIT[self.outcome]


def land(repo: str, branch: str, notify: Callable[[str], None], paid_fix: bool = False) -> Result:
    """Land `branch`; the steps of design relay-land 4.1. Returns the outcome and the lines to print. `paid_fix` lets the branch
    through a red paid run (lib/relay_land_waits.py)."""
    import relay_config      # these are not at the top: the merge hook's plugin folder carries this file without them
    import relay_land_waits
    import relay_queue
    try:
        main, default = relay_queue._context_with_relay(repo)
    except relay_queue.Refused as exc:
        return Result(REFUSED, [f"land: {exc}"])
    cfg = relay_config.load_bindings(main)
    tries, inert_tries, ff_tries = (setting(cfg, k) for k in ("land_tries", "land_inert_tries", "land_ff_lock_tries"))
    stats = Event("done", now(), branch=branch, pid=os.getpid())
    try:
        tree = _preflight(main, default, branch)
        if (refusal := relay_queue.open_item_refusal(tree, branch)): return Result(REFUSED, [refusal])
        record(main, Event("asked", now(), branch=branch, pid=os.getpid()))
        try:
            relay_land_waits.check(main, default, branch, paid_fix)      # before the lock: a waiting branch does not queue for it
        except Stop as stop:
            stats.outcome, stats.ts = stop.outcome, now()
            record(main, stats)
            return Result(stop.outcome, stop.lines)
        handle = lock(main, branch, notify)
    except Stop as stop:
        return Result(stop.outcome, stop.lines)
    try:
        record(main, Event("locked", now(), branch=branch, pid=os.getpid()))
        try:
            relay_land_waits.check(main, default, branch, paid_fix)      # again after the lock: the wait may have begun while this one queued
            result = _locked(main, default, branch, tree, stats, tries, inert_tries, ff_tries, notify, paid_fix)
        except Stop as stop:
            result = Result(stop.outcome, stop.lines)
            for key, value in stop.fields.items():
                setattr(stats, key, value)
        except Exception as exc:        # anything else under the lock still gets its done event, so the counters see the landing
            result = Result(REFUSED, [f"land: stopped by an unexpected error ({type(exc).__name__}: {exc}); the default branch is at {_sha(main, 'refs/heads/' + default)[:12]}"])
        stats.outcome, stats.ts = result.outcome, now()
        record(main, stats)
    finally:
        handle.close()
    if result.outcome == LANDED:                  # after the done event and the lock: the landing stays LANDED whatever the record does
        result.lines.extend(_change_records(repo, main, result, stats))
    return result


def _change_records(repo: str, main: str, result: Result, stats: Event) -> list[str]:
    """Write the change records of a landing (relay_metrics); a failure is one line naming the next command, never a changed outcome."""
    names = [slug for slug, _ in result.units]
    try:
        import relay_metrics
        lines: list[str] = []
        relay_metrics.record_landing(repo, result.units, stats.before, stats.sha or "", read_events(main)[0], stats.pid, lines.append, landed=stats.branch)
        return lines
    except Exception as exc:        # the landing already happened (the rule _close_features follows)
        return [f"land: landed, but the change record was not written: {exc}; next: relay metrics backfill {' '.join(names)}".rstrip()]


def _preflight(main: str, default: str, branch: str) -> str:
    """Refuse, naming the next step, before the lock is taken. Returns the branch's worktree path."""
    if relay_git.git(main, "rev-parse", "--verify", "-q", "refs/heads/" + branch)[0] != 0:
        raise Stop(REFUSED, [f"land: there is no branch {branch}"])
    tree = next((w for w in relay_git.worktrees(main) if w["branch"] == branch), None)
    if tree is None:
        raise Stop(REFUSED, [f"land: {branch} has no worktree: make one (git worktree add) so the take of {default} has a place to run"])
    rc, status = relay_git.git(tree["path"], "status", "--porcelain", "--untracked-files=normal")
    if rc != 0 or status:
        raise Stop(REFUSED, [f"land: the worktree of {branch} has uncommitted changes ({', '.join(l[3:] for l in status.splitlines()[:5])}): commit them or remove them, then relay land {branch} again"])
    if relay_git.current_branch(main) != default:
        raise Stop(REFUSED, [f"land: the main checkout is not on {default}: switch it back, then relay land {branch} again"])
    files = blocking(main, branch)
    if files:
        raise Stop(DIRTY, _dirty_lines(files, branch))
    return tree["path"]


def _locked(main: str, default: str, branch: str, tree: str, stats: Event, tries: int, inert_tries: int, ff_tries: int,
            notify: Callable[[str], None], paid_fix: bool = False) -> Result:
    import relay_gate
    import relay_land_waits
    code_moves = inert_moves = 0
    ref = "refs/heads/" + default
    while True:
        base = _sha(main, ref)                      # the default branch the take is made from
        taken = take(tree, default)
        if taken.conflicts:
            raise Stop(CONFLICT, [
                f"land: taking {default} into {branch} conflicts in {', '.join(taken.conflicts)}; the worktree is clean again",
                f"next: a cycle unit of kind fix in {os.path.relpath(tree, main)} on {branch}: fix 'take {default} into {branch} and resolve "
                f"{', '.join(taken.conflicts)}', findings = the branch's last review JSON (the review of its cycle result), fixes = the "
                f"fixer's report, no item (the branch's item is already closed); then relay land {branch} again"], code_moves=code_moves, inert_moves=inert_moves)
        reason = _judge(main, branch, before_gate=True)
        if reason:
            raise Stop(REFUSED, [reason], code_moves=code_moves, inert_moves=inert_moves)
        started = time.monotonic()
        head = _sha(tree, "HEAD")
        try:
            code, log, red = relay_gate.run(tree, quick=True, environ={**os.environ, "RELAY_LAND": "1"})
        except relay_gate.GateRefused as exc:
            raise Stop(REFUSED, [f"land: the gate could not run: {exc}"], code_moves=code_moves, inert_moves=inert_moves)
        ran = os.path.basename(log) == head + ".gate.log"      # a reused log is named for an earlier commit
        if ran:
            stats.gates_run, stats.gate_seconds = stats.gates_run + 1, stats.gate_seconds + time.monotonic() - started
        if code == relay_gate.LIMIT_EXIT:     # stopped at the time limit: not a red gate (no fixer, no fall back to one change at a time)
            m = re.search(r"stopped at the (\S+ limit)(?:, step (.+) was running)?", " ".join(red))
            how = f"stopped at the {m[1]}" + (f" (step {m[2]} was running)" if m[2] else "") if m else "stopped at its time limit"
            raise Stop(RED if (twice := relay_gate.earlier_stop(tree, head, True) is not None) else HANDED_BACK, [f"land: the gate of {branch} {how}" + (" twice on the same code: a hang, not load: a fix unit or the owner, not a rerun" if twice else f": relay land {branch} again")], code_moves=code_moves, inert_moves=inert_moves)
        if code != 0:
            raise Stop(RED, [f"land: the gate of {branch} is red (exit {code}); log {log}", *red[:5]], code_moves=code_moves, inert_moves=inert_moves)
        landed = False
        if _sha(main, ref) == base:         # (a moved default branch makes the judge say "behind": count the move and take again)
            judged = _sha(main, "refs/heads/" + branch)
            reason = _judge(main, branch, before_gate=False)
            if reason:
                raise Stop(REFUSED, [reason], code_moves=code_moves, inert_moves=inert_moves)
            stats.code_moves, stats.inert_moves = code_moves, inert_moves
            relay_land_waits.check(main, default, branch, paid_fix)      # right before the fast-forward: a paid run or a hold may have begun during the gate
            landed = _fast_forward(main, default, branch, base, ff_tries, notify, judged)
        if landed:
            stats.before = base
            return _landed(main, default, branch, stats, started)
        # the default branch moved while we gated: an inert move (only queue records or the handover) is cheap, a code move is not
        if relay_inert.changed(main, base, _sha(main, ref)):
            code_moves += 1
        else:
            inert_moves += 1
        if code_moves > tries or inert_moves > inert_tries:
            raise Stop(HANDED_BACK, [f"land: {default} moved {code_moves + inert_moves} times during the landing: relay land {branch} again"],
                       code_moves=code_moves, inert_moves=inert_moves)


def _fast_forward(main: str, default: str, branch: str, base: str, ff_tries: int, notify: Callable[[str], None], judged: str) -> bool:
    """True when landed; False when the default branch moved since `base` (the caller retakes); a Stop for every other end.
    The short branch name is used so the reflog reads `merge wt/x: Fast-forward`, which relay_lanes.landing matches."""
    ref = "refs/heads/" + default
    for attempt in range(ff_tries):
        if _sha(main, "refs/heads/" + branch) != judged:      # a commit after the judge would land with no gate and no check
            raise Stop(HANDED_BACK, [f"land: {branch} moved after the judge passed: relay land {branch} again"])
        done = subprocess.run(["git", "-C", main, "merge", "--ff-only", branch], capture_output=True, text=True)
        if done.returncode == 0:
            return True
        if _sha(main, ref) != base:
            return False
        files = blocking(main, branch)
        if files:
            raise Stop(DIRTY, _dirty_lines(files, branch))
        lock_file = os.path.join(_common_dir(main), "index.lock")
        if os.path.exists(lock_file):
            if attempt + 1 < ff_tries:
                notify(f"another git command holds index.lock; trying again (try {attempt + 2} of {ff_tries})")
                time.sleep(FF_LOCK_WAIT_S)
            continue
        reason = (done.stderr.strip().splitlines() or done.stdout.strip().splitlines() or ["git gave no reason"])[-1]
        raise Stop(REFUSED, [f"land: the fast-forward of {default} to {branch} was refused: {reason}"])
    raise Stop(HANDED_BACK, [f"land: another git command holds {os.path.join(_common_dir(main), 'index.lock')}: relay land {branch} again"])


def _close_features(main: str) -> list[str]:
    """Close the feature items of landed branches with the landed sha (a fix is closed by the cycle's --test)."""
    try:
        import relay_lanes
        return relay_lanes.close_landed(main)
    except Exception as exc:        # the landing already happened: a queue problem is a line, never a lost done event
        return [f"land: the landing happened, but the queue could not be updated: {exc}"]


def _landed(main: str, default: str, branch: str, stats: Event, started: float) -> Result:
    stats.sha = _sha(main, "refs/heads/" + default)
    lines: list[str] = []
    units = _units(main, stats.before, stats.sha, branch)
    try:
        done = subprocess.run([sys.executable, "-I", HOOK, "landed", main, branch], capture_output=True, text=True, timeout=JUDGE_TIMEOUT_S)
        lines = done.stdout.splitlines()
        if done.returncode != 0:
            lines.append(f"land: {branch} landed, but the cleanup of its worktree and branch failed (exit {done.returncode}): "
                         f"{(done.stderr.strip().splitlines() or ['no reason given'])[-1]}")
    except subprocess.TimeoutExpired:
        lines.append(f"land: {branch} landed, but the cleanup of its worktree and branch did not finish in {JUDGE_TIMEOUT_S} s")
    closed = _close_features(main)
    how = f"gate {stats.gate_seconds / 60:.1f} min" if stats.gates_run else "gate reused: only queue records or the handover came in"
    return Result(LANDED, [f"landed {branch} on {default} at {stats.sha[:12]} ({how})", *lines, *closed], units)


def _units(main: str, before: Optional[str], head: Optional[str] = None, branch: Optional[str] = None) -> list[tuple[str, str]]:
    """The queue items this landing brought in, asked before the cleanup removes their branches (none for a rider with no item)."""
    try:
        import relay_metrics
        return relay_metrics.landed_units(main, before, head, branch)
    except Exception:            # the record is optional: a queue problem is reported by _close_features
        return []


def note_held(main: str, waits: list[Any]) -> None:
    """Record the "held at start" events (the start counter): one per (slug, holder) pair, never twice. `waits` are
    relay_lanes.Wait values (the holder is the running branch, or the pick of the same call)."""
    seen = {(e.slug, e.holder) for e in read_events(main)[0] if e.kind == "held"}
    for wait in waits:
        holder_name = wait.branch or (wait.pick or "")
        if (wait.slug, holder_name) not in seen:
            record(main, Event("held", now(), slug=wait.slug, file=wait.file, holder=holder_name))
            seen.add((wait.slug, holder_name))
