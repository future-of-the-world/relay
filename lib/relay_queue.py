"""The work queue: items kept as `.relay/queue/<slug>.md` on the default branch (design: docs/plans/review-gate.md, section 10).

Everything reads the default branch through git (`ls-tree`, `cat-file --batch`), never a checkout, so
every worktree sees the same queue. Commands that change an item land one commit on the default branch
without touching any checkout (`hash-object`, a temporary index, `commit-tree`), on a branch
`wt/queue-<slug>` that is created only if absent, and fast-forward the main checkout to it. Each try
re-reads the head and re-checks the command's precondition; after `QUEUE_LAND_TRIES` failed tries the
branch is kept for `relay queue land`.
"""

import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile
import time

import relay_git

QUEUE_LAND_TRIES = 5          # bound 1-20: at 20 a landing can take about 20 s
MAX_TRIES = 20
WAITS = (0.2, 0.4, 0.8, 1.0)  # seconds between tries; the last repeats (0.2-1 s, design 10.4)
QDIR = ".relay/queue"
ZERO = "0" * 40
KINDS = ("fix", "feature")
STATES = ("open", "taken", "done", "dropped")
FIELDS = ("kind", "state", "ip", "size", "found", "taken-by", "closed-by", "test")
LABELS = ("What is wrong", "Failing case", "Pass-cases", "Why it matters", "Where", "Finding", "Size", "Smallest fix", "Design", "What")
LINTER = re.compile(r"^(?P<path>[^\s:]+):(?P<line>\d+): (?P<sev>[A-Z]+): (?P<id>[A-Z]\d+) (?P<what>.+)$")
LABEL = re.compile(r"^(%s):\s*(.*)$" % "|".join(re.escape(x) for x in LABELS))


class Refused(ValueError):
    """The command was refused or could not land; the message is for the person. Nothing was written unless it says so."""


# ---------------------------------------------------------------- item files

def _frontmatter(text):
    """(dict of field -> string, index of the closing `---` line, lines) or (None, 0, lines) when there is no frontmatter."""
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None, 0, lines
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            fields = {}
            for raw in lines[1:i]:
                key, sep, value = raw.partition(":")
                if sep and key.strip():
                    fields[key.strip()] = re.sub(r"\s{2,}#.*$", "", value).strip()
            return fields, i, lines
    return None, 0, lines


def parse(slug, text):
    """An item as a dict: the fields, `title`, `where`, `body`, and `problems` (empty when well formed)."""
    fields, end, lines = _frontmatter(text)
    item = {"slug": slug, "problems": [], "kind": "", "state": "", "ip": None, "size": None, "found": "",
            "taken_by": "", "closed_by": "", "test": "", "title": slug, "where": "", "body": ""}
    if fields is None:
        item["problems"].append("no frontmatter")
        return item
    body = "\n".join(lines[end + 1:])
    item["body"] = body
    item["kind"], item["state"] = fields.get("kind", ""), fields.get("state", "")
    item["found"], item["taken_by"] = fields.get("found", ""), fields.get("taken-by", "")
    item["closed_by"], item["test"] = fields.get("closed-by", ""), fields.get("test", "")
    if item["kind"] not in KINDS:
        item["problems"].append("kind is not fix or feature")
    if item["state"] not in STATES:
        item["problems"].append("state is not open, taken, done or dropped")
    for key in ("ip", "size"):
        value = fields.get(key, "")
        if re.fullmatch(r"\d+", value):
            item[key] = int(value)
        else:
            item["problems"].append(f"{key} is not a whole number")
    for raw in body.split("\n"):
        if raw.startswith("# "):
            item["title"] = raw[2:].strip() or slug
            break
    match = re.search(r"(?m)^Where:\s*(\S+)", body)
    item["where"] = match.group(1) if match else ""
    if item["kind"] == "fix" and not field_block(body, "Failing case"):
        item["problems"].append("a fix without Failing case:")
    return item


def field_block(body, label):
    """The text of `<label>: ...` and its continuation lines, up to the next known label; "" when absent or empty."""
    out, inside = [], False
    for raw in body.split("\n"):
        match = LABEL.match(raw)
        if match:
            if inside:
                break
            inside = match.group(1) == label
            if inside:
                out.append(match.group(2))
            continue
        if inside:
            out.append(raw)
    return "\n".join(out).strip()


def set_fields(text, **changes):
    """`text` with these frontmatter fields set (underscores stand for hyphens); the rest is kept byte for byte."""
    fields, end, lines = _frontmatter(text)
    if fields is None:
        raise Refused("the item has no frontmatter")
    for key, value in changes.items():
        name = key.replace("_", "-")
        line = f"{name}: {value}".rstrip()
        for i in range(1, end):
            if lines[i].startswith(name + ":"):
                lines[i] = line
                break
        else:
            lines.insert(end, line)
            end += 1
    return "\n".join(lines)


