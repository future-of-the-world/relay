"""`relay gate` (R1-R5) and the inert probe of bin/ci (A11) of docs/plans/review-gate.md sections 12.4 and 12.6.

Every repository is built in a temp directory; the gate commands are fixtures, never the real bin/ci of this repo
except as the file the A11 fixture copies.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RELAY = os.path.join(ROOT, "bin", "relay")
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import leaked_gates
from fake_tools import install_fake

GATE_TIMEOUT = 900      # seconds a test waits for its gate; the slowest (a copied bin/ci with its nested probe) takes about a minute
GATE_STOP_GRACE = 30    # seconds the stopped gate has to end its command and free its slot
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args, check=True):
    done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if check and done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


def read(path):
    with open(path) as handle:
        return handle.read()


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if mode and mode & stat.S_IXUSR:
        install_fake(path, text)    # an executable is shared per text, so macOS scans it once per run
        return
    with open(path, "w") as handle:
        handle.write(text)
    if mode:
        os.chmod(path, mode)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = {**os.environ, **GIT_ENV, "RELAY_ROOT": ROOT, "RELAY_HOME": os.path.join(self.tmp, "home")}      # slots in the temp dir, never the live ~/.relay
        self.env.pop("RELAY_GATE", None)

    def repo(self, relay=True, gate=None, ignore=".ci/\n.worktrees/\n"):
        """main checkout on master with a worktree .worktrees/x on wt/x holding one commit; gate = the gate script's text"""
        main = os.path.join(self.tmp, "main")
        os.makedirs(main)
        git(main, "init", "-q", "-b", "master")
        write(os.path.join(main, ".gitignore"), ignore)
        if relay:
            write(os.path.join(main, ".relay", "README.md"), "x\n")
        if gate is not None:
            script = os.path.join(self.tmp, "gate.sh")
            write(script, "#!/bin/sh\n" + gate, stat.S_IRWXU)
            write(os.path.join(main, ".claude", "kit.toml"), '[gate]\nci = "%s"\n' % script)
            self.script = script
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "init")
        self.main = main
        self.wt = os.path.join(main, ".worktrees", "x")
        git(main, "worktree", "add", "-q", self.wt, "-b", "wt/x")
        write(os.path.join(self.wt, "lib", "a.py"), "a\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "work")

    @staticmethod
    def _stop(proc):
        """SIGTERM the gate (its handler kills its command's group and frees its slot), wait; SIGKILL only if it ignores that."""
        proc.terminate()
        try:
            proc.communicate(timeout=GATE_STOP_GRACE)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()

    def gate(self, cwd, *args, timeout=GATE_TIMEOUT):
        """Run `relay gate`; past `timeout` seconds the gate is stopped (SIGTERM: it ends its command's process group and
        frees its slot), killed if it ignores that, and the test fails. A gate never outlives its test."""
        # No new session: the gate stays in the runner's process group, so a stop of that group (SIGTERM, SIGINT, hangup)
        # reaches the gate and its handler ends the command; a session of its own would orphan it.
        proc = subprocess.Popen([sys.executable, RELAY, "gate", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                cwd=cwd, env=self.env)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._stop(proc)
            raise AssertionError("relay gate still running after %s s; it was stopped" % timeout)
        except BaseException:      # an interrupt of the test: the gate must end its command too, so stop it the same way
            self._stop(proc)
            raise
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


class Gate(Fixture):
    def test_r1_refuses_without_relay_folder(self):
        """R1: the default branch has no .relay/: refused, the message names relay setup, no log, no commit."""
        self.repo(relay=False, gate="exit 0\n")
        before = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        self.assertIn("relay setup", run.stderr)
        self.assertEqual(git(self.wt, "rev-parse", "HEAD"), before)
        self.assertFalse(os.path.exists(os.path.join(self.wt, ".relay")))

    def test_r2_refuses_a_dirty_worktree_and_accepts_an_ignored_file(self):
        """R2: a changed tracked file and an untracked one are refused (the log names a commit, so the code that ran must
        be that commit); an ignored file is fine."""
        self.repo(gate="exit 0\n")
        write(os.path.join(self.wt, "lib", "a.py"), "changed\n")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        self.assertIn("commit first", run.stderr)
        self.assertIn("lib/a.py", run.stderr)
        git(self.wt, "checkout", "--", "lib/a.py")
        write(os.path.join(self.wt, "new.txt"), "x\n")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        self.assertIn("new.txt", run.stderr)
        os.remove(os.path.join(self.wt, "new.txt"))
        write(os.path.join(self.wt, ".ci", "junk.log"), "x\n")      # ignored by .gitignore
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_r3_green_gate_writes_and_commits_its_log_alone(self):
        """R3: log = head <G>, cmd, the gate's output, exit 0; committed alone; the gate saw RELAY_GATE=<G>; the three
        printed lines. (That a staged file stays staged is the property of commit_file, tested in test_marks.py; a gate
        that leaves a file staged is refused, see the Moved tests.)"""
        self.repo(gate='echo "step one ok"\necho "seen=$RELAY_GATE" > .ci/seen\nexit 0\n')
        head = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 0, run.stderr)
        log = os.path.join(self.wt, ".relay", "checks", head + ".gate.log")
        lines = read(log).splitlines()
        self.assertEqual(lines[0], "head " + head)
        self.assertEqual(lines[1], "cmd %s --quick" % self.script)
        self.assertRegex(lines[2], r"^wait \d+\.\d$")      # the slot wait, then the gate's output
        self.assertEqual(lines[3:-1], ["step one ok"])
        self.assertEqual(lines[-1], "exit 0")
        self.assertEqual(read(os.path.join(self.wt, ".ci", "seen")).strip(), "seen=" + head)
        self.assertEqual([l for l in git(self.wt, "show", "--name-only", "--format=%s", "HEAD").splitlines() if l],
                         ["relay: gate of " + head, ".relay/checks/%s.gate.log" % head])
        out = run.stdout.splitlines()
        self.assertEqual(out, ["gate %s: exit 0" % head, log])

    def refused_gate(self, body):
        """Run a gate whose command does `body` to the tree; returns (run, gated head). It must be refused with no log."""
        self.repo(gate=body + "exit 0\n")
        head = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("the worktree changed while the gate ran", run.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))
        return run, head

    def test_t4_a_gate_that_commits_code_midrun_is_refused(self):
        """T4: the command commits lib/n.py, so HEAD is another commit with a code file changed: the tested tree is not the gated commit."""
        run, head = self.refused_gate('echo n > lib/n.py\ngit add lib/n.py\ngit commit -q -m code\n')
        self.assertIn("lib/n.py", run.stderr)
        self.assertNotEqual(git(self.wt, "rev-parse", "HEAD"), head)

    def test_t4_a_gate_that_leaves_an_untracked_file_is_refused(self):
        run, _ = self.refused_gate("echo n > new.txt\n")
        self.assertIn("new.txt", run.stderr)

    def test_t4_a_gate_that_edits_a_tracked_file_is_refused(self):
        run, _ = self.refused_gate("echo changed > lib/a.py\n")
        self.assertIn("lib/a.py", run.stderr)

    def test_t4_a_gate_that_leaves_a_file_staged_is_refused(self):
        run, _ = self.refused_gate("echo n > extra.txt\ngit add extra.txt\n")
        self.assertIn("extra.txt", run.stderr)

    def test_t5_a_gate_that_commits_only_an_inert_file_midrun_is_green(self):
        """T5 (guards against over-reach): docs/handover.md is inert, so a commit of it mid-run leaves the gated commit certified;
        the log names the gated head and sits on top of the new HEAD. A file written only into the ignored .ci/ is fine too."""
        self.repo(gate='echo i > .ci/scratch\nmkdir -p docs\necho h > docs/handover.md\ngit add docs/handover.md\ngit commit -q -m handover\nexit 0\n')
        head = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")

    def test_f11_a_project_that_does_not_ignore_ci_can_run_the_gate_twice(self):
        """F11: .gitignore lacks .ci/. The gate's own output file must not appear in the tree: two gates in a row both run
        (the second is on the first's log commit, an inert one), and the tree stays clean."""
        self.repo(gate="echo ok\nexit 0\n", ignore=".worktrees/\n")
        first = self.gate(self.wt)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.gate(self.wt)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")

    def test_r4_red_gate_exits_with_its_status_and_names_the_failure(self):
        """R4: a red fixture gate: exit status 1 (its own), the log ends exit 1, the failing step's lines are printed."""
        self.repo(gate='echo "ci: tests ok (1s)"\necho "ci: lint FAILED (1s, log: x)"\necho "    bad line"\nexit 1\n')
        head = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        log = os.path.join(self.wt, ".relay", "checks", head + ".gate.log")
        self.assertEqual(read(log).splitlines()[-1], "exit 1")
        self.assertEqual(run.stdout.splitlines(), ["gate %s: exit 1" % head, log, "ci: lint FAILED (1s, log: x)", "    bad line"])
        # a different status passes through: 3 stays 3
        write(self.script, "#!/bin/sh\nexit 3\n", stat.S_IRWXU)    # the script lives outside the repo: the worktree is still clean
        self.assertEqual(self.gate(self.wt).returncode, 3)

    def test_r5_refused_in_the_main_checkout(self):
        """R5: the gate runs on a task branch, not in the main checkout."""
        self.repo(gate="exit 0\n")
        run = self.gate(self.main)
        self.assertEqual(run.returncode, 1)
        self.assertIn("task branch", run.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.main, ".relay", "checks")))

    def test_a_gate_that_outlives_its_timeout_is_stopped_with_its_command(self):
        """A gate command that never ends: the helper stops the gate at the timeout, the command dies with it (no process
        left holding a slot), and the test fails with a message."""
        self.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % self.tmp)
        with self.assertRaises(AssertionError) as caught:
            self.gate(self.wt, timeout=3)
        self.assertIn("still running", str(caught.exception))
        pid = int(read(os.path.join(self.tmp, "pid")))
        with self.assertRaises(ProcessLookupError):      # the gate waited for its command's end, so it is gone now
            os.kill(pid, 0)


