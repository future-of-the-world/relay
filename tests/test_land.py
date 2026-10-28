"""`relay land` (lib/relay_land.py, design relay-land): every test builds a temporary repository; the gate is a script that counts
its runs, set through kit.toml [gate] ci. Nothing touches the live .relay/."""
import json
import os
import signal
import stat
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

from relay_testbase import load_hook  # noqa: E402
from test_gate import RELAY, Fixture, git, read, write  # noqa: E402

import relay_lanes  # noqa: E402
import relay_land  # noqa: E402

HOOK = os.path.join(ROOT, "plugins", "relay", "hooks", "merge.py")
WAIT = 60       # seconds a test waits for a condition (a file, a line, an exit)


class Land(Fixture):
    GATE = 'echo run >> "%(counter)s"\nexit 0\n'

    def start(self, gate=None, kit_extra=""):
        """main on master and a checked branch wt/x (a code commit, a mark with open 0)."""
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate=(gate or self.GATE) % {"counter": self.counter, "tmp": self.tmp})
        if kit_extra:
            kit = os.path.join(self.main, ".claude", "kit.toml")
            write(kit, read(kit) + kit_extra)
            git(self.main, "add", "-A")
            git(self.main, "commit", "-q", "-m", "settings")
            git(self.wt, "merge", "-q", "--no-edit", "master")
        self.mark(self.wt)

    def mark(self, wt, open_=0, sha=None):
        """a mark for `sha` (default the head) in the worktree, as `relay: check of` commits make them"""
        sha = sha or git(wt, "rev-parse", "HEAD")
        data = {"schema": 2, "commit": sha, "check": sha + ".check.json", "verdict": {"open": open_, "queued": 0}}
        write(os.path.join(wt, ".relay", "checks", sha + ".json"), json.dumps(data))
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "relay: check of " + sha)
        return sha

    def runs(self):
        return len(read(self.counter).splitlines()) if os.path.exists(self.counter) else 0

    def master_commit(self, rel, text, message="master moves"):
        write(os.path.join(self.main, rel), text)
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", message)

    def land(self, branch="wt/x", *args, env=None, wait=True):
        proc = subprocess.Popen([sys.executable, RELAY, "land", branch, "-C", self.main, *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd=self.main, env=env or self.env)
        if not wait:
            return proc
        out, err = proc.communicate(timeout=WAIT * 5)
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def events(self):
        events, bad = relay_land.read_events(self.main)
        self.assertEqual(bad, 0)
        return events

    def done(self):
        return [e for e in self.events() if e.kind == "done"]

    def master(self):
        return git(self.main, "rev-parse", "master")

    def wait_for(self, path):
        import time
        end = time.monotonic() + WAIT
        while not os.path.exists(path):
            self.assertLess(time.monotonic(), end, "never appeared: " + path)
            time.sleep(0.05)


class Landing(Land):
    def test_land_takes_gates_lands(self):
        # master moved by code: the take is a code take, the gate runs once on it, and master ends at the branch head
        self.start()
        self.master_commit("lib/b.py", "b\n")
        run = self.land()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.runs(), 1)
        self.assertIn("landed wt/x on master", run.stdout)
        # the landed tree has a green gate log whose head is the take (a merge commit)
        take = git(self.main, "log", "master", "--merges", "-n1", "--format=%H")
        self.assertTrue(os.path.exists(os.path.join(self.main, ".relay", "checks", take + ".gate.log")))
        (event,) = self.done()
        self.assertEqual((event.outcome, event.gates_run), ("landed", 1))
        self.assertEqual(event.sha, self.master())
        self.assertEqual(git(self.main, "for-each-ref", "refs/heads/wt/train-*"), "")
        self.assertTrue(relay_lanes.landing(self.main, "master", "wt/x", None)[0])        # the reflog names the branch

    def test_land_starts_no_agent(self):
        self.start()
        bin_dir = os.path.join(self.tmp, "fakebin")
        marker = os.path.join(self.tmp, "agent-started")
        write(os.path.join(bin_dir, "claude"), '#!/bin/sh\necho started >> "%s"\n' % marker, stat.S_IRWXU)
        env = {**self.env, "PATH": bin_dir + os.pathsep + self.env["PATH"]}
        self.master_commit("lib/b.py", "b\n")
        self.assertEqual(self.land(env=env).returncode, 0)
        self.assertFalse(os.path.exists(marker))

    def test_land_inert_take_reuses_gate(self):
        # the branch is gated at its code commit; master then moves only by the handover: the take is inert, no gate runs
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate=self.GATE % {"counter": self.counter})
        code = git(self.wt, "rev-parse", "HEAD")
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.mark(self.wt, sha=code)
        self.master_commit("docs/handover.md", "state\n")
        run = self.land()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.done()[0].gates_run, 0)
        self.assertIn("gate reused", run.stdout)

    def test_land_inert_move_during_gate(self):
        # a handover record lands on master while the gate runs: the fast-forward fails, the lander takes again and lands;
        # the gate ran once (the take after an inert move reuses it)
        flag = os.path.join(self.tmp, "moved")
        self.counter = os.path.join(self.tmp, "runs")
        main_dir = os.path.join(self.tmp, "main")
        script = ('echo run >> "%s"\nif [ ! -e "%s" ]; then touch "%s"; mkdir -p "%s/docs"; echo moved > "%s/docs/handover.md"; '
                  'git -C "%s" add docs/handover.md; git -C "%s" commit -q -m handover; fi\nexit 0\n') % (
                      self.counter, flag, flag, main_dir, main_dir, main_dir, main_dir)
        self.repo(gate=script)
        self.mark(self.wt)
        self.master_commit("lib/b.py", "b\n")
        run = self.land()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.runs(), 1)
        (event,) = self.done()
        self.assertEqual((event.outcome, event.gates_run, event.inert_moves, event.code_moves), ("landed", 1, 1, 0))
        self.assertEqual(git(self.main, "show", "master:docs/handover.md"), "moved")

    def test_land_conflict_stops(self):
        self.start()
        write(os.path.join(self.wt, "lib", "a.py"), "branch\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "branch edit")
        self.mark(self.wt)
        self.master_commit("lib/a.py", "master\n")
        before = self.master()
        run = self.land()
        self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
        self.assertIn("lib/a.py", run.stdout)
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")
        self.assertEqual(self.master(), before)
        self.assertEqual(self.runs(), 0)
        # the printed next step is the exact shape of the fix unit
        for words in ("kind fix", "findings = the branch's last review JSON", "no item"):
            self.assertIn(words, run.stdout)

    def test_conflict_fix_unit_then_land(self):
        # a conflict, the fixer resolves it by hand: land refuses before a gate until the resolved file is checked, then lands
        self.start()
        write(os.path.join(self.wt, "lib", "a.py"), "branch\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "branch edit")
        self.mark(self.wt)
        self.master_commit("lib/a.py", "master\n")
        self.assertEqual(self.land().returncode, 3)
        subprocess.run(["git", "-C", self.wt, "merge", "--no-edit", "master"], capture_output=True, env=self.env)
        write(os.path.join(self.wt, "lib", "a.py"), "both\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "--no-edit")
        refused = self.land()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("lib/a.py", refused.stderr + refused.stdout)
        self.assertEqual(self.runs(), 0)                     # refused before any gate
        self.mark(self.wt)                                   # the check of the resolved head
        run = self.land()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.runs(), 1)

    def test_land_open_mark_refused_before_gate(self):
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate=self.GATE % {"counter": self.counter})
        self.mark(self.wt, open_=1)
        self.master_commit("lib/b.py", "b\n")
        run = self.land()
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("open", run.stdout + run.stderr)
        self.assertEqual(self.runs(), 0)
        self.assertEqual(self.done()[0].outcome, "refused")

    def test_land_red_gate_keeps_master(self):
        self.start(gate="exit 1\n")
        before = self.master()
        run = self.land()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertEqual(self.master(), before)
        self.assertEqual(self.done()[0].outcome, "red")


class Dirty(Land):
    def test_land_dirty_overlap_at_start(self):
        self.start()
        write(os.path.join(self.main, "lib", "a.py"), "mine\n")        # untracked in the main checkout; the branch brings lib/a.py
        run = self.land()
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("lib/a.py", run.stdout)
        self.assertEqual(self.runs(), 0)

    def test_land_dirty_unrelated_lands(self):
        self.start()
        write(os.path.join(self.main, "notes.txt"), "mine\n")          # the landing does not write this file
        run = self.land()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(read(os.path.join(self.main, "notes.txt")), "mine\n")

    def test_land_ff_dirty_main(self):
        # the file appears in the main checkout while the gate runs: the fast-forward is refused, master did not move: dirty, no loop
        gate = 'echo run >> "%(counter)s"\nmkdir -p "%(tmp)s/main/lib"; echo mine > "%(tmp)s/main/lib/a.py"\nexit 0\n'
        self.start(gate=gate)
        before = self.master()
        run = self.land()
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("lib/a.py", run.stdout)
        self.assertEqual(self.master(), before)
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.done()[0].outcome, "dirty")

    def test_land_ff_index_lock_retry(self):
        # index.lock exists when the fast-forward runs: the lander says it tries again; the test frees the lock on that line
        # (a condition, not a delay), and the landing completes
        gate = 'echo run >> "%(counter)s"\ntouch "%(tmp)s/main/.git/index.lock"\nexit 0\n'
        self.start(gate=gate)
        proc = self.land(wait=False)
        said = ""
        for line in proc.stderr:
            said += line
            if "trying again" in line:
                os.remove(os.path.join(self.main, ".git", "index.lock"))
                break
        out, err = proc.communicate(timeout=WAIT * 3)
        self.assertIn("trying again", said)
        self.assertEqual(proc.returncode, 0, out + err)


