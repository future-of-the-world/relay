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

import copy
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

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
# The keys of an item file, in the order they are written. An item keeps dated events, never a stored state: `state_of` computes it.
# TEXT are lists of lines (so a git diff goes line by line).
ORDER = ("kind", "ip", "time", "found_at", "found_in", "title", "what", "why", "failing_case", "pass_cases", "where",
         "taken_at", "taken_by", "closed_at", "test", "dropped_at", "dropped_why")
TEXT = ("what", "why", "failing_case", "pass_cases")
EVENTS = ("found_at", "taken_at", "closed_at", "dropped_at")
OLD_ONLY = ("state", "found", "closed_by")    # the keys of the shape before dated events; `relay queue migrate` rewrites them
REQUIRED = ("kind", "ip", "time", "found_at", "found_in", "title", "what", "why", "taken_at", "taken_by", "closed_at", "test",
            "dropped_at", "dropped_why")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MIGRATE_HINT = "run `relay queue migrate` on this branch"
TITLE_MAX = 60                # a title is under this many characters (rules/queue.md)


class Refused(ValueError):
    """The command was refused or could not land; the message is for the person. Nothing was written unless it says so."""


# ---------------------------------------------------------------- item files

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_lines(value):
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


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


def check(slug, data, where=None):
    """The reasons `data` (a decoded item file) is not a well-formed item; [] when it is.

    `where` is "open" (the queue folder) or "done" (its done/ folder) when the folder of the file is known."""
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
    for key in ("ip", "time"):
        if key in data and not _is_int(data[key]):
            problems.append(f"{key} is not a whole number from 0")
    for key in EVENTS:
        if key in data and data[key] is not None and not _timestamp(data[key]):
            problems.append(f"{key} is not null or a UTC time YYYY-MM-DDTHH:MM:SSZ")
    if "found_at" in data and data["found_at"] is None:
        problems.append("found_at is null")
    for key in ("found_in", "title", "where"):
        if key in data and not isinstance(data[key], str):
            problems.append(f"{key} is not a string")
    for key in ("taken_by", "test"):
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
    if closed is not None and taken is None:
        problems.append("closed_at without taken_at")
    if closed is not None and not data.get("test"):
        problems.append("closed_at without a test")
    if data.get("test") and closed is None:
        problems.append("a test without closed_at")
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
    if where is not None:
        ended = closed is not None or dropped is not None
        if ended != (where == "done"):
            problems.append("an item under done/ needs closed_at or dropped_at" if where == "done" else "an item with closed_at or dropped_at belongs under done/")
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

    `where` is "open" or "done" when the folder of the file is known. A file that fails the check (an old-shape one
    too) comes back as {"slug", "problems"} only, so nothing reads half an item."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return {"slug": slug, "problems": [f"not valid JSON: {exc}"]}
    problems = check(slug, data, where)
    if problems:
        return {"slug": slug, "problems": problems}
    item = {key: data[key] for key in ORDER if key in data}
    item.update(state=state_of(data), slug=slug, problems=[])
    return item


def serialize(slug, item, where=None):
    """The file text of an item: indent 2, fixed key order, UTF-8, a trailing newline. Refused when it fails the check
    (`where` is "open" or "done": the folder the file is written to)."""
    data = {key: item[key] for key in ORDER if key in item}
    extra = sorted(set(item) - set(ORDER) - {"slug", "problems", "state"})
    problems = check(slug, data, where) + [f"unknown key {k}" for k in extra]
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


def new_item(kind, ip, minutes, found_at, found_in, title, what, why, failing="", pass_cases="", where=""):
    item = {"kind": kind, "ip": ip, "time": minutes, "found_at": found_at, "found_in": found_in,
            "title": title, "what": lines_of(what), "why": lines_of(why)}
    if failing.strip():
        item["failing_case"] = lines_of(failing)
    if pass_cases.strip():
        item["pass_cases"] = lines_of(pass_cases)
    if where:
        item["where"] = where
    item.update({"taken_at": None, "taken_by": None, "closed_at": None, "test": None, "dropped_at": None, "dropped_why": None})
    return item


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48].strip("-")
    if not slug:
        raise Refused("the title has no letters or digits to make a name from")
    return slug


