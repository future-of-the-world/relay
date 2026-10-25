#!/usr/bin/env python3
"""The check-mark hook (design docs/plans/review-gate.md, section 6): SubagentStop.

When `delegate:checker` finishes in a repository whose default branch has `.relay/`, this copies the checker's
recorded check record into a committed mark `.relay/checks/<head>.json`, with the record itself (`<head>.check.json`: the
item's problem, the reviews' findings, one verdict for each, the gate). Only JSON is stored: no readable report
is written (`relay check show` renders one on demand). The facts come only from the JSON that `relay check record check`
wrote at the `Report:` path, loaded with `relay_verdict.load_record`; the hook applies no rule of its own and counts
nothing (`open` and `queued` are derived from the record). The prompt is never parsed for them. The prompt gives one thing, the `Report: <path>` label (the check's JSON
file), to find that JSON. The checker never writes a mark; no model decides which later commits keep it. Always exits 0 (it never blocks); a missing or invalid
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


def entry_text(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) else ""


def entry_start(entry):
    stamp = entry.get("timestamp")
    if isinstance(stamp, str):
        try:
            return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def first_entry(path):
    """(prompt text, start time as epoch seconds or None) of the last user entry that carries a `Report:` label among
    the transcript's leading user entries (before the first assistant entry): a workflow puts its own relayed request
    first and the checker's prompt next. With no label there, the first user entry (its prompt has no label)."""
    first = labelled = None
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    entry = None
                if not isinstance(entry, dict) or not isinstance(entry.get("message") or {}, dict):
                    if first is None and labelled is None:  # a prompt (labelled or not) was seen: skip attachments
                        raise Fail("the checker's transcript does not start with a prompt")
                    continue
                if entry.get("type") == "assistant" or (entry.get("message") or {}).get("role") == "assistant":
                    break
                text = entry_text(entry)
                if not text.strip():
                    if first is None and labelled is None:  # a prompt (labelled or not) was seen: skip attachments
                        raise Fail("the checker's transcript does not start with a prompt")
                    continue
                if report_label(text):
                    labelled = (text, entry_start(entry))  # the last one wins: the workflow's first line may quote "Report:"
                    continue
                if first is None:
                    first = (text, entry_start(entry))
    except OSError:
        raise Fail("the checker's transcript cannot be read")
    if first is None and labelled is None:
        raise Fail("the checker's transcript does not start with a prompt")
    return labelled or first


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


RECORDED_RE = re.compile(r"^recorded (.+) \(open \d+, queued \d+\)\s*$", re.M)


class NoRecord(Fail):
    """The checker wrote no check record during its run."""


def result_texts(entry):
    """The texts of the tool results in a transcript entry (what the checker's commands printed)."""
    content = (entry.get("message") or {}).get("content")
    found = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            inner = block.get("content")
            if isinstance(inner, list):
                inner = "\n".join(b.get("text", "") for b in inner if isinstance(b, dict))
            if isinstance(inner, str):
                found.append(inner)
    return found


def recorded_paths(path):
    """The paths `relay check record check` printed in the checker's transcript, in the order printed ("recorded <path> (open n, queued m)")."""
    found = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and isinstance(entry.get("message") or {}, dict):
                    for text in result_texts(entry):
                        found.extend(RECORDED_RE.findall(text))
    except OSError:
        pass
    return found


def fresh_records(cwd, label, printed, start):
    """The check data files this checker wrote (modified at or after its start): (path, text), the label's first, then the others newest first."""
    names = ([resolve(cwd, label)] if label else []) + [resolve(cwd, name) for name in reversed(printed)]
    seen = []
    for name in names:
        if name not in seen:
            seen.append(name)
    found = []
    for name in seen:
        try:
            with open(name, encoding="utf-8") as handle:
                text, mtime = handle.read(), os.path.getmtime(name)
        except OSError:
            continue
        if start is None or mtime >= start:
            found.append((name, text, mtime))
    found.sort(key=lambda item: (item[0] != (resolve(cwd, label) if label else None), -item[2]))
    return [(name, text) for name, text, _ in found]


