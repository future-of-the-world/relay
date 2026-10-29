"""What a change really cost, measured from agent transcripts, and the time estimate built on it.

Derived data: nothing here is stored. A change's agent minutes are the summed durations of the subagents that ran in its worktree
(`.worktrees/<name>`, the agent's own working folder); its build minutes are those of the `worker` agents among them. The estimate
of a new item is the median fixed cycle of past changes (everything but the build: gates, review, checks, queue close) plus the median
build part. The paid run is not part of it: one paid run checks a wave of changes, so it is shown beside the estimate as its own line
(`paid_run_text`), not added to any item."""

import glob
import json
import os
import re
import statistics
import datetime as dt
from dataclasses import dataclass, field

import relay_config
import relay_transcripts

DEFAULT_FOLDER = ".worktrees"
WORKTREE_LINE = re.compile(r"Worktree:\s*(\S+)")
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


def worktree_folder(root: str | None) -> str:
    """The worktrees folder of the project at `root` as a full path: kit.toml `project.worktrees` (relative to `root`, or absolute),
    else `<root>/.worktrees` (also when the file is unreadable). Without `root`, the bare default name."""
    if root is None:
        return DEFAULT_FOLDER
    try:
        return relay_config.worktrees_folder(root)
    except (OSError, ValueError):
        return os.path.join(root, DEFAULT_FOLDER)


def _own_folders(root: str | None) -> list[str]:
    """The project's own worktrees folder as full paths (as written and with links resolved), unless it is the default one."""
    if root is None:
        return []
    folder = worktree_folder(root)
    if os.path.basename(folder) == DEFAULT_FOLDER and os.path.dirname(folder) in {root, os.path.realpath(root)}:
        return []
    return list(dict.fromkeys([folder, os.path.realpath(folder)]))


def worktree_of(cwd: str) -> str | None:
    """The worktree folder name inside a working directory (`/x/.worktrees/foo/lib` -> `foo`); None outside any worktree.
    The folder must be a whole path part: `/x/my.worktrees/foo` is not one."""
    found = re.search(rf"(?:^|/){re.escape(DEFAULT_FOLDER)}/([A-Za-z0-9._-]+)", cwd or "")
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
    pattern = re.compile(rf"(/[^\s\"'`]*?)/{re.escape(DEFAULT_FOLDER)}/([A-Za-z0-9._-]+)")
    own = [re.compile(rf"(?<![^\s\"'`(]){re.escape(f)}/([A-Za-z0-9._-]+)") for f in _own_folders(root)]
    hits = [(f.start(), f.group(2), f.group(1)) for f in pattern.finditer(text or "")]
    hits += [(f.start(), f.group(1), None) for rx in own for f in rx.finditer(text or "")]
    for _, name, base in sorted(hits, key=lambda h: h[0]):
        if base is None or _under(root, base):
            return name
    return None


def change_of(cwd: str, prompt: str, root: str | None = None, brief_first: bool = False) -> str | None:
    """The change an agent worked for: the worktree its working folder lies in, else the one its brief names (the `Worktree:` line first,
    then the first `.worktrees/<name>` path) - agents run with `git -C` from the primary checkout have only the brief to say it.
    With `root`, only worktrees under `<root>/.worktrees/` count. `brief_first`: the brief outranks the working folder - a workflow's agents
    start in the folder the workflow was launched from, which is often another change's worktree (journal labels: 75 of 77 such agents
    belong to the change their brief names)."""
    if brief_first and (name := _worktree_in(prompt, root)):
        return name
    if root is None and (name := worktree_of(cwd)):  # no project known: only the default folder
        return name
    if (name := _worktree_in(cwd, root)):
        return name
    for line in WORKTREE_LINE.finditer(prompt or ""):
        if (name := _worktree_in(line.group(1), root)):
            return name
    return _worktree_in(prompt, root) or (worktree_of(prompt) if root is None else None)


BRANCH = re.compile(r"\bwt/([A-Za-z0-9._-]+)")
EARLY = 4      # an agent that was handed a brief file reads it in its first steps: the first user messages and tool results say what it works on


def _block_text(block: object) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    inner = block.get("text") if block.get("type") == "text" else block.get("content") if block.get("type") == "tool_result" else ""
    if isinstance(inner, list):
        return " ".join(_block_text(b) for b in inner)
    return inner if isinstance(inner, str) else ""


