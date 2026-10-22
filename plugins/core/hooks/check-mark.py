#!/usr/bin/env python3
"""The check-mark hook (design docs/plans/review-gate.md, section 6): SubagentStop.

When `delegate:checker` finishes in a repository whose default branch has `.relay/`, this copies the checker's
recorded data into a committed mark `.relay/checks/<head>.json`, with the check report and its data (`<head>.check.md`,
`<head>.check.json`) and the review (`<reviewed>.review.md` and `.review.json`, the review data of each findings file
joined). The facts come only from the JSON that `relay check record check` wrote beside the report (the worktree, the
head, the reviewed sha, the gate log, the review data files, open, queued); the prose of the report and the prompt are
never parsed for them. The prompt gives one thing, the `Report: <path>` label, to find that JSON. The checker never
writes a mark; no model decides which later commits keep it. Always exits 0 (it never blocks); a missing or invalid
JSON writes no mark, removes a stale one for the checked commit, and says why in `systemMessage`.

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
import relay_verdict  # noqa: E402

AGENT_TYPE = "delegate:checker"
WORKTREE_RE = re.compile(r"(?:^|(?<=\s))Worktree:\s+([^\s]+)")
REPORT_RE = re.compile(r"(?:^|(?<=\s))Report:\s+(.*)")
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


def report_label(prompt):
    """The value of the prompt's last `Report:` label (first line of what follows, backticks and a final period
    stripped), or None."""
    found = REPORT_RE.findall(prompt)
    return clean_value(found[-1]) if found and clean_value(found[-1]) else None


def worktree_label(prompt):
    found = WORKTREE_RE.findall(prompt or "")
    return clean_value(found[-1]) if found else None


def resolve(base, name):
    return name if os.path.isabs(name) else os.path.join(base, name)


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read(), os.path.getmtime(path)
    except OSError:
        raise Fail("%s %s cannot be read; the checker must run relay check record check" % (what, path))


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
    prompt = ""
    try:
        path = transcript_path(hook)
        if path is None:
            raise Fail("the checker's transcript was not found")
        prompt, start = first_entry(path)
        label = report_label(prompt)
        if not label:
            raise Fail("the checker's prompt has no Report: line; start it with the delegate skill's check prompt, never a brief file")
        report_path = resolve(cwd, label)
        data_path = relay_verdict.json_path(report_path)
        text, mtime = read_json(data_path, "the check data")
        if start is not None and mtime < start:
            raise Fail("the check data is older than the checker's start")
        try:
            data = relay_verdict.load_check(text, "the check data %s" % data_path)
        except relay_verdict.VerdictError as exc:
            raise Fail(str(exc))
        wt = os.path.realpath(data["worktree"])
        if not os.path.isdir(wt) or relay_git.main_checkout(wt) != relay_git.main_checkout(cwd):
            raise Fail("the check data's worktree is not a worktree of this repository")
        try:
            report = open(report_path, encoding="utf-8").read()
        except OSError:
            raise Fail("the report %s cannot be read" % label)
        head, reviewed = data["head"], data["reviewed"]
        for key in ("head", "reviewed"):
            if relay_git.git(wt, "cat-file", "-e", data[key] + "^{commit}")[0] != 0:
                raise Fail("%s %s is not a commit of this worktree" % (key, data[key]))
        if relay_git.git(wt, "merge-base", "--is-ancestor", head, "HEAD")[0] != 0:
            raise Fail("head %s is not the worktree's head or an ancestor of it" % head)
        reviews, review_md = [], []
        for path in data["review"]:
            rtext, _ = read_json(path, "the review data")
            try:
                review = relay_verdict.load_review(rtext, "the review data %s" % path)
            except relay_verdict.VerdictError as exc:
                raise Fail(str(exc))
            if review["reviewed"] != reviewed:
                raise Fail("the review data %s is of %s, not of the reviewed sha %s" % (path, review["reviewed"], reviewed))
            base = path[:-len(".json")] if path.endswith(".json") else path
            md = base + ".md" if os.path.isfile(base + ".md") else base
            name = os.path.basename(md)
            try:
                review_md.append("# %s\n\n%s" % (name, open(md, encoding="utf-8").read().rstrip()))
            except OSError:
                raise Fail("the findings file %s cannot be read" % md)
            reviews.append(dict(review, file=name))
        gate_name = os.path.basename(data["gate"] or "")
        gate = gate_name if GATE_NAME.match(gate_name) and os.path.isfile(os.path.join(wt, relay_marks.FOLDER, gate_name)) else None
        mark = {
            "commit": head,
            "verdict": {"open": data["open"], "queued": data["queued"], "reviewed": reviewed},
            "review": "%s.review.md" % reviewed,
            "review_data": "%s.review.json" % reviewed,
            "check": "%s.check.md" % head,
            "check_data": "%s.check.json" % head,
            "gate": gate,
            "time": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        dump = lambda obj: json.dumps(obj, indent=2, sort_keys=True) + "\n"
        files = {mark["review"]: "\n\n".join(review_md) + "\n", mark["check"]: report,
                 mark["review_data"]: dump(relay_verdict.stored_set(reviews, reviewed)),
                 mark["check_data"]: dump(relay_verdict.stored_check(data, mark["review_data"]))}
        relay_marks.put(wt, head, mark, files)
        return "check mark written for %s: %s, open %d, queued %d" % (relay_git.current_branch(wt) or wt, head, data["open"], data["queued"])
    except (Fail, relay_marks.MarkError) as exc:
        if wt is None:
            # the data could not be read, so the worktree is not known from it: the prompt's Worktree: label only says
            # where a stale mark of the same worktree may sit to be removed (no fact of a mark comes from it)
            hint = worktree_label(prompt)
            wt = os.path.realpath(hint) if hint and os.path.isdir(hint) and relay_git.main_checkout(hint) == relay_git.main_checkout(cwd) else None
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