def write_mark(wt, data):
    """Commit the mark and the stored record of the loaded check record `data` in worktree `wt` (`relay_marks.write_check_mark`,
    the code `relay check record check` runs too); returns the line the hook prints."""
    counts = relay_marks.write_check_mark(wt, data)
    return "check mark written for %s: %s, open %d, queued %d" % (relay_git.current_branch(wt) or wt, data["head"], counts["open"], counts["queued"])


class Blocked(Exception):
    """The checker may not stop yet; the reason goes to it on stderr, exit 2."""


def usable(cwd, data_path, text):
    """(worktree, data) of the check data read from `data_path`, or Fail."""
    try:
        data = relay_verdict.load_record(text, "the check data %s" % data_path)
    except relay_verdict.VerdictError as exc:
        raise Fail(str(exc))
    wt = os.path.realpath(data["worktree"])
    if not os.path.isdir(wt) or relay_git.main_checkout(wt) != relay_git.main_checkout(cwd):
        raise Fail("the check data's worktree is not a worktree of this repository")
    head = data["head"]
    if relay_git.git(wt, "cat-file", "-e", head + "^{commit}")[0] != 0:
        raise Fail("head %s is not a commit of this worktree" % head)
    if relay_git.git(wt, "merge-base", "--is-ancestor", head, "HEAD")[0] != 0:
        raise Fail("head %s is not the worktree's head or an ancestor of it" % head)
    return wt, data


def no_record_reason(cwd, prompt, label):
    hint = worktree_label(prompt)
    wt = os.path.realpath(hint) if hint and os.path.isdir(hint) and relay_git.main_checkout(hint) == relay_git.main_checkout(cwd) else None
    rc, head = relay_git.git(wt, "rev-parse", "HEAD") if wt else (1, "")
    return ("no check record written during your run was found (%s). Run `relay check record check --input <file.toml>` for %s "
            "and write the record to a new file; the check mark is made from that record when you stop."
            % ("Report: %s" % label if label else "the prompt has no Report: line", "the head " + head if rc == 0 else "the worktree's head"))


def run(hook):
    """The line to say (or None); raises Blocked when the checker must go on."""
    cwd = hook.get("cwd")
    if hook.get("agent_type") != AGENT_TYPE or not isinstance(cwd, str) or not os.path.isdir(cwd):
        return None
    if not relay_git.has_relay(cwd):
        return None
    prompt = ""
    wt = None
    try:
        path = transcript_path(hook)
        if path is None:
            raise Fail("the checker's transcript was not found")
        prompt, start = first_entry(path)
        label = report_label(prompt)
        records = fresh_records(cwd, label, recorded_paths(path), start)
        if not records:
            raise NoRecord(no_record_reason(cwd, prompt, label))
        failure = None
        for data_path, text in records:
            try:
                wt, data = usable(cwd, data_path, text)
            except Fail as exc:
                failure = failure or exc
                continue
            return write_mark(wt, data)
        raise failure
    except NoRecord as exc:
        if not hook.get("stop_hook_active"):
            raise Blocked(str(exc))
        return "check mark not written for %s: %s" % (branch_of(cwd, prompt), exc)
    except (Fail, relay_marks.MarkError) as exc:
        return "check mark not written for %s: %s" % (branch_of(cwd, prompt, wt), exc)


def branch_of(cwd, prompt, wt=None):
    """The branch named in a failure line: of the worktree the record names, else of the prompt's Worktree: label."""
    if wt is None:
        hint = worktree_label(prompt)
        wt = os.path.realpath(hint) if hint and os.path.isdir(hint) and relay_git.main_checkout(hint) == relay_git.main_checkout(cwd) else None
    return (relay_git.current_branch(wt) if wt and os.path.isdir(wt) else None) or "this worktree"


def main():
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    if isinstance(hook, dict):
        try:
            text = run(hook)
        except Blocked as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if text:
            say(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
