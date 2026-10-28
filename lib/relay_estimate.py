"""What a change really cost, measured from agent transcripts, and the time estimate built on it.

Derived data: nothing here is stored. A change's agent minutes are the summed durations of the subagents that ran in its worktree
(`.worktrees/<name>`, the agent's own working folder); its build minutes are those of the `worker` agents among them. The estimate
of a new item is the median fixed cycle of past changes (everything but the build: gates, review, checks, queue close) plus the median
build part, plus the paid run's wall minutes when the change edits agent, skill, role or rule texts."""

import glob
import json
import os
import re
import statistics
from dataclasses import dataclass

import relay_transcripts

WORKTREE = re.compile(r"\.worktrees/([A-Za-z0-9._-]+)")
TEXT_PLACES = ("agents/", "skills/", "roles/", "rules/")     # a change touching these is checked by a paid run
BUILD_SUFFIX = "worker"       # `delegate:worker`, `ng-worker`, `worker`: the agents that build


@dataclass(frozen=True)
class AgentRow:
    change: str        # the worktree folder name, `wt/` and `.worktrees/` stripped
    kind: str          # the agent type, e.g. `delegate:worker`
    seconds: float


@dataclass(frozen=True)
class Measured:
    change: str
    agent_min: float
    build_min: float
    agents: int


def worktree_of(cwd: str) -> str | None:
    """The worktree folder name inside a working directory (`/x/.worktrees/foo/lib` -> `foo`); None outside any worktree."""
    found = WORKTREE.search(cwd or "")
    return found.group(1) if found else None


def _first_cwd(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                cwd = entry.get("cwd") if isinstance(entry, dict) else None
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        pass
    return ""


def agent_rows(projects_dir: str) -> list[AgentRow]:
    """One row per subagent transcript under `projects_dir/*/*/subagents/` that ran in a worktree, sorted for a stable result."""
    rows = []
    for path in sorted(glob.glob(os.path.join(projects_dir, "*", "*", "subagents", "agent-*.jsonl"))):
        change = worktree_of(_first_cwd(path))
        if change is None:
            continue
        trace = relay_transcripts.read_trace(path, kind="agent")
        meta = relay_transcripts.agent_meta(path)
        rows.append(AgentRow(change, str(meta.get("agentType") or meta.get("agent_type") or ""), relay_transcripts.duration_s(trace)))
    return rows


def _is_build(kind: str) -> bool:
    return kind.rsplit(":", 1)[-1].endswith(BUILD_SUFFIX)


def by_change(rows: list[AgentRow]) -> dict[str, Measured]:
    out: dict[str, Measured] = {}
    for name in sorted({r.change for r in rows}):
        mine = [r for r in rows if r.change == name]
        out[name] = Measured(name, sum(r.seconds for r in mine) / 60, sum(r.seconds for r in mine if _is_build(r.kind)) / 60, len(mine))
    return out


def edits_texts(places: list[str]) -> bool:
    """Whether any `where` place (`path`, `path:N` ...) lies in an agent, skill, role or rule text folder (also under `plugins/*/`)."""
    for place in places:
        path = place.split()[0] if place.split() else ""
        parts = path.split("/")
        tails = ["/".join(parts[i:]) for i in range(len(parts))]
        if any(t.startswith(TEXT_PLACES) for t in tails) and not path.startswith(("tests/", "lib/")):
            return True
    return False


def estimate(history: list[Measured], paid_run_min: float = 0.0) -> int | None:
    """Whole minutes: median fixed cycle + median build part of `history` + `paid_run_min`; None with no history (no guess is made)."""
    if not history:
        return None
    fixed = statistics.median(m.agent_min - m.build_min for m in history)
    build = statistics.median(m.build_min for m in history)
    return round(fixed + build + paid_run_min)


def _minutes_between(start: str, end: str) -> int | None:
    import datetime as dt
    try:
        a = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((b - a).total_seconds() / 60)


def compare_lines(items: list[dict], measured: dict[str, Measured]) -> list[str]:
    """For each closed, well-formed item that a measured change belongs to (`taken_by` is `wt/<worktree>`): the estimate beside the agent
    minutes and the wall minutes (taken to closed). Sorted by close time; an item with no transcripts is left out, not shown as 0."""
    rows = []
    for item in items:
        if item.get("problems") or not item.get("closed_at") or not item.get("taken_by"):
            continue
        change = measured.get(str(item["taken_by"]).removeprefix("wt/"))
        if change is None:
            continue
        wall = _minutes_between(item["taken_at"], item["closed_at"]) if item.get("taken_at") else None
        rows.append((item["closed_at"], item["slug"], item["time"], round(change.agent_min), round(change.build_min), wall))
    rows.sort()
    out = ["estimate and actual, minutes: estimate, agents (of which build), wall (taken to closed)"]
    for _, slug, est, agent, build, wall in rows:
        out.append(f"  {est:>4} est  {agent:>4} agents ({build} build)  {'?' if wall is None else wall:>5} wall  {slug}")
    return out


def next_estimate_text(history: list[Measured]) -> str:
    """The estimate for a new item, with its parts; says so when there is nothing measured to base it on."""
    value = estimate(history)
    if value is None:
        return "no measured change yet: no estimate"
    return (f"estimate for a new item: {value}m (median fixed cycle plus median build part of {len(history)} changes); "
            "add the paid run's wall minutes when it edits agent, skill, role or rule texts")
