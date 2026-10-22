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

import relay_queue as rq  # noqa: E402

NOSLEEP = lambda seconds: None  # noqa: E731  (time is a value: the tests never wait)
QUIET = {"sleep": NOSLEEP}


def git(repo, *args, check=True):
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


def fix_item(title="A fix", ip=91, size=10, found="2026-10-01, test", failing="the case fails"):
    return rq.render("fix", ip, size, found, title, f"Where: lib/x.py:5\nWhat is wrong: {title}\nFailing case: {failing}\nPass-cases: the other case\nWhy it matters: it matters")


def feature_item(title="A feature", ip=0, size=10, found="2026-10-01, test"):
    return rq.render("feature", ip, size, found, title, f"What: {title}\nWhy it matters: it matters")


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
                files[f".relay/queue/{slug}.md"] = text
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
        out = git(self.main, "show", f"{rev}:.relay/queue/{sub}{slug}.md", check=False)
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
        # ip 90 first; the three at ip 50 go older `found` first (b, c on 2026-10-01 by slug, then a on 2026-10-02)
        items = [rq.parse(s, t) for s, t in {
            "a": feature_item(ip=50, found="2026-10-02, x"), "c": feature_item(ip=50, found="2026-10-01, x"),
            "b": feature_item(ip=50, found="2026-10-01, x"), "d": fix_item(ip=90)}.items()]
        self.assertEqual([i["slug"] for i in rq.ordered(items)], ["d", "b", "c", "a"])

    def test_q1_cli_list_in_that_order(self):
        repo = self.repo("cli", items={"low": feature_item(ip=5), "high": fix_item(ip=80)})
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", "-C", repo],
                              capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=ROOT))
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.strip().split("\n")
        self.assertEqual(lines[0].split(), ["slug", "kind", "ip", "time", "title"])   # the header names the columns
        self.assertEqual([line.split()[0] for line in lines[1:]], ["high", "low"])

    def test_q2_fix_without_failing_case_refused_and_shown_malformed(self):
        before = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.add(self.main, "fix", "No case", why="w", minutes=5, **QUIET)
        self.assertIn("Failing case", str(ctx.exception))
        self.assertEqual(git(self.main, "rev-parse", "master"), before)       # nothing was written
        bad = rq.render("fix", 10, 5, "2026-10-01, t", "Bad", "What is wrong: x")
        self.write_commit(self.main, {".relay/queue/bad.md": bad}, "bad item")
        lines = rq.list_lines(rq.read_queue(self.main))
        self.assertEqual(len(lines), 1)
        self.assertIn("malformed", lines[0])
        self.assertEqual(rq.count_text(rq.read_queue(self.main)), "0 fix, 0 feature")   # a malformed item is not counted as open

    def test_q3_add_from_report_copies_the_finding(self):
        report = os.path.join(self.tmp, "review.md")
        with open(report, "w") as handle:
            handle.write("Reviewed: abc\n\n## Findings\n"
                         "lib/other.py:9: LOW: F2 something else\nFailing case: not this one\n"
                         "lib/relay_inert.py:51: MEDIUM: F7 a merge commit lists master's files\n"
                         "Failing case: merge master into a branch;\n  changed() lists 3 files\nPass-cases: a branch without a merge\n"
                         "Why it matters: the gate runs on the wrong files\nSize: 25\n\n## Outside this change\n")
        message = rq.add_from(self.main, report, "F7", today="2026-10-22", **QUIET)
        self.assertIn("queued a-merge-commit-lists-master-s-files (fix, ip 1)", message)
        item = self.item("a-merge-commit-lists-master-s-files")
        self.assertEqual((item["kind"], item["state"], item["ip"], item["time"]), ("fix", "open", 1, 25))
        self.assertEqual(item["found"], "2026-10-22, finding F7 of review.md")
        self.assertEqual(item["where"], "lib/relay_inert.py:51")
        self.assertIn("lib/relay_inert.py:51: MEDIUM: F7 a merge commit lists master's files", item["body"])   # the linter line, verbatim
        self.assertEqual(rq.field_block(item["body"], "Failing case"), "merge master into a branch;\n  changed() lists 3 files")
        self.assertEqual(rq.field_block(item["body"], "Pass-cases"), "a branch without a merge")
        self.assertNotIn("not this one", item["body"])
        with self.assertRaises(rq.Refused):
            rq.add_from(self.main, report, "F9", **QUIET)

    def test_q4_count_ignores_done_taken_and_other_branches(self):
        # open: one fix (ip 80, time 30m), one feature; ignored: a done item, a taken one, an item only on a branch
        repo = self.repo("c", items={"f1": fix_item(ip=80, size=30), "ft": feature_item(ip=3),
                                     "tk": rq.set_fields(fix_item(ip=99), state="taken", taken_by="wt/z")})
        self.write_commit(repo, {".relay/queue/done/old.md": rq.set_fields(fix_item(ip=95), state="done")}, "done item")
        git(repo, "checkout", "-q", "-b", "wt/side")
        self.write_commit(repo, {".relay/queue/side.md": fix_item(ip=100)}, "only on a branch")
        git(repo, "checkout", "-q", "master")
        self.assertEqual(rq.count_text(rq.read_queue(repo)), "1 fix, 1 feature; top: f1 (fix, ip 80, time 30m)")
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", "count", "-C", repo],
                              capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=ROOT))
        self.assertEqual(done.stdout.strip(), "1 fix, 1 feature; top: f1 (fix, ip 80, time 30m)")

    def test_q5_session_line_from_a_worktree_and_nothing_without_queue(self):
        hook = os.path.join(ROOT, "plugins", "front", "hooks", "handover.py")

        def run(cwd):
            done = subprocess.run([sys.executable, hook], input=json.dumps({"source": "startup", "cwd": cwd}), capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            return json.loads(done.stdout) if done.stdout.strip() else None

        repo = self.repo("q5", items={"top": fix_item(ip=95, size=30), "ft": feature_item(ip=1)})
        wt = os.path.join(self.tmp, "q5wt")
        git(repo, "worktree", "add", "-q", "-b", "wt/q5wt", wt)
        want = "Queue: 1 fix, 1 feature; top: top (fix, ip 95, time 30m). relay queue lists them."
        out = run(wt)
        self.assertIn(want, out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(out["systemMessage"], want)
        self.assertIsNone(run(self.repo("q5none", relay=False)))                 # no .relay/: nothing
        self.assertIsNone(run(self.repo("q5empty")))                              # .relay/ but no queue folder: nothing
        only_done = self.repo("q5done", items={})
        self.write_commit(only_done, {".relay/queue/x.md": rq.set_fields(fix_item(), state="taken", taken_by="wt/z")}, "taken only")
        self.assertIsNone(run(only_done))                                          # zero open items: nothing

    def test_q8_new_fix_gets_one_more_than_top_open_feature(self):
        # open features 40 and 70; a taken feature at 90 does not count; so a fix gets 71, a feature 0
        repo = self.repo("q8", items={"fa": feature_item(ip=40), "fb": feature_item(ip=70),
                                      "fc": rq.set_fields(feature_item(ip=90), state="taken", taken_by="wt/z")})
        rq.add(repo, "fix", "New fix", why="w", failing="f", minutes=5, **QUIET)
        self.assertEqual(rq.parse("n", git(repo, "show", "master:.relay/queue/new-fix.md"))["ip"], 71)
        rq.add(repo, "feature", "New feature", why="w", minutes=5, **QUIET)
        self.assertEqual(rq.parse("n", git(repo, "show", "master:.relay/queue/new-feature.md"))["ip"], 0)
        bare = self.repo("q8b")
        rq.add(bare, "fix", "First", why="w", failing="f", minutes=5, **QUIET)
        self.assertEqual(rq.parse("n", git(bare, "show", "master:.relay/queue/first.md"))["ip"], 1)   # no open feature: 1 + 0


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
        repo = self.repo("align", items={"a": fix_item("A", ip=90, size=90), "bb": feature_item("B", ip=5, size=20)})
        lines = rq.list_lines(rq.read_queue(repo), header=True)
        # slugs "a"/"bb" pad to 2, kinds "fix"/"feature" to 7, times "1h 30m"/"20m" to 6 (right-aligned): both titles start at one column
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1].rindex("A"), lines[2].rindex("B"))
        self.assertTrue(lines[1].endswith("1h 30m  A"))
        self.assertTrue(lines[2].endswith("   20m  B"))

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
            self.assertTrue(os.path.exists(os.path.join(self.main, ".relay/queue", slug + ".md")))   # the main checkout followed
        self.assertEqual(git(wt, "status", "--porcelain"), "")                      # the worktree was not touched
        self.assertEqual(git(self.main, "status", "--porcelain"), "")
        self.assertEqual(self.branches(), [])
        self.assertEqual(git(self.main, "log", "-1", "--format=%s"), "queue: from-worktree")

    def test_q6_same_title_gets_suffix(self):
        rq.add(self.main, "feature", "Same title", why="one", minutes=5, **QUIET)
        message = rq.add(self.main, "feature", "Same title", why="two", minutes=5, **QUIET)
        self.assertIn("queued same-title-2", message)
        self.assertIn("one", self.item("same-title")["body"])
        self.assertIn("two", self.item("same-title-2")["body"])
        self.write_commit(self.main, {".relay/queue/done/other.md": rq.set_fields(feature_item(), state="done")}, "done")
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
            bodies = self.item(slug)["body"] + self.item(slug + "-2")["body"]
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
            self.write_commit(self.main, {".relay/queue/late.md": feature_item()}, "head moves")
        with self.assertRaises(rq.Refused):
            rq.add(self.main, "feature", "Late", why="w", minutes=5, tries=1, after_plan=move_head, **QUIET)
        # a kept `late` branch would add late.md, which now exists on master with other content: it no longer holds
        with self.assertRaises(rq.Refused) as ctx:
            rq.land(self.main, "late", **QUIET)
        self.assertIn("no longer holds", str(ctx.exception))
        self.assertEqual(self.branches(), ["wt/queue-late"])
        self.assertIsNotNone(text)

    def test_q9_a_second_file_is_refused_and_the_branch_deleted(self):
        before = git(self.main, "rev-parse", "master")

        def planner(reader):
            plan = rq.Plan("sneaky", {".relay/queue/sneaky.md": feature_item(), "README.md": "changed\n"}, "feature, ip 0", "queued")
            plan.allowed = {".relay/queue/sneaky.md"}      # what the command may touch: the one item file
            return plan
        with self.assertRaises(rq.Refused) as ctx:
            rq._land(self.main, planner, **QUIET)
        self.assertIn("beyond the one allowed file", str(ctx.exception))
        self.assertEqual(self.branches(), [])
        self.assertEqual(git(self.main, "rev-parse", "master"), before)


