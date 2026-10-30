"""Lanes: how many changes are being built, which queue items can start next, and `relay queue start`.

Everything is derived from git and the queue each time; no lane record is stored (principle 3). A **lane** is one change
built in its own worktree on a `wt/*` branch. It runs from the take of its queue item to its landing (the branch has own
commits and its tip is on the default branch, or its ref is gone and the default branch's history holds its merge).
A worktree on a `wt/*` branch that no item names counts as a lane while it changed within `front.lane_quiet_hours`.
A `wt/train-*` branch is no lane of its own, except that an open one (changed within the same hours) holding running riders is
their one lane; a rider merged into no open train is its own lane. Free lanes = the project's setting ("Changes built at once: N." in its generated
instruction file, 1-8, default 4) minus the running ones.

The pick: queue order (fixes first, then ip), skipping an item with an unanswered owner question, and skipping an item whose
`where` names a file that a running branch has already changed (committed against the default branch, or modified in its
worktree): that item waits, and the line says which file and branch. Used by the front's hooks (plugins/front/hooks/lanes.py)
and by `relay queue start`. Settings, in the project's .claude/kit.toml under [front]:
  lanes_line_items  default 3, bound 0-10   startable items named after the picks ("next: ...") so a stuck pick hides nothing; 0 is the line
                                            without "next:" (at 10 about 250 tokens per message). Out of bounds: the default, and the line says so
  feature_lanes     default 0, bound 0..lanes  lanes kept for features (relay: 3): while fewer feature lanes run, a free lane goes to the top startable
                                            feature before any fix; the line shows "N of M fix lanes, K of J feature lanes"; 0 is no split
  stop_nudge        default 1, bound 0-2    Stop refusals per observed lane state and session (0: the line only; 2: a hold costs two extra turns)
  lane_quiet_hours  default 3, bound 1-24   a worktree with no item counts as a lane while changed within this (at 1 a long gate drops it
                                            from the count; at 24 a parked branch holds a lane for a day)
Tests: tests/test_lanes_state.py
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import re
import time
from typing import Any, NamedTuple, Optional

import relay_config
import relay_git
import relay_inert
import relay_queue
from relay_lane_features import feature_lanes_read, feature_lanes_setting  # noqa: F401  (the setting is re-exported for callers and tests)

LANES_DEFAULT, LANES_MAX = 4, 8
SETTINGS = {"lanes_line_items": (3, 0, 10), "stop_nudge": (1, 0, 2), "lane_quiet_hours": (3, 1, 24)}   # default, lowest, highest
LIST_ITEMS = 3             # waits, landed and uncounted worktrees named in the line
LOG_DEPTH = 500            # newest merges of the default branch searched for the landing of a branch whose ref is gone
SHA_COMMITS = 40           # newest commits of a landed branch looked at for the one that names the change


class Lane(NamedTuple):
    branch: str
    slug: Optional[str]        # the queue item that took it; None for a worktree no item names
    riders: tuple = ()         # for an open train: the running branches merged into it (their files still count)


class Pick(NamedTuple):
    slug: str
    kind: str                  # fix or feature
    ip: int
    mode: str                  # "start" (a build) or "design" (a design in a fresh worktree)


class Wait(NamedTuple):
    slug: str
    file: str
    branch: str
    pick: Optional[str] = None      # set when the wait is for another pick of the same call (then `branch` is empty)


class Landed(NamedTuple):
    slug: str
    kind: str
    branch: str
    sha: Optional[str]         # the commit that names the change (a non-inert one); None when git no longer shows it


class State(NamedTuple):
    setting: int
    running: list[Lane]
    free: int
    picks: list[Pick]
    waits: list[Wait]
    landed_open: list[Landed]
    quiet: list[str]           # no-item worktrees not counted (quiet or already landed)
    upcoming: list[Pick] = []  # the startable items after the picks (at most SETTINGS["lanes_line_items"] high), named so one stuck pick hides nothing
    skipped: list[str] = []    # open items left out of the picks because their newest reproduce result is "no" (`relay queue note` with reproduced = "no")
    feature_split: int = 0     # lanes kept for features (front.feature_lanes); 0 = no split
    feature_running: int = 0   # running lanes (a train counts its riders) that took a feature
    itemless: int = 0          # running lanes that took no queue item (a design worktree): neither fix nor feature lanes
    feature_note: Optional[str] = None   # why front.feature_lanes was not used as written (out of bounds, not a whole number)


def setting(cfg: Any, key: str) -> int:
    """The setting `front.<key>` clamped to its bounds; the default when it is missing or not a whole number."""
    default, low, high = SETTINGS[key]
    value = relay_config.get(cfg, "front." + key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if key == "lanes_line_items" and not low <= value <= high:
        return default
    return max(low, min(high, value))


def setting_note(cfg: Any, key: str) -> Optional[str]:
    """Why `front.<key>` was not used as written (set, but out of bounds or not a whole number); None when it is unset or used."""
    default, low, high = SETTINGS[key]
    value = relay_config.get(cfg, "front." + key)
    if value is None or key != "lanes_line_items":     # only this key falls back to the default when out of bounds; the others are clamped
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{key} {value} is not a whole number: {default} is used"
    if low <= value <= high:
        return None
    return f"{key} {value} is out of bounds {low}-{high}: {default} is used"


def lanes_setting(main: str) -> int:
    """N of "Changes built at once: N." in the project's generated instruction file; the default when no file says it."""
    for name in ("CLAUDE.local.md", "CLAUDE.md"):
        try:
            with open(os.path.join(main, name), encoding="utf-8") as handle:
                found = re.search(r"^Changes built at once: (\d+)\.", handle.read(), re.M)
        except OSError:
            continue
        if found:
            return max(1, min(LANES_MAX, int(found.group(1))))
    return LANES_DEFAULT


