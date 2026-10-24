"""The work queue (design docs/plans/review-gate.md 12.5, tests Q1-Q10). Every git test runs on scratch repositories in a temp dir."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_marks  # noqa: E402
import relay_queue as rq  # noqa: E402
import relay_verdict as rv  # noqa: E402

NOSLEEP = lambda seconds: None  # noqa: E731  (time is a value: the tests never wait)
QUIET = {"sleep": NOSLEEP}


def git(repo, *args, check=True):
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


SLUG = "item"   # the check only compares the title with the file's own name; no helper title is the words "item"


def fix_item(title="A fix", ip=91, size=10, found="2026-10-01T00:00:00Z", failing="the case fails"):
    return rq.serialize(SLUG, rq.new_item("fix", ip, size, found, "test", title, "what is wrong here", "it matters", failing=failing,
                                          pass_cases="the other case", where="lib/x.py:5"))


def feature_item(title="A feature", ip=0, size=10, found="2026-10-01T00:00:00Z"):
    return rq.serialize(SLUG, rq.new_item("feature", ip, size, found, "test", title, "what is wanted here", "it matters"))


TAKEN_AT = "2026-10-02T00:00:00Z"
CLOSED_AT = "2026-10-03T00:00:00Z"


def taken_fields(by="wt/z"):
    return {"taken_at": TAKEN_AT, "taken_by": by}


def with_fields(text, **changes):
    """The item text with these fields set, written by the library."""
    return rq.serialize(SLUG, rq.changed(rq.parse(SLUG, text), **changes))


def raw_item(text, drop=(), **changes):
    """Item text edited around the library: a file as a person or a bad merge could leave it."""
    data = json.loads(text)
    data.update(changes)
    for key in drop:
        del data[key]
    return json.dumps(data, indent=2) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-queue-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        empty = os.path.join(self.tmp, "gitconfig")
        open(empty, "w").close()
        patch = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": empty, "GIT_CONFIG_SYSTEM": empty, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
                                             "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"})
        patch.start()
        self.addCleanup(patch.stop)
        self.main = self.repo("main")

    def repo(self, name, relay=True, items=None):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        git(path, "init", "-q", "-b", "master")
        files = {"README.md": "x\n"}
        if relay:
            files[".relay/README.md"] = "relay folder\n"
            for slug, text in (items or {}).items():
                files[f".relay/queue/{slug}.json"] = text
        self.write_commit(path, files, "start")
        return path

    def write_commit(self, repo, files, message):
        for rel, text in files.items():
            full = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as handle:
                handle.write(text)
            git(repo, "add", rel)
        git(repo, "commit", "-q", "-m", message)

    def worktree(self, name):
        path = os.path.join(self.tmp, name)
        git(self.main, "worktree", "add", "-q", "-b", "wt/" + name, path)
        return path

    def item(self, slug, rev="master", sub=""):
        out = git(self.main, "show", f"{rev}:.relay/queue/{sub}{slug}.json", check=False)
        return rq.parse(slug, out) if out else None

    def branches(self):
        return [b for b in git(self.main, "for-each-ref", "--format=%(refname:short)", "refs/heads/wt/queue-*").split("\n") if b]

    def pair(self, fa, fb):
        """Run two callables at once; returns their results, or the exception each raised."""
        out = [None, None]

        def run(i, fn):
            try:
                out[i] = fn()
            except Exception as exc:  # noqa: BLE001  (the test reports what each session saw)
                out[i] = exc
        threads = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate((fa, fb))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
            self.assertFalse(t.is_alive(), "a session hung")
        return out

    def barrier(self):
        gate = threading.Barrier(2, timeout=30)

        def hook(n, plan):
            if n == 0:
                gate.wait()
        return hook


class TestOrderAndParse(Base):
    def test_q1_order_ip_then_found_then_slug(self):
        # ip 90 first; the three at ip 50 go older `found_at` first (b, c on 2026-10-01 by slug, then a on 2026-10-02)
        items = [rq.parse(s, t) for s, t in {
            "a": feature_item(ip=50, found="2026-10-02T00:00:00Z"), "c": feature_item(ip=50, found="2026-10-01T00:00:00Z"),
            "b": feature_item(ip=50, found="2026-10-01T00:00:00Z"), "d": fix_item(ip=90)}.items()]
        self.assertEqual([i["slug"] for i in rq.ordered(items)], ["d", "b", "c", "a"])

    def test_q1_cli_list_in_that_order(self):
        repo = self.repo("cli", items={"low": feature_item(ip=5), "high": fix_item(ip=80)})
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", "-C", repo],
                              capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=ROOT))
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.strip().split("\n")
        self.assertEqual(lines[0].split(), ["ip", "kind", "time", "what", "name"])   # the header names the columns
        self.assertEqual([line.split()[-1] for line in lines[1:]], ["high", "low"])   # the name is the last word

    def test_q2_fix_without_failing_case_refused_and_shown_malformed(self):
        before = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "fix", "No case", why="w", minutes=5, **QUIET)
        self.assertIn("failing case", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)       # nothing was written
        bad = raw_item(fix_item("Bad"), failing_case=[])   # a fix whose failing case is empty (written by hand: the library refuses to)
        self.write_commit(self.main, {".relay/queue/bad.json": bad}, "bad item")
        lines = rq.list_lines(rq.read_queue(self.main))
        self.assertEqual(len(lines), 1)
        self.assertIn("malformed", lines[0])
        self.assertEqual(rq.count_text(rq.read_queue(self.main)), "0 fix, 0 feature")   # a malformed item is not counted as open

    def review_data(self, name="review", findings=None, **extra):
        """A review as `relay check record review` stores it: <name>.json; returns its path."""
        data = {"schema": 1, "type": "review", "reviewed": "a" * 40, "base": "master", "findings": findings}
        data.update(extra)
        report = os.path.join(self.tmp, name + ".json")
        with open(report, "w") as handle:
            json.dump(data, handle)
        return report

    def test_q3_add_from_the_recorded_review_copies_the_finding(self):
        other = {"id": "F2", "path": "lib/other.py", "line": 9, "severity": "LOW", "rank": "low", "kind": "inside",
                 "summary": "something else", "failing_case": ["not this one"]}
        wanted = {"id": "F7", "path": "lib/relay_inert.py", "line": 51, "severity": "MEDIUM", "rank": "medium", "kind": "outside",
                  "summary": "a merge commit lists master's files", "failing_case": ["merge master into a branch;", "  changed() lists 3 files"]}
        report = self.review_data(findings=[other, wanted])
        message = rq.add_from(self.main, report, "F7", why="the gate runs on the wrong files", minutes=25, now="2026-10-22T08:30:00Z", **QUIET)
        self.assertIn("queued a-merge-commit-lists-master-s-files (fix, ip 1)", message)
        item = self.item("a-merge-commit-lists-master-s-files")
        self.assertEqual((item["kind"], item["state"], item["ip"], item["time"]), ("fix", "open", 1, 25))
        self.assertEqual((item["found_at"], item["found_in"]), ("2026-10-22T08:30:00Z", "finding F7 of review.json"))
        self.assertEqual(item["where"], "lib/relay_inert.py:51")
        self.assertEqual(item["title"], "A merge commit lists master's files")
        # the linter line is built by relay_verdict.linter: path:line: SEVERITY: id summary
        self.assertEqual(item["what"], ["lib/relay_inert.py:51: MEDIUM: F7 a merge commit lists master's files"])
        self.assertEqual(item["failing_case"], ["merge master into a branch;", "  changed() lists 3 files"])   # lines kept, indent too
        self.assertEqual(item["why"], ["the gate runs on the wrong files"])
        self.assertNotIn("not this one", json.dumps(item))
        with self.assertRaises(rq.Refused) as ctx:
            rq.add_from(self.main, report, "F9", why="w", minutes=5, **QUIET)
        self.assertIn("no finding F9", str(ctx.exception))

    def test_f4_add_from_copies_the_findings_pass_cases_and_q1_carries_them(self):
        both = {"id": "F1", "path": "lib/q.py", "line": 4, "severity": "LOW", "rank": "low", "kind": "outside", "summary": "the thing breaks",
                "failing_case": ["call c()"], "pass_cases": ["call c(), get d", "call e(), get f"]}
        none = dict(both, id="F2", summary="the other thing breaks")
        del none["pass_cases"]
        report = self.review_data(findings=[both, none])
        rq.add_from(self.main, report, "F1", why="w", minutes=5, **QUIET)
        rq.add_from(self.main, report, "F2", why="w", minutes=5, **QUIET)
        self.assertEqual(self.item("the-thing-breaks")["pass_cases"], ["call c(), get d", "call e(), get f"])
        self.assertNotIn("pass_cases", self.item("the-other-thing-breaks"))          # without the key, as before
        wa = self.worktree("w4")
        rq.take(wa, "the-thing-breaks", **QUIET)
        self.assertEqual(rq.record_item(wa)[1]["pass_cases"], ["call c(), get d", "call e(), get f"])

    def test_title_under_60_and_a_long_summary_is_cut_at_a_word(self):
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "feature", "A" + " word" * 12, why="w", minutes=5, **QUIET)   # 61 characters
        self.assertIn("under 60 characters", str(ctx.exception))
        long = {"id": "F1", "path": "lib/q.py", "line": 4, "severity": "LOW", "rank": "low", "kind": "outside",
                "summary": "queue add --from takes a summary longer than sixty characters and still queues it", "failing_case": ["x"]}
        rq.add_from(self.main, self.review_data(findings=[long]), "F1", why="w", minutes=5, **QUIET)
        titles = [i["title"] for i in rq.read_queue(self.main)]
        # 58 characters taken, cut back to the last space: "Queue add --from takes a summary longer than sixty" + ellipsis
        self.assertEqual(titles, ["Queue add --from takes a summary longer than sixty…"])

    def test_q3_add_from_a_checks_new_finding_and_a_flows_own_severity_word(self):
        new = {"id": "N1", "path": "lib/x.py", "line": 3, "severity": "BLOCKER", "rank": "high", "kind": "inside",
               "summary": "drops a row on empty input", "failing_case": ["a=1 gives none"]}
        check = {"schema": 2, "type": "check", "head": "b" * 40, "branch": "wt/x", "item": None, "gate": None, "worktree": "/w",
                 "findings": [dict(new, source="check", since="a" * 40, verdict="NOT MET", reason=[])]}
        report = os.path.join(self.tmp, "chk.json")
        with open(report, "w") as handle:
            json.dump(check, handle)
        rq.add_from(self.main, report, "N1", why="w", minutes=5, **QUIET)
        self.assertEqual(self.item("drops-a-row-on-empty-input")["what"], ["lib/x.py:3: BLOCKER: N1 drops a row on empty input"])

    def test_q3_add_from_refuses_a_missing_or_broken_json_naming_the_file(self):
        missing = os.path.join(self.tmp, "none.json")
        before = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add_from(self.main, missing, "F1", why="w", minutes=5, **QUIET)
        self.assertIn("no recorded findings at " + missing, str(ctx.exception))
        broken = os.path.join(self.tmp, "broken.json")
        with open(broken, "w") as handle:
            handle.write("{")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add_from(self.main, broken, "F1", why="w", minutes=5, **QUIET)
        self.assertIn("is not JSON", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)

    def test_q4_count_ignores_done_taken_and_other_branches(self):
        # open: one fix (ip 80, 30m), one feature; ignored: a done item, a taken one, an item only on a branch
        repo = self.repo("c", items={"f1": fix_item(ip=80, size=30), "ft": feature_item(ip=3),
                                     "tk": with_fields(fix_item(ip=99), **taken_fields())})
        self.write_commit(repo, {".relay/queue/done/old.json": with_fields(fix_item(ip=95), **taken_fields(), closed_at=CLOSED_AT, test="t.py::t")}, "done item")
        git(repo, "checkout", "-q", "-b", "wt/side")
        self.write_commit(repo, {".relay/queue/side.json": fix_item(ip=100)}, "only on a branch")
        git(repo, "checkout", "-q", "master")
        self.assertEqual(rq.count_text(rq.read_queue(repo)), "1 fix, 1 feature; top: f1 (fix, ip 80, 30m)")
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", "count", "-C", repo],
                              capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=ROOT))
        self.assertEqual(done.stdout.strip(), "1 fix, 1 feature; top: f1 (fix, ip 80, 30m)")

    def test_q5_session_line_from_a_worktree_and_nothing_without_queue(self):
        hook = os.path.join(ROOT, "plugins", "front", "hooks", "handover.py")

        def run(cwd):
            done = subprocess.run([sys.executable, hook], input=json.dumps({"source": "startup", "cwd": cwd}), capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            return json.loads(done.stdout) if done.stdout.strip() else None

        repo = self.repo("q5", items={"top": fix_item(ip=95, size=30), "ft": feature_item(ip=1)})
        wt = os.path.join(self.tmp, "q5wt")
        git(repo, "worktree", "add", "-q", "-b", "wt/q5wt", wt)
        want = "Queue: 1 fix, 1 feature; top: top (fix, ip 95, 30m). relay queue lists them."
        out = run(wt)
        self.assertIn(want, out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(out["systemMessage"], want)
        self.assertIsNone(run(self.repo("q5none", relay=False)))                 # no .relay/: nothing
        self.assertIsNone(run(self.repo("q5empty")))                              # .relay/ but no queue folder: nothing
        only_done = self.repo("q5done", items={})
        self.write_commit(only_done, {".relay/queue/x.json": with_fields(fix_item(), **taken_fields())}, "taken only")
        self.assertIsNone(run(only_done))                                          # zero open items: nothing

    def test_q8_new_fix_gets_one_more_than_top_open_feature(self):
        # open features 40 and 70; a taken feature at 90 does not count; so a fix gets 71, a feature 0
        repo = self.repo("q8", items={"fa": feature_item(ip=40), "fb": feature_item(ip=70),
                                      "fc": with_fields(feature_item(ip=90), **taken_fields())})
        rq.add(repo, "fix", "New fix", why="w", failing="f", minutes=5, **QUIET)
        self.assertEqual(rq.parse("n", git(repo, "show", "master:.relay/queue/new-fix.json"))["ip"], 71)
        rq.add(repo, "feature", "New feature", why="w", minutes=5, **QUIET)
        self.assertEqual(rq.parse("n", git(repo, "show", "master:.relay/queue/new-feature.json"))["ip"], 0)
        bare = self.repo("q8b")
        rq.add(bare, "fix", "First", why="w", failing="f", minutes=5, **QUIET)
        self.assertEqual(rq.parse("n", git(bare, "show", "master:.relay/queue/first.json"))["ip"], 1)   # no open feature: 1 + 0


class TestSchema(Base):
    """The check in lib/relay_queue.py: each rule refuses on its own."""

    def problems(self, text, slug="some-slug"):
        return rq.parse(slug, text)["problems"]

    def test_a_well_formed_item_has_no_problems(self):
        self.assertEqual(self.problems(fix_item()), [])
        self.assertEqual(self.problems(feature_item()), [])

    def test_each_rule_refuses(self):
        good = fix_item()
        cases = [
            ("unknown key", raw_item(good, color="red"), "unknown key color"),
            ("missing key", raw_item(good, drop=("why",)), "missing key why"),
            ("ip as text", raw_item(good, ip="91"), "ip is not a whole number"),
            ("ip negative", raw_item(good, ip=-1), "ip is not a whole number"),
            ("ip true is not a number", raw_item(good, ip=True), "ip is not a whole number"),
            ("time a float", raw_item(good, time=2.5), "time is not a whole number"),
            ("what as a plain string", raw_item(good, what="one line"), "what is not a list of lines"),
            ("a line that is not text", raw_item(good, why=["ok", 3]), "why is not a list of lines"),
            ("title not a string", raw_item(good, title=5), "title is not a string"),
            ("bad date", raw_item(good, found_at="22 Oct"), "found_at is not null or a UTC time"),
            ("bad kind", raw_item(good, kind="bug"), "kind is not fix or feature"),
            ("old shape: a stored state", raw_item(good, state="open"), "old shape (state)"),
            ("old shape: found and closed_by", raw_item(good, found="2026-10-01", closed_by=""), "run `relay queue migrate`"),
            ("dropped_why text", raw_item(good, dropped_why="no"), "dropped_why is not null or a list"),
            ("fix without failing_case", raw_item(good, drop=("failing_case",)), "a fix without failing_case"),
            ("fix with an empty failing_case", raw_item(good, failing_case=["  "]), "a fix without failing_case"),
            ("title equal to the slug words", raw_item(good, title="some-slug"), "title only repeats the name"),
            ("what equal to the slug words", raw_item(good, what=["some-slug"]), "what only repeats the name"),
            ("not json", "{ nope", "not valid JSON"),
            ("not an object", "[1, 2]\n", "not a JSON object"),
        ]
        for label, text, want in cases:
            found = self.problems(text)
            self.assertTrue(any(want in p for p in found), f"{label}: {found}")

    def test_a_feature_needs_no_failing_case(self):
        self.assertEqual(self.problems(raw_item(feature_item(), failing_case=[])), [])

    def test_a_malformed_item_is_only_its_name_and_reasons(self):
        item = rq.parse("x", raw_item(fix_item(), ip="no"))
        self.assertEqual(sorted(item), ["problems", "slug"])

    def test_the_library_refuses_to_write_a_bad_item(self):
        data = rq.changed(rq.parse("some-slug", fix_item()), ip=-3)
        with self.assertRaises(rq.Refused):
            rq.serialize("some-slug", data)
        with self.assertRaises(rq.Refused):
            rq.serialize("some-slug", dict(rq.changed(rq.parse("some-slug", fix_item())), surprise=1))

    def test_add_refuses_a_what_equal_to_the_slug_words(self):
        before = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "fix", "A real sentence here", what="a-real-sentence-here", why="w", failing="f", minutes=5, **QUIET)
        self.assertIn("what only repeats the name", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)


def read_ref(repo):
    """Where the tests read inert-folder text from: "HEAD^" in an inert probe commit (the probe appends a line to every
    inert file and commits it as "inert probe", so the commit before it holds the real text), else None: the checkout."""
    return "HEAD^" if git(repo, "log", "-1", "--format=%s", "HEAD", check=False) == "inert probe" else None


def show_raw(repo, ref, path):
    """The exact text of `path` at `ref` (git() strips; the working-tree read does not, so the two must agree), or None."""
    done = subprocess.run(["git", "-C", repo, "show", "%s:%s" % (ref, path)], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else None


def committed_items(repo):
    """{file name: text} of the .relay/queue items. The queue folder is inert (bin/ci's inert probe appends a line to every
    item and commits it as "inert probe"), so in a probe commit the items are read from git, from the commit before it. Anywhere
    else they are read from the working tree, the text `bin/ci --quick` loops on and the gate will read on the commit."""
    ref = read_ref(repo)
    names = git(repo, "ls-tree", "--name-only", ref, ".relay/queue/", check=False).split("\n") if ref else [""]
    if names == [""]:
        folder = os.path.join(repo, ".relay", "queue")
        return {n: open(os.path.join(folder, n), encoding="utf-8").read() for n in sorted(os.listdir(folder)) if n.endswith(".json")}
    return {os.path.basename(n): show_raw(repo, ref, n) for n in sorted(names) if n.endswith(".json")}


def committed_text(repo, path):
    """The text of `path`: the working tree's, except in an inert probe commit, where it is the commit before it (see committed_items)."""
    ref = read_ref(repo)
    out = show_raw(repo, ref, path) if ref else None
    return out if out else open(os.path.join(repo, path), encoding="utf-8").read()