class Inert(Fixture):
    """A11: bin/ci's last step `inert` runs only under `relay gate`, once, and is RED when a test reads an inert file."""

    TEST = (
        "import os, unittest\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_it(self):\n"
        "        marker = os.environ.get('INERT_MARKER')\n"
        "        if marker:\n"
        "            with open(marker, 'a') as handle:\n"
        "                handle.write('run\\n')\n"
        "%s"
    )

    def project(self, body="        pass\n"):
        """A project whose gate is a copy of the real bin/ci with one passing library test; a fake `claude` on PATH."""
        main = os.path.join(self.tmp, "main")
        os.makedirs(main)
        git(main, "init", "-q", "-b", "master")
        write(os.path.join(main, ".gitignore"), ".ci/\n.worktrees/\n__pycache__/\n.ruff_cache/\n")      # what a real run of the copied gate leaves behind
        write(os.path.join(main, ".relay", "README.md"), "x\n")
        write(os.path.join(main, "docs", "handover.md"), "state\n")
        write(os.path.join(main, "tests", "test_x.py"), self.TEST % body)
        write(os.path.join(main, "evals", "plugin", "graders.test.sh"), "exit 0\n")
        os.makedirs(os.path.join(main, "bin"))
        shutil.copy(os.path.join(ROOT, "bin", "ci"), os.path.join(main, "bin", "ci"))
        os.makedirs(os.path.join(main, "lib"))
        shutil.copy(os.path.join(ROOT, "lib", "relay_ci.py"), os.path.join(main, "lib", "relay_ci.py"))   # the wrapper runs it
        # the copied gate's library tests run through the unittest runner that gives every test its temporary folders
        for name in ("run_unittest.py", "parallel_unittest.py", "tmp_default.py", "leaked_gates.py"):
            shutil.copy(os.path.join(ROOT, "tests", name), os.path.join(main, "tests", name))
        for name in ("relay_config.py", "relay_toml.py"):      # parallel_unittest finds $RELAY_HOME through relay_config
            shutil.copy(os.path.join(ROOT, "lib", name), os.path.join(main, "lib", name))
        # the "types and lint" step of the copied gate: its script, its config and one python file to check
        shutil.copy(os.path.join(ROOT, "bin", "types-lint"), os.path.join(main, "bin", "types-lint"))
        shutil.copy(os.path.join(ROOT, "pyproject.toml"), main)
        write(os.path.join(main, "lib", "relay_x.py"), "X = 1\n")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "init")
        self.wt = os.path.join(main, ".worktrees", "x")
        git(main, "worktree", "add", "-q", self.wt, "-b", "wt/x")
        fake = os.path.join(self.tmp, "fakebin")
        write(os.path.join(fake, "claude"), "#!/bin/sh\nexit 0\n", stat.S_IRWXU)
        self.marker = os.path.join(self.tmp, "marker")
        self.env.update(PATH=fake + os.pathsep + self.env["PATH"], INERT_MARKER=self.marker)

    def runs(self):
        return len(read(self.marker).splitlines()) if os.path.exists(self.marker) else 0

    def test_without_relay_gate_the_step_is_skipped(self):
        """A11 (1): plain `bin/ci --quick` prints the skip line, is green, and runs the tests once."""
        self.project()
        run = subprocess.run(["bash", "bin/ci", "--quick"], capture_output=True, text=True, cwd=self.wt, env=self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("inert: skipped (runs under relay gate)", run.stdout)
        self.assertEqual(self.runs(), 1)

    def test_under_relay_gate_one_nested_run_and_green(self):
        """A11 (3) and (4): under `relay gate` with nothing reading an inert file: `inert` ok, and exactly one nested run
        (the marker file has the outer run's line and the nested run's: 2)."""
        self.project()
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.runs(), 2)
        head = git(self.wt, "rev-parse", "HEAD~1")
        self.assertIn("ci: inert ok", read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))

    def test_a_test_reading_an_inert_file_turns_inert_red(self):
        """A11 (2): a committed test asserts on docs/handover.md. The outer run passes ("state"); the nested run, where
        the file got a probe line, fails: the step results differ, so `inert` is RED and so is the gate."""
        self.project("        with open('docs/handover.md') as handle:\n"
                     "            self.assertEqual(handle.read(), 'state\\n')\n")
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        head = git(self.wt, "rev-parse", "HEAD~1")
        log = read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log"))
        self.assertIn("ci: inert FAILED", log)
        self.assertIn("ci: library tests ok", log)       # the outer run itself was green
        self.assertEqual(self.runs(), 2)

    def test_an_inert_red_shows_the_whole_diff_and_keeps_the_nested_log(self):
        """Case 5: the red `inert` line is followed by every line of the difference (the probe's step result), not only the
        lines with FAIL in them, and the probe's own output stays in .ci/steps/inert-nested.log."""
        self.project("        with open('docs/handover.md') as handle:\n"
                     "            self.assertEqual(handle.read(), 'state\\n')\n")
        self.gate(self.wt, "--", "--quick")
        head = git(self.wt, "rev-parse", "HEAD~1")
        log = read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log"))
        # the probe's "library tests FAILED" line is a '+' line of the diff; it has no FAIL-matching word besides that one
        self.assertIn("+++ probe run", log)
        self.assertIn("+library tests FAILED", log)
        self.assertIn("-library tests ok", log)
        self.assertIn("ci: library tests FAILED", read(os.path.join(self.wt, ".ci", "steps", "inert-nested.log")))   # the probe run itself, as it printed it

    def test_a_probe_that_is_killed_turns_inert_red_and_leaves_no_worktree(self):
        """Case 2: the nested run is killed (SIGKILL) halfway: `inert` is FAILED, not ok, and `git worktree list` shows only
        the main checkout and the task's worktree. Only the nested run lacks RELAY_GATE, so only it kills its own parent
        (the gate program)."""
        self.env["RELAY_TEST_JOBS"] = "1"     # the test kills its parent: with one job that is the nested run's own test process
        self.project("        if not os.environ.get('RELAY_GATE'):\n"
                     "            os.kill(os.getppid(), 9)\n")
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        head = git(self.wt, "rev-parse", "HEAD~1")
        log = read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log"))
        self.assertIn("ci: inert FAILED", log)
        self.assertNotIn("ci: inert ok", log)
        self.assertIn("stopped by signal 9", log)
        self.assertEqual(len(git(self.wt, "worktree", "list").splitlines()), 2)

    def test_a_full_run_is_probed_with_its_hook_suites_in_full(self):
        """The hook case count must not depend on the mode: a suite that prints 2 ok lines in full mode and 1 under
        RELAY_QUICK=1 (as guard-main does) gives 2 in a full outer run; the nested probe run is quick for the paid steps
        only, so it must count 2 as well, else `inert` was red with 932 against 448 cases. The full outer run ends red
        here (the fixture has no eval-record); only the `inert` line is asserted."""
        self.project()
        write(os.path.join(self.wt, "plugins", "x", "tests", "a.test.sh"),
              'echo "ok   one"\n[ "${RELAY_QUICK:-0}" = 1 ] || echo "ok   two"\n')
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "hook suite")
        self.gate(self.wt, "--")
        head = git(self.wt, "rev-parse", "HEAD~1")
        log = read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log"))
        self.assertIn("ci: inert ok", log)

    def test_f9_the_probe_plants_files_under_the_stored_json_names(self):
        """F9: a test that breaks on an unknown queue item or check JSON (as a reader listing the folders would) turns
        `inert` red: the probe planted .relay/queue/zz-probe.json, .relay/checks/zz.review.json and zz.check.json."""
        self.project("        for rel in ('.relay/queue/zz-probe.json', '.relay/checks/zz.review.json', '.relay/checks/zz.check.json'):\n"
                     "            self.assertFalse(os.path.exists(rel), rel)\n")
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        head = git(self.wt, "rev-parse", "HEAD~1")
        self.assertIn("ci: inert FAILED", read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))


