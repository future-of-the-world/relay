"""`relay queue migrate` (moved out of test_queue.py to keep each test file under the line cap)."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import test_queue as tq  # noqa: E402


def old_shape(title, state="open", taken_by="", closed_by="", test="", dropped_why=None, kind="feature"):
    """An item file in the shape before dated events (what the migration reads)."""
    data = {"kind": kind, "state": state, "ip": 0, "time": 10, "found": "2026-10-01", "found_in": "test", "title": title,
            "what": ["what is wanted here"], "why": ["it matters"], "taken_by": taken_by, "closed_by": closed_by, "test": test,
            "dropped_why": dropped_why}
    return json.dumps(data, indent=2) + "\n"


class TestMigrate(tq.Base):
    """`relay queue migrate` (lib/relay_queue_migrate.py) on a scratch repository whose commits carry chosen times."""

    def commit_at(self, files, when, message="queue", remove=()):
        env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        with mock.patch.dict(os.environ, env):
            for rel in remove:
                tq.git(self.main, "rm", "-q", rel)
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
        job = self.read("job.json")
        self.assertEqual((job["found_at"], job["taken_at"], job["taken_by"], job["closed_at"], job["test"], job["dropped_at"]),
                         ("2026-10-01T10:00:00Z", "2026-10-01T13:00:00Z", "wt/b", "2026-10-01T16:00:00Z", "tests/t.py::t", None))
        self.assertTrue(set(job).isdisjoint(tq.rq.OLD_ONLY))
        gone = self.read("gone.json")
        self.assertEqual((gone["found_at"], gone["dropped_at"], gone["dropped_why"], gone["taken_at"], gone["taken_by"]),
                         ("2026-10-02T09:00:00Z", "2026-10-02T10:00:00Z", ["no"], None, None))
        plain = self.read("plain.json")
        self.assertEqual((plain["found_at"], plain["taken_at"], plain["taken_by"], plain["test"]), ("2026-10-03T08:00:00Z", None, None, None))
        busy = self.read("busy.json")
        self.assertEqual((busy["found_at"], busy["taken_at"], busy["taken_by"]), ("2026-10-03T09:00:00Z", "2026-10-03T09:00:00Z", "wt/c"))
        self.assertEqual(tq.rq.check_files(self.main), [])

    def test_f4_it_runs_again_and_changes_only_what_is_still_old(self):
        self.history()
        self.run_relay("migrate", "-C", self.main)
        tq.git(self.main, "add", "-A")
        tq.git(self.main, "commit", "-q", "-m", "migrated")
        before = self.read("plain.json")
        again = self.run_relay("migrate", "-C", self.main)
        self.assertEqual((again.returncode, again.stdout.startswith("nothing to migrate")), (0, True), again.stdout)
        self.assertEqual(tq.git(self.main, "status", "--porcelain"), "")
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
        # a file left in the gone done/ folder is reported with the way out
        os.makedirs(os.path.join(self.main, ".relay", "queue", "done"), exist_ok=True)
        with open(os.path.join(self.main, ".relay", "queue", "done", "late.json"), "w") as handle:
            handle.write(tq.new_shape())
        stray = self.run_relay("check", "-C", self.main)
        self.assertEqual(stray.returncode, 1)
        self.assertIn(".relay/queue/done/late.json: the done/ folder is gone: run `relay queue migrate`", stray.stdout)

    def test_json_lists_the_done_items_too_with_their_dates_and_the_table_does_not(self):
        self.history()
        self.run_relay("migrate", "-C", self.main)
        tq.git(self.main, "add", "-A")
        tq.git(self.main, "commit", "-q", "-m", "migrated")
        items = json.loads(self.run_relay("json", "-C", self.main).stdout)
        self.assertEqual(sorted((i["slug"], i["state"]) for i in items),
                         [("busy", "taken"), ("gone", "dropped"), ("job", "done"), ("plain", "open")])
        job = next(i for i in items if i["slug"] == "job")
        self.assertEqual((job["found_at"], job["taken_at"], job["closed_at"]), ("2026-10-01T10:00:00Z", "2026-10-01T13:00:00Z", "2026-10-01T16:00:00Z"))
        table = self.run_relay("-C", self.main).stdout
        self.assertNotIn("gone", table)
        self.assertNotIn("job", table)

    def test_add_writes_only_the_new_shape(self):
        tq.rq.add(self.main, "feature", "Fresh item here", why="w", minutes=5, now="2026-10-22T08:30:00Z", **tq.QUIET)
        data = json.loads(tq.git(self.main, "show", "master:.relay/queue/fresh-item-here.json"))
        self.assertEqual((data["found_at"], data["taken_at"], data["taken_by"], data["closed_at"], data["test"], data["dropped_at"], data["dropped_why"]),
                         ("2026-10-22T08:30:00Z", None, None, None, None, None, None))
        self.assertTrue(set(data).isdisjoint(tq.rq.OLD_ONLY))