def new_shape(**changes):
    """A new-shape (event-based) item file as step 2 will write it; `changes` set or replace keys."""
    data = {"kind": "feature", "ip": 0, "time": 10, "found_at": "2026-10-23T21:16:10Z", "found_in": "test",
            "title": "A new shape", "what": ["what is wanted here"], "why": ["it matters"],
            "taken_at": None, "taken_by": None, "closed_at": None, "test": None, "dropped_at": None, "dropped_why": None}
    data.update(changes)
    return json.dumps(data, indent=2) + "\n"


TAKEN = {"taken_at": "2026-10-23T21:47:35Z", "taken_by": "wt/x"}
CLOSED = dict(TAKEN, closed_at="2026-10-24T01:00:00Z", test="tests/t.py::test_x")
DROPPED = {"dropped_at": "2026-10-24T01:00:00Z", "dropped_why": ["not wanted"]}


class TestNewShape(unittest.TestCase):
    """The item shape with dated events: states computed, every rule of the check refuses on its own."""

    def parse(self, text, where=None):
        return rq.parse("some-slug", text, where)

    def test_each_of_the_four_states_is_computed_from_the_events(self):
        # open: no event; taken: taken_at; done: closed_at (and taken_at); dropped: dropped_at wins
        same_second = dict(DROPPED, dropped_at="2026-10-23T21:16:10Z")      # found_at == dropped_at is in order
        cases = [("open", {}, "open"), ("taken", TAKEN, "open"), ("done", CLOSED, "done"), ("dropped", DROPPED, "done"), ("dropped", same_second, "done")]
        for state, fields, where in cases:
            item = self.parse(new_shape(**fields), where)
            self.assertEqual((item["problems"], item["state"]), ([], state))
        taken = self.parse(new_shape(**TAKEN))
        self.assertEqual((taken["taken_by"], taken["test"]), ("wt/x", None))
        self.assertEqual(self.parse(new_shape(**CLOSED), "done")["taken_by"], "wt/x")      # taken_by stays: it is the closing branch

    def test_f2_utc_found_before_taken_across_midnight_is_accepted(self):
        # found 21:16 UTC and taken 21:47 UTC of the same day are in order; the old local-date pair was not
        self.assertEqual(self.parse(new_shape(**TAKEN))["problems"], [])

    def test_each_new_rule_refuses(self):
        cases = [
            ("taken_by without taken_at", new_shape(taken_by="wt/x"), None, "taken_by is set exactly when taken_at"),
            ("taken_at without taken_by", new_shape(taken_at=TAKEN["taken_at"]), None, "taken_by is set exactly when taken_at"),
            ("closed before taken", new_shape(**dict(CLOSED, closed_at="2026-10-23T21:00:00Z")), "done", "not in order"),
            ("found after taken", new_shape(**dict(TAKEN, found_at="2026-10-24T00:00:00Z")), None, "not in order"),
            ("test without closed_at", new_shape(test="t.py::x"), None, "a test without closed_at"),
            ("closed_at without a test", new_shape(**dict(CLOSED, test=None)), "done", "closed_at without a test"),
            ("closed_at without taken_at", new_shape(closed_at=CLOSED["closed_at"], test="t.py::x"), "done", "closed_at without taken_at"),
            ("dropped with closed", new_shape(**dict(CLOSED, **DROPPED)), "done", "dropped_at together with"),
            ("dropped_at without why", new_shape(dropped_at=DROPPED["dropped_at"]), "done", "dropped_at without dropped_why"),
            ("why without dropped_at", new_shape(dropped_why=["x"]), None, "dropped_why without dropped_at"),
            ("done/ file with no end", new_shape(), "done", "needs closed_at or dropped_at"),
            ("ended item outside done/", new_shape(**CLOSED), "open", "belongs under done/"),
            ("bad time", new_shape(found_at="2026-10-23"), None, "found_at is not null or a UTC time"),
            ("impossible time", new_shape(found_at="2026-13-45T00:00:00Z"), None, "found_at is not null or a UTC time"),
            ("found_at null", new_shape(found_at=None), None, "found_at is null"),
            ("missing key", json.dumps({k: v for k, v in json.loads(new_shape()).items() if k != "taken_at"}), None, "missing key taken_at"),
            ("dropped before found", new_shape(dropped_at="2026-10-01T00:00:00Z", dropped_why=["no"]), "done", "not in order"),
            ("taken_by empty string", new_shape(taken_by=""), None, "taken_by is null or a non-empty string"),
            ("test empty string", new_shape(test=""), None, "test is null or a non-empty string"),
            ("dropped_why empty list", new_shape(dropped_why=[]), None, "dropped_why is null or a non-empty list"),
            ("old shape keys beside the new ones", new_shape(state="open"), None, "run `relay queue migrate`"),
            ("old shape found beside found_at", new_shape(found="2026-10-23"), None, "run `relay queue migrate`"),
        ]
        for name, text, where, expected in cases:
            problems = self.parse(text, where)["problems"]
            self.assertTrue(any(expected in p for p in problems), f"{name}: {problems}")

    def test_a_whole_old_shape_file_is_refused_naming_the_migration(self):
        old = json.dumps({"kind": "feature", "state": "open", "ip": 0, "time": 10, "found": "2026-10-01", "found_in": "test", "title": "Old one here",
                          "what": ["what"], "why": ["why"], "taken_by": "", "closed_by": "", "test": "", "dropped_why": None})
        item = self.parse(old)
        self.assertEqual(sorted(item), ["problems", "slug"])
        self.assertEqual(len(item["problems"]), 1)
        self.assertIn("run `relay queue migrate`", item["problems"][0])


