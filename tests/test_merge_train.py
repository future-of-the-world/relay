"""A merge train (design docs/plans/review-gate.md section 7.7): ready changes ride one throwaway branch that is gated once and
lands with one fast-forward. The merge hook must let it land (absorbed branches, covered files), and must still refuse every
tree that no gate or check has seen. Real throwaway repositories under a temp dir; no clock, no network.

Case names T1..T16 are the design's test list (docs/plans/review-gate.md section 7.7 / design-regate); Q1 of the queue item
`each-merge-makes-every-waiting-change-gate-again` ("N ready changes merge with at most one extra gate in total") is
`test_q1_ready_changes_merge_with_one_gate_for_the_wave`.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_inert as ri  # noqa: E402
import relay_marks as rm  # noqa: E402
import relay_queue as rq  # noqa: E402
import relay_verdict as rv  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
SHARED = "".join("line %d\n" % n for n in range(1, 13))        # far enough apart that two changes merge without a conflict
TEST_SRC = "def test_x_stays_fixed():\n    pass\n\n\ndef test_y_stays_fixed():\n    pass\n"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relative))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qjson(slug, state="taken", by="wt/a", test=None):
    event = {"taken_at": "2026-10-22T10:00:00Z", "taken_by": by, "closed_at": None, "test": None, "dropped_at": None, "dropped_why": None}
    if state == "done":
        event.update(closed_at="2026-10-22T12:00:00Z", test=test)
    return json.dumps(dict({"kind": "fix", "ip": 5, "time": 10, "found_at": "2026-10-22T08:00:00Z", "found_in": "fixture",
                            "title": "Item %s loses a row" % slug, "what": ["it loses a row"], "why": ["a row is lost"],
                            "failing_case": ["y"]}, **event), indent=2) + "\n"


class TrainCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patch = mock.patch.dict(os.environ, GIT_ENV)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.main = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(self.main, "lib"))
        os.makedirs(os.path.join(self.main, "tests"))
        os.makedirs(os.path.join(self.main, ".relay", "queue"))
        self.git(self.main, "init", "-q", "-b", "master")
        self.write(self.main, {".gitignore": ".worktrees/\n", ".relay/README.md": "x\n", "lib/shared.py": SHARED, "lib/f.py": SHARED,
                               "tests/test_relay.py": TEST_SRC,
                               ".relay/queue/x.json": qjson("x"), ".relay/queue/y.json": qjson("y", by="wt/b")})
        self.git(self.main, "add", "-A")
        self.git(self.main, "commit", "-q", "-m", "init")
        self.hook = load("merge_hook_under_test", os.path.join("plugins", "core", "hooks", "merge.py"))

    # ---- fixtures ----
    def git(self, cwd, *args, check=True):
        done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
        if check and done.returncode != 0:
            raise AssertionError("git %s failed: %s" % (" ".join(args), done.stderr))
        return done.stdout.strip()

    def write(self, wt, files):
        for name, text in files.items():
            path = os.path.join(wt, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(text)

    def tree(self, name, base="master"):
        path = os.path.join(self.main, ".worktrees", name)
        self.git(self.main, "worktree", "add", "-q", path, "-b", "wt/" + name, base)
        return path

    def commit(self, wt, files, msg="work"):
        self.write(wt, files)
        self.git(wt, "add", "-A")
        self.git(wt, "commit", "-q", "-m", msg)
        return self.git(wt, "rev-parse", "HEAD")

    def gate(self, wt, code=0):
        head = self.git(wt, "rev-parse", "HEAD")
        path = os.path.join(wt, ".relay", "checks", head + ".gate.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("head %s\ncmd fixture\nexit %d\n" % (head, code))
        rm.commit_file(wt, path, "relay: gate of " + head)
        return path

    def mark(self, wt, commit, open_=0, item=None):
        findings = []
        if item:
            findings.append({"id": "Q1", "path": "lib/a.py", "line": 1, "severity": "HIGH", "rank": "high", "kind": "inside",
                             "summary": "it loses a row", "failing_case": ["y"], "source": "queue", "since": commit,
                             "verdict": "MET", "reason": ["tests/test_relay.py:1"]})
        record = {"schema": 2, "type": "check", "head": commit, "branch": self.git(wt, "branch", "--show-current"), "item": item,
                  "gate": None, "scope": [], "notes": [], "findings": findings}
        rm.put(wt, commit, {"schema": 2, "commit": commit, "verdict": {"open": open_, "queued": 0}, "check": commit + ".check.json",
                            "gate": None, "time": "2026-10-22T10:00:00Z"}, {commit + ".check.json": json.dumps(record) + "\n"})

    def ready(self, wt, files, open_=0, item=None, msg="work"):
        """A ready change: a code commit, a green gate on it and a check mark of it. Returns the checked commit."""
        commit = self.commit(wt, files, msg)
        self.gate(wt)
        self.mark(wt, commit, open_, item)
        return commit

    def train(self, *names, number=1):
        wt = self.tree("train-%d" % number)
        for name in names:
            self.git(wt, "merge", "--no-ff", "--no-edit", "wt/" + name)
        return wt

    def verdict(self, branch):
        """None when the hook lets `git merge --ff-only <branch>` run, else its refusal line."""
        try:
            self.hook.judge(self.main, "master", branch)
        except self.hook.Refused as exc:
            return str(exc)
        return None

    def land_and_clean(self, branch):
        self.git(self.main, "merge", "-q", "--ff-only", branch)
        out = io.StringIO()
        event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": self.main, "session_id": "s0",
                 "tool_input": {"command": "git merge --ff-only " + branch}}
        with contextlib.redirect_stdout(out):
            self.hook.post(event)
        return json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] if out.getvalue() else ""

    def has_branch(self, branch):
        return subprocess.run(["git", "-C", self.main, "show-ref", "--verify", "--quiet", "refs/heads/" + branch]).returncode == 0

    def two_riders(self):
        """Riders a and b with disjoint files, each ready; returns (a's worktree, b's worktree)."""
        a, b = self.tree("a"), self.tree("b")
        self.ready(a, {"lib/a.py": "a1\n"})
        self.ready(b, {"lib/b.py": "b1\n"})
        return a, b

    def shared_riders(self):
        """Riders a and b that both change lib/shared.py (far apart, so git combines it), each ready."""
        a, b = self.tree("a"), self.tree("b")
        self.ready(a, {"lib/shared.py": SHARED.replace("line 1\n", "A one\n"), "lib/a.py": "a1\n"})
        self.ready(b, {"lib/shared.py": SHARED.replace("line 10\n", "B ten\n"), "lib/b.py": "b1\n"})
        return a, b


class TheTrainLands(TrainCase):
    def test_t1_riders_with_no_shared_file_land_with_a_gate_and_no_mark_of_their_own(self):
        # A and B each carry their own open-0 check; the train's own files are all theirs, so it needs only its gate.
        self.two_riders()
        train = self.train("a", "b")
        self.assertIn("no green gate", self.verdict("wt/train-1"))        # not gated yet
        self.gate(train)
        self.assertIsNone(self.verdict("wt/train-1"))
        head = self.git(train, "rev-parse", "HEAD")
        said = self.land_and_clean("wt/train-1")
        self.assertEqual(self.git(self.main, "rev-parse", "master"), head)      # master moved to the gated tree in one step
        for name in ("train-1", "a", "b"):
            self.assertFalse(os.path.exists(os.path.join(self.main, ".worktrees", name)), name)
            self.assertFalse(self.has_branch("wt/" + name), name)
        self.assertEqual(said.count("Removed .worktrees/"), 3)

    def test_q1_ready_changes_merge_with_one_gate_for_the_wave(self):
        # Q1 of the queue item: N ready changes merge with at most one extra gate in total. Three ready changes, each gated once on
        # its own head (3 gate logs, worked out by hand), land through one train: master ends with 3 + 1 = 4 gate logs in its
        # history, the extra one the train's, and it is at the train head. Without the absorbed-branch rule the train is refused
        # for want of a mark of its own, so each change would take master and gate again, one by one.
        self.two_riders()
        c = self.tree("c")
        self.ready(c, {"lib/c.py": "c1\n"})
        train = self.train("a", "b", "c")
        self.gate(train)
        self.assertIsNone(self.verdict("wt/train-1"))
        head = self.git(train, "rev-parse", "HEAD")
        self.land_and_clean("wt/train-1")
        self.assertEqual(self.git(self.main, "rev-parse", "master"), head)
        self.assertEqual(len(rm.gate_logs(self.main, "master")), 4)

    def test_t3_a_train_head_nobody_gated_is_refused_naming_the_gate_in_the_train_worktree(self):
        # both riders were gated on their own heads, the combined tree was not: no ungated tree may become master's head
        self.two_riders()
        self.train("a", "b")
        reason = self.verdict("wt/train-1")
        self.assertIn("no green gate for the code at wt/train-1's head", reason)
        self.assertIn("run relay gate in .worktrees/train-1", reason)

    def test_t4_a_rider_whose_check_left_a_problem_open_is_not_absorbed_and_the_train_is_refused(self):
        a, b = self.tree("a"), self.tree("b")
        self.ready(a, {"lib/a.py": "a1\n"})
        self.ready(b, {"lib/b.py": "b1\n"}, open_=1)
        train = self.train("a", "b")
        self.gate(train)
        self.assertEqual(sorted(ri.absorbed(self.main, "wt/train-1")), ["wt/a"])
        self.assertIn("left 1 thing inside the change wrong", self.verdict("wt/train-1"))

    def test_t5_a_rider_with_a_code_commit_after_its_mark_is_not_absorbed_and_the_train_is_refused(self):
        a, b = self.tree("a"), self.tree("b")
        self.ready(a, {"lib/a.py": "a1\n"})
        self.ready(b, {"lib/b.py": "b1\n"})
        self.commit(b, {"lib/b2.py": "later\n"})                           # code after the check
        train = self.train("a", "b")
        self.gate(train)
        self.assertEqual(sorted(ri.absorbed(self.main, "wt/train-1")), ["wt/a"])
        self.assertIn("lib/b2.py", self.verdict("wt/train-1"))

    def test_t16_after_the_land_a_rider_with_uncommitted_changes_is_kept_and_the_others_removed(self):
        a, b = self.two_riders()
        train = self.train("a", "b")
        self.gate(train)
        self.write(b, {"lib/b.py": "edited, not committed\n"})
        self.assertIsNone(self.verdict("wt/train-1"))
        said = self.land_and_clean("wt/train-1")
        self.assertTrue(os.path.isdir(b) and self.has_branch("wt/b"))
        self.assertIn("kept .worktrees/b: it holds changes not in the branch", said)
        self.assertFalse(os.path.exists(a) or self.has_branch("wt/a") or self.has_branch("wt/train-1"))


class CombinedFiles(TrainCase):
    def test_t2_a_file_both_riders_changed_needs_a_merge_check_on_the_train(self):
        self.shared_riders()
        train = self.train("a", "b")
        self.gate(train)
        reason = self.verdict("wt/train-1")
        self.assertIn("lib/shared.py", reason)
        self.assertNotIn("lib/a.py", reason)                               # a's and b's own files are covered by their checks
        self.assertIn("run relay gate, then delegate:checker", reason)
        base = self.git(train, "merge-base", "master", "HEAD")
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", train, "--own", base],
                              capture_output=True, text=True)
        self.assertEqual(done.stdout.split(), ["lib/shared.py"])           # the train's own files are exactly the combined file
        head = self.git(train, "rev-parse", "HEAD")
        self.mark(train, head)                                             # what delegate:checker records once M1 is MET
        self.assertIsNone(self.verdict("wt/train-1"))

    def test_t11_a_train_commit_that_sets_a_combined_file_to_one_riders_version_is_refused(self):
        # A and B both changed lib/shared.py. A commit on the train makes it A's version, so B's change is gone with no check:
        # the file is A's version (condition 1) and master did not touch it (condition 2), but B also changed it (condition 3).
        a, b = self.shared_riders()
        train = self.train("a", "b")
        self.commit(train, {"lib/shared.py": self.git(self.main, "show", "wt/a:lib/shared.py") + "\n"})        # git() strips the last newline
        self.gate(train)
        self.assertEqual(self.git(train, "rev-parse", "HEAD:lib/shared.py"), self.git(self.main, "rev-parse", "wt/a:lib/shared.py"))   # same blob
        self.assertIn("lib/shared.py", self.verdict("wt/train-1"))
        tip = self.git(train, "rev-parse", "HEAD")
        base = self.git(train, "merge-base", "master", tip)
        got = ri.changed(self.main, base, tip, own=True, absorbed=ri.absorbed(self.main, tip))
        self.assertEqual(got, ["lib/shared.py"])

    def test_a_file_only_one_rider_changed_is_covered_and_one_the_train_rewrote_is_not(self):
        # condition 1 on its own: lib/a.py is a's version at the train head (covered); after the train rewrites it, it is not
        a, b = self.two_riders()
        train = self.train("a", "b")
        tip = self.git(train, "rev-parse", "HEAD")
        base = self.git(train, "merge-base", "master", tip)
        held = ri.absorbed(self.main, tip)
        self.assertEqual(ri.changed(self.main, base, tip, own=True, absorbed=held), [])
        self.assertEqual(ri.changed(self.main, base, tip, own=True), ["lib/a.py", "lib/b.py"])
        self.commit(train, {"lib/a.py": "rewritten on the train\n"})
        tip = self.git(train, "rev-parse", "HEAD")
        self.assertEqual(ri.changed(self.main, base, tip, own=True, absorbed=ri.absorbed(self.main, tip)), ["lib/a.py"])


class StackedBranches(TrainCase):
    def stacked(self):
        """P changed lib/f.py (ready); S is made from P's tip."""
        p = self.tree("p")
        self.ready(p, {"lib/f.py": SHARED.replace("line 1\n", "P one\n")})
        s = self.tree("s", "wt/p")
        return p, s

    def test_t10_a_hand_resolved_merge_that_drops_masters_change_stays_the_branchs_own_file(self):
        # P changed line 1 of lib/f.py; master merged Q, which changed the same line; S (made from P) took master and kept P's side
        # by hand, so Q's change is gone from S. lib/f.py at S equals P's tip (condition 1) but master changed it after P left
        # (condition 2 fails), so it is S's own file: listed for the checker and for the mark step, not covered by P.
        # (The hook compares with the mark's tree, where lib/f.py is already P's version, so only the list shows it here.)
        p, s = self.stacked()
        self.ready(s, {"lib/g.py": "g1\n"})
        self.commit(self.main, {"lib/f.py": SHARED.replace("line 1\n", "Q one\n")}, "Q")
        self.git(s, "merge", "--no-edit", "master", check=False)
        self.git(s, "checkout", "--ours", "--", "lib/f.py")
        self.git(s, "add", "-A")
        self.git(s, "commit", "-q", "--no-edit")
        tip = self.git(s, "rev-parse", "HEAD")
        self.assertEqual(self.git(s, "show", "HEAD:lib/f.py"), self.git(self.main, "show", "wt/p:lib/f.py"))   # P's version, Q's gone
        self.assertEqual(self.git(self.main, "rev-parse", "master"), self.git(s, "merge-base", "master", tip))
        held = ri.absorbed(self.main, tip)
        self.assertEqual(sorted(held), ["wt/p"])
        self.assertEqual(ri.changed(self.main, "master", tip, own=True, absorbed=held), ["lib/f.py", "lib/g.py"])

    def test_t12_a_stacked_branch_is_checked_for_its_own_files_only(self):
        # P has a usable check and nobody else changed lib/f.py: S's checker is not asked about it again
        p, s = self.stacked()
        base = self.git(s, "merge-base", "master", "wt/s")
        self.commit(s, {"lib/g.py": "g1\n"})
        tip = self.git(s, "rev-parse", "HEAD")
        self.assertEqual(ri.changed(self.main, base, tip, own=True, absorbed=ri.absorbed(self.main, tip)), ["lib/g.py"])
        self.gate(s)
        self.assertIn("lib/g.py", self.verdict("wt/s"))                    # S still needs a mark for its own file
        self.mark(s, tip)
        self.assertIsNone(self.verdict("wt/s"))

    def test_t7_a_stacked_branch_on_an_unchecked_one_is_judged_as_before(self):
        p = self.tree("p")
        self.commit(p, {"lib/f.py": SHARED.replace("line 1\n", "P one\n")})               # no mark: P is not absorbed
        s = self.tree("s", "wt/p")
        base = self.git(s, "merge-base", "master", "wt/s")
        self.ready(s, {"lib/g.py": "g1\n"})
        tip = self.git(s, "rev-parse", "HEAD")
        self.assertEqual(ri.absorbed(self.main, tip), {})
        self.assertEqual(ri.changed(self.main, base, tip, own=True, absorbed=ri.absorbed(self.main, tip)), ["lib/f.py", "lib/g.py"])
        self.assertIsNone(self.verdict("wt/s"))                            # S's own mark covers the head, as today
        self.commit(s, {"lib/h.py": "later\n"})
        self.gate(s)
        self.assertIn("lib/h.py", self.verdict("wt/s"))


