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
from datetime import datetime, timedelta, timezone
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
FRONT_KEYS = {"day", "cost_usd", "sessions", "basis"}      # basis: "exact" or "estimate", as `relay report` labels a session


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
    front = rec.get("front")
    if front is not None and (not isinstance(front, dict) or set(front) - FRONT_KEYS or front.get("basis") not in ("exact", "estimate")):
        raise ValueError(f"front figure outside the schema: {front}")
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
    """Every record under .relay/changes at `rev`, read in one batch; a file that does not parse is skipped (the gate's tests parse them)."""
    import relay_queue
    rc, out = relay_git.git(main, "ls-tree", "-r", "--name-only", rev, "--", DIR)
    paths = out.splitlines() if rc == 0 else []
    found = []
    for blob in relay_queue.cat_batch(main, [f"{rev}:{path}" for path in paths]):
        try:
            found.append(parse(blob.decode("utf-8", "replace"))) if blob is not None else None
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


def front_days(main: str, rev: str, now: float) -> list[str]:
    """The complete UTC days (BACKFILL_FROM to yesterday) that have no front record at `rev`, oldest first."""
    have = {r["front"]["day"] for r in stored(main, rev) if r.get("front")}
    day = datetime.fromisoformat(BACKFILL_FROM).date()
    today = datetime.fromtimestamp(now, timezone.utc).date()
    out = []
    while day < today:
        if day.isoformat() not in have:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def front_figures(days: list[str]) -> dict[str, dict[str, Any]]:
    """{day: front figure} for `days`, from the main sessions' transcripts with the one rule of `relay report` (relay_analyze); a day with
    no front session is a stored zero, so it is not looked up again. With no transcript folder at all nothing was measured: no figure."""
    import relay_analyze
    import relay_config
    if not days or not os.path.isdir(os.path.join(relay_config.claude_dir(), "projects")):
        return {}
    since = datetime.fromisoformat(days[0] + "T00:00:00+00:00")
    found = relay_analyze.front_cost_by_day(relay_analyze.collect(relay_config.claude_dir(), since=since))
    return {d: {"day": d, **found.get(d, {"cost_usd": 0.0, "sessions": 0, "basis": "exact"})} for d in days}


def plan(main: str, rev: str, ledger: list[dict[str, Any]], items: list[dict[str, Any]], landing: dict[str, dict[str, Any]],
         now: float, quiet_min: int, notes: list[str], held: Optional[dict[str, list[dict[str, Any]]]] = None,
         front: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, str]:
    """The files to add at `rev`: a `land-<head>` record per landing unit (its agents not yet stored, its events, its range) and a
    `sweep-<stamp>` record per other unit whose agents all stopped `quiet_min` ago. Each agent id is stored once in the repository.
    `held` is the hold rows by slug: a dropped item never lands, so the sweep stores its rows (once) under its slug."""
    records = stored(main, rev)
    done = {a["id"] for rec in records for a in rec["agents"]}
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
    for slug, rows in sorted((held or {}).items()):
        if states.get(slug, {}).get("state") != "dropped" or slug in landing:
            continue
        kept = {tuple(sorted(r.items())) for rec in records if rec["unit"] == slug for r in rec["land"]}
        fresh = [r for r in rows if tuple(sorted(r.items())) not in kept]
        if not fresh:
            continue
        path = f"{DIR}/{slug}/sweep-{stamp}.json"
        rec = parse(writes[path]) if path in writes else _record("change", slug, slug, [])
        rec["land"] = rec["land"] + fresh
        writes[path] = dump(rec)
    for day, figure in sorted((front or {}).items()):
        path = f"{DIR}/front/{day}.json"
        if path not in have:
            rec = _record("front", "front", None, [])
            rec["front"] = {**figure, "cost_usd": round(figure["cost_usd"], 4)}
            writes[path] = dump(rec)
    return writes


def _held_rows(events: list[Any], slug: str) -> list[dict[str, Any]]:
    return [{"kind": "held", "at": e.ts, "file": e.file, "holder": e.holder} for e in events if e.kind == "held" and e.slug == slug]