class TestSeedItems(unittest.TestCase):
    """Review F14 and the seed-item findings: the committed items say what is true and follow the queue rule."""

    def test_f14_every_seed_title_is_under_60_characters_and_a_one_line_text(self):
        for name, text in committed_items(ROOT).items():
            title = rq.parse(name[:-5], text)["title"]
            self.assertLess(len(title), rq.TITLE_MAX, name)
            self.assertNotIn("\n", title, name)

    def test_f14_setups_readme_text_is_relays_own_readme(self):
        import relay_setup
        self.assertEqual(relay_setup.RELAY_README, committed_text(ROOT, ".relay/README.md"))

    def test_f14_a_where_line_names_the_line_the_item_talks_about(self):
        # core-tests-not-in-gate: when the item was filed, the skip list of bin/ci was on the line `where` gives. Read at the
        # commit that first added the item (in .relay/queue/ or, once done, .relay/queue/done/), not at HEAD: the fix the
        # item asks for removes that skip, so HEAD no longer holds the line.
        name = "core-tests-not-in-gate.json"
        added = git(ROOT, "log", "--diff-filter=A", "--format=%H", "--", ".relay/queue/" + name, ".relay/queue/done/" + name).split("\n")
        self.assertTrue(added[-1], "the commit that added the item is not in the history")
        filed = added[-1]
        for folder in (".relay/queue/", ".relay/queue/done/"):
            text = git(ROOT, "show", "%s:%s%s" % (filed, folder, name), check=False)
            if text:
                break
        where = json.loads(text)["where"]          # the item as it was filed, in the shape of that commit
        path, _, line = where.rpartition(":")
        self.assertIn("*inject-addition*", git(ROOT, "show", "%s:%s" % (filed, path)).split("\n")[int(line) - 1])

    def test_f7_gate_log_summary_is_a_feature_and_not_a_fix_with_a_failing_case_that_cannot_fail(self):
        item = rq.parse("gate-log-summary", committed_items(ROOT)["gate-log-summary.json"])
        self.assertEqual((item["kind"], item["ip"]), ("feature", 0))
        self.assertNotIn("failing_case", item)

    def test_f6_the_votes_item_names_the_grader_name_prefix_that_tally_reads(self):
        # Read the item and tally.py at b176e6d, the commit that set the item's `where`, never at HEAD: the live queue is
        # inert (bin/ci's inert probe appends a line to every item), and the change the item asks for removes that regex.
        name = "eval-votes-in-file-names.json"
        text = git(ROOT, "show", "b176e6d:.relay/queue/" + name)
        path, _, line = json.loads(text)["where"].rpartition(":")
        self.assertEqual(path, "evals/judge-measure/tally.py")
        self.assertIn("(yes|no)--", git(ROOT, "show", "b176e6d:%s" % path).split("\n")[int(line) - 1])


class TestFormat(Base):
    def test_round_trip_is_byte_identical_for_every_seed_item(self):
        items = committed_items(ROOT)
        self.assertGreaterEqual(len(items), 22)
        for name, text in items.items():
            item = rq.parse(name[:-5], text)
            self.assertEqual(item["problems"], [], name)
            self.assertEqual(rq.serialize(name[:-5], item), text, name)

    def test_the_seed_items_are_read_from_before_the_inert_probe_commit(self):
        # the probe appends a line to every item and commits it: the committed items before it are what counts
        repo = self.repo("probe", items={"x": fix_item("Long one")})
        good = open(os.path.join(repo, ".relay", "queue", "x.json"), encoding="utf-8").read()
        with open(os.path.join(repo, ".relay", "queue", "x.json"), "a", encoding="utf-8") as handle:
            handle.write("inert probe line\n")
        git(repo, "commit", "-aqm", "inert probe")
        self.assertEqual(committed_items(repo), {"x.json": good})

    def test_the_file_form_is_indent_2_fixed_order_utf8_and_lines_as_arrays(self):
        item = rq.new_item("fix", 3, 5, "2026-10-01T00:00:00Z", "t", "Caf\u00e9 breaks", "first\nsecond", "why", failing="a\nb")
        text = rq.serialize("cafe", item)
        # keys in the fixed order; non-ASCII written as itself; each line its own array entry; one trailing newline
        self.assertEqual(text.split("\n")[1:3], ['  "kind": "fix",', '  "ip": 3,'])
        self.assertIn('"title": "Caf\u00e9 breaks"', text)
        self.assertIn('"what": [\n    "first",\n    "second"\n  ]', text)
        self.assertTrue(text.endswith("}\n") and not text.endswith("\n\n"))
        keys = list(json.loads(text))
        self.assertEqual(keys, [k for k in rq.ORDER if k in keys])
        self.assertEqual(keys[-1], "dropped_why")

    def test_a_changed_line_is_a_one_line_diff(self):
        repo = self.repo("diff", items={"x": fix_item("Long one")})
        rq.set_ip(repo, "x", 55, **QUIET)
        diff = git(repo, "diff", "HEAD~1", "HEAD", "-U0", "--", ".relay/queue/x.json")
        changed = [line for line in diff.split("\n") if line[:1] in "+-" and line[:3] not in ("+++", "---")]
        self.assertEqual(changed, ['-  "ip": 91,', '+  "ip": 55,'])

    def test_malformed_is_shown_not_crashed(self):
        repo = self.repo("mal", items={"good": fix_item("Good one"), "broken": "{ not json", "wrong": raw_item(feature_item(), ip="x")})
        lines = rq.list_lines(rq.read_queue(repo), header=True)
        self.assertEqual(len(lines), 4)                                           # header, the good row, two malformed ones last
        self.assertTrue(lines[-2].startswith("broken  malformed: not valid JSON"), lines)
        self.assertEqual(lines[-1], "wrong  malformed: ip is not a whole number from 0")
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", "-C", repo], capture_output=True, text=True,
                              env=dict(os.environ, RELAY_ROOT=ROOT))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("malformed: ip is not a whole number", done.stdout)
        self.assertEqual(rq.count_text(rq.read_queue(repo)), "1 fix, 0 feature; top: good (fix, ip 91, 10m)")