class FixItems(TrainCase):
    def closing_riders(self):
        """A closes x (test_x_stays_fixed) and B closes y (test_y_stays_fixed), each with a Q1-MET check."""
        a, b = self.tree("a"), self.tree("b")
        for wt, slug, by, test in ((a, "x", "wt/a", "test_x_stays_fixed"), (b, "y", "wt/b", "test_y_stays_fixed")):
            self.git(wt, "rm", "-q", ".relay/queue/%s.json" % slug)
            self.ready(wt, {".relay/queue/done/%s.json" % slug: qjson(slug, "done", by, "tests/test_relay.py::" + test),
                            "lib/%s.py" % slug: "fixed\n"}, item=slug)
        return a, b

    def test_t6_two_riders_that_each_close_a_fix_land_together(self):
        a, b = self.closing_riders()
        train = self.train("a", "b")
        self.gate(train)
        self.assertIsNone(self.verdict("wt/train-1"))
        # judged at the train head, as one branch, each close would be refused: the newest check there is only one rider's
        for slug, test in (("x", "test_x_stays_fixed"), ("y", "test_y_stays_fixed")):
            self.assertIsNotNone(rq.close_refusal(self.main, "refs/heads/wt/train-1", slug, "tests/test_relay.py::" + test))

    def test_t13_a_rider_that_removes_another_riders_closing_test_makes_the_train_refused(self):
        a = self.tree("a")
        self.git(a, "rm", "-q", ".relay/queue/x.json")
        self.ready(a, {".relay/queue/done/x.json": qjson("x", "done", "wt/a", "tests/test_relay.py::test_x_stays_fixed"), "lib/x.py": "fixed\n"}, item="x")
        b = self.tree("b")
        self.ready(b, {"tests/test_relay.py": "def test_y_stays_fixed():\n    pass\n"})      # b removes test_x_stays_fixed
        train = self.train("a", "b")
        self.gate(train)
        reason = self.verdict("wt/train-1")
        self.assertIn("queue item x is closed without a test or a check", reason)
        self.assertIn("test_x_stays_fixed", reason)

    def test_the_test_and_the_check_part_of_a_close_are_judged_at_their_own_refs(self):
        a, b = self.closing_riders()
        self.train("a", "b")
        test = "tests/test_relay.py::test_x_stays_fixed"
        self.assertIsNone(rq.test_refusal(self.main, "refs/heads/wt/train-1", test))
        self.assertIsNone(rq.check_refusal(self.main, "refs/heads/wt/a", "x"))
        self.assertIn("after the check of", rq.check_refusal(self.main, "refs/heads/wt/train-1", "x"))
        self.assertIn("does not hold a test named", rq.test_refusal(self.main, "refs/heads/master~0", "tests/test_relay.py::test_nope"))
        self.assertEqual(rq.close_refusal(self.main, "refs/heads/wt/a", "x", test), None)


