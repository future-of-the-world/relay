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
import datetime as dt
from dataclasses import dataclass, field

import relay_transcripts

WORKTREE = re.compile(r"\.worktrees/([A-Za-z0-9._-]+)")
WORKTREE_PATH = re.compile(r"(/[^\s\"'`]*?)/\.worktrees/([A-Za-z0-9._-]+)")
WORKTREE_LINE = re.compile(r"Worktree:\s*(\S+)")
TEXT_PLACES = ("agents/", "skills/", "roles/", "rules/")     # a change touching these is checked by a paid run
BUILD_SUFFIX = "worker"       # `delegate:worker`, `ng-worker`, `worker`: the agents that build


@dataclass(frozen=True)
class AgentRow:
    change: str        # the worktree folder name, `wt/` and `.worktrees/` stripped
    kind: str          # the agent type, e.g. `delegate:worker`
    seconds: float
    start: str = field(default="", compare=False)   # when the agent began (ISO), to tell two changes that reused one worktree name apart


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


def _first_cwd_and_prompt(path: str) -> tuple[str, str]:
    """The first working folder and the text of the first user message of a transcript ("" when absent)."""
    cwd, prompt = "", ""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if not cwd and isinstance(entry.get("cwd"), str):
                    cwd = entry["cwd"]
                if not prompt and entry.get("type") == "user":
                    content = (entry.get("message") or {}).get("content")
                    if isinstance(content, list):
                        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                    prompt = content if isinstance(content, str) else ""
                if cwd and prompt:
                    break
    except OSError:
        pass
    return cwd, prompt


def _under(root: str | None, base: str) -> bool:
    return root is None or base in {root, os.path.realpath(root)} or os.path.realpath(base) == os.path.realpath(root)


def _worktree_in(text: str, root: str | None) -> str | None:
    for found in WORKTREE_PATH.finditer(text or ""):
        if _under(root, found.group(1)):
            return found.group(2)
    return None


def change_of(cwd: str, prompt: str, root: str | None = None) -> str | None:
    """The change an agent worked for: the worktree its working folder lies in, else the one its brief names (the `Worktree:` line first,
    then the first `.worktrees/<name>` path) - agents run with `git -C` from the primary checkout have only the brief to say it.
    With `root`, only worktrees under `<root>/.worktrees/` count."""
    if root is None and (name := worktree_of(cwd)):
        return name
    if (name := _worktree_in(cwd, root)):
        return name
    for line in WORKTREE_LINE.finditer(prompt or ""):
        if (name := _worktree_in(line.group(1), root)):
            return name
    return _worktree_in(prompt, root) or (worktree_of(prompt) if root is None else None)


def agent_rows(projects_dir: str, root: str | None = None) -> list[AgentRow]:
    """One row per subagent transcript under `projects_dir/*/*/subagents/` that worked for a change, sorted for a stable result.
    With `root` (the repo folder) only the project folders of that repo and its worktrees are read and only its worktrees count."""
    rows = []
    prefix = "*"
    if root is not None:
        prefix = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(root)) + "*"
    for path in sorted(glob.glob(os.path.join(projects_dir, prefix, "*", "subagents", "agent-*.jsonl"))):
        cwd, prompt = _first_cwd_and_prompt(path)
        change = change_of(cwd, prompt, root)
        if change is None:
            continue
        trace = relay_transcripts.read_trace(path, kind="agent")
        meta = relay_transcripts.agent_meta(path)
        rows.append(AgentRow(change, str(meta.get("agentType") or meta.get("agent_type") or ""), relay_transcripts.duration_s(trace), trace.started))
    return rows


def _is_build(kind: str) -> bool:
    return kind.rsplit(":", 1)[-1].endswith(BUILD_SUFFIX)


def by_change(rows: list[AgentRow]) -> dict[str, Measured]:
    out: dict[str, Measured] = {}
    for name in sorted({r.change for r in rows}):
        mine = [r for r in rows if r.change == name]
        out[name] = Measured(name, sum(r.seconds for r in mine) / 60, sum(r.seconds for r in mine if _is_build(r.kind)) / 60, len(mine))
    return out


def _when(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def measure_item(rows: list[AgentRow], item: dict) -> Measured | None:
    """The agents of the item's worktree (`taken_by` is `wt/<name>`) that began between its taken_at and closed_at; None when none did,
    so two changes that reused one worktree name are not summed into each other."""
    if not item.get("taken_by") or not item.get("closed_at"):
        return None
    name = str(item["taken_by"]).removeprefix("wt/")
    lo, hi = _when(item.get("taken_at") or ""), _when(item["closed_at"])
    mine = []
    for r in rows:
        if r.change != name:
            continue
        at = _when(r.start)
        if at is None or (lo and at < lo) or (hi and at > hi):
            continue
        mine.append(r)
    if not mine:
        return None
    return Measured(name, sum(r.seconds for r in mine) / 60, sum(r.seconds for r in mine if _is_build(r.kind)) / 60, len(mine))


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
    try:
        a = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((b - a).total_seconds() / 60)


def compare_lines(items: list[dict], measured: dict[str, Measured]) -> list[str]:
    """For each closed, well-formed item that a measured change belongs to (`measured` is keyed by item slug): the estimate beside the agent
    minutes and the wall minutes (taken to closed). Sorted by close time; an item with no transcripts is left out, not shown as 0."""
    rows = []
    for item in items:
        if item.get("problems") or not item.get("closed_at") or not item.get("taken_by"):
            continue
        change = measured.get(item["slug"])
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