class TestExtensions(Base):
    def relay(self, repo, *args, cwd=None):
        return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", *args, "-C", repo], capture_output=True, text=True,
                              env=dict(os.environ, RELAY_ROOT=ROOT), cwd=cwd)

    def setUp(self):
        super().setUp()
        self.repo_q = self.repo("ext", items={"low": feature_item("Low one", ip=5), "high": fix_item("High one", ip=80)})

    def test_table_is_the_default_and_a_named_view(self):
        plain, named, flag = self.relay(self.repo_q), self.relay(self.repo_q, "table"), self.relay(self.repo_q, "--view", "table")
        for done in (plain, named, flag):
            self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(plain.stdout, named.stdout)
        self.assertEqual(plain.stdout, flag.stdout)
        self.assertEqual([x.split()[-1] for x in plain.stdout.strip().split("\n")[1:]], ["high", "low"])

    def test_json_prints_the_ordered_items_for_scripts(self):
        for args in (("json",), ("--view", "json")):
            done = self.relay(self.repo_q, *args)
            self.assertEqual(done.returncode, 0, done.stderr)
            data = json.loads(done.stdout)
            self.assertEqual([i["slug"] for i in data], ["high", "low"])         # ip 80 before ip 5
            self.assertEqual(data[0]["failing_case"], ["the case fails"])
            self.assertEqual(data[0]["ip"], 80)

    def test_an_unknown_name_lists_the_available_ones(self):
        done = self.relay(self.repo_q, "nope")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no queue view 'nope'", done.stderr)
        self.assertIn("available: json, table", done.stderr)

    def test_a_name_with_a_path_in_it_is_refused(self):
        for name in ("../table", "a/b", "..", "/etc/passwd", "table.py", "Table"):
            for args in ((name,), ("--view", name)):
                done = self.relay(self.repo_q, *args)
                self.assertNotEqual(done.returncode, 0, name)
                self.assertIn("no queue view", done.stderr, name)
        with self.assertRaises(rq.Refused):
            rq.run_extension("../table", [])

    def test_a_view_in_the_project_is_never_run(self):
        marker = os.path.join(self.tmp, "ran")
        folder = os.path.join(self.repo_q, "lib", "queue_ext")
        os.makedirs(folder)
        with open(os.path.join(folder, "evil.py"), "w") as handle:
            handle.write(f"def run(items, args):\n    open({marker!r}, 'w').close()\n    return 0\n")
        done = self.relay(self.repo_q, "evil", cwd=self.repo_q)   # run from inside the project, where the view lies
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(os.path.exists(marker))

    def test_a_view_gets_copies_and_plain_data_only(self):
        folder = os.path.join(self.tmp, "extdir")
        os.makedirs(folder)
        with open(os.path.join(folder, "meddle.py"), "w") as handle:
            handle.write("import json\n\ndef run(items, args):\n"
                         "    json.dumps(items)\n"                               # plain data: nothing callable or opaque is inside
                         "    items[0]['state'] = 'done'\n    items[0]['why'].append('tampered')\n    items.clear()\n    return 7\n")
        items = rq.read_queue(self.repo_q)
        before = json.dumps(items, sort_keys=True)
        with mock.patch.object(rq, "EXT_DIR", folder):
            self.assertEqual(rq.run_extension("meddle", items, []), 7)
        self.assertEqual(json.dumps(items, sort_keys=True), before)              # what the caller holds is unchanged
        fresh = {i["slug"]: i for i in rq.read_queue(self.repo_q)}                 # and so is the queue in git
        self.assertEqual((fresh["high"]["state"], fresh["high"]["why"]), ("open", ["it matters"]))


class TestTime(Base):
    def test_t1_format_time(self):
        # under an hour: minutes; whole hours: Nh; otherwise "Nh Mm" (125 = 2 h 5 min)
        for minutes, want in [(0, "0m"), (5, "5m"), (59, "59m"), (60, "1h"), (90, "1h 30m"), (120, "2h"), (125, "2h 5m")]:
            self.assertEqual(rq.format_time(minutes), want)

    def test_t2_parse_time_accepts_the_forms(self):
        for text, want in [("20m", 20), ("1h", 60), ("1h30m", 90), ("45", 45), ("0", 0), ("2h", 120), ("1h 30m", 90), ("2h5m", 125)]:
            self.assertEqual(rq.parse_time(text), want)

    def test_t3_parse_time_refuses_the_rest(self):
        for text in ["", "abc", "1.5h", "-5", "30 min", "m", "h", "30m1h", "1h  30m"]:
            with self.assertRaises(rq.Refused) as ctx:
                rq.parse_time(text)
            self.assertIn("1h30m", str(ctx.exception))             # the message shows the accepted forms

    def test_t5_columns_align_with_wide_times(self):
        repo = self.repo("align", items={"a": fix_item("Short one", ip=90, size=90), "bb": feature_item("Longer title", ip=5, size=20)})
        lines = rq.list_lines(rq.read_queue(repo), header=True)
        # ip is a bare number right-aligned to the header's width 2; kind pads to "feature" (7); time right-aligned to "1h 30m" (6);
        # what pads to "Longer title" (12); the name comes last. Worked by hand:
        self.assertEqual(lines, [
            " ip  kind       time  what          name",
            " 90  fix      1h 30m  Short one     a",
            "  5  feature     20m  Longer title  bb",
        ])

    def test_t6_what_is_cut_at_60_with_an_ellipsis(self):
        long61 = "x" * 61
        exact60 = "y" * 60
        repo = self.repo("cut", items={"p": fix_item(long61, ip=90), "q": feature_item(exact60, ip=5)})
        lines = rq.list_lines(rq.read_queue(repo))
        self.assertIn("x" * 59 + "\u2026  p", lines[0])      # 61 characters: 59 kept plus the ellipsis makes 60
        self.assertNotIn("x" * 60, lines[0])
        self.assertIn("y" * 60 + "  q", lines[1])             # exactly 60 stays whole

    def test_t7_add_refuses_a_title_that_is_the_slug_words(self):
        before = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "feature", "core-tests-not-in-gate", why="w", minutes=5, **QUIET)
        self.assertIn("repeats the name", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)       # nothing was written
        rq.add(self.main, "feature", "Core tests are not in the gate", why="w", minutes=5, **QUIET)   # a sentence is accepted

    def test_f13_a_lowercase_sentence_is_a_title_only_the_slug_typed_is_refused(self):
        # review F13: "tally crashes on bad input" is a sentence, though its slug words are the same words
        rq.add(self.main, "fix", "tally crashes on bad input", why="w", failing="f", minutes=5, **QUIET)
        item = self.item("tally-crashes-on-bad-input")
        self.assertEqual(item["title"], "tally crashes on bad input")
        self.assertEqual(rq.parse("tally-crashes-on-bad-input", git(self.main, "show", "master:.relay/queue/tally-crashes-on-bad-input.json"))["problems"], [])
        rq.add(self.main, "feature", "Tally crashes on bad input two", why="w", minutes=5, **QUIET)   # (as today: capitalised)

    def test_t4_list_row_shows_time_and_cli_size_option(self):
        repo = self.repo("time", items={"long": fix_item(size=90)})
        self.assertIn("1h 30m", rq.list_lines(rq.read_queue(repo))[0])
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", "add", "--kind", "feature", "--title", "T",
                               "--why", "w", "--time", "soon", "-C", repo],
                              capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=ROOT))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("1h30m", done.stderr)


