"""The gate's sweep of leftovers (B) and its reclaim of a killed gate's command (docs: queue item
gates-and-tests-stop-what-an-earlier-test-left-r). Fakes feed `sweep` the process table; the real-process tests plant their
orphans inside a folder of the test's own temporary folder and pass it as the sweep's root, so nothing outside the test is touched."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_gate import GIT_ENV, Fixture, read, write
from pidfile import wait_pid

import relay_gate
import relay_procs
from relay_procs import Proc

BOUND = 30      # seconds any wait here may last


def proc(pid, ppid, pgid, command, age=5.0):
    return Proc(pid, ppid, pgid, time.time() - age, command)


class FakeSweep(unittest.TestCase):
    """`sweep` with a faked process table and faked stops: it must pick the right processes and the right way to stop each."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="roots-"))
        self.targets = []
        self.killed = []
        patcher = mock.patch.object(relay_procs, "stop", lambda targets: (self.targets.extend(targets), self.killed)[1])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.me = [proc(999, 50, 50, "python3 relay gate"), proc(50, 40, 50, "zsh")]

    def make(self, *names):
        for name in names:
            os.makedirs(os.path.join(self.root, name), exist_ok=True)

    def sweep(self, others, cwds=None, roots=None):
        return relay_gate.sweep(roots or [self.root], lambda: self.me + others, lambda pids: dict(cwds or {}), [999])

    def test_the_shape_of_the_22_a_parent_1_group_leader_in_a_deleted_folder_is_stopped_as_a_group(self):
        """relay-run-X lives, relay-gate-Y (inside it) is gone: one stop line, the group of pid 1469 (pgid == pid) is the target."""
        self.make("relay-run-X")
        command = "/bin/sh %s/relay-run-X/relay-gate-Y/gate.sh" % self.root
        lines = self.sweep([proc(1469, 1, 1469, command)])
        self.assertEqual(self.targets, [(1469, True)])
        self.assertEqual(len(lines), 1)
        self.assertIn("1469", lines[0])
        self.assertTrue(lines[0].startswith(relay_gate.STOPPED))
        self.assertIn("folder deleted", lines[0])

    def test_a_process_in_a_folder_that_is_not_relays_is_left(self):
        """`<root>/tmpabc123/build.sh`: no relay prefix on the path, even though its folder is gone."""
        command = "/bin/sh %s/tmpabc123/build.sh" % self.root
        self.assertEqual(self.sweep([proc(1469, 1, 1469, command)]), [])
        self.assertEqual(self.targets, [])

    def test_an_old_relay_gate_with_its_folder_present_is_stopped_alone_when_it_shares_a_group(self):
        """pid 500 in group 400 (a live process whose parent is not 1: another gate's command): only pid 500 gets the signal, never the group."""
        self.make("relay-gate-Y/main/.worktrees/x")
        cwd = os.path.join(self.root, "relay-gate-Y", "main", ".worktrees", "x")
        old = proc(500, 1, 400, "/usr/bin/python3 /somewhere/bin/relay gate", age=26 * 3600)
        lines = self.sweep([old, proc(400, 77, 400, "/bin/sh gate.sh")], cwds={500: cwd})
        self.assertEqual(self.targets, [(500, False)])
        self.assertIn("older than", lines[0])

    def test_a_young_leftover_whose_folder_is_present_is_left(self):
        self.make("relay-gate-Y")
        command = "/bin/sh %s/relay-gate-Y/gate.sh" % self.root
        self.assertEqual(self.sweep([proc(1469, 1, 1469, command, age=5)]), [])

    def test_a_process_whose_parent_is_alive_is_left_even_when_its_folder_is_gone(self):
        command = "/bin/sh %s/relay-gate-Y/gate.sh" % self.root
        self.assertEqual(self.sweep([proc(1469, 77, 1469, command)]), [])

    def test_the_sweeping_gates_own_group_is_never_signalled_as_a_group(self):
        """A leftover that leads group 1469, the group the sweeping gate itself runs in: stopped alone."""
        self.me = [proc(999, 50, 1469, "python3 relay gate"), proc(50, 40, 1469, "zsh")]
        command = "/bin/sh %s/relay-gate-Y/gate.sh" % self.root
        self.sweep([proc(1469, 1, 1469, command)])
        self.assertEqual(self.targets, [(1469, False)])

    def test_the_sweeping_gate_and_its_parents_are_never_candidates(self):
        command = "python3 relay gate %s/relay-gate-Y/x" % self.root
        self.me = [proc(999, 1, 999, command)]
        self.assertEqual(self.sweep([]), [])

    def test_a_relay_gate_outside_every_relay_folder_is_left(self):
        """Never a real gate: parent 1, `relay gate`, but its working folder is no relay test folder."""
        real = proc(500, 1, 500, "/usr/bin/python3 /Users/x/relay/bin/relay gate", age=26 * 3600)
        self.assertEqual(self.sweep([real], cwds={500: "/Users/x/relay/.worktrees/some-task"}), [])
        self.assertEqual(self.sweep([real], cwds={500: os.path.join(self.root, "tmpabc")}), [])

    def test_both_spellings_of_the_temporary_folder_match(self):
        """/var/folders/.. and /private/var/folders/..: the command shows one, TMPDIR the other; a link stands for the pair."""
        link = self.root + "-link"
        os.symlink(self.root, link)
        self.addCleanup(os.remove, link)
        for roots, spelled in (([link, self.root], self.root), ([link, self.root], link)):
            self.targets.clear()
            command = "/bin/sh %s/relay-run-X/gate.sh" % spelled
            self.assertEqual(len(self.sweep([proc(1469, 1, 1469, command)], roots=roots)), 1)
            self.assertEqual(self.targets, [(1469, True)])

    def test_a_pid_stopped_alone_and_then_killed_is_followed_by_one_more_look(self):
        """Its command may have become a leader in a deleted folder: ps is read again and the new one is stopped by the same rule."""
        command = "/bin/sh %s/relay-gate-Y/gate.sh" % self.root
        first = proc(500, 1, 400, command)
        reads = [[first], [proc(501, 1, 501, command)]]
        self.killed = [(500, False)]
        lines = relay_gate.sweep([self.root], lambda: self.me + reads.pop(0), lambda pids: {}, [999])
        self.assertEqual(self.targets, [(500, False), (501, True)])
        self.assertEqual(len(lines), 2)

    def test_the_temp_roots_hold_both_spellings_of_the_temporary_folder(self):
        link = self.root + "-link"
        os.symlink(self.root, link)
        self.addCleanup(os.remove, link)
        with mock.patch.dict(os.environ, {"TMPDIR": link}), mock.patch.object(tempfile, "tempdir", None):
            roots = relay_gate.temp_roots()
        self.assertIn(link, roots)
        self.assertIn(self.root, roots)
        self.assertIn(os.path.realpath("/tmp"), roots)


