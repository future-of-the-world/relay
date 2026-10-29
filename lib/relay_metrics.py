"""Change records: what git does not hold about a change (its agents, its landing events, its landed range), kept in the repository.

One record is one small JSON file `.relay/changes/<unit>/<key>.json`; this module is the only writer (principle 4). Stage times, counts
and totals are never stored: `summary` and `unit_lines` compute them from the records, the queue and git (principle 3).
Design: relay's scratchpad design "each change records its stage times, cost and coverage", revision 2.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import relay_git
import relay_labels

DIR = ".relay/changes"
KEYS = {"schema", "kind", "unit", "item", "branch", "before", "head", "agents", "land", "front"}
AGENT_KEYS = {"id", "session", "stage", "n", "model", "start", "stop", "requests", "cost_usd"}
LAND_KEYS = {"kind", "at", "gates_run", "gate_seconds", "file", "holder"}
KINDS = ("change", "design", "other", "front")
SETTINGS = {"sweep_quiet_min": (60, 10, 1440)}   # default, lowest, highest
BACKFILL_FROM = "2026-10-27T00:00:00+00:00"
DESIGN_STAGES = ("design", "design review", "design revise")


# ---- the record: one typed shape, one checking parser ----

def parse(text: str) -> dict[str, Any]:
    """The record in `text`; ValueError naming the problem when it is not schema 1 (a key outside the list, such as `duration`, is refused)."""
    try:
        rec = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"not JSON: {exc}")
    if not isinstance(rec, dict) or rec.get("schema") != 1:
        raise ValueError("not a change record of schema 1")
    if set(rec) - KEYS:
        raise ValueError(f"keys outside the schema: {sorted(set(rec) - KEYS)}")
    if rec.get("kind") not in KINDS or not isinstance(rec.get("unit"), str):
        raise ValueError("kind or unit is missing or unknown")
    for key, allowed in (("agents", AGENT_KEYS), ("land", LAND_KEYS)):
        for row in rec.get(key, []):
            if not isinstance(row, dict) or set(row) - allowed:
                raise ValueError(f"{key} row with keys outside the schema: {sorted(set(row) - allowed) if isinstance(row, dict) else row}")
    return rec


def dump(rec: dict[str, Any]) -> str:
    parse(json.dumps(rec))      # the writer refuses what the parser would
    return json.dumps(rec, indent=1, sort_keys=True) + "\n"


def setting(cfg: Any, key: str) -> int:
    import relay_config
    default, low, high = SETTINGS[key]
    value = relay_config.get(cfg, "metrics." + key, default)
    return default if isinstance(value, bool) or not isinstance(value, int) else max(low, min(high, value))


def enabled(cfg: Any) -> bool:
    import relay_config
    return relay_config.get(cfg, "metrics.enabled", True) is not False


# ---- the ledger: finished, labelled agents ----

def _epoch(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def ledger_agents(ledger_dir: str) -> list[dict[str, Any]]:
    """Every labelled `agent_stop` in the ledger as an agent row (+ `unit`), oldest first. Unreadable lines are skipped: the ledger is outside git."""
    starts: dict[str, str] = {}
    stops: list[dict[str, Any]] = []
    try:
        names = sorted(n for n in os.listdir(ledger_dir) if n.endswith(".jsonl"))
    except OSError:
        return []
    for name in names:
        with open(os.path.join(ledger_dir, name), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("event") == "agent_start" and row.get("agent_id"):
                    starts[str(row["agent_id"])] = str(row.get("ts"))
                elif row.get("event") == "agent_stop" and row.get("agent_id") and relay_labels.STAGE_LABEL.match(str(row.get("label") or "")):
                    stops.append(row)
    out = []
    for row in stops:
        stage, _, unit = str(row["label"]).partition(": ")
        word = re.match(r"^(.*?)( \d+)?$", stage)
        out.append({"id": str(row["agent_id"]), "session": str(row.get("session_id") or ""), "stage": word.group(1) if word else stage,
                    "n": int(word.group(2)) if word and word.group(2) else 1, "model": str(row.get("model") or ""),
                    "start": starts.get(str(row["agent_id"]), str(row["ts"])), "stop": str(row["ts"]),
                    "requests": int(row.get("requests") or 0), "cost_usd": float(row.get("cost_est") or 0.0), "unit": unit})
    return out


def match_unit(agent: dict[str, Any], items: list[dict[str, Any]], notes: list[str]) -> Optional[str]:
    """The queue item an agent belongs to, or None. A full item id matches exactly; an old 40-char label matches an item only inside
    the item's taken..closed window, and never two items (the agent is named in `notes` and left out)."""
    unit = agent["unit"]
    for prefix in ("", "design-", "fix-"):
        if prefix and not unit.startswith(prefix):
            continue
        name = unit[len(prefix):]
        if any(i["slug"] == name for i in items):
            return name
    name = re.sub(r"^(design|fix)-", "", unit)
    start = _epoch(agent["start"])
    hits = []
    for item in items:
        if item["slug"][:40] != name[:40] or not item.get("taken_at"):
            continue
        end = item.get("closed_at") or item.get("dropped_at")
        if _epoch(item["taken_at"]) <= start <= (_epoch(end) if end else float("inf")):
            hits.append(item["slug"])
    if len(hits) > 1:
        notes.append(f"metrics: agent {agent['id']} ({agent['stage']}: {unit}) fits the windows of {', '.join(sorted(hits))}; stored in none")
        return None
    return hits[0] if hits else None


