#!/usr/bin/env python3
"""The check-mark hook (design docs/plans/review-gate.md, section 6): SubagentStop.

When `delegate:checker` finishes in a repository whose default branch has `.relay/`, this copies the checker's
verdict into a committed mark `.relay/checks/<head>.json`, with the check report (`<head>.check.md`) and the review
(`<reviewed>.review.md`, the findings files of `Check:` joined). The checker never writes a mark; no model decides
which later commits keep it. Always exits 0 (it never blocks); a failure writes no mark, removes a stale one for the
checked commit, and says why in `systemMessage`.

The checker's prompt is the delegate skill's one line:
    Check: <findings file>[, <findings file>]. Fixes: <...>. Worktree: <path>. Check command: <cmd>. Gate: <log or none>. Report: <path>.
"""
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import relay_git  # noqa: E402
import relay_marks  # noqa: E402

AGENT_TYPE = "delegate:checker"
LABELS = ("Check command", "Check", "Fixes", "Worktree", "Gate", "Report")
LABEL_RE = re.compile(r"(?:^|(?<=\s))(%s):\s" % "|".join(LABELS))
GATE_NAME = re.compile(r"^[0-9a-f]{40}\.gate\.log\Z")


class Fail(Exception):
    """A reason, in one phrase, why no mark was written."""


def say(text):
    print(json.dumps({"systemMessage": text}))


def transcript_path(hook):
    """The agent's own transcript: `agent_transcript_path`, else beside the session's (as the ledger hook does)."""
    path = hook.get("agent_transcript_path")
    if path and os.path.isfile(path):
        return path
    session = hook.get("transcript_path") or ""
    aid = "".join(ch for ch in str(hook.get("agent_id") or "") if ch.isalnum() or ch in "-_")
    if session.endswith(".jsonl") and aid:
        candidate = os.path.join(session[:-len(".jsonl")], "subagents", "agent-%s.jsonl" % aid)
        if os.path.isfile(candidate):
            return candidate
    return None


def first_entry(path):
    """(prompt text, start time as epoch seconds or None) of the transcript's first line."""
    try:
        with open(path, encoding="utf-8") as handle:
            first = handle.readline()
    except OSError:
        raise Fail("the checker's transcript cannot be read")
    try:
        entry = json.loads(first)
    except ValueError:
        raise Fail("the checker's transcript does not start with a prompt")
    content = (entry.get("message") or {}).get("content") if isinstance(entry, dict) else None
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str) or not content.strip():
        raise Fail("the checker's transcript does not start with a prompt")
    start = None
    stamp = entry.get("timestamp")
    if isinstance(stamp, str):
        try:
            start = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            start = None
    return content, start


def clean_value(text):
    text = text.strip().replace("`", "").strip()
    return text[:-1].rstrip() if text.endswith(".") else text


def parse_prompt(prompt):
    """{label: value} of the labels in the prompt's check line (each value stripped of backticks and a final period)."""
    found = {}
    marks = list(LABEL_RE.finditer(prompt))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(prompt)
        found.setdefault(m.group(1), clean_value(prompt[m.end():end]))
    return found


def resolve(base, name):
    return name if os.path.isabs(name) else os.path.join(base, name)


def last_verdict(report):
    """{head, reviewed, open, queued} from the last `## Verdict` block of the report; Fail when it is not whole."""
    lines = report.splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip() == "## Verdict"]
    if not starts:
        raise Fail("the report has no ## Verdict block")
    got = {}
    for line in lines[starts[-1] + 1:]:
        if line.startswith("#"):
            break
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("head", "reviewed", "open", "queued"):
            got.setdefault(parts[0], parts[1])
    missing = [k for k in ("head", "reviewed", "open", "queued") if k not in got]
    if missing:
        raise Fail("the verdict lacks %s" % ", ".join(missing))
    for key in ("head", "reviewed"):
        if not relay_marks.is_sha(got[key]):
            raise Fail("verdict %s is not a full sha: %s" % (key, got[key]))
    for key in ("open", "queued"):
        if not re.match(r"^\d+\Z", got[key]):
            raise Fail("verdict %s is not a number: %s" % (key, got[key]))
        got[key] = int(got[key])
    return got


