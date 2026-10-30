# size: over the 600-line limit until its split item lands
"""Review and check data as JSON, the only stored form of a report (docs/plans/review-gate.md sections 3, 4.1, 6).

A review (critic or any judge) records `<report>.json`; a checker records the same for its check. Nothing readable is
stored beside the data: `render_review` / `render_check` / `render_set` and their `brief_*` forms print the readable text
from the JSON on demand (`relay check show`). The JSON is written by `record_review` / `record_check` (the commands
`relay check record review|check --input <file.toml>`), never typed by an agent: the agent writes a TOML input file
(multi-line text in '''...''' keeps every character, so no text passes through the shell), this module validates it
against the schemas below (no outside library) and refuses bad input with a message that names the field.

Review data (what a critic records; schema 1): {"schema": 1, "type": "review", "reviewed": <full sha or "unknown">,
               "base": <sha or ref>, "scope": [line, ...], "notes": [line, ...], "findings": [FINDING, ...],
               "owner": [{"id": of a finding, "words": [line, ...], "date": "YYYY-MM-DD"}, ...]}   (a stored set adds "file")
The owner's word that a finding is not wrong is data: `relay check owner <review.json> <id> --input <file.toml>`
(`add_owner`) appends to "owner" the words as the owner said them; a checker counts such a finding as not wrong.
FINDING:      {"id": "F<n>", "path", "line": int >= 1, "severity": a word of WORDS (the flow's own),
               "rank": high|medium|low, "kind": inside|outside|design|feature|question, "summary",
               "failing_case": [line, ...] (at least one), "details", "pass_cases", "evidence", "fix_hint": [line, ...],
               "decided": one line, optional: the principle or recorded decision that settled it without the owner}
A scope cut that a principle settles is a finding of kind outside with `decided`; a checker gives such a MEDIUM or LOW
finding the verdict OUTSIDE with `decided` (never a HIGH one, never a question or design finding): it is then not open.

The check record (schema 2): ONE file per change, `.relay/checks/<head>.check.json`, built in one order by
`build_record` and written by `relay check record check --input <file.toml>`; every reader (the check hook, `relay queue
done`, the merge guard) loads it with `load_record`. Counts are never stored: `open_of` and `queued_of` derive them.
    {"schema": 2, "type": "check", "head": <sha>, "branch", "item": <queue item name or null>, "gate": <log file name, `log <path>`, pipeline line or null>,
     "worktree": <path> (left out of the stored copy), "scope": [...], "notes": [...],
     "findings": [RECORD FINDING, ...]}
RECORD FINDING: a FINDING plus {"source": "queue"|<review file name>|"merge"|"check", "source_id" (a review's own id),
     "since": <sha the finding was stated against>, "verdict": MET|NOT MET|DISPUTED|GAP|OUTSIDE|QUEUED, "reason": [line, ...],
     "owner": [{"words", "date", "queue"?}, ...]}. Ids: Q1 the queue item, F1.. the reviews' findings in order, M1.. the
     merge findings, N1.. the checker's own (new problems, a gate that is missing, red or for other code).
"""

import json
import os
import re
from typing import Optional

import relay_git

SCHEMA = 1                     # the review data
RECORD_SCHEMA = 2              # the check record
REVIEW_TYPE, CHECK_TYPE = "review", "check"
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
FINDING_ID = re.compile(r"^[FQMN]\d+\Z")
GATE_NAME = re.compile(r"^([0-9a-f]{40})(?:\.remote)?\.gate\.log\Z")      # a Mac gate log or a remote one (.relay/queue/gates-on-the-vps-hosts-transport-watch-bring-up.plan.md 5.1)
PIPELINE = re.compile(r"^pipeline #[0-9]+ on ([0-9a-f]{40}) passed\Z")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
PROSE = ("details", "pass_cases", "evidence", "fix_hint")       # a finding's optional prose, as lists of lines
NO_DECIDED_KINDS = ("question", "design")      # a checker never decides these (finding_errors, record_errors)
# The most lines `relay check show --brief` prints (bound 5-30: at 5 only the verdict and two findings fit, at 30 it is a page).
BRIEF_LINES = 10


class VerdictError(Exception):
    """Bad input to a record or unreadable data; the text names the field and why, in one line."""


def is_sha(value):
    return isinstance(value, str) and bool(SHA.match(value))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value


def _lines_ok(value):
    """A list of one-line strings (blank lines allowed: they separate paragraphs)."""
    return isinstance(value, list) and all(isinstance(l, str) and "\n" not in l for l in value)


def lines_of(text):
    """Text as the list of its lines, the blank lines at its start and end dropped (the lines themselves unchanged)."""
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _prose_errors(data, key, where, errors):
    if key in data and not _lines_ok(data[key]):
        errors.append("%s: %s must be a list of one-line texts" % (where, key))


def finding_errors(finding, where, extra=()):
    if not isinstance(finding, dict):
        return ["%s is not an object" % where]
    errors = []
    allowed = {"id", "path", "line", "severity", "rank", "kind", "summary", "failing_case", "decided"} | set(PROSE) | set(extra)
    for key in sorted(set(finding) - allowed):
        errors.append("%s has an unknown field %s" % (where, key))
    if not (isinstance(finding.get("id"), str) and FINDING_ID.match(finding["id"])):
        errors.append("%s: id must look like F1 (or Q1 for a queue item), got %r" % (where, finding.get("id")))
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
    if not (_lines_ok(case) and any(l.strip() for l in case)):
        errors.append("%s: failing_case must be a list of lines with at least one non-empty line (no finding without a failing case)" % where)
    for key in PROSE:
        _prose_errors(finding, key, where, errors)
    if "decided" in finding and not _text(finding["decided"]):
        errors.append("%s: decided must be a one-line text (the principle or decision, and why)" % where)
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


