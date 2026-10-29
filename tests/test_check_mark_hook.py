"""The check mark is made only by the SubagentStop hook, for a delegate:checker, from the record the checker wrote during its
own run (queue item `a-merge-check-of-a-train-is-recorded-but-leaves`, Q1; findings F1-F3 of review-check-mark).

The hook finds the record by what the checker's own `relay check record check` printed, not by the prompt's Report: label
(the label only breaks a tie); a checker that wrote no record is kept going once (exit 2); a mark made earlier is never
removed by the hook. `relay check record check` itself makes no mark. Real throwaway repositories under a temp dir.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import relay_git
import test_merge_train as tmt

ROOT = tmt.ROOT
RELAY = os.path.join(ROOT, "bin", "relay")
HOOK = os.path.join(ROOT, "plugins", "relay", "hooks", "check-mark.py")
START = "2026-10-22T10:00:00Z"
START_EPOCH = dt.datetime.fromisoformat(START.replace("Z", "+00:00")).timestamp()


class CheckerStop(tmt.TrainCase):
    def relay_record(self, train, gate, name="in.toml", env=None):
        head = self.git(train, "rev-parse", "HEAD")
        report = os.path.join(self.tmp, "rec-" + name + ".json")
        toml = os.path.join(self.tmp, name)
        with open(toml, "w") as handle:
            handle.write("report = '%s'\nhead = '%s'\nworktree = '%s'\ngate = '%s'\nreview = []\n[[status]]\nid = 'M1'\nverdict = 'MET'\n"
                         "reason = ['lib/shared.py:1']\n" % (report, head, train, gate))
        done = subprocess.run([sys.executable, RELAY, "check", "record", "check", "--input", toml], capture_output=True, text=True,
                              env={**os.environ, "RELAY_ROOT": ROOT, **(env or {})}, cwd=train)
        return head, report, done

    def transcript(self, train, label, printed=()):
        """A checker's transcript: its prompt (labelled `label`, started at START), then one record command per printed line."""
        path = os.path.join(self.tmp, "agent.jsonl")
        prompt = "Check: `%s`. Fixes: `none`. Worktree: `%s`. Check command: `bin/ci --quick`. Gate: `none`. Report: `%s`." % (label, train, label)
        entries = [{"type": "user", "timestamp": START, "message": {"role": "user", "content": prompt}}]
        for line in printed:
            entries.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]}})
            entries.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": line}]}})
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(e) + "\n" for e in entries))
        return path

    def age(self, path, seconds):
        os.utime(path, (START_EPOCH + seconds, START_EPOCH + seconds))

    def stop(self, transcript, active=False):
        event = {"hook_event_name": "SubagentStop", "agent_type": "delegate:checker", "agent_id": "a1", "cwd": self.main,
                 "agent_transcript_path": transcript, "stop_hook_active": active}
        return subprocess.run([sys.executable, "-I", HOOK], input=json.dumps(event), capture_output=True, text=True)

    def train_ready(self):
        self.shared_riders()
        train = self.train("a", "b")
        return train, self.gate(train)

    def test_q1_a_checker_prompted_with_an_old_report_that_records_into_a_new_file_gets_its_mark(self):
        # The train-8 shape: the prompt's Report: label names an old file (older than the start); the checker records into
        # another, new file. Before: the hook read the old file ("older than the checker's start"), made no mark.
        train, gate = self.train_ready()
        old = os.path.join(self.tmp, "old.json")
        with open(old, "w") as handle:
            handle.write("{}")
        self.age(old, -3600)
        head, report, done = self.relay_record(train, gate)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.age(report, 60)
        self.assertIn("lib/shared.py", self.verdict("wt/train-1"))        # the command made no mark (F2)
        out = self.stop(self.transcript(train, old, [done.stdout]))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.git(train, "log", "-1", "--format=%s"), "relay: check of " + head)
        self.assertIsNone(self.verdict("wt/train-1"))
        self.assertIn("mark %s: open 0" % head, "\n".join(tmt.rm.show(self.main, "wt/train-1")))

    def test_f2_a_worker_running_the_record_command_gets_no_mark(self):
        # No hook runs for a worker: the command only records; no "relay: check of" commit and the merge still refuses.
        train, gate = self.train_ready()
        before = self.git(train, "rev-parse", "HEAD")
        head, report, done = self.relay_record(train, gate)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("recorded %s (open 0, queued 0)" % report, done.stdout)
        self.assertEqual(self.git(train, "rev-parse", "HEAD"), before)
        self.assertIn("lib/shared.py", self.verdict("wt/train-1"))

    def test_f1_a_mark_made_earlier_stays_when_the_hook_cannot_make_one(self):
        # A checker made the mark of the head; a later checker (second stop, no record of its own) leaves it alone.
        # Before: the failure path dropped the mark of HEAD, and the merge fell back to "no check covers lib/shared.py".
        train, gate = self.train_ready()
        head, report, done = self.relay_record(train, gate)
        self.age(report, 60)
        first = self.stop(self.transcript(train, report, [done.stdout]))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIsNone(self.verdict("wt/train-1"))
        after_mark = self.git(train, "rev-parse", "HEAD")
        stale = os.path.join(self.tmp, "stale.json")
        with open(stale, "w") as handle:
            handle.write("{}")
        self.age(stale, -3600)
        second = self.stop(self.transcript(train, stale), active=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("check mark not written", json.loads(second.stdout)["systemMessage"])
        self.assertEqual(self.git(train, "rev-parse", "HEAD"), after_mark)
        self.assertIsNone(self.verdict("wt/train-1"))
        self.assertIn("mark %s: open 0" % head, "\n".join(tmt.rm.show(self.main, "wt/train-1")))

    def test_f1_an_invalid_record_does_not_remove_the_earlier_mark_either(self):
        train, gate = self.train_ready()
        head, report, done = self.relay_record(train, gate)
        self.age(report, 60)
        self.assertEqual(self.stop(self.transcript(train, report, [done.stdout])).returncode, 0)
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as handle:
            handle.write("not json")
        self.age(bad, 60)
        out = self.stop(self.transcript(train, bad))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIsNone(self.verdict("wt/train-1"))

    def test_f3_a_checker_that_recorded_nothing_is_kept_going_once_and_then_let_go_with_no_mark(self):
        # The train-8 case: the checker ends without running `relay check record check`. First stop: exit 2 and the reason on
        # stderr (SubagentStop keeps the agent going); second stop (stop_hook_active): exit 0, no mark, no loop.
        train, gate = self.train_ready()
        head = self.git(train, "rev-parse", "HEAD")
        old = os.path.join(self.tmp, "check2.json")
        with open(old, "w") as handle:
            handle.write("{}")
        self.age(old, -3600)
        first = self.stop(self.transcript(train, old))
        self.assertEqual(first.returncode, 2)
        self.assertIn("relay check record check --input", first.stderr)
        self.assertIn(head, first.stderr)
        self.assertEqual(first.stdout, "")
        second = self.stop(self.transcript(train, old), active=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("check mark not written", json.loads(second.stdout)["systemMessage"])
        self.assertEqual(self.git(train, "rev-parse", "HEAD"), head)

    def test_a_checker_that_recorded_the_label_file_itself_is_not_blocked(self):
        train, gate = self.train_ready()
        head, report, done = self.relay_record(train, gate)
        self.age(report, 60)
        out = self.stop(self.transcript(train, report))        # no printed line in the transcript: the label's file is new
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.git(train, "log", "-1", "--format=%s"), "relay: check of " + head)

    def test_two_new_records_the_label_breaks_the_tie(self):
        train, gate = self.train_ready()
        head, first, done_a = self.relay_record(train, gate, "a.toml")
        head, second, done_b = self.relay_record(train, gate, "b.toml")
        with open(first) as handle:
            record = json.load(handle)
        record["findings"][0]["reason"] = ["lib/shared.py:2"]
        with open(second, "w") as handle:
            json.dump(record, handle)
        self.age(first, 60)
        self.age(second, 120)                                  # the newer one is not the label
        out = self.stop(self.transcript(train, first, [done_a.stdout, done_b.stdout]))
        self.assertEqual(out.returncode, 0, out.stderr)
        stored = self.git(train, "show", "HEAD:.relay/checks/%s.check.json" % head)
        self.assertIn("lib/shared.py:1", stored)
        self.assertNotIn("lib/shared.py:2", stored)


    def git_spy(self):
        """A `git` on PATH that appends `<folder>|<arguments>` to a log for each process started; (env, log path)."""
        folder = os.path.join(self.tmp, "spy")
        os.makedirs(folder)
        log = os.path.join(folder, "calls.log")
        script = os.path.join(folder, "git")
        with open(script, "w") as handle:
            handle.write('#!/bin/sh\necho "$PWD|$*" >> "%s"\nexec "%s" "$@"\n' % (log, shutil.which("git")))
        os.chmod(script, 0o755)
        return {"PATH": folder + os.pathsep + os.environ["PATH"]}, log

    def test_one_check_record_asks_git_each_question_once_and_in_few_processes(self):
        # Measured 29 Oct (master ee932b26): one `relay check record check` on a train of two ready changes started 239 git
        # processes, 18 of them `diff --name-only` and 16 `rev-parse --git-common-dir`, most the same question again.
        # Now: no question (folder + arguments) is asked twice, and the run stays far under the old count. The ceiling 120 is
        # between the 81 measured after the fix and the 239 before; the fixture's three merges make it not a per-record bound.
        train, gate = self.train_ready()
        env, log = self.git_spy()
        head, report, done = self.relay_record(train, gate, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(log) as handle:
            calls = handle.read().splitlines()
        again = sorted({c for c in calls if calls.count(c) > 1})
        # lib/relay_queue.py reads the queue with its own git calls (not part of this item): its repeats are left out
        queue = ("cat-file --batch", "ls-tree --name-only HEAD .relay/queue/", "rev-parse --verify HEAD")
        self.assertEqual([a for a in (c.split("|", 1)[1].split(" ", 2)[2] for c in again) if not a.startswith(queue)], [])
        self.assertLess(len(calls), 120)


class GitAnswersKept(unittest.TestCase):
    """lib/relay_git.py: what cannot change is asked once; what can change only inside `reading()`."""

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, True)
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one"]):
            subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True)
        self.sha = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        self.started = []
        real = subprocess.run
        def counting(command, *a, **k):
            self.started.append(command)
            return real(command, *a, **k)
        patch = mock.patch.object(relay_git.subprocess, "run", counting)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_question_about_a_full_sha_is_asked_once(self):
        # A commit never changes: its parent listing asked twice starts one process.
        first = relay_git.git(self.repo, "rev-list", "--count", self.sha)
        second = relay_git.git(self.repo, "rev-list", "--count", self.sha)
        self.assertEqual((first, second, len(self.started)), ((0, "1"), (0, "1"), 1))

    def test_a_question_about_a_branch_is_asked_again_outside_reading_and_once_inside(self):
        # A branch can move: outside `reading()` two asks start two processes (2); inside, two asks start one (1), and the
        # window ends with the block, so the next ask starts one more (1 + 2 + 1 = 4 in all).
        relay_git.git(self.repo, "rev-parse", "HEAD")
        relay_git.git(self.repo, "rev-parse", "HEAD")
        with relay_git.reading():
            relay_git.git(self.repo, "rev-parse", "HEAD")
            relay_git.git(self.repo, "rev-parse", "HEAD")
        relay_git.git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(len(self.started), 2 + 1 + 1)

    def test_a_missing_object_is_not_remembered(self):
        # An object not there yet may be made later: a failed answer about a sha is not kept.
        absent = "0" * 40
        self.assertNotEqual(relay_git.git(self.repo, "cat-file", "-e", absent + "^{commit}")[0], 0)
        self.assertNotEqual(relay_git.git(self.repo, "cat-file", "-e", absent + "^{commit}")[0], 0)
        self.assertEqual(len(self.started), 2)


if __name__ == "__main__":
    unittest.main()