def _git(main: str, *args: str) -> tuple[int, str]:
    return relay_git.git(main, *args)


def _is_ancestor(main: str, older: str, newer: str) -> bool:
    return _git(main, "merge-base", "--is-ancestor", older, newer)[0] == 0


def _branch_name(branch: str) -> "re.Pattern[str]":
    # wt/x is not wt/xy and not wt/x/y
    return re.compile(r"(?<![\w/])" + re.escape(branch) + r"(?![\w/.-])")


def _newest_real_commit(main: str, tip: str, since: Optional[str]) -> Optional[str]:
    """The newest commit of the branch's own line (first parent: what the default branch brought in by a merge is skipped) taken after
    `since` that changes a file which is not inert (a tip is often a check commit)."""
    args = ["log", "--first-parent", "--no-merges", "--format=%H", "-n", str(SHA_COMMITS)]
    if since:
        args.append("--since=" + since)
    rc, out = _git(main, *args, tip)
    for sha in out.split() if rc == 0 else []:
        rc, names = _git(main, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha)
        if rc == 0 and any(not relay_inert.matches(n) for n in names.splitlines() if n.strip()):
            return sha
    return None


def landing(main: str, default: str, branch: str, taken_at: Optional[str]) -> tuple[bool, Optional[str]]:
    """(landed, sha): the branch has own commits and its tip is on the default branch, or its ref is gone and the
    default branch's history holds its merge (a merge commit, in either message form, or a fast-forward in the reflog)."""
    ref, base = "refs/heads/" + branch, "refs/heads/" + default
    if _git(main, "show-ref", "--verify", "--quiet", ref)[0] == 0:
        if relay_git.has_own_commits(main, branch) and _is_ancestor(main, ref, base):
            return True, _newest_real_commit(main, ref, taken_at)
        return False, None
    named = _branch_name(branch)
    rc, out = _git(main, "log", base, "--merges", "--format=%H%x09%s", "-n", str(LOG_DEPTH))
    for line in out.splitlines() if rc == 0 else []:
        sha, _, subject = line.partition("\t")
        found = named.search(subject)
        if found and not re.search(r"\binto\s+'?$", subject[:found.start()]):      # "Merge master into wt/x" takes master, it does not land wt/x
            return True, sha
    rc, out = _git(main, "reflog", "show", "--format=%H %gs", "-n", str(LOG_DEPTH), base)
    for entry in out.splitlines() if rc == 0 else []:
        tip, _, subject = entry.partition(" ")
        if subject.startswith("merge ") and subject.endswith("Fast-forward") and named.search(subject):
            return True, _newest_real_commit(main, tip, taken_at)       # the tip master moved to, walked to the branch's own commit
    return False, None