class TestLanding(Base):
    def test_q6_add_refuses_without_relay_folder(self):
        bare = self.repo("plain", relay=False)
        before = git(bare, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(bare, "feature", "Thing", why="w", minutes=5, **QUIET)
        self.assertIn(".relay", str(ctx.exception))
        self.assertEqual(git(bare, "rev-parse", "master"), before)
        self.assertEqual(git(bare, "branch", "--list", "wt/queue-*"), "")

    def test_q6_add_from_main_and_from_a_worktree_leaves_no_trace(self):
        wt = self.worktree("w1")
        first = rq.add(self.main, "feature", "From main", why="w", minutes=5, **QUIET)
        second = rq.add(wt, "feature", "From worktree", why="w", minutes=5, **QUIET)
        head = git(self.main, "rev-parse", "master")
        self.assertIn(f"landed on master at {head}", second)                       # the full 40-character sha
        self.assertEqual(len(head), 40)
        self.assertTrue(first.startswith("queued from-main (feature, ip 0)"))
        for slug in ("from-main", "from-worktree"):
            self.assertIsNotNone(self.item(slug))
            self.assertTrue(os.path.exists(os.path.join(self.main, ".relay/queue", slug + ".json")))   # the main checkout followed
        self.assertEqual(git(wt, "status", "--porcelain"), "")                      # the worktree was not touched
        self.assertEqual(git(self.main, "status", "--porcelain"), "")
        self.assertEqual(self.branches(), [])
        self.assertEqual(git(self.main, "log", "-1", "--format=%s"), "queue: from-worktree")

    def test_q6_same_title_gets_suffix(self):
        rq.add(self.main, "feature", "Same title", why="one", minutes=5, **QUIET)
        message = rq.add(self.main, "feature", "Same title", why="two", minutes=5, **QUIET)
        self.assertIn("queued same-title-2", message)
        self.assertEqual(self.item("same-title")["why"], ["one"])
        self.assertEqual(self.item("same-title-2")["why"], ["two"])
        self.write_commit(self.main, {".relay/queue/done/other.json": with_fields(feature_item(), **taken_fields(), closed_at=CLOSED_AT, test="t.py::t")}, "done")
        rq.add(self.main, "feature", "Other", why="w", minutes=5, **QUIET)
        self.assertIsNotNone(self.item("other-2"))                                  # a name in done/ is taken too

    def test_q6_add_refused_when_main_is_not_on_default(self):
        git(self.main, "checkout", "-q", "-b", "side")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "feature", "Thing", why="w", minutes=5, **QUIET)
        self.assertIn("main checkout is not on master", str(ctx.exception))
        self.assertEqual(self.branches(), [])

    def test_q9_two_adds_from_two_worktrees_ten_rounds(self):
        w1, w2 = self.worktree("w1"), self.worktree("w2")
        for rnd in range(10):
            hook = self.barrier()
            a, b = self.pair(lambda: rq.add(w1, "feature", f"Alpha {rnd}", why="a", minutes=5, after_plan=hook, **QUIET),
                             lambda: rq.add(w2, "feature", f"Beta {rnd}", why="b", minutes=5, after_plan=hook, **QUIET))
            self.assertIsInstance(a, str, a)
            self.assertIsInstance(b, str, b)
            self.assertIsNotNone(self.item(f"alpha-{rnd}"))
            self.assertIsNotNone(self.item(f"beta-{rnd}"))
            self.assertEqual(self.branches(), [])

    def test_q9_same_title_at_once_ten_rounds(self):
        w1, w2 = self.worktree("w1"), self.worktree("w2")
        for rnd in range(10):
            title = f"Twin {rnd}"
            hook = self.barrier()
            a, b = self.pair(lambda: rq.add(w1, "feature", title, why=f"text-a-{rnd}", minutes=5, after_plan=hook, **QUIET),
                             lambda: rq.add(w2, "feature", title, why=f"text-b-{rnd}", minutes=5, after_plan=hook, **QUIET))
            self.assertIsInstance(a, str, a)
            self.assertIsInstance(b, str, b)
            slug = f"twin-{rnd}"
            bodies = " ".join(self.item(slug)["why"] + self.item(slug + "-2")["why"])
            self.assertIn(f"text-a-{rnd}", bodies)                                  # both texts intact, one in each file
            self.assertIn(f"text-b-{rnd}", bodies)
            self.assertEqual(self.branches(), [])

    def test_q9_lands_after_an_index_lock_is_released(self):
        lock = os.path.join(self.main, ".git", "index.lock")
        open(lock, "w").close()
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            if len(slept) == 3 and os.path.exists(lock):    # the lock holder lets go during the third wait
                os.remove(lock)
        message = rq.add(self.main, "feature", "Locked", why="w", minutes=5, sleep=sleep)
        self.assertIn("queued locked", message)
        self.assertEqual(len(slept), 3)                                              # tries 1-3 met the lock; the fourth landed
        self.assertTrue(all(0.2 <= s <= 1 for s in slept), slept)                    # design 10.4: 0.2-1 s between tries
        self.assertEqual(self.branches(), [])

    def test_q9_one_try_and_a_moved_head_keeps_the_branch_and_land_finishes_it(self):
        def move_head(n, plan):
            self.write_commit(self.main, {"other.txt": "moved\n"}, "head moves")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "feature", "Slow", why="w", minutes=5, tries=1, after_plan=move_head, **QUIET)
        self.assertIn("not landed after 1 tries", str(ctx.exception))
        self.assertIn("kept on wt/queue-slow", str(ctx.exception))
        self.assertIn("relay queue land slow", str(ctx.exception))
        self.assertEqual(self.branches(), ["wt/queue-slow"])
        self.assertIsNone(self.item("slow"))
        # while the branch is left, an add of that title takes the next suffix
        rq.add(self.main, "feature", "Slow", why="second", minutes=5, **QUIET)
        self.assertIsNotNone(self.item("slow-2"))
        self.assertIn("landed on master", rq.land(self.main, "slow", **QUIET))
        self.assertIsNotNone(self.item("slow"))
        self.assertEqual(self.branches(), [])
        self.assertTrue(os.path.exists(os.path.join(self.main, "other.txt")))        # the moved head stayed

    def test_q9_land_refused_when_the_file_no_longer_holds(self):
        rq.add(self.main, "feature", "Gone", why="w", minutes=5, **QUIET)
        text = self.item("gone")

        def move_head(n, plan):
            self.write_commit(self.main, {".relay/queue/late.json": feature_item()}, "head moves")
        with self.assertRaises(rq.Refused):
            rq.add(self.main, "feature", "Late", why="w", minutes=5, tries=1, after_plan=move_head, **QUIET)
        # a kept `late` branch would add late.json, which now exists on master with other content: it no longer holds
        with self.assertRaises(rq.Refused) as ctx:
            rq.land(self.main, "late", **QUIET)
        self.assertIn("no longer holds", str(ctx.exception))
        self.assertEqual(self.branches(), ["wt/queue-late"])
        self.assertIsNotNone(text)

    def test_q9_a_second_file_is_refused_and_the_branch_deleted(self):
        before = git(self.main, "rev-parse", "master")

        def planner(reader):
            plan = rq.Plan("sneaky", {".relay/queue/sneaky.json": feature_item(), "README.md": "changed\n"}, "feature, ip 0", "queued")
            plan.allowed = {".relay/queue/sneaky.json"}      # what the command may touch: the one item file
            return plan
        with self.assertRaises(rq.Refused) as ctx:
            rq._land(self.main, planner, **QUIET)
        self.assertIn("beyond the one allowed file", str(ctx.exception))
        self.assertEqual(self.branches(), [])
        self.assertEqual(git(self.main, "rev-parse", "master"), before)