def _early_text(path: str) -> str:
    """The text of the first few user entries of a transcript (the prompt and what the agent read first, e.g. its brief file)."""
    out: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "user":
                    continue
                content = (entry.get("message") or {}).get("content")
                out.append(" ".join(_block_text(b) for b in content) if isinstance(content, list) else _block_text(content))
                if len(out) >= EARLY:
                    break
    except OSError:
        pass
    return "\n".join(out)


def _worktree_read(path: str, root: str | None) -> str | None:
    """The change named in what the agent first read (its brief file): a `<root>/.worktrees/<name>` path, else a `wt/<name>` branch."""
    text = _early_text(path)
    if (name := _worktree_in(text, root)):
        return name
    found = BRANCH.search(text)
    return found.group(1) if found else None


def agent_rows(projects_dir: str, root: str | None = None) -> list[AgentRow]:
    """One row per subagent transcript under `projects_dir/*/*/subagents/` that worked for a change, sorted for a stable result.
    With `root` (the repo folder) only the project folders of that repo and its worktrees are read and only its worktrees count."""
    rows = []
    prefix = "*"
    if root is not None:
        prefix = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(root)) + "*"
    sessions = os.path.join(projects_dir, prefix, "*", "subagents")
    # a workflow's agents (gate, review, check, fix of the cycle) live one level deeper: subagents/workflows/<run>/agent-*.jsonl
    paths = glob.glob(os.path.join(sessions, "agent-*.jsonl")) + glob.glob(os.path.join(sessions, "workflows", "*", "agent-*.jsonl"))
    for path in sorted(paths):
        cwd, prompt = _first_cwd_and_prompt(path)
        change = change_of(cwd, prompt, root, brief_first=os.sep + "workflows" + os.sep in path) or _worktree_read(path, root)
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


def measure_item(rows: list[AgentRow], item: dict, items: list[dict] | None = None) -> Measured | None:
    """The agents of the item's worktree (`taken_by` is `wt/<name>`) that began after its taken_at and before the next item taken by the
    same worktree name (`items`) - not before its closed_at: the closing writes come before the last checks, which still run in the worktree.
    None when none did, so two changes that reused one worktree name are not summed into each other."""
    if not item.get("taken_by") or not item.get("closed_at"):
        return None
    name = str(item["taken_by"]).removeprefix("wt/")
    lo = _when(item.get("taken_at") or "")
    later = [t for other in (items or []) if other is not item and other.get("taken_by") == item["taken_by"]
             if (t := _when(other.get("taken_at") or "")) and lo and t > lo]
    hi = min(later) if later else None
    mine = []
    for r in rows:
        if r.change != name:
            continue
        at = _when(r.start)
        if at is None or (lo and at < lo) or (hi and at >= hi):
            continue
        mine.append(r)
    if not mine:
        return None
    return Measured(name, sum(r.seconds for r in mine) / 60, sum(r.seconds for r in mine if _is_build(r.kind)) / 60, len(mine))


def estimate(history: list[Measured]) -> int | None:
    """Whole minutes: median fixed cycle + median build part of `history`; None with no history (no guess is made)."""
    if not history:
        return None
    fixed = statistics.median(m.agent_min - m.build_min for m in history)
    build = statistics.median(m.build_min for m in history)
    return round(fixed + build)


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


def paid_run_text(folder: str) -> str:
    """One line on the paid run of a wave, from the full batches stored in `folder` (`$RELAY_HOME/evals/<repo>/*.json`): the median wall minutes
    and cost. A paid run checks a wave of changes, so it is not added to an item's estimate."""
    minutes, costs = [], []
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                d = json.load(handle)
            seconds, cost = d["durationSeconds"], d["costUsd"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if d.get("partial") is True or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in (seconds, cost)):
            continue
        minutes.append(seconds / 60)
        costs.append(float(cost))
    if not minutes:
        return "paid run of a wave (not part of an item's estimate): not measured yet"
    return (f"paid run of a wave (not part of an item's estimate): median {round(statistics.median(minutes))}m and "
            f"${statistics.median(costs):.2f} over {len(minutes)} full runs")


def next_estimate_text(history: list[Measured]) -> str:
    """The estimate for a new item, with its parts; says so when there is nothing measured to base it on."""
    value = estimate(history)
    if value is None:
        return "no measured change yet: no estimate"
    return f"estimate for a new item: {value}m (median fixed cycle plus median build part of {len(history)} changes)"
