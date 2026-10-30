"""The paid run's state from dated records (lib/relay_paid.py), `bin/paid-cost state`, the writers in bin/ci and `relay sync`.
Every test builds a temporary repository and a temporary RELAY_HOME; time and the process check are values passed in."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import relay_ci  # noqa: E402
import relay_land_waits  # noqa: E402
import relay_paid  # noqa: E402
from relay_paid import PaidEvent  # noqa: E402
from test_gate import GIT_ENV, git, write  # noqa: E402

PAID_COST = os.path.join(ROOT, "bin", "paid-cost")
START = "2026-10-30T10:00:00+00:00"
ALIVE, DEAD = (lambda pid: True), (lambda pid: False)
GREEN, REDV = (lambda data: True), (lambda data: False)


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-paid-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        self.main = os.path.join(self.tmp, "main")
        os.makedirs(self.main)
        self.env = {**os.environ, **GIT_ENV}
        patch = mock.patch.dict(os.environ, GIT_ENV)
        patch.start()
        self.addCleanup(patch.stop)
        git(self.main, "init", "-q", "-b", "master")
        write(os.path.join(self.main, "README.md"), "x\n")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "init")
        self.head = git(self.main, "rev-parse", "HEAD")
        self.home = os.path.join(self.tmp, "home")

    def started(self, ts=START, pid=4242, head=None):
        relay_paid.record(self.main, PaidEvent("started", ts, head=head or self.head, pid=pid))

    def evals(self, name, started_at="2026-10-30T10:01:00.000Z", seconds=600, head=None, partial=False, branch="master"):
        # a record with no cases and not partial is a pass by bin/eval-record; partial is not
        folder = relay_paid.evals_folder(self.main, self.home)
        data = {"startedAt": started_at, "durationSeconds": seconds, "partial": partial, "cases": [], "head": head or self.head, "branch": branch}
        write(os.path.join(folder, name + ".json"), json.dumps(data))

    def state(self, alive=DEAD, judge=GREEN):
        return relay_paid.state(self.main, self.home, alive, judge)


class State(Repo):
    def test_no_started_record_is_free(self):
        self.assertEqual(self.state().name, "free")

    def test_a_live_run_with_no_record_is_going(self):
        # the record of the run does not exist yet and its process is alive
        self.started()
        s = self.state(alive=ALIVE)
        self.assertEqual((s.name, s.since), ("going", START))

    def test_a_dead_run_with_no_record_stopped_without_a_verdict(self):
        self.started()
        s = self.state(alive=DEAD)
        self.assertEqual(s.name, "stopped")
        self.assertIn("start the paid run again", s.line)

    def test_green_record_without_sync_waits_for_relay_sync(self):
        self.started()
        self.evals("a")
        s = self.state()
        self.assertEqual(s.name, "waits_sync")
        self.assertIn("run relay sync", s.line)

    def test_green_record_then_a_sync_after_its_end_is_free(self):
        # the run ends 10:01:00 + 600 s = 10:11:00; a sync at 10:20 is after it, a sync at 10:05 (during the run) is not
        self.started()
        self.evals("a")
        relay_paid.record(self.main, PaidEvent("synced", "2026-10-30T10:05:00+00:00", head=self.head))
        self.assertEqual(self.state().name, "waits_sync")
        relay_paid.record(self.main, PaidEvent("synced", "2026-10-30T10:20:00+00:00", head=self.head))
        self.assertEqual(self.state().name, "free")

    def test_a_red_record_is_red_whatever_a_sync_says(self):
        self.started()
        self.evals("a", partial=True)
        relay_paid.record(self.main, PaidEvent("synced", "2026-10-30T10:20:00+00:00", head=self.head))
        self.assertEqual(self.state(judge=REDV).name, "red")

    def test_a_record_of_an_earlier_run_does_not_answer_a_newer_start(self):
        # the earlier run began 09:00 and was green; a new run started 10:00 on the same head has no record yet
        self.evals("old", started_at="2026-10-30T09:00:00.000Z")
        self.started()
        self.assertEqual(self.state(alive=ALIVE).name, "going")

    def test_a_record_of_another_head_or_branch_is_not_this_runs(self):
        self.started()
        self.evals("a", head="f" * 40)
        self.evals("b", branch="other")
        self.assertEqual(self.state(alive=ALIVE).name, "going")

    def test_the_real_judge_reads_the_stored_record(self):
        # bin/eval-record's own rule: not partial and no failing case is a pass, partial is not
        self.started()
        self.evals("a", partial=True)
        self.assertEqual(relay_paid.state(self.main, self.home, DEAD).name, "red")
        self.evals("b", started_at="2026-10-30T10:02:00.000Z")
        self.assertEqual(relay_paid.state(self.main, self.home, DEAD).name, "waits_sync")

    def test_parse_event_rejects_what_is_not_an_event(self):
        self.assertIsNone(relay_paid.parse_event("not json"))
        self.assertIsNone(relay_paid.parse_event(json.dumps({"kind": "bogus", "ts": START})))
        self.assertIsNone(relay_paid.parse_event(json.dumps({"kind": "started", "ts": "yesterday"})))
        self.assertIsNone(relay_paid.parse_event(json.dumps({"kind": "started", "ts": START, "pid": "7"})))
        self.assertIsNone(relay_paid.parse_event(json.dumps({"kind": "started", "ts": START, "extra": 1})))
        self.assertEqual(relay_paid.parse_event(json.dumps({"kind": "synced", "ts": START, "head": "ab"})), PaidEvent("synced", START, head="ab"))

    def test_the_command_prints_the_state(self):
        self.started(pid=os.getpid())
        done = subprocess.run([sys.executable, PAID_COST, "state", "--repo", self.main], capture_output=True, text=True,
                              env={**self.env, "RELAY_HOME": self.home})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.startswith("going: a paid run has been going since " + START), done.stdout)


class Writers(Repo):
    def ci(self, root):
        return relay_ci.Ci(root, False, env=dict(self.env))

    def events(self):
        return relay_paid.read_events(self.main)

    def test_a_full_run_on_the_default_branch_head_writes_started(self):
        said = []
        ci = self.ci(self.main)
        ci.say = said.append
        self.assertTrue(ci.note_paid_start())
        (event,) = self.events()
        self.assertEqual((event.kind, event.head, event.pid), ("started", self.head, os.getpid()))

    def test_a_detached_worktree_of_the_default_head_writes_started(self):
        tree = os.path.join(self.tmp, "paid")
        git(self.main, "worktree", "add", "-q", "--detach", tree, "master")
        self.assertTrue(self.ci(tree).note_paid_start())
        self.assertEqual(len(self.events()), 1)

    def test_a_full_run_in_a_task_worktree_writes_none(self):
        # disabled rule (no branch test): the task branch would write a started record and hold every paid-path landing
        tree = os.path.join(self.tmp, "task")
        git(self.main, "worktree", "add", "-q", tree, "-b", "wt/t")        # a fresh task branch: its head is the default branch's head, only its name tells
        self.assertTrue(self.ci(tree).note_paid_start())
        self.assertEqual(self.events(), [])

    def test_sync_writes_synced_and_names_the_waiting_branches(self):
        lines = relay_land_waits.after_sync(self.main)
        (event,) = self.events()
        self.assertEqual((event.kind, event.head), ("synced", self.head))
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