def _head_errors(data, kind):
    errors = []
    if data.get("schema") != SCHEMA or isinstance(data.get("schema"), bool):
        errors.append("schema must be %d, got %r" % (SCHEMA, data.get("schema")))
    if data.get("type") != kind:
        errors.append("type must be %s, got %r" % (kind, data.get("type")))
    for key in ("scope", "notes"):
        _prose_errors(data, key, "the data", errors)
    return errors


def review_errors(data):
    """[message] for review data that breaks the schema; [] when it is whole."""
    if not isinstance(data, dict):
        return ["the review data is not an object"]
    errors = _head_errors(data, REVIEW_TYPE)
    if not (is_sha(data.get("reviewed")) or data.get("reviewed") == "unknown"):
        errors.append("reviewed must be a full 40-character sha or \"unknown\", got %r" % (data.get("reviewed"),))
    if not _text(data.get("base")):
        errors.append("base must be a one-line text (a sha or a ref), got %r" % (data.get("base"),))
    if "file" in data and not _text(data["file"]):
        errors.append("file must be a one-line text")
    for key in sorted(set(data) - {"schema", "type", "reviewed", "base", "scope", "notes", "findings", "file", "owner"}):
        errors.append("unknown field %s" % key)
    errors += _findings_errors(data.get("findings"), "findings")
    return errors + _owner_errors(data)


def _owner_errors(data):
    """[message] for the `owner` list of review data: each entry an id of one of its findings, the words, a date."""
    if "owner" not in data:
        return []
    owner = data["owner"]
    if not isinstance(owner, list):
        return ["owner must be a list"]
    ids = {f.get("id") for f in data.get("findings") or [] if isinstance(f, dict)}
    errors = []
    for i, entry in enumerate(owner):
        where = "owner[%d]" % i
        if not isinstance(entry, dict):
            errors.append("%s is not an object" % where)
            continue
        for key in sorted(set(entry) - {"id", "words", "date", "queue"}):
            errors.append("%s has an unknown field %s" % (where, key))
        if "queue" in entry and not (isinstance(entry["queue"], str) and SLUG.match(entry["queue"])):
            errors.append("%s: queue must be the name of a queue item (lowercase words with hyphens), got %r" % (where, entry["queue"]))
        if entry.get("id") not in ids:
            errors.append("%s: id %r is not a finding of this review" % (where, entry.get("id")))
        if not (_lines_ok(entry.get("words")) and any(l.strip() for l in entry["words"])):
            errors.append("%s: words must be a list of lines with at least one non-empty line" % where)
        if not (isinstance(entry.get("date"), str) and DATE.match(entry["date"])):
            errors.append("%s: date must look like 2026-10-23, got %r" % (where, entry.get("date")))
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


MIGRATE_LINE = "this is a schema-1 check from before the record; run `relay check migrate` (or check the change again)"
RECORD_EXTRA = ("source", "source_id", "since", "verdict", "reason", "owner")
RECORD_TOP = ("schema", "type", "head", "branch", "item", "gate", "worktree", "scope", "notes", "findings")


def _owner_entry_errors(owner, where):
    if not isinstance(owner, list):
        return ["%s: owner must be a list" % where]
    errors = []
    for i, entry in enumerate(owner):
        label = "%s: owner[%d]" % (where, i)
        if not isinstance(entry, dict):
            errors.append("%s is not an object" % label)
            continue
        for key in sorted(set(entry) - {"words", "date", "queue"}):
            errors.append("%s has an unknown field %s" % (label, key))
        if "queue" in entry and not (isinstance(entry["queue"], str) and SLUG.match(entry["queue"])):
            errors.append("%s: queue must be the name of a queue item, got %r" % (label, entry["queue"]))
        if not (_lines_ok(entry.get("words")) and any(l.strip() for l in entry["words"])):
            errors.append("%s: words must hold at least one non-empty line" % label)
        if not (isinstance(entry.get("date"), str) and DATE.match(entry["date"])):
            errors.append("%s: date must look like 2026-10-23, got %r" % (label, entry.get("date")))
    return errors


