# size: over the 600-line limit until its split item lands
"""The work queue: items kept as `.relay/queue/<slug>.json` on the default branch (design: docs/plans/review-gate.md, section 10).

An item is a JSON file, written only by this module (`serialize`) and read only by it (`parse`), so the format
lives in one place. Extensions in `lib/queue_ext/` read parsed copies of the items; they never write.

Everything reads the default branch through git (`ls-tree`, `cat-file --batch`), never a checkout, so
every worktree sees the same queue. Commands that change an item land one commit on the default branch
without touching any checkout (`hash-object`, a temporary index, `commit-tree`), on a branch
`wt/queue-<slug>` that is created only if absent, and fast-forward the main checkout to it. Each try
re-reads the head and re-checks the command's precondition; after `QUEUE_LAND_TRIES` failed tries the
branch is kept for `relay queue land`.
"""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import ast
import copy
import datetime as dt
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

if TYPE_CHECKING:   # Python 3.9 has no typing.TypeGuard; annotations are never evaluated at run time
    from typing import TypeGuard

import relay_git
import relay_verdict

QUEUE_LAND_TRIES = 5          # bound 1-20: at 20 a landing can take about 20 s
MAX_TRIES = 20
WAITS = (0.2, 0.4, 0.8, 1.0)  # seconds between tries; the last repeats (0.2-1 s, design 10.4)
QDIR = ".relay/queue"
EXT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue_ext")
EXT_NAME = re.compile(r"[a-z][a-z0-9_]*")
ZERO = "0" * 40
KINDS = ("fix", "feature")
# What the failing case of a fix rests on. A "claim" (a reviewer's, a scout's, the front's) is reproduced before the build.
FAILING_KINDS = ("test", "run", "claim")
# The keys of an item file, in the order they are written. An item keeps dated events, never a stored state: `state_of` computes it.
# TEXT are lists of lines (so a git diff goes line by line).
ORDER = ("kind", "ip", "time", "found_at", "found_in", "title", "what", "why", "failing_case", "failing_kind", "pass_cases", "where",
         "taken_at", "taken_by", "closed_at", "test", "fixed_by", "evidence", "dropped_at", "dropped_why", "notes")
TEXT = ("what", "why", "failing_case", "pass_cases")
EVENTS = ("found_at", "taken_at", "closed_at", "dropped_at")
OLD_ONLY = ("state", "found", "closed_by")    # the keys of the shape before dated events; `relay queue migrate` rewrites them
REQUIRED = ("kind", "ip", "time", "found_at", "found_in", "title", "what", "why", "taken_at", "taken_by", "closed_at", "test",
            "dropped_at", "dropped_why")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MIGRATE_HINT = "run `relay queue migrate` on this branch"
STRAY_DONE = "the done/ folder is gone: run `relay queue migrate` to move this file back into .relay/queue/"
TEST_RUN_SECONDS = 120        # one run of a named test at one commit (`close_fixed_by`); a slower test is refused, not waited for
TITLE_MAX = 60                # a title is under this many characters (rules/queue.md)


class Refused(ValueError):
    """The command was refused or could not land; the message is for the person. Nothing was written unless it says so."""