def order_key(item):
    return (-item["ip"], item["found_at"], item["slug"])


def ordered(items):
    """Well-formed items by ip (highest first), then older `found_at`, then slug; malformed ones last, by slug."""
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


def show_text(item):
    """One well-formed item in full, as the person reads it (a read-only view of the stored JSON)."""
    state = item["state"] + (f" by {item['taken_by']}" if item["taken_by"] else "")
    out = [f"{item['slug']}: {item['title']}", f"{item['kind']}, ip {item['ip']}, {format_time(item['time'])}, {state}",
           f"found {item['found_at']} in {item['found_in']}"]
    if item.get("where"):
        out.append(f"where {item['where']}")
    for label, key in (("taken", "taken_at"), ("closed", "closed_at"), ("dropped", "dropped_at")):
        if item[key]:
            out.append(f"{label} {item[key]}")
    if item["test"]:
        out.append(f"test {item['test']}")
    for title, key in (("What", "what"), ("Why", "why"), ("Failing case", "failing_case"), ("Pass cases", "pass_cases"), ("Dropped because", "dropped_why")):
        if item.get(key):
            out += [f"{title}:"] + ["  " + line for line in item[key]]
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
        if self._items is None:
            slugs = self.names()
            blobs = cat_batch(self.main, [f"{self.rev}:{QDIR}/{s}.json" for s in slugs])
            self._items = {s: parse(s, b.decode("utf-8", "replace"), "open") for s, b in zip(slugs, blobs) if b is not None}
        return self._items

    def closed_items(self):
        """The items of `done/` (closed or dropped), parsed, by slug."""
        slugs = self.names("done/")
        blobs = cat_batch(self.main, [f"{self.rev}:{QDIR}/done/{s}.json" for s in slugs])
        return {s: parse(s, b.decode("utf-8", "replace"), "done") for s, b in zip(slugs, blobs) if b is not None}

    def used_slugs(self):
        return set(self.names()) | set(self.names("done/"))

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
    """Every item (parsed) of the default branch, read from git; [] when there is no queue folder.
    With `closed`, the items of `done/` (closed and dropped) too."""
    main, default = _context(repo)
    rc, out, _ = _git(main, "rev-parse", "--verify", "-q", f"refs/heads/{default}")
    if rc != 0:
        return []
    reader = Reader(main, _text(out))
    if not reader.has_folder():
        return []
    return list(reader.items().values()) + (list(reader.closed_items().values()) if closed else [])


def check_files(root):
    """(path, reasons) for each item file under `root`/.relay/queue and its done/ folder that is not well formed, sorted by path.
    Reads the checkout's files, so a branch is checked before its merge. Raises Refused when there is no queue folder."""
    problems = []
    base = os.path.join(root, QDIR)
    if not os.path.isdir(base):
        raise Refused(f"no {QDIR} folder under {root}")
    for sub, where in (("", "open"), ("done", "done")):
        folder = os.path.join(base, sub)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name.endswith(".json"):
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    item = parse(name[:-5], handle.read(), where)
                if item["problems"]:
                    problems.append((f"{QDIR}/{sub + '/' if sub else ''}{name}", item["problems"]))
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


def _last_line(text):
    lines = [x for x in text.strip().split("\n") if x.strip()]
    return lines[-1].strip() if lines else "no message from git"


def _land(repo, planner, tries=None, sleep=time.sleep, after_plan=None, takeover=None):
    """Land the change `planner(Reader)` describes on the default branch (design 10.4, steps 1-6).

    Returns (plan, sha). `after_plan(try_index, plan)` runs between steps 2 and 3 (tests use it to
    place a second session exactly there). `takeover` is the tip of a kept branch `relay queue land` retries.
    Raises Refused for a refusal and when the last try failed (the message says the branch is kept)."""
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
        if not takeover and n < tries - 1:
            _git(main, "update-ref", "-d", ref, new)
    if held:
        raise Refused(last)
    raise Refused(f"not landed after {tries} tries: {last}; kept on {branch}; relay queue land {plan.slug} tries again")


def _result(plan, default_sha, default):
    return f"{plan.verb} {plan.slug} ({plan.label}), landed on {default} at {default_sha}"