def record_errors(data, stored=False):
    """[message] for check record data that breaks the schema; the stored copy has no `worktree`."""
    if not isinstance(data, dict):
        return ["the check record is not an object"]
    if data.get("type") == CHECK_TYPE and data.get("schema") == 1:
        return [MIGRATE_LINE]
    errors = []
    if data.get("schema") != RECORD_SCHEMA or isinstance(data.get("schema"), bool):
        errors.append("schema must be %d, got %r" % (RECORD_SCHEMA, data.get("schema")))
    if data.get("type") != CHECK_TYPE:
        errors.append("type must be %s, got %r" % (CHECK_TYPE, data.get("type")))
    for key in sorted(set(data) - set(RECORD_TOP)):
        errors.append("unknown field %s" % key)
    if not is_sha(data.get("head")):
        errors.append("head must be a full 40-character sha, got %r" % (data.get("head"),))
    if not _text(data.get("branch")):
        errors.append("branch must be a one-line text")
    if data.get("item") is not None and not (isinstance(data["item"], str) and SLUG.match(data["item"])):
        errors.append("item must be null or the name of a queue item, got %r" % (data.get("item"),))
    gate = data.get("gate")
    if gate is not None and not (_text(gate) and (GATE_NAME.match(gate) or PIPELINE.match(gate) or gate.startswith("log "))):
        errors.append("gate must be null, a gate log file name, a pipeline line or `log <path>`, got %r" % (gate,))
    if stored:
        if "worktree" in data:
            errors.append("a stored check has no worktree")
    elif not _text(data.get("worktree")):
        errors.append("worktree must be a path")
    for key in ("scope", "notes"):
        _prose_errors(data, key, "the data", errors)
    findings = data.get("findings")
    if not isinstance(findings, list):
        return errors + ["findings must be a list"]
    seen = set()
    for i, finding in enumerate(findings):
        where = "findings[%d]" % i
        errors += finding_errors(finding, where, RECORD_EXTRA)
        if not isinstance(finding, dict):
            continue
        if finding.get("id") in seen:
            errors.append("%s: id %s is used twice" % (where, finding.get("id")))
        seen.add(finding.get("id"))
        if not _text(finding.get("source")):
            errors.append("%s: source must be a one-line text" % where)
        if "source_id" in finding and not _text(finding["source_id"]):
            errors.append("%s: source_id must be a one-line text" % where)
        if not is_sha(finding.get("since")):
            errors.append("%s: since must be a full 40-character sha, got %r" % (where, finding.get("since")))
        if finding.get("verdict") not in VERDICTS:
            errors.append("%s: verdict must be one of %s, got %r" % (where, "/".join(VERDICTS), finding.get("verdict")))
        _prose_errors(finding, "reason", where, errors)
        if finding.get("verdict") == "OUTSIDE" and finding.get("decided") and (finding.get("rank") == "high" or finding.get("kind") in NO_DECIDED_KINDS):
            errors.append("%s: decided is refused on %s: only a reversible scope cut of a medium or low finding that is not a question or design finding may be decided without the owner" % (
                where, "rank high" if finding.get("rank") == "high" else "kind " + finding["kind"]))
        if finding.get("verdict") == "OUTSIDE" and finding.get("decided") and finding.get("source") == "merge":
            errors.append("%s: decided is refused on a merge finding: it is a re-check of a file the merge changed, not part of the item" % where)
        if "owner" in finding:
            errors += _owner_entry_errors(finding["owner"], where)
    return errors


def load_record(text, what="the check record", stored=False):
    """The check record in JSON `text`; VerdictError (naming the field) when it is not one. A schema-1 check is refused
    with a line that names `relay check migrate`. The one function every reader of a check uses."""
    return _load(text, record_errors, what, stored=stored)


def is_decided_cut(finding):
    """True for a record finding the checker gave OUTSIDE with `decided`: a scope cut settled without the owner."""
    return finding.get("verdict") == "OUTSIDE" and bool(finding.get("decided"))


def open_of(record):
    """How many findings are wrong and unanswered: any kind but outside (a request for new work, a design question or
    a question is counted too, so none is counted nowhere), rank high or medium, verdict not MET, not a decided scope cut
    (OUTSIDE with `decided`), and no owner entry (the owner's word, or a move to a queue item, answers it)."""
    return sum(1 for f in record["findings"]
               if f["kind"] != "outside" and f["rank"] in ("high", "medium") and f["verdict"] != "MET" and not is_decided_cut(f) and not f.get("owner"))


def queued_of(record):
    """How many findings the owner moved to a queue item (an owner entry with `queue`)."""
    return sum(1 for f in record["findings"] if any(e.get("queue") for e in f.get("owner") or []))


def outside_of(record):
    """How many findings of the record are outside the change: of kind outside, or a decided scope cut."""
    return sum(1 for f in record["findings"] if f["kind"] == "outside" or is_decided_cut(f))


def decided_lines(record):
    """One line `decided: F<n> <text>` for each finding of the record that was decided without the owner."""
    return ["decided: %s %s" % (f["id"], f["decided"]) for f in record["findings"] if f.get("decided")]


def stored_record(record):
    """The record without its machine-specific part (the worktree)."""
    return {k: v for k, v in record.items() if k != "worktree"}


def load_any(text, what="the data"):
    """(type, data) of a review or a check record, by its `type`; VerdictError when it is neither or invalid.
    A record with a `worktree` is a recorded one, without it a stored one."""
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise VerdictError("%s is not JSON: %s" % (what, exc))
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    if kind == REVIEW_TYPE:
        return kind, load_review(text, what)
    if kind == CHECK_TYPE:
        return kind, load_record(text, what, stored="worktree" not in parsed)
    raise VerdictError("%s is not a review or a check (type %r)" % (what, kind))


def linter(finding):
    return "%s:%d: %s: %s %s" % (finding["path"], finding["line"], finding["severity"], finding["id"], finding["summary"])


# ---------------------------------------------------------------- readable views (read-only, rendered from the data)

def _section(out, title, lines, indent="  "):
    if lines:
        out.append(title + ":")
        out += [(indent + l).rstrip() for l in lines]