class NeverInsideATest(unittest.TestCase):
    """A gate whose worktree or home lies in a temporary folder is a test's: it calls no sweep."""

    def check(self, worktree, env, expected_calls):
        with mock.patch.object(relay_gate, "temp_roots", return_value=["/fake-temp"]), \
                mock.patch.object(relay_gate, "sweep", return_value=[]) as sweep, mock.patch.dict(os.environ, env, clear=False):
            for key in ("RELAY_HOME", "HOME"):
                if key not in env:
                    os.environ.pop(key, None)
            relay_gate.sweep_leftovers(worktree, os.environ)
        self.assertEqual(sweep.call_count, expected_calls)

    def test_relay_home_under_temp_sweeps_nothing(self):
        self.check("/work/tree", {"RELAY_HOME": "/fake-temp/x/home", "HOME": "/home/u"}, 0)

    def test_home_under_temp_with_no_relay_home_sweeps_nothing(self):
        self.check("/work/tree", {"HOME": "/fake-temp/h"}, 0)

    def test_a_worktree_under_temp_sweeps_nothing(self):
        self.check("/fake-temp/main/.worktrees/x", {"RELAY_HOME": "/home/u/.relay", "HOME": "/home/u"}, 0)

    def test_a_real_gate_sweeps(self):
        self.check("/work/tree", {"RELAY_HOME": "/home/u/.relay", "HOME": "/home/u"}, 1)