def _run(repo, planner, **kwargs):
    plan, sha = _land(repo, planner, **kwargs)
    return _result(plan, sha, _context(repo)[1])


def _item_at(reader, slug):
    item = reader.items().get(slug)
    if item is None:
        raise Refused(f"no open queue item '{slug}'")
    if item["problems"]:
        raise Refused(f"queue item '{slug}' is malformed ({'; '.join(item['problems'])})")
    return item


def _path(slug, sub=""):
    return f"{QDIR}/{sub}{slug}.json"


def _taken_by_refusal(item):
    return Refused(f"queue item '{item['slug']}' is taken by {item['taken_by']}; release it first")


# ---------------------------------------------------------------- commands

def find_finding(report, fid):
    """The finding `fid` from the JSON a judge recorded at `report` (written by `relay check record`): a review's findings,
    or a check's new ones. Refused, naming the file, when it is missing or invalid."""
    try:
        with open(report, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        raise Refused(f"no recorded findings at {report}: it is the JSON file `relay check record` wrote")
    try:
        kind, data = relay_verdict.load_any(text, f"the recorded data {report}")
    except relay_verdict.VerdictError as exc:
        raise Refused(str(exc))
    if kind == relay_verdict.SET_TYPE:
        found = [f for r in data["reviews"] for f in r["findings"]]
    else:
        found = data["new"] if kind == relay_verdict.CHECK_TYPE else data["findings"]
    for finding in found:
        if finding["id"] == fid:
            return finding
    raise Refused(f"no finding {fid} in {report}")


ADD_KEYS = ("kind", "title", "why", "what", "failing_case", "pass_cases", "time", "ip", "where")
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
        if key in ("kind", "title", "where"):
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


def add(repo, kind, title, why="", what="", failing="", pass_cases="", minutes=None, ip=None, where="",
        context="relay queue add", now=None, **engine):
    """Queue a new item. The slug comes from the title, suffixed -2, -3, ... when taken."""
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
    if not why.strip():
        raise Refused("an item needs why it matters (`why` in the input)")
    if minutes is None or minutes < 0:
        raise Refused(f"an item needs its time (`time` in the input or --time), as {TIME_FORMS}")
    if ip is not None and ip < 0:
        raise Refused("ip is a whole number from 0")
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
            top = [i["ip"] for i in reader.items().values() if not i["problems"] and i["kind"] == "feature" and i["state"] == "open"]
            value = (1 + max(top, default=0)) if kind == "fix" else 0
        item = new_item(kind, value, minutes, found, context, title.strip(), what or title.strip(), why, failing, pass_cases, where)
        return Plan(slug, {_path(slug): serialize(slug, item)}, f"{kind}, ip {value}", "queued")

    return _run(repo, planner, **engine)


def add_from(repo, report, fid, why="", minutes=None, ip=None, now=None, **engine):
    """Queue the finding `fid` recorded beside `report` as a fix item: its place and failing case are copied, its
    linter line (relay_verdict.linter) is the item's `what`, so the check page can tell which item carries it."""
    found = find_finding(report, fid)
    context = f"finding {fid} of {os.path.basename(report)}"
    summary = found["summary"]
    title = summary[0].upper() + summary[1:]     # a summary is a sentence; the capital keeps `add` from taking it for the slug's words
    if len(title) >= TITLE_MAX:                   # a title is the "what" column: cut a long summary at a word (the linter line in `what` holds all of it)
        title = title[:TITLE_MAX - 2].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"
    return add(repo, "fix", title, why=why, what=relay_verdict.linter(found), failing="\n".join(found["failing_case"]),
               pass_cases="\n".join(found.get("pass_cases") or []), minutes=minutes, ip=ip, where=f"{found['path']}:{found['line']}", context=context, now=now, **engine)


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
        text = serialize(slug, changed(item, dropped_at=utcnow(), dropped_why=lines_of(why)), "done")
        return Plan(slug, {_path(slug): None, _path(slug, "done/"): text}, f"{item['kind']}, ip {item['ip']}", "dropped")

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
    where = item.get("where") or f"{_path(item['slug'])}:1"
    place, _, line = where.rpartition(":")
    if not (place and line.isdigit() and int(line) >= 1):
        place, line = where, "1"
    return {"id": "Q1", "path": place, "line": int(line), "severity": "HIGH", "rank": "high", "kind": "inside", "summary": item["title"],
            "failing_case": list(item["failing_case"]), "details": list(item["why"]),
            "pass_cases": list(item.get("pass_cases") or []), "evidence": [], "fix_hint": []}


def take(worktree, slug, findings, **engine):
    """Land `taken` on the default branch, bring it into the worktree's branch, and for a fix write the review JSON
    (`findings`, one finding Q1 from the item) that the checker records against."""
    main, default = _context_with_relay(worktree)
    branch = relay_git.current_branch(worktree)
    if branch is None or branch == default:
        raise Refused("take from the worktree of a task branch")
    seen = {}

    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] == "taken":
            raise Refused(f"queue item '{slug}' is taken by {item['taken_by']}")
        if item["state"] != "open":
            raise Refused(f"queue item '{slug}' is {item['state']}")
        seen["item"] = item
        if item["kind"] == "fix":                   # the finding Q1 must be writable before `taken` lands: no item left taken without findings
            errors = relay_verdict.finding_errors(_q1(item), "finding Q1 of the item")
            if errors:
                raise Refused(f"queue item '{slug}' cannot become finding Q1, nothing taken: {'; '.join(errors[:3])}")
        text = serialize(slug, changed(item, taken_at=utcnow(), taken_by=branch))
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, ip {item['ip']}", "taken")

    plan, sha = _land(worktree, planner, **engine)
    out = [_result(plan, sha, default)]
    rc, merged, err = _git(worktree, "merge", "--no-edit", default)
    if rc != 0:
        raise Refused(f"{out[0]}; but merging {default} into {branch} failed: {_last_line(err or _text(merged))}")
    item = seen["item"]
    if item["kind"] == "fix":
        rc, base, err = _git(worktree, "merge-base", branch, default)
        if rc != 0:
            raise Refused(f"{out[0]}; but no merge-base of {branch} and {default}: {err}")
        data = relay_verdict.review_data(_text(base), default, [_q1(item)], scope=[f"From queue item {slug}: the fix is checked as finding Q1."])
        try:
            relay_verdict.write_review(findings, data)
        except relay_verdict.VerdictError as exc:
            raise Refused(f"{out[0]}; but the findings cannot be written: {exc}")
        out.append(f"findings written to {findings}")
    return "\n".join(out)


