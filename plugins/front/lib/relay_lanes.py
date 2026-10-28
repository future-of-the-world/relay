"""Lanes: how many changes are being built, which queue items can start next, and `relay queue start`.

Everything is derived from git and the queue each time; no lane record is stored (principle 3). A **lane** is one change
built in its own worktree on a `wt/*` branch. It runs from the take of its queue item to its landing (the branch has own
commits and its tip is on the default branch, or its ref is gone and the default branch's history holds its merge).
A worktree on a `wt/*` branch that no item names counts as a lane while it changed within `front.lane_quiet_hours`.
`wt/train-*` branches are never lanes. Free lanes = the project's setting ("Changes built at once: N." in its generated
instruction file, 1-8, default 4) minus the running ones.

The pick: queue order (fixes first, then ip), skipping an item with an unanswered owner question, and skipping an item whose
`where` names a file that a running branch has already changed (committed against the default branch, or modified in its
worktree): that item waits, and the line says which file and branch. Used by the front's hooks (plugins/front/hooks/lanes.py)
and by `relay queue start`. Settings, in the project's .claude/kit.toml under [front]:
  lanes_line_items  default 3, bound 1-8    items named in the line (at 8 about 200 tokens per message)
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

LANES_DEFAULT, LANES_MAX = 4, 8
SETTINGS = {"lanes_line_items": (3, 1, 8), "stop_nudge": (1, 0, 2), "lane_quiet_hours": (3, 1, 24)}   # default, lowest, highest
LOG_DEPTH = 500            # newest merges of the default branch searched for the landing of a branch whose ref is gone
SHA_COMMITS = 40           # newest commits of a landed branch looked at for the one that names the change


class Lane(NamedTuple):
    branch: str
    slug: Optional[str]        # the queue item that took it; None for a worktree no item names


class Pick(NamedTuple):
    slug: str
    kind: str                  # fix or feature
    ip: int
    mode: str                  # "start" (a build) or "design" (a design in a fresh worktree)


class Wait(NamedTuple):
    slug: str
    file: str
    branch: str


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


def setting(cfg: Any, key: str) -> int:
    """The setting `front.<key>` clamped to its bounds; the default when it is missing or not a whole number."""
    default, low, high = SETTINGS[key]
    value = relay_config.get(cfg, "front." + key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


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


def _overlap(where: list[str], changed: list[str]) -> Optional[str]:
    """The first changed file an item's `where` names (a file, or a folder holding it); None when none."""
    for element in where:
        place = relay_queue.parse_place(element)
        if place is None:
            continue
        stem = place.path.rstrip("/")
        for name in changed:
            if name == stem or name.startswith(stem + "/"):
                return name
    return None


def mode_of(item: dict) -> str:
    """A feature, or a fix whose `where` says design, starts as a design; any other fix as a build."""
    notes = []                  # the words after the path: a path such as docs/design.md says nothing about the mode
    for element in item.get("where") or []:
        place = relay_queue.parse_place(element)
        notes.append(place.note if place else element)
    return "design" if item["kind"] == "feature" or "design" in " ".join(notes).lower() else "start"


def _waiting_question(item: dict) -> bool:
    return bool(relay_queue._waiting(relay_queue.notes_of(item)))


def lanes_state(repo: str, quiet_hours: int = SETTINGS["lane_quiet_hours"][0], now: Optional[float] = None, limit: Optional[int] = None) -> State:
    """The lanes of the project that `repo` belongs to. `now` is epoch seconds (a value the tests pass); `limit` is the lanes setting
    (read from the instruction file when None). Raises relay_queue.Refused outside a project with a queue."""
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
    free = max(0, capacity - len(running))
    picks: list[Pick] = []
    waits: list[Wait] = []
    if free:
        changed = {lane.branch: touched(main, default, lane.branch, trees.get(lane.branch)) for lane in running}
        for item in relay_queue.ordered(open_items):
            if item["state"] != "open" or _waiting_question(item):
                continue
            where = item.get("where") or []
            hit = next(((f, b) for b, files in sorted(changed.items()) for f in [_overlap(where, files)] if f), None)
            if hit:
                waits.append(Wait(item["slug"], hit[0], hit[1]))
                continue
            picks.append(Pick(item["slug"], item["kind"], item["ip"], mode_of(item)))
            if len(picks) == free:
                break
    return State(capacity, running, free, picks, waits, landed_open, quiet)


