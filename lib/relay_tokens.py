"""The machine-wide pool of test tokens: every test process on one machine runs only while it holds a token.

The pool is N lock files `$RELAY_HOME/test-tokens/token-0 .. token-(N-1)` (OS file locks, so a killed process frees its tokens
by dying). Two kinds: GATE tokens `0 .. R-1` (R = per-gate share x gate slots), kept for gates, and SHARED tokens `R .. N-1`
for everything else (a lane's `relay precheck`, a `pytest` session, a hand-started test run).

A run's BASE tokens are held for the whole run; its EXTRA tokens are held for one test class each.
- A gate takes its share of GATE tokens after its slot and before its command starts (`take_base`, kind GATE).
- A run with no holder above it takes one SHARED token as base (`acquire_run_base`).
- A holder passes its base down in `RELAY_TEST_TOKENS=<count>@<pool folder>`; a run that finds it for its own pool folder
  takes no base token (the jobserver rule "the first job is free"). Relay adds nothing for a project's own gate command:
  what its bin/ci checks and how parallel it runs is the project's choice.
- Extras are taken only if free now (`try_extra`), never of a kind a base waiter is waiting for (waiter files under
  `waiting/`, live while their pid lives), so a released token reaches the waiter, not the releaser.

Settings (files in the pool folder; a value outside its bounds is brought into them with a note):
  count     tokens in all; default the usable CPUs; bounds R+1 .. 4 x CPUs
  per-gate  tokens a gate holds; default 4; bounds 2 .. 2 x the per-run worker ceiling (RELAY_TEST_JOBS, default 4)
  retry     seconds an idle extra waits before it looks again; default 1; bounds 0.2 .. 10
"""

from __future__ import annotations

import fcntl
import itertools
import math
import os
import sys
import time
from typing import IO, Callable, Mapping, NamedTuple, Optional

import relay_config

ENV_HOLD = "RELAY_TEST_TOKENS"       # <count>@<pool folder>, set by a holder for its children
GATE = "gate"
SHARED = "shared"
DEFAULT_PER_GATE = 4
MIN_PER_GATE = 2
DEFAULT_JOBS = 4         # the per-run worker ceiling when RELAY_TEST_JOBS is not set (tests/parallel_unittest.py DEFAULT_JOBS)
DEFAULT_RETRY = 1.0
RETRY_LOW, RETRY_HIGH = 0.2, 10.0
POLL = 0.2               # seconds between looks while a base waiter waits
CPU_FACTOR = 4           # the pool may be at most this many times the usable CPUs
_ids = itertools.count()


class Settings(NamedTuple):
    total: int
    per_gate: int
    slots: int
    retry: float
    notes: tuple[str, ...]

    @property
    def gate_tokens(self) -> int:
        return self.per_gate * self.slots


class Held:
    """Open token files; closing them frees the tokens."""

    def __init__(self, files: Optional[list[IO[str]]] = None) -> None:
        self.files: list[IO[str]] = files if files is not None else []

    def release(self) -> None:
        for handle in self.files:
            handle.close()
        self.files = []

    def __len__(self) -> int:
        return len(self.files)


class RunBase(NamedTuple):
    workers: int      # workers the run may start without asking for more
    passed: bool      # True: a holder above passed the base down, nothing is held here
    held: Held
    home: str
    settings: Settings


def pool_dir(home: str) -> str:
    return os.path.join(home, "test-tokens")


def cpus_from(affinity: int, cpu_max: Optional[str]) -> int:
    """Usable CPUs: the affinity, lowered to ceil(quota / period) when the cgroup `cpu.max` text holds a quota."""
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                quota, period = int(parts[0]), int(parts[1])
            except ValueError:
                quota = period = 0
            if quota > 0 and period > 0:
                return max(1, min(affinity, math.ceil(quota / period)))
    return max(1, affinity)


def usable_cpus() -> int:
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    try:
        with open("/sys/fs/cgroup/cpu.max") as handle:
            text: Optional[str] = handle.read()
    except OSError:
        text = None
    return cpus_from(affinity, text)


def read_setting(path: str, default: float, low: float, high: float, whole: bool = True) -> tuple[float, str]:
    """(value, note) of a setting file: missing or empty gives the default (itself kept inside the bounds); text that is not a
    number gives the default with a note; a number outside low..high is brought into it with a note."""
    default = min(max(default, low), high)
    try:
        with open(path) as handle:
            text = handle.read().strip()
    except FileNotFoundError:
        return default, ""
    except OSError as exc:
        return default, "cannot read %s (%s): using %g" % (path, exc, default)
    if not text:
        return default, ""
    try:
        value = float(text)
    except ValueError:
        return default, "%s holds %r, not a number: using %g" % (path, text, default)
    if not math.isfinite(value) or (whole and value != int(value)):
        return default, "%s holds %r, not a %s: using %g" % (path, text, "whole number" if whole else "number", default)
    clamped = min(max(value, low), high)
    if clamped != value:
        return clamped, "%s holds %g, outside %g..%g: using %g" % (path, value, low, high, clamped)
    return value, ""