class RefusalsNameTheSteps(TrainCase):
    def test_t9_a_refusal_after_a_later_commit_names_the_gate_and_the_checker_and_show_names_the_files(self):
        a = self.tree("a")
        self.ready(a, {"lib/a.py": "a1\n"})
        clean = rm.show(self.main, "wt/a")
        self.assertEqual(len(clean), 3)                                    # on a clean branch the output is unchanged
        self.assertIsNone(self.verdict("wt/a"))
        self.commit(a, {"lib/late.py": "x\n"})
        self.gate(a)
        reason = self.verdict("wt/a")
        self.assertIn("lib/late.py", reason)
        self.assertIn("run relay gate, then delegate:checker", reason)
        lines = rm.show(self.main, "wt/a")
        self.assertEqual(lines[3], "1 non-inert file changed after the mark: lib/late.py; run relay gate, then delegate:checker")
        self.assertEqual(lines[:3], rm.show(self.main, "wt/a")[:3])

    def test_a_branch_with_no_mark_is_told_to_gate_and_check(self):
        a = self.tree("a")
        self.commit(a, {"lib/a.py": "a1\n"})
        self.assertIn("run relay gate, then delegate:checker on its head", self.verdict("wt/a"))


class MergeCheck(TrainCase):
    def test_t14_the_train_check_lists_only_the_combined_files_and_needs_no_review(self):
        self.shared_riders()
        train = self.train("a", "b")
        gate = self.gate(train)
        lines = rv.finding_list(train, [])
        self.assertEqual(lines[1], "Item: none")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[2].startswith("M1 [merge, since "), lines[2])        # exactly M1: no F, no Q1
        self.assertIn("lib/shared.py", lines[2])
        head = self.git(train, "rev-parse", "HEAD")
        report = os.path.join(self.tmp, "record.json")
        toml = os.path.join(self.tmp, "in.toml")
        with open(toml, "w") as handle:
            handle.write("report = '%s'\nhead = '%s'\nworktree = '%s'\ngate = '%s'\nreview = []\n[[status]]\nid = 'M1'\nverdict = 'MET'\n"
                         "reason = ['lib/shared.py:1']\n" % (report, head, train, gate))
        rv.record_check(toml)
        with open(report) as handle:
            record = rv.load_record(handle.read())
        self.assertEqual([f["id"] for f in record["findings"]], ["M1"])
        load("check_mark_under_test", os.path.join("plugins", "core", "hooks", "check-mark.py")).write_mark(train, record)
        self.assertIsNone(self.verdict("wt/train-1"))

    def test_t14_a_normal_branch_still_needs_a_review(self):
        a = self.tree("a")
        self.commit(a, {"lib/a.py": "a1\n"})
        with self.assertRaises(rv.VerdictError) as ctx:
            rv.finding_list(a, [])
        self.assertIn("`review` must be a list of at least one review JSON path", str(ctx.exception))
        toml = os.path.join(self.tmp, "in.toml")
        with open(toml, "w") as handle:
            handle.write("report = '%s'\nhead = '%s'\nworktree = '%s'\ngate = 'none'\nreview = []\n" % (
                os.path.join(self.tmp, "r.json"), self.git(a, "rev-parse", "HEAD"), a))
        with self.assertRaises(rv.VerdictError) as ctx:
            rv.record_check(toml)
        self.assertIn("at least one review", str(ctx.exception))