def _holds_test(path, name, source):
    """Whether the test file's text defines the test `name` as a whole word (a python file: `def name`); test_xy is not test_x."""
    pattern = r"\bdef\s+" + re.escape(name) + r"\b" if path.endswith(".py") else r"(?<![\w])" + re.escape(name) + r"(?![\w])"
    return re.search(pattern, source) is not None


def _check_is_of_this_item(worktree, slug, check, data):
    """Refuse check data that is not the check of this branch's Q1 for this item: its head must be HEAD (or an earlier commit
    with only `.relay/` files changed since), and one of its reviews must be the findings file `take` wrote for `slug`."""
    rc, _, _ = _git(worktree, "merge-base", "--is-ancestor", data["head"], "HEAD")
    if rc != 0:
        raise Refused(f"the check data {check} is of {data['head'][:12]}, which is not in this branch's history: it is not the check of this fix")
    rc, out, _ = _git(worktree, "diff", "--name-only", "--no-renames", f"{data['head']}..HEAD")
    later = sorted(p for p in _text(out).split("\n") if p and not p.startswith(".relay/"))
    if later:
        raise Refused(f"the check data {check} is of {data['head'][:12]}; {', '.join(later[:3])} changed after it: check the fix again")
    marker = f"From queue item {slug}:"
    for path in data["review"]:
        try:
            with open(path, encoding="utf-8") as handle:
                review = relay_verdict.load_review(handle.read(), f"the review data {path}")
        except (OSError, relay_verdict.VerdictError):
            continue
        if any(line.startswith(marker) for line in review.get("scope") or []):
            return
    raise Refused(f"the check data {check} does not check the findings file `relay queue take` wrote for '{slug}' (scope \"{marker}\")")


