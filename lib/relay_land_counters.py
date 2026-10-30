"""The landing counters of `relay land --stats`: computed from the landing events and from git, never stored.
(Moved out of relay_land.py, which holds the landing itself.)"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import relay_git
import relay_inert
from relay_land import CONFLICT, LANDED, Event, read_events

LABELS = {
    "landings": "code landings on the default branch",
    "all": "all gate logs per code landing",
    "take": "take gates per code landing",
}
WAIT_S = 5.0          # a lander whose lock came later than this after it asked "waited behind another"


def _when(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"cannot read the date {text!r}: write it as 2026-10-24 or 2026-10-28T08:53")
    return stamp.timestamp()


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def _fmt(value: float) -> str:
    return f"{value:.1f}"


def code_landings(main: str, default: str, since: Optional[str], until: Optional[str]) -> list[tuple[str, str]]:
    """(before, after) of each fast-forward of the default branch in the window (the reflog entries `merge ...: Fast-forward`)
    that changed a non-inert file."""
    low, high = _when(since), _when(until)
    rc, out = relay_git.git(main, "reflog", "show", "--format=%H%x09%ct%x09%gs", f"refs/heads/{default}", "-n", "100000")
    entries = [l.split("\t", 2) for l in out.splitlines() if l.count("\t") == 2] if rc == 0 else []
    found = []
    for i, (new, stamp, subject) in enumerate(entries[:-1]):
        old = entries[i + 1][0]
        if not (subject.startswith("merge ") and subject.endswith("Fast-forward")):
            continue
        if (low is not None and int(stamp) < low) or (high is not None and int(stamp) > high):
            continue
        if relay_inert.changed(main, old, new):
            found.append((old, new))
    return found


def gate_counts(main: str, spans: list[tuple[str, str]]) -> tuple[int, int, int]:
    """(all Mac gate logs, take gates, remote gate logs) in the spans: a take gate is a Mac gate log whose head is a merge commit."""
    every = takes = remote = 0
    for old, new in spans:
        rc, out = relay_git.git(main, "log", "--format=%s", f"{old}..{new}")
        for subject in out.splitlines() if rc == 0 else []:
            if subject.startswith("relay: remote gate of "):
                remote += 1
            elif subject.startswith("relay: gate of "):
                every += 1
                head = subject[len("relay: gate of "):].strip()
                rc, parents = relay_git.git(main, "rev-list", "--parents", "-n", "1", head)
                if rc == 0 and len(parents.split()) > 2:
                    takes += 1
    return every, takes, remote


@dataclass
class Lander:
    branch: str
    pid: int
    asked: float
    locked: Optional[float] = None
    done: Optional[Event] = None
    done_at: Optional[float] = None


def landers(events: list[Event]) -> list[Lander]:
    """One Lander per `asked` event, joined with the next `locked` and `done` events of the same (pid, branch)."""
    out: list[Lander] = []
    for event in events:
        stamp = datetime.fromisoformat(event.ts).timestamp()
        if event.kind == "asked":
            out.append(Lander(event.branch, event.pid, stamp))
            continue
        mine = [l for l in out if l.pid == event.pid and l.branch == event.branch and l.done is None]
        if not mine or event.kind not in ("locked", "done"):
            continue
        if event.kind == "locked" and mine[-1].locked is None:
            mine[-1].locked = stamp
        elif event.kind == "done":
            mine[-1].done, mine[-1].done_at = event, stamp
    return out


def ready_to_landing(main: str, lander: Lander) -> Optional[float]:
    """Seconds from the branch's newest `relay: check of` commit (inside the landed span) to the landing."""
    done = lander.done
    if done is None or done.outcome != LANDED or not done.sha or not done.before or lander.done_at is None:
        return None
    rc, out = relay_git.git(main, "log", "--format=%ct%x09%s", f"{done.before}..{done.sha}")
    for line in out.splitlines() if rc == 0 else []:
        stamp, _, subject = line.partition("\t")
        if subject.startswith("relay: check of ") and stamp.isdigit():
            return max(0.0, lander.done_at - int(stamp))
    return None


