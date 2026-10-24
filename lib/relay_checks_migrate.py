"""`relay check migrate`: convert the schema-1 checks in `.relay/checks/` to the schema-2 check record, once.

Schema 1 kept a check as `<head>.check.json` (verdicts only, ids of the reviews' findings, a `new` list, counts), the findings in
review sets `<sha>.review.json`, and a mark `<head>.json` with the counts and the reviewed sha. Schema 2 is ONE record holding
the findings and their verdicts (relay_verdict.py). The conversion, in the order of the design:

1. Every schema-1 check is converted first, in memory; one that cannot be converted stops the run with nothing written.
   It gets the findings of the sets it names (two checks may name one set). Q findings become Q1.., the others F1.. in the order
   of the sets (the old id kept as `source_id`, the set's file name as `source`). `item` comes from the set's scope line
   "From queue item <slug>:". The old `new` findings become N1.. with the old id in `reason`. A check whose notes say
   "Q1 is MET: ..." while no set holds a Q finding gets a Q1 MET quoting that line verbatim, marked "migrated".
2. The mark of each converted check becomes schema 2 (counts derived from the record, `review` and `verdict.reviewed` dropped).
3. Only then every review set is deleted (git keeps them), the lone ones too.

A second run finds no schema-1 check and changes nothing.
"""

import json
import os
import re

import relay_verdict

FOLDER = os.path.join(".relay", "checks")
ITEM_LINE = re.compile(r"(?:From|closing) queue item ([a-z0-9][a-z0-9-]*)")
WORKTREE = re.compile(r"/\.worktrees/([^/]+)/")
Q1_MET = re.compile(r"Q1 is MET: ")
MIGRATED = "migrated"


class MigrateError(Exception):
    """A check cannot be converted; the text names the file and why, in one line."""


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise MigrateError("%s cannot be read: %s" % (os.path.basename(path), exc))


def _gate_name(check, name):
    gate = check.get("gate")
    if gate is None:
        return None
    if isinstance(gate, str) and gate.endswith(".gate.log"):
        return os.path.basename(gate)
    if isinstance(gate, str) and (relay_verdict.PIPELINE.match(gate) or gate.startswith("log ")):
        return gate
    raise MigrateError("%s: cannot tell the gate from %r" % (name, gate))


def _branch(check, name):
    """The branch of the change: the task worktree named in the old gate path (`.worktrees/<task>/` is branch `wt/<task>`)."""
    found = WORKTREE.search(check.get("gate") or "")
    if not found:
        raise MigrateError("%s: cannot tell the branch (the gate %r names no task worktree)" % (name, check.get("gate")))
    return "wt/" + found.group(1)


def _sha_or(*candidates):
    return next((c for c in candidates if relay_verdict.is_sha(c)), None)


def _stated(finding, source, since, source_id=None, owner=()):
    out = dict(finding, source=source, since=since)
    if source_id is not None:
        out["source_id"] = source_id
    if owner:
        out["owner"] = [{k: v for k, v in e.items() if k != "id"} for e in owner]
    return out


def _item_of(sets):
    """The queue item named by a scope line of the sets, or None."""
    for review_set in sets:
        for review in review_set.get("reviews", []):
            for line in review.get("scope") or []:
                found = ITEM_LINE.search(line)
                if found:
                    return found.group(1)
    return None


