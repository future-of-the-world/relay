"""Review and check data as JSON, the only stored form of a report (docs/plans/review-gate.md sections 3, 4.1, 6).

A review (critic or any judge) records `<report>.json`; a checker records the same for its check. Nothing readable is
stored beside the data: `render_review` / `render_check` / `render_set` and their `brief_*` forms print the readable text
from the JSON on demand (`relay check show`). The JSON is written by `record_review` / `record_check` (the commands
`relay check record review|check --input <file.toml>`), never typed by an agent: the agent writes a TOML input file
(multi-line text in '''...''' keeps every character, so no text passes through the shell), this module validates it
against the schemas below (no outside library) and refuses bad input with a message that names the field.

Every file carries "schema": 1 (a version, for later conversions) and "type". Prose is stored as lists of lines.
Review data:  {"schema": 1, "type": "review", "reviewed": <full sha or "unknown">, "base": <sha or ref>,
               "scope": [line, ...], "notes": [line, ...], "findings": [FINDING, ...],
               "owner": [{"id": of a finding, "words": [line, ...], "date": "YYYY-MM-DD"}, ...]}   (a stored set adds "file")
The owner's word that a finding is not wrong is data: `relay check owner <review.json> <id> --input <file.toml>`
(`add_owner`) appends to "owner" the words as the owner said them; a checker counts such a finding as not wrong.
FINDING:      {"id": "F<n>" or "Q<n>", "path", "line": int >= 1, "severity": a word of WORDS (the flow's own),
               "rank": high|medium|low, "kind": inside|outside|design|feature|question, "summary",
               "failing_case": [line, ...] (at least one), "details", "pass_cases", "evidence", "fix_hint": [line, ...]}
Check data:   {"schema": 1, "type": "check", "head": <full sha>, "reviewed": <full sha>, "gate": <log path> or null,
               "worktree": <path> (left out of the stored copy), "review": [<review json path>, ...],
               "scope": [...], "notes": [...],
               "findings": [{"id", "verdict": MET|NOT MET|DISPUTED|GAP|OUTSIDE|QUEUED, "reason": [line, ...]}],
               "new": [FINDING, ...], "open": int >= 0, "queued": int >= 0}
Stored review set (`.relay/checks/<reviewed>.review.json`): {"schema": 1, "type": "review-set", "reviewed": <sha>,
               "reviews": [review data with "file", ...]}
"""

import json
import os
import re

SCHEMA = 1
REVIEW_TYPE, CHECK_TYPE, SET_TYPE = "review", "check", "review-set"
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
FINDING_ID = re.compile(r"^[FQ]\d+\Z")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
PROSE = ("details", "pass_cases", "evidence", "fix_hint")       # a finding's optional prose, as lists of lines
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


def finding_errors(finding, where):
    if not isinstance(finding, dict):
        return ["%s is not an object" % where]
    errors = []
    allowed = {"id", "path", "line", "severity", "rank", "kind", "summary", "failing_case"} | set(PROSE)
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


def check_errors(data, stored=False):
    """[message] for check data that breaks the schema; the stored copy has no `worktree`."""
    if not isinstance(data, dict):
        return ["the check data is not an object"]
    errors = _head_errors(data, CHECK_TYPE)
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
            for key in sorted(set(item) - {"id", "verdict", "reason"}):
                errors.append("%s has an unknown field %s" % (where, key))
            if not (isinstance(item.get("id"), str) and FINDING_ID.match(item["id"])):
                errors.append("%s: id must look like F1, got %r" % (where, item.get("id")))
            if item.get("verdict") not in VERDICTS:
                errors.append("%s: verdict must be one of %s, got %r" % (where, "/".join(VERDICTS), item.get("verdict")))
            _prose_errors(item, "reason", where, errors)
            if item.get("id") in seen:
                errors.append("%s: id %s is used twice" % (where, item.get("id")))
            seen.add(item.get("id"))
    errors += _findings_errors(data.get("new"), "new")
    for key in sorted(set(data) - {"schema", "type", "head", "reviewed", "gate", "worktree", "review", "scope", "notes", "findings", "new", "open", "queued"}):
        errors.append("unknown field %s" % key)
    return errors


def set_errors(data):
    if not isinstance(data, dict):
        return ["the stored review is not an object"]
    errors = _head_errors(data, SET_TYPE)
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


