"""A recorded merge check always leaves the mark the merge hook reads (queue item
`a-merge-check-of-a-train-is-recorded-but-leaves`, Q1).

The mark used to be made only by the SubagentStop hook from the Report: label of the checker's prompt; a checker that
recorded its check some other way (or whose hook read another file) left a record and no mark. Now `relay check record
check` commits the mark itself. Real throwaway repositories under a temp dir.
"""
import os
import subprocess
import sys
import unittest

import test_merge_train as tmt

ROOT = tmt.ROOT
RELAY = os.path.join(ROOT, "bin", "relay")


class RecordMakesMark(tmt.TrainCase):
    def relay_record(self, train, gate, name="in.toml"):
        head = self.git(train, "rev-parse", "HEAD")
        toml = os.path.join(self.tmp, name)
        with open(toml, "w") as handle:
            handle.write("report = '%s'\nhead = '%s'\nworktree = '%s'\ngate = '%s'\nreview = []\n[[status]]\nid = 'M1'\nverdict = 'MET'\n"
                         "reason = ['lib/shared.py:1']\n" % (os.path.join(self.tmp, "rec-" + name + ".json"), head, train, gate))
        done = subprocess.run([sys.executable, RELAY, "check", "record", "check", "--input", toml], capture_output=True, text=True,
                              env={**os.environ, "RELAY_ROOT": ROOT}, cwd=train)
        return head, done

    def test_q1_a_train_check_recorded_by_the_command_leaves_the_mark_and_the_hook_accepts_it(self):
        # Two riders both changed lib/shared.py, so the train needs its own check (M1). Recording it with no hook involved
        # must commit "relay: check of <head>" and the merge hook must then let the train land: before, it was refused for
        # "1 non-inert file changed after the mark" (the riders' marks do not cover the combined file).
        self.shared_riders()
        train = self.train("a", "b")
        gate = self.gate(train)
        self.assertIn("lib/shared.py", self.verdict("wt/train-1"))        # no mark of the train yet
        head, done = self.relay_record(train, gate)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.git(train, "log", "-1", "--format=%s"), "relay: check of " + head)
        self.assertIsNone(self.verdict("wt/train-1"))
        self.assertIn("mark %s: open 0" % head, "\n".join(tmt.rm.show(self.main, "wt/train-1")))

    def test_q1_the_hook_after_the_command_adds_no_second_mark_commit(self):
        self.shared_riders()
        train = self.train("a", "b")
        gate = self.gate(train)
        head, done = self.relay_record(train, gate)
        self.assertEqual(done.returncode, 0, done.stderr)
        before = self.git(train, "rev-parse", "HEAD")
        with open(os.path.join(self.tmp, "rec-in.toml.json")) as handle:
            record = tmt.rv.load_record(handle.read())
        tmt.load("check_mark_under_test", os.path.join("plugins", "core", "hooks", "check-mark.py")).write_mark(train, record)
        self.assertEqual(self.git(train, "rev-parse", "HEAD"), before)

    def test_q1_when_the_mark_cannot_be_committed_the_command_refuses_and_says_what_to_run(self):
        self.shared_riders()
        train = self.train("a", "b")
        gate = self.gate(train)
        lock = tmt.rm.lock_path(train)
        with open(lock, "w"):
            pass
        self.addCleanup(lambda: os.path.exists(lock) and os.remove(lock))
        head, done = self.relay_record(train, gate)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no check mark was made", done.stderr)
        self.assertIn("run relay check record check again", done.stderr)


if __name__ == "__main__":
    unittest.main()
