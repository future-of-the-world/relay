"""`relay gate` (R1-R5) and the inert probe of bin/ci (A11) of docs/plans/review-gate.md sections 12.4 and 12.6.

Every repository is built in a temp directory; the gate commands are fixtures, never the real bin/ci of this repo
except as the file the A11 fixture copies.
"""
import fcntl
import glob
import os
import re
import shutil
import signal
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
import relay_procs
from fake_tools import install_fake
from pidfile import wait_pid

GATE_TIMEOUT = 900      # seconds a test waits for its gate; the slowest (a copied bin/ci with its nested probe) takes about a minute
LEAK_GRACE = 5.0        # seconds a correct gate command (a loop that checks its folder) gets to end after the fixture's folder is removed
GATE_STOP_GRACE = 600   # seconds the stopped gate has to end its command and free its slot
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
        self.addCleanup(self.remove_tree)
        self.env = {**os.environ, **GIT_ENV, "RELAY_ROOT": ROOT, "RELAY_HOME": os.path.join(self.tmp, "home")}      # slots in the temp dir, never the live ~/.relay
        self.env.pop("RELAY_GATE", None)

    def remove_tree(self):
        """E: remove the fixture's folder, then make sure no gate process it started outlives it. The worktree locks
        (`relay-gate.lock` in the git folders, text `<gate pid> <command group>`) name them: a process that kept the lock file is
        still a holder. A loop that checks its folder ends by itself within LEAK_GRACE; any holder left after that is stopped and the
        test fails, naming it. (A process that closed the lock file is not seen here: the end-of-run scan under bin/ci finds it.)"""
        locks = []
        for path in glob.glob(os.path.join(self.tmp, "main", ".git", "relay-gate.lock")) + glob.glob(os.path.join(self.tmp, "main", ".git", "worktrees", "*", "relay-gate.lock")):
            try:
                handle = open(path)
            except OSError:
                continue
            text = handle.read()
            numbers = [int(word) for word in re.findall(r"\d+", text)]
            locks.append((path, handle, numbers))
        shutil.rmtree(self.tmp, ignore_errors=True)
        left = []
        try:
            for path, handle, numbers in locks:
                if not self.lock_freed(handle, LEAK_GRACE):
                    left += self.stop_holders(path, handle, numbers)
        finally:
            for _, handle, _ in locks:
                handle.close()
        if left:
            raise AssertionError("the test left gate processes running after its folder was removed (stopped): " + ", ".join("%d %s" % item for item in left))

    @staticmethod
    def lock_freed(handle, grace):
        """Whether no process holds the lock file `handle` is open on, within `grace` seconds."""
        deadline = time.monotonic() + grace
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)
                continue
            fcntl.flock(handle, fcntl.LOCK_UN)
            return True

    def stop_holders(self, path, handle, numbers):
        """The lock at `path` is still held: stop the gate (SIGTERM) and the members of its command group (SIGKILL) that have this lock
        file open; returns [(pid, command)] of what was stopped."""
        procs = relay_procs.read_procs()
        candidates = {p.pid: p for p in procs if (numbers and p.pid == numbers[0]) or (len(numbers) > 1 and p.pgid == numbers[1])}
        names = relay_procs.open_names(list(candidates)) or {}
        mine = {pid: p for pid, p in candidates.items() if any(os.path.basename(name) == "relay-gate.lock" and (name == path or name.startswith(path)) for name in names.get(pid, []))}
        if numbers and numbers[0] in mine:
            relay_procs.send(numbers[0], False, signal.SIGTERM)
        for pid in mine:
            if pid != (numbers[0] if numbers else 0):
                relay_procs.send(pid, False, signal.SIGKILL)
        self.lock_freed(handle, relay_procs.STOP_GRACE)
        if not mine:      # still held and nobody identified: say so rather than pass
            return [(numbers[0] if numbers else 0, "holder of %s not identified" % path)]
        return [(pid, p.command) for pid, p in sorted(mine.items())]

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

    def gate(self, cwd, *args, timeout=GATE_TIMEOUT, started=None):
        """Run `relay gate`; past `timeout` seconds the gate is stopped (SIGTERM: it ends its command's process group and
        frees its slot), killed if it ignores that, and the test fails. A gate never outlives its test.
        `started`: a file the gate command writes once it runs; `timeout` then counts from that moment (waiting for it is
        bounded by GATE_TIMEOUT), so a loaded machine that is slow to start the command does not decide the outcome."""
        # No new session: the gate stays in the runner's process group, so a stop of that group (SIGTERM, SIGINT, hangup)
        # reaches the gate and its handler ends the command; a session of its own would orphan it.
        proc = subprocess.Popen([sys.executable, RELAY, "gate", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                cwd=cwd, env=self.env)
        try:
            if started:
                limit = time.monotonic() + GATE_TIMEOUT
                while not os.path.exists(started) and time.monotonic() < limit:
                    try:
                        proc.wait(timeout=0.05)
                        break
                    except subprocess.TimeoutExpired:
                        pass
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

    def test_the_help_names_both_gate_modes(self):
        run = subprocess.run([sys.executable, RELAY, "help"], capture_output=True, text=True, env=self.env)
        self.assertIn("--paid", run.stdout + run.stderr)

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

    def _counting_red_gate(self):
        """a red gate script that appends a line to a counter file outside the repo each time it runs"""
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate='echo run >> "%s"\necho "ci: lint FAILED (1s, log: x)"\necho "    bad line"\nexit 3\n' % self.counter)

    def runs(self):
        return len(read(self.counter).splitlines()) if os.path.exists(self.counter) else 0

    def test_a_rerun_on_the_record_commit_of_a_red_gate_prints_the_old_result(self):
        """HEAD = the record commit of a finished red gate: no second run (the counter stays 1), the same exit code (3),
        the same log and failing lines are printed."""
        self._counting_red_gate()
        head = git(self.wt, "rev-parse", "HEAD")
        first = self.gate(self.wt)
        self.assertEqual(first.returncode, 3)
        self.assertNotEqual(git(self.wt, "rev-parse", "HEAD"), head)      # HEAD is now the record commit
        again = self.gate(self.wt)
        self.assertEqual(again.returncode, 3)
        self.assertEqual(self.runs(), 1)
        self.assertEqual(again.stdout, first.stdout)

    def test_a_rerun_after_a_change_outside_the_checks_folder_gates_in_full(self):
        """record commit plus a code change: the old red result must not stand; the gate runs again (counter 2)."""
        self._counting_red_gate()
        self.assertEqual(self.gate(self.wt).returncode, 3)
        write(os.path.join(self.wt, "lib", "b.py"), "b\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "more work")
        self.assertEqual(self.gate(self.wt).returncode, 3)
        self.assertEqual(self.runs(), 2)

    def test_a_rerun_after_an_inert_file_change_still_gates_a_red_result_in_full(self):
        """a red result is reused only across .relay/checks/ files: a docs file in between means a full run (counter 2)."""
        self._counting_red_gate()
        self.assertEqual(self.gate(self.wt).returncode, 3)
        write(os.path.join(self.wt, "docs", "n.md"), "n\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "docs")
        self.assertEqual(self.gate(self.wt).returncode, 3)
        self.assertEqual(self.runs(), 2)

    def _red_then_log(self, code):
        """a gate script that exits `code` the first time and 0 afterwards, with a counter outside the repo; returns after the
        first (red) gate, HEAD = its record commit"""
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate='echo run >> "%s"\n[ "$(wc -l < "%s")" -eq 1 ] && exit %d\nexit 0\n' % (self.counter, self.counter, code))
        self.assertEqual(self.gate(self.wt).returncode, code)

    def test_f1_a_reused_red_says_so_on_stderr(self):
        """pass 1: plain rerun on a red record commit: exit 3, no run (counter 1), stderr names the reused gate of G."""
        self._red_then_log(3)
        g = git(self.wt, "rev-parse", "HEAD~1")      # the gated commit; HEAD is its record commit
        again = self.gate(self.wt)
        self.assertEqual(again.returncode, 3)
        self.assertEqual(self.runs(), 1)
        self.assertIn("unchanged since the red gate of %s: reported, not run" % g, again.stderr)

    def test_f1_again_runs_the_gate_anyway_and_logs_the_new_result(self):
        """pass 2: --again on a red record commit runs the command (counter 2); its new result (green here) is printed."""
        self._red_then_log(3)
        again = self.gate(self.wt, "--again")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(self.runs(), 2)

    def test_f1_a_red_that_could_not_start_or_was_killed_is_not_reused(self):
        """pass 3: exit 137 (killed) and exit 127 (could not start) logs are not reused: a plain rerun runs (counter 2)."""
        for code in (137, 127):
            with self.subTest(code=code):
                shutil.rmtree(os.path.join(self.tmp, "main"), ignore_errors=True)
                if os.path.exists(os.path.join(self.tmp, "runs")):
                    os.remove(os.path.join(self.tmp, "runs"))
                self._red_then_log(code if code < 128 else 137)
                again = self.gate(self.wt)
                self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                self.assertEqual(self.runs(), 2)

    def test_f1_a_green_record_commit_is_still_reused(self):
        """pass 4: green reuse unchanged: exit 0, nothing runs."""
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate='echo run >> "%s"\nexit 0\n' % self.counter)
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 1)

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
        # another command line is a new gate: the finished red result above is not reused for it
        self.assertEqual(self.gate(self.wt, "--", "--again").returncode, 3)

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
            self.gate(self.wt, timeout=3, started=os.path.join(self.tmp, "pid"))  # expected timeout
        self.assertIn("still running", str(caught.exception))
        pid = wait_pid(os.path.join(self.tmp, "pid"))
        with self.assertRaises(ProcessLookupError):      # the gate waited for its command's end, so it is gone now
            os.kill(pid, 0)

    def test_the_timeout_counts_from_the_start_of_the_command_not_of_the_gate(self):
        """A command slow to start (a loaded machine) is not cut by a short timeout: the wait is for the pid file, then the
        timeout. Here the command starts after 2 s, the timeout is 1 s: the gate is still stopped for running too long, and
        its pid file exists (without `started` the helper stopped it before the command ran)."""
        self.repo(gate='sleep 2\necho $$ > "%s/pid"\nexec sleep 600\n' % self.tmp)
        with self.assertRaises(AssertionError) as caught:
            self.gate(self.wt, timeout=1, started=os.path.join(self.tmp, "pid"))  # expected timeout
        self.assertIn("still running", str(caught.exception))
        pid = wait_pid(os.path.join(self.tmp, "pid"))
        with self.assertRaises(ProcessLookupError):
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
        write(os.path.join(main, "evals", "plugin", "graders.py"), "raise SystemExit(0)\n")
        os.makedirs(os.path.join(main, "bin"))
        shutil.copy(os.path.join(ROOT, "bin", "ci"), os.path.join(main, "bin", "ci"))
        shutil.copy(os.path.join(ROOT, "deps.toml"), os.path.join(main, "deps.toml"))   # bin/ci reads the python pin
        os.makedirs(os.path.join(main, "lib"))
        for module in ("relay_ci.py", "relay_ci_lines.py", "relay_ci_python.py"):   # the wrapper runs relay_ci, which imports the other two
            shutil.copy(os.path.join(ROOT, "lib", module), os.path.join(main, "lib", module))
        # the copied gate's library tests run through the unittest runner that gives every test its temporary folders
        for name in ("run_unittest.py", "parallel_unittest.py", "tmp_default.py", "leaked_gates.py"):
            shutil.copy(os.path.join(ROOT, "tests", name), os.path.join(main, "tests", name))
        for name in ("relay_config.py", "relay_toml.py", "relay_coverage.py", "relay_procs.py"):      # parallel_unittest finds $RELAY_HOME through relay_config; leaked_gates reads processes through relay_procs
            shutil.copy(os.path.join(ROOT, "lib", name), os.path.join(main, "lib", name))
        # the "types and lint" step of the copied gate: its script, its config and one python file to check
        for name in ("types-lint", "types_lint.py"):      # the wrapper runs bin/types_lint.py
            shutil.copy(os.path.join(ROOT, "bin", name), os.path.join(main, "bin", name))
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
        """The case count must not depend on the mode: a test file with 2 tests in full mode and 1 under RELAY_QUICK=1
        (as guard-main's shared cases) gives "Ran 3" in a full outer run (1 sample test of the fixture + 2); the nested
        probe run is quick for the paid steps only, so it must count the same, else `inert` was red. The full outer run
        ends red here (the fixture has no eval-record); only the `inert` line is asserted."""
        self.project()
        write(os.path.join(self.wt, "tests", "test_y.py"),
              "import os, unittest\n\nclass Y(unittest.TestCase):\n    def test_one(self):\n        pass\n\n"
              "if os.environ.get('RELAY_QUICK') != '1':\n    Y.test_two = lambda self: None\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "mode dependent suite")
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
        return gate, wait_pid(pid_file, 600, writer_alive=lambda: gate.poll() is None)

    def test_a_gate_left_under_the_folder_is_stopped_with_its_command_and_named(self):
        self.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % self.tmp)
        gate, command_pid = self.start_orphan("pid")
        found = leaked_gates.stop(self.tmp)
        # the gate is found by its pid (its sleeping command runs from the same folder, so it is found too); both are gone after
        self.assertIn(gate.pid, [pid for pid, _ in found])
        gate.wait(timeout=600)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and leaked_gates._alive(command_pid):
            time.sleep(0.05)
        self.assertFalse(leaked_gates._alive(command_pid))

    def test_any_child_left_in_the_folder_is_found_and_stopped(self):
        """A process that is not a `relay gate` (a sleeping child with its working folder in the run's folder, and a script
        whose command path is in it) is a leak too."""
        folder = os.path.realpath(tempfile.mkdtemp(prefix="relay-leak-"))
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        by_cwd = subprocess.Popen(["sleep", "600"], cwd=folder, stdin=subprocess.DEVNULL)
        by_path = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", os.path.join(folder, "x")], stdin=subprocess.DEVNULL)
        self.addCleanup(by_cwd.kill)
        self.addCleanup(by_path.kill)
        found = [pid for pid, _ in leaked_gates.find(folder)]
        self.assertEqual(sorted(found), sorted([by_cwd.pid, by_path.pid]))
        leaked_gates.stop(folder)
        by_cwd.wait(timeout=600)
        by_path.wait(timeout=600)

    def test_a_gate_outside_the_folder_is_left_running(self):
        """Pass case 3: a legitimately detached gate elsewhere is not touched."""
        self.repo(gate='echo $$ > "%s/pid"\nexec sleep 600\n' % self.tmp)
        gate, command_pid = self.start_orphan("pid")
        other = os.path.realpath(tempfile.mkdtemp(prefix="relay-other-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertEqual(leaked_gates.stop(other), [])
        self.assertIsNone(gate.poll())
        self.assertTrue(leaked_gates._alive(command_pid))
        self.assertIn(gate.pid, [pid for pid, _ in leaked_gates.stop(self.tmp)])  # cleanup: the gate and its command end
        gate.wait(timeout=600)


class FirstFailureOfAStoppedGate(unittest.TestCase):
    STOPPED = "gate: stopped at the 30-minute limit, step library tests was running"

    def test_t9_the_stopped_line_is_the_first_failing_line(self):
        import relay_gate
        out = "ci: types and lint ok (3s)\nci: lib copies identical ok (0s)\n%s\nci: RED (stopped at the time limit)" % self.STOPPED
        self.assertEqual(relay_gate.first_failure(out), [self.STOPPED])

    def test_t9_a_step_that_failed_before_the_stop_comes_first(self):
        import relay_gate
        out = "ci: library tests FAILED (9s, log: x)\n    FAIL a\n%s\nci: RED" % self.STOPPED
        self.assertEqual(relay_gate.first_failure(out), ["ci: library tests FAILED (9s, log: x)", "    FAIL a"])


if __name__ == "__main__":
    unittest.main()
