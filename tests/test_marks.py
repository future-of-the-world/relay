"""Check marks, gate logs and `relay check show` (docs/plans/review-gate.md sections 4.1, 6 and 12.3: P3, P4).

Every repository is built in a temp directory; nothing touches the real repo. Time is a value the tests drive: the
waits take an injected `sleep`, so a lock "held 2 s" is ten polls of 0.2 s and no test measures a clock.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_marks  # noqa: E402
import relay_verdict  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


class Marks(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-marks-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for key, value in GIT_ENV.items():
            old = os.environ.get(key)
            os.environ[key] = value
            self.addCleanup(lambda k=key, o=old: os.environ.pop(k, None) if o is None else os.environ.__setitem__(k, o))
        self.main = os.path.join(self.tmp, "main")
        os.makedirs(os.path.join(self.main, ".relay"))
        git(self.tmp, "init", "-q", "-b", "master", self.main)
        with open(os.path.join(self.main, ".relay", "README.md"), "w") as handle:
            handle.write("x\n")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "init")
        self.wt = os.path.join(self.main, ".worktrees", "x")
        git(self.main, "worktree", "add", "-q", self.wt, "-b", "wt/x")
        with open(os.path.join(self.wt, "a.txt"), "w") as handle:
            handle.write("a\n")
        git(self.wt, "add", "a.txt")
        git(self.wt, "commit", "-q", "-m", "work")
        self.head = git(self.wt, "rev-parse", "HEAD")

    def mark(self, commit=None, open_=0, queued=0):
        commit = commit or self.head
        return {"schema": 2, "commit": commit, "verdict": {"open": open_, "queued": queued}, "check": "%s.check.json" % commit, "gate": None, "time": "t"}

    def lock(self):
        return relay_marks.lock_path(self.wt)

    # -- the module ---------------------------------------------------------------------------------------------

    def test_put_get_marks_roundtrip_and_one_commit(self):
        before = git(self.wt, "rev-list", "--count", "HEAD")
        relay_marks.put(self.wt, self.head, self.mark(), {"%s.check.json" % self.head: "{}\n"})
        # two files in exactly one new commit (hand-counted: the mark and the check record; no .md)
        self.assertEqual(int(git(self.wt, "rev-list", "--count", "HEAD")), int(before) + 1)
        self.assertEqual(sorted(git(self.wt, "show", "--name-only", "--format=", "HEAD").split()),
                         sorted([".relay/checks/%s.%s" % (self.head, e) for e in ("json", "check.json")]))
        got = relay_marks.get(self.main, "wt/x", self.head)
        self.assertEqual(got["verdict"], {"open": 0, "queued": 0})
        self.assertEqual([c for c, _ in relay_marks.marks(self.main, "wt/x")], [self.head])
        self.assertEqual(relay_marks.marks(self.main, "master"), [])

    def test_a_mark_that_is_not_well_formed_is_not_a_mark(self):
        folder = os.path.join(self.wt, ".relay", "checks")
        os.makedirs(folder)
        other = "1" * 40
        for name, text in (("%s.json" % self.head, "not json"), ("%s.json" % other, json.dumps({"commit": other, "verdict": {"open": "0"}}))):
            with open(os.path.join(folder, name), "w") as handle:
                handle.write(text)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "bad marks")
        self.assertEqual(relay_marks.marks(self.main, "wt/x"), [])
        self.assertIsNone(relay_marks.get(self.main, "wt/x", self.head))

    def test_gate_logs_need_head_first_and_exit_last(self):
        folder = os.path.join(self.wt, ".relay", "checks")
        os.makedirs(folder)
        a, b, c = self.head, "2" * 40, "3" * 40
        logs = {a: "head %s\ncmd bin/ci\nok\nexit 0\n" % a,
                b: "head %s\nexit 1\n" % b,
                c: "head %s\nrunning\n" % c}            # no exit line: not a result
        logs[b + "x"] = "x"                              # not a sha name
        for name, text in logs.items():
            with open(os.path.join(folder, name + ".gate.log"), "w") as handle:
                handle.write(text)
        with open(os.path.join(folder, "4" * 40 + ".gate.log"), "w") as handle:
            handle.write("head %s\nexit 0\n" % ("5" * 40))   # first line names another commit
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "logs")
        self.assertEqual(relay_marks.gate_logs(self.main, "wt/x"), sorted([(a, 0), (b, 1)]))

    def test_other_staged_changes_stay_staged_and_out_of_the_commit(self):
        with open(os.path.join(self.wt, "other.txt"), "w") as handle:
            handle.write("o\n")
        git(self.wt, "add", "other.txt")
        relay_marks.put(self.wt, self.head, self.mark(), {})
        self.assertEqual(git(self.wt, "show", "--name-only", "--format=", "HEAD"), ".relay/checks/%s.json" % self.head)
        self.assertEqual(git(self.wt, "diff", "--cached", "--name-only"), "other.txt")

    def test_a_locked_index_lands_on_a_retry(self):
        open(self.lock(), "w").close()
        polls = []

        def sleep(seconds):
            polls.append(seconds)
            os.remove(self.lock())      # the lock goes after the first wait

        relay_marks.put(self.wt, self.head, self.mark(), {}, sleep=sleep)
        self.assertEqual(polls, [1])
        self.assertIsNotNone(relay_marks.get(self.main, "wt/x", self.head))

    def test_a_lock_that_stays_gives_index_busy_after_the_retries(self):
        open(self.lock(), "w").close()
        polls = []
        with self.assertRaises(relay_marks.MarkError) as caught:
            relay_marks.put(self.wt, self.head, self.mark(), {}, sleep=polls.append)
        self.assertEqual(str(caught.exception), "index busy")
        self.assertEqual(len(polls), relay_marks.MARK_COMMIT_RETRIES)      # 3 retries, 1 s each
        self.assertIsNone(relay_marks.get(self.main, "wt/x", self.head))

    def test_drop_removes_mark_and_check_data_only(self):
        relay_marks.put(self.wt, self.head, self.mark(), {"%s.check.json" % self.head: "{}\n", "%s.review.json" % self.head: "{}\n"})
        self.assertTrue(relay_marks.drop(self.wt, self.head))
        self.assertIsNone(relay_marks.get(self.main, "wt/x", self.head))
        self.assertEqual(git(self.wt, "ls-tree", "--name-only", "HEAD", ".relay/checks/"), ".relay/checks/%s.review.json" % self.head)
        self.assertFalse(relay_marks.drop(self.wt, self.head))               # nothing left to drop

    # -- relay check show: P3, P4 -------------------------------------------------------------------------------

    def finding(self, fid, kind, path="a.txt", line=1):
        return {"id": fid, "path": path, "line": line, "severity": "MEDIUM", "rank": "medium", "kind": kind, "summary": "s " + fid, "failing_case": ["x"]}

    def gate_log(self):
        folder = os.path.join(self.wt, ".relay", "checks")
        os.makedirs(folder, exist_ok=True)
        log = os.path.join(folder, "%s.gate.log" % self.head)
        with open(log, "w") as handle:
            handle.write("head %s\ncmd bin/ci --quick\nci: green\nexit 0\n" % self.head)
        relay_marks.commit_file(self.wt, log, "relay: gate of %s" % self.head)

    def record(self, *kinds):
        """A stored check record whose findings have these kinds (hand-written: Fn, the n-th kind)."""
        findings = [dict(self.finding("F%d" % n, kind), source="a.json", since=self.head, verdict="MET") for n, kind in enumerate(kinds, 1)]
        return {"schema": 2, "type": "check", "head": self.head, "branch": "wt/x", "item": None, "gate": None, "scope": [], "notes": [], "findings": findings}

    def stored(self, record="default"):
        """A gate log, then a mark whose check record holds four findings, two of kind outside (hand-written), a question
        and one inside. `record` replaces the stored record's text (None: not stored)."""
        self.gate_log()
        text = json.dumps(self.record("inside", "outside", "outside", "question")) if record == "default" else record
        files = {}
        if text is not None:
            files["%s.check.json" % self.head] = text
        relay_marks.put(self.wt, self.head, self.mark(queued=1), files)

    def test_P3_prints_exactly_three_lines(self):
        self.stored()
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "check", "show", "-C", self.main, "wt/x"],
                              capture_output=True, text=True, env={**os.environ, "RELAY_ROOT": ROOT})
        self.assertEqual(done.returncode, 0, done.stderr)
        # worked by hand: gate exit 0; mark open 0 queued 1 reviewed = the head; the check record has two findings of kind outside
        # (F2, F3); the inside finding and the question do not count
        self.assertEqual(done.stdout.splitlines(), [
            "gate %s: exit 0" % self.head,
            "mark %s: open 0, queued 1" % self.head,
            "outside: 2 in the check",
        ])

    def test_outside_is_counted_from_the_json(self):
        """The record holds two findings, one outside and one inside: the count is 1 (hand: one finding of kind outside)."""
        self.stored(json.dumps(self.record("outside", "inside")))
        self.assertEqual(relay_marks.show(self.main, "wt/x", sleep=lambda s: None)[2], "outside: 1 in the check")

    def test_a_mark_without_a_stored_check_gives_no_count_and_says_so(self):
        self.stored(record=None)
        self.assertEqual(relay_marks.show(self.main, "wt/x", sleep=lambda s: None)[2], "outside: check not stored")

    def test_an_invalid_check_json_gives_a_message_not_a_count(self):
        self.stored(record=json.dumps({"schema": 2, "type": "check", "head": "x"}))
        line = relay_marks.show(self.main, "wt/x", sleep=lambda s: None)[2]
        self.assertTrue(line.startswith("outside: unknown (the check data %s.check.json is not valid: " % self.head), line)

    def test_a_schema_1_check_is_reported_with_the_migration_line(self):
        self.stored(record=json.dumps({"schema": 1, "type": "check", "head": self.head}))
        self.assertIn("relay check migrate", relay_marks.show(self.main, "wt/x", sleep=lambda s: None)[2])

    def test_a_schema_1_mark_is_not_a_mark(self):
        old = {"schema": 1, "commit": self.head, "verdict": {"open": 0, "queued": 0, "reviewed": self.head}, "review": "r.review.json",
               "check": "%s.check.json" % self.head, "gate": None, "time": "t"}
        relay_marks.put(self.wt, self.head, old, {})
        self.assertIsNone(relay_marks.get(self.main, "wt/x", self.head))      # a guard of the new code fails closed on it

    def test_P3_without_a_mark_is_still_three_lines(self):
        lines = relay_marks.show(self.main, "wt/x", sleep=lambda s: None)
        self.assertEqual(lines, ["gate: none yet", "mark: no mark yet", "outside: unknown (no mark yet)"])

    def test_P4_waits_while_the_lock_is_held_then_prints_the_new_mark(self):
        open(self.lock(), "w").close()
        polls = []

        def sleep(seconds):
            polls.append(seconds)
            if len(polls) == 10:        # 10 polls of 0.2 s = the lock held 2 s, then the hook's commit lands
                os.remove(self.lock())
                relay_marks.put(self.wt, self.head, self.mark(open_=2), {})

        lines = relay_marks.show(self.main, "wt/x", sleep=sleep)
        self.assertEqual(len(polls), 10)
        self.assertEqual(lines[1], "mark %s: open 2, queued 0" % self.head)

    def test_P4_a_lock_held_past_the_bound_prints_no_mark_yet_within_it(self):
        open(self.lock(), "w").close()
        polls = []
        lines = relay_marks.show(self.main, "wt/x", sleep=polls.append)
        self.assertEqual(lines[1], "mark: no mark yet")
        # 10 s bound at 0.2 s a poll = 50 polls, no more
        self.assertEqual(len(polls), 50)
        self.assertEqual(sum(polls), relay_marks.CHECK_SHOW_WAIT_S)

    def test_an_unknown_branch_is_an_error_not_an_empty_answer(self):
        with self.assertRaises(relay_marks.MarkError):
            relay_marks.show(self.main, "wt/none", sleep=lambda s: None)


if __name__ == "__main__":
    unittest.main()