def settings(home: str, slots: int, jobs: int = DEFAULT_JOBS, cpus: Optional[int] = None) -> Settings:
    folder = pool_dir(home)
    cpus = cpus or usable_cpus()
    per_gate, note1 = read_setting(os.path.join(folder, "per-gate"), DEFAULT_PER_GATE, MIN_PER_GATE, max(MIN_PER_GATE, 2 * jobs))
    gate_tokens = int(per_gate) * slots
    total, note2 = read_setting(os.path.join(folder, "count"), cpus, gate_tokens + 1, max(CPU_FACTOR * cpus, gate_tokens + 1))
    retry, note3 = read_setting(os.path.join(folder, "retry"), DEFAULT_RETRY, RETRY_LOW, RETRY_HIGH, whole=False)
    return Settings(int(total), int(per_gate), slots, retry, tuple(n for n in (note1, note2, note3) if n))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _indices(st: Settings, kind: str) -> range:
    return range(0, st.gate_tokens) if kind == GATE else range(st.gate_tokens, st.total)


def _try_lock(folder: str, index: int) -> Optional[IO[str]]:
    handle = open(os.path.join(folder, "token-%d" % index), "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _take_any(folder: str, indices: range) -> Optional[IO[str]]:
    for index in indices:
        handle = _try_lock(folder, index)
        if handle is not None:
            return handle
    return None


def waiting_kinds(folder: str) -> set[str]:
    """Kinds some live process is waiting for as base (a waiter file whose pid is dead is removed)."""
    found: set[str] = set()
    waiting = os.path.join(folder, "waiting")
    try:
        names = os.listdir(waiting)
    except OSError:
        return found
    for name in names:
        parts = name.split("-")
        if len(parts) == 3 and parts[1].isdigit():
            if _alive(int(parts[1])):
                found.add(parts[0])
            else:
                try:
                    os.unlink(os.path.join(waiting, name))
                except OSError:
                    pass
    return found


def take_base(home: str, st: Settings, kind: str, count: int, notify: Optional[Callable[[str], None]] = None,
              what: str = "test tokens") -> tuple[Held, float]:
    """Take `count` tokens of `kind`, waiting without a time limit; returns (held, seconds waited). While it waits, a waiter
    file keeps extras from taking this kind. `notify` is called once, when the first look finds nothing free."""
    folder = pool_dir(home)
    os.makedirs(os.path.join(folder, "waiting"), exist_ok=True)
    held = Held()
    started = time.monotonic()
    marker = ""
    try:
        while len(held) < count:
            handle = _take_any(folder, _indices(st, kind))
            if handle is not None:
                held.files.append(handle)
                continue
            if not marker:
                marker = os.path.join(folder, "waiting", "%s-%d-%d" % (kind, os.getpid(), next(_ids)))
                open(marker, "a").close()
                if notify is not None:
                    notify("waiting for %s (all %d busy; $RELAY_HOME/test-tokens/count sets the pool, per-gate the gates' share)"
                           % (what, len(_indices(st, kind))))
            time.sleep(POLL)
    except BaseException:
        held.release()
        raise
    finally:
        if marker:
            try:
                os.unlink(marker)
            except OSError:
                pass
    return held, time.monotonic() - started


def try_extra(home: str, st: Settings, prefer: str = SHARED) -> Optional[Held]:
    """One token that is free now, of a kind nobody waits for as base; None when there is none."""
    folder = pool_dir(home)
    os.makedirs(folder, exist_ok=True)
    blocked = waiting_kinds(folder)
    for kind in (prefer, GATE if prefer == SHARED else SHARED):
        if kind in blocked:
            continue
        handle = _take_any(folder, _indices(st, kind))
        if handle is not None:
            return Held([handle])
    return None


def hold_value(count: int, home: str) -> str:
    return "%d@%s" % (count, os.path.realpath(pool_dir(home)))


def passed_down(environ: Mapping[str, str], home: str) -> int:
    """The base a holder above passed down for this pool folder, else 0 (a value for another pool, or malformed, is ignored)."""
    count, _, folder = environ.get(ENV_HOLD, "").partition("@")
    if count.isdigit() and int(count) > 0 and folder and os.path.realpath(folder) == os.path.realpath(pool_dir(home)):
        return int(count)
    return 0


def jobs_from(environ: Mapping[str, str]) -> int:
    """The per-run worker ceiling: RELAY_TEST_JOBS when it is a whole number of 1 or more, else the default."""
    raw = environ.get("RELAY_TEST_JOBS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_JOBS


def settings_for_run(environ: Mapping[str, str], home: str) -> Settings:
    """The settings as a test run reads them (the gate slot count comes from relay_gate, imported late: it imports this module)."""
    import relay_gate
    try:
        slots = relay_gate.slot_count(home)
    except relay_gate.GateRefused:
        slots = relay_gate.default_slots()
    return settings(home, slots, jobs_from(environ))


def run_home(environ: Mapping[str, str]) -> str:
    return os.path.expanduser(environ["RELAY_HOME"]) if environ.get("RELAY_HOME") else str(relay_config.home_dir())


def acquire_run_base(environ: Mapping[str, str], notify: Optional[Callable[[str], None]] = None) -> RunBase:
    """The base of a test run: the holder's count when one passed it down, else one SHARED token taken here (waiting)."""
    home = run_home(environ)
    st = settings_for_run(environ, home)
    for note in st.notes:
        print("NOTE test tokens: " + note, file=sys.stderr, flush=True)
    given = passed_down(environ, home)
    if given:
        return RunBase(given, True, Held(), home, st)
    held, _ = take_base(home, st, SHARED, 1, notify, "a test token")
    return RunBase(1, False, held, home, st)