def touched(main: str, default: str, branch: str, worktree: Optional[str]) -> list[str]:
    """Files a running branch has changed: committed against the default branch, plus modified or new in its worktree. Inert files left out."""
    names: set[str] = set()
    rc, out = _git(main, "diff", "--name-only", "--no-renames", f"refs/heads/{default}...refs/heads/{branch}")
    names.update(out.splitlines() if rc == 0 else [])
    if worktree:
        rc, out = relay_git.git(worktree, "status", "--porcelain", "--untracked-files=all", raw=True)
        for line in out.splitlines() if rc == 0 else []:
            names.add(line[3:].split(" -> ")[-1].strip('"'))
    return sorted(n for n in names if n and not relay_inert.matches(n))


def _activity(main: str, branch: str, worktree: Optional[str]) -> float:
    """Epoch seconds of the newest sign of work on a branch with no item: its newest reflog entry or the newest changed file."""
    newest = 0.0
    rc, out = _git(main, "reflog", "show", "--date=unix", "--format=%gd", "-n", "1", "refs/heads/" + branch)    # the entry's own time, not its commit's
    found = re.search(r"@\{(\d+)\}", out) if rc == 0 else None
    if found:
        newest = float(found.group(1))
    if worktree:
        rc, out = relay_git.git(worktree, "status", "--porcelain", "--untracked-files=all", raw=True)
        for line in out.splitlines() if rc == 0 else []:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(worktree, line[3:].split(" -> ")[-1].strip('"'))))
            except OSError:
                continue
    return newest


def canonical(path: str) -> str:
    """A file's name with a plugin's copy mapped to its source, as the links under plugins/<p>/lib point (a link never shows in a diff, so this maps a name written by hand): plugins/<p>/lib/relay_*.py and
    prices.toml come from lib/ (prices.toml from the root); plugins/<p>/bin/relay is bin/relay. Two names of one file compare equal."""
    found = re.fullmatch(r"plugins/[^/]+/(lib/relay_[^/]*\.py|lib/prices\.toml|bin/relay)", path)
    if not found:
        return path
    return "prices.toml" if found.group(1) == "lib/prices.toml" else found.group(1)


def _overlap(where: list[str], changed: list[str]) -> Optional[str]:
    """The first changed file an item's `where` names (a file, or a folder holding it); None when none."""
    for element in where:
        place = relay_queue.parse_place(element)
        if place is None:
            continue
        stem = canonical(place.path.rstrip("/"))
        for name in map(canonical, changed):
            if name == stem or name.startswith(stem + "/"):
                return name
    return None


def _paths(where: list[str]) -> list[str]:
    """The paths an item's `where` names, without line ranges or notes."""
    places = (relay_queue.parse_place(element) for element in where)
    return [canonical(place.path.rstrip("/")) for place in places if place is not None]


def _shared(where: list[str], others: list[str]) -> Optional[str]:
    """The first path both `where` lists name: the same file, or one a folder holding the other; None when none."""
    for mine in _paths(where):
        for theirs in others:
            if mine == theirs or mine.startswith(theirs + "/") or theirs.startswith(mine + "/"):
                return max(mine, theirs, key=len)
    return None


def mode_of(item: dict) -> str:
    """A feature, or a fix whose `where` says design, starts as a design; any other fix as a build."""
    notes = []                  # the words after the path: a path such as docs/design.md says nothing about the mode
    for element in item.get("where") or []:
        place = relay_queue.parse_place(element)
        notes.append(place.note if place else element)
    return "design" if item["kind"] == "feature" or "design" in " ".join(notes).lower() else "start"


def _waiting_question(item: dict) -> bool:
    return bool(relay_queue.owner_waiting(relay_queue.notes_of(item)))


