"""Review and check data as JSON, and the readable report rendered from it (docs/plans/review-gate.md sections 3, 4.1, 6).

A review (critic or any judge) records `<report>.json` beside its readable `<report>.md`; a checker records the same for
its check. The JSON is written by `record_review` / `record_check` (the commands `relay check record review|check`),
never typed by an agent: the agent passes fields, this module validates them against the schemas below (no outside
library) and refuses bad input with a message that names the field. The readable report is the agent's prose plus a
block this module generates from the same data, from the line `RECORD_MARK` to the end of the file, so the two cannot
disagree. Recording again replaces that block and keeps the prose before it.

Review data:  {"schema": "relay-review/1", "reviewed": <full sha or "unknown">, "base": <sha or ref>,
               "findings": [FINDING, ...]}               (optional "file": the findings file's name, in a stored set)
FINDING:      {"id": "F<n>", "path", "line": int >= 1, "severity": a word of WORDS (the flow's own), "rank": high|medium|low,
               "kind": inside|outside|design|feature|question, "summary", "failing_case": [line, ...] (at least one)}
Check data:   {"schema": "relay-check/1", "head": <full sha>, "reviewed": <full sha>, "gate": <log path> or null,
               "worktree": <path> (left out of the stored copy), "review": [<review json path>, ...],
               "findings": [{"id", "verdict": MET|NOT MET|DISPUTED|GAP|OUTSIDE|QUEUED, "note"?}],
               "new": [FINDING, ...], "open": int >= 0, "queued": int >= 0}
Stored review set (`.relay/checks/<reviewed>.review.json`): {"schema": "relay-review-set/1", "reviewed": <sha>,
               "reviews": [review data with "file", ...]}
"""

import json
import os
import re

REVIEW_SCHEMA = "relay-review/1"
CHECK_SCHEMA = "relay-check/1"
SET_SCHEMA = "relay-review-set/1"
RECORD_MARK = "<!-- relay:record -->"
# Each flow's severity words and the rank they stand for. The finding keeps the flow's word (`severity`) and stores
# its rank beside it (`rank`); everything that counts or sorts findings uses the rank.
WORD_SETS = (("default", ("HIGH", "MEDIUM", "LOW")), ("spec-reviewer", ("BLOCKER", "FIX", "NIT")),
             ("spec-conformance", ("CRITICAL", "WARNING", "SUGGESTION")))
RANK_ORDER = ("high", "medium", "low")
WORDS = {word: RANK_ORDER[i] for _, words in WORD_SETS for i, word in enumerate(words)}
SEVERITIES = tuple(WORDS)
SEVERITY_HELP = ", ".join("/".join(words) for _, words in WORD_SETS)
KINDS = ("inside", "outside", "design", "feature", "question")
VERDICTS = ("MET", "NOT MET", "DISPUTED", "GAP", "OUTSIDE", "QUEUED")
SHA = re.compile(r"^[0-9a-f]{40}\Z")
FINDING_ID = re.compile(r"^F\d+\Z")
FINDING_KEYS = ("id", "path", "line", "severity", "kind", "summary", "failing")


class VerdictError(Exception):
    """Bad input to a record or unreadable data; the text names the field and why, in one line."""


def is_sha(value):
    return isinstance(value, str) and bool(SHA.match(value))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value


def finding_errors(finding, where):
    if not isinstance(finding, dict):
        return ["%s is not an object" % where]
    errors = []
    allowed = {"id", "path", "line", "severity", "rank", "kind", "summary", "failing_case"}
    for key in sorted(set(finding) - allowed):
        errors.append("%s has an unknown field %s" % (where, key))
    if not (isinstance(finding.get("id"), str) and FINDING_ID.match(finding["id"])):
        errors.append("%s: id must look like F1, got %r" % (where, finding.get("id")))
    if not _text(finding.get("path")):
        errors.append("%s: path must be a one-line text" % where)
    if not (_is_int(finding.get("line")) and finding["line"] >= 1):
        errors.append("%s: line must be a whole number of 1 or more, got %r" % (where, finding.get("line")))
    if finding.get("severity") not in SEVERITIES:
        errors.append("%s: severity must be one of %s, got %r" % (where, SEVERITY_HELP, finding.get("severity")))
    elif finding.get("rank") != WORDS[finding["severity"]]:
        errors.append("%s: rank must be %s for severity %s, got %r" % (where, WORDS[finding["severity"]], finding["severity"], finding.get("rank")))
    if finding.get("kind") not in KINDS:
        errors.append("%s: kind must be one of %s, got %r" % (where, "/".join(KINDS), finding.get("kind")))
    if not _text(finding.get("summary")):
        errors.append("%s: summary must be a one-line text" % where)
    case = finding.get("failing_case")
    if not (isinstance(case, list) and case and all(isinstance(l, str) and l.strip() for l in case)):
        errors.append("%s: failing_case must be a list of at least one non-empty line (no finding without a failing case)" % where)
    return errors