def _land_rows(events: list[Any], slug: str, branch: str, pid: int) -> list[dict[str, Any]]:
    """The rows of one landing: asked, locked and done of the landed `branch` (the train's branch for a rider) and `pid`, and the slug's held rows."""
    rows = []
    for e in events:
        if e.kind in ("asked", "locked", "done") and e.branch == branch and e.pid == pid:
            rows.append({"kind": e.kind, "at": e.ts, **({"gates_run": e.gates_run, "gate_seconds": e.gate_seconds} if e.kind == "done" else {})})
        elif e.kind == "held" and e.slug == slug:
            rows.append({"kind": "held", "at": e.ts, "file": e.file, "holder": e.holder})
    return rows


def landed_units(main: str, before: Optional[str], head: Optional[str] = None, branch: Optional[str] = None) -> list[tuple[str, str]]:
    """(item id, branch) of the items this landing brought in. Two sources: open items whose landed commit is not reachable from
    `before` (a feature still `taken`, closed afterwards), and items `taken` at `before` by the landed branch or a rider of the train
    (a fix closed on its branch is `done` at the new head). Ask before the cleanup removes the branches. An item that landed earlier
    and is still open is not a unit of this landing."""
    import relay_lanes
    import relay_queue
    out = []
    for x in relay_lanes.lanes_state(main, limit=relay_lanes.LANES_MAX).landed_open:
        if before and x.sha and relay_git.git(main, "merge-base", "--is-ancestor", x.sha, before)[0] == 0:
            continue
        out.append((x.slug, x.branch))
    if before and head and branch:
        brought = {branch} | _riders(main, before, head)
        have = {slug for slug, _ in out}
        for slug, item in sorted(relay_queue.Reader(main, before).items().items()):
            if item.get("state") == "taken" and item.get("taken_by") in brought and slug not in have and not item.get("problems"):
                out.append((slug, item["taken_by"]))
    return out


def _riders(main: str, before: Optional[str], head: str) -> set[str]:
    """The branches a train merged into itself inside before..head (none for a plain landing)."""
    if not before or before == head:
        return set()
    rc, log = relay_git.git(main, "log", "--merges", "--format=%s", f"{before}..{head}")
    return set(re.findall(r"^Merge (wt/\S+) into wt/train-", log, re.M)) if rc == 0 else set()


def record_landing(repo: str, units: list[tuple[str, str]], before: Optional[str], head: str, events: list[Any], pid: int,
                   notify: Callable[[str], None], now: Optional[float] = None, landed: Optional[str] = None) -> None:
    """Write the records of a landing (one per unit, none for a train branch) and the sweep, in one commit on the default branch.
    `landed` is the branch `relay land` was called with (a train's own branch for its riders); its events are the landing's, shared by every unit."""
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
        landing = {slug: {"branch": branch, "before": before, "head": head, "land": _land_rows(events, slug, landed or branch, pid)} for slug, branch in units}
        held: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            held[item["slug"]] = _held_rows(events, item["slug"])
        return plan(main, rev, ledger, items, landing, moment, quiet, notes, held, front_figures(front_days(main, rev, moment)))

    for branch in _riders(main, before, head) - {b for _, b in units}:
        notes.append(f"metrics: {branch} landed in {head[:12]} with no queue item; no record")
    relay_queue.land_files(repo, f"metrics-{head[:12]}", writes_at, "change records")
    for line in sorted(set(notes)):
        notify(line)


# ---- reading: computed from the records, never stored ----

def _minutes(rec_agent: dict[str, Any]) -> float:
    return max(0.0, _epoch(rec_agent["stop"]) - _epoch(rec_agent["start"])) / 60


def _fmt(value: float) -> str:
    return f"{value:.1f}"