def _not_reproduced(item: dict) -> bool:
    """True when the newest fact note with `reproduced` (written by `relay queue note`) says "no": the item is no pick (it would hide every item behind it)."""
    verdict = [n.reproduced for n in relay_queue.notes_of(item) if n.kind == "fact" and n.reproduced]      # notes are in date order: the newest decides
    return verdict[-1:] == ["no"]


def _one_lane_per_train(main: str, running: list[Lane], trees: dict[str, str], when: float, quiet_hours: int) -> list[Lane]:
    """A running branch with own commits whose tip is inside an open `wt/*` branch (a train rider) is not a lane of its own:
    the branch it was merged into is the lane, with the riders listed so their files still count. A holder counts as open while it
    changed within `quiet_hours` (a red, abandoned train does not); of several open holders the most recently active one is taken.
    One `for-each-ref --contains` per rider candidate."""
    kept: list[Lane] = []
    riders: dict[str, list[str]] = {}
    for lane in running:
        into: Optional[str] = None
        if relay_git.has_own_commits(main, lane.branch):
            held = _git(main, "for-each-ref", "--contains", "refs/heads/" + lane.branch, "--format=%(refname:short)", "refs/heads/wt/")[1].split()
            best = 0.0
            for b in held:
                if b == lane.branch or _is_ancestor(main, "refs/heads/" + b, "refs/heads/" + lane.branch):
                    continue                                   # itself, or a branch at the same tip: not a train
                seen = _activity(main, b, trees.get(b))
                if when - seen <= quiet_hours * 3600 and seen > best:
                    into, best = b, seen
        if into is None:
            kept.append(lane)
        else:
            riders.setdefault(into, []).append(lane.branch)
    have = {lane.branch for lane in kept}
    for train in sorted(riders):
        if train not in have:
            kept.append(Lane(train, None, tuple(riders[train])))
    return kept


def _lane_files(main: str, default: str, lane: Lane, trees: dict[str, str]) -> list[str]:
    """Files a lane has changed: its own, and for a train those of its riders (their worktrees may hold uncommitted edits)."""
    names: set[str] = set()
    for branch in (lane.branch,) + tuple(lane.riders):
        names.update(touched(main, default, branch, trees.get(branch)))
    return sorted(names)