def _findings_errors(findings, where):
    if not isinstance(findings, list):
        return ["%s must be a list" % where]
    errors, seen = [], set()
    for i, finding in enumerate(findings):
        label = "%s[%d]" % (where, i)
        errors += finding_errors(finding, label)
        fid = finding.get("id") if isinstance(finding, dict) else None
        if fid in seen:
            errors.append("%s: id %s is used twice" % (label, fid))
        seen.add(fid)
    return errors


def review_errors(data):
    """[message] for review data that breaks the schema; [] when it is whole."""
    if not isinstance(data, dict):
        return ["the review data is not an object"]
    errors = []
    if data.get("schema") != REVIEW_SCHEMA:
        errors.append("schema must be %s, got %r" % (REVIEW_SCHEMA, data.get("schema")))
    if not (is_sha(data.get("reviewed")) or data.get("reviewed") == "unknown"):
        errors.append("reviewed must be a full 40-character sha or \"unknown\", got %r" % (data.get("reviewed"),))
    if not _text(data.get("base")):
        errors.append("base must be a one-line text (a sha or a ref), got %r" % (data.get("base"),))
    if "file" in data and not _text(data["file"]):
        errors.append("file must be a one-line text")
    for key in sorted(set(data) - {"schema", "reviewed", "base", "findings", "file"}):
        errors.append("unknown field %s" % key)
    return errors + _findings_errors(data.get("findings"), "findings")


def check_errors(data, stored=False):
    """[message] for check data that breaks the schema; the stored copy has no `worktree`."""
    if not isinstance(data, dict):
        return ["the check data is not an object"]
    errors = []
    if data.get("schema") != CHECK_SCHEMA:
        errors.append("schema must be %s, got %r" % (CHECK_SCHEMA, data.get("schema")))
    for key in ("head", "reviewed"):
        if not is_sha(data.get(key)):
            errors.append("%s must be a full 40-character sha, got %r" % (key, data.get(key)))
    if data.get("gate") is not None and not _text(data.get("gate")):
        errors.append("gate must be a log path or null")
    if stored:
        if "worktree" in data:
            errors.append("a stored check has no worktree")
    elif not _text(data.get("worktree")):
        errors.append("worktree must be a path")
    review = data.get("review")
    if not (isinstance(review, list) and review and all(_text(r) for r in review)):
        errors.append("review must be a list of at least one review data path")
    for key in ("open", "queued"):
        if not (_is_int(data.get(key)) and data[key] >= 0):
            errors.append("%s must be a whole number of 0 or more, got %r" % (key, data.get(key)))
    statuses = data.get("findings")
    if not isinstance(statuses, list):
        errors.append("findings must be a list")
    else:
        seen = set()
        for i, item in enumerate(statuses):
            where = "findings[%d]" % i
            if not isinstance(item, dict):
                errors.append("%s is not an object" % where)
                continue
            for key in sorted(set(item) - {"id", "verdict", "note"}):
                errors.append("%s has an unknown field %s" % (where, key))
            if not (isinstance(item.get("id"), str) and FINDING_ID.match(item["id"])):
                errors.append("%s: id must look like F1, got %r" % (where, item.get("id")))
            if item.get("verdict") not in VERDICTS:
                errors.append("%s: verdict must be one of %s, got %r" % (where, "/".join(VERDICTS), item.get("verdict")))
            if "note" in item and not _text(item["note"]):
                errors.append("%s: note must be a one-line text" % where)
            if item.get("id") in seen:
                errors.append("%s: id %s is used twice" % (where, item.get("id")))
            seen.add(item.get("id"))
    errors += _findings_errors(data.get("new"), "new")
    for key in sorted(set(data) - {"schema", "head", "reviewed", "gate", "worktree", "review", "findings", "new", "open", "queued"}):
        errors.append("unknown field %s" % key)
    return errors