def moments(all_landers: list[Lander]) -> list[tuple[str, int, float]]:
    """The landing counter: each lock passed to lander L while at least one other had asked and was not yet locked (L and that
    one are two landings at once, where a train would have formed), as (branch of L, how many waited, the minutes L held the lock)."""
    found = []
    for lander in all_landers:
        if lander.locked is None:
            continue
        waiting = [o for o in all_landers if o is not lander and o.asked < lander.locked and (o.locked is None or o.locked > lander.locked)]
        if len(waiting) >= 1:
            held = (lander.done_at - lander.locked) / 60 if lander.done_at is not None else 0.0
            found.append((lander.branch, len(waiting), held))
    return found


def stats(repo: str, since: Optional[str], until: Optional[str]) -> list[str]:
    """The lines of `relay land --stats`: the gate measures from git (the same function for any window, so the baseline and the
    new numbers are one measure), then the counters from the events."""
    import relay_queue
    main, default = relay_queue._context(repo)
    spans = code_landings(main, default, since, until)
    every, takes, remote = gate_counts(main, spans)
    n = len(spans)
    lines = [f"{LABELS['landings']}: {n}",
             f"{LABELS['all']}: {_fmt(every / n) if n else 'none'} ({every} gate logs)",
             f"{LABELS['take']}: {_fmt(takes / n) if n else 'none'} ({takes} take gates)",
             f"remote gate logs: {remote}"]
    events, unreadable = read_events(main)
    low, high = _when(since), _when(until)
    events = [e for e in events if (low is None or datetime.fromisoformat(e.ts).timestamp() >= low) and (high is None or datetime.fromisoformat(e.ts).timestamp() <= high)]
    everyone = landers(events)
    done = [l for l in everyone if l.done is not None]
    landed = [l for l in done if l.done and l.done.outcome == LANDED]
    lines.append(f"landings by relay land: {len(landed)}")
    lines.append(f"gates relay land ran: {sum(l.done.gates_run for l in done if l.done)}")
    lines.append(f"gates reused (inert takes): {sum(1 for l in landed if l.done and l.done.gates_run == 0)}")
    outcomes = sorted({l.done.outcome for l in done if l.done})
    lines.append("outcomes: " + (", ".join(f"{o} {sum(1 for l in done if l.done and l.done.outcome == o)}" for o in outcomes) or "none"))
    lines.append(f"conflicts (each one a fix unit): {sum(1 for l in done if l.done and l.done.outcome == CONFLICT)}")
    lines.append("re-checks by agents: 0")
    ready = [r for r in (ready_to_landing(main, l) for l in landed) if r is not None]
    lines.append("ready to landing, minutes p50 / p90: " + (f"{_fmt(_percentile(ready, 0.5) / 60)} / {_fmt(_percentile(ready, 0.9) / 60)} (n={len(ready)})" if ready else "none"))
    waits = [(l.locked - l.asked) for l in everyone if l.locked is not None]
    lines.append(f"landers that waited behind another: {sum(1 for w in waits if w > WAIT_S)}; longest wait minutes: {_fmt(max(waits) / 60) if waits else 'none'}")
    found = moments(everyone)
    lines.append(f"landing counter, moments with 2+ waiting: {len(found)}" + "".join(f"; {b}: {w} waited behind it {_fmt(m)} min" for b, w, m in found))
    first: dict[str, Event] = {}
    for event in events:
        if event.kind == "held" and event.slug not in first:
            first[event.slug] = event
    extra = []
    try:
        taken = {i.get("slug"): i.get("taken_at") for i in relay_queue.read_queue(main, closed=True)}
    except relay_queue.Refused:
        taken = {}
    for slug, event in sorted(first.items()):
        try:
            late = (datetime.fromisoformat(str(taken.get(slug))).timestamp() - datetime.fromisoformat(event.ts).timestamp()) / 60
            extra.append(f"{slug}: {_fmt(max(0.0, late))} min")
        except ValueError:
            extra.append(f"{slug}: not taken yet")
    lines.append(f"start counter, items held at start: {len(first)}" + "".join(f"; {e}" for e in extra))
    if unreadable:
        lines.append(f"unreadable event lines: {unreadable}")
    return lines
