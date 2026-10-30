"""Linux and Mac gate results compared on the same code, per wave (design each-change-is-gated-in-a-fresh-container, rev 2, section 7).

Only reads: the landing events, the gate logs, the watch, twin and re-run files and the paid run's `synced` events. Nothing is stored; a
pair, a verdict, a wave and the streak are computed when read. The Mac keeps deciding merges; this module only counts how often the Linux
gate on the gate host said the same thing about the same code. Shown by `relay hosts status` and `relay hosts compare [--waves N]`."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import relay_git
import relay_gate_ssh
import relay_hosts
import relay_inert
import relay_land
import relay_marks
import relay_paid
from relay_gate_logs import MAC_SUFFIX, REMOTE_SUFFIX, _exit_code, first_failure

DEFAULT_WAVES = 3
WAVES_BOUNDS = (1, 20)
TWIN_DIR = "twin"
AGREE, FLAKY, LINUX_RED, MAC_FLAKY, MAC_RED, MAC_OPEN, NONE = "agree", "linux-flaky", "linux-red", "mac-flaky", "mac-red", "mac-open", "none"
BREAKS = (LINUX_RED, MAC_RED)       # the verdicts that end the run of agreeing pairs
OPEN = (NONE, MAC_OPEN)             # counted as unresolved: neither agreement nor disagreement


def _red(code: Optional[int]) -> bool:
    return code is not None and 0 < code < 127 and code != 124


def run_name(sha: str, k: int) -> str:
    """The file of run k of a commit: the first run keeps today's name, a re-run is `<sha>.rerun-<k>` (k = 1, 2, 3)."""
    return sha + REMOTE_SUFFIX if k == 0 else "%s.rerun-%d%s" % (sha, k, REMOTE_SUFFIX)


def run_files(folder: str, sha: str) -> list[str]:
    """The remote run files of `sha` in `folder`, oldest first: the first run, then its re-runs."""
    paths = [os.path.join(folder, run_name(sha, k)) for k in range(0, relay_hosts.SETTINGS["rerun_disagreement"][2] + 1)]
    return [p for p in paths if os.path.isfile(p)]


def _lines(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def _line(main: str, ref: str) -> list[str]:
    """The first-parent commits of `ref`, newest first; [] when the ref does not exist."""
    rc, out = relay_git.git(main, "rev-list", "--first-parent", ref)
    return out.split() if rc == 0 else []


def stretch(main: str, sha: str, refs: tuple[str, ...] = ()) -> list[str]:
    """The commits that hold the same code as `sha`, newest first: the later commits of `refs` (each a first-parent line holding `sha`) up to
    the first non-inert change after it, then `sha` and the commits before it on its own first-parent line back to the first commit after
    which a non-inert file changed."""
    found: list[str] = []
    for ref in refs:
        line = _line(main, ref)
        if sha in line:
            later: list[str] = []
            for commit in reversed(line[:line.index(sha)]):      # oldest first, so the walk stops at the first code change
                if relay_inert.changed(main, sha, commit):
                    break
                later.append(commit)
            found += [c for c in reversed(later) if c not in found]
    for commit in _line(main, sha):
        if relay_inert.changed(main, commit, sha):
            break
        found.append(commit)
    return found


@dataclass
class Linux:
    codes: list[int]      # exit codes of the runs of the commit that decides, oldest first (first run, re-runs)
    path: str             # the newest run's file

    @property
    def code(self) -> int:
        return self.codes[-1]


def linux_result(main: str, sha: str, refs: tuple[str, ...] = ()) -> Optional[Linux]:
    """The Linux result of `sha`: the newest remote run of its inert stretch (a committed build-time log, a watch file, a twin file or a
    re-run of any of them). None when there is none, or when the newest run reached no verdict (a stop at the limit, a kill)."""
    linux = relay_gate_ssh.linux_dir(main)
    places = (linux, os.path.join(linux, TWIN_DIR), os.path.join(main, relay_marks.FOLDER))
    for commit in stretch(main, sha, refs):
        best: list[str] = []
        for place in places:
            files = run_files(place, commit)
            if len(files) > len(best):
                best = files
        if not best:
            continue
        codes = [_exit_code(_lines(p)) for p in best]
        if codes[-1] is None or not (codes[-1] == 0 or _red(codes[-1])):
            return None
        return Linux([c for c in codes if c is not None], best[-1])
    return None


def step_of(path: str) -> str:
    """The first failing step of a log file, "" when the log has none."""
    lines = _lines(path)
    start = next((i for i, line in enumerate(lines) if line.startswith("host ")), 3)
    block = first_failure("\n".join(lines[start + 1:-1])) if len(lines) > start + 1 else []
    return block[0].strip() if block else ""


def _mac_code(main: str, ref: str, commit: str) -> Optional[int]:
    rc, text = relay_git.git(main, "show", "%s:%s/%s%s" % (ref, relay_marks.FOLDER, commit, MAC_SUFFIX))
    lines = text.splitlines() if rc == 0 else []
    code = _exit_code(lines) if lines and lines[0] == "head %s" % commit else None
    return code if code == 0 or _red(code) else None


def mac_next(main: str, default: str, judged: str, branch: str) -> Optional[int]:
    """The exit of the next Mac gate of the same code as `judged`, on the branch the red event names or on the default branch: a gate log of a
    later commit whose inert stretch holds `judged`. No new Mac run is ever made for this."""
    for ref in (branch, default):
        if not ref or relay_git.git(main, "rev-parse", "--verify", "-q", "refs/heads/" + ref)[0] != 0:
            continue
        rc, out = relay_git.git(main, "rev-list", "--first-parent", "refs/heads/" + ref)
        line = out.split() if rc == 0 else []
        if judged not in line:
            continue
        for commit in reversed(line[:line.index(judged)]):
            if relay_inert.changed(main, judged, commit):
                break
            code = _mac_code(main, "refs/heads/" + ref, commit)
            if code is not None:
                return code
    return None


@dataclass
class Entry:
    ts: datetime
    sha: str
    branch: str
    mac_red: bool
    verdict: str
    note: str = ""      # the step, or why there is no Linux result


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _refs(default: str, branch: str) -> tuple[str, ...]:
    return ("refs/heads/" + default, *(("refs/heads/" + branch,) if branch else ()))


def _entry(main: str, default: str, event: relay_land.Event, reruns: int, host: relay_hosts.Host, stop: bool) -> Entry:
    red = event.outcome == relay_land.RED
    sha = (event.judged if red else event.sha) or ""
    entry = Entry(_when(event.ts), sha, event.branch, red, NONE)
    linux = linux_result(main, sha, _refs(default, event.branch))
    if linux is None:
        entry.note = "sending stopped" if stop else "not twinned" if red and not host.twin_red_landings else ""
        return entry
    if red:
        if _red(linux.code):
            entry.verdict = AGREE
            return entry
        code = mac_next(main, default, sha, event.branch)
        entry.verdict = MAC_OPEN if code is None else MAC_FLAKY if code == 0 else MAC_RED
        return entry
    if linux.code == 0:
        entry.verdict = FLAKY if any(_red(c) for c in linux.codes) else AGREE
        return entry
    entry.note = step_of(linux.path)
    entry.verdict = LINUX_RED if len(linux.codes) > 1 or reruns == 0 else NONE
    if entry.verdict == NONE:
        entry.note += " (re-run not finished)"
    return entry


def waves(main: str, count: int) -> list[tuple[Optional[datetime], Optional[datetime]]]:
    """The last `count` waves, newest first: the stretches between two dated `synced` events (a wave is the changes landed between two
    paid runs); with none, one group (None, None) for everything before the first recorded wave."""
    marks = sorted({_when(e.ts) for e in relay_paid.read_events(main) if e.kind == "synced"})
    if not marks:
        return [(None, None)]
    edges: list[Optional[datetime]] = [None, *marks, None]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)][::-1][:count]