class TestTake(Base):
    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {".relay/queue/job.md": fix_item("Job", ip=60, failing="line 1\nline 2"),
                                      ".relay/queue/feat.md": feature_item("Feat", ip=20)}, "seed")
        self.wa, self.wb = self.worktree("a"), self.worktree("b")

    def findings(self, name="f.md"):
        return os.path.join(self.tmp, name)

    def test_q10_take_lands_taken_on_default_and_writes_the_findings(self):
        out = rq.take(self.wa, "job", self.findings(), **QUIET)
        self.assertIn("taken job (fix, ip 60), landed on master at " + git(self.main, "rev-parse", "master"), out)
        item = self.item("job")
        self.assertEqual((item["state"], item["taken_by"]), ("taken", "wt/a"))
        self.assertEqual(rq.count_text(rq.read_queue(self.main)), "0 fix, 1 feature; top: feat (feature, ip 20, time 10m)")
        self.assertEqual(self.branches(), [])
        # the worktree branch now holds the taken state (a fast-forward of a fresh worktree)
        self.assertEqual(git(self.wa, "rev-parse", "HEAD"), git(self.main, "rev-parse", "master"))
        with open(self.findings()) as handle:
            text = handle.read()
        self.assertEqual(text.split("\n")[0], "Reviewed: " + git(self.main, "rev-parse", "master"))   # merge-base = the head it merged
        self.assertIn("From queue: job", text)
        self.assertIn("lib/x.py:5: HIGH: Q1 Job", text)
        self.assertIn("Failing case: line 1\nline 2", text)
        self.assertIn("Pass-cases: the other case", text)

    def test_q10_second_take_from_another_worktree_is_refused(self):
        rq.take(self.wa, "job", self.findings(), **QUIET)
        with self.assertRaises(rq.Refused) as ctx:
            rq.take(self.wb, "job", self.findings("g.md"), **QUIET)
        self.assertIn("taken by wt/a", str(ctx.exception))
        self.assertFalse(os.path.exists(self.findings("g.md")))

    def test_q10_two_takes_started_together_exactly_one_lands(self):
        for rnd in range(10):
            slug = f"race{rnd}"
            self.write_commit(self.main, {f".relay/queue/{slug}.md": fix_item(slug)}, "item")
            for wt in (self.wa, self.wb):                  # worktrees follow master so the take's merge is a fast-forward
                git(wt, "merge", "-q", "--no-edit", "master")
            hook = self.barrier()
            a, b = self.pair(lambda: rq.take(self.wa, slug, self.findings(f"fa{rnd}.md"), after_plan=hook, **QUIET),
                             lambda: rq.take(self.wb, slug, self.findings(f"fb{rnd}.md"), after_plan=hook, **QUIET))
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
            self.write_commit(self.main, {f".relay/queue/{slug}.md": fix_item(slug, ip=60)}, "item")
            git(self.wa, "merge", "-q", "--no-edit", "master")
            hook = self.barrier()
            took, changed = self.pair(lambda: rq.take(self.wa, slug, self.findings(f"i{rnd}.md"), after_plan=hook, **QUIET),
                                      lambda: rq.set_ip(self.main, slug, 50, after_plan=hook, **QUIET))
            self.assertIsInstance(took, str, took)
            states = []                                     # the item's history on master, oldest first
            for sha in git(self.main, "log", "--reverse", "--format=%H", "--", f".relay/queue/{slug}.md").split("\n"):
                states.append(rq.parse(slug, git(self.main, "show", f"{sha}:.relay/queue/{slug}.md")))
            self.assertEqual(states[-1]["state"], "taken")
            if isinstance(changed, str):                    # both landed: the ip change came while the item was still open
                self.assertEqual([s["state"] for s in states], ["open", "open", "taken"])
                self.assertEqual(states[-1]["ip"], 50)
            else:
                self.assertIn("taken by wt/a", str(changed))
                self.assertEqual([s["state"] for s in states], ["open", "taken"])
                self.assertEqual(states[-1]["ip"], 60)

    def test_q10_ip_and_drop_refuse_a_taken_item_and_release_opens_it(self):
        rq.take(self.wa, "job", self.findings(), **QUIET)
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
        self.assertEqual((item["state"], item["taken_by"]), ("open", ""))
        rq.drop(self.main, "feat", "the owner said drop it", **QUIET)
        self.assertIsNone(self.item("feat"))
        dropped = self.item("feat", sub="done/")
        self.assertEqual(dropped["state"], "dropped")
        self.assertIn("the owner said drop it", dropped["body"])

    def test_q10_later_done_on_the_task_branch_merges_without_conflict(self):
        rq.take(self.wa, "job", self.findings(), **QUIET)
        rq.add(self.main, "feature", "Meanwhile", why="w", minutes=5, **QUIET)        # master moves on
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "the fix and its test")
        report = os.path.join(self.tmp, "check.md")
        with open(report, "w") as handle:
            handle.write("Q1 MET tests/test_job.py:1\n")
        message = rq.done(self.wa, "job", "tests/test_job.py::test_job_works", report)
        self.assertIn("closed job", message)
        self.assertEqual(git(self.wa, "log", "-1", "--format=%s"), "queue: done job")
        self.assertEqual(git(self.wa, "status", "--porcelain"), "")
        self.assertEqual(self.item("job")["state"], "taken")                         # master changes only when the branch merges
        git(self.main, "merge", "-q", "--no-edit", "wt/a")                           # no conflict
        self.assertIsNone(self.item("job"))
        closed = self.item("job", sub="done/")
        self.assertEqual((closed["state"], closed["closed_by"], closed["test"]),
                         ("done", "wt/a", "tests/test_job.py::test_job_works"))
        self.assertIsNotNone(self.item("meanwhile"))

    def test_q7_done_refusals(self):
        rq.take(self.wa, "job", self.findings(), **QUIET)
        self.write_commit(self.wa, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "test")
        good = os.path.join(self.tmp, "good.md")
        weak = os.path.join(self.tmp, "weak.md")
        with open(good, "w") as handle:
            handle.write("Q1 MET tests/test_job.py:1\n")
        with open(weak, "w") as handle:
            handle.write("Q1 NOT MET it still fails\nF2 MET x:1\n")
        head = git(self.wa, "rev-parse", "HEAD")
        cases = [("", good, "--test"),                                              # no --test
                 ("tests/test_job.py::test_other", good, "does not hold a test named"),   # a name the file lacks
                 ("tests/missing.py::test_job_works", good, "is not in the last commit"),
                 ("tests/test_job.py::test_job_works", weak, "Q1 MET"),               # a report lacking Q1 MET
                 ("tests/test_job.py::test_job_works", os.path.join(self.tmp, "none.md"), "cannot read")]
        for test, report, expect in cases:
            with self.assertRaises(rq.Refused, msg=test) as ctx:
                rq.done(self.wa, "job", test, report)
            self.assertIn(expect, str(ctx.exception))
            self.assertEqual(git(self.wa, "rev-parse", "HEAD"), head)               # nothing committed
        git(self.wb, "merge", "-q", "--no-edit", "master")                           # wt/b sees the item, but wt/a took it
        self.write_commit(self.wb, {"tests/test_job.py": "def test_job_works():\n    pass\n"}, "test")
        with self.assertRaises(rq.Refused) as ctx:
            rq.done(self.wb, "job", "tests/test_job.py::test_job_works", good)
        self.assertIn("not taken by wt/b", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