def line(state: State, items: int = SETTINGS["lanes_line_items"][0]) -> Optional[str]:
    """The one line for the front; None when there is nothing to say (lanes full, or no item can start, and nothing landed)."""
    if not (state.picks or state.waits or state.landed_open):
        return None
    parts = [f"Lanes: {len(state.running)} of {state.setting} running"]
    if state.picks:
        parts.append(", ".join(f"{p.mode}: {p.slug} ({p.kind}, ip {p.ip})" for p in state.picks[:items]))
    if state.waits:
        parts.append("waits: " + ", ".join(f"{w.slug} ({w.file}, {w.branch})" for w in state.waits[:items]))
    if state.landed_open:
        parts.append("landed, still open: " + ", ".join(f"{x.slug} ({x.branch} landed)" for x in state.landed_open[:items]))
    if state.quiet:
        parts.append("no lane, not counted: " + ", ".join(state.quiet[:items]))
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
            "or say in one sentence why the lane stays free. This reply is what the owner reads last: repeat the answer you already gave in full, then add that sentence.")


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


def build_brief(item: dict, worktree: str, branch: str, scratch: str, name: str, state: State, check: str) -> str:
    """The brief of a build (a fix) printed from the item: the per-item lines; the rest is the fixed template."""
    others = [f"- {lane.branch}" + (f" ({lane.slug})" if lane.slug else "") for lane in state.running]
    lines = [f"# Build: {item['title']}", "",
             f"Worktree: {worktree} (branch {branch}). `git -C` and absolute paths; never `cd` into it.",
             f"Queue item ({item['kind']}, ip {item['ip']}): `{item['slug']}`, already taken by this branch. Read it with `relay queue show {item['slug']}`: "
             "its notes hold the owner's words and answers.", "",
             "What:", relay_queue.joined(item, "what"), "", "Why:", relay_queue.joined(item, "why")]
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
    return [(lane, touched(main, default, lane.branch, trees.get(lane.branch))) for lane in state.running]


def design_brief(item: dict, worktree: str, scratch: str, name: str) -> str:
    """The brief of a design: the item in full (the owner's words verbatim), then the fixed design steps (owner, 27 Oct: designed against the fresh repository)."""
    return "\n".join([
        f"# Design: {item['title']}", "",
        f"Worktree (fresh, for reading the code): {worktree}. `git -C` and absolute paths; never `cd` into it.",
        f"Queue item `{item['slug']}`, already taken. The item in full, the owner's words verbatim:", "",
        relay_queue.show_text(item), "",
        "Measure live data first (a script over the queue, git, the ledger); write at least two distinct approaches plus doing nothing, and how "
        "leading tools solve it; every recommendation says what it rests on (a measured number, or not measured). End with an \"Open for the owner\" "
        "list of real trade-offs only, each with options and the recommendation first. Critique the owner's own picks once, plainly.",
        f"Output: {scratch}/reports/design-{name}.md"]) + "\n"


def start(repo: str, slug: str, scratch: str, quiet_hours: int = SETTINGS["lane_quiet_hours"][0]) -> str:
    """`relay queue start <slug>`: make the worktree and branch, take the item, write its brief into `<scratch>/briefs/`, and print the
    cycle unit (JSON for the Workflow: a `change` unit for a fix, a design for a feature). Refused when no lane is free, the item is not
    open, or an owner question about it is unanswered; nothing is left behind when the take fails."""
    if not os.path.isabs(scratch):
        raise relay_queue.Refused("--scratch is an absolute folder (the session's reports/briefs folder)")
    main, default = relay_queue._context_with_relay(repo)
    state = lanes_state(main, quiet_hours)
    item = next((i for i in relay_queue.read_queue(main) if i["slug"] == slug), None)
    if item is None or item.get("problems") or item["state"] != "open":
        raise relay_queue.Refused(f"queue item '{slug}' is not an open, well-formed item of the default branch")
    if _waiting_question(item):
        raise relay_queue.Refused(f"queue item '{slug}' has an owner question without an answer: record the answer first")
    if state.free < 1:
        raise relay_queue.Refused(f"no free lane: {len(state.running)} of {state.setting} running")
    name = _short(slug)
    branch, worktree = "wt/" + name, os.path.join(main, ".worktrees", name)
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
        text = design_brief(item, worktree, scratch, name)
        unit: dict[str, Any] = {"designs": [{"name": name, "brief": brief, "out": os.path.join(scratch, "reports", f"design-{name}.md"), "review": True}]}
    else:
        brief = os.path.join(folder, f"{name}.md")
        check = _check_for(worktree, item.get("where") or [])
        text = build_brief(item, worktree, branch, scratch, name, state, check)
        unit = {"items": [{"kind": "change", "name": name, "wt": worktree, "check": check, "branch": branch, "item": slug}]}
    with open(brief, "w", encoding="utf-8") as handle:
        handle.write(text)
    waits = [f"{w.slug} waits for {w.file} ({w.branch})" for w in state.waits]
    return json.dumps({"started": slug, "branch": branch, "worktree": worktree, "brief": brief, "mode": mode, "cycle_args": unit, "other_waits": waits}, indent=2)


__all__ = ["Lane", "Pick", "Wait", "Landed", "State", "setting", "lanes_setting", "landing", "touched", "lanes_state", "line",
           "close_landed", "stop_refusal", "start", "mode_of"]