class TestTake(Base):
    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {".relay/queue/job.json": fix_item("Job", ip=60, failing="line 1\nline 2"),
                                      ".relay/queue/feat.json": feature_item("Feat", ip=20)}, "seed")
        self.wa, self.wb = self.worktree("a"), self.worktree("b")

    def test_q10_take_lands_taken_on_default_and_the_check_states_the_item_as_q1(self):
        with mock.patch.object(rq, "utcnow", return_value="2026-10-05T12:00:00Z"):
            out = rq.take(self.wa, "job", **QUIET)
        self.assertIn("taken job (fix, ip 60), landed on master at " + git(self.main, "rev-parse", "master"), out)
        item = self.item("job")
        # take writes taken_at (the time then, UTC) and taken_by; no stored state: it is computed from taken_at
        self.assertEqual((item["state"], item["taken_at"], item["taken_by"]), ("taken", "2026-10-05T12:00:00Z", "wt/a"))
        self.assertNotIn("state", json.loads(git(self.main, "show", "master:.relay/queue/job.json")))
        self.assertEqual(rq.count_text(rq.read_queue(self.main)), "0 fix, 1 feature; top: feat (feature, ip 20, 10m)")
        self.assertEqual(self.branches(), [])
        # the worktree branch now holds the taken state (a fast-forward of a fresh worktree)
        self.assertEqual(git(self.wa, "rev-parse", "HEAD"), git(self.main, "rev-parse", "master"))
        slug, q1 = rq.record_item(self.wa)               # take writes no findings file: the check states the item's problem as Q1
        self.assertEqual(slug, "job")
        self.assertEqual(q1["since"], git(self.main, "rev-parse", "master"))      # stated at the commit that landed `taken`
        # one finding Q1 built from the item (fix_item: where lib/x.py:5, failing "line 1\nline 2", pass case, why "it matters")
        self.assertEqual((q1["id"], q1["path"], q1["line"], q1["severity"], q1["kind"], q1["summary"]), ("Q1", "lib/x.py", 5, "HIGH", "inside", "Job"))
        self.assertEqual(q1["failing_case"], ["line 1", "line 2"])
        self.assertEqual(q1["pass_cases"], ["the other case"])
        self.assertEqual(q1["details"], ["it matters"])
        self.assertEqual(rv.linter(q1), "lib/x.py:5: HIGH: Q1 Job")

    def test_q10_second_take_from_another_worktree_is_refused(self):
        rq.take(self.wa, "job", **QUIET)
        with self.assertRaises(rq.Refused) as ctx:
            rq.take(self.wb, "job", **QUIET)
        self.assertIn("taken by wt/a", str(ctx.exception))

    def test_q10_two_takes_started_together_exactly_one_lands(self):
        for rnd in range(10):
            slug = f"race{rnd}"
            self.write_commit(self.main, {f".relay/queue/{slug}.json": feature_item(f"Race item {slug}")}, "item")
            for wt in (self.wa, self.wb):                  # worktrees follow master so the take's merge is a fast-forward
                git(wt, "merge", "-q", "--no-edit", "master")
            hook = self.barrier()
            a, b = self.pair(lambda: rq.take(self.wa, slug, after_plan=hook, **QUIET),
                             lambda: rq.take(self.wb, slug, after_plan=hook, **QUIET))
            winners = [r for r in (a, b) if isinstance(r, str)]
            losers = [r for r in (a, b) if isinstance(r, rq.Refused)]
            self.assertEqual((len(winners), len(losers)), (1, 1), (a, b))
            first = "wt/a" if isinstance(a, str) else "wt/b"
            self.assertIn(f"taken by {first}", str(losers[0]))
            self.assertEqual(self.item(slug)["taken_by"], first)
            self.assertEqual(self.branches(), [])

    def test_q10_ip_racing_a_take_never_edits_a_taken_item(self):
        for rnd in range(10):
            slug = f"ipr{rnd}"
            self.write_commit(self.main, {f".relay/queue/{slug}.json": feature_item(f"Ipr item {slug}", ip=60)}, "item")
            git(self.wa, "merge", "-q", "--no-edit", "master")
            hook = self.barrier()
            took, changed = self.pair(lambda: rq.take(self.wa, slug, after_plan=hook, **QUIET),
                                      lambda: rq.set_ip(self.main, slug, 50, after_plan=hook, **QUIET))
            self.assertIsInstance(took, str, took)
            states = []                                     # the item's history on master, oldest first
            for sha in git(self.main, "log", "--reverse", "--format=%H", "--", f".relay/queue/{slug}.json").split("\n"):
                states.append(rq.parse(slug, git(self.main, "show", f"{sha}:.relay/queue/{slug}.json")))
            self.assertEqual(states[-1]["state"], "taken")
            if isinstance(changed, str):                    # both landed: the ip change came while the item was still open
                self.assertEqual([s["state"] for s in states], ["open", "open", "taken"])
                self.assertEqual(states[-1]["ip"], 50)
            else:
                self.assertIn("taken by wt/a", str(changed))
                self.assertEqual([s["state"] for s in states], ["open", "taken"])
                self.assertEqual(states[-1]["ip"], 60)

    def test_q10_ip_and_drop_refuse_a_taken_item_and_release_opens_it(self):
        rq.take(self.wa, "job", **QUIET)
        head = git(self.main, "rev-parse", "master")
        for call in (lambda: rq.set_ip(self.main, "job", 5, **QUIET), lambda: rq.drop(self.main, "job", "no longer wanted", **QUIET)):
            with self.assertRaises(rq.Refused) as ctx:
                call()
            self.assertIn("taken by wt/a; release it first", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), head)
        with self.assertRaises(rq.Refused):
            rq.release(self.main, "feat", **QUIET)                                   # not taken: nothing to release
        rq.release(self.main, "job", **QUIET)
        item = self.item("job")
        # release clears both take fields: an earlier take is not kept
        self.assertEqual((item["state"], item["taken_at"], item["taken_by"]), ("open", None, None))
        with mock.patch.object(rq, "utcnow", return_value="2026-10-06T08:00:00Z"):
            rq.drop(self.main, "feat", "the owner said drop it", **QUIET)
        self.assertIsNone(self.item("feat"))
        dropped = self.item("feat", sub="done/")
        self.assertEqual((dropped["state"], dropped["dropped_at"], dropped["taken_at"]), ("dropped", "2026-10-06T08:00:00Z", None))
        self.assertEqual(dropped["dropped_why"], ["the owner said drop it"])

    def checked(self, verdict="MET", item="job", ids=("Q1",)):
        """A check mark for the commit wt/a is at, as the hook commits it, with these ids at this verdict in its record."""
        head = git(self.wa, "rev-parse", "HEAD")
        findings = [{"id": i, "path": "lib/x.py", "line": 5, "severity": "HIGH", "rank": "high", "kind": "inside", "summary": "Job",
                     "failing_case": ["line 1"], "source": "queue", "since": head, "verdict": verdict, "reason": ["tests/test_job.py:1"]} for i in ids]
        record = {"schema": 2, "type": "check", "head": head, "branch": "wt/a", "item": item, "gate": None, "scope": [], "notes": [], "findings": findings}
        mark = {"schema": 2, "commit": head, "verdict": {"open": 0, "queued": 0}, "check": head + ".check.json", "gate": None, "time": "t"}
        relay_marks.put(self.wa, head, mark, {head + ".check.json": json.dumps(record) + "\n"})

    def test_q10_writers_refuse_an_old_shape_item_naming_the_migration_and_change_nothing(self):
        # a branch started before the migration can carry an item with `state`; no writer may rewrite it
        old = json.dumps({"kind": "feature", "state": "open", "ip": 0, "time": 10, "found": "2026-10-01", "found_in": "test", "title": "Old item here",
                          "what": ["what"], "why": ["why"], "taken_by": "", "closed_by": "", "test": "", "dropped_why": None})
        self.write_commit(self.main, {".relay/queue/old.json": old + "\n"}, "an old-shape item")
        head = git(self.main, "rev-parse", "master")
        for name, call in (("set_ip", lambda: rq.set_ip(self.main, "old", 5, **QUIET)),
                           ("drop", lambda: rq.drop(self.main, "old", "no longer wanted", **QUIET)),
                           ("release", lambda: rq.release(self.main, "old", **QUIET)),
                           ("take", lambda: rq.take(self.wa, "old", **QUIET))):
            with self.assertRaises(rq.Refused, msg=name) as ctx:
                call()
            self.assertIn("run `relay queue migrate`", str(ctx.exception), name)
            self.assertEqual(git(self.main, "rev-parse", "master"), head, name)
        # done: the item taken by this branch is still in the old shape
        taken = json.loads(old)
        taken.update(state="taken", taken_by="wt/a")
        self.write_commit(self.wa, {".relay/queue/old.json": json.dumps(taken) + "\n", "tests/test_old.py": "def test_old():\n    pass\n"}, "taken, old shape")
        with self.assertRaises(rq.Refused) as ctx:
            rq.done(self.wa, "old", "tests/test_old.py::test_old")
        self.assertIn("run `relay queue migrate`", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.wa, ".relay", "queue", "done", "old.json")))

    def test_f7_land_of_a_kept_old_shape_branch_is_refused_naming_the_migration(self):
        old = json.dumps({"kind": "feature", "state": "open", "ip": 0, "time": 10, "found": "2026-10-01", "found_in": "test", "title": "Kept old one",
                          "what": ["what"], "why": ["why"], "taken_by": "", "closed_by": "", "test": "", "dropped_why": None})
        git(self.main, "branch", "wt/queue-kept", "master")
        git(self.main, "worktree", "add", "-q", os.path.join(self.tmp, "kept"), "wt/queue-kept")
        self.write_commit(os.path.join(self.tmp, "kept"), {".relay/queue/kept.json": old + "\n"}, "queue: kept")
        git(self.main, "worktree", "remove", "--force", os.path.join(self.tmp, "kept"))
        head = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.land(self.main, "kept", **QUIET)
        self.assertIn("run `relay queue migrate`", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), head)

    def test_done_writes_closed_at_and_keeps_the_taking_branch(self):
        with mock.patch.object(rq, "utcnow", return_value="2026-10-05T12:00:00Z"):
            rq.take(self.wa, "job", **QUIET)
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "the fix and its test")
        self.checked()
        with mock.patch.object(rq, "utcnow", return_value="2026-10-05T13:30:00Z"):
            rq.done(self.wa, "job", "tests/test_job.py::test_job_works")
        data = json.loads(git(self.wa, "show", "HEAD:.relay/queue/done/job.json"))
        self.assertEqual((data["taken_at"], data["taken_by"], data["closed_at"], data["test"]),
                         ("2026-10-05T12:00:00Z", "wt/a", "2026-10-05T13:30:00Z", "tests/test_job.py::test_job_works"))
        self.assertTrue(set(data).isdisjoint(rq.OLD_ONLY))

    def test_q10_later_done_on_the_task_branch_merges_without_conflict(self):
        rq.take(self.wa, "job", **QUIET)
        rq.add(self.main, "feature", "Meanwhile", why="w", minutes=5, **QUIET)        # master moves on
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "the fix and its test")
        self.checked()
        message = rq.done(self.wa, "job", "tests/test_job.py::test_job_works")
        self.assertIn("closed job", message)
        self.assertEqual(git(self.wa, "log", "-1", "--format=%s"), "queue: done job")
        self.assertEqual(git(self.wa, "status", "--porcelain"), "")
        self.assertEqual(self.item("job")["state"], "taken")                         # master changes only when the branch merges
        git(self.main, "merge", "-q", "--no-edit", "wt/a")                           # no conflict
        self.assertIsNone(self.item("job"))
        closed = self.item("job", sub="done/")
        self.assertEqual((closed["state"], closed["taken_by"], closed["test"]),
                         ("done", "wt/a", "tests/test_job.py::test_job_works"))
        self.assertIsNotNone(self.item("meanwhile"))

    def test_q7_done_refusals(self):
        rq.take(self.wa, "job", **QUIET)
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "test")
        self.checked()
        head = git(self.wa, "rev-parse", "HEAD")
        cases = [("", "--test"),                                                    # no --test
                 ("tests/test_job.py::test_other", "does not hold a test named"),   # a name the file lacks
                 ("tests/missing.py::test_job_works", "is not in the last commit")]
        for test, expect in cases:
            with self.assertRaises(rq.Refused, msg=test) as ctx:
                rq.done(self.wa, "job", test)
            self.assertIn(expect, str(ctx.exception))
            self.assertEqual(git(self.wa, "rev-parse", "HEAD"), head)               # nothing committed
        git(self.wb, "merge", "-q", "--no-edit", "master")                           # wt/b sees the item, but wt/a took it
        self.write_commit(self.wb, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "test")
        with self.assertRaises(rq.Refused) as ctx:
            rq.done(self.wb, "job", "tests/test_job.py::test_job_works")
        self.assertIn("not taken by wt/b", str(ctx.exception))

    def test_done_reads_the_record_of_the_branchs_newest_check_for_q1(self):
        """A fix closes only when the branch's newest check, with no own file changed since it, has Q1 MET: no check, Q1 NOT MET
        and a record with no verdict for Q1 are refused with the reason and commit nothing; Q1 MET is accepted."""
        rq.take(self.wa, "job", **QUIET)
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "test")
        test = "tests/test_job.py::test_job_works"
        head = git(self.wa, "rev-parse", "HEAD")
        with self.assertRaises(rq.Refused) as ctx:
            rq.done(self.wa, "job", test)
        self.assertIn("no check of this fix", str(ctx.exception))
        for make, expect in ((lambda: self.checked("NOT MET"), "says Q1 NOT MET, not MET"), (lambda: self.checked(ids=("F2",)), "gives no verdict for Q1")):
            make()
            with self.assertRaises(rq.Refused, msg=expect) as ctx:
                rq.done(self.wa, "job", test)
            self.assertIn(expect, str(ctx.exception))
        self.assertEqual(git(self.wa, "diff", "--name-only", head, "HEAD").count("\n") + 1, 4)       # only the marks and records were committed
        self.checked()
        self.assertIn("closed job", rq.done(self.wa, "job", test))

    def test_f3_done_refuses_a_check_that_is_not_of_this_fix_or_not_of_this_code(self):
        """Review F3: Q1 MET in a check of another item, or of code changed since, closes nothing."""
        rq.take(self.wa, "job", **QUIET)
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "test")
        test = "tests/test_job.py::test_job_works"
        self.checked(item="another-thing")
        with self.assertRaises(rq.Refused) as ctx:
            rq.done(self.wa, "job", test)
        self.assertIn("is of another-thing, not of 'job'", str(ctx.exception))
        self.write_commit(self.wa, {"lib/x.py": "changed\n"}, "code after the check")
        with self.assertRaises(rq.Refused) as ctx:
            rq.done(self.wa, "job", test)
        self.assertIn("lib/x.py changed", str(ctx.exception))
        self.checked()                                                           # the check of this branch's own Q1, at this code
        self.assertIn("closed job", rq.done(self.wa, "job", test))

    def test_f3_a_check_from_before_a_queue_only_commit_still_closes(self):
        rq.take(self.wa, "job", **QUIET)
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "test")
        self.checked()
        self.write_commit(self.wa, {".relay/queue/zzz-note.json": feature_item("Zzz note")}, "a queue-only commit")
        self.assertIn("closed job", rq.done(self.wa, "job", "tests/test_job.py::test_job_works"))

    def test_f15_done_wants_the_test_name_whole(self):
        rq.take(self.wa, "job", **QUIET)
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works_twice():\n    pass\n"}, "test")
        with self.assertRaises(rq.Refused) as ctx:                                  # the file holds test_job_works_twice only
            rq.done(self.wa, "job", "tests/test_job.py::test_job_works")
        self.assertIn("does not hold a test named test_job_works", str(ctx.exception))
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works_twice():\n    pass\n\n\nclass T:\n    def test_job_works(self):\n        pass\n"}, "t2")
        self.checked()
        self.assertIn("closed job", rq.done(self.wa, "job", "tests/test_job.py::T::test_job_works"))

    def test_f2_take_refuses_before_landing_when_q1_cannot_be_built(self):
        """Review F2: an item whose title cannot be a one-line summary is not left taken with no findings."""
        text = raw_item(fix_item("Two lines"), title="Two\nlines title")             # a file as a bad merge could leave it
        self.write_commit(self.main, {".relay/queue/two-lines-title.json": text}, "bad title")
        git(self.wa, "merge", "-q", "--no-edit", "master")
        # the file is malformed to the reader, so take refuses it; and `add` refuses to create one (the finding's failing case)
        before = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused):
            rq.take(self.wa, "two-lines-title", **QUIET)
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "fix", "Two\nlines title", why="w", failing="f", minutes=5, **QUIET)
        self.assertIn("one line", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)
        self.assertEqual(self.item("job")["state"], "open")

    def test_f2_take_builds_q1_in_the_planner_before_the_landing(self):
        # the guard is the planner's call of finding_errors: with Q1 unwritable (here by patching _q1 to give a two-line summary)
        # nothing lands and the item stays open
        before = git(self.main, "rev-parse", "master")
        real = rq._q1
        with mock.patch.object(rq, "_q1", lambda item: dict(real(item), summary="a\nb")):
            with self.assertRaises(rq.Refused) as ctx:
                rq.take(self.wa, "job", **QUIET)
        self.assertIn("cannot become finding Q1, nothing taken", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)
        self.assertEqual(self.item("job")["state"], "open")

    def test_f12_ip_to_its_own_value_is_a_plain_refusal(self):
        before = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:                                  # feat has ip 20
            rq.set_ip(self.main, "feat", 20, **QUIET)
        self.assertIn("already has ip 20", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)
        self.assertEqual(self.branches(), [])
        rq.set_ip(self.main, "feat", 21, **QUIET)                                   # a new value lands
        self.assertEqual(self.item("feat")["ip"], 21)