def set_errors(data):
    if not isinstance(data, dict):
        return ["the stored review is not an object"]
    errors = []
    if data.get("schema") != SET_SCHEMA:
        errors.append("schema must be %s, got %r" % (SET_SCHEMA, data.get("schema")))
    if not is_sha(data.get("reviewed")):
        errors.append("reviewed must be a full 40-character sha, got %r" % (data.get("reviewed"),))
    reviews = data.get("reviews")
    if not (isinstance(reviews, list) and reviews):
        return errors + ["reviews must be a list of at least one review"]
    for i, review in enumerate(reviews):
        errors += ["reviews[%d]: %s" % (i, e) for e in review_errors(review)]
    return errors


def _load(text, checker, what, **kw):
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise VerdictError("%s is not JSON: %s" % (what, exc))
    errors = checker(data, **kw)
    if errors:
        raise VerdictError("%s is not valid: %s" % (what, "; ".join(errors[:3]) + (" (and %d more)" % (len(errors) - 3) if len(errors) > 3 else "")))
    return data


def load_review(text, what="the review data"):
    return _load(text, review_errors, what)


def load_check(text, what="the check data", stored=False):
    return _load(text, check_errors, what, stored=stored)


def load_set(text, what="the stored review"):
    return _load(text, set_errors, what)


def json_path(report):
    """The data file beside a report: `x.md` -> `x.json`, any other name gets `.json` added."""
    return (report[:-3] if report.endswith(".md") else report) + ".json"


def linter(finding):
    return "%s:%d: %s: %s %s" % (finding["path"], finding["line"], finding["severity"], finding["id"], finding["summary"])


def _finding_lines(finding):
    lines = [linter(finding)]
    if finding["kind"] in ("design", "feature"):
        lines.append("Kind: %s" % finding["kind"])
    lines.append("Failing case: " + finding["failing_case"][0])
    lines += finding["failing_case"][1:]
    return lines


def render_review(data):
    """The generated block of a review report (it starts with RECORD_MARK)."""
    out = [RECORD_MARK, "## Findings", "Reviewed: %s" % data["reviewed"], "Base: %s" % data["base"]]
    groups = (("inside", None), ("outside", "## Outside this change"), ("question", "## Questions for the owner"))
    shown = {"inside": [f for f in data["findings"] if f["kind"] in ("inside", "design", "feature")],
             "outside": [f for f in data["findings"] if f["kind"] == "outside"],
             "question": [f for f in data["findings"] if f["kind"] == "question"]}
    for name, heading in groups:
        if heading:
            if not shown[name]:
                continue
            out += ["", heading]
        for finding in shown[name]:
            out += [""] + _finding_lines(finding)
    if not data["findings"]:
        out += ["", "No findings."]
    return "\n".join(out) + "\n"


def render_check(data):
    """The generated block of a check report: status lines, new problems, then the five verdict lines last."""
    out = [RECORD_MARK, "## Findings checked"]
    for item in data["findings"]:
        out.append(("%s %s %s" % (item["id"], item["verdict"], item.get("note", ""))).rstrip())
    if not data["findings"]:
        out.append("No findings to check.")
    if data["new"]:
        out += ["", "## New problems"]
        for finding in data["new"]:
            out += [""] + _finding_lines(finding)
    out += ["", "## Verdict", "head %s" % data["head"], "reviewed %s" % data["reviewed"], "open %d" % data["open"], "queued %d" % data["queued"]]
    return "\n".join(out) + "\n"


