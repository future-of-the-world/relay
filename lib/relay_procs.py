"""Reading and stopping processes: the one parser of `ps`, the one reader of working folders, and the one stop.

The gate's sweep of leftovers (lib/relay_gate.py), the gate's reclaim of a killed gate's command, and the test runners'
leak scan (tests/leaked_gates.py) all read the process table here, so it is parsed once, one way. Standard library only.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

STOP_GRACE = 10.0       # seconds a process has to end after SIGTERM before it is killed (a gate ends its command's group in that time)
PS_TIMEOUT = 600        # seconds `ps` may take (master raised these from 30 to 600: a loaded machine answers slowly)
LSOF_TIMEOUT = 600      # seconds `lsof` may take (as PS_TIMEOUT)


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    started: float      # seconds since the epoch (from ps's lstart, local time)
    command: str


def parse_ps(text: str) -> List[Proc]:
    """The records of `ps -axo pid=,ppid=,pgid=,lstart=,command=` output; a line of another shape is skipped."""
    procs: List[Proc] = []
    for line in text.splitlines():
        words = line.split(None, 8)      # pid ppid pgid, then lstart's five words ("Thu Oct 29 09:05:12 2026"), then the command
        if len(words) < 8 or not all(word.isdigit() for word in words[:3]):
            continue
        try:
            started = time.mktime(time.strptime(" ".join(words[3:8]), "%a %b %d %H:%M:%S %Y"))
        except (ValueError, OverflowError):
            continue
        procs.append(Proc(int(words[0]), int(words[1]), int(words[2]), started, words[8].strip() if len(words) > 8 else ""))
    return procs


def read_procs() -> List[Proc]:
    """Every process `ps` shows. Raises OSError or subprocess.SubprocessError when ps cannot run: "nobody is there" and "could not look" differ."""
    env = dict(os.environ, LC_ALL="C")      # lstart's words are English month and day names
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,lstart=,command="], capture_output=True, text=True, timeout=PS_TIMEOUT, env=env).stdout
    return parse_ps(out)


def ancestors(procs: Iterable[Proc], pid: int) -> set:
    """`pid` and its parents, from the records given."""
    parent = {p.pid: p.ppid for p in procs}
    chain = {pid}
    while parent.get(pid, 0) > 1 and parent[pid] not in chain:
        pid = parent[pid]
        chain.add(pid)
    return chain


def working_folders(pids: Optional[Sequence[int]] = None) -> Optional[Dict[int, str]]:
    """pid -> resolved working folder, for `pids` (every process we can read when None): /proc where it exists, else one `lsof` call.
    None when lsof could not run or timed out."""
    found: Dict[int, str] = {}
    if os.path.isdir("/proc/self"):
        names = [str(p) for p in pids] if pids is not None else [n for n in os.listdir("/proc") if n.isdigit()]
        for name in names:
            try:
                found[int(name)] = os.path.realpath(os.readlink("/proc/%s/cwd" % name))
            except OSError:
                pass
        return found
    if pids is not None and not pids:
        return found
    cmd = ["lsof", "-a", "-d", "cwd", "-Fpn"] + (["-p", ",".join(str(p) for p in pids)] if pids is not None else [])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=LSOF_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = 0
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            found[pid] = os.path.realpath(line[1:])
    return found


def holders_of(path: str) -> Optional[List[int]]:
    """Pids that have the file `path` open (one `lsof -t`); None when lsof could not run."""
    try:
        out = subprocess.run(["lsof", "-t", "--", path], capture_output=True, text=True, timeout=LSOF_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [int(word) for word in out.split() if word.isdigit()]


def open_names(pids: Sequence[int]) -> Optional[Dict[int, List[str]]]:
    """pid -> the names of the files it has open (`lsof -a -p <pids> -Fn`); None when lsof could not run."""
    names: Dict[int, List[str]] = {}
    if not pids:
        return names
    try:
        out = subprocess.run(["lsof", "-a", "-p", ",".join(str(p) for p in pids), "-Fpn"], capture_output=True, text=True, timeout=LSOF_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = 0
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            names.setdefault(pid, []).append(line[1:])
    return names


def is_alive(pid: int) -> bool:
    """Whether the process exists; a zombie counts as gone."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    try:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=600).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(state) and not state.startswith("Z")


SIGNAL_LOG_ENV = "RELAY_SIGNAL_LOG"      # the shared log of every stop relay sends (a gate's command inherits it)


def signal_log() -> str:
    """The shared log of signals relay sends: `$RELAY_SIGNAL_LOG`, else `$RELAY_HOME/signals.log` (default ~/.relay)."""
    return os.environ.get(SIGNAL_LOG_ENV) or os.path.join(os.path.expanduser(os.environ.get("RELAY_HOME") or "~/.relay"), "signals.log")


def record_sent(pid: int, group: bool, sig: int, reason: str, now: Optional[float] = None) -> None:
    """Append one line to the shared signal log: when, the sender (this process), the signal, the target and why. The log is
    best effort: a log that cannot be written never stops the signal."""
    name = signal.Signals(sig).name if sig in {int(s) for s in signal.Signals} else "signal %d" % sig
    line = "t=%.3f relay pid %d sent %s to %s %d: %s\n" % (time.time() if now is None else now, os.getpid(), name, "group" if group else "pid", pid, reason or "no reason given")
    try:
        path = signal_log()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def sent_by_relay(number: int, since: float) -> Optional[str]:
    """The newest line of the signal log from `since` on (epoch seconds) that sent a signal to pid or group `number`, else None."""
    try:
        with open(signal_log(), encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    found = None
    for line in lines:
        m = re.match(r"t=([0-9.]+) (relay pid .* sent \S+ to (?:pid|group) (\d+): .*)", line)
        if m and int(m.group(3)) == number and float(m.group(1)) >= since:
            found = m.group(2)
    return found


def send(pid: int, group: bool, sig: int, reason: str = "") -> None:
    """Signal the process, or its whole group, and record it in the signal log; a process that is gone or not ours is not an error."""
    record_sent(pid, group, sig, reason)
    try:
        (os.killpg if group else os.kill)(pid, sig)
    except OSError:
        pass


def stop(targets: Sequence[Tuple[int, bool]], reason: str = "") -> List[Tuple[int, bool]]:
    """Stop each (pid, whole group?): SIGTERM, then SIGKILL for those still there after STOP_GRACE. Returns the targets that needed SIGKILL."""
    for pid, group in targets:
        send(pid, group, signal.SIGTERM, reason)
    deadline = time.monotonic() + STOP_GRACE
    pending = list(targets)
    while pending and time.monotonic() < deadline:
        pending = [t for t in pending if _still(t)]
        if pending:
            time.sleep(0.05)
    pending = [t for t in pending if _still(t)]
    for pid, group in pending:
        send(pid, group, signal.SIGKILL, reason + " (still there after SIGTERM)")
    return pending


def _still(target: Tuple[int, bool]) -> bool:
    pid, group = target
    if not group:
        return is_alive(pid)
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True