def finding_lines(finding, owner=()):
    """The finding as the reader sees it: the linter line, then its kind (when not plain inside), prose and the owner's
    words (the entries of the review's `owner` list for this finding), indented."""
    out = [linter(finding)]
    if finding["kind"] != "inside":
        out.append("  Kind: %s" % finding["kind"])
    if finding.get("decided"):
        out.append("  decided: %s" % finding["decided"])
    for title, key in (("Failing case", "failing_case"), ("Pass cases", "pass_cases"), ("Details", "details"),
                       ("Evidence", "evidence"), ("Fix hint", "fix_hint")):
        _section(out, "  " + title, finding.get(key) or [], indent="    ")
    for entry in owner:
        what = "moved to queue item %s" % entry["queue"] if entry.get("queue") else "says not wrong"
        _section(out, "  Owner (%s) %s" % (entry["date"], what), entry["words"], indent="    ")
    return out


def owner_of(data, fid):
    """The owner entries of review data for finding `fid`, in the order they were given."""
    return [e for e in data.get("owner") or [] if e["id"] == fid]


def _prose_head(out, data):
    _section(out, "Scope", data.get("scope") or [])
    _section(out, "Notes", data.get("notes") or [])


def _review_lines(data):
    out = ["Review of %s against %s" % (data["reviewed"], data["base"])]
    _prose_head(out, data)
    out.append("Findings: %d" % len(data["findings"]))
    for finding in data["findings"]:
        out += [""] + finding_lines(finding, owner_of(data, finding["id"]))
    return out


def render_review(data):
    """The full readable text of review data."""
    return "\n".join(_review_lines(data)) + "\n"


def _cut(lines, source, limit=BRIEF_LINES):
    if len(lines) <= limit:
        return lines
    return lines[:limit - 1] + ["... %d more lines: relay check show %s" % (len(lines) - limit + 1, source)]


def brief_review(data, source="<report>"):
    counts = counts_by_rank(data["findings"])
    out = ["Review of %s against %s: %d findings (high %d, medium %d, low %d)" % (
        data["reviewed"][:12], data["base"][:12], len(data["findings"]), counts["high"], counts["medium"], counts["low"])]
    out += [linter(f) for f in data["findings"]]
    return "\n".join(_cut(out, source)) + "\n"


def render_check(data):
    """The full readable text of a check record."""
    out = ["Check of %s on %s" % (data["head"], data["branch"]), "Item: %s" % (data["item"] or "none"),
           "Gate: %s" % (data["gate"] or "none"), "Open: %d  Queued: %d" % (open_of(data), queued_of(data))]
    _prose_head(out, data)
    out.append("Findings: %d" % len(data["findings"]))
    for finding in data["findings"]:
        out += [""] + finding_lines(finding, finding.get("owner") or [])
        out.append("  Source: %s%s, since %s" % (finding["source"], " " + finding["source_id"] if finding.get("source_id") else "", finding["since"][:12]))
        out.append("  Verdict: %s" % finding["verdict"])
        out += ["    " + l for l in finding.get("reason") or []]
    return "\n".join(out) + "\n"


def brief_check(data, source="<report>"):
    out = ["Check of %s: open %d, queued %d, gate %s" % (data["head"][:12], open_of(data), queued_of(data), data["gate"][:12] if data["gate"] else "none")]
    for finding in data["findings"]:
        reason = finding.get("reason") or []
        out.append(("%s %s %s" % (finding["id"], finding["verdict"], reason[0] if reason else "")).rstrip())
    return "\n".join(_cut(out, source)) + "\n"


def render_any(text, brief=False, source="<report>", what="the data"):
    """The readable text (or the 10-line summary) of a review or a check record given as JSON text."""
    kind, data = load_any(text, what)
    full = {REVIEW_TYPE: render_review, CHECK_TYPE: render_check}
    short = {REVIEW_TYPE: brief_review, CHECK_TYPE: brief_check}
    return short[kind](data, source) if brief else full[kind](data)


# ---------------------------------------------------------------- the TOML input and the records

def read_input(path, done="recorded"):
    """The decoded TOML input file at `path`; VerdictError ("nothing <done>: ...") when it cannot be read or is not TOML."""
    try:
        import tomllib
    except ImportError:
        raise VerdictError("nothing %s: reading the input needs Python 3.11 or newer (tomllib)" % done)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise VerdictError("nothing %s: the input file %s cannot be read: %s" % (done, path, exc.strerror))
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise VerdictError("nothing %s: the input file is not valid TOML: %s" % (done, exc))


def table_errors(raw, where, allowed, required):
    """[message] for unknown or missing keys of the input table `raw` (`where` names it)."""
    if not isinstance(raw, dict):
        return ["%s is not a table" % where]
    errors = ["unknown key `%s` %s (allowed: %s)" % (k, where, ", ".join(allowed)) for k in sorted(set(raw) - set(allowed))]
    errors += ["missing required key `%s` %s" % (k, where) for k in required if k not in raw]
    return errors


def as_lines(value, key, where, errors):
    """A prose value of the input as a list of lines: a text is split into lines, a list of texts is taken as it is."""
    if isinstance(value, str):
        return lines_of(value)
    if isinstance(value, list) and all(isinstance(l, str) and "\n" not in l for l in value):
        return list(value)
    errors.append("`%s` %s must be a text (''' ... ''' for several lines) or a list of one-line texts" % (key, where))
    return []


FINDING_KEYS = ("id", "path", "line", "severity", "kind", "summary", "failing_case") + PROSE + ("decided",)
NEW_KEYS = FINDING_KEYS[1:-1]              # a new problem of the checker: its id (N1, ...) is given by the record; the checker decides nothing in it
STATUS_KEYS = ("id", "verdict", "reason", "decided")