def convert_check(old, sets, name):
    """The schema-2 record (stored form, no worktree) for the schema-1 check `old` (file `name`) and the review sets it names
    (already loaded, in the order it names them). MigrateError when a verdict is missing or the result is not a valid record."""
    head = old.get("head")
    verdicts = {}
    for f in old.get("findings") or []:
        if f.get("id") in verdicts:
            raise MigrateError("%s: the old verdict id %s is used twice" % (name, f.get("id")))
        verdicts[f.get("id")] = f
    queue, reviews, used = [], [], set()
    for review_set in sets:
        for review in review_set.get("reviews", []):
            since = _sha_or(review.get("reviewed"), review_set.get("reviewed"), old.get("reviewed"), head)
            source = review.get("file") or "review"
            owner = review.get("owner") or []
            for finding in review.get("findings", []):
                old_id = finding["id"]
                if old_id in used:
                    raise MigrateError("%s: the finding id %s is in two of its reviews" % (name, old_id))
                used.add(old_id)
                said = verdicts.get(old_id)
                if said is None:
                    raise MigrateError("%s: no verdict for %s of %s" % (name, old_id, source))
                mine = [e for e in owner if e.get("id") == old_id]
                if old_id.startswith("Q"):
                    new_id, bucket, src = "Q%d" % (len(queue) + 1), queue, "queue"
                else:
                    new_id, bucket, src = "F%d" % (len(reviews) + 1), reviews, source
                got = _stated(dict(finding, id=new_id), src, since, None if src == "queue" else old_id, mine)
                bucket.append(dict(got, verdict=said["verdict"], reason=list(said.get("reason") or [])))
    extra = sorted(set(verdicts) - used)
    if extra:
        raise MigrateError("%s: verdicts for %s are for no finding of its reviews" % (name, ", ".join(map(str, extra))))
    item = _item_of(sets)
    if not queue:
        queue = _note_q1(old, item, name, head)
    news = []
    for n, finding in enumerate(old.get("new") or [], 1):
        reason = ["%s: this was %s in the old check" % (MIGRATED, finding.get("id"))]
        news.append(dict(_stated(dict(finding, id="N%d" % n), "check", head), verdict="NOT MET", reason=reason))
    data = {"schema": relay_verdict.RECORD_SCHEMA, "type": relay_verdict.CHECK_TYPE, "head": head, "branch": _branch(old, name),
            "item": item, "gate": _gate_name(old, name), "scope": list(old.get("scope") or []),
            "notes": list(old.get("notes") or []), "findings": queue + reviews + news}
    errors = relay_verdict.record_errors(data, stored=True)
    if errors:
        raise MigrateError("%s: the converted record is not valid: %s" % (name, "; ".join(errors[:3])))
    return data


def _note_q1(old, item, name, head):
    """[Q1 MET] when a note of the old check says "Q1 is MET: ..." (the checker's own verdict, written where no set held Q1)."""
    for line in (old.get("notes") or []) + (old.get("scope") or []):
        if Q1_MET.search(line):
            if item is None:
                raise MigrateError("%s: a note says Q1 is MET but no scope line names the queue item" % name)
            since = _sha_or(old.get("reviewed"), head)
            return [{"id": "Q1", "path": ".relay/queue/done/%s.json" % item, "line": 1, "severity": "HIGH", "rank": "high",
                     "kind": "inside", "summary": "The queue item %s (migrated from a note of the old check)" % item,
                     "failing_case": ["migrated: the old check recorded no Q1 finding; the item's own text is in .relay/queue/done/%s.json" % item],
                     "source": "queue", "since": since, "verdict": "MET", "reason": [MIGRATED, line]}]
    return []


def convert_mark(mark, record, check_name, name):
    """The schema-2 mark for a schema-1 `mark` of the converted `record`."""
    gate = mark.get("gate")
    return {"schema": 2, "commit": mark.get("commit"), "verdict": {"open": relay_verdict.open_of(record),
            "queued": relay_verdict.queued_of(record)}, "check": check_name, "gate": gate, "time": mark.get("time")}


def _dump(data):
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def migrate(repo):
    """Convert `repo`'s `.relay/checks/` in place; returns (checks converted, marks converted, sets deleted). MigrateError, with
    nothing written, when a check cannot be converted."""
    folder = os.path.join(repo, FOLDER)
    if not os.path.isdir(folder):
        return 0, 0, 0
    names = sorted(os.listdir(folder))
    writes, converted = {}, {}
    for name in names:
        if not name.endswith(".check.json"):
            continue
        old = _read(os.path.join(folder, name))
        if not (isinstance(old, dict) and old.get("type") == relay_verdict.CHECK_TYPE and old.get("schema") == 1):
            continue
        sets = [_read(os.path.join(folder, os.path.basename(s))) for s in old.get("review") or []]
        for s, loaded in zip(old.get("review") or [], sets):
            if not isinstance(loaded, dict) or loaded.get("type") != "review-set":
                raise MigrateError("%s: %s is not a review set" % (name, s))
        record = convert_check(old, sets, name)
        converted[name] = record
        writes[name] = _dump(record)
    marks = 0
    for name in names:
        if not (name.endswith(".json") and relay_verdict.is_sha(name[:-5])):
            continue
        mark = _read(os.path.join(folder, name))
        if not (isinstance(mark, dict) and mark.get("schema") == 1):
            continue
        check_name = mark.get("check")
        if check_name not in converted:
            raise MigrateError("%s: its check %r is not a schema-1 check of this folder" % (name, check_name))
        writes[name] = _dump(convert_mark(mark, converted[check_name], check_name, name))
        marks += 1
    sets_gone = [n for n in names if n.endswith(".review.json") and _is_set(os.path.join(folder, n))]
    for name, text in writes.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    for name in sets_gone:
        os.remove(os.path.join(folder, name))
    return len(converted), marks, len(sets_gone)


def _is_set(path):
    data = _read(path)
    return isinstance(data, dict) and data.get("type") == "review-set"