def load_any(text, what="the data"):
    """(type, data) of a review, check or stored review set, by its `type`; VerdictError when it is none of them or invalid.
    A check with a `worktree` is a recorded one, without it a stored one."""
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise VerdictError("%s is not JSON: %s" % (what, exc))
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    if kind == REVIEW_TYPE:
        return kind, load_review(text, what)
    if kind == CHECK_TYPE:
        return kind, load_check(text, what, stored="worktree" not in parsed)
    if kind == SET_TYPE:
        return kind, load_set(text, what)
    raise VerdictError("%s is not a review, a check or a stored review (type %r)" % (what, kind))


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


def render_check(data):
    """The full readable text of check data."""
    out = ["Check of %s" % data["head"], "Reviewed: %s" % data["reviewed"], "Gate: %s" % (data["gate"] or "none"),
           "Open: %d  Queued: %d" % (data["open"], data["queued"])]
    _prose_head(out, data)
    out.append("Findings checked: %d" % len(data["findings"]))
    for item in data["findings"]:
        out.append("%s %s" % (item["id"], item["verdict"]))
        out += ["  " + l for l in item.get("reason") or []]
    if data["new"]:
        out += ["", "New problems: %d" % len(data["new"])]
        for finding in data["new"]:
            out += [""] + finding_lines(finding)
    return "\n".join(out) + "\n"


def render_set(data):
    """The full readable text of a stored review set: each review under its findings file's name."""
    out = []
    for review in data["reviews"]:
        out += ["# %s" % review.get("file", "review")] + _review_lines(review) + [""]
    return "\n".join(out).rstrip("\n") + "\n"


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


def brief_check(data, source="<report>"):
    out = ["Check of %s (reviewed %s): open %d, queued %d, gate %s" % (
        data["head"][:12], data["reviewed"][:12], data["open"], data["queued"], os.path.basename(data["gate"]) if data["gate"] else "none")]
    for item in data["findings"]:
        reason = item.get("reason") or []
        out.append(("%s %s %s" % (item["id"], item["verdict"], reason[0] if reason else "")).rstrip())
    out += ["new: " + linter(f) for f in data["new"]]
    return "\n".join(_cut(out, source)) + "\n"


def brief_set(data, source="<report>"):
    found = [f for r in data["reviews"] for f in r["findings"]]
    out = ["Review of %s: %d findings in %d files" % (data["reviewed"][:12], len(found), len(data["reviews"]))] + [linter(f) for f in found]
    return "\n".join(_cut(out, source)) + "\n"


def render_any(text, brief=False, source="<report>", what="the data"):
    """The readable text (or the 10-line summary) of a review, check or stored review set given as JSON text."""
    kind, data = load_any(text, what)
    full = {REVIEW_TYPE: render_review, CHECK_TYPE: render_check, SET_TYPE: render_set}
    short = {REVIEW_TYPE: brief_review, CHECK_TYPE: brief_check, SET_TYPE: brief_set}
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


FINDING_KEYS = ("id", "path", "line", "severity", "kind", "summary", "failing_case") + PROSE
STATUS_KEYS = ("id", "verdict", "reason")


def _finding_from(raw, where, errors):
    """A finding dict from one `[[finding]]`/`[[new]]` table of the input; problems are appended to `errors`."""
    problems = table_errors(raw, where, FINDING_KEYS, FINDING_KEYS[:7])
    errors += problems
    if not isinstance(raw, dict):
        return {}
    out = {k: v for k, v in raw.items() if k in FINDING_KEYS and k not in PROSE and k != "failing_case"}
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
    out = {k: raw[k] for k in ("id", "verdict") if k in raw}
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


CHECK_TOP = ("report", "head", "reviewed", "worktree", "gate", "review", "scope", "notes", "status", "new", "open", "queued")