def _finding_from(raw, where, errors, keys=FINDING_KEYS):
    """A finding dict from one `[[finding]]`/`[[new]]` table of the input; problems are appended to `errors`. `keys` are
    the allowed keys; the first seven (the first six of a new problem, which has no id) are required."""
    problems = table_errors(raw, where, keys, [k for k in keys if k not in PROSE and k != "decided"])
    errors += problems
    if not isinstance(raw, dict):
        return {}
    out = {k: v for k, v in raw.items() if k in keys and k not in PROSE and k != "failing_case"}
    out["failing_case"] = as_lines(raw["failing_case"], "failing_case", where, errors) if "failing_case" in raw else []
    for key in PROSE:
        out[key] = as_lines(raw.get(key, []), key, where, errors)
    if out.get("severity") in WORDS:
        out["rank"] = WORDS[out["severity"]]
    return out


def _tables(raw, key, build, errors):
    value = raw.get(key, [])
    if not isinstance(value, list):
        errors.append("`%s` must be written as [[%s]] tables" % (key, key))
        return []
    return [build(item, "in [[%s]] %d" % (key, i), errors) for i, item in enumerate(value, 1)]


def _status_from(raw, where, errors):
    errors += table_errors(raw, where, STATUS_KEYS, STATUS_KEYS[:2])
    if not isinstance(raw, dict):
        return {}
    out = {k: raw[k] for k in ("id", "verdict", "decided") if k in raw}
    if "decided" in out and out.get("verdict") != "OUTSIDE":
        errors.append("decided %s is only for the verdict OUTSIDE, got %r" % (where, out.get("verdict")))
    out["reason"] = as_lines(raw.get("reason", []), "reason", where, errors)
    return out


def _report_errors(raw, errors):
    if "report" in raw and not (isinstance(raw["report"], str) and raw["report"].endswith(".json") and raw["report"].strip() != ".json"):
        errors.append("`report` must be the path of the report's JSON file, ending in .json")


def _write_json(path, data):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise VerdictError("nothing recorded: cannot write %s: %s" % (path, exc.strerror))
    return path


def review_data(reviewed, base, findings, scope=(), notes=()):
    """Review data as a dict (the findings already as `_finding_from` makes them); the schema check is the caller's."""
    return {"schema": SCHEMA, "type": REVIEW_TYPE, "reviewed": reviewed, "base": base, "scope": list(scope), "notes": list(notes),
            "findings": findings}


def write_review(path, data):
    """Validate review `data` and write it as JSON at `path` (the library's own writers, e.g. a queue take, use this)."""
    errors = review_errors(data)
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    return _write_json(path, data)


REVIEW_TOP = ("report", "reviewed", "base", "scope", "notes", "finding")


def record_review(input_path):
    """Record a review from the TOML input file at `input_path`; returns the JSON path."""
    raw = read_input(input_path)
    errors = table_errors(raw, "at the top of the input", REVIEW_TOP, REVIEW_TOP[:3])
    if not isinstance(raw, dict) or errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    _report_errors(raw, errors)
    findings = _tables(raw, "finding", _finding_from, errors)
    prose = {k: as_lines(raw.get(k, []), k, "at the top of the input", errors) for k in ("scope", "notes")}
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    return write_review(raw["report"], review_data(raw["reviewed"], raw["base"], findings, prose["scope"], prose["notes"]))


OWNER_USAGE_KEYS = ("words", "queue")