class Absorbed(TrainCase):
    def test_a_train_absorbs_exactly_the_ready_changes_inside_it(self):
        a, b, c = self.tree("a"), self.tree("b"), self.tree("c")
        self.ready(a, {"lib/a.py": "a1\n"})
        self.ready(b, {"lib/b.py": "b1\n"}, open_=1)           # a problem left open
        self.commit(c, {"lib/c.py": "c1\n"})                   # no check
        d = self.tree("d")
        self.ready(d, {"lib/d.py": "d1\n"})                    # ready, but not in the train
        self.git(self.main, "branch", "wt/queue-1", "master")
        train = self.tree("train-1")
        for name in ("a", "b", "c"):
            self.git(train, "merge", "--no-ff", "--no-edit", "wt/" + name)
        self.assertEqual(ri.absorbed(self.main, "wt/train-1"), {"wt/a": self.git(self.main, "rev-parse", "wt/a")})

    def test_nested_riders_are_both_absorbed_and_a_branch_with_nothing_inside_absorbs_nothing(self):
        p = self.tree("p")
        self.ready(p, {"lib/p.py": "p1\n"})
        s = self.tree("s", "wt/p")
        self.ready(s, {"lib/s.py": "s1\n"})
        train = self.tree("train-1")
        self.git(train, "merge", "--no-ff", "--no-edit", "wt/s")
        self.assertEqual(sorted(ri.absorbed(self.main, "wt/train-1")), ["wt/p", "wt/s"])
        self.assertEqual(ri.absorbed(self.main, "refs/heads/wt/p"), {})
        self.assertEqual(sorted(ri.absorbed(self.main, "wt/s")), ["wt/p"])

    def test_a_branch_already_on_master_is_not_absorbed(self):
        a = self.tree("a")
        self.ready(a, {"lib/a.py": "a1\n"})
        self.git(self.main, "merge", "-q", "--ff-only", "wt/a")
        self.assertEqual(ri.absorbed(self.main, "master"), {})


class Bounded(TrainCase):
    def test_t15_one_judge_of_a_train_of_ten_riders_reads_few_trees(self):
        # 10 riders with 3 marks each. Design: "well under 100 tree reads" (21 ms each, so well under 5 s; the hook is killed at
        # 60 s and then cannot refuse). Without the per-commit tree cache every changed() call re-reads its trees and the count
        # is in the hundreds.
        names = []
        for n in range(10):
            wt = self.tree("r%d" % n)
            for k in range(3):
                self.ready(wt, {"lib/r%d_%d.py" % (n, k): "x\n"})
            names.append("r%d" % n)
        train = self.train(*names)
        self.gate(train)
        reads = []
        real = subprocess.run

        def counting(args, *rest, **more):
            if "ls-tree" in args:
                reads.append((args[2], args[-1]))             # (repo, commit) of `git -C <repo> ls-tree -r -z <commit>`
            return real(args, *rest, **more)
        with mock.patch.object(subprocess, "run", counting):
            self.assertIsNone(self.verdict("wt/train-1"))
        self.assertLess(len(reads), 100)
        self.assertEqual(len(reads), len(set(reads)))              # a commit's tree is read once per judge, not once per question


if __name__ == "__main__":
    unittest.main()