def done(worktree, slug, test, check):
    """Close a taken item on the task branch: needs the named test at HEAD and, for a fix, check data (`check`, the JSON
    `relay check record check` wrote) whose verdict for Q1 is MET."""
    branch = relay_git.current_branch(worktree)
    main, default = _context(worktree)
    if branch is None or branch == default:
        raise Refused("done runs in the worktree of the task branch that took the item")
    path, _, name = test.partition("::")
    if not path or not name:
        raise Refused("--test is <test file>::<test name>")
    rc, out, _ = _git(worktree, "cat-file", "blob", f"HEAD:{_path(slug)}")
    if rc != 0:
        raise Refused(f"no queue item '{slug}' on this branch (take it first)")
    item = parse(slug, out.decode("utf-8", "replace"), "open")
    if item["problems"]:
        raise Refused(f"queue item '{slug}' is malformed ({'; '.join(item['problems'])})")
    if item["state"] != "taken" or item["taken_by"] != branch:
        raise Refused(f"queue item '{slug}' is not taken by {branch}")
    rc, source, _ = _git(worktree, "cat-file", "blob", f"HEAD:{path}")
    if rc != 0:
        raise Refused(f"the test file {path} is not in the last commit of {branch}")
    if not _holds_test(path, name.split("::")[-1], source.decode("utf-8", "replace")):
        raise Refused(f"{path} does not hold a test named {name}")
    try:
        with open(check, encoding="utf-8") as handle:
            report = handle.read()
    except OSError as exc:
        raise Refused(f"cannot read the check data {check}: {exc.strerror}")
    try:
        kind, data = relay_verdict.load_any(report, f"the check data {check}")
    except relay_verdict.VerdictError as exc:
        raise Refused(str(exc))
    if kind != relay_verdict.CHECK_TYPE:
        raise Refused(f"{check} is a {kind}, not the check data (the JSON of relay check record check)")
    if item["kind"] == "fix":
        verdict = next((s["verdict"] for s in data["findings"] if s["id"] == "Q1"), None)
        if verdict is None:
            raise Refused(f"the check data {check} gives no verdict for Q1")
        if verdict != "MET":
            raise Refused(f"the check data {check} says Q1 {verdict}, not MET")
        _check_is_of_this_item(worktree, slug, check, data)
    root = _text(_git(worktree, "rev-parse", "--show-toplevel")[1])
    text = serialize(slug, changed(item, closed_at=utcnow(), test=test), "done")
    old, new = os.path.join(root, _path(slug)), os.path.join(root, _path(slug, "done/"))
    os.makedirs(os.path.dirname(new), exist_ok=True)
    with open(new, "w", encoding="utf-8") as handle:
        handle.write(text)
    if os.path.exists(old):
        os.remove(old)
    paths = [_path(slug), _path(slug, "done/")]
    for args in (("add", "-A", "--", *paths), ("commit", "-m", f"queue: done {slug}", "--only", "--", *paths)):
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
    if not paths or len(paths) > 2 or any(p != _path(slug) and p != _path(slug, "done/") for p in paths):
        raise Refused(f"{branch} changes more than the item '{slug}'; delete it (relay doctor)")
    texts = dict(zip(paths, cat_batch(main, [f"{tip}:{p}" for p in paths])))
    old = Reader(main, base)
    verb = "queued"

    def planner(reader):
        for p in paths:
            if texts[p] is not None:         # a kept change of the old shape (made before the migration) is refused, not landed
                bad = parse(slug, texts[p].decode("utf-8", "replace"), "done" if "/done/" in p else "open")["problems"]
                if bad:
                    raise Refused(f"{p} on {branch} is not well formed ({'; '.join(bad)}); branch {branch} kept")
            if reader.blob(p) != old.blob(p):
                raise Refused(f"{p} changed on {default} since this change was made; it no longer holds (branch {branch} kept)")
        return Plan(slug, {p: (t.decode("utf-8", "replace") if t is not None else None) for p, t in texts.items()}, "kept change", verb)

    plan, sha = _land(repo, planner, takeover=tip, **engine)
    return _result(plan, sha, default)