def add_owner(review_path, fid, input_path, today, queue_has=None):
    """Append the owner's word on finding `fid` to the `owner` list of the review JSON at `review_path`: that it is not wrong, or
    (with `queue` in the input) that it moved to that queue item. The TOML input holds `words`, the owner's words as said, and
    optionally `queue`, the item's name; `today` is the date (YYYY-MM-DD) stored with them. `queue_has(name)` says whether the
    item is on the default branch; with a `queue` it must be given and true, else nothing is recorded (the finding stays open).
    Returns the path; VerdictError (nothing changed) for a bad input, an unreadable review or an id it does not have."""
    raw = read_input(input_path, "owner word kept")
    errors = table_errors(raw, "at the top of the input", OWNER_USAGE_KEYS, ("words",))
    if not isinstance(raw, dict) or errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    queue = raw.get("queue")
    if queue is not None and not (isinstance(queue, str) and SLUG.match(queue)):
        errors.append("`queue` must be the name of a queue item (lowercase words with hyphens)")
    elif queue is not None and not (queue_has and queue_has(queue)):
        errors.append("queue item %s not found on the default branch" % queue)
    words = as_lines(raw["words"], "words", "at the top of the input", errors)
    if not any(l.strip() for l in words):
        errors.append("`words` must hold the owner's words")
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    try:
        with open(review_path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise VerdictError("nothing recorded: the review data %s cannot be read: %s" % (review_path, exc.strerror))
    data = load_review(text, "the review data %s" % review_path)
    if fid not in {f["id"] for f in data["findings"]}:
        raise VerdictError("nothing recorded: %s is not a finding of %s" % (fid, review_path))
    entry = {"id": fid, "words": words, "date": today}
    if queue is not None:
        entry["queue"] = queue
    data["owner"] = list(data.get("owner") or []) + [entry]
    return write_review(review_path, data)


def counts_by_rank(findings):
    """{"high": n, "medium": n, "low": n} of finding dicts, whatever words their flow used."""
    counts = {rank: 0 for rank in RANK_ORDER}
    for finding in findings:
        counts[finding["rank"]] += 1
    return counts


# ---------------------------------------------------------------- the check record: built in one order, from git and the inputs

CHECK_TOP = ("report", "head", "worktree", "gate", "review", "item", "scope", "notes", "status", "new")
M_FAILING = ("%s came in from %s (merge %s) after the point this branch was last reviewed or checked.",
             "The branch's own change to it was never judged against the merged code.")
M_PASS = ("At head the branch's own change to the file still does what the review said, against the merged code.",)


def _ok(wt, *args):
    return relay_git.git(wt, *args)[0] == 0


def _is_commit(wt, sha):
    return is_sha(sha) and relay_git.resolve_commit(wt, sha) is not None


def _is_ancestor(wt, older, newer):
    return relay_git.is_ancestor(wt, older, newer)


def _newer(wt, a, b):
    """Of two commits (or None) the one that is a descendant of the other; `a` when neither is."""
    if a is None or b is None:
        return a or b
    return b if _is_ancestor(wt, a, b) else a


def _stated(finding, source, since, **more):
    out = dict(finding, source=source, since=since)
    out.update(more)
    return out


def _review_findings(wt: str, head: str, paths: list[str]) -> list[dict]:
    """The findings of the review JSON files at `paths`, numbered F1, F2, ... across the files in the order given; each keeps
    its file name (`source`), its own id (`source_id`), the sha it was stated against (`since`) and the owner's words on it."""
    out, number = [], 0
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            raise VerdictError("nothing recorded: the review data %s cannot be read (record the review first)" % path)
        review = load_review(text, "the review data %s" % path)
        since = review["reviewed"]
        if not _is_commit(wt, since):
            raise VerdictError("nothing recorded: the review data %s is of %s, which is not a commit of this worktree" % (path, since))
        if not _is_ancestor(wt, since, head):
            import relay_inert
            try:
                moved = relay_inert.twin(wt, since, head)         # a rebase that left the patch alone: the review is of the new commit
            except ValueError:
                moved = None
            if moved is not None:
                since = moved
        if not _is_ancestor(wt, since, head):
            raise VerdictError("nothing recorded: the review data %s is of %s, which is not in the history of head %s" % (path, since, head))
        for finding in review["findings"]:
            number += 1
            owner = [{k: v for k, v in e.items() if k != "id"} for e in review.get("owner") or [] if e["id"] == finding["id"]]
            more = {"owner": owner} if owner else {}
            out.append(_stated(dict(finding, id="F%d" % number), os.path.basename(path), since, source_id=finding["id"], **more))
    return out


def _merge_findings(wt: str, head: str, anchors: list[Optional[str]]) -> list[dict]:
    """One M finding for each file the branch changed (`relay_inert.changed(..., own=True)`) that a merge of the default
    branch (or of a branch it absorbs: a train's merge of a ready change) changed after the anchor, the newest of `anchors` (the branch's last mark and its newest review); with none, the
    point the branch left the default branch. Its `since` is the newest such merge."""
    import relay_inert
    default = relay_git.default_branch(wt)
    if default is None:
        raise VerdictError("nothing recorded: cannot tell the default branch")
    base = "refs/heads/" + default
    anchor = None
    for candidate in anchors:
        anchor = _newer(wt, anchor, candidate)
    if anchor is None:
        rc, out = relay_git.git(wt, "merge-base", base, head)
        if rc != 0:
            raise VerdictError("nothing recorded: no common commit of %s and %s" % (default, head))
        anchor = out
    try:
        ab = relay_inert.absorbed(wt, head)
        own = set(relay_inert.own_since_mark(wt, anchor, head, ab))
    except ValueError as exc:
        raise VerdictError("nothing recorded: %s" % exc)
    if not own:
        return []
    rc, out = relay_git.git(wt, "rev-list", "--merges", "--reverse", "%s..%s" % (anchor, head))
    newest = {}
    for merge in (out.splitlines() if rc == 0 else []):
        second = relay_git.resolve_commit(wt, merge + "^2")
        if second is None:
            continue
        if not _is_ancestor(wt, second, base) and second not in ab.values():
            continue                                                  # not a merge of the default branch or of an absorbed branch
        for name in relay_git.changed_paths(wt, merge + "^1", merge) or []:
            if name in own:
                newest[name] = merge
        for name in relay_inert.dropped(wt, merge, own):                  # a hand-resolved merge that threw the other side's change away
            newest[name] = merge
    found = []
    for number, name in enumerate(sorted(newest), 1):
        merge = newest[name]
        found.append({"id": "M%d" % number, "path": name, "line": 1, "severity": "MEDIUM", "rank": "medium", "kind": "inside",
                      "summary": "%s was changed by a merge of %s after it was last checked" % (name, default),
                      "failing_case": [M_FAILING[0] % (name, default, merge[:12]), M_FAILING[1]], "pass_cases": list(M_PASS),
                      "source": "merge", "since": merge})
    return found


def _gate(wt, head, gate, since=None):
    """(the gate the record keeps or None, [N problems as (path, summary, failing_case lines)]) for the `gate` input: a log
    file name in .relay/checks, a path to a log anywhere (absolute or relative to the worktree), a line
    "pipeline #<n> on <sha> passed", or "none". The log's head and exit are read from the log, never copied. `since` is the
    newest commit a review was of: with "none", only own code changed after it counts as code with no gate."""
    import relay_inert
    problems = []
    if gate in (None, "none"):
        default = relay_git.default_branch(wt)
        if since is None:
            rc, since = relay_git.git(wt, "merge-base", "refs/heads/%s" % default, head) if default else (1, "")
            if rc != 0:
                return None, problems
        try:
            moved = relay_inert.changed(wt, since, head, own=True)
        except ValueError:
            moved = []
        moved = [m for m in moved if not (m.startswith("openspec/") or m.startswith("docs/"))]   # specs and docs are no code
        if moved:
            problems.append((".relay/checks", "no gate result for the code of this change",
                             ["The check was given Gate: none, but %s changed on this branch after the review." % ", ".join(moved[:3]),
                              "No gate ran on the code at head, so nothing shows the whole test suite passes."]))
        return None, problems
    gate = str(gate)
    piped = PIPELINE.match(gate)
    if piped:
        logged, shown, kept, lines = piped.group(1), gate, gate, None
    else:
        base = os.path.basename(gate)
        checks = os.path.join(wt, ".relay", "checks", base)
        if "/" not in gate and not GATE_NAME.match(gate):
            raise VerdictError("nothing recorded: `gate` must be \"none\", a pipeline line or the path of a gate log, got %r" % (gate,))
        path = gate if os.path.isabs(gate) else os.path.join(wt, gate) if "/" in gate else checks
        named = GATE_NAME.match(base)
        inside = named and os.path.realpath(path) == os.path.realpath(checks)
        shown = ".relay/checks/" + base if inside else path
        kept = base if inside else "log " + path
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            return None, [(shown, "the gate log is missing", ["The check names the gate log %s but it cannot be read." % shown])]
        logged = lines[0].strip()[len("head "):] if lines and lines[0].strip().startswith("head ") else None
        code = lines[-1].strip() if lines else ""
        if (inside and logged != named.group(1)) or not is_sha(logged) or not code.startswith("exit ") or not code[5:].isdigit():
            return None, [(shown, "the gate log is not in the gate's form", ["%s must start with `head <sha>` (of its own name, in .relay/checks) and end with `exit <n>`." % shown])]
        if int(code[5:]) != 0:
            problems.append((shown, "the gate is red", ["The gate for %s ended with `%s`." % (logged[:12], code)]))
    try:
        moved = relay_inert.changed(wt, logged, head, archive=True) if _is_commit(wt, logged) else None
    except ValueError:
        moved = None
    if moved is None:
        problems.append((shown, "the gate log is for a commit this worktree does not have", ["Gate commit %s is not a commit of this worktree." % logged[:12]]))
    elif moved:
        problems.append((shown, "the gate log is for other code than head", ["%s changed after the gate ran at %s." % (", ".join(moved[:3]), logged[:12])]))
    return kept, problems


def _n_finding(number, path, summary, failing, head, severity="HIGH"):
    return {"id": "N%d" % number, "path": path, "line": 1, "severity": severity, "rank": WORDS[severity], "kind": "inside",
            "summary": summary, "failing_case": list(failing), "source": "check", "since": head}


def build_findings(wt, head, review_paths, item=None):
    """(branch, item or None, [findings without verdicts]) for the change at `head` in worktree `wt`, in the one order of the
    record: Q1 (the fix item this branch took), F (the reviews), M (merges of the default branch after the last check).
    `item` names the fix item the check is of, for a train that carries several closed ones.
    VerdictError ("nothing recorded: ...") when a part cannot be read."""
    import relay_marks
    import relay_queue
    try:
        branch = relay_git.current_branch(wt, strict=True)
    except relay_git.GitError as exc:
        raise VerdictError("nothing recorded: %s" % exc)
    if branch is None:
        raise VerdictError("nothing recorded: the worktree is not on a branch")
    try:
        held = relay_queue.record_item(wt, item)
    except relay_queue.Refused as exc:
        raise VerdictError("nothing recorded: %s" % exc)
    found, item = [], None
    if held:
        item = held[0]
        found.append(held[1])
    import relay_inert
    try:
        ab = relay_inert.absorbed(wt, head)
    except ValueError as exc:
        raise VerdictError("nothing recorded: %s" % exc)
    if not review_paths and not ab:
        raise VerdictError("nothing recorded: `review` must be a list of at least one review JSON path")     # a merge check is only for a branch that holds ready changes
    reviews = _review_findings(wt, head, review_paths)
    found += reviews
    if not review_paths:             # no review: every own file must be one a merge of a ready change or of the default branch brought
        default = relay_git.default_branch(wt)
        try:
            rc, fork = relay_git.git_strict(wt, "merge-base", "refs/heads/%s" % (default or ""), head)
        except relay_git.GitError as exc:
            raise VerdictError("nothing recorded: %s" % exc)
        if rc != 0:
            raise VerdictError("nothing recorded: no common commit of %s and %s" % (default, head))
        try:
            own_files = relay_inert.changed(wt, fork, head, own=True, absorbed=ab)
        except ValueError as exc:
            raise VerdictError("nothing recorded: %s" % exc)
        merged = {f["path"] for f in _merge_findings(wt, head, [])}
        loose = [n for n in own_files if n not in merged]
        if loose:
            raise VerdictError("nothing recorded: `review` must be a list of at least one review JSON path: %s changed on this branch "
                               "outside a merge of a ready change, and a merge check covers only files a merge combined" % ", ".join(loose[:3]))
    default = relay_git.default_branch(wt)
    try:
        rc, out = relay_git.git_strict(wt, "rev-list", head, "^refs/heads/%s" % default) if default else (1, "")
    except relay_git.GitError as exc:
        raise VerdictError("nothing recorded: %s" % exc)
    own = set(out.splitlines()) if rc == 0 else set()
    for tip in ab.values():                      # the marks of branches inside this one are theirs, not this branch's own
        inside = relay_git.git(wt, "rev-list", tip)[1].split()
        own -= set(inside)
    def kept(commit, mark):            # a mark whose check left an M finding not MET does not move the anchor: it is judged again
        try:
            data = relay_marks.check_data(wt, head, mark.get("check", ""))
        except relay_marks.MarkError:
            return True
        return data is None or all(f["verdict"] == "MET" for f in data["findings"] if f["id"].startswith("M"))
    mark = relay_marks.newest(wt, head, [(c, m) for c, m in relay_marks.marks(wt, head) if c in own and kept(c, m)])
    anchors = [mark[0] if mark else None] + [f["since"] for f in reviews]
    found += _merge_findings(wt, head, anchors)
    return branch, item, found


def finding_list(wt: str, review_paths: list[str], item: Optional[str] = None) -> list[str]:
    with relay_git.reading():
        return _finding_list(wt, review_paths, item)


def _finding_list(wt: str, review_paths: list[str], item: Optional[str] = None) -> list[str]:
    """The lines `relay check findings` prints: each finding the check must give a verdict for, with its id."""
    rc, head = relay_git.git(wt, "rev-parse", "HEAD")
    if rc != 0:
        raise VerdictError("nothing listed: %s is not a git worktree" % wt)
    _, item, found = build_findings(wt, head, review_paths, item)
    out = ["Check of %s" % head, "Item: %s" % (item or "none")]
    for f in found:
        out.append("%s [%s%s, since %s] %s" % (f["id"], f["source"], " " + f["source_id"] if f.get("source_id") else "", f["since"][:12], linter(f)))
    return out


def record_check(input_path: str) -> str:
    with relay_git.reading():      # one run reads, moves no ref: each distinct git question is asked once
        return _record_check(input_path)


def _record_check(input_path: str) -> str:
    """Record the check from the TOML input file at `input_path`: build the record in its one order (the queue item as Q1, the
    reviews' findings, the merge findings, one verdict for each, the checker's own new problems and the gate result) and write
    it at `report`. Refused, nothing written, when a verdict is missing or is for an id that is not a finding. Returns the path."""
    raw = read_input(input_path)
    errors = table_errors(raw, "at the top of the input", CHECK_TOP, ("report", "head", "worktree", "gate", "review"))
    if not isinstance(raw, dict) or errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    _report_errors(raw, errors)
    if "item" in raw and not (_text(raw["item"]) and SLUG.match(raw["item"])):
        errors.append("`item` must be the slug of a queue item")
    statuses = _tables(raw, "status", _status_from, errors)
    new = _tables(raw, "new", lambda item, where, errs: _finding_from(item, where, errs, NEW_KEYS), errors)
    prose = {k: as_lines(raw.get(k, []), k, "at the top of the input", errors) for k in ("scope", "notes")}
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    review_paths = raw["review"]
    if not (isinstance(review_paths, list) and all(_text(p) for p in review_paths)):
        raise VerdictError("nothing recorded: `review` must be a list of at least one review JSON path")
    if not (_text(raw["worktree"]) and os.path.isdir(raw["worktree"])):
        raise VerdictError("nothing recorded: `worktree` must be the path of a worktree")
    wt = os.path.realpath(raw["worktree"])
    head = raw["head"]
    if not _is_commit(wt, head):
        raise VerdictError("nothing recorded: head %s is not a commit of this worktree" % (head,))
    if not _is_ancestor(wt, head, "HEAD"):
        raise VerdictError("nothing recorded: head %s is not the worktree's head or an ancestor of it" % head)
    branch, item, found = build_findings(wt, head, [os.path.abspath(p) for p in review_paths], raw.get("item"))    # no review: only a merge check
    said = {}
    for status in statuses:
        if status.get("id") in said:
            errors.append("findings: %s has two verdicts" % status["id"])
        said[status.get("id")] = status
    ids = [f["id"] for f in found]
    errors += ["findings: %s is not a finding of this check (relay check findings lists them)" % i for i in said if i not in ids]
    errors += ["findings: no verdict for %s" % i for i in ids if i not in said]
    newest_review = None
    for path in review_paths:
        newest_review = _newer(wt, newest_review, load_review(open(os.path.abspath(path), encoding="utf-8").read(), path)["reviewed"])
    name, gate_problems = _gate(wt, head, raw["gate"], newest_review)
    problems = [_n_finding(n, p[0], p[1], p[2], head) for n, p in enumerate(gate_problems, len(new) + 1)]
    news = []
    for n, f in enumerate(new, 1):
        news.append(_stated(dict(f, id="N%d" % n), "check", head))
    findings = []
    for f in found + news + problems:
        status = said.get(f["id"], {})
        verdict = status.get("verdict", "NOT MET")
        base = dict(f)
        if "decided" in status:
            base["decided"] = status["decided"]
        elif verdict == "OUTSIDE":
            base.pop("decided", None)       # the reviewer's decided is not the checker's scope cut: an OUTSIDE without its own decided stays open
        findings.append(dict(base, verdict=verdict, reason=status.get("reason", [])))
    data = {"schema": RECORD_SCHEMA, "type": CHECK_TYPE, "head": head, "branch": branch, "item": item, "gate": name,
            "worktree": wt, "scope": prose["scope"], "notes": prose["notes"], "findings": findings}
    errors += record_errors(data)
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    return _write_json(raw["report"], data)