def _label(start: Optional[datetime], end: Optional[datetime]) -> str:
    fmt = "%d %b %H:%MZ"
    if start is None and end is None:
        return "before the first recorded wave"
    if start is None:
        return "before the first recorded wave (until %s)" % end.strftime(fmt)      # type: ignore[union-attr]
    return "since %s" % start.strftime(fmt) if end is None else "%s-%s" % (start.strftime(fmt), end.strftime(fmt))


DETAIL = {FLAKY: "Linux-only red, flaky (green on re-run)", LINUX_RED: "Linux-only red, reproduced", MAC_FLAKY: "Mac-only red, flaky on the Mac",
          MAC_RED: "Mac-only red, reproduced on the Mac", MAC_OPEN: "Mac-only red, not re-run on the Mac (Linux green)"}


def compare_lines(repo: str, count: int = DEFAULT_WAVES, home: Optional[str] = None) -> list[str]:
    """The comparison block (design 7.1). ValueError when the repository has no default branch or no gate host is recorded."""
    main, default = relay_git.main_checkout(repo), relay_git.default_branch(repo)
    host = relay_hosts.first(home)
    if not main or not default:
        raise ValueError("%s is not in a repository with a default branch" % repo)
    if host is None:
        raise ValueError("there is no gate host in the record: relay hosts add <host>")
    stop = relay_gate_ssh.stopped(relay_gate_ssh.read_events(main, host.name), host.get("stop_after")) is not None
    reruns = host.get("rerun_disagreement")
    events = [e for e in relay_land.read_events(main)[0] if e.kind == "done" and ((e.outcome == relay_land.LANDED and e.sha) or (e.outcome == relay_land.RED and e.judged))]
    out = ["  Linux and Mac on the same code (last %d waves):" % count]
    everything: list[Entry] = []
    for start, end in waves(main, count):
        mine = [_entry(main, default, e, reruns, host, stop) for e in events
                if (start is None or _when(e.ts) >= start) and (end is None or _when(e.ts) < end)]
        everything += mine
        landed, red = sum(not m.mac_red for m in mine), sum(m.mac_red for m in mine)
        parts = ["%d landed" % landed, "%d red landings" % red, "%d agree" % sum(m.verdict == AGREE for m in mine)]
        unresolved = sum(m.verdict in OPEN for m in mine)
        if unresolved:
            parts.append("%d unresolved" % unresolved)
        out.append("    wave %s: %s" % (_label(start, end), ", ".join(parts[:2]) + "; " + parts[2] + ("; " + parts[3] if unresolved else "")))
        for m in sorted(mine, key=lambda x: x.ts, reverse=True):
            if m.verdict in DETAIL:
                out.append("      %s: %s%s" % (DETAIL[m.verdict], m.sha[:12], (" step " + m.note) if m.note else ""))
            elif m.verdict == NONE:
                out.append("      no Linux result%s: %s%s" % (" (%s)" % m.note.strip() if m.note.strip() else "", m.sha[:12], " (red landing)" if m.mac_red else ""))
    row = 0
    for m in sorted(everything, key=lambda x: x.ts, reverse=True):
        if m.verdict in BREAKS:
            break
        row += m.verdict == AGREE
    out.append("    agreeing pairs in a row: %d; %d unresolved; the Mac decides landings (owner, 29 Oct)" % (row, sum(m.verdict in OPEN for m in everything)))
    return out