def _week(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%G-W%V")


def coverage_by_week(main: str, rev: str) -> dict[str, list[float]]:
    """{week: coverage percents} from the `ci: coverage N%` lines of the committed gate logs; a log is placed in the week of the commit that added it."""
    rc, hits = relay_git.git(main, "grep", "-e", "^ci: coverage ", rev, "--", ".relay/checks")
    percent = {m.group(1): float(m.group(2)) for m in re.finditer(r"^[^:\n]*:(\S+\.gate\.log):ci: coverage ([\d.]+)%", hits, re.M)} if rc == 0 else {}
    if not percent:
        return {}
    rc, log = relay_git.git(main, "log", "--format=@%ct", "--name-only", rev, "--", ".relay/checks")
    when: dict[str, float] = {}
    moment = 0.0
    for line in log.splitlines() if rc == 0 else []:
        if line.startswith("@"):
            moment = float(line[1:])
        elif line in percent or line.rsplit("/", 1)[-1] in percent:
            when[line.rsplit("/", 1)[-1]] = moment      # newest first, so the oldest commit of the file wins
    weeks: dict[str, list[float]] = {}
    for name, value in percent.items():
        name = name.rsplit("/", 1)[-1]
        if name in when:
            weeks.setdefault(_week(when[name]), []).append(value)
    return weeks


def summary(main: str, rev: str) -> list[str]:
    """The repository, per week: median and p90 agent minutes per stage, cost per change, and the coverage of the gates, from the records at `rev`."""
    records = stored(main, rev)
    stage: dict[tuple[str, str], list[float]] = {}
    cost: dict[tuple[str, str], float] = {}
    for rec in records:
        for a in rec["agents"]:
            week = _week(_epoch(a["start"]))
            stage.setdefault((week, a["stage"]), []).append(_minutes(a))
            cost[(week, rec["unit"])] = cost.get((week, rec["unit"]), 0.0) + a["cost_usd"]
    lines = [f"records: {len(records)}; units: {len({r['unit'] for r in records})}"]
    front: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        if rec.get("front"):
            front.setdefault(_week(_epoch(rec["front"]["day"] + "T00:00:00Z")), []).append(rec["front"])
    coverage = coverage_by_week(main, rev)
    for week in sorted({w for w, _ in stage} | set(coverage) | set(front)):
        lines.append(week + ":")
        for (w, name), mins in sorted(stage.items()):
            if w == week:
                ordered = sorted(mins)
                lines.append(f"  {name}: {len(mins)} agents, median {_fmt(statistics.median(ordered))} min, p90 {_fmt(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))])} min, "
                             f"total {_fmt(sum(mins))} min")
        week_cost = [v for (w, _), v in cost.items() if w == week]
        if week_cost:
            lines.append(f"  cost per unit: median ${statistics.median(week_cost):.2f}, total ${sum(week_cost):.2f}")
        if week in front:
            estimated = sum(1 for f in front[week] if f["basis"] == "estimate")
            lines.append(f"  front: ${sum(f['cost_usd'] for f in front[week]):.2f} over {len(front[week])} days ({estimated} estimated, the rest exact)")
        if week in coverage:
            lines.append(f"  coverage: median {_fmt(statistics.median(coverage[week]))}% over {len(coverage[week])} gates")
    return lines


def owner_lines(notes: list) -> list[str]:
    """The owner's answers and the waiting they cost, and the decisions agents took. A decision an agent took is no owner waiting, answered
    or not: the owner's reversal of it adds no wait. `overruled` counts the decisions the owner answered with another letter."""
    waits = [_epoch(n.answered_at) - _epoch(n.at) for n in notes if n.kind == "decision" and n.answered_at and not n.decided_by]
    decided = [n for n in notes if n.kind == "decision" and n.decided_by]
    lines = [f"owner: {len(waits)} answers, {_fmt(sum(waits) / 60)} min waited"] if waits else []
    if decided:
        overruled = sum(1 for n in decided if n.answer_choice and n.answer_choice != n.chosen)
        lines.append(f"agents decided: {len(decided)}, owner overruled: {overruled}")
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
    lines += owner_lines(item.get("notes") or [] if item else [])
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
                       done[0].pid if done else 0, lines.append, landed=done[0].branch if done else None)
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