def stale_commits(wt):
    """Commits whose mark a failed re-check must remove: HEAD, and the newest marked ancestor when only
    `.relay/checks/` files came after it (a mark commit does not change the checked code)."""
    found = []
    rc, head = relay_git.git(wt, "rev-parse", "HEAD")
    if rc == 0:
        found.append(head)
    newest = relay_marks.newest(wt, "HEAD", relay_marks.marks(wt, "HEAD"))
    if newest and newest[0] not in found:
        rc, names = relay_git.git(wt, "diff", "--name-only", "--no-renames", "%s..HEAD" % newest[0])
        if rc == 0 and all(n.startswith(relay_marks.FOLDER + "/") for n in names.splitlines()):
            found.append(newest[0])
    return found


def run(hook):
    cwd = hook.get("cwd")
    if hook.get("agent_type") != AGENT_TYPE or not isinstance(cwd, str) or not os.path.isdir(cwd):
        return None
    if not relay_git.has_relay(cwd):
        return None
    wt = None
    try:
        path = transcript_path(hook)
        if path is None:
            raise Fail("the checker's transcript was not found")
        prompt, start = first_entry(path)
        labels = parse_prompt(prompt)
        if not labels.get("Check") or not labels.get("Worktree"):
            raise Fail("the checker's prompt has no Check:/Worktree: line; start it with the delegate skill's check prompt, never a brief file")
        wt = os.path.realpath(labels["Worktree"])
        if not os.path.isdir(wt) or relay_git.main_checkout(wt) != relay_git.main_checkout(cwd):
            raise Fail("the prompt's Worktree is not a worktree of this repository")
        if not labels.get("Report"):
            raise Fail("the checker's prompt has no Report: line")
        report_path = resolve(wt, labels["Report"])
        try:
            report = open(report_path, encoding="utf-8").read()
            mtime = os.path.getmtime(report_path)
        except OSError:
            raise Fail("the report %s cannot be read" % labels["Report"])
        if start is not None and mtime < start:
            raise Fail("the report is older than the checker's start")
        verdict = last_verdict(report)
        for key in ("head", "reviewed"):
            if relay_git.git(wt, "cat-file", "-e", verdict[key] + "^{commit}")[0] != 0:
                raise Fail("verdict %s %s is not a commit of this worktree" % (key, verdict[key]))
        if relay_git.git(wt, "merge-base", "--is-ancestor", verdict["head"], "HEAD")[0] != 0:
            raise Fail("verdict head %s is not the worktree's head or an ancestor of it" % verdict["head"])
        review = []
        for name in [n.strip() for n in labels["Check"].split(",") if n.strip()]:
            try:
                review.append("# %s\n\n%s" % (os.path.basename(name), open(resolve(wt, name), encoding="utf-8").read().rstrip()))
            except OSError:
                raise Fail("the findings file %s cannot be read" % name)
        gate_name = os.path.basename(labels.get("Gate", ""))
        gate = gate_name if GATE_NAME.match(gate_name) and os.path.isfile(os.path.join(wt, relay_marks.FOLDER, gate_name)) else None
        head, reviewed = verdict["head"], verdict["reviewed"]
        mark = {
            "commit": head,
            "verdict": {"open": verdict["open"], "queued": verdict["queued"], "reviewed": reviewed},
            "review": "%s.review.md" % reviewed,
            "check": "%s.check.md" % head,
            "gate": gate,
            "time": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        files = {mark["review"]: "\n\n".join(review) + "\n", mark["check"]: report}
        relay_marks.put(wt, head, mark, files)
        return "check mark written for %s: %s, open %d, queued %d" % (relay_git.current_branch(wt) or wt, head, verdict["open"], verdict["queued"])
    except (Fail, relay_marks.MarkError) as exc:
        label = (relay_git.current_branch(wt) if wt and os.path.isdir(wt) else None) or "this worktree"
        if wt and os.path.isdir(wt):
            try:
                for commit in stale_commits(wt):
                    relay_marks.drop(wt, commit)
            except relay_marks.MarkError as drop_exc:
                return "check mark not written for %s: %s; the old mark could not be removed: %s" % (label, exc, drop_exc)
        return "check mark not written for %s: %s" % (label, exc)


def main():
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    if isinstance(hook, dict):
        text = run(hook)
        if text:
            say(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