class Lock(Land):
    def slow_gate(self):
        return ('echo run >> "%(counter)s"\ntouch "%(tmp)s/started"\n'
                'while [ ! -e "%(tmp)s/go" ]; do sleep 0.05; done\nexit 0\n')

    def test_land_two_wait_in_turn(self):
        self.start(gate=self.slow_gate())
        # a second branch, checked, with a code commit of its own
        wt_y = os.path.join(self.main, ".worktrees", "y")
        git(self.main, "worktree", "add", "-q", wt_y, "-b", "wt/y", "master")
        write(os.path.join(wt_y, "lib", "y.py"), "y\n")
        git(wt_y, "add", "-A")
        git(wt_y, "commit", "-q", "-m", "work y")
        self.mark(wt_y)
        first = self.land("wt/x", wait=False)
        self.wait_for(os.path.join(self.tmp, "started"))
        second = self.land("wt/y", wait=False)
        import time
        end = time.monotonic() + WAIT
        while not any(e.kind == "asked" and e.branch == "wt/y" for e in relay_land.read_events(self.main)[0]):
            self.assertLess(time.monotonic(), end)
            time.sleep(0.05)
        write(os.path.join(self.tmp, "go"), "")
        out1, err1 = first.communicate(timeout=WAIT * 3)
        out2, err2 = second.communicate(timeout=WAIT * 3)
        self.assertEqual((first.returncode, second.returncode), (0, 0), out1 + err1 + out2 + err2)
        self.assertIn("waits for the landing of wt/x", err2)
        events = self.events()
        done_x = next(e for e in events if e.kind == "done" and e.branch == "wt/x")
        locked_y = next(e for e in events if e.kind == "locked" and e.branch == "wt/y")
        self.assertGreaterEqual(locked_y.ts, done_x.ts)
        # y's take held x's head: both files are on master, and y's take has x's landed head as an ancestor
        self.assertEqual(git(self.main, "merge-base", "--is-ancestor", done_x.sha, "master", check=False), "")
        self.assertEqual(git(self.main, "ls-tree", "--name-only", "master", "lib/"), "lib/a.py\nlib/y.py")
        self.assertEqual(git(self.main, "for-each-ref", "refs/heads/wt/train-*"), "")

    def test_hand_merge_refused_while_landing(self):
        self.start()
        handle = relay_land.lock(self.main, "wt/z", lambda line: None)
        self.addCleanup(handle.close)
        module = load_hook("merge_hook_land_test", HOOK)
        import contextlib
        import io
        err = io.StringIO()
        hook = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.main, "tool_input": {"command": "git merge --ff-only wt/x"}}
        with contextlib.redirect_stderr(err):
            rc = module.pre(hook)
        self.assertEqual(rc, 2)
        self.assertIn("a landing is running (wt/z", err.getvalue())

    def test_land_lock_frees_on_kill(self):
        self.start(gate=self.slow_gate())
        proc = self.land(wait=False)
        self.wait_for(os.path.join(self.tmp, "started"))
        self.assertIsNotNone(relay_land.holder(self.main))
        proc.send_signal(signal.SIGKILL)
        proc.communicate(timeout=WAIT)
        self.assertIsNone(relay_land.holder(self.main))           # the OS freed it, no cleanup ran
        write(os.path.join(self.tmp, "go"), "")                   # let the orphaned gate script end