class TestInputFile(Base):
    """`relay queue add --input <file.toml>`: free text reaches the item through a file, never through the shell."""

    def run_relay(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", *args], capture_output=True, text=True,
                              env=dict(os.environ, RELAY_ROOT=ROOT))

    def toml(self, text, name="in.toml"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    # text a shell would change: a variable, backticks, a command substitution, both quotes, a backslash, indentation, a blank line
    TRICKY = 'costs $TMPDIR and `rm -rf x` and $(whoami)\n  "double" and \'single\' with a \\ backslash\n\nlast line  '

    def test_text_with_shell_characters_is_stored_byte_identical(self):
        # in the TOML a literal multi-line string (three single quotes) keeps every character; the lines are stored as given
        # (blank lines at the edges dropped), so joining them by newline gives the text again
        why = self.TRICKY.replace("'single'", "single")          # a literal string cannot hold three quotes in a row; one is fine, but keep it simple
        path = self.toml("title = 'Shell text survives'\ntime = '1h30m'\nwhy = \'\'\'\n" + why + "\n\'\'\'\nwhat = \'\'\'\nthe `what` line\n\'\'\'\n")
        done = self.run_relay("add", "--input", path, "-C", self.main)
        self.assertEqual(done.returncode, 0, done.stderr)
        item = self.item("shell-text-survives")
        self.assertEqual("\n".join(item["why"]), why)
        self.assertEqual(item["what"], ["the `what` line"])
        self.assertEqual(item["time"], 90)
        self.assertEqual(item["kind"], "feature")

    def test_each_refusal_names_the_key_and_queues_nothing(self):
        before = git(self.main, "rev-parse", "master")
        cases = [("title = 'T'\nwhy = 'w'\ntime = '5m'\ncolour = 'red'\n", "unknown key `colour`"),
                 ("title = 'T'\nwhy = 'w'\n", "missing required key `time`"),
                 ("why = 'w'\ntime = '5m'\n", "missing required key `title`"),
                 ("title = 'T'\nwhy = 'w'\ntime = 'soon'\n", "`time` must be"),
                 ("title = 'T'\nwhy = 'w'\ntime = '5m'\nip = 'high'\n", "`ip` must be a whole number"),
                 ("title = 'T'\nwhy = 'w'\ntime = '5m'\nwhat = 3\n", "`what` in the input must be a text"),
                 ("title = (\n", "not valid TOML")]
        for text, expect in cases:
            done = self.run_relay("add", "--input", self.toml(text), "-C", self.main)
            self.assertEqual(done.returncode, 2, text)
            self.assertIn(expect, done.stderr)
        both = self.run_relay("add", "--input", self.toml("title = 'T'\nwhy = 'w'\ntime = '5m'\n"), "--time", "10m", "-C", self.main)
        self.assertIn("--time is given in the input file and on the command line", both.stderr)
        self.assertNotEqual(self.run_relay("add", "--title", "T", "--why", "w", "--time", "5m", "-C", self.main).returncode, 0)   # free-text flags are gone
        self.assertEqual(git(self.main, "rev-parse", "master"), before)

    def test_add_from_a_recorded_finding_takes_why_and_time_from_the_input(self):
        report = os.path.join(self.tmp, "rev.json")
        with open(report, "w") as handle:
            json.dump({"schema": 1, "type": "review", "reviewed": "a" * 40, "base": "master", "findings": [
                {"id": "F3", "path": "lib/q.py", "line": 4, "severity": "LOW", "rank": "low", "kind": "outside", "summary": "a thing is off",
                 "failing_case": ["x gives y"]}]}, handle)
        done = self.run_relay("add", "--from", report, "F3", "--input", self.toml("why = 'it matters'\ntime = '20m'\n"), "--ip", "7", "-C", self.main)
        self.assertEqual(done.returncode, 0, done.stderr)
        item = self.item("a-thing-is-off")
        self.assertEqual((item["why"], item["time"], item["ip"], item["where"]), (["it matters"], 20, 7, "lib/q.py:4"))

    def test_f5_drop_takes_the_owners_words_from_a_toml_file(self):
        self.write_commit(self.main, {".relay/queue/feat.json": feature_item("Feat")}, "seed")
        words = 'owner said $HOME `date` "no"'                                # a shell would expand the first two
        path = self.toml("why = \'\'\'\n" + words + "\n\'\'\'\n", "drop.toml")
        before = git(self.main, "rev-parse", "master")
        for args in (("drop", "feat", "-C", self.main), ("drop", "feat", "--why", "x", "-C", self.main)):    # no input file, and the old flag
            done = self.run_relay(*args)
            self.assertEqual(done.returncode, 2, args)
        self.assertEqual(git(self.main, "rev-parse", "master"), before)           # nothing landed
        done = self.run_relay("drop", "feat", "--input", path, "-C", self.main)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.item("feat", sub="done/")["dropped_why"], [words])

    def test_f5_drop_of_a_taken_item_is_still_refused(self):
        self.write_commit(self.main, {".relay/queue/job.json": with_fields(fix_item("Job"), **taken_fields("wt/x"))}, "seed")
        done = self.run_relay("drop", "job", "--input", self.toml("why = 'no'\n"), "-C", self.main)
        self.assertEqual(done.returncode, 2)
        self.assertIn("taken by wt/x", done.stderr)

    def test_f11_add_from_with_kind_is_a_usage_error_and_queues_nothing(self):
        report = os.path.join(self.tmp, "rev.json")
        with open(report, "w") as handle:
            json.dump({"schema": 1, "type": "review", "reviewed": "a" * 40, "base": "master", "findings": [
                {"id": "F1", "path": "lib/q.py", "line": 4, "severity": "LOW", "rank": "low", "kind": "outside", "summary": "a thing is off",
                 "failing_case": ["x"]}]}, handle)
        before = git(self.main, "rev-parse", "master")
        done = self.run_relay("add", "--from", report, "F1", "--input", self.toml("why = 'w'\ntime = '5m'\n"), "--kind", "fix", "-C", self.main)
        self.assertEqual(done.returncode, 2)
        self.assertIn("--kind does not go with --from", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(git(self.main, "rev-parse", "master"), before)

    def test_show_prints_one_item_in_full(self):
        self.write_commit(self.main, {".relay/queue/job.json": fix_item("Job", ip=60, size=90, failing="line 1\nline 2")}, "seed")
        done = self.run_relay("show", "job", "-C", self.main)
        self.assertEqual(done.returncode, 0, done.stderr)
        # worked by hand from fix_item: slug job, title Job; fix, ip 60, 90 minutes = 1h 30m, open; found 2026-10-01 in test
        self.assertEqual(done.stdout.splitlines(), [
            "job: Job", "fix, ip 60, 1h 30m, open", "found 2026-10-01T00:00:00Z in test", "where lib/x.py:5",
            "What:", "  what is wrong here", "Why:", "  it matters", "Failing case:", "  line 1", "  line 2", "Pass cases:", "  the other case"])
        self.assertEqual(self.run_relay("show", "nope", "-C", self.main).returncode, 2)


def old_shape(title, state="open", taken_by="", closed_by="", test="", dropped_why=None, kind="feature"):
    """An item file in the shape before dated events (what the migration reads)."""
    data = {"kind": kind, "state": state, "ip": 0, "time": 10, "found": "2026-10-01", "found_in": "test", "title": title,
            "what": ["what is wanted here"], "why": ["it matters"], "taken_by": taken_by, "closed_by": closed_by, "test": test,
            "dropped_why": dropped_why}
    return json.dumps(data, indent=2) + "\n"


class TestMigrate(Base):
    """`relay queue migrate` (lib/relay_queue_migrate.py) on a scratch repository whose commits carry chosen times."""

    def commit_at(self, files, when, message="queue", remove=()):
        env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        with mock.patch.dict(os.environ, env):
            for rel in remove:
                git(self.main, "rm", "-q", rel)
            self.write_commit(self.main, files, message)

    def run_relay(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", *args], capture_output=True, text=True,
                              env=dict(os.environ, RELAY_ROOT=ROOT))

    def history(self):
        q = ".relay/queue/"
        d = ".relay/queue/done/"
        self.commit_at({q + "job.json": old_shape("Job item here")}, "2026-10-01T10:00:00Z")                      # found
        self.commit_at({q + "job.json": old_shape("Job item here", "taken", "wt/a")}, "2026-10-01T11:00:00Z")     # first take
        self.commit_at({q + "job.json": old_shape("Job item here")}, "2026-10-01T12:00:00Z")                      # released
        self.commit_at({q + "job.json": old_shape("Job item here", "taken", "wt/b")}, "2026-10-01T13:00:00Z")     # the last take
        done = old_shape("Job item here", "done", "wt/b", "wt/b", "tests/t.py::t")
        self.commit_at({d + "job.json": done}, "2026-10-01T14:00:00Z", remove=[q + "job.json"])                   # closed
        self.commit_at({q + "job.json": old_shape("Job item here", "taken", "wt/b")}, "2026-10-01T15:00:00Z", remove=[d + "job.json"])   # reverted
        self.commit_at({d + "job.json": done}, "2026-10-01T16:00:00Z", remove=[q + "job.json"])                   # closed again
        self.commit_at({q + "gone.json": old_shape("Gone item here")}, "2026-10-02T09:00:00Z")
        self.commit_at({d + "gone.json": old_shape("Gone item here", "dropped", dropped_why=["no"])}, "2026-10-02T10:00:00Z", remove=[q + "gone.json"])
        self.commit_at({q + "plain.json": old_shape("Plain item here")}, "2026-10-03T08:00:00Z")
        self.commit_at({q + "busy.json": old_shape("Busy item here", "taken", "wt/c")}, "2026-10-03T09:00:00Z")

    def read(self, rel):
        with open(os.path.join(self.main, ".relay", "queue", rel), encoding="utf-8") as handle:
            return json.load(handle)

    def test_dates_come_from_the_commits_of_the_history(self):
        self.history()
        out = self.run_relay("migrate", "-C", self.main)
        self.assertEqual(out.returncode, 0, out.stderr)
        # job: first commit 10:00 is found_at; taken 11:00, released 12:00, taken again 13:00: the LAST take (13:00) counts;
        # closed 14:00, reverted back to taken 15:00 (a revert is not a take), closed again 16:00: closed_at is 16:00
        job = self.read("done/job.json")
        self.assertEqual((job["found_at"], job["taken_at"], job["taken_by"], job["closed_at"], job["test"], job["dropped_at"]),
                         ("2026-10-01T10:00:00Z", "2026-10-01T13:00:00Z", "wt/b", "2026-10-01T16:00:00Z", "tests/t.py::t", None))
        self.assertTrue(set(job).isdisjoint(rq.OLD_ONLY))
        gone = self.read("done/gone.json")
        self.assertEqual((gone["found_at"], gone["dropped_at"], gone["dropped_why"], gone["taken_at"], gone["taken_by"]),
                         ("2026-10-02T09:00:00Z", "2026-10-02T10:00:00Z", ["no"], None, None))
        plain = self.read("plain.json")
        self.assertEqual((plain["found_at"], plain["taken_at"], plain["taken_by"], plain["test"]), ("2026-10-03T08:00:00Z", None, None, None))
        busy = self.read("busy.json")
        self.assertEqual((busy["found_at"], busy["taken_at"], busy["taken_by"]), ("2026-10-03T09:00:00Z", "2026-10-03T09:00:00Z", "wt/c"))
        self.assertEqual(rq.check_files(self.main), [])

    def test_f4_it_runs_again_and_changes_only_what_is_still_old(self):
        self.history()
        self.run_relay("migrate", "-C", self.main)
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "migrated")
        before = self.read("plain.json")
        again = self.run_relay("migrate", "-C", self.main)
        self.assertEqual((again.returncode, again.stdout.startswith("nothing to migrate")), (0, True), again.stdout)
        self.assertEqual(git(self.main, "status", "--porcelain"), "")
        # another branch lands an item in the old shape after this branch migrated: the second run converts that one only
        self.commit_at({".relay/queue/late.json": old_shape("Late item here")}, "2026-10-04T08:00:00Z")
        out = self.run_relay("migrate", "-C", self.main)
        self.assertEqual(out.stdout.splitlines()[1:], ["  .relay/queue/late.json"], out.stdout)
        self.assertEqual(self.read("late.json")["found_at"], "2026-10-04T08:00:00Z")
        self.assertEqual(self.read("plain.json"), before)

    def test_an_item_with_no_history_stops_the_run_and_writes_nothing(self):
        self.history()
        path = os.path.join(self.main, ".relay", "queue", "uncommitted.json")
        with open(path, "w") as handle:
            handle.write(old_shape("Not committed yet"))
        out = self.run_relay("migrate", "-C", self.main)
        self.assertEqual(out.returncode, 2)
        self.assertIn("uncommitted", out.stderr)
        self.assertIn('"state"', open(os.path.join(self.main, ".relay", "queue", "plain.json")).read())    # nothing was rewritten

    def test_check_lists_the_files_that_fail_and_exits_1(self):
        self.history()
        bad = self.run_relay("check", "-C", self.main)
        self.assertEqual(bad.returncode, 1)
        self.assertIn(".relay/queue/plain.json: old shape (state, found, closed_by): run `relay queue migrate`", bad.stdout)
        self.run_relay("migrate", "-C", self.main)
        ok = self.run_relay("check", "-C", self.main)
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "every queue item file is well formed"))
        # a done/ file whose events were removed is reported with the folder rule
        data = self.read("done/job.json")
        data.update(closed_at=None, test=None)
        with open(os.path.join(self.main, ".relay", "queue", "done", "job.json"), "w") as handle:
            json.dump(data, handle)
        self.assertIn("needs closed_at or dropped_at", self.run_relay("check", "-C", self.main).stdout)

    def test_json_lists_the_done_items_too_with_their_dates_and_the_table_does_not(self):
        self.history()
        self.run_relay("migrate", "-C", self.main)
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "migrated")
        items = json.loads(self.run_relay("json", "-C", self.main).stdout)
        self.assertEqual(sorted((i["slug"], i["state"]) for i in items),
                         [("busy", "taken"), ("gone", "dropped"), ("job", "done"), ("plain", "open")])
        job = next(i for i in items if i["slug"] == "job")
        self.assertEqual((job["found_at"], job["taken_at"], job["closed_at"]), ("2026-10-01T10:00:00Z", "2026-10-01T13:00:00Z", "2026-10-01T16:00:00Z"))
        table = self.run_relay("-C", self.main).stdout
        self.assertNotIn("gone", table)
        self.assertNotIn("job", table)

    def test_add_writes_only_the_new_shape(self):
        rq.add(self.main, "feature", "Fresh item here", why="w", minutes=5, now="2026-10-22T08:30:00Z", **QUIET)
        data = json.loads(git(self.main, "show", "master:.relay/queue/fresh-item-here.json"))
        self.assertEqual((data["found_at"], data["taken_at"], data["taken_by"], data["closed_at"], data["test"], data["dropped_at"], data["dropped_why"]),
                         ("2026-10-22T08:30:00Z", None, None, None, None, None, None))
        self.assertTrue(set(data).isdisjoint(rq.OLD_ONLY))