# ---------------------------------------------------------------- item files

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_lines(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


class Place(NamedTuple):
    """One element of an item's `where`: the place as its first word (`path`, `path:N` or `path:N-M`), then a note for people."""
    path: str
    line: Optional[int]
    end: Optional[int]
    note: str


PLACE_WORD = re.compile(r"([^\s:()]+)(?::(\d+)(?:-(\d+))?)?")


def parse_place(element: str) -> Optional[Place]:
    """The Place an element of `where` says, or None when its first word is not `path`, `path:N` or `path:N-M`
    (N from 1, M not before N). The one reader of that string: the schema check, Q1 and `show` all use it."""
    parts = element.split(None, 1)
    found = PLACE_WORD.fullmatch(parts[0]) if parts and element == element.strip() else None
    if found is None:
        return None
    line = int(found.group(2)) if found.group(2) else None
    end = int(found.group(3)) if found.group(3) else None
    if line is not None and line < 1 or end is not None and end < (line or 0):
        return None
    return Place(found.group(1), line, end, parts[1] if len(parts) > 1 else "")


def where_problems(value: object) -> list[str]:
    """Why `where` (a list of places, each a string `parse_place` reads) is not well formed; [] when it is."""
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        return ["where is not a list of places"]
    if not value:
        return ["where is empty (leave the key out)"]
    return [f"where element {n} does not start with path, path:N or path:N-M" for n, element in enumerate(value, 1) if parse_place(element) is None]


def where_folders(where: object, repo: str, stored: object = None) -> list[str]:
    """Why a `where` entry names a folder or a pattern instead of a file, one text per entry; [] when every entry is a file (a file
    that does not exist yet is fine). Entries also in `stored` (the old list of an edit) are not judged. Run by `add` and by `edit` of `where`, never by `where_problems`: `check` has no tree."""
    if not isinstance(where, list):
        return []
    out = []
    for n, element in enumerate(where, 1):
        place = parse_place(element) if isinstance(element, str) else None
        if place is None or (isinstance(stored, list) and element in stored):
            continue
        path = place.path
        if path.endswith("/") or os.path.isdir(os.path.join(repo, path)):
            kind = "a folder"
        elif any(mark in path for mark in "*?["):
            kind = "a pattern"
        else:
            continue
        out.append(f"where element {n} `{path}` is {kind}: name the file you will change (a new file is fine, e.g. lib/relay_cmd/digest.py)")
    return out


def state_of(item):
    """open, taken, done or dropped, computed from the events: dropped_at, then closed_at, then taken_at; none is open."""
    if item.get("dropped_at"):
        return "dropped"
    if item.get("closed_at"):
        return "done"
    if item.get("taken_at"):
        return "taken"
    return "open"


def utcnow():
    """The time now as the UTC timestamp an event is stored as (tests replace this function)."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp(value):
    if not (isinstance(value, str) and TIMESTAMP.fullmatch(value)):
        return False
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------- notes

class Note(NamedTuple):
    """One note of an item: what the owner said (`said`), a measured or observed fact (`fact`), or a decision (a question as it was
    asked, its lettered options, and, once the owner replied, his whole reply and the front's reading of it). The one typed record
    of a note: `parse_note` builds it, `note_dict` writes it, every reader goes through them."""
    kind: str                    # said | fact | decision
    at: str                      # when it was said, measured, or (a decision) asked
    text: list                   # the lines said or measured; for a decision, the question block as asked
    number: int = 0              # a decision recorded before 28 Oct: its number in the reply that asked it; 0 for every other note (new questions have none)
    options: list = []           # a decision: the lettered lines as shown
    answered_at: Optional[str] = None
    answer: list = []            # the owner's whole reply, every explanation included
    reading: list = []           # the front's reading of the answer, always shown as the front's
    edited: str = ""             # a fact note written by `relay queue edit`: the field it edited (data, not prose); "" for the others
    decided_by: str = ""         # a decision an agent took itself (one of DECIDERS); "" for a question the owner was asked
    chosen: str = ""             # the letter the agent chose; set exactly when decided_by is
    because: list = []           # the agent's reason; set exactly when decided_by is
    answer_choice: str = ""      # the letter the owner's answer carries, "" when it carries none


DECIDERS = ("front",)       # who may record a decision of their own; a reviewer's decisions live in the check record
NOTE_ONE_OF = {"said", "fact", "question"}
NOTE_KEYS = {"said": ("at", "said"), "fact": ("at", "fact", "edited"),
             "question": ("asked_at", "number", "question", "options", "decided_by", "chosen", "because", "answered_at", "answer",
                          "answer_choice", "reading")}


def note_dict(note: Note) -> dict:
    """The JSON object of a note, keys in the order they are written."""
    if note.kind == "said":
        return {"at": note.at, "said": list(note.text)}
    if note.kind == "fact":
        if note.edited:
            return {"at": note.at, "edited": note.edited, "fact": list(note.text)}
        return {"at": note.at, "fact": list(note.text)}
    out: dict = {"asked_at": note.at}
    if note.number:
        out["number"] = note.number         # only a question recorded with a number keeps it
    out.update(question=list(note.text), options=list(note.options))
    if note.decided_by:
        out.update(decided_by=note.decided_by, chosen=note.chosen, because=list(note.because))
    if note.answered_at:
        out.update(answered_at=note.answered_at, answer=list(note.answer))
        if note.answer_choice:
            out["answer_choice"] = note.answer_choice
        if note.reading:
            out["reading"] = list(note.reading)
    return out


def option_problem(options: object) -> Optional[str]:
    """Why `options` are not the stored form (at least two lines starting a. , b. , ... in order), or None. The one rule of the schema
    check and of the `note` input."""
    if not _is_lines(options) or len(options) < 2:
        return "options are not at least two lines starting a. , b. , ... in order"
    for n, line in enumerate(options):
        if not line.startswith(f"{chr(97 + n)}. "):
            return "options are not at least two lines starting a. , b. , ... in order"
    return None


def parse_note(raw: object) -> tuple:
    """(Note, []) for a well-formed note object, else (None, reasons). The one reader of a note's JSON: the schema check and `parse`
    both use it."""
    if not isinstance(raw, dict):
        return None, ["is not an object"]
    kinds = sorted(NOTE_ONE_OF & set(raw))
    if len(kinds) != 1:
        return None, ["has none of said, fact, question" if not kinds else f"has more than one of {', '.join(kinds)}"]
    kind = kinds[0]
    problems = [f"has the unknown key {key}" for key in sorted(set(raw) - set(NOTE_KEYS[kind]))]
    stamp = "asked_at" if kind == "question" else "at"
    if not _timestamp(raw.get(stamp)):
        problems.append(f"{stamp} is not a UTC time YYYY-MM-DDTHH:MM:SSZ")
    if not _nonblank(raw.get(kind)):
        problems.append(f"{kind} is not a non-empty list of lines")
    if "edited" in raw and (kind != "fact" or raw["edited"] not in EDIT_FIELDS):
        problems.append("edited is not a field that `relay queue edit` edits")
    if kind != "question":
        return (None, problems) if problems else (Note(kind, raw["at"], list(raw[kind]), edited=raw.get("edited", "")), [])
    number: Any = raw.get("number", 0)
    options: Any = raw.get("options")
    if "number" in raw and (not isinstance(number, int) or isinstance(number, bool) or number < 1):
        problems.append("number is not a whole number from 1")
    bad_options = option_problem(options)
    if bad_options:
        problems.append(bad_options)
    answered, answer, reading = raw.get("answered_at"), raw.get("answer"), raw.get("reading")
    if ("answered_at" in raw) != ("answer" in raw):
        problems.append("answer is set exactly when answered_at is")
    elif "answered_at" in raw:
        if not _timestamp(answered):
            problems.append("answered_at is not a UTC time YYYY-MM-DDTHH:MM:SSZ")
        elif _timestamp(raw.get("asked_at")) and answered < raw["asked_at"]:
            problems.append("answered_at is before asked_at")
        if not _nonblank(answer):
            problems.append("answer is not a non-empty list of lines")
    if "reading" in raw and ("answer" not in raw or not _nonblank(reading)):
        problems.append("reading needs an answer and is a non-empty list of lines")
    letters = [chr(97 + n) for n in range(len(options))] if isinstance(options, list) else []
    deciding = [k for k in ("decided_by", "chosen", "because") if k in raw]
    if deciding and len(deciding) != 3:
        problems.append("decided_by, chosen and because go together; missing " + ", ".join(k for k in ("decided_by", "chosen", "because") if k not in raw))
    elif deciding:
        if raw["decided_by"] not in DECIDERS:
            problems.append("decided_by is one of: " + ", ".join(DECIDERS))
        if raw["chosen"] not in letters:
            problems.append("chosen is not the letter of one of the options")
        if not _nonblank(raw["because"]):
            problems.append("because is not a non-empty list of lines")
    if "answer_choice" in raw and ("answer" not in raw or raw["answer_choice"] not in letters):
        problems.append("answer_choice needs an answer and is the letter of one of the options")
    if problems:
        return None, problems
    return Note("decision", raw["asked_at"], list(raw["question"]), number, list(options), answered,
                list(answer or []), list(reading or []), "", raw.get("decided_by", ""), raw.get("chosen", ""),
                list(raw.get("because") or []), raw.get("answer_choice", "")), []


def notes_problems(data: dict) -> list:
    """Why the `notes` of a decoded item are not well formed ([] when they are, or there are none)."""
    if "notes" not in data:
        return []
    notes = data["notes"]
    if not isinstance(notes, list) or not notes:
        return ["notes is not a non-empty list (leave the key out)"]
    problems, parsed = [], []
    for n, raw in enumerate(notes, 1):
        note, why = parse_note(raw)
        problems += [f"note {n} {w}" for w in why]
        parsed.append(note)
    found = data.get("found_at")
    for n, note in enumerate(parsed, 1):
        if note is not None and _timestamp(found):
            times = [note.at] + ([note.answered_at] if note.answered_at else [])
            if any(t < found for t in times):
                problems.append(f"note {n} is dated before found_at")
    stamps = [x.at for x in parsed if x is not None]
    if stamps != sorted(stamps):
        problems.append("notes are not in date order")
    return problems


def notes_of(item: dict) -> list:
    """The Notes of a parsed item ([] when it has none)."""
    return list(item.get("notes") or [])


def check(slug, data):
    """The reasons `data` (a decoded item file) is not a well-formed item; [] when it is."""
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    old = [k for k in OLD_ONLY if k in data]
    if old:
        return [f"old shape ({', '.join(old)}): {MIGRATE_HINT}"]
    problems = []
    for key in sorted(set(data) - set(ORDER)):
        problems.append(f"unknown key {key}")
    for key in REQUIRED:
        if key not in data:
            problems.append(f"missing key {key}")
    if data.get("kind") == "fix" and not _nonblank(data.get("failing_case")):
        problems.append("a fix without failing_case")
    if "kind" in data and data["kind"] not in KINDS:
        problems.append("kind is not fix or feature")
    if "failing_kind" in data and data["failing_kind"] not in FAILING_KINDS:
        problems.append("failing_kind is not test, run or claim")
    for key in ("ip", "time"):
        if key in data and not _is_int(data[key]):
            problems.append(f"{key} is not a whole number from 0")
    for key in EVENTS:
        if key in data and data[key] is not None and not _timestamp(data[key]):
            problems.append(f"{key} is not null or a UTC time YYYY-MM-DDTHH:MM:SSZ")
    if "found_at" in data and data["found_at"] is None:
        problems.append("found_at is null")
    if "where" in data:
        problems += where_problems(data["where"])
    for key in ("found_in", "title"):
        if key in data and not isinstance(data[key], str):
            problems.append(f"{key} is not a string")
    for key in ("taken_by", "test", "evidence", "fixed_by"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            problems.append(f"{key} is not null or a string")
        elif data.get(key) == "":
            problems.append(f"{key} is null or a non-empty string")
    for key in TEXT:
        if key in data and not _is_lines(data[key]):
            problems.append(f"{key} is not a list of lines")
    if "dropped_why" in data and data["dropped_why"] is not None and not _is_lines(data["dropped_why"]):
        problems.append("dropped_why is not null or a list of lines")
    elif data.get("dropped_why") == []:
        problems.append("dropped_why is null or a non-empty list of lines")
    found, taken, closed, dropped = (data.get(k) for k in ("found_at", "taken_at", "closed_at", "dropped_at"))
    if bool(data.get("taken_by")) != (taken is not None):
        problems.append("taken_by is set exactly when taken_at is set")
    evidence = data.get("evidence")
    fixed_by = data.get("fixed_by")
    if closed is not None and taken is None and not evidence and not fixed_by:
        problems.append("closed_at without taken_at")
    if closed is not None and not data.get("test") and not evidence:
        problems.append("closed_at without a test or evidence")
    if data.get("test") and evidence:
        problems.append("a test together with evidence: a close has one or the other")
    if data.get("test") and closed is None:
        problems.append("a test without closed_at")
    if fixed_by and (data.get("kind") != "fix" or closed is None or not data.get("test")):
        problems.append("fixed_by belongs to a closed fix with a test")
    if evidence and closed is None:
        problems.append("evidence without closed_at")
    if evidence and data.get("kind") == "fix":
        problems.append("a fix is closed with a test, not with evidence")
    if dropped is not None and not data.get("dropped_why"):
        problems.append("dropped_at without dropped_why")
    if data.get("dropped_why") and dropped is None:
        problems.append("dropped_why without dropped_at")
    if dropped is not None and (taken is not None or closed is not None):
        problems.append("dropped_at together with taken_at or closed_at")
    for chain in ((found, taken, closed), (found, dropped)):
        stamps = [t for t in chain if _timestamp(t)]
        if stamps != sorted(stamps):
            problems.append("the times are not in order: found_at <= taken_at <= closed_at, found_at <= dropped_at")
            break
    problems += notes_problems(data)
    _title_problems(slug, data, problems)
    return problems


def _title_problems(slug, data, problems):
    # "repeats the name" means typed as the slug itself (hyphens): a lowercase sentence is a title, and its slug is its words
    if isinstance(data.get("title"), str):
        if "\n" in data["title"]:
            problems.append("the title is not one line")
        if data["title"].strip() in ("", slug):
            problems.append("the title only repeats the name")
    if _is_lines(data.get("what")) and "\n".join(data["what"]).strip() in ("", slug):
        problems.append("what only repeats the name")


def _nonblank(lines):
    return _is_lines(lines) and any(x.strip() for x in lines)


def parse(slug, text, where=None):
    """An item as a dict: the fields of the file, the computed `state`, `slug` and `problems` (empty when well formed).
    `where` is ignored: it stays because the default branch's merge hook still passes a third value (the folder) until this change lands.

    A file that fails the check (an old-shape one too) comes back as {"slug", "problems"} only, so nothing reads half an item."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return {"slug": slug, "problems": [f"not valid JSON: {exc}"]}
    problems = check(slug, data)
    if problems:
        return {"slug": slug, "problems": problems}
    item = {key: data[key] for key in ORDER if key in data}
    if "notes" in item:
        item["notes"] = [parse_note(raw)[0] for raw in item["notes"]]
    item.update(state=state_of(data), slug=slug, problems=[])
    return item


def serialize(slug, item):
    """The file text of an item: indent 2, fixed key order, UTF-8, a trailing newline. Refused when it fails the check."""
    data = {key: item[key] for key in ORDER if key in item}
    if "notes" in data:
        data["notes"] = [note_dict(n) if isinstance(n, Note) else n for n in data["notes"]]
    extra = sorted(set(item) - set(ORDER) - {"slug", "problems", "state"})
    problems = check(slug, data) + [f"unknown key {k}" for k in extra]
    if problems:
        raise Refused(f"item '{slug}' is not well formed: {'; '.join(problems)}")
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def changed(item, **changes):
    """The item's fields with `changes` applied (a new dict; `slug`, `problems` and the computed `state` dropped)."""
    out = {key: copy.deepcopy(item[key]) for key in ORDER if key in item}
    out.update(changes)
    return out


def lines_of(text):
    """Text as the list of its lines (blank lines at its start and end dropped, the lines themselves unchanged)."""
    return relay_verdict.lines_of(text)


def joined(item, key):
    return "\n".join(item.get(key) or [])


def new_item(kind, ip, minutes, found_at, found_in, title, what, why, failing="", pass_cases="", where=(), failing_kind=""):
    item = {"kind": kind, "ip": ip, "time": minutes, "found_at": found_at, "found_in": found_in,
            "title": title, "what": lines_of(what), "why": lines_of(why)}
    if failing.strip():
        item["failing_case"] = lines_of(failing)
    if failing_kind:
        item["failing_kind"] = failing_kind
    if pass_cases.strip():
        item["pass_cases"] = lines_of(pass_cases)
    if where:
        item["where"] = list(where)
    item.update({"taken_at": None, "taken_by": None, "closed_at": None, "test": None, "dropped_at": None, "dropped_why": None})
    return item


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48].strip("-")
    if not slug:
        raise Refused("the title has no letters or digits to make a name from")
    return slug


def order_key(item):
    return (item["kind"] != "fix", -item["ip"], item["found_at"], item["slug"])


def ordered(items):
    """Well-formed items fix before feature, then by ip (highest first), then older `found_at`, then slug; malformed ones last, by slug."""
    good = sorted((i for i in items if not i["problems"]), key=order_key)
    bad = sorted((i for i in items if i["problems"]), key=lambda i: i["slug"])
    return good + bad


def format_time(minutes):
    """Minutes as a person reads them: 20m, 1h, 1h 30m."""
    if minutes < 60:
        return f"{minutes}m"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h" + (f" {rest}m" if rest else "")


TIME_FORMS = "20m, 1h, 1h30m, \"1h 30m\" or a whole number of minutes"


def parse_time(text):
    """`20m`, `1h`, `1h30m`, `1h 30m` or bare minutes to whole minutes; Refused for anything else."""
    m = re.fullmatch(r"(\d+)|(?:(\d+)h)? ?(?:(\d+)m)?", text.strip())
    if not m or not text.strip():
        raise Refused(f"time '{text}' is not understood; use {TIME_FORMS}")
    if m.group(1) is not None:
        return int(m.group(1))
    return int(m.group(2) or 0) * 60 + int(m.group(3) or 0)


def count_text(items):
    """`10 fix, 12 feature; top: slug (fix, ip 95, 30m)` over the open, well-formed items."""
    open_items = [i for i in items if not i["problems"] and i["state"] == "open"]
    fix = sum(1 for i in open_items if i["kind"] == "fix")
    text = f"{fix} fix, {len(open_items) - fix} feature"
    if open_items:
        top = sorted(open_items, key=order_key)[0]
        text += f"; top: {top['slug']} ({top['kind']}, ip {top['ip']}, {format_time(top['time'])})"
    return text


def show_text(item, tz=None):
    """One well-formed item in full, as the person reads it (a read-only view of the stored JSON)."""
    state = item["state"] + (f" by {item['taken_by']}" if item["taken_by"] else "")
    out = [f"{item['slug']}: {item['title']}", f"{item['kind']}, ip {item['ip']}, {format_time(item['time'])}, {state}",
           f"found {item['found_at']} in {item['found_in']}"]
    if item.get("where"):
        out += ["Where:"] + ["  " + place for place in item["where"]]
    for label, key in (("taken", "taken_at"), ("closed", "closed_at"), ("dropped", "dropped_at")):
        if item[key]:
            out.append(f"{label} {item[key]}")
    if item["test"]:
        out.append(f"test {item['test']}")
    if item.get("fixed_by"):
        out.append(f"fixed by {item['fixed_by']}")
    if item.get("evidence"):
        out.append(f"evidence {item['evidence']}")
    for title, key in (("What", "what"), ("Why", "why"), ("Failing case" + (f" ({item['failing_kind']})" if item.get("failing_kind") else ""), "failing_case"), ("Pass cases", "pass_cases"), ("Dropped because", "dropped_why")):
        if item.get(key):
            mark = [n.at for n in notes_of(item) if n.edited == key]
            if mark:
                title += f" (edited {_local(mark[-1], tz).rsplit(' ', 1)[0]})"
            out += [f"{title}:"] + ["  " + line for line in item[key]]
        if key == "why":
            out += notes_text(item, tz)
    return "\n".join(out)


LIST_HEADER = ("ip", "kind", "time", "what", "name")
WHAT_WIDTH = 60   # the "what" column is cut to this many characters, the last one "…"


def _cut(text, width=WHAT_WIDTH):
    return text if len(text) <= width else text[:width - 1] + "…"


def list_lines(items, header=False):
    """One aligned line per item: ip, kind, time, what (the title), name (the slug); with `header`, a first line naming the columns."""
    rows = []
    for i in ordered(items):
        if i["problems"]:
            rows.append(("malformed", f"{i['slug']}  malformed: {'; '.join(i['problems'])}"))
            continue
        state = "" if i["state"] == "open" else f"  {i['state']} by {i['taken_by'] or '?'}"
        rows.append(("ok", (str(i["ip"]), i["kind"], format_time(i["time"]), _cut(i["title"]) + state, i["slug"])))
    good = [r[1] for r in rows if r[0] == "ok"]
    width = [max(len(r[c]) for r in good + [LIST_HEADER]) for c in range(4)] if good else []
    lines = []
    if header and good:
        lines.append(_row(LIST_HEADER, width))
    for kind, row in rows:
        lines.append(row if kind == "malformed" else _row(row, width))
    return lines


def _row(row, width):
    # ip and time are right-aligned so digits and units line up; the name is last and needs no padding
    return f" {row[0]:>{width[0]}}  {row[1]:<{width[1]}}  {row[2]:>{width[2]}}  {row[3]:<{width[3]}}  {row[4]}"


# ---------------------------------------------------------------- read-only extensions

def extensions():
    """Names of the views in relay's own `lib/queue_ext/`, sorted."""
    try:
        names = os.listdir(EXT_DIR)
    except OSError:
        return []
    return sorted(n[:-3] for n in names if n.endswith(".py") and EXT_NAME.fullmatch(n[:-3]))


def run_extension(name, items, args=()):
    """Run the view `lib/queue_ext/<name>.py`: `run(items, args) -> int`, on copies of the parsed items in queue order.

    Only relay's own folder is searched: a name with a path in it, or one not listed, is refused. An extension
    is given plain data and no write function; changing an item stays with add/take/release/done/drop/ip."""
    known = extensions()
    if not EXT_NAME.fullmatch(name) or name not in known:
        raise Refused(f"no queue view '{name}'; available: {', '.join(known) or 'none'}")
    spec = importlib.util.spec_from_file_location("queue_ext_" + name, os.path.join(EXT_DIR, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.run(copy.deepcopy(ordered(items)), list(args)))


# ---------------------------------------------------------------- reading git

def _git(repo, *args, env=None, data=None, timeout=20):
    """(exit code, stdout bytes, stderr text); (127, b"", reason) when git cannot run."""
    try:
        done = subprocess.run(["git", "-C", repo, *args], input=data, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, b"", str(exc)
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace").strip()


def _text(out):
    return out.decode("utf-8", "replace").strip()


def cat_batch(main, specs):
    """The contents (bytes) of each `rev:path` spec through one `git cat-file --batch`; None for a missing one."""
    if not specs:
        return []
    rc, out, err = _git(main, "cat-file", "--batch", data=("\n".join(specs) + "\n").encode())
    if rc != 0:
        raise Refused(f"git cat-file failed: {err}")
    result, pos = [], 0
    for _ in specs:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode("utf-8", "replace")
        pos = end + 1
        if header.endswith(" missing") or header.endswith(" ambiguous"):
            result.append(None)
            continue
        size = int(header.split()[2])
        result.append(out[pos:pos + size])
        pos += size + 1
    return result


class Reader:
    """The queue as it is at one commit `rev` of the repository whose main checkout is `main`."""

    def __init__(self, main, rev):
        self.main, self.rev, self._items = main, rev, None

    def names(self, sub=""):
        rc, out, _ = _git(self.main, "ls-tree", "--name-only", self.rev, f"{QDIR}/{sub}")
        names = [] if rc != 0 else _text(out).split("\n")
        return sorted(os.path.basename(n)[:-5] for n in names if n.endswith(".json") and os.path.dirname(n) == (QDIR + "/" + sub).rstrip("/"))

    def has_folder(self):
        rc, out, _ = _git(self.main, "ls-tree", "-d", "--name-only", self.rev, QDIR)
        return rc == 0 and _text(out) == QDIR

    def items(self):
        """Every item of the folder, parsed, by slug: open, taken, done and dropped (the state is in the item)."""
        if self._items is None:
            slugs = self.names()
            blobs = cat_batch(self.main, [f"{self.rev}:{QDIR}/{s}.json" for s in slugs])
            self._items = {s: parse(s, b.decode("utf-8", "replace")) for s, b in zip(slugs, blobs) if b is not None}
        return self._items

    def used_slugs(self):
        """The names of every item file, closed and dropped ones too (a slug is never reused)."""
        return set(self.names())

    def blob(self, path):
        rc, out, _ = _git(self.main, "rev-parse", "--verify", "-q", f"{self.rev}:{path}")
        return _text(out) if rc == 0 else None


def _context(repo):
    """(main checkout, default branch) of `repo`, or Refused when this project has no queue to write."""
    repo = os.path.realpath(repo)
    main = relay_git.main_checkout(repo)
    if main is None:
        raise Refused("not a git repository")
    default = relay_git.default_branch(repo)
    if default is None:
        raise Refused("cannot tell the default branch: set project.default_branch in .claude/kit.toml")
    return main, default


def _context_with_relay(repo):
    main, default = _context(repo)
    if not relay_git.has_relay(repo):
        raise Refused(f"{default} has no .relay/ folder: the work queue is off in this project")
    return main, default


def _head(main, default):
    rc, out, err = _git(main, "rev-parse", "--verify", "-q", f"refs/heads/{default}")
    if rc != 0:
        raise Refused(f"no local branch {default}")
    return _text(out)


def read_queue(repo, closed=False):
    """The open and taken items (parsed) of the default branch, read from git; [] when there is no queue folder.
    With `closed`, the done and dropped ones too. An item that does not parse has no state and is always listed."""
    main, default = _context(repo)
    rc, out, _ = _git(main, "rev-parse", "--verify", "-q", f"refs/heads/{default}")
    if rc != 0:
        return []
    reader = Reader(main, _text(out))
    if not reader.has_folder():
        return []
    return [i for i in reader.items().values() if closed or i.get("state") in (None, "open", "taken")]


def check_files(root):
    """(path, reasons) for each item file under `root`/.relay/queue that is not well formed, sorted by path; a file left in the
    gone done/ folder is reported too. Reads the checkout's files, so a branch is checked before its merge. Raises Refused when
    there is no queue folder."""
    problems = []
    base = os.path.join(root, QDIR)
    if not os.path.isdir(base):
        raise Refused(f"no {QDIR} folder under {root}")
    for name in sorted(os.listdir(base)):
        if name.endswith(".json") and os.path.isfile(os.path.join(base, name)):
            with open(os.path.join(base, name), encoding="utf-8") as handle:
                item = parse(name[:-5], handle.read())
            if item["problems"]:
                problems.append((f"{QDIR}/{name}", item["problems"]))
    stray = os.path.join(base, "done")
    for name in sorted(os.listdir(stray)) if os.path.isdir(stray) else []:
        if name.endswith(".json"):
            problems.append((f"{QDIR}/done/{name}", [STRAY_DONE]))
    return problems


def session_line(cwd):
    """The line for a session's start, or "" when the project has no queue or no open item (never raises)."""
    try:
        items = read_queue(cwd)
        if not any(not i["problems"] and i["state"] == "open" for i in items):
            return ""
        return f"Queue: {count_text(items)}. relay queue lists them."
    except Exception:
        return ""


def leftover_branches(repo):
    """Names `wt/queue-*` of the branches a landing left behind (for `relay doctor`)."""
    main, _ = _context(repo)
    rc, out, _ = _git(main, "for-each-ref", "--format=%(refname:short)", "refs/heads/wt/queue-*")
    return sorted(_text(out).split("\n")) if rc == 0 and _text(out) else []


# ---------------------------------------------------------------- landing

class Plan:
    """What one command writes at one head: `writes` maps a path to its new text (None: delete the path)."""

    def __init__(self, slug, writes, label, verb):
        self.slug, self.writes, self.label, self.verb = slug, writes, label, verb
        self.allowed = set(writes)


def _commit(main, head, plan):
    """A commit on `head` with the plan's writes, touching no checkout. Returns its sha."""
    tmp = tempfile.mkdtemp(prefix="relay-queue-")
    try:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        rc, _, err = _git(main, "read-tree", head, env=env)
        if rc != 0:
            raise Refused(f"git read-tree failed: {err}")
        for path, text in sorted(plan.writes.items()):
            if text is None:
                rc, _, err = _git(main, "update-index", "--force-remove", "--", path, env=env)
            else:
                rc, out, err = _git(main, "hash-object", "-w", "--stdin", data=text.encode(), env=env)
                if rc == 0:
                    rc, _, err = _git(main, "update-index", "--add", "--cacheinfo", f"100644,{_text(out)},{path}", env=env)
            if rc != 0:
                raise Refused(f"git update-index failed for {path}: {err}")
        rc, out, err = _git(main, "write-tree", env=env)
        if rc != 0:
            raise Refused(f"git write-tree failed: {err}")
        rc, out, err = _git(main, "commit-tree", _text(out), "-p", head, "-m", f"queue: {plan.slug}", env=env)
        if rc != 0:
            raise Refused(f"git commit-tree failed: {err}")
        return _text(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Run in a child: the default branch's own copy of lib/ reads each record the lander is about to write.
_CHILD = ("import json, sys; sys.path.insert(0, sys.argv[1]); import relay_queue as q\n"
          "print(json.dumps({s: q.parse(s, t)['problems'] for s, t in json.loads(sys.stdin.read()).items()}))")
OWN_CODE = "lib/relay_queue.py"


def _default_rejects(main: str, head: str, default: str, plan: Plan) -> list[str]:
    """What the default branch's own code (its lib/ at `head`) finds wrong with the records `plan` writes; [] when it accepts them or
    the branch has no such code (a project that only uses relay). Raises Refused when that code cannot be run."""
    records = {os.path.basename(p)[:-5]: t for p, t in plan.writes.items()
               if t is not None and p.endswith(".json") and os.path.dirname(p) == QDIR}   # only queue records go to the queue parser
    if not records or cat_batch(main, [f"{head}:{OWN_CODE}"]) == [None]:
        return []
    rc, tar, err = _git(main, "archive", "--format=tar", head, "lib", timeout=60)
    if rc != 0:
        raise Refused(f"cannot read {default}'s code to check the record: {err}")
    tmp = tempfile.mkdtemp(prefix="relay-queue-lib-")
    try:
        with tarfile.open(fileobj=io.BytesIO(tar)) as bundle:
            bundle.extractall(tmp, filter="data") if hasattr(tarfile, "data_filter") else bundle.extractall(tmp)
        try:
            done = subprocess.run([sys.executable, "-I", "-c", _CHILD, os.path.join(tmp, "lib")], input=json.dumps(records),
                                  capture_output=True, text=True, timeout=60)
            found = json.loads(done.stdout) if done.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise Refused(f"cannot run {default}'s queue code to check the record: {exc}") from exc
        if found is None:
            raise Refused(f"cannot run {default}'s queue code to check the record: {_last_line(done.stderr)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return [f"{slug}: {reason}" for slug, reasons in sorted(found.items()) for reason in reasons]


def _last_line(text):
    lines = [x for x in text.strip().split("\n") if x.strip()]
    return lines[-1].strip() if lines else "no message from git"


def _land(repo, planner, tries=None, sleep=time.sleep, after_plan=None, takeover=None, drop_kept=False):
    """Land the change `planner(Reader)` describes on the default branch (design 10.4, steps 1-6).

    Returns (plan, sha). `after_plan(try_index, plan)` runs between steps 2 and 3 (tests use it to
    place a second session exactly there). `takeover` is the tip of a kept branch `relay queue land` retries.
    Raises Refused for a refusal and when the last try failed (the message says the branch is kept; with `drop_kept` the branch is
    deleted and the message names no `relay queue land`: a record that is not a queue item cannot be retried by it)."""
    tries = QUEUE_LAND_TRIES if tries is None else tries
    if not 1 <= tries <= MAX_TRIES:
        raise ValueError(f"tries must be 1-{MAX_TRIES}")
    main, default = _context_with_relay(repo)
    last, held, wait = "", False, False
    tip, branch = takeover, None
    for n in range(tries):
        if n and wait:
            sleep(WAITS[min(n - 1, len(WAITS) - 1)])
        wait = True
        head = _head(main, default)                                        # step 1
        if relay_git.current_branch(main) != default:
            raise Refused(f"the main checkout is not on {default}")
        plan = planner(Reader(main, head))                                 # step 2: a Refused ends the command
        if after_plan:
            after_plan(n, plan)
        rejected = _default_rejects(main, head, default, plan)             # step 2b: the default branch's code must accept the record
        if rejected:
            raise Refused(f"nothing landed: {default}'s own queue code rejects the record ({'; '.join(rejected)}). The code that adds this "
                          f"is not on {default} yet: merge the code first, or land this from the {default} checkout")
        new = _commit(main, head, plan)                                    # step 3
        branch = "wt/queue-" + plan.slug
        ref = "refs/heads/" + branch
        rc, _, err = _git(main, "update-ref", ref, new, tip or ZERO)
        if rc != 0:
            held, last = True, f"{branch} exists (relay queue land, or relay doctor)"
            wait = plan.verb != "queued"                                    # an add goes straight to the next suffix
            continue
        held = False
        rc, out, err = _git(main, "diff", "--name-only", "--no-renames", f"{head}..{ref}")   # step 4
        touched = set(_text(out).split("\n")) - {""}
        if rc != 0 or touched != plan.allowed:
            _git(main, "update-ref", "-d", ref, new)
            raise Refused(f"{branch} changes {sorted(touched ^ plan.allowed)} beyond the one allowed file; refused, branch deleted")
        rc, out, err = _git(main, "merge", "--ff-only", ref)                # step 5
        if rc == 0:
            _git(main, "branch", "-d", branch)
            return plan, new
        last = _last_line(err or _text(out))
        tip = new if takeover else None
        if not takeover and (n < tries - 1 or drop_kept):
            _git(main, "update-ref", "-d", ref, new)
    if held:
        raise Refused(last)
    if drop_kept:
        raise Refused(f"not landed after {tries} tries: {last}")
    raise Refused(f"not landed after {tries} tries: {last}; kept on {branch}; relay queue land {plan.slug} tries again")


class NothingToWrite(Refused):
    """The planner of `land_files` had no file to write at the head it looked at."""


def land_files(repo, slug, writes_at, label):
    """Land the files `writes_at(head)` returns (a path to its text) on the default branch with the queue's own committer, which
    re-plans at the new head on every try and touches no checkout. The branch is `wt/queue-<slug>`. Returns the commit sha, or
    None when there is nothing to write. Raises Refused when it could not land."""
    def planner(reader):
        writes = writes_at(reader.rev)
        if not writes:
            raise NothingToWrite("nothing to write")
        return Plan(slug, writes, label, "recorded")
    try:
        return _land(repo, planner, drop_kept=True)[1]
    except NothingToWrite:
        return None


def _result(plan, default_sha, default):
    return f"{plan.verb} {plan.slug} ({plan.label}), landed on {default} at {default_sha}"


def _run(repo, planner, **kwargs):
    plan, sha = _land(repo, planner, **kwargs)
    return _result(plan, sha, _context(repo)[1])


def _item_at(reader, slug):
    item = reader.items().get(slug)
    if item is None:
        raise Refused(f"no queue item '{slug}'")
    if item["problems"]:
        raise Refused(f"queue item '{slug}' is malformed ({'; '.join(item['problems'])})")
    if item["state"] in ("done", "dropped"):
        raise Refused(f"queue item '{slug}' is {item['state']} ({'closed' if item['state'] == 'done' else 'dropped'} {(item.get('closed_at') or item.get('dropped_at'))[:10]}); a finished item is not changed")
    return item


def _path(slug):
    return f"{QDIR}/{slug}.json"


def _taken_by_refusal(item):
    return Refused(f"queue item '{item['slug']}' is taken by {item['taken_by']}; release it first")


# ---------------------------------------------------------------- commands

def find_finding(report, fid):
    """The finding `fid` from the JSON a judge recorded at `report` (written by `relay check record`): a review's findings,
    or the check record's. Refused, naming the file, when it is missing or invalid."""
    try:
        with open(report, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        raise Refused(f"no recorded findings at {report}: it is the JSON file `relay check record` wrote")
    try:
        kind, data = relay_verdict.load_any(text, f"the recorded data {report}")
    except relay_verdict.VerdictError as exc:
        raise Refused(str(exc))
    found = data["findings"]       # a review's findings, or the check record's one list (Q, F, M and N alike)
    for finding in found:
        if finding["id"] == fid:
            return finding
    raise Refused(f"no finding {fid} in {report}")


ADD_KEYS = ("kind", "title", "why", "what", "failing_case", "failing_kind", "pass_cases", "time", "ip", "where", "said")
FROM_KEYS = ("why", "time", "ip")


def read_add_input(path, keys, required, done="queued"):
    """The values of a queue-add TOML input file as keyword arguments of `add`: text fields as strings (their lines
    joined), `time` in minutes. Refused, naming the key, for an unknown or missing key or a wrong kind of value."""
    try:
        raw = relay_verdict.read_input(path, done)
    except relay_verdict.VerdictError as exc:
        raise Refused(str(exc))
    problems = relay_verdict.table_errors(raw, "in the input", keys, required)
    if problems:
        raise Refused(f"nothing {done}: " + "; ".join(problems))
    out = {}
    for key, value in raw.items():
        if key == "where":
            if _is_lines(value):
                out["where"] = value
            else:
                problems.append("`where` must be a list of places, each a text starting with path, path:N or path:N-M")
        elif key in ("kind", "title", "failing_kind"):
            if not isinstance(value, str):
                problems.append(f"`{key}` must be a text")
            out[key] = value
        elif key == "ip":
            if not _is_int(value):
                problems.append("`ip` must be a whole number from 0")
            out["ip"] = value
        elif key == "time":
            try:
                out["minutes"] = value if _is_int(value) else parse_time(value)
            except (Refused, AttributeError):
                problems.append(f"`time` must be {TIME_FORMS}")
        else:
            errors = []
            lines = relay_verdict.as_lines(value, key, "in the input", errors)
            problems += errors
            out[{"failing_case": "failing", "pass_cases": "pass_cases"}.get(key, key)] = "\n".join(lines)
    if problems:
        raise Refused(f"nothing {done}: " + "; ".join(problems))
    return out


def add(repo, kind, title, why="", what="", failing="", pass_cases="", minutes=None, ip=None, where=(),
        context="relay queue add", now=None, failing_kind="", said="", **engine):
    """Queue a new item. The slug comes from the title, suffixed -2, -3, ... when taken. `said` is the owner's words, verbatim: they
    become a `said` note dated now, never part of the text (so `relay queue edit` can never reach them)."""
    if kind not in KINDS:
        raise Refused("kind is fix or feature")
    if not title.strip():
        raise Refused("an item needs a title")
    if "\n" in title.strip():
        raise Refused("the title is one line")
    if len(title.strip()) >= TITLE_MAX:
        raise Refused(f"the title is under {TITLE_MAX} characters (it is the \"what\" column); the longer story goes in `what`")
    if title.strip() == slugify(title):
        raise Refused("the title only repeats the name; say in a sentence what is wrong or wanted")
    if what.strip() == slugify(title):
        raise Refused("what only repeats the name; say in a sentence what is wrong or wanted")
    if kind == "fix" and not failing.strip():
        raise Refused("a fix item needs its failing case (`failing_case` in the input)")
    if kind == "fix" and failing_kind not in FAILING_KINDS:
        raise Refused("a fix item says what its failing case is (`failing_kind` in the input): test (a failing test), run (a recorded red run) or claim (someone's word, reproduced before the build)")
    if kind == "feature" and failing_kind:
        raise Refused("only a fix item has a failing_kind")
    if not why.strip():
        raise Refused("an item needs why it matters (`why` in the input)")
    if minutes is None or minutes < 0:
        raise Refused(f"an item needs its time (`time` in the input or --time), as {TIME_FORMS}")
    if ip is not None and ip < 0:
        raise Refused("ip is a whole number from 0")
    if where:
        bad = where_problems(where if isinstance(where, str) else list(where))
        bad = bad or where_folders(None if isinstance(where, str) else list(where), repo)
        if bad:
            raise Refused("; ".join(bad))
    refuse_session_paths("queued", what=what, why=why, failing_case=failing, pass_cases=pass_cases)
    base = slugify(title)
    found = now or utcnow()

    def planner(reader):
        used = reader.used_slugs()
        branches = set(leftover_branches(reader.main))
        n = 1
        while True:
            slug = base if n == 1 else f"{base[:48 - len(str(n)) - 1].rstrip('-')}-{n}"
            if slug not in used and "wt/queue-" + slug not in branches:
                break
            n += 1
        value = ip
        if value is None:
            value = 0                                  # a fix lists above every feature by kind, so it needs no lifted ip
        item = new_item(kind, value, minutes, found, context, title.strip(), what or title.strip(), why, failing, pass_cases, where, failing_kind)
        if said.strip():
            item["notes"] = [Note("said", found, lines_of(said))]
        return Plan(slug, {_path(slug): serialize(slug, item)}, f"{kind}, ip {value}", "queued")

    return _run(repo, planner, **engine)


def add_from(repo, report, fid, why="", minutes=None, ip=None, now=None, **engine):
    """Queue the finding `fid` recorded beside `report` as a fix item: its place and failing case are copied, its
    linter line (relay_verdict.linter) is the item's `what`."""
    found = find_finding(report, fid)
    context = f"finding {fid} of {os.path.basename(report)}"
    summary = found["summary"]
    title = summary[0].upper() + summary[1:]     # a summary is a sentence; the capital keeps `add` from taking it for the slug's words
    if len(title) >= TITLE_MAX:                   # a title is the "what" column: cut a long summary at a word (the linter line in `what` holds all of it)
        title = title[:TITLE_MAX - 2].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"
    try:
        return add(repo, "fix", title, why=why, what=relay_verdict.linter(found), failing="\n".join(found["failing_case"]),
                   pass_cases="\n".join(found.get("pass_cases") or []), minutes=minutes, ip=ip, where=[f"{found['path']}:{found['line']}"], context=context, now=now,
                   failing_kind="claim", **engine)     # a review's finding is its reviewer's claim
    except Refused as exc:
        if "names a session file" not in str(exc):
            raise
        raise Refused(f"{exc}. The text comes from the recorded review and cannot be edited here: queue the finding with "
                      "`relay queue add --input <file.toml>` and write its failing case and pass cases without the session file")


def set_ip(repo, slug, ip, **engine):
    if ip < 0:
        raise Refused("ip is a whole number from 0")

    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] == "taken":
            raise _taken_by_refusal(item)
        if item["state"] != "open":
            raise Refused(f"queue item '{slug}' is {item['state']}")
        if item["ip"] == ip:
            raise Refused(f"queue item '{slug}' already has ip {ip}; nothing changed")
        return Plan(slug, {_path(slug): serialize(slug, changed(item, ip=ip))}, f"{item['kind']}, ip {ip}", "ip set")

    return _run(repo, planner, **engine)


def drop(repo, slug, why, **engine):
    if not why.strip():
        raise Refused("drop needs the owner's words (`why` in the input)")

    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] == "taken":
            raise _taken_by_refusal(item)
        text = serialize(slug, changed(item, dropped_at=utcnow(), dropped_why=lines_of(why)))
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, ip {item['ip']}", "dropped")

    return _run(repo, planner, **engine)


def _branch_live(repo, branch):
    """True while refs/heads/<branch> exists and is not yet part of the default branch (its own `done` still has to find the item)."""
    main, default = _context(repo)
    ref = "refs/heads/" + branch
    if relay_git.git(main, "show-ref", "--verify", "--quiet", ref)[0] != 0:
        return False
    return relay_git.git(main, "merge-base", "--is-ancestor", ref, "refs/heads/" + default)[0] != 0


def _carries_code(main: str, sha: str) -> bool:
    """True when `sha` (judged against its first parent) changes a file that is not inert; a failed read counts as inert."""
    import relay_inert
    has_parent = _git(main, "rev-parse", "--verify", "-q", f"{sha}^1")[0] == 0
    rc, out, _ = _git(main, "diff-tree", "--no-commit-id", "--name-only", "-r", *((f"{sha}^1", sha) if has_parent else ("--root", sha)))
    return rc == 0 and any(not relay_inert.matches(n) for n in _text(out).split("\n") if n.strip())


def _commit_on_default(repo: str, ref: str, slug: str | None = None) -> str:
    """The full sha of `ref` in `repo` when it is a commit on that repo's default branch; Refused (naming why) otherwise.
    A commit that changes only inert files is accepted for `slug` when the range it closes does carry code: the commits on the
    default branch (first parent) since the item's file last changed. A fast-forward landing leaves no merge of the change, so the
    head of the default branch is often such a commit. Refused, it names the last commit before it that carries code."""
    main, default = _context(repo)
    rc, out, _ = _git(main, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    if rc != 0:
        raise Refused(f"--evidence {ref} is not a commit of {os.path.basename(main) or main}")
    sha = _text(out)
    if _git(main, "merge-base", "--is-ancestor", sha, "refs/heads/" + default)[0] != 0:
        raise Refused(f"{sha[:12]} is not on {default}: evidence is a change that is merged")
    if _carries_code(main, sha):
        return sha
    if slug:
        rc, out, _ = _git(main, "log", "-1", "--format=%H", sha, "--", _path(slug))
        base = _text(out) if rc == 0 else ""
        if base:      # no base: the item is absent from sha's history (sha predates it) or the read failed; no range to judge
            rc, out, _ = _git(main, "rev-list", "--first-parent", f"{base}..{sha}")
            if rc == 0 and any(_carries_code(main, c) for c in _text(out).split()):
                return sha
    rc, out, _ = _git(main, "rev-list", "--first-parent", sha)
    last = next((c for c in _text(out).split() if _carries_code(main, c)), "") if rc == 0 else ""
    hint = f": name {last[:12]}, the last commit before it that carries code" if last else ""
    since = ", and no commit since the item was last changed carries code" if slug else ""
    raise Refused(f"{sha[:12]} changes only inert files (queue, checks, handover){since}{hint}")


def _checked_evidence(repo: str, evidence: str, slug: str | None = None) -> str:
    """`evidence` as it is stored: the full sha of a commit on the default branch (`<repo folder>:<sha>` for a commit of another
    repo, checked there), or a repo-relative file that exists at the tip of the default branch (a report). Anything else is refused."""
    other, colon, ref = evidence.partition(":")
    if colon and os.path.isdir(os.path.expanduser(other)):
        if not other.startswith(("~", "/")):
            raise Refused(f"--evidence {evidence}: write the other repository's folder as ~/<folder> or an absolute path, "
                          "so the stored text names it wherever it is read")
        folder = os.path.realpath(os.path.expanduser(other))
        try:
            return f"{other}:{_commit_on_default(folder, ref.strip())}"
        except Refused as exc:
            if "not a git repository" not in str(exc):
                raise
            raise Refused(f"--evidence {evidence}: {other} is not a git repository") from exc
    main, default = _context(repo)
    if _git(main, "rev-parse", "--verify", "-q", f"{evidence}^{{commit}}")[0] == 0:
        return _commit_on_default(repo, evidence, slug)
    if not os.path.isabs(evidence):
        import relay_inert
        rc, kind, _ = _git(main, "cat-file", "-t", f"refs/heads/{default}:{evidence}")
        if rc == 0 and _text(kind) == "blob" and not relay_inert.matches(evidence):
            return evidence
    raise Refused(f"--evidence {evidence} is not a commit of this repository, nor a file on {default}; "
                  "for a commit of another repository write <repo folder>:<sha>")


def close_with_evidence(repo, slug, evidence, **engine):
    """Close a feature that was finished without a branch of this repo's own: `evidence` is a commit on the default branch (of this
    repo, or `<repo folder>:<sha>` of another), or a report file on it; one line, checked in git and stored as the full sha.
    A fix is closed with a test (`done`), never with this."""
    evidence = evidence.strip()
    if not evidence or "\n" in evidence:
        raise Refused("--evidence is one line: a sha on the default branch, <repo folder>:<sha>, or a report file")
    refuse_session_paths("closed", evidence=evidence)

    def planner(reader):
        item = _item_at(reader, slug)
        if item["kind"] == "fix":
            raise Refused(f"'{slug}' is a fix: close it with --test on the branch that took it, or with --fixed-by <commit> --test <file>::<Class>::<name> when a change already on the default branch fixed it")
        if item["state"] == "taken" and _branch_live(repo, item["taken_by"]):
            raise _taken_by_refusal(item)
        text = serialize(slug, changed(item, closed_at=utcnow(), evidence=_checked_evidence(repo, evidence, slug)))
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, ip {item['ip']}", "closed")

    return _run(repo, planner, **engine)


def _run_pytest(tree, node):
    """Exit code of pytest on the test `node` inside the folder `tree`; None when pytest cannot be run or takes too long."""
    exe = shutil.which("pytest") or os.path.expanduser("~/.local/bin/pytest")
    if not os.path.exists(exe):
        return None
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        return subprocess.run([exe, "-q", "-x", "-p", "no:cacheprovider", node], cwd=tree, env=env, capture_output=True,
                              timeout=TEST_RUN_SECONDS).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _test_at(repo, commit, test, source, run_test):
    """Exit code of the test at `commit`: that commit's tree with the test file as it is on the default branch (`source`)."""
    rc, out, err = _git(repo, "archive", "--format=tar", commit, timeout=120)
    if rc != 0:
        raise Refused(f"cannot read {commit[:12]}: {err}")
    path, _, node = test.strip().partition("::")
    tree = tempfile.mkdtemp(prefix="relay-queue-fixed-")
    try:
        with tarfile.open(fileobj=io.BytesIO(out)) as tar:
            tar.extractall(tree, filter="data")
        target = os.path.join(tree, path.strip())
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(source)
        return run_test(tree, f"{path.strip()}::{node.strip()}")
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def _with_class(test, source):
    """`<file>::<name>` where the file defines `name` only as a method of one class becomes `<file>::<Class>::<name>` (pytest finds a
    method only through its class); any other form is returned as typed."""
    path, _, rest = test.strip().partition("::")
    if "::" in rest or not path.endswith(".py"):
        return test.strip()
    name = rest.strip()
    try:
        tree = ast.parse(source.decode("utf-8", "replace"))
    except SyntaxError:
        return test.strip()
    defs = (ast.FunctionDef, ast.AsyncFunctionDef)
    if any(isinstance(n, defs) and n.name == name for n in tree.body):
        return test.strip()
    classes = [c.name for c in tree.body if isinstance(c, ast.ClassDef) and any(isinstance(n, defs) and n.name == name for n in c.body)]
    return f"{path.strip()}::{classes[0]}::{name}" if len(classes) == 1 else test.strip()


def close_fixed_by(repo, slug, commit, test, run_test=_run_pytest, **engine):
    """Close a fix that a change already on the default branch fixed, with no branch of its own. `commit` is that change's commit;
    `test` is a python test at the tip of the default branch. The close is refused unless the test fails at the parent of `commit`
    and passes at `commit` (the test file taken as it is on the default branch), so the commit is shown to have fixed it.
    An item taken by a branch that is merged or gone is closed here, keeping its take; one taken by a live branch is released
    first (`relay queue release`, which works from any checkout), then this is run again. A test that is a method of a class may be
    named `<file>::<name>`: the class is found in the test file on the default branch, and the full `<file>::<Class>::<name>` is run and kept."""
    main, default = _context(repo)
    tip = "refs/heads/" + default
    rc, out, _ = _git(main, "rev-parse", "--verify", "-q", f"{commit.strip()}^{{commit}}")
    if rc != 0:
        raise Refused(f"--fixed-by {commit.strip()} is not a commit of this repository")
    sha = _text(out)
    if _git(main, "merge-base", "--is-ancestor", sha, tip)[0] != 0:
        raise Refused(f"{sha[:12]} is not on {default}: a change fixes an item for the queue only when it is merged")
    rc, out, _ = _git(main, "rev-parse", "--verify", "-q", f"{sha}^")
    if rc != 0:
        raise Refused(f"{sha[:12]} has no parent to show the test failing at")
    parent = _text(out)
    path = test.strip().partition("::")[0].strip()
    if not path.endswith(".py"):
        raise Refused(f"--fixed-by runs a python test: {TEST_FORMS}")
    reason = test_refusal(main, tip, test)
    if reason:
        raise Refused(reason.replace("in the last commit of the branch", f"on {default}"))
    source = _git(main, "cat-file", "blob", f"{tip}:{path}")[1]
    test = _with_class(test, source)
    before = _test_at(main, parent, test, source, run_test)
    if before is None or before not in (0, 1):
        raise Refused(f"cannot tell whether {test} fails at {parent[:12]}, the parent of {sha[:12]}: it did not run to a pass or a fail")
    if before == 0:
        raise Refused(f"{test} passes at {parent[:12]}, the parent of {sha[:12]}: that commit did not fix it")
    after = _test_at(main, sha, test, source, run_test)
    if after != 0:
        raise Refused(f"{test} does not pass at {sha[:12]}: that commit did not fix it")

    def planner(reader):
        item = _item_at(reader, slug)
        if item["kind"] != "fix":
            raise Refused(f"'{slug}' is a feature: close it with --evidence <sha on the default branch> | ~/<repo folder>:<sha> | <report file>")
        if item["state"] == "taken" and _branch_live(repo, item["taken_by"]):
            raise Refused(f"queue item '{slug}' is taken by {item['taken_by']}, which is not merged: "
                          f"relay queue release {slug}, then run this again")
        text = serialize(slug, changed(item, closed_at=utcnow(), test=test.strip(), fixed_by=sha))
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, ip {item['ip']}", "closed")

    return _run(repo, planner, **engine)


def release(repo, slug, **engine):
    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] != "taken":
            raise Refused(f"queue item '{slug}' is not taken")
        text = serialize(slug, changed(item, taken_at=None, taken_by=None))
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, ip {item['ip']}", "released")

    return _run(repo, planner, **engine)


def _q1(item):
    """The finding Q1 a fix item becomes: its place, title, failing case, why and pass cases."""
    places = item.get("where") or [f"{_path(item['slug'])}:1"]
    first = parse_place(places[0])          # the check has refused an element that does not parse
    return {"id": "Q1", "path": first.path, "line": first.line or 1, "severity": "HIGH", "rank": "high", "kind": "inside", "summary": item["title"],
            "failing_case": list(item["failing_case"]), "details": list(item["why"]) + [f"Also: {place}" for place in places[1:]],
            "pass_cases": list(item.get("pass_cases") or []), "evidence": [], "fix_hint": []}


def _closed_at(blob: bytes | None) -> bool:
    """True when the item file text `blob` (None: no such file) is a JSON object whose closed_at is set."""
    if blob is None:
        return False
    try:
        data = json.loads(blob.decode("utf-8", "replace"))
    except ValueError:
        return False
    return isinstance(data, dict) and bool(data.get("closed_at"))


def closed_on(main: str, base: str, tip: str, slug: str) -> bool:
    """True when the branch whose fork point is `base` and whose tip is `tip` closed the item `slug`: closed_at is empty (or the file
    is absent) at `base` and set at `tip`. The one rule of the merge hook, the train's closer search and `held_fix_items`: a close
    edits the item file in place, so no file is added when an item is closed."""
    after, before, before_old = cat_batch(main, [f"{tip}:{_path(slug)}", f"{base}:{_path(slug)}", f"{base}:{QDIR}/done/{slug}.json"])
    return _closed_at(after) and not _closed_at(before) and not _closed_at(before_old)     # done/ at the base: the move out of it closes nothing


def merge_base(main: str, left: str, right: str) -> str:
    """The merge base of two revisions; Refused when git cannot tell."""
    rc, out = relay_git.git(main, "merge-base", left, right)
    if rc != 0 or not out.strip():
        raise Refused(f"cannot find the merge base of {left} and {right}")
    return out.strip()


def closing_tip(main: str, default: str, absorbed: dict, slug: str) -> str | None:
    """The tip of the innermost absorbed branch (fewest commits) whose range from the default branch closes `slug` (`closed_on`), or
    None: the ref where a rider's own check is judged, the way merging that rider alone would."""
    closers = []
    for name, tip in absorbed.items():
        if closed_on(main, merge_base(main, f"refs/heads/{default}", tip), tip, slug):
            rc, count = relay_git.git(main, "rev-list", "--count", tip)
            if rc != 0 or not count.strip().isdigit():
                raise Refused(f"cannot count the commits of {name} ({tip}): the branch tip is not readable")
            closers.append((int(count), name, tip))
    return min(closers)[2] if closers else None


def held_fix_items(worktree: str, riders: bool = False) -> dict:
    """{slug: item} of the fix items the branch of `worktree` holds: taken by it at HEAD, or closed on it (`closed_on` the default
    branch: an item already closed there, say by an older branch of the same name, is not this branch's).
    With `riders` (a train's check) an item closed on any branch this one merged is held too, whoever took it."""
    main, default = _context(worktree)
    branch = relay_git.current_branch(worktree)
    held = {}
    head = _text(_git(worktree, "rev-parse", "--verify", "HEAD")[1])        # a sha: closed_on reads it in the main checkout, where HEAD is another commit
    for slug, item in Reader(worktree, "HEAD").items().items():
        if item["problems"] or item["kind"] != "fix":
            continue
        if item["state"] == "taken" and item.get("taken_by") == branch:
            held[slug] = item
        elif item["state"] == "done" and (riders or item.get("taken_by") == branch) and closed_on(main, f"refs/heads/{default}", head, slug):
            held[slug] = item
    return held


def open_item_refusal(worktree: str, branch: str) -> str | None:
    """Why `relay land` refuses: the branch of `worktree` still holds a taken fix item, or its queue cannot be read; else None."""
    try:
        held = held_fix_items(worktree)
        open_slugs = {s for s, i in held.items() if i["state"] == "taken"}
        main, default = _context(worktree)       # a take on the default branch that the branch head has not merged yet is open too
        here = Reader(worktree, "HEAD").items()
        for slug, item in Reader(main, f"refs/heads/{default}").items().items():
            if (not item["problems"] and item["kind"] == "fix" and item["state"] == "taken" and item.get("taken_by") == branch
                    and here.get(slug, {}).get("state") != "done"):
                open_slugs.add(slug)
        taken = sorted(open_slugs)
    except Refused as exc:
        return f"land: cannot read the queue of {branch}: {exc}"
    if not taken:
        return None
    return (f"land: {branch} still holds the open fix item '{taken[0]}': close it first, "
            f"relay queue done {taken[0]} -C {worktree} --test <file>::<name>; then relay land {branch} again")


def _unvouched_rider_item(worktree: str, slug: str) -> bool:
    """True when a rider-closed item still needs a check on this branch: judged the way the merge hook does (`step_queue`), at the
    innermost absorbed branch whose range closes it (`closing_tip`), else at this branch. An item vouched for at its rider needs none."""
    import relay_inert
    main, default = _context(worktree)
    closer = closing_tip(main, default, relay_inert.absorbed(worktree, "HEAD"), slug) or "HEAD"
    return check_refusal(worktree, closer, slug) is not None


def record_item(worktree: str, named: str | None = None) -> tuple | None:
    """(slug, finding Q1) for the fix item the branch of `worktree` holds, or None. Q1 is the item's problem, stated against the
    commit that landed `taken` (its `since`). Refused when the branch holds more than one fix item. A train holds the items its
    riders closed: `named` is the slug of the one this check is of (needed when there are several, refused when not held)."""
    held = held_fix_items(worktree, riders=True)
    if named is None:
        mine = held_fix_items(worktree)
        held = {s: i for s, i in held.items() if s in mine or _unvouched_rider_item(worktree, s)}
    if named is not None and named not in held:
        raise Refused(f"this branch does not hold the fix item '{named}'" + (f" (it holds {', '.join(sorted(held))})" if held else ""))
    if named is None:
        if not held:
            return None
        if len(held) > 1:
            raise Refused(f"this branch holds {len(held)} fix items ({', '.join(sorted(held))}); name the one to check (`item` in the input, `--item` in `relay check findings`)")
        named = next(iter(held))
    slug, item = named, held[named]
    rc, out, err = _git(worktree, "log", "--format=%H", "--diff-filter=AM", "HEAD", "--", _path(slug))
    if rc != 0:
        raise Refused(f"cannot find the commit that took '{slug}' in the history of this branch")
    since = ""
    for commit in _text(out).split():       # newest first: the close edits the file in place, so the take is the newest commit that left it unclosed
        rc, blob, _ = _git(worktree, "cat-file", "blob", f"{commit}:{_path(slug)}")
        if rc == 0 and not _closed_at(blob):
            since = commit
            break
    if not relay_verdict.is_sha(since):
        raise Refused(f"cannot find the commit that took '{slug}' in the history of this branch")
    return slug, dict(_q1(item), source="queue", since=since)


def take(worktree, slug, **engine):
    """Land `taken` on the default branch and bring it into the worktree's branch. A fix item is refused on a branch that
    already holds one (open or closed on it). Q1, the item's problem, is written by the check (`record_item`), not here."""
    main, default = _context_with_relay(worktree)
    branch = relay_git.current_branch(worktree)
    if branch is None or branch == default:
        raise Refused("take from the worktree of a task branch")

    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] == "taken":
            raise Refused(f"queue item '{slug}' is taken by {item['taken_by']}")
        if item["state"] != "open":
            raise Refused(f"queue item '{slug}' is {item['state']}")
        if item["kind"] == "fix":                   # the finding Q1 must be writable before `taken` lands: no item left taken that cannot be checked
            errors = relay_verdict.finding_errors(_q1(item), "finding Q1 of the item")
            if errors:
                raise Refused(f"queue item '{slug}' cannot become finding Q1, nothing taken: {'; '.join(errors[:3])}")
            held = held_fix_items(worktree)
            if held:
                name, other = next(iter(sorted(held.items())))
                raise Refused(f"{branch} already holds the fix item '{name}' ({'closed' if other['state'] == 'done' else 'open'} on it); a branch holds one fix item: take '{slug}' from another worktree")
        text = serialize(slug, changed(item, taken_at=utcnow(), taken_by=branch))
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, ip {item['ip']}", "taken")

    plan, sha = _land(worktree, planner, **engine)
    out = [_result(plan, sha, default)]
    rc, merged, err = _git(worktree, "merge", "--no-edit", default)
    if rc != 0:
        raise Refused(f"{out[0]}; but merging {default} into {branch} failed: {_last_line(err or _text(merged))}")
    return "\n".join(out)


def holds_test(test, source):
    """Whether `source`, the text of the test file named in `test` (`<file>::<name>` or `<file>::<Class>::<name>`), defines the test.
    The one rule of `relay queue done` and of the merge guard. `source` is None when the file is not there."""
    path, _, rest = test.strip().partition("::")
    parts = [p.strip() for p in rest.split("::")]
    name = parts[-1]
    if not path.strip() or not name or source is None:
        return False
    if path.strip().endswith(".py") and len(parts) > 1:
        # pytest collects file::Class::name only when the class is defined in the file
        if not all(re.search(r"\bclass\s+" + re.escape(c) + r"\b", source) for c in parts[:-1]):
            return False
    return _holds_test(path.strip(), name, source)


def _holds_test(path, name, source):
    """Whether the test file's text defines the test `name` as a whole word (a python file: `def name`); test_xy is not test_x."""
    pattern = r"\bdef\s+" + re.escape(name) + r"\b" if path.endswith(".py") else r"(?<![\w])" + re.escape(name) + r"(?![\w])"
    return re.search(pattern, source) is not None


TEST_FORMS = "--test is <test file>::<test name>, or evals/plugin/<case>::<grader> (or evals/judge-measure/<case>::<grader>) for an eval case"


def test_refusal(repo, ref, test):
    """None when the test named by `test` (`<file>::<name>` or `<file>::<Class>::<name>`) is in the tree at `ref` of `repo` and
    defined there (`holds_test`), else the refusal line. An eval case form `evals/plugin/<case>::<grader>` (or `evals/judge-measure/...`)
    is proved by the grader file `graders/<grader>.md` at `ref`."""
    path, _, rest = test.strip().partition("::")
    name = rest.split("::")[-1].strip()
    if not path.strip() or not name:
        return TEST_FORMS
    case = re.fullmatch(r"(evals/(?:plugin|judge-measure)/[^/]+)/?", path.strip())
    if case:                                        # an eval case: the proof is the grader file, which need not name itself
        grader = f"{case.group(1)}/graders/{name}.md"
        rc, _, _ = _git(repo, "cat-file", "blob", f"{ref}:{grader}")
        if rc != 0:
            return f"the grader {grader} is not in the last commit of the branch ({TEST_FORMS})"
        return None
    rc, source, _ = _git(repo, "cat-file", "blob", f"{ref}:{path.strip()}")
    if rc != 0:
        return f"the test file {path.strip()} is not in the last commit of the branch ({TEST_FORMS})"
    if not holds_test(test, source.decode("utf-8", "replace")):
        return f"{path.strip()} does not hold a test named {name} ({TEST_FORMS})"
    return None


def close_refusal(repo, ref, slug, test):
    """None when the item `slug` may be closed with `test` at `ref` of `repo`, else the refusal line. The one rule of
    `relay queue done` (ref HEAD of the task worktree) and of the merge guard (ref the branch): what may change after the check.
    It is `test_refusal` and `check_refusal` at one ref; the merge guard of a train asks them at different refs.

    The test is `<file>::<name>` or `<file>::<Class>::<name>`: the file is in the tree at `ref` and defines the test (`holds_test`);
    or `evals/plugin/<case>::<grader>` (also `evals/judge-measure/<case>`): the grader file `graders/<grader>.md` is in the tree at `ref`.
    For a fix item, the newest check mark of the branch with no file of the branch's own changed since (the inert files do not
    count: `relay_inert`) must be of this item and its finding Q1 must be MET."""
    return test_refusal(repo, ref, test) or check_refusal(repo, ref, slug)


Q1_PARTS = ("summary", "failing_case", "details", "pass_cases")


def stale_check(repo: str, default: str, slug: str, q1: dict, commit: str) -> Optional[str]:
    """None when the problem the check judged (its recorded Q1) is the item's problem now (the item at the default branch's tip, where
    `relay queue edit` lands); else the refusal line. Queue files are inert, so without this an edit after a MET check would let the
    fix close against a problem the check never saw. An item not on the default branch has no edit to compare with."""
    rc, out, _ = _git(repo, "cat-file", "blob", f"refs/heads/{default}:{_path(slug)}")
    if rc != 0:
        return None
    now = parse(slug, out.decode("utf-8", "replace"))
    if now["problems"] or now.get("kind") != "fix":
        return None
    current = _q1(now)
    differs = [part for part in Q1_PARTS if q1.get(part) != current[part]]
    if differs:
        return (f"the problem of '{slug}' changed on {default} after the check of {commit[:12]} ({', '.join(differs)}): "
                f"take {default} into the branch and check the fix again")
    return None


def check_refusal(repo, ref, slug):
    """The check part of `close_refusal`: None when the item is not a fix, or the newest usable check at `ref` is of it with Q1 MET;
    else the refusal line."""
    import relay_inert
    import relay_marks
    kind = None
    rc, out, _ = _git(repo, "cat-file", "blob", f"{ref}:{_path(slug)}")
    if rc == 0:
        kind = parse(slug, out.decode("utf-8", "replace")).get("kind")
    if kind != "fix":
        return None
    default = relay_git.default_branch(repo)
    if default is None:
        return "cannot tell the default branch: set project.default_branch in .claude/kit.toml"
    stored = dict(relay_marks.marks(repo, ref))
    rc, out = relay_git.git(repo, "rev-list", "--topo-order", ref, f"^refs/heads/{default}")
    order = [c for c in out.splitlines() if c in stored] if rc == 0 else []
    if not order:
        return f"no check of this fix: run delegate:checker on the branch's head, then close '{slug}'"
    first, other = None, None
    for commit in order:
        try:
            own = relay_inert.own_since_mark(repo, commit, ref)
        except ValueError as exc:
            return str(exc)
        if own:
            first = first or (commit, own)
            continue
        try:
            record = relay_marks.check_data(repo, ref, stored[commit]["check"])
        except relay_marks.MarkError as exc:
            return str(exc)
        if record is None:
            return f"the mark of {commit[:12]} names {stored[commit]['check']}, which is not stored"
        if record["item"] != slug:       # a train carries several closed items: an older check with no own change since may be this one's
            other = other or f"the check of {commit[:12]} is of {record['item'] or 'no queue item'}, not of '{slug}'"
            continue
        verdict = next((f["verdict"] for f in record["findings"] if f["id"] == "Q1"), None)
        if verdict is None:
            return f"the check of {commit[:12]} gives no verdict for Q1"
        if verdict != "MET":
            return f"the check of {commit[:12]} says Q1 {verdict}, not MET"
        return stale_check(repo, default, slug, next(f for f in record["findings"] if f["id"] == "Q1"), commit)
    if other:
        return other
    commit, own = first
    return f"after the check of {commit[:12]}, {', '.join(own[:3])} changed, which is not inert: check the fix again"


def done(worktree, slug, test):
    """Close a taken item on the task branch: needs `close_refusal` to say it may be closed (the named test at HEAD and, for a
    fix, the branch's check with Q1 MET)."""
    branch = relay_git.current_branch(worktree)
    main, default = _context(worktree)
    if branch == default:
        held = Reader(worktree, "HEAD").items().get(slug)
        if held and held["state"] == "taken" and _branch_live(worktree, held["taken_by"]):
            raise Refused(f"queue item '{slug}' is taken by {held['taken_by']}, which is not merged: "
                          f"run relay queue done {slug} -C <its worktree> --test {test}")
        raise Refused(f"done runs in the worktree of the task branch that took the item; from the main checkout a fix taken by a branch "
                      f"that is merged or gone closes with relay queue done {slug} --fixed-by <commit> --test <file>.py::<Class>::<name>; "
                      f"one that was never fixed is released with relay queue release {slug}")
    if branch is None:
        raise Refused("done runs in the worktree of the task branch that took the item")
    path, _, name = test.partition("::")
    if not path or not name:
        raise Refused(TEST_FORMS)
    rc, out, _ = _git(worktree, "cat-file", "blob", f"HEAD:{_path(slug)}")
    if rc != 0:
        raise Refused(f"no queue item '{slug}' on this branch (take it first)")
    item = parse(slug, out.decode("utf-8", "replace"))
    if item["problems"]:
        raise Refused(f"queue item '{slug}' is malformed ({'; '.join(item['problems'])})")
    if item["state"] != "taken" or item["taken_by"] != branch:
        raise Refused(f"queue item '{slug}' is not taken by {branch}")
    reason = close_refusal(worktree, "HEAD", slug, test)
    if reason:
        raise Refused(reason)
    root = _text(_git(worktree, "rev-parse", "--show-toplevel")[1])
    text = serialize(slug, changed(item, closed_at=utcnow(), test=test))
    with open(os.path.join(root, _path(slug)), "w", encoding="utf-8") as handle:
        handle.write(text)
    paths = [_path(slug)]
    for args in (("add", "--", *paths), ("commit", "-m", f"queue: done {slug}", "--only", "--", *paths)):
        rc, _, err = _git(worktree, *args)
        if rc != 0:
            raise Refused(f"git {args[0]} failed: {err}")
    return f"closed {slug} on {branch} (test {test}); the merge of {branch} lands it"


def land(repo, slug, **engine):
    """Retry the landing of a kept `wt/queue-<slug>` at the new head; refused when its files changed meanwhile."""
    main, default = _context_with_relay(repo)
    branch = "wt/queue-" + slug
    rc, out, _ = _git(main, "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}")
    if rc != 0:
        raise Refused(f"no branch {branch} to land")
    tip = _text(out)
    parents = _text(_git(main, "rev-list", "--parents", "-n", "1", tip)[1]).split()[1:]
    if len(parents) != 1:
        raise Refused(f"{branch} is not a single queue commit")
    base = parents[0]
    rc, out, _ = _git(main, "diff", "--name-only", "--no-renames", f"{base}..{tip}")
    paths = sorted(set(_text(out).split("\n")) - {""})
    if paths != [_path(slug)]:
        raise Refused(f"{branch} changes more than the item '{slug}'; delete it (relay doctor)")
    texts = dict(zip(paths, cat_batch(main, [f"{tip}:{p}" for p in paths])))
    old = Reader(main, base)
    verb = "queued"

    def planner(reader):
        for p in paths:
            if texts[p] is not None:         # a kept change of the old shape (made before the migration) is refused, not landed
                bad = parse(slug, texts[p].decode("utf-8", "replace"))["problems"]
                if bad:
                    raise Refused(f"{p} on {branch} is not well formed ({'; '.join(bad)}); branch {branch} kept")
            if reader.blob(p) != old.blob(p):
                raise Refused(f"{p} changed on {default} since this change was made; it no longer holds (branch {branch} kept)")
        return Plan(slug, {p: (t.decode("utf-8", "replace") if t is not None else None) for p, t in texts.items()}, "kept change", verb)

    plan, sha = _land(repo, planner, takeover=tip, **engine)
    return _result(plan, sha, default)


# ---------------------------------------------------------------- session files in front-written text

# A temporary path, or the word "scratchpad" with a file name or a path in the same sentence. Session files are deleted on reboot, so
# an item that points at one points at nothing (design: owner-words 5.5). The owner's own words (`said`, `answer`) are never checked.
TEMP_PATH = re.compile(r"(?<![\w.~-])(?:/private)?/(?:tmp|var/folders)/\S*")
FILE_IN_SENTENCE = re.compile(r"[\w.-]+/[\w./-]+|[\w-]+\.(?:md|json|jsonl|py|toml|txt|sh|log|yaml|yml)\b")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def session_path_problem(field: str, lines: object, done: str = "queued") -> Optional[str]:
    """The refusal text when a line of `lines` (the front's own text for item field `field`) names a session file, else None."""
    if not _is_lines(lines):
        return None
    for number, line in enumerate(lines, 1):
        hit = TEMP_PATH.search(line)
        if hit is None:
            for sentence in SENTENCE_END.split(line):
                if "scratchpad" in sentence.lower() and FILE_IN_SENTENCE.search(sentence):
                    hit = FILE_IN_SENTENCE.search(sentence)
                    break
        if hit is not None:
            return (f"nothing {done}: line {number} of `{field}` names a session file (\"{hit.group(0)}\"); session files are deleted on reboot. "
                    "Put the fact itself in (the number, the date, the owner's words) or leave it out; a design is written fresh when the item is taken")
    return None


def refuse_session_paths(done: str, **fields: object) -> None:
    """Refused (the first problem) when any of the front-written `fields` (name -> text or lines) names a session file."""
    for name, value in fields.items():
        lines = lines_of(value) if isinstance(value, str) else value
        problem = session_path_problem(name, lines, done)
        if problem:
            raise Refused(problem)


# ---------------------------------------------------------------- notes: the command, the search, the view

def decision_errors(fields: dict) -> list:
    """Why the decision keys of a question input (`chosen`, `decided_by`, `because`) are wrong, [] when they are right or absent. The one
    rule of the `note` input and of `note`."""
    keys = ("chosen", "decided_by", "because")
    if not any(k in fields for k in keys):
        return []
    errors = [f"a decision you took needs `{k}` as well (chosen, decided_by and because go together)" for k in keys if k not in fields]
    if "decided_by" in fields and fields["decided_by"] not in DECIDERS:
        errors.append("decided_by is one of: " + ", ".join(DECIDERS) +
                      ("; a reviewer's decisions live in the check record, not in the queue" if fields["decided_by"] == "reviewer" else ""))
    if "chosen" in fields and not (isinstance(fields["chosen"], str) and len(fields["chosen"]) == 1 and fields["chosen"].isalpha()):
        errors.append("`chosen` is the letter of one option, like \"a\"")
    return errors


def read_note_input(path: str) -> dict:
    """The values of a `relay queue note` TOML input: lines for the text keys, `to` and `at` as they are. Refused, with the
    next step, for an unknown key, no kind, two kinds, or a key that does not go with the kind."""
    try:
        raw = relay_verdict.read_input(path, "noted")
    except relay_verdict.VerdictError as exc:
        raise Refused(str(exc))
    allowed = ("said", "fact", "question", "options", "answer", "to", "reading", "at", "chosen", "decided_by", "because")
    problems = relay_verdict.table_errors(raw, "in the input", allowed, ())
    if problems:
        raise Refused("nothing noted: " + "; ".join(problems))
    kinds = [k for k in ("said", "fact", "question", "answer") if k in raw]
    if len(kinds) != 1:
        raise Refused("nothing noted: the input has " + (f"both `{kinds[0]}` and `{kinds[1]}`" if kinds else "none of `said`, `fact`, `question`, `answer`") +
                      "; a note is one of said (the owner's words), fact (a measurement), question (with options) or answer")
    kind = kinds[0]
    extra = {"question": ("options", "chosen", "decided_by", "because"), "answer": ("to", "reading", "chosen")}
    for key in ("options", "to", "reading", "chosen", "decided_by", "because"):
        if key in raw and key not in extra.get(kind, ()):
            raise Refused(f"nothing noted: `{key}` does not go with `{kind}`" + ("; it belongs to a question" if key in extra["question"] else "; it belongs to an answer"))
    if kind == "question" and "options" not in raw:
        raise Refused("nothing noted: a question needs `options` (the lettered lines as you will show them)")
    out: dict = {"kind": kind}
    errors: list = []
    if kind == "question":
        errors += decision_errors(raw)
        out.update({k: raw[k] for k in ("chosen", "decided_by") if k in raw})
    elif kind == "answer" and "chosen" in raw:
        letters = [raw["chosen"]] if isinstance(raw["chosen"], str) else raw["chosen"]
        if not (isinstance(letters, list) and letters and all(isinstance(x, str) and len(x) == 1 and x.isalpha() and x.islower() for x in letters)):
            errors.append("`chosen` is a list of letters, one per question answered, like [\"a\"]")
        out["chosen"] = letters
    for key in ("said", "fact", "question", "options", "answer", "reading", "because"):
        if key in raw:
            out[key] = relay_verdict.as_lines(raw[key], key, "in the input", errors)
    if "to" in raw:
        if not (isinstance(raw["to"], list) and raw["to"] and all(_timestamp(x) for x in raw["to"])):
            errors.append("`to` must be a list of the asked times of the questions answered, like [\"2026-10-27T01:20:00Z\"]")
        out["to"] = raw["to"]
    if "at" in raw:
        stamp = raw["at"]
        if isinstance(stamp, dt.datetime) and stamp.tzinfo is not None and stamp.utcoffset() == dt.timedelta(0):
            raw["at"] = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")        # TOML reads an unquoted UTC time as a datetime: the same time
        if not _timestamp(raw["at"]):
            errors.append("`at` must be a UTC time like 2026-10-27T01:20:00Z")
        out["at"] = raw["at"]
    if "options" in out and option_problem(out["options"]):
        first = next((o for n, o in enumerate(out["options"]) if not o.startswith(f"{chr(97 + n)}. ")), "")
        errors.append("each `options` line starts with its letter, a dot and a space, in order, at least two (a. ..., b. ...)" +
                      (f"; yours: '{first}'" if first else ""))
    if errors:
        raise Refused("nothing noted: " + "; ".join(errors))
    return out


def question_title(note: Note) -> str:
    """The first line of a question as a short title: markup and a leading number (in questions asked before 28 Oct) dropped."""
    first = next((x for x in note.text if x.strip()), "")
    return re.sub(r"^\d+\.\s*", "", first.strip().strip("*").strip())


def question_block(note: Note) -> str:
    """The question as the owner sees it: the block, then the lettered options (what `note` prints back and `show` prints)."""
    return "\n".join(list(note.text) + list(note.options))


def owner_waiting(notes: list) -> list:
    """The questions the owner was asked and has not answered. A decision an agent took is not among them: nobody waits for the owner
    on it. Used by the reminder hook and by `relay lanes` (the startable list and `lanes start`)."""
    return [n for n in notes if n.kind == "decision" and n.answered_at is None and not n.decided_by]


def answerable(notes: list) -> list:
    """The questions an owner answer can still land on: unanswered, decided by an agent or not. Used by the answer path, so the owner
    can reverse a decision."""
    return [n for n in notes if n.kind == "decision" and n.answered_at is None]


def note(repo: str, slug: str, fields: dict, now: Optional[str] = None, **engine: object) -> str:
    """Append a note to item `slug` (any state), or fill the waiting question(s) with the owner's answer. `fields` is `read_note_input`'s
    result. Never edits an earlier note. Returns the landing line, and for a question the block to paste into the reply."""
    kind = fields["kind"]
    if kind == "question" and decision_errors(fields):
        raise Refused("nothing noted: " + "; ".join(decision_errors(fields)))
    refuse_session_paths("noted", **{k: fields[k] for k in ("fact", "question", "options", "reading", "because") if k in fields})
    stamp = now or utcnow()

    def planner(reader):
        item = reader.items().get(slug)
        if item is None:
            raise Refused(f"nothing noted: no queue item '{slug}'. A question or words about something no item covers: add the item first "
                          "(`relay queue add`), then note on it")
        if item["problems"]:
            raise Refused(f"nothing noted: queue item '{slug}' is malformed ({'; '.join(item['problems'])})")
        when = fields.get("at") or stamp
        if when > stamp:
            raise Refused(f"nothing noted: `at` {when} is in the future (now {stamp})")
        if when < item["found_at"]:
            raise Refused(f"nothing noted: `at` {when} is before the item was found ({item['found_at']})")
        notes = notes_of(item)
        if kind in ("said", "fact"):
            new = Note(kind, when, list(fields[kind]))
        elif kind == "question":
            if any(w.at == when for w in answerable(notes)):
                raise Refused(f"nothing noted: {slug} already has a question asked at {when} waiting for an answer, and an answer names its "
                              "question by that time; add `at` one second later")
            if "decided_by" in fields:
                asked = Note("decision", when, list(fields["question"]), 0, list(fields["options"]))
                if fields["chosen"] not in [chr(97 + n) for n in range(len(asked.options))]:
                    raise Refused(f"nothing noted: chosen '{fields['chosen']}' is not one of the options")
                same = next((w for w in owner_waiting(notes) if question_title(w) == question_title(asked)), None)
                if same:
                    raise Refused(f"nothing noted: the owner was already asked '{question_title(same)}' (asked {same.at}) and has not answered; "
                                  "an agent does not decide a question the owner was asked")
                new = asked._replace(decided_by=fields["decided_by"], chosen=fields["chosen"], because=list(fields["because"]))
            else:
                new = Note("decision", when, list(fields["question"]), 0, list(fields["options"]))
        else:
            waiting = answerable(notes)
            targets = fields.get("to")
            if not waiting:
                raise Refused(f"nothing noted: {slug} has no question waiting; record the question first, or keep these words as `said`")
            named = " and ".join(f"'{question_title(w)}' (" + ("decided " if w.decided_by else "asked ") + f"{w.at})" for w in waiting)
            if targets is None:
                if len(waiting) > 1 or waiting[0].decided_by:
                    raise Refused(f"nothing noted: {slug} " + ("can take this answer on" if any(w.decided_by for w in waiting) else "waits on questions") + f" {named}; add `to = [\"<asked time>\"]` naming the one(s) this answers")
                targets = [waiting[0].at]
            for target in targets:
                hit = next((w for w in waiting if w.at == target), None)
                if hit is None:
                    raise Refused(f"nothing noted: no question asked at {target} is waiting on {slug}; waiting: {named}")
                if when < hit.at:
                    raise Refused(f"nothing noted: `at` {when} is before the question '{question_title(hit)}' was asked ({hit.at})")
            letters = fields.get("chosen")
            if letters is not None:
                if len(letters) != len(targets):
                    raise Refused(f"nothing noted: `chosen` is one letter per question answered ({len(targets)}), in the order of `to`; got {len(letters)}")
                for target, letter in zip(targets, letters):
                    hit = next(w for w in waiting if w.at == target)
                    if letter not in [chr(97 + n) for n in range(len(hit.options))]:
                        raise Refused(f"nothing noted: chosen '{letter}' is not one of the options of '{question_title(hit)}'")
            letter_of = dict(zip(targets, letters or []))
            notes = [n._replace(answered_at=when, answer=list(fields["answer"]), reading=list(fields.get("reading") or []),
                                answer_choice=letter_of.get(n.at, ""))
                     if n in waiting and n.at in targets else n for n in notes]
            return Plan(slug, {_path(slug): serialize(slug, changed(item, notes=notes))}, "answer to " + ", ".join(f"'{question_title(n)}'" for n in notes if n.kind == "decision" and n.at in targets), "noted")
        position = len([n for n in notes if n.at <= when])
        notes.insert(position, new)
        return Plan(slug, {_path(slug): serialize(slug, changed(item, notes=notes))}, "question" if kind == "question" else kind, "noted")

    plan, sha = _land(repo, planner, **engine)
    text = _result(plan, sha, _context(repo)[1])
    if kind == "question" and "decided_by" in fields:
        text += f"\nDecided by {fields['decided_by']} at {fields.get('at') or stamp}: {fields['chosen']}; the owner reverses it by an answer with `to = [\"{fields.get('at') or stamp}\"]`. Nothing to show the owner as a question."
    elif kind == "question":
        text += f"\nAsked at {fields.get('at') or stamp}; an answer to it names that time in `to`.\nShow the owner exactly this:\n" + question_block(Note("decision", "", fields["question"], 0, fields["options"]))
    return text


# ---------------------------------------------------------------- edit: one exact fragment, quoted text untouched

EDIT_FIELDS = ("title", "what", "why", "failing_case", "failing_kind", "pass_cases", "where", "time", "test")
EDIT_KEYS = ("field", "old", "new", "because")
DOUBLE_QUOTES = {'"': '"', "«": "»", "“": "”"}
QUOTE_BEFORE_OPEN = " \n(:[{=,\"«“"      # a straight quote opens after one of these and before a non-space
QUOTE_AFTER_CLOSE = ".,;:!?)]\"»”'"  # and closes before a space, a line end or one of these
SINGLE_OPEN = " \n(:"          # a single quote opens a span after a line start, a space, "(" or ":" ("owner's" opens nothing)
SINGLE_CLOSE = " \n.,;:!?)"    # and closes before a line end or one of these ("repository not found'.")


def _straight_span_end(text: str, start: int) -> int:
    """The index of the " that closes the straight-quoted span opened at `start`, or -1. Straight quotes nest: a " after a line start,
    space, "(", ":" or another opening mark and before a non-space opens (depth + 1); one before a line end, space, punctuation or a
    closing mark closes (depth - 1); the span ends where depth returns to 0. A mark that fits neither role, or a span still open
    at the end, gives -1 (the field is not edited)."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] != '"':
            continue
        before = text[i - 1] if i else "\n"
        after = text[i + 1] if i + 1 < len(text) else "\n"
        if before in QUOTE_BEFORE_OPEN and not after.isspace():
            depth += 1
        elif depth and (after.isspace() or after in QUOTE_AFTER_CLOSE):
            depth -= 1
            if depth == 0:
                return i
        else:
            return -1
    return -1


def quoted_spans(lines: list) -> Optional[list]:
    """The protected spans of a field's lines (joined with a line break, so a quote over two lines is one span): "...", «...», “...”
    and '...' (opened after a line start, space, "(" or ":"; closed before a line end, space or punctuation). Each is returned with its
    quote marks. None when a double quote has no closing mark: such a field is not edited. A lone single quote is an apostrophe."""
    text = "\n".join(lines)
    spans, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            end = _straight_span_end(text, i)
            if end < 0:
                return None
            spans.append(text[i:end + 1])
            i = end + 1
            continue
        if ch in DOUBLE_QUOTES:
            end = text.find(DOUBLE_QUOTES[ch], i + 1)
            if end < 0:
                return None
            spans.append(text[i:end + 1])
            i = end + 1
            continue
        if ch == "'" and (i == 0 or text[i - 1] in SINGLE_OPEN):
            end = i + 1
            while True:
                end = text.find("'", end)
                if end < 0 or end + 1 == len(text) or text[end + 1] in SINGLE_CLOSE:
                    break
                end += 1
            if end >= 0 and end > i + 1:
                spans.append(text[i:end + 1])
                i = end + 1
                continue
        i += 1
    return spans


def read_edit_input(path: str) -> dict:
    """The values of a `relay queue edit` TOML input: field, old, new, because (texts, kept exactly as written). Refused for an unknown
    or missing key, a field that cannot be edited, or an empty `old` or `because`."""
    try:
        raw = relay_verdict.read_input(path, "edited")
    except relay_verdict.VerdictError as exc:
        raise Refused(str(exc))
    problems = relay_verdict.table_errors(raw, "in the input", EDIT_KEYS, EDIT_KEYS)
    problems += [f"`{k}` must be a text" for k in EDIT_KEYS if k in raw and not isinstance(raw[k], str)]
    if problems:
        raise Refused("nothing edited: " + "; ".join(problems))
    if raw["field"] == "notes":
        raise Refused("nothing edited: notes are only added (`relay queue note`), never edited; a wrong claim in a note is corrected by a later fact note")
    if raw["field"] not in EDIT_FIELDS:
        raise Refused(f"nothing edited: `field` is one of {', '.join(EDIT_FIELDS)}")
    if not raw["old"] or not raw["because"].strip():
        raise Refused("nothing edited: `old` (the exact text to replace) and `because` (what was found, and when) are not empty")
    return {key: raw[key] for key in EDIT_KEYS}


def _edited_value(item: dict, field: str, old: str, new: str, repo: str, default: str) -> object:
    """The field's new stored value after replacing the one occurrence of `old` by `new`; Refused with the reason otherwise."""
    slug = item["slug"]
    if field == "time":
        if old.strip() != format_time(item["time"]) and old.strip() != str(item["time"]):
            raise Refused(f"nothing edited: the time of '{slug}' is {format_time(item['time'])}, not '{old}'")
        return parse_time(new)
    if field in ("title", "failing_kind", "test"):
        current = item.get(field)
        if not isinstance(current, str):
            raise Refused(f"nothing edited: '{slug}' has no {field} to edit")
        lines = [current]
    else:
        found = item.get(field)
        if not found:
            raise Refused(f"nothing edited: '{slug}' has no {field} to edit")
        lines = list(found)
    text = "\n".join(lines)
    if text.count(old) != 1:
        raise Refused(f"nothing edited: `old` is found {text.count(old)} times in {field} of '{slug}', not once; give more of the text around it")
    out = text.replace(old, new, 1)
    if field in ("title", "failing_kind", "test"):
        if "\n" in out:
            raise Refused(f"nothing edited: {field} is one line")
        return out.strip()
    return lines_of(out)


def edit_problem(item: dict, field: str, before: object, after: object) -> Optional[str]:
    """The refusal text when the edit of `field` from `before` to `after` changes a protected span (`quoted_spans`) or leaves quotes
    unbalanced, else None. Checked on the result: every quoted span of the old text stays byte-equal in the new."""
    if field in ("time",):
        return None
    old_lines = [before] if isinstance(before, str) else [str(x) for x in before]  # type: ignore[attr-defined]
    new_lines = [after] if isinstance(after, str) else [str(x) for x in after]  # type: ignore[attr-defined]
    spans = quoted_spans(old_lines)
    if spans is None:
        return f"quotes do not balance in {field} of '{item['slug']}'; correct it with a fact note (`relay queue note`)"
    kept = quoted_spans(new_lines)
    if kept is None:
        return f"the edit leaves a quote open in {field}; quoted text is never changed"
    for span in spans:
        if span in kept:
            kept.remove(span)
        else:
            return f"the edit changes quoted text in {field}: {span if len(span) < 80 else span[:77] + '...'}; quoted text is never changed (correct it with a fact note)"
    return None


def edit(repo: str, slug: str, field: str, old: str, new: str, because: str, now: Optional[str] = None, **engine: object) -> str:
    """Replace the one exact fragment `old` of `field` of item `slug` (any state) by `new`, leaving every quoted span byte-equal, and
    append a dated fact note saying why (`because`). The earlier text stays in git (`history`). `test` is edited only on a closed item,
    to a test found at the default branch's tip. Returns the landing line."""
    if field not in EDIT_FIELDS:
        raise Refused(f"nothing edited: `field` is one of {', '.join(EDIT_FIELDS)}")
    if not because.strip():
        raise Refused("nothing edited: say why in `because`")
    stamp = now or utcnow()
    if field in ("what", "why", "failing_case", "pass_cases"):
        refuse_session_paths("edited", **{field: new})

    def planner(reader):
        item = reader.items().get(slug)
        if item is None:
            raise Refused(f"nothing edited: no queue item '{slug}'")
        if item["problems"]:
            raise Refused(f"nothing edited: queue item '{slug}' is malformed ({'; '.join(item['problems'])})")
        main, default = _context(repo)
        if field == "test" and item["state"] != "done":
            raise Refused(f"nothing edited: the test of '{slug}' is edited only after it is closed (it is {item['state']}); `relay queue done` sets it")
        before = item["time"] if field == "time" else item.get(field)
        after = _edited_value(item, field, old, new, repo, default)
        if field == "test":                       # the whole test the item ends up naming, not the fragment
            reason = test_refusal(main, f"refs/heads/{default}", str(after))
            if reason:
                raise Refused(f"nothing edited: {reason}")
        if field == "failing_kind" and (item["kind"] != "fix" or after not in FAILING_KINDS):
            raise Refused(f"nothing edited: failing_kind is {', '.join(FAILING_KINDS)}, and only a fix has one")
        problem = edit_problem(item, field, before, after)
        if problem:
            raise Refused(f"nothing edited: {problem}")
        if field == "where":
            bad = where_problems(after) or where_folders(after, repo, before)
            if bad:
                raise Refused("nothing edited: " + "; ".join(bad))
        if after == before:
            raise Refused(f"nothing edited: {field} of '{slug}' is already that")
        when = stamp
        if when < item["found_at"]:
            raise Refused(f"nothing edited: {when} is before the item was found ({item['found_at']})")
        notes = notes_of(item)
        notes.insert(len([n for n in notes if n.at <= when]), Note("fact", when, [f"Edited {field}: {line}" if n == 0 else line for n, line in enumerate(lines_of(because))], edited=field))
        text = serialize(slug, changed(item, **{field: after}, notes=notes))
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, {field} edited", "edited")

    plan, sha = _land(repo, planner, **engine)
    out = _result(plan, sha, _context(repo)[1])
    item = Reader(_context(repo)[0], sha).items().get(slug) if sha else None
    if item and not item["problems"] and item["state"] == "taken":
        out += f"\n'{slug}' is taken by {item['taken_by']}: its check sees this once that branch takes the default branch"
    return out


def history(repo: str, slug: str) -> str:
    """The earlier text of item `slug`, read from git: for every commit on the default branch that changed a text field of the item,
    the date and the lines it replaced. Refused when the item has no file there."""
    main, default = _context(repo)
    rc, out, _ = _git(main, "log", "--reverse", "--format=%H %cI", f"refs/heads/{default}", "--", _path(slug))
    commits = [line.split(" ", 1) for line in _text(out).split("\n") if line] if rc == 0 else []
    if not commits:
        raise Refused(f"no queue item '{slug}' in the history of {default}")
    versions = cat_batch(main, [f"{c}:{_path(slug)}" for c, _ in commits])
    lines, prev = [], None
    for (_, when), blob in zip(commits, versions):
        try:
            data = json.loads((blob or b"{}").decode("utf-8", "replace"))
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        if prev is not None:
            for field in EDIT_FIELDS:
                if field in prev and prev.get(field) != data.get(field):
                    was = prev[field] if isinstance(prev[field], list) else [str(prev[field])]
                    lines += [f"{when[:16].replace('T', ' ')} {field} was:"] + ["  " + str(x) for x in was]
        prev = data
    return "\n".join(lines) if lines else f"'{slug}' has no earlier text: no field was edited"


def _haystack(item: dict) -> str:
    parts = [item["title"]] + item["what"] + item["why"]
    for n in notes_of(item):
        parts += n.text + n.options + n.because + n.answer + n.reading
    return "\n".join(parts).lower()


def search_items(items: list, words: str) -> list:
    """The well-formed items whose title, what, why or notes hold every word of `words`, in queue order."""
    wanted = words.lower().split()
    return ordered([i for i in items if not i["problems"] and wanted and all(w in _haystack(i) for w in wanted)])


def find_for_show(items: list, query: str) -> tuple:
    """(items, how): the item with that exact slug, else the items the words find ([] when none)."""
    exact = [i for i in items if i["slug"] == query]
    if exact:
        return exact, "slug"
    return search_items(items, query), "words"


def match_lines(found: list) -> list:
    """One line per found item: slug, title, state, number of decisions."""
    lines = []
    for i in found:
        decisions = sum(1 for n in notes_of(i) if n.kind == "decision")
        lines.append(f"{i['slug']}: {i['title']} ({i['state']}, {decisions} decision{'s' if decisions != 1 else ''})")
    return lines


def _local(stamp: str, tz: Optional[dt.tzinfo]) -> str:
    when = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).astimezone(tz)
    return f"{when.day} {when.strftime('%b %H:%M')}"


def _quoted(lines: list) -> list:
    body = ["    " + x for x in lines]
    body[0] = "    \u201c" + lines[0]
    body[-1] += "\u201d"
    return body


def notes_text(item: dict, tz: Optional[dt.tzinfo] = None) -> list:
    """The "Notes:" section lines of an item, oldest first, in local time (`tz`: tests pass UTC)."""
    out = []
    for n in notes_of(item):
        when = _local(n.at, tz)
        if n.kind in ("said", "fact"):
            out.append(f"  {when} " + ("the owner said:" if n.kind == "said" else "fact (front):"))
            if n.kind == "said":
                out += _quoted(n.text)
            else:
                out += ["    " + x for x in n.text]
            continue
        if n.decided_by:
            out.append(f"  {when} decided by the {n.decided_by} (an agent; owner can reverse) '{question_title(n)}', at {n.at}:")
        else:
            out.append(f"  {when} question '{question_title(n)}', asked {n.at}:")
        out += ["    " + x for x in n.text] + ["    - " + x for x in n.options]
        if n.decided_by:
            out += [f"    chosen: {n.chosen}", "    because: " + n.because[0]] + ["    " + x for x in n.because[1:]]
        if n.answered_at is None:
            if not n.decided_by:
                out.append("    not answered yet")
            continue
        out.append(f"  {_local(n.answered_at, tz)} the owner answered '{question_title(n)}' " + ("decided" if n.decided_by else "asked") + f" {n.at} (whole reply):")
        out += _quoted(n.answer)
        if n.reading:
            out += ["    front's reading (owner can reverse): " + n.reading[0]] + ["    " + x for x in n.reading[1:]]
        if n.answer_choice:
            if n.decided_by and n.answer_choice == n.chosen:
                out.append("    confirmed by the owner")
            elif n.decided_by:
                out.append(f"    owner chose {n.answer_choice}: overrules the {n.decided_by}'s {n.chosen}")
            else:
                out.append(f"    owner chose {n.answer_choice}")
    return ["Notes:"] + out if out else []


def waiting_lines(cwd: str, days: int, limit: int, now: Optional[str] = None) -> list:
    """Lines that name the questions waiting for an answer (asked within `days`, at most `limit` lines), for the front's message hook.
    One `git grep -l` on the default branch names the files with an asked question; only those are parsed. [] outside a project
    with `.relay/`, and when nothing waits. Never raises."""
    try:
        if not relay_git.has_relay(cwd):
            return []
        main, default = _context(cwd)
        rc, out, _ = _git(main, "grep", "-l", '"asked_at"', f"refs/heads/{default}", "--", QDIR)
        paths = [x.split(":", 1)[1] for x in _text(out).split("\n") if ":" in x and x.endswith(".json")] if rc == 0 else []
        if not paths:
            return []
        blobs = cat_batch(main, [f"refs/heads/{default}:{p}" for p in paths])
        stamp = now or utcnow()
        current = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        waiting = []
        for path, blob in zip(paths, blobs):
            if blob is None:
                continue
            item = parse(os.path.basename(path)[:-5], blob.decode("utf-8", "replace"))
            for n in owner_waiting(notes_of(item)) if not item["problems"] else []:
                age = current - dt.datetime.strptime(n.at, "%Y-%m-%dT%H:%M:%SZ")
                if age <= dt.timedelta(days=days):
                    waiting.append((n.at, item["slug"], n, age))
        waiting.sort(key=lambda w: (w[0], w[1]))
        lines = []
        for _, slug, n, age in waiting[:limit]:
            hours = int(age.total_seconds() // 3600)
            ago = f"{hours // 24}d" if hours >= 48 else f"{hours}h" if hours else f"{int(age.total_seconds() // 60)}m"
            lines.append(f"Waiting for the owner: {slug} question '{question_title(n)}', asked {n.at} ({ago} ago); if this message answers it, "
                         f"record the owner's whole message with `relay queue note {slug} --input <file.toml>` (answer = the message, to = [\"{n.at}\"])")
        return lines
    except Exception:
        return []