def lanes_state(repo: str, quiet_hours: int = SETTINGS["lane_quiet_hours"][0], now: Optional[float] = None, limit: Optional[int] = None,
                features: Optional[int] = None) -> State:
    """The lanes of the project that `repo` belongs to. `now` is epoch seconds (a value the tests pass); `limit` is the lanes setting
    (read from the instruction file when None); `features` the lanes kept for features (read from kit.toml when None). Raises relay_queue.Refused outside a project with a queue."""
    main, default = relay_queue._context_with_relay(repo)
    when = time.time() if now is None else now
    capacity = lanes_setting(main) if limit is None else limit
    every = relay_queue.read_queue(main, closed=True)
    open_items = [i for i in every if not i.get("problems") and i.get("state") in ("open", "taken")]
    named = {i.get("taken_by") for i in every if i.get("taken_by")}
    trees = {t["branch"]: t["path"] for t in relay_git.worktrees(main) if t["branch"]}
    running: list[Lane] = []
    landed_open: list[Landed] = []
    quiet: list[str] = []
    counted: set[str] = set()
    for item in open_items:
        if item["state"] != "taken" or not item.get("taken_by"):
            continue
        branch = item["taken_by"]
        landed, sha = landing(main, default, branch, item.get("taken_at"))
        if landed:
            landed_open.append(Landed(item["slug"], item["kind"], branch, sha))
        elif _git(main, "show-ref", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0:
            if branch not in counted:                      # a branch that took two items is one lane
                counted.add(branch)
                running.append(Lane(branch, item["slug"]))
        else:
            quiet.append(f"{branch} (gone, item {item['slug']} still taken)")
    for branch in sorted(trees):
        if not branch.startswith("wt/") or branch.startswith("wt/train-") or branch in named:
            continue
        done, _ = landing(main, default, branch, None)
        if done:
            quiet.append(f"{branch} (landed)")
        elif when - _activity(main, branch, trees[branch]) <= quiet_hours * 3600:
            running.append(Lane(branch, None))
        else:
            quiet.append(f"{branch} (quiet)")
    running = _one_lane_per_train(main, running, trees, when, quiet_hours)
    free = max(0, capacity - len(running))
    split, split_note = feature_lanes_read(main, capacity) if features is None else (max(0, min(capacity, features)), None)
    taken_kinds: dict[str, set[str]] = {}          # a lane is a branch: the kinds of the items it took (a train: those of its riders too)
    for i in open_items:
        if i["state"] == "taken" and i.get("taken_by"):
            taken_kinds.setdefault(i["taken_by"], set()).add(i["kind"])
    lane_kinds = [set().union(*(taken_kinds.get(b, set()) for b in (lane.branch,) + tuple(lane.riders))) for lane in running]
    feature_running = sum(1 for k in lane_kinds if "feature" in k)
    itemless = sum(1 for k in lane_kinds if not k)
    picks: list[Pick] = []
    upcoming: list[Pick] = []
    skipped: list[str] = []
    waits: list[Wait] = []
    chosen: list[tuple[str, list[str]]] = []      # the picks so far in this call, with the paths their `where` names
    for item in open_items:                       # a running lane holds the files its taken item names, before its branch has changed any
        if item["state"] == "taken" and any(lane.branch == item.get("taken_by") for lane in running):
            chosen.append((item["slug"], _paths(item.get("where") or [])))
    if free:
        changed = {lane.branch: _lane_files(main, default, lane, trees) for lane in running}

        def blocked(item: dict, held: list[tuple[str, list[str]]]) -> Optional[Wait]:
            """The wait that keeps an item from starting now (a running branch changed its file, or an earlier pick holds it); None when it can start."""
            where = item.get("where") or []
            hit = next(((f, b) for b, files in sorted(changed.items()) for f in [_overlap(where, files)] if f), None)
            if hit:
                return Wait(item["slug"], hit[0], hit[1])
            twin = next(((slug, shared) for slug, paths in held for shared in [_shared(where, paths)] if shared), None)
            return Wait(item["slug"], twin[1], "", twin[0]) if twin else None

        def candidates() -> list[dict]:
            return [i for i in relay_queue.ordered(open_items) if i["state"] == "open" and not _waiting_question(i) and not _not_reproduced(i)]

        first: list[str] = []                         # the split: the top startable features take the lanes kept for features, before any fix
        trial = list(chosen)
        for item in candidates() if split > feature_running else []:
            if len(first) == min(free, split - feature_running):
                break
            if item["kind"] == "feature" and blocked(item, trial) is None:
                first.append(item["slug"])
                trial.append((item["slug"], _paths(item.get("where") or [])))
        for item in relay_queue.ordered(open_items):
            if item["state"] == "open" and not _waiting_question(item) and _not_reproduced(item):
                skipped.append(item["slug"])
        pool = candidates()
        for item in [i for i in pool if i["slug"] in first] + [i for i in pool if i["slug"] not in first]:
            where = item.get("where") or []
            full = len(picks) == free          # past the picks: the same checks, but nothing is recorded as a wait and nothing is chosen
            wait = blocked(item, chosen)
            if wait:
                if not full:
                    waits.append(wait)
                continue
            pick = Pick(item["slug"], item["kind"], item["ip"], mode_of(item))
            if full:
                upcoming.append(pick)
                if len(upcoming) == SETTINGS["lanes_line_items"][2]:
                    break
                continue
            chosen.append((item["slug"], _paths(where)))
            picks.append(pick)
    return State(capacity, running, free, picks, waits, landed_open, quiet, upcoming, skipped, split, feature_running, itemless, split_note)


def wait_text(w: Wait) -> str:
    """One wait in words: the item, the file, and what it waits for (a running branch, or another item that holds the file)."""
    return f"{w.slug} waits for {w.file} (same file as {w.pick})" if w.pick else f"{w.slug} waits for {w.file} ({w.branch})"


def line(state: State, items: int = SETTINGS["lanes_line_items"][0], note: Optional[str] = None) -> Optional[str]:
    """The one line for the front; None when there is nothing to say (lanes full, or no item can start, and nothing landed).
    `items` startable items after the picks are named ("next:"); 0 names none. `note` (a setting that was not used) ends the line."""
    if not (state.picks or state.waits or state.landed_open):
        return None
    parts = [f"Lanes: {len(state.running)} of {state.setting} running"]
    if state.feature_split:
        fixes = len(state.running) - state.feature_running - state.itemless
        parts[0] += (f" ({fixes} of {state.setting - state.feature_split} fix lanes, "
                     f"{state.feature_running} of {state.feature_split} feature lanes"
                     + (f", {state.itemless} without an item" if state.itemless else "") + ")")
    if state.picks:
        parts.append(", ".join(f"{p.mode}: {p.slug} ({p.kind}, ip {p.ip})" for p in state.picks))
    if items and state.upcoming:
        parts.append("next: " + ", ".join(f"{p.slug} ({p.kind}, ip {p.ip})" for p in state.upcoming[:items]))
    if state.waits:
        parts.append("waits: " + ", ".join((f"{w.slug} (same file as {w.pick}: {w.file})" if w.pick else f"{w.slug} ({w.file}, {w.branch})") for w in state.waits[:LIST_ITEMS]))
    if state.landed_open:
        parts.append("landed, still open: " + ", ".join(f"{x.slug} ({x.branch} landed)" for x in state.landed_open[:LIST_ITEMS]))
    if state.skipped:
        parts.append("skipped, not reproduced: " + ", ".join(state.skipped[:LIST_ITEMS]))
    if state.quiet:
        parts.append("no lane, not counted: " + ", ".join(state.quiet[:LIST_ITEMS]))
    for text in (note, state.feature_note):
        if text:
            parts.append(text)
    return "; ".join(parts)


def close_landed(repo: str) -> list[str]:
    """Close each feature whose branch has landed with the sha that names its change; a fix is left to the cycle's --test close.
    One line per item: closed, or why it could not be (a hook must not hide it)."""
    out: list[str] = []
    for gone in lanes_state(repo, limit=LANES_MAX).landed_open:
        if gone.kind != "feature":
            continue
        if gone.sha is None:
            out.append(f"{gone.slug}: landed, but git no longer shows its commit; close it by hand with `relay queue done {gone.slug} --evidence <sha>`")
            continue
        try:
            out.append(relay_queue.close_with_evidence(repo, gone.slug, gone.sha))
        except relay_queue.Refused as exc:
            out.append(f"{gone.slug}: landed, not closed: {exc}")
    return out


def stop_key(state: State) -> str:
    """The observed state a Stop refusal is counted for: the sorted running lanes and the free count."""
    return json.dumps({"running": sorted(lane.branch for lane in state.running), "free": state.free})


def stop_refusal(state: State, stamp: str, nudge: int, session: str) -> Optional[str]:
    """The reason to refuse the end of the front's turn, or None. Counts refusals per session in the file `stamp`
    (outside the repository): at most `nudge` for one state, so a deliberate hold costs one extra turn per lane event, never a loop."""
    if not nudge or not state.picks or not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        return None
    key = stop_key(state)
    seen = 0
    try:
        with open(stamp, encoding="utf-8") as handle:
            old = json.load(handle)
        if isinstance(old, dict) and old.get("state") == key and isinstance(old.get("count"), int):
            seen = old["count"]
    except (OSError, ValueError):
        pass
    if seen >= nudge:
        return None
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    with open(stamp, "w", encoding="utf-8") as handle:
        json.dump({"state": key, "count": seen + 1}, handle)
    shown = line(state) or ""
    return (f"{shown}. Free lanes and items that can start: start them with `relay queue start <slug> --scratch <folder>`, "
            "or say in one short sentence why the lane stays free: facts only (what is free, what waits), never a reading of what the owner wants or said.")


# ---------------------------------------------------------------- relay queue start

def _short(slug: str) -> str:
    return slug[:40].rstrip("-")


def _check_for(worktree: str, where: list[str]) -> str:
    """The quick check for a build: the test files named like the item's `where` files, else the project's quick gate."""
    found: list[str] = []
    for element in where:
        place = relay_queue.parse_place(element)
        if place is None:
            continue
        stem = os.path.splitext(os.path.basename(place.path.rstrip("/")))[0].removeprefix("relay_")
        folder = os.path.join(worktree, "tests")
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if stem and name.startswith("test_") and name.endswith(".py") and stem in name and name not in found:
                found.append(name)
    if found:
        return "pytest -q -x " + " ".join(os.path.join(worktree, "tests", n) for n in found)
    return f"{worktree}/bin/ci --quick"


def build_brief(item: dict, worktree: str, branch: str, scratch: str, name: str, state: State, check: str, plan: Optional[str] = None) -> str:
    """The brief of a build (a fix) printed from the item: the per-item lines; the rest is the fixed template."""
    others = [f"- {lane.branch}" + (f" ({lane.slug})" if lane.slug else "") for lane in state.running]
    lines = [f"# Build: {item['title']}", "",
             f"Worktree: {worktree} (branch {branch}). `git -C` and absolute paths; never `cd` into it.",
             f"Queue item ({item['kind']}, ip {item['ip']}): `{item['slug']}`, already taken by this branch. Read it with `relay queue show {item['slug']}`: "
             "its notes hold the owner's words and answers.", "",
             "What:", relay_queue.joined(item, "what"), "", "Why:", relay_queue.joined(item, "why")]
    if plan:
        lines += ["", f"Plan: {plan} (read it first; the section \"what changed after the review\" says what the design review found)"]
    if item.get("failing_case"):
        lines += ["", "Failing case:", relay_queue.joined(item, "failing_case")]
    if item.get("pass_cases"):
        lines += ["", "Pass cases:", relay_queue.joined(item, "pass_cases")]
    if item.get("where"):
        lines += ["", "Where:"] + [f"- {w}" for w in item["where"]]
    if others:
        lines += ["", "Other lanes running now (the files they have changed so far are in the line below; say which shared files you touched):"] + others
        shared = [f"- {lane.branch}: {', '.join(touched_files[:8])}" for lane, touched_files in state_touched(state, worktree)]
        lines += shared
    lines += ["", "Rules: types on new or changed code; tests first, one per scenario; each new test shown to fail without the fix; no paid run; "
              "a fix item's test is closed by the cycle with `relay queue done`.",
              f"Check to loop on: `{check}`. Do not run the full gate. Commit.",
              f"Report: {scratch}/reports/{name}.md, reply in at most 10 lines."]
    return "\n".join(lines) + "\n"


def state_touched(state: State, worktree: str) -> list[tuple[Lane, list[str]]]:
    """(lane, files it has changed) for each running lane, for the brief's warning."""
    main = relay_git.main_checkout(worktree) or worktree
    default = relay_git.default_branch(main) or "master"
    trees = {t["branch"]: t["path"] for t in relay_git.worktrees(main) if t["branch"]}
    return [(lane, _lane_files(main, default, lane, trees)) for lane in state.running]


def design_brief(item: dict, worktree: str, scratch: str, name: str, plan: Optional[str] = None) -> str:
    """The brief of a design: the item in full (the owner's words verbatim), then the fixed design steps (owner, 27 Oct: designed against the fresh repository)."""
    return "\n".join([
        f"# Design: {item['title']}", "",
        f"Worktree (fresh, for reading the code): {worktree}. `git -C` and absolute paths; never `cd` into it.",
        f"Queue item `{item['slug']}`, already taken. The item in full, the owner's words verbatim:", "",
        relay_queue.show_text(item), "",
        "Measure live data first (a script over the queue, git, the ledger); write at least two distinct approaches plus doing nothing, and how "
        "leading tools solve it; every recommendation says what it rests on (a measured number, or not measured). End with an \"Open for the owner\" "
        "list of real trade-offs only, each with options and the recommendation first. Critique the owner's own picks once, plainly.",
        *([f"Earlier plan: {plan}; your output replaces it."] if plan else []),
        f"Output: {scratch}/reports/design-{name}.md",
        f"Last step, after the plan is written: run `relay queue plan {item['slug']} --input {scratch}/reports/design-{name}.md` and put its last line in your hand-back. "
        "A revised plan ends with the section \"what changed after the review\": each finding of the design review, whether it held, and the fix."]) + "\n"


def start(repo: str, slug: str, scratch: str, quiet_hours: int = SETTINGS["lane_quiet_hours"][0], despite_wait: bool = False) -> str:
    """`relay queue start <slug>`: make the worktree and branch, take the item, write its brief into `<scratch>/briefs/`, and print the
    cycle unit (JSON for the Workflow: a `change` unit for a fix, a design for a feature). Refused when no lane is free, the item is not
    open, an owner question about it is unanswered, or it waits for a file another change holds (unless `despite_wait`); nothing is left behind when the take fails."""
    if not os.path.isabs(scratch):
        raise relay_queue.Refused("--scratch is an absolute folder (the session's reports/briefs folder)")
    main, default = relay_queue._context_with_relay(repo)
    state = lanes_state(main, quiet_hours)
    item = next((i for i in relay_queue.read_queue(main) if i["slug"] == slug), None)
    if item is None or item.get("problems") or item["state"] != "open":
        raise relay_queue.Refused(f"queue item '{slug}' is not an open, well-formed item of the default branch")
    if _waiting_question(item):
        raise relay_queue.Refused(f"queue item '{slug}' has an owner question without an answer: record the answer first")
    waiting = next((w for w in state.waits if w.slug == slug), None)
    if waiting and not despite_wait:
        raise relay_queue.Refused(f"{wait_text(waiting)}: start it after that change lands, or start it anyway with --despite-wait")
    if state.free < 1:
        raise relay_queue.Refused(f"no free lane: {len(state.running)} of {state.setting} running")
    name = _short(slug)
    branch, worktree = "wt/" + name, os.path.join(relay_config.worktrees_folder(main), name)
    if os.path.exists(worktree) or _git(main, "show-ref", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0:
        raise relay_queue.Refused(f"{branch} or {worktree} exists already")
    rc, out = _git(main, "worktree", "add", "-q", "-b", branch, worktree, "refs/heads/" + default)
    if rc != 0:
        raise relay_queue.Refused(f"could not make the worktree {worktree}")
    try:
        relay_queue.take(worktree, slug)
    except relay_queue.Refused:
        _git(main, "worktree", "remove", "--force", worktree)
        _git(main, "branch", "-D", branch)
        raise
    mode = mode_of(item)
    folder = os.path.join(scratch, "briefs")
    os.makedirs(folder, exist_ok=True)
    if mode == "design":
        brief = os.path.join(folder, f"design-{name}.md")
        text = design_brief(item, worktree, scratch, name, relay_queue.plan_path(main, slug))
        unit: dict[str, Any] = {"designs": [{"name": name, "brief": brief, "out": os.path.join(scratch, "reports", f"design-{name}.md"), "review": True, "item": slug}]}
    else:
        brief = os.path.join(folder, f"{name}.md")
        check = _check_for(worktree, item.get("where") or [])
        text = build_brief(item, worktree, branch, scratch, name, state, check, relay_queue.plan_path(main, slug))
        unit = {"items": [{"kind": "change", "name": name, "wt": worktree, "check": check, "branch": branch, "item": slug}]}
    with open(brief, "w", encoding="utf-8") as handle:
        handle.write(text)
    waits = [wait_text(w) for w in state.waits if w.slug != slug]
    return json.dumps({"started": slug, "branch": branch, "worktree": worktree, "brief": brief, "mode": mode, "cycle_args": unit, "other_waits": waits}, indent=2)


__all__ = ["Lane", "Pick", "Wait", "Landed", "State", "setting", "lanes_setting", "setting_note", "landing", "touched", "lanes_state", "line",
           "close_landed", "stop_refusal", "start", "mode_of"]