ORPHAN = '#!/bin/sh\necho $$ > "%s"\nwhile true; do sleep 0.05; done\n'      # no folder check: it never ends by itself


class RealSweep(Fixture):
    """`run()` on a fixture worktree, with the sweep's root pointed at a folder of the test's own."""

    def setUp(self):
        super().setUp()
        self.roots = os.path.realpath(tempfile.mkdtemp(prefix="roots-"))
        self.repo(gate="exit 0\n")
        environ = {**GIT_ENV, "RELAY_HOME": os.path.join(self.tmp, "home")}
        for patcher in (mock.patch.object(relay_gate, "temp_roots", return_value=[self.roots]), mock.patch.dict(os.environ, environ)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def orphan(self, parent):
        """A parent-1 group leader `/bin/sh <parent>/relay-gate-N/gate.sh` that never ends; its folder is deleted. Returns its pid."""
        folder = os.path.join(parent, "relay-run-X", "relay-gate-N")
        pidfile = os.path.join(self.tmp, "pid-%d" % len(os.listdir(self.tmp)))
        write(os.path.join(folder, "gate.sh"), ORPHAN % pidfile, 0o700)
        launcher = "import subprocess,sys; subprocess.Popen(['/bin/sh', sys.argv[1]], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
        subprocess.run([sys.executable, "-c", launcher, os.path.join(folder, "gate.sh")], check=True)
        pid = wait_pid(pidfile)
        self.addCleanup(relay_procs.send, pid, False, 9)
        self.wait_until(lambda: {p.pid: p for p in relay_procs.read_procs()}[pid].ppid == 1)
        os.remove(os.path.join(folder, "gate.sh"))
        os.rmdir(folder)
        return pid

    @staticmethod
    def wait_until(condition):
        deadline = time.monotonic() + BOUND
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError("condition not reached within %d s" % BOUND)
            time.sleep(0.02)

    def test_run_stops_the_leftover_and_logs_the_stop_between_wait_and_the_output(self):
        pid = self.orphan(self.roots)
        outside = self.orphan(os.path.join(self.tmp, "elsewhere"))      # outside the sweep's roots: not relay's to stop here
        code, log, _ = relay_gate.run(self.wt)
        self.assertEqual(code, 0)
        self.wait_until(lambda: not relay_procs.is_alive(pid))
        self.assertTrue(relay_procs.is_alive(outside))
        lines = read(log).splitlines()
        # head / cmd / wait keep their places (the merge hook reads them), the stop line follows, the command's output (none) and exit last
        self.assertTrue(lines[0].startswith("head "))
        self.assertTrue(lines[1].startswith("cmd "))
        self.assertTrue(lines[2].startswith("wait "))
        self.assertTrue(lines[3].startswith("%s %d (/bin/sh " % (relay_gate.STOPPED, pid)), lines[3])
        self.assertEqual(lines[-1], "exit 0")
        self.assertEqual(len(lines), 5)

    def test_a_reused_gate_runs_nothing_and_sweeps_nothing(self):
        relay_gate.run(self.wt)
        pid = self.orphan(self.roots)
        code, _, _ = relay_gate.run(self.wt)      # same code, green log: reported, not run
        self.assertEqual(code, 0)
        self.assertTrue(relay_procs.is_alive(pid))


class Reclaim(Fixture):
    """step 5: a gate whose predecessor was killed while its command ran stops that command instead of waiting it out."""

    def hold(self, text):
        """A lock file holding `text`, locked by a process of its own in its own group; returns (path, holder Popen)."""
        path = os.path.join(self.tmp, "lockfile")
        write(path, text)
        holder = subprocess.Popen([sys.executable, "-c", "import fcntl,sys,time; f=open(sys.argv[1]); fcntl.flock(f, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(600)", path],
                                  stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(holder.kill)
        self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        return path, holder

    def dead_pid(self):
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait()
        return done.pid

    def take(self, path):
        lines, recorded, box = [], [], []
        thread = threading.Thread(target=lambda: box.append(relay_gate.take_worktree_lock(path, lines.append, recorded.append)), daemon=True)
        thread.start()
        return thread, lines, recorded, box

    def test_a_dead_gate_whose_command_group_holds_the_lock_is_stopped_and_the_lock_taken(self):
        """Lock text `<dead gate pid> <group of the holder>`: the holder is that group's leader and has the file open: it is stopped, one line recorded."""
        holder_pid = None
        path = os.path.join(self.tmp, "lockfile")
        write(path, "")
        holder = subprocess.Popen([sys.executable, "-c", "import fcntl,sys,time; f=open(sys.argv[1]); fcntl.flock(f, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(600)", path],
                                  stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(holder.kill)
        self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        holder_pid = holder.pid
        write(path, "%d %d\n" % (self.dead_pid(), holder_pid))
        with mock.patch.object(relay_procs, "STOP_GRACE", 0.3):      # the stopped holder is our child, a zombie until reaped: it would count as alive for the whole grace
            thread, lines, recorded, box = self.take(path)
            thread.join(BOUND)
        self.assertTrue(box, "the lock was not taken")
        box[0].close()
        self.assertEqual(holder.wait(timeout=BOUND), -15)      # SIGTERM from the reclaim
        self.assertEqual(len(recorded), 1)
        self.assertTrue(recorded[0].startswith("%s %d (" % (relay_gate.STOPPED, holder_pid)), recorded[0])
        self.assertEqual([l for l in lines if "waiting" in l], [])

    def test_a_dead_gate_whose_group_does_not_hold_the_lock_leaves_the_waiter_waiting(self):
        """The text names a live group (a sleeping process) but the lock is held by another process: nothing is stopped, the waiting line is printed."""
        path, holder = self.hold("")
        sleeper = subprocess.Popen(["sleep", "600"], start_new_session=True)
        self.addCleanup(sleeper.wait)      # cleanups run last-first: kill, then wait
        self.addCleanup(sleeper.kill)
        write(path, "%d %d\n" % (self.dead_pid(), sleeper.pid))
        thread, lines, recorded, box = self.take(path)
        deadline = time.monotonic() + BOUND
        while not lines and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(lines), 1)
        self.assertIn("waiting for the gate already running", lines[0])
        self.assertEqual(recorded, [])
        self.assertIsNone(sleeper.poll())
        self.assertIsNone(holder.poll())
        holder.kill()      # the lock frees; the waiter takes it
        holder.wait()
        thread.join(BOUND)
        self.assertTrue(box)
        box[0].close()

    def test_a_live_gate_is_waited_for_and_the_line_is_printed_once(self):
        """The text names a live gate (this test process): the waiter prints the waiting line once, however long it polls, and stops nothing."""
        path, holder = self.hold("%d %d\n" % (os.getpid(), holder_group_placeholder()))
        thread, lines, recorded, box = self.take(path)
        deadline = time.monotonic() + BOUND
        while not lines and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(3 * relay_gate.SLOT_POLL)      # several polls pass with the gate alive
        self.assertEqual(len(lines), 1)
        self.assertEqual(recorded, [])
        self.assertIsNone(holder.poll())
        holder.kill()
        holder.wait()
        thread.join(BOUND)
        box[0].close()


def holder_group_placeholder():
    return 2 ** 22 - 1      # a group nobody has


if __name__ == "__main__":
    unittest.main()