def _write_pair(report, block, data):
    """Replace the generated block of `report` (keep the prose before RECORD_MARK) and write its JSON; both or error."""
    try:
        old = open(report, encoding="utf-8").read() if os.path.exists(report) else ""
    except OSError as exc:
        raise VerdictError("the report %s cannot be read: %s" % (report, exc.strerror))
    prose = old.split(RECORD_MARK, 1)[0].rstrip()
    text = (prose + "\n\n" if prose else "") + block
    try:
        os.makedirs(os.path.dirname(os.path.abspath(report)), exist_ok=True)
        with open(report, "w", encoding="utf-8") as handle:
            handle.write(text)
        with open(json_path(report), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise VerdictError("cannot write the report or its data: %s" % exc.strerror)
    return json_path(report)


def _finding(raw):
    """A finding dict from the dict the command line collected (strings), line as int; VerdictError on a bad line."""
    out = {k: raw[k] for k in ("id", "path", "severity", "kind", "summary") if k in raw}
    if "line" in raw:
        try:
            out["line"] = int(raw["line"])
        except ValueError:
            raise VerdictError("%s: line must be a whole number, got %r" % (raw.get("id", "a finding"), raw["line"]))
    out["failing_case"] = list(raw.get("failing", []))
    if out.get("severity") in WORDS:
        out["rank"] = WORDS[out["severity"]]
    return out


def record_review(report, reviewed, base, findings, file=None):
    """Validate and write a review's data and generated report block; returns the JSON path. `findings` are dicts of
    strings as `parse_findings` makes them."""
    data = {"schema": REVIEW_SCHEMA, "reviewed": reviewed, "base": base, "findings": [_finding(f) for f in findings]}
    if file:
        data["file"] = file
    errors = review_errors(data)
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    return _write_pair(report, render_review(data), data)


def record_check(report, head, reviewed, gate, worktree, review_paths, statuses, new, open_, queued):
    """Validate and write a check's data and generated report block; returns the JSON path. Every review data file must
    be valid and name the same `reviewed`; every checked id must be a finding of those reviews or a new one."""
    paths = [os.path.abspath(p) for p in review_paths]
    known = set()
    for path in paths:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            raise VerdictError("nothing recorded: the review data %s cannot be read (record the review first)" % path)
        review = load_review(text, "the review data %s" % path)
        if review["reviewed"] != reviewed:
            raise VerdictError("nothing recorded: the review data %s is of %s, not of the reviewed sha %s" % (path, review["reviewed"], reviewed))
        known |= {f["id"] for f in review["findings"]}
    data = {"schema": CHECK_SCHEMA, "head": head, "reviewed": reviewed, "gate": None if gate in (None, "none") else gate,
            "worktree": worktree, "review": paths, "findings": statuses, "new": [_finding(f) for f in new],
            "open": open_, "queued": queued}
    errors = check_errors(data)
    known |= {f["id"] for f in data["new"] if isinstance(f, dict)}
    errors += ["findings: %s is not a finding of the reviews or a new one" % s["id"] for s in statuses if s.get("id") not in known]
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    return _write_pair(report, render_check(data), data)


def parse_findings(tokens):
    """[finding] from the words after a `--finding`/`--new` option: `key=value` words, a new finding at each `id=`; `failing=`
    may repeat (one failing-case line each). A word without a known key is refused."""
    found = []
    for token in tokens:
        key, sep, value = token.partition("=")
        if not sep or key not in FINDING_KEYS:
            raise VerdictError("a finding word must be one of %s as key=value, got %r" % (", ".join(k + "=" for k in FINDING_KEYS), token))
        if key == "id" or not found:
            if key != "id":
                raise VerdictError("a finding starts with id=F<n>, got %r" % token)
            found.append({"failing": []})
        if key == "failing":
            found[-1]["failing"].append(value)
        elif key in found[-1]:
            raise VerdictError("%s is given twice for %s" % (key, found[-1].get("id", "a finding")))
        else:
            found[-1][key] = value
    return found


def parse_status(text):
    """{"id", "verdict", "note"?} from `F2=NOT MET: no test` (the note after a colon is optional)."""
    fid, sep, rest = text.partition("=")
    if not sep:
        raise VerdictError("a status must look like F1=MET or F2=NOT MET: why, got %r" % text)
    for verdict in sorted(VERDICTS, key=len, reverse=True):
        if rest == verdict or rest.startswith(verdict + ":"):
            note = rest[len(verdict) + 1:].strip()
            item = {"id": fid, "verdict": verdict}
            if note:
                item["note"] = note
            return item
    raise VerdictError("status %r: the verdict must be one of %s" % (text, "/".join(VERDICTS)))


def stored_set(reviews, reviewed):
    """The stored review set (a dict) for review data dicts `reviews`, each marked with its findings file's name."""
    return {"schema": SET_SCHEMA, "reviewed": reviewed, "reviews": reviews}


def stored_check(data, review_name):
    """The check data without its machine-specific parts: no worktree, `review` the stored review set's name."""
    out = {k: v for k, v in data.items() if k != "worktree"}
    out["review"] = [review_name]
    return out


def outside_count(review_set):
    """How many findings of a stored review set are outside the change."""
    return sum(1 for review in review_set["reviews"] for f in review["findings"] if f["kind"] == "outside")


def counts_by_rank(findings):
    """{"high": n, "medium": n, "low": n} of finding dicts, whatever words their flow used."""
    counts = {rank: 0 for rank in RANK_ORDER}
    for finding in findings:
        counts[finding["rank"]] += 1
    return counts