# ---- reading the records at a commit ----

def stored(main: str, rev: str) -> list[dict[str, Any]]:
    """Every record under .relay/changes at `rev`; a file that does not parse is skipped (the gate's tests parse them)."""
    rc, out = relay_git.git(main, "ls-tree", "-r", "--name-only", rev, "--", DIR)
    found = []
    for path in out.splitlines() if rc == 0 else []:
        rc, text = relay_git.git(main, "show", f"{rev}:{path}", raw=True)
        try:
            found.append(parse(text)) if rc == 0 else None
        except ValueError:
            continue
    return found


def _stored_paths(main: str, rev: str) -> set[str]:
    rc, out = relay_git.git(main, "ls-tree", "-r", "--name-only", rev, "--", DIR)
    return set(out.splitlines()) if rc == 0 else set()


# ---- planning the writes at one head ----

def _record(kind: str, unit: str, item: Optional[str], agents: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [{k: v for k, v in a.items() if k in AGENT_KEYS} for a in sorted(agents, key=lambda a: a["start"])]
    return {"schema": 1, "kind": kind, "unit": unit, "item": item, "branch": None, "before": None, "head": None, "agents": rows, "land": []}


def plan(main: str, rev: str, ledger: list[dict[str, Any]], items: list[dict[str, Any]], landing: dict[str, dict[str, Any]],
         now: float, quiet_min: int, notes: list[str]) -> dict[str, str]:
    """The files to add at `rev`: a `land-<head>` record per landing unit (its agents not yet stored, its events, its range) and a
    `sweep-<stamp>` record per other unit whose agents all stopped `quiet_min` ago. Each agent id is stored once in the repository."""
    done = {a["id"] for rec in stored(main, rev) for a in rec["agents"]}
    have = _stored_paths(main, rev)
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for agent in ledger:
        if agent["id"] in done:
            continue
        item = match_unit(agent, items, notes)
        by_unit.setdefault(item or "other:" + agent["unit"], []).append(agent)
    states = {i["slug"]: i for i in items}
    writes: dict[str, str] = {}
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for unit, info in sorted(landing.items()):
        path = f"{DIR}/{unit}/land-{info['head'][:12]}.json"
        if path in have:
            continue
        rec = _record("change", unit, unit, by_unit.pop(unit, []))
        rec.update(branch=info.get("branch"), before=info.get("before"), head=info["head"], land=info.get("land", []))
        writes[path] = dump(rec)
    for unit, agents in sorted(by_unit.items()):
        item = unit if unit in states else None
        stages = {a["stage"] for a in agents}
        if item and states[item].get("state") == "taken":
            continue                                    # its own landing will write it
        if now - max(_epoch(a["stop"]) for a in agents) < quiet_min * 60:
            continue                                    # maybe still going
        name = unit.partition("other:")[2] or unit
        kind = "design" if stages <= set(DESIGN_STAGES) else ("other" if stages <= {"other"} else "change")
        path = f"{DIR}/{name}/sweep-{stamp}.json"
        writes[path] = dump(_record(kind, name, item, agents))
    return writes


def _land_rows(events: list[Any], slug: str, branch: str, pid: int) -> list[dict[str, Any]]:
    rows = []
    for e in events:
        if e.kind in ("asked", "locked", "done") and e.branch == branch and e.pid == pid:
            rows.append({"kind": e.kind, "at": e.ts, **({"gates_run": e.gates_run, "gate_seconds": e.gate_seconds} if e.kind == "done" else {})})
        elif e.kind == "held" and e.slug == slug:
            rows.append({"kind": "held", "at": e.ts, "file": e.file, "holder": e.holder})
    return rows


def landed_units(main: str, before: Optional[str]) -> list[tuple[str, str]]:
    """(item id, branch) of the open items this landing brought in: their landed commit is not reachable from `before`. Ask before the
    cleanup removes the branches. An item that landed earlier and is still open is not a unit of this landing."""
    import relay_lanes
    out = []
    for x in relay_lanes.lanes_state(main, limit=relay_lanes.LANES_MAX).landed_open:
        if before and x.sha and relay_git.git(main, "merge-base", "--is-ancestor", x.sha, before)[0] == 0:
            continue
        out.append((x.slug, x.branch))
    return out


def record_landing(repo: str, units: list[tuple[str, str]], before: Optional[str], head: str, events: list[Any], pid: int,
                   notify: Callable[[str], None], now: Optional[float] = None) -> None:
    """Write the records of a landing (one per unit, none for a train branch) and the sweep, in one commit on the default branch."""
    import relay_config
    import relay_queue
    main, _ = relay_queue._context(repo)
    cfg = relay_config.load_bindings(main)
    if not enabled(cfg):
        return
    items = relay_queue.read_queue(main, closed=True)
    items += [{"slug": slug} for slug, _ in units if slug not in {i["slug"] for i in items}]     # a landed unit always matches its own id
    ledger = ledger_agents(relay_config.ledger_dir())
    moment = time.time() if now is None else now
    quiet = setting(cfg, "sweep_quiet_min")
    notes: list[str] = []

    def writes_at(rev: str) -> dict[str, str]:
        landing = {slug: {"branch": branch, "before": before, "head": head, "land": _land_rows(events, slug, branch, pid)} for slug, branch in units}
        return plan(main, rev, ledger, items, landing, moment, quiet, notes)

    relay_queue.land_files(repo, f"metrics-{head[:12]}", writes_at, "change records")
    for line in sorted(set(notes)):
        notify(line)


# ---- reading: computed from the records, never stored ----

def _minutes(rec_agent: dict[str, Any]) -> float:
    return max(0.0, _epoch(rec_agent["stop"]) - _epoch(rec_agent["start"])) / 60


def _fmt(value: float) -> str:
    return f"{value:.1f}"


def summary(main: str, rev: str) -> list[str]:
    """The repository: agent minutes and cost per stage, cost per change, from every record at `rev`."""
    records = stored(main, rev)
    stage: dict[str, list[float]] = {}
    cost: dict[str, float] = {}
    for rec in records:
        for a in rec["agents"]:
            stage.setdefault(a["stage"], []).append(_minutes(a))
            cost[rec["unit"]] = cost.get(rec["unit"], 0.0) + a["cost_usd"]
    lines = [f"records: {len(records)}; units: {len({r['unit'] for r in records})}"]
    for name, mins in sorted(stage.items()):
        ordered = sorted(mins)
        lines.append(f"{name}: {len(mins)} agents, median {_fmt(statistics.median(ordered))} min, p90 {_fmt(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))])} min, "
                     f"total {_fmt(sum(mins))} min")
    if cost:
        lines.append(f"cost per unit: median ${statistics.median(cost.values()):.2f}, total ${sum(cost.values()):.2f}")
    return lines


def unit_lines(main: str, rev: str, unit: str) -> list[str]:
    """One unit: minutes and cost per stage, and idle time (taken to landing with no agent of the unit running)."""
    import relay_queue
    records = [r for r in stored(main, rev) if r["unit"] == unit]
    if not records:
        return [f"metrics: no record for {unit}"]
    agents = [a for r in records for a in r["agents"]]
    lines = []
    for name in sorted({a["stage"] for a in agents}):
        mine = [a for a in agents if a["stage"] == name]
        lines.append(f"{name}: {len(mine)} agents, {_fmt(sum(_minutes(a) for a in mine))} min, ${sum(a['cost_usd'] for a in mine):.2f}")
    item = next((i for i in relay_queue.read_queue(main, closed=True) if i["slug"] == unit), None)
    done = [r for r in records if r.get("head") and r["land"]]
    if item and item.get("taken_at") and done and agents:
        end = max(_epoch(x["at"]) for r in done for x in r["land"])
        busy, last = 0.0, 0.0
        for a in sorted(agents, key=lambda a: a["start"]):
            lo, hi = _epoch(a["start"]), _epoch(a["stop"])
            busy += max(0.0, hi - max(lo, last))
            last = max(last, hi)
        lines.append(f"idle: {_fmt(max(0.0, end - _epoch(item['taken_at']) - busy) / 60)} min of {_fmt((end - _epoch(item['taken_at'])) / 60)} min taken to landed")
    return lines


# ---- backfill: the changes landed since 27 Oct, while their ledger lines are here ----

def backfill(repo: str, notify: Callable[[str], None]) -> list[str]:
    """Records for the fast-forwards of the default branch since BACKFILL_FROM that have none; the range comes from the reflog."""
    import relay_land
    import relay_queue
    main, default = relay_queue._context(repo)
    low = datetime.fromisoformat(BACKFILL_FROM).timestamp()
    rc, out = relay_git.git(main, "reflog", "show", "--format=%H%x09%ct%x09%gs", f"refs/heads/{default}", "-n", "100000")
    entries = [x.split("\t", 2) for x in out.splitlines() if x.count("\t") == 2] if rc == 0 else []
    items = relay_queue.read_queue(main, closed=True)
    events = relay_land.read_events(main)[0]
    lines = []
    for i, (new, stamp, subject) in enumerate(entries[:-1]):
        m = re.match(r"merge (wt/\S+): Fast-forward$", subject)
        if not m or int(stamp) < low:
            continue
        old, branch = entries[i + 1][0], m.group(1)
        branches = [branch]
        if branch.startswith("wt/train-"):
            rc, log = relay_git.git(main, "log", "--merges", "--format=%s", f"{old}..{new}")
            branches = re.findall(r"^Merge (wt/\S+) into wt/train-", log, re.M) if rc == 0 else []
        units = [(x["slug"], b) for b in branches for x in items if x.get("taken_by") == b]
        if not units:
            lines.append(f"metrics: no queue item for {branch} at {new[:12]}; no record")
            continue
        done = [e for e in events if e.kind == "done" and e.sha == new]
        record_landing(repo, units, done[0].before if done else old, new, [e for e in events if e.pid == done[0].pid and e.branch == done[0].branch] if done else [],
                       done[0].pid if done else 0, lines.append)
    return lines


def main(argv: list[str], repo: str) -> int:
    """`relay metrics [<unit> | sweep | backfill]`."""
    import relay_queue
    root, default = relay_queue._context(repo)
    if argv[:1] == ["backfill"]:
        print("\n".join(backfill(repo, print)) or "metrics: backfill done")
        return 0
    if argv[:1] == ["sweep"]:
        record_landing(repo, [], None, relay_git.git(root, "rev-parse", default)[1], [], 0, print, now=time.time())
        return 0
    rev = "refs/heads/" + default
    print("\n".join(unit_lines(root, rev, argv[0]) if argv else summary(root, rev)))
    return 0