class TestFrontSkill(unittest.TestCase):
    def test_f1_the_front_skill_tells_the_front_to_name_waiting_fix_items_before_a_new_request(self):
        """Review (remaining) F1, the owner's "q4 - a": a text the front always loads holds the instruction, not only rules/queue.md."""
        with open(os.path.join(ROOT, "plugins", "front", "skills", "front", "SKILL.md"), encoding="utf-8") as handle:
            skill = " ".join(handle.read().split())
        self.assertIn("## A new request while fix items wait", skill)
        for phrase in ("how many, the top one by name, its time, and ask what goes first", "The owner decides"):
            self.assertIn(phrase, skill)
        self.assertIn("With no fix item waiting there is nothing to say", skill)


class TestStructuredRule(unittest.TestCase):
    def test_the_rule_has_the_shape_relay_sync_needs_and_says_the_owner_s_words(self):
        import relay_rules
        rule = relay_rules.rules()["structured-data"]
        self.assertEqual(rule["title"], "Structured data")
        self.assertTrue(rule["gist"].startswith("Information that a script, a hook or a later step reads, when it is one of many records of the same shape, is stored as a structured file"))
        for phrase in ("one of many records of the same shape", "changed only through one script", "Extensions", "relay only", "never write", "No new label or regex search over markdown"):
            self.assertIn(phrase, rule["gist"] + rule["body"])
        counts = [l for l in rule["body"].splitlines() if l.startswith("- What counts")]
        self.assertEqual(len(counts), 1)
        for word in ("hand-backs", "state"):
            self.assertNotIn(word, counts[0])
        self.assertIn("agent reports", rule["body"])


if __name__ == "__main__":
    unittest.main()