def record_check(input_path):
    """Record a check from the TOML input file at `input_path`. Every review data file must be valid and name the same
    `reviewed`; every checked id must be a finding of those reviews or a new one. Returns the JSON path."""
    raw = read_input(input_path)
    errors = table_errors(raw, "at the top of the input", CHECK_TOP, ("report", "head", "reviewed", "worktree", "gate", "review", "open", "queued"))
    if not isinstance(raw, dict) or errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    _report_errors(raw, errors)
    statuses = _tables(raw, "status", _status_from, errors)
    new = _tables(raw, "new", _finding_from, errors)
    prose = {k: as_lines(raw.get(k, []), k, "at the top of the input", errors) for k in ("scope", "notes")}
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    review_paths = raw["review"]
    if not (isinstance(review_paths, list) and review_paths and all(_text(p) for p in review_paths)):
        raise VerdictError("nothing recorded: `review` must be a list of at least one review JSON path")
    paths = [os.path.abspath(p) for p in review_paths]
    known = set()
    loaded = []
    for path in paths:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            raise VerdictError("nothing recorded: the review data %s cannot be read (record the review first)" % path)
        review = load_review(text, "the review data %s" % path)
        if review["reviewed"] != raw["reviewed"]:
            raise VerdictError("nothing recorded: the review data %s is of %s, not of the reviewed sha %s" % (path, review["reviewed"], raw["reviewed"]))
        known |= {f["id"] for f in review["findings"]}
        loaded.append(review)
    gate = raw["gate"]
    data = {"schema": SCHEMA, "type": CHECK_TYPE, "head": raw["head"], "reviewed": raw["reviewed"], "gate": None if gate in (None, "none") else gate,
            "worktree": os.path.realpath(raw["worktree"]) if _text(raw["worktree"]) else raw["worktree"], "review": paths,
            "scope": prose["scope"], "notes": prose["notes"], "findings": statuses, "new": new, "open": raw["open"], "queued": raw["queued"]}
    errors = check_errors(data)
    known |= {f["id"] for f in data["new"] if isinstance(f, dict)}
    errors += ["findings: %s is not a finding of the reviews or a new one" % s["id"] for s in statuses if s.get("id") not in known]
    if not errors:
        # `open` is typed by the checker but the merge gate trusts it: it may not be below what the verdicts say
        floor = floor_error(loaded, data)
        errors += [floor] if floor else []
    if errors:
        raise VerdictError("nothing recorded: " + "; ".join(errors))
    return _write_json(raw["report"], data)


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


def owner_ids(review):
    """The ids of review data that have an owner entry saying not wrong (an entry with a `queue` is a move, not that word)."""
    return {e["id"] for e in review.get("owner") or [] if not e.get("queue")}


def moved_ids(review):
    """The ids of review data the owner moved to a queue item: they count under the check's `queued`, not `open`."""
    return {e["id"] for e in review.get("owner") or [] if e.get("queue")}


def count_open(review, statuses):
    """How many HIGH or MEDIUM findings inside the change of review data `review` are NOT MET in `statuses` (the check's
    [{"id", "verdict"}]) and have no owner entry. A finding with no status counts as NOT MET. (The checker adds the new
    problems and its own +1s.)"""
    said = {s["id"]: s["verdict"] for s in statuses}
    owned = owner_ids(review)
    return sum(1 for f in review["findings"]
               if f["kind"] == "inside" and f["rank"] in ("high", "medium") and said.get(f["id"]) != "MET" and f["id"] not in owned)


def open_floor(reviews, check):
    """The ids of the findings that must count as open in check data `check` (a dict with `findings` and `new`): the HIGH or
    MEDIUM inside findings of the review data dicts `reviews` that are not MET and have no owner entry (`count_open`'s rule),
    and the check's own new inside HIGH or MEDIUM findings. The checker's `open` may be higher (its +1s), never lower."""
    ids = []
    for review in reviews:
        said = {s["id"]: s["verdict"] for s in check["findings"]}
        owned = owner_ids(review)
        ids += [f["id"] for f in review["findings"]
                if f["kind"] == "inside" and f["rank"] in ("high", "medium") and said.get(f["id"]) != "MET" and f["id"] not in owned]
    ids += [f["id"] for f in check["new"] if f["kind"] == "inside" and f["rank"] in ("high", "medium")]
    return ids


def floor_error(reviews, check):
    """The refusal text when `check`'s `open` is below `open_floor`, else None."""
    ids = open_floor(reviews, check)
    if check["open"] < len(ids):
        return "open is %d but %d findings inside the change are not met: %s" % (check["open"], len(ids), ", ".join(ids))
    moved = sorted(i for review in reviews for i in moved_ids(review))
    if check["queued"] < len(moved):
        return "queued is %d but the owner moved %d findings to queue items: %s" % (check["queued"], len(moved), ", ".join(moved))
    return None


def stored_set(reviews, reviewed):
    """The stored review set (a dict) for review data dicts `reviews`, each marked with its findings file's name."""
    return {"schema": SCHEMA, "type": SET_TYPE, "reviewed": reviewed, "reviews": reviews}


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
