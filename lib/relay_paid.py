"""The paid run's state, derived from dated records (design: the change-cycle script lands a ready change itself, 5.4).

Three dated facts, none of them a process lock: `started` (written by bin/ci when the full run reaches the plugin evals on
the default branch's head), the eval record that bin/eval-record stores (head, startedAt, durationSeconds, the green verdict),
and `synced` (written by `relay sync` after a write that was not held). This module owns the file of the first and last,
`<git common dir>/relay-paid/events.jsonl`, and computes the state from them when asked (`bin/paid-cost state`).
Tests: tests/test_relay_paid.py
"""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from importlib.machinery import SourceFileLoader
import importlib.util
from typing import Any, Callable, Optional

import relay_git

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
KINDS = ("started", "synced")
FREE, GOING, STOPPED, WAITS_SYNC, RED = "free", "going", "stopped", "waits_sync", "red"


@dataclass
class PaidEvent:
    kind: str               # started | synced
    ts: str                 # ISO 8601 UTC
    head: str = ""          # the default branch's head the run (started) or the settings (synced) belong to
    pid: int = 0            # started: the process of the full run


@dataclass
class State:
    name: str               # free | going | stopped | waits_sync | red
    since: str              # the ts of the record that decided it, "" for free
    line: str               # one plain line naming what to do


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_event(line: str) -> Optional[PaidEvent]:
    """The one checking parser: a PaidEvent, or None for a line that is not one."""
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
        if key not in ("kind", "ts", "head", "pid"):
            return None
        if key == "pid" and (isinstance(value, bool) or not isinstance(value, int)):
            return None
        if key != "pid" and not isinstance(value, str):
            return None
    return PaidEvent(**data)


def _common_dir(repo: str) -> str:
    rc, out = relay_git.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not out:
        raise ValueError(f"cannot find the git directory of {repo}")
    return out


def events_path(repo: str) -> str:
    return os.path.join(_common_dir(repo), "relay-paid", "events.jsonl")


def record(repo: str, event: PaidEvent) -> None:
    """The one writer: append the event as a line under an exclusive lock."""
    path = events_path(repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps({k: v for k, v in asdict(event).items() if v not in ("", 0) or k in ("kind", "ts")}) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(line)
        handle.flush()


def read_events(repo: str) -> list[PaidEvent]:
    try:
        with open(events_path(repo), encoding="utf-8") as handle:
            lines = [l for l in handle.read().splitlines() if l.strip()]
    except OSError:
        return []
    return [e for e in (parse_event(l) for l in lines) if e is not None]


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _when(text: str) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def real_judge(data: dict[str, Any]) -> bool:
    """bin/eval-record's own verdict (is_green)."""
    loader = SourceFileLoader("eval_record", os.path.join(ROOT, "bin", "eval-record"))
    spec = importlib.util.spec_from_loader("eval_record", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return bool(module.is_green(data))


def evals_folder(repo: str, home: Optional[str] = None) -> str:
    base = os.path.expanduser(home or os.environ.get("RELAY_HOME") or "~/.relay")
    return os.path.join(base, "evals", os.path.basename(os.path.dirname(_common_dir(repo))))


def _record_of(folder: str, default: str, started: PaidEvent) -> Optional[tuple[datetime, dict[str, Any]]]:
    """(end time, record) of the newest eval record of the run `started` opened: same head and branch, begun after it."""
    begun = _when(started.ts)
    found: list[tuple[datetime, dict[str, Any]]] = []
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return None
    for name in names:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                data = json.load(handle)
            start = _when(data["startedAt"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if not isinstance(data, dict) or start is None or begun is None or data.get("head") != started.head or data.get("branch") != default or start < begun:
            continue
        seconds = data.get("durationSeconds")
        end = start + timedelta(seconds=seconds) if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else start
        found.append((end, data))
    return max(found, key=lambda f: f[0]) if found else None


def state(repo: str, home: Optional[str] = None, alive: Callable[[int], bool] = pid_alive,
          judge: Callable[[dict[str, Any]], bool] = real_judge) -> State:
    """The paid run's state, computed from the records (table of design 5.4)."""
    events = read_events(repo)
    starts = [e for e in events if e.kind == "started"]
    if not starts:
        return State(FREE, "", "no paid run is going")
    started = starts[-1]
    default = relay_git.default_branch(repo) or ""
    found = _record_of(evals_folder(repo, home), default, started)
    if found is None:
        if alive(started.pid):
            return State(GOING, started.ts, f"a paid run has been going since {started.ts}")
        return State(STOPPED, started.ts, f"the paid run begun {started.ts} ended without a verdict: start the paid run again")
    end, data = found
    if not judge(data):
        return State(RED, started.ts, f"the paid run begun {started.ts} was red")
    synced = [e for e in events if e.kind == "synced" and (_when(e.ts) or end) >= end]
    if synced:
        return State(FREE, synced[-1].ts, "no paid run is going")
    return State(WAITS_SYNC, started.ts, f"the paid run begun {started.ts} is green: run relay sync")