def render(kind, ip, size, found, title, body, state="open"):
    return (f"---\nkind: {kind}\nstate: {state}\nip: {ip}\nsize: {size}\nfound: {found}\ntaken-by:\nclosed-by:\ntest:\n---\n"
            f"# {title}\n\n{body.rstrip()}\n")


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48].strip("-")
    if not slug:
        raise Refused("the title has no letters or digits to make a name from")
    return slug


def order_key(item):
    return (-item["ip"], item["found"], item["slug"])


def ordered(items):
    """Well-formed items by ip (highest first), then older `found`, then slug; malformed ones last, by slug."""
    good = sorted((i for i in items if not i["problems"]), key=order_key)
    bad = sorted((i for i in items if i["problems"]), key=lambda i: i["slug"])
    return good + bad


def count_text(items):
    """`10 fix, 12 feature; top: slug (fix, ip 95, 30 min)` over the open, well-formed items."""
    open_items = [i for i in items if not i["problems"] and i["state"] == "open"]
    fix = sum(1 for i in open_items if i["kind"] == "fix")
    text = f"{fix} fix, {len(open_items) - fix} feature"
    if open_items:
        top = sorted(open_items, key=order_key)[0]
        text += f"; top: {top['slug']} ({top['kind']}, ip {top['ip']}, {top['size']} min)"
    return text


def list_lines(items):
    lines = []
    for i in ordered(items):
        if i["problems"]:
            lines.append(f"{i['slug']}  malformed ({'; '.join(i['problems'])})")
            continue
        state = "" if i["state"] == "open" else f"  {i['state']} by {i['taken_by'] or '?'}"
        lines.append(f"{i['slug']}  {i['kind']}  ip {i['ip']}  {i['size']} min{state}  {i['title']}")
    return lines


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
        return sorted(os.path.basename(n)[:-3] for n in names if n.endswith(".md") and os.path.dirname(n) == (QDIR + "/" + sub).rstrip("/"))

    def has_folder(self):
        rc, out, _ = _git(self.main, "ls-tree", "-d", "--name-only", self.rev, QDIR)
        return rc == 0 and _text(out) == QDIR

    def items(self):
        if self._items is None:
            slugs = self.names()
            blobs = cat_batch(self.main, [f"{self.rev}:{QDIR}/{s}.md" for s in slugs])
            self._items = {s: parse(s, b.decode("utf-8", "replace")) for s, b in zip(slugs, blobs) if b is not None}
            self._texts = {s: b.decode("utf-8", "replace") for s, b in zip(slugs, blobs) if b is not None}
        return self._items

    def text(self, slug):
        self.items()
        return self._texts.get(slug)

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


def read_queue(repo):
    """Every item (parsed) of the default branch, read from git; [] when there is no queue folder."""
    main, default = _context(repo)
    rc, out, _ = _git(main, "rev-parse", "--verify", "-q", f"refs/heads/{default}")
    if rc != 0:
        return []
    reader = Reader(main, _text(out))
    return list(reader.items().values()) if reader.has_folder() else []


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
    return f"{QDIR}/{sub}{slug}.md"


def _taken_by_refusal(item):
    return Refused(f"queue item '{item['slug']}' is taken by {item['taken_by']}; release it first")


# ---------------------------------------------------------------- commands

def find_finding(report_text, fid):
    """The finding `fid` of a findings report: where, severity, what, and its labelled fields."""
    lines = report_text.split("\n")
    for i, raw in enumerate(lines):
        match = LINTER.match(raw)
        if match and match.group("id") == fid:
            block = []
            for nxt in lines[i + 1:]:
                if LINTER.match(nxt) or nxt.startswith("#"):
                    break
                block.append(nxt)
            body = "\n".join(block)
            size = re.match(r"\d+", field_block(body, "Size"))
            return {"linter": raw, "where": f"{match.group('path')}:{match.group('line')}", "what": match.group("what"),
                    "failing": field_block(body, "Failing case"), "pass": field_block(body, "Pass-cases"),
                    "why": field_block(body, "Why it matters"), "size": int(size.group()) if size else None}
    raise Refused(f"no finding {fid} in the report")


def add(repo, kind, title, why="", what="", failing="", pass_cases="", size=None, ip=None, where="", linter="",
        context="relay queue add", today=None, **engine):
    """Queue a new item. The slug comes from the title, suffixed -2, -3, ... when taken."""
    if kind not in KINDS:
        raise Refused("kind is fix or feature")
    if not title.strip():
        raise Refused("an item needs a title")
    if kind == "fix" and not failing.strip():
        raise Refused("a fix item needs its Failing case:")
    if not why.strip():
        raise Refused("an item needs Why it matters (--why)")
    if size is None or size < 0:
        raise Refused("an item needs its size in agent minutes (--size)")
    if ip is not None and ip < 0:
        raise Refused("ip is a whole number from 0")
    base = slugify(title)
    found = f"{today or dt.date.today().isoformat()}, {context}"
    parts = []
    if where:
        parts.append(f"Where: {where}")
    if linter:
        parts.append(f"Finding: {linter}")
    parts.append(f"What is wrong: {what or title}" if kind == "fix" else f"What: {what or title}")
    if kind == "fix":
        parts.append(f"Failing case: {failing.strip()}")
        if pass_cases.strip():
            parts.append(f"Pass-cases: {pass_cases.strip()}")
    parts.append(f"Why it matters: {why.strip()}")
    body = "\n".join(parts)

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
        return Plan(slug, {_path(slug): render(kind, value, size, found, title.strip(), body)}, f"{kind}, ip {value}", "queued")

    return _run(repo, planner, **engine)