class LeakedGates(Fixture):
    """F3: a gate left running under the run's temporary folder is found and stopped with its command (tests/leaked_gates.py)."""

    def start_orphan(self, name):
        """A real `relay gate` whose command sleeps, started detached (its runner is gone); returns (gate Popen, command pid)."""
        pid_file = os.path.join(self.tmp, name)
        gate = subprocess.Popen([sys.executable, RELAY, "gate"], cwd=self.wt, env=self.env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(gate.wait)
        self.addCleanup(gate.kill)
        deadline = time.monotonic() + 60
        while not os.path.exists(pid_file) and time.monotonic() < deadline and gate.poll() is None:
            time.sleep(0.05)
        self.assertTrue(os.path.exists(pid_file), "the gate command did not start")
        return gate, int(read(pid_file))

    def test_a_gate_left_under_the_folder_is_stopped_with_its_command_and_named(self):
        self.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % self.tmp)
        gate, command_pid = self.start_orphan("pid")
        found = leaked_gates.stop(self.tmp)
        # one gate, found by its pid; it and its sleeping command are both gone afterwards
        self.assertEqual([pid for pid, _ in found], [gate.pid])
        gate.wait(timeout=30)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and leaked_gates._alive(command_pid):
            time.sleep(0.05)
        self.assertFalse(leaked_gates._alive(command_pid))

    def test_a_gate_outside_the_folder_is_left_running(self):
        """Pass case 3: a legitimately detached gate elsewhere is not touched."""
        self.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % self.tmp)
        gate, command_pid = self.start_orphan("pid")
        other = os.path.realpath(tempfile.mkdtemp(prefix="relay-other-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertEqual(leaked_gates.stop(other), [])
        self.assertIsNone(gate.poll())
        self.assertTrue(leaked_gates._alive(command_pid))
        self.assertEqual(len(leaked_gates.stop(self.tmp)), 1)  # cleanup: the gate and its command end
        gate.wait(timeout=30)


if __name__ == "__main__":
    unittest.main()
