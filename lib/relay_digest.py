"""`relay digest`: one page for the owner per wave of landings, and when such a page (or a spend alert) is due.

Everything is computed from git and the queue each time; the only thing stored is a dated event when a page or an alert was sent
(`<git common dir>/relay-digest/events.jsonl`, the same pattern as relay-land). Printing never records: `--sent <sha>` does, with the head the page printed on its last line (what landed meanwhile is on the next page).

The page covers the queue difference between the default branch head stored at the last sent digest and the head now (no timestamp
inside a record decides what is new: a close is recorded on a change's branch hours before it reaches the default branch).
  Merged                items whose closed_at was empty at the start head and is set now; dropped ones are counted
  Added                 item files absent at the start head
  Decisions             decision notes an agent took, new since the start head and still unanswered, grouped by item
  Waiting               questions the owner was asked and has not answered (the same set the ask_waiting hook names), once per title
  Numbers               open items, today's paid spend, the last paid run
`--due` prints one line per reason a digest or an alert is due, nothing otherwise: a paid run ended after the last sent digest;
`digest_max_landings` landings without one; today's paid spend at `spend_alert_share` of the day's cap with no alert sent today.

Settings, in the project's .claude/kit.toml under [front] (an out-of-bounds value is clamped; a missing one is the default):
  digest_max_landings   default 15, bound 5-50     at 5 about 4 digests a day; at 50 a day without a paid run sends none
  spend_alert_share     default 0.8, bound 0.5-1.0 at 0.5 an alert at half the day's cap; at 1.0 only when bin/ci refuses at the cap
  digest_merged_lines   default 10, bound 3-40     merged titles on a page; at 40 a full day's closes fill the page
  digest_decision_lines default 30, bound 10-60    decision lines on a page; the rest are "and N more" (`--all` prints them)
Tests: tests/test_digest.py
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import datetime as dt
import json
import os
import re
import subprocess
from typing import Any, Callable, NamedTuple, Optional

import relay_config
import relay_git
import relay_inert
import relay_land
import relay_queue

SETTINGS = {"digest_max_landings": (15, 5, 50), "spend_alert_share": (0.8, 0.5, 1.0),
            "digest_merged_lines": (10, 3, 40), "digest_decision_lines": (30, 10, 60)}     # default, lowest, highest
WINDOW_HOURS = 24            # the page when no digest was sent yet, or the stored head is gone from the history
QDIR = relay_queue.QDIR
STAMP = "%Y-%m-%dT%H:%M:%SZ"
SPEND_LINE = re.compile(r"spent \$([0-9.]+) of the \$([0-9.]+) cap")
SPEND_TIMEOUT_S = 3.0
USAGE = ("relay digest [--since <sha|date>] [--all] [-C <repo>] | relay digest --due [-C <repo>] | "
         "relay digest --sent <sha> [-C <repo>] | relay digest --alert-sent [-C <repo>]")

Spend = Optional[tuple]      # (spent, cap) in USD, None when not known


class DigestError(ValueError):
    """The command cannot answer; the message names the next step."""


def setting(cfg: Any, key: str) -> Any:
    """The setting `front.<key>` clamped to its bounds; the default when missing or not a number."""
    default, low, high = SETTINGS[key]
    value = relay_config.get(cfg, "front." + key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(default, int) and not isinstance(value, int)):
        return default
    return max(low, min(high, value))


def epoch_of(stamp: str) -> float:
    return dt.datetime.strptime(stamp, STAMP).replace(tzinfo=dt.timezone.utc).timestamp()


def stamp_of(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime(STAMP)


def now_stamp() -> str:
    return stamp_of(dt.datetime.now(dt.timezone.utc).timestamp())


def show_time(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%-d %b %H:%M UTC")


# ---------------------------------------------------------------- git and the events

def git(main: str, *args: str) -> Optional[str]:
    """The output of a git read, None when git fails."""
    code, out = relay_git.git(main, *args)
    return out if code == 0 else None


def head_of(main: str, default: str) -> str:
    sha = git(main, "rev-parse", "--verify", "-q", "refs/heads/" + default)
    if not sha:
        raise DigestError("no local branch %s: the digest reads the default branch" % default)
    return sha


def events_file(main: str) -> str:
    common = git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        raise DigestError("not a git repository")
    return os.path.join(common, "relay-digest", "events.jsonl")


def read_events(main: str) -> "list[dict]":
    """The recorded events, oldest first: {"kind": "sent" | "alert", "at": UTC time, "head": sha}. A line that is not one is skipped
    (the file is written only by `record_event`; a torn last line must not hide the earlier ones)."""
    out: "list[dict]" = []
    try:
        with open(events_file(main), encoding="utf-8") as handle:
            for text in handle:
                try:
                    row = json.loads(text)
                except ValueError:
                    continue
                if (isinstance(row, dict) and row.get("kind") in ("sent", "alert") and isinstance(row.get("at"), str)
                        and isinstance(row.get("head"), str)):
                    out.append(row)
    except OSError:
        pass
    return out


def record_event(main: str, kind: str, at: str, head: str) -> None:
    path = events_file(main)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": kind, "at": at, "head": head}) + "\n")


class Start(NamedTuple):
    sha: Optional[str]       # None: no commit that old, everything counts as new
    epoch: float             # the time the page starts from
    note: str = ""           # why it is not the stored head ("" when it is)


def first_parent_before(main: str, head: str, epoch: float) -> Optional[str]:
    sha = git(main, "rev-list", "--first-parent", "-1", "--before=" + stamp_of(epoch), head)
    return sha or None


def commit_time(main: str, sha: str) -> float:
    out = git(main, "log", "-1", "--format=%ct", sha)
    if not out or not out.isdigit():
        raise DigestError("cannot read the time of commit %s" % sha[:8])
    return float(out)


def date_epoch(text: str) -> Optional[float]:
    for form in (STAMP, "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, form).replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def window_start(main: str, head: str, now: float, note: str = "") -> Start:
    epoch = now - WINDOW_HOURS * 3600
    return Start(first_parent_before(main, head, epoch), epoch, note)


def resolve_start(main: str, head: str, events: "list[dict]", since: Optional[str], now: float) -> Start:
    """Where the page starts: `since` (a commit, or a date: the first-parent commit at that time), else the head of the last sent
    digest, else the first-parent commit of 24 h ago. A stored head that is not an ancestor of the head falls back to 24 h, said."""
    if since is not None:
        sha = git(main, "rev-parse", "--verify", "-q", since + "^{commit}")
        if sha:
            if not relay_git.is_ancestor(main, sha, head):
                return window_start(main, head, now, "%s is not on the default branch history: covering the last %d h" % (since, WINDOW_HOURS))
            return Start(sha, commit_time(main, sha))
        epoch = date_epoch(since)
        if epoch is None:
            raise DigestError("--since is a commit or a date like 2026-10-30 (or 2026-10-30T04:40:00Z); got '%s'" % since)
        return Start(first_parent_before(main, head, epoch), epoch)
    sent = [e for e in events if e["kind"] == "sent"]
    if not sent:
        return window_start(main, head, now)
    last = sent[-1]
    if git(main, "rev-parse", "--verify", "-q", last["head"] + "^{commit}") and relay_git.is_ancestor(main, last["head"], head):
        return Start(last["head"], commit_time(main, last["head"]))
    return window_start(main, head, now, "the head stored at the last digest (%s) is not on the default branch history: covering the last %d h"
                        % (last["head"][:8], WINDOW_HOURS))


# ---------------------------------------------------------------- the queue difference

def queue_items(main: str, rev: str, slugs: "list[str]") -> "dict[str, dict]":
    """The well-formed items among `slugs` at `rev` (a missing or malformed file is absent)."""
    blobs = relay_queue.cat_batch(main, ["%s:%s/%s.json" % (rev, QDIR, s) for s in slugs])
    out: "dict[str, dict]" = {}
    for slug, blob in zip(slugs, blobs):
        if blob is None:
            continue
        item = relay_queue.parse(slug, blob.decode("utf-8", "replace"))
        if not item["problems"]:
            out[slug] = item
    return out


def changed_slugs(main: str, start: Optional[str], head: str) -> "list[str]":
    if start is None:
        return relay_queue.Reader(main, head).names()
    out = git(main, "diff", "--name-only", start, head, "--", QDIR)
    if out is None:
        raise DigestError("git could not compare the queue between %s and %s" % (start[:8], head[:8]))
    return sorted({os.path.basename(p)[:-5] for p in out.splitlines() if p.endswith(".json") and os.path.dirname(p) == QDIR})


class Decision(NamedTuple):
    slug: str
    title: str
    merged: bool
    note: Any


class Changes(NamedTuple):
    merged: "list[dict]"
    dropped: int
    added: "list[dict]"
    decisions: "list[Decision]"


def agent_decisions(item: dict) -> "list[Any]":
    return [n for n in relay_queue.notes_of(item) if n.kind == "decision" and n.decided_by and n.answered_at is None]


def changes(main: str, start: Optional[str], head: str) -> Changes:
    """The queue at `head` against the queue at `start`, for the items that differ."""
    slugs = changed_slugs(main, start, head)
    after = queue_items(main, head, slugs)
    before = queue_items(main, start, slugs) if start else {}
    merged, added, decisions, dropped = [], [], [], 0
    for slug in slugs:
        now_item, was = after.get(slug), before.get(slug)
        if now_item is None:
            continue
        if was is None:
            added.append(now_item)
        if now_item.get("closed_at") and not (was or {}).get("closed_at"):
            merged.append(now_item)
        if now_item.get("dropped_at") and not (was or {}).get("dropped_at"):
            dropped += 1
        known = {n.at for n in agent_decisions(was)} if was else set()
        for n in agent_decisions(now_item):
            if n.at not in known:
                decisions.append(Decision(slug, now_item["title"], bool(now_item.get("closed_at")), n))
    merged.sort(key=lambda i: (i["closed_at"], i["slug"]))
    return Changes(merged, dropped, added, sorted(decisions, key=lambda d: (d.slug, d.note.at)))


# ---------------------------------------------------------------- the paid side

def evals_dir(main: str) -> str:
    home = os.path.expanduser(os.environ.get("RELAY_HOME") or "~/.relay")
    return os.path.join(home, "evals", os.path.basename(main))


class PaidRun(NamedTuple):
    ended: float
    passed: int
    total: int
    partial: bool


def paid_runs(folder: str, default: str) -> "list[PaidRun]":
    """The stored paid runs on the default branch (any outcome), oldest end first. A record that does not have the fields is skipped,
    and so is one of another branch (a branch run does not end a wave)."""
    out: "list[PaidRun]" = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                rec = json.load(handle)
            started = dt.datetime.strptime(rec["startedAt"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
            if rec.get("branch", default) != default:
                continue
            agg = rec["aggregates"]
            out.append(PaidRun(started + float(rec["durationSeconds"]), int(agg["casesPassed"]), int(agg["casesTotal"]), bool(rec.get("partial"))))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out)


def project_spend(main: str) -> Spend:
    """(spent, cap) of the UTC day from the project's own bin/paid-cost, None when it has none or does not answer in time."""
    tool = os.path.join(main, "bin", "paid-cost")
    if not os.access(tool, os.X_OK):
        return None
    try:
        done = subprocess.run([tool, "today"], cwd=main, capture_output=True, text=True, timeout=SPEND_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    found = SPEND_LINE.search(done.stdout) if done.returncode == 0 else None
    return (float(found.group(1)), float(found.group(2))) if found else None


# ---------------------------------------------------------------- the page

def option_text(options: "list[str]", letter: str) -> str:
    index = ord(letter) - 97
    return options[index][3:] if 0 <= index < len(options) else letter


def decision_lines(decisions: "list[Decision]", room: int) -> "tuple[list[str], int]":
    """The decisions grouped by item, at most `room` decision lines; (lines, how many decisions were left out)."""
    lines: "list[str]" = []
    shown = 0
    last = None
    for d in decisions:
        if shown >= room:
            break
        if d.slug != last:
            lines.append("  %s (%s)" % (d.title, "merged" if d.merged else "not merged yet"))
            last = d.slug
        n = d.note
        because = " ".join(x.strip() for x in n.because)
        lines.append("    **%s** chosen %s. %s (%s: %s)" % (relay_queue.question_title(n), n.chosen, option_text(n.options, n.chosen), n.decided_by, because))
        shown += 1
    return lines, len(decisions) - shown


def waiting_for_owner(items: "dict[str, dict]") -> "list[tuple[str, str]]":
    """(asked time, title) of each question the owner has not answered, a title once (the oldest), oldest first."""
    seen: "dict[str, str]" = {}
    for item in items.values():
        for n in relay_queue.owner_waiting(relay_queue.notes_of(item)):
            title = relay_queue.question_title(n)
            if title not in seen or n.at < seen[title]:
                seen[title] = n.at
    return sorted((at, title) for title, at in seen.items())


def numbers_line(items: "dict[str, dict]", spend: Spend, runs: "list[PaidRun]") -> str:
    open_items = [i for i in items.values() if i.get("state") in ("open", "taken")]
    parts = ["open %d fix, %d feature" % tuple(sum(1 for i in open_items if i["kind"] == k) for k in relay_queue.KINDS)]
    parts.append("paid today $%.2f of $%g" % spend if spend else "paid spend today not known")
    if runs:
        last = runs[-1]
        parts.append("last paid run %d of %d cases passed%s (%s)" % (last.passed, last.total, ", partial" if last.partial else "", show_time(last.ended)))
    else:
        parts.append("no paid run recorded")
    return "Numbers: " + "; ".join(parts) + "."


def page(main: str, default: str, cfg: Any, since: Optional[str] = None, show_all: bool = False, now: Optional[str] = None,
         spend: Optional[Callable[[], Spend]] = None, evals: Optional[str] = None) -> "list[str]":
    """The digest as lines. Reads only; the caller records the delivery with `record_event`."""
    clock = epoch_of(now or now_stamp())
    head = head_of(main, default)
    start = resolve_start(main, head, read_events(main), since, clock)
    diff = changes(main, start.sha, head)
    items = relay_queue.Reader(main, head).items()
    waiting = waiting_for_owner(items)
    room = len(diff.decisions) if show_all else setting(cfg, "digest_decision_lines")
    shown_decisions, left = decision_lines(diff.decisions, room)
    since_text = "since %s" % show_time(start.epoch)
    quiet = not (diff.merged or diff.added or diff.decisions or diff.dropped)
    lines = []
    if start.note:
        lines.append("note: " + start.note)
    if quiet:
        lines.append("relay: nothing new %s." % since_text)
    else:
        lines.append("relay: %s: %d merged, %d added, %d decisions taken without you, %d question%s wait." %
                     (since_text, len(diff.merged), len(diff.added), len(diff.decisions), len(waiting), "" if len(waiting) == 1 else "s"))
    if diff.merged or diff.dropped:
        counts = ", ".join("%s %d" % (k, sum(1 for i in diff.merged if i["kind"] == k)) for k in relay_queue.KINDS)
        lines.append("Merged (%s)%s:" % (counts, "; dropped %d" % diff.dropped if diff.dropped else ""))
        cap = setting(cfg, "digest_merged_lines")
        lines += ["  - " + i["title"] for i in diff.merged[:cap]]
        if len(diff.merged) > cap:
            lines.append("  ... and %d more" % (len(diff.merged) - cap))
    if diff.decisions:
        lines.append("Decisions taken without you (answer by title to reverse):")
        lines += shown_decisions
        if left:
            lines.append("  and %d more decisions: relay digest --all" % left)
    if waiting:
        lines.append("Waiting for you: " + "; ".join("**%s** (asked %s)" % (title, show_time(epoch_of(at))) for at, title in waiting))
    lines.append(numbers_line(items, (spend or (lambda: project_spend(main)))(), paid_runs(evals or evals_dir(main), default)))
    lines.append("Page head %s: after sending, run relay digest --sent %s" % (head[:8], head[:8]))
    return lines


# ---------------------------------------------------------------- when something is due

def landings(main: str, since: float) -> int:
    """Changes landed by `relay land` after `since` (epoch): one landed `done` event each, counted only when the landing moved a file
    that is not inert (a queue-only or handover-only landing is no landing). A fast-forward puts every commit of the branch on the
    default branch's first-parent chain, so commits cannot be counted."""
    count = 0
    for event in relay_land.read_events(main)[0]:
        if event.kind != "done" or event.outcome != relay_land.LANDED or dt.datetime.fromisoformat(event.ts).timestamp() <= since:
            continue
        names = git(main, "diff", "--name-only", event.before, event.sha) if event.before and event.sha else None
        if names is None or any(not relay_inert.matches(n) for n in names.splitlines()):      # git cannot tell: count it
            count += 1
    return count


def due(main: str, default: str, cfg: Any, now: Optional[str] = None, spend: Optional[Callable[[], Spend]] = None,
        evals: Optional[str] = None) -> "list[str]":
    """One line per reason a digest or an alert is due now; [] when none."""
    clock = epoch_of(now or now_stamp())
    head_of(main, default)       # no local default branch: the same refusal as the page
    events = read_events(main)
    sent = [e for e in events if e["kind"] == "sent"]
    since = epoch_of(sent[-1]["at"]) if sent else clock - WINDOW_HOURS * 3600
    lines: "list[str]" = []
    ended = [r for r in paid_runs(evals or evals_dir(main), default) if r.ended > since]
    if ended:
        lines.append("digest due: a paid run ended %s" % show_time(ended[-1].ended))
    count = landings(main, since)
    limit = setting(cfg, "digest_max_landings")
    if count >= limit:
        lines.append("digest due: %d landings since the last digest (limit %d)" % (count, limit))
    today = stamp_of(clock)[:10]
    if not any(e["kind"] == "alert" and e["at"][:10] == today for e in events):
        known = (spend or (lambda: project_spend(main)))()
        share = setting(cfg, "spend_alert_share")
        if known and known[1] > 0 and known[0] >= share * known[1]:
            lines.append("alert due: paid spend today $%.2f is at %d%% of the $%g cap (alert at %d%%)" % (known[0], known[0] / known[1] * 100, known[1], share * 100))
    return lines


# ---------------------------------------------------------------- the command

def take_flag(args: "list[str]", flag: str) -> Optional[str]:
    if flag not in args:
        return None
    i = args.index(flag)
    if i + 1 >= len(args):
        raise DigestError(USAGE)
    value = args[i + 1]
    del args[i:i + 2]
    return value


def main(args: "list[str]", out: Callable[[str], None] = print) -> int:
    """`relay digest ...`; prints the page or the due lines. Exit 0, or 2 for a usage error (DigestError)."""
    args = list(args)
    repo = take_flag(args, "-C") or "."
    since = take_flag(args, "--since")
    if "--sent" in args and args.index("--sent") + 1 >= len(args):
        raise DigestError("relay digest --sent needs the head the page printed: take <sha> from the page's last line (\"Page head <sha>\"), "
                          "run relay digest --sent <sha>")
    sent_sha = take_flag(args, "--sent")
    modes = [f for f in ("--due", "--alert-sent", "--all") if f in args] + (["--sent"] if sent_sha is not None else [])
    for flag in modes:
        if flag in args:
            args.remove(flag)
    if args or (len(modes) > 1 and "--all" not in modes) or (since is not None and any(m in modes for m in ("--due", "--sent", "--alert-sent"))):
        raise DigestError(USAGE)
    main_dir = relay_git.main_checkout(repo)
    default = relay_git.default_branch(repo)
    if main_dir is None or default is None or not relay_git.has_relay(repo):
        raise DigestError("this is not a relay project (no git repository, default branch or .relay/ folder)")
    cfg = relay_config.load_bindings(main_dir)
    if "--sent" in modes or "--alert-sent" in modes:
        kind = "sent" if "--sent" in modes else "alert"
        head = head_of(main_dir, default)
        if sent_sha is not None:
            full = git(main_dir, "rev-parse", "--verify", "-q", sent_sha + "^{commit}")
            if not full or not relay_git.is_ancestor(main_dir, full, head):
                raise DigestError("%s is not a commit on the %s history: take <sha> from the last line of the page (\"Page head <sha>\")"
                                  % (sent_sha, default))
            head = full
        record_event(main_dir, kind, now_stamp(), head)
        out("recorded: %s at %s" % ("digest sent" if kind == "sent" else "spend alert sent", now_stamp()))
        return 0
    if "--due" in modes:
        for line in due(main_dir, default, cfg):
            out(line)
        return 0
    for line in page(main_dir, default, cfg, since=since, show_all="--all" in modes):
        out(line)
    return 0