def add_from(repo, report, fid, why="", size=None, ip=None, today=None, **engine):
    """Queue the finding `fid` of a findings report as a fix item (the linter line and the cases are copied)."""
    try:
        with open(report, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise Refused(f"cannot read the report: {exc}")
    found = find_finding(text, fid)
    context = f"finding {fid} of {os.path.basename(report)}"
    if size is None:
        size = found["size"]
    return add(repo, "fix", found["what"], why=why or found["why"], what=found["what"], failing=found["failing"],
               pass_cases=found["pass"], size=size, ip=ip, where=found["where"], linter=found["linter"],
               context=context, today=today, **engine)


def set_ip(repo, slug, ip, **engine):
    if ip < 0:
        raise Refused("ip is a whole number from 0")

    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] == "taken":
            raise _taken_by_refusal(item)
        if item["state"] != "open":
            raise Refused(f"queue item '{slug}' is {item['state']}")
        return Plan(slug, {_path(slug): set_fields(reader.text(slug), ip=ip)}, f"{item['kind']}, ip {ip}", "ip set")

    return _run(repo, planner, **engine)


def drop(repo, slug, why, **engine):
    if not why.strip():
        raise Refused("drop needs the owner's words (--why)")

    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] == "taken":
            raise _taken_by_refusal(item)
        text = set_fields(reader.text(slug), state="dropped")
        text = text.rstrip("\n") + f"\n\nDropped on the owner's word: {why.strip()}\n"
        return Plan(slug, {_path(slug): None, _path(slug, "done/"): text}, f"{item['kind']}, ip {item['ip']}", "dropped")

    return _run(repo, planner, **engine)


def release(repo, slug, **engine):
    def planner(reader):
        item = _item_at(reader, slug)
        if item["state"] != "taken":
            raise Refused(f"queue item '{slug}' is not taken")
        text = set_fields(reader.text(slug), state="open", taken_by="")
        return Plan(slug, {_path(slug): text}, f"{item['kind']}, ip {item['ip']}", "released")

    return _run(repo, planner, **engine)


def take(worktree, slug, findings, **engine):
    """Land `taken` on the default branch, bring it into the worktree's branch, and for a fix write the findings file."""
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
        text = set_fields(reader.text(slug), state="taken", taken_by=branch)
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
        where = item["where"] or f"{_path(slug)}:1"
        parts = [f"Reviewed: {_text(base)}", f"From queue: {slug}", "",
                 f"{where}: HIGH: Q1 {item['title']}", f"Failing case: {field_block(item['body'], 'Failing case')}"]
        passes = field_block(item["body"], "Pass-cases")
        if passes:
            parts.append(f"Pass-cases: {passes}")
        os.makedirs(os.path.dirname(os.path.abspath(findings)), exist_ok=True)
        with open(findings, "w", encoding="utf-8") as handle:
            handle.write("\n".join(parts) + "\n")
        out.append(f"findings written to {findings}")
    return "\n".join(out)


def done(worktree, slug, test, check):
    """Close a taken item on the task branch: needs the named test at HEAD and a checker report that says `Q1 MET`."""
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
    item = parse(slug, out.decode("utf-8", "replace"))
    if item["problems"]:
        raise Refused(f"queue item '{slug}' is malformed ({'; '.join(item['problems'])})")
    if item["state"] != "taken" or item["taken_by"] != branch:
        raise Refused(f"queue item '{slug}' is not taken by {branch}")
    rc, source, _ = _git(worktree, "cat-file", "blob", f"HEAD:{path}")
    if rc != 0:
        raise Refused(f"the test file {path} is not in the last commit of {branch}")
    if name.split("::")[-1] not in source.decode("utf-8", "replace"):
        raise Refused(f"{path} does not hold a test named {name}")
    try:
        with open(check, encoding="utf-8") as handle:
            report = handle.read()
    except OSError as exc:
        raise Refused(f"cannot read the checker report: {exc}")
    if item["kind"] == "fix" and not re.search(r"(?m)^\s*Q1 MET\b", report):
        raise Refused("the checker report does not say Q1 MET")
    root = _text(_git(worktree, "rev-parse", "--show-toplevel")[1])
    text = set_fields(out.decode("utf-8", "replace"), state="done", closed_by=branch, test=test)
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
            if reader.blob(p) != old.blob(p):
                raise Refused(f"{p} changed on {default} since this change was made; it no longer holds (branch {branch} kept)")
        return Plan(slug, {p: (t.decode("utf-8", "replace") if t is not None else None) for p, t in texts.items()}, "kept change", verb)

    plan, sha = _land(repo, planner, takeover=tip, **engine)
    return _result(plan, sha, default)