class Counters(Land):
    def put(self, lines):
        path = relay_land.events_path(self.main)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))

    def test_land_stats_counts(self):
        self.start()
        base = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)

        def at(seconds):
            return (base + timedelta(seconds=seconds)).isoformat(timespec="seconds")

        # Z holds the lock 0-100 s; A, B, C ask at 10, 20, 30 s and get it at 101, 201, 301 s
        rows = []
        for pid, name, asked, locked, done in (
                (1, "wt/z", 0, 0, 100), (2, "wt/a", 10, 101, 200), (3, "wt/b", 20, 201, 300), (4, "wt/c", 30, 301, 400)):
            rows += [{"kind": "asked", "ts": at(asked), "branch": name, "pid": pid}, {"kind": "locked", "ts": at(locked), "branch": name, "pid": pid},
                     {"kind": "done", "ts": at(done), "branch": name, "pid": pid, "outcome": "landed"}]
        rows.sort(key=lambda r: r["ts"])
        self.put(rows)
        lines = dict(l.split(": ", 1) for l in relay_land.stats(self.main, None, None))
        # waits: a 91 s, b 181 s, c 271 s (z 0): three waited behind another, the longest 271 s = 4.5 min
        self.assertEqual(lines["landers that waited behind another"].split(";")[0], "3")
        self.assertEqual(lines["landers that waited behind another"], "3; longest wait minutes: 4.5")
        # a gets the lock at 101 s while b and c have asked and wait: one moment (b at 201 s sees only c)
        self.assertTrue(lines["landing counter, moments with 2+ waiting"].startswith("1; wt/a: 2 waited behind it"))
        # unreadable lines are counted, not guessed
        with open(relay_land.events_path(self.main), "a") as handle:
            handle.write("not json\n")
        self.assertIn("unreadable event lines: 1", relay_land.stats(self.main, None, None))

    def test_stats_gate_measures(self):
        # one landing with 3 cycle gates and 1 take gate: all gates 4.0, take gates 1.0 on separate labelled lines
        self.start()
        self.counter = None
        wt = self.wt

        def gate_log(sha):
            write(os.path.join(wt, ".relay", "checks", sha + ".gate.log"), "head %s\nexit 0\n" % sha)
            git(wt, "add", "-A")
            git(wt, "commit", "-q", "-m", "relay: gate of " + sha)

        for i in range(3):
            write(os.path.join(wt, "lib", "c%d.py" % i), "c\n")
            git(wt, "add", "-A")
            git(wt, "commit", "-q", "-m", "code %d" % i)
            gate_log(git(wt, "rev-parse", "HEAD"))
        self.master_commit("lib/b.py", "b\n")
        git(wt, "merge", "-q", "--no-edit", "master")
        gate_log(git(wt, "rev-parse", "HEAD"))                       # the gate of the take (a merge commit)
        git(self.main, "merge", "-q", "--ff-only", "wt/x")
        lines = relay_land.stats(self.main, None, None)
        self.assertEqual(lines[0], "code landings on the default branch: 1")
        self.assertEqual(lines[1], "all gate logs per code landing: 4.0 (4 gate logs)")
        self.assertEqual(lines[2], "take gates per code landing: 1.0 (1 take gates)")

    def test_lanes_hold_recorded_once(self):
        self.start()
        waits = [relay_lanes.Wait("slug-a", "lib/a.py", "wt/x"), relay_lanes.Wait("slug-b", "lib/a.py", "", "slug-a")]
        relay_land.note_held(self.main, waits)
        relay_land.note_held(self.main, waits)             # the hook prints the same line again and again
        held = [e for e in self.events() if e.kind == "held"]
        self.assertEqual(sorted((e.slug, e.holder) for e in held), [("slug-a", "wt/x"), ("slug-b", "slug-a")])

    def test_parse_event_rejects_what_is_not_an_event(self):
        for line in ("nope", '{"kind": "x", "ts": "2026-10-20T10:00:00+00:00"}', '{"kind": "done", "ts": "2026-10-20T10:00:00+00:00"}',
                     '{"kind": "asked", "ts": "yesterday"}', '{"kind": "asked", "ts": "2026-10-20T10:00:00+00:00", "pid": "7"}'):
            self.assertIsNone(relay_land.parse_event(line), line)
        self.assertIsNotNone(relay_land.parse_event('{"kind": "asked", "ts": "2026-10-20T10:00:00+00:00", "pid": 7, "branch": "wt/x"}'))


if __name__ == "__main__":
    unittest.main()
