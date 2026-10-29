"""bin/check template (Python, standard library) on a PATH with no GNU tools (no timeout, gtimeout, md5sum, perl): green passes, a hang is HUNG."""
import os
import signal
import time
import shutil
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

from pidfile import wait_pid

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "bin-check"
TOOLS = ["git", "python3", "sleep", "true", "false", "sh", "env"]  # no timeout, gtimeout, md5sum, md5, perl, bash


STEP_OK = 'run_step("ok", ["true"])'


def sh_step(name, script):
    return "run_step(%r, ['sh', '-c', %r])" % (name, script)


class BinCheckPortable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.proj = base / "proj"
        (self.proj / "bin").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        # A PATH of symlinks to the needed tools only: no timeout, no gtimeout.
        self.toolbin = base / "tools"
        self.toolbin.mkdir()
        for t in TOOLS:
            found = shutil.which(t)
            if found:
                (self.toolbin / t).symlink_to(found)
        for gnu in ("timeout", "gtimeout", "md5sum", "md5", "perl", "bash"):
            self.assertFalse((self.toolbin / gnu).exists())

    def write(self, step, drop=()):
        text = TEMPLATE.read_text().replace("{{check_steps}}", step)
        script = self.proj / "bin" / "check"
        script.write_text(text)
        script.chmod(0o755)
        for t in drop:
            (self.toolbin / t).unlink(missing_ok=True)

    def run_check(self, *args, timeout_s="30"):
        env = {"PATH": str(self.toolbin), "CHECK_TIMEOUT": timeout_s, "HOME": self.tmp.name}
        return subprocess.run([sys.executable, str(self.proj / "bin" / "check"), *args],
                              cwd=self.proj, env=env, capture_output=True, text=True, timeout=60)

    def test_green_step_passes_without_timeout(self):
        self.write(STEP_OK)
        r = self.run_check("change", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("passed", r.stdout)

    def test_hanging_step_is_hung_within_bound(self):
        # CHECK_TIMEOUT=1 and a 30 s sleep: the wrapper must kill it and report HUNG, exit 1.
        self.write('run_step("sleeper", ["sleep", "30"])')
        r = self.run_check("change", "1", timeout_s="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("HUNG: sleeper exceeded 1s", r.stdout)

    def test_tests_key_hash_works_without_md5sum(self):
        # --tests names its state file by a hash; with no md5sum the fallback must still give one.
        self.write(STEP_OK)
        r = self.run_check("--tests", "a.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = [p.name for p in (self.proj / ".ci" / "check").iterdir()]
        self.assertTrue(any(n.startswith("tests-") and len(n.split(".")[0]) == len("tests-") + 8
                            for n in names), names)

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def wait_for(self, cond, what, secs=20):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            if cond():
                return
            time.sleep(0.05)
        self.fail("timeout waiting for " + what)

    def _signal_check_group(self, signum):
        pidfile = self.proj / "step.pid"
        self.write(sh_step("sleeper", "echo $$ > %s; exec sleep 177" % pidfile))
        env = {"PATH": str(self.toolbin), "CHECK_TIMEOUT": "100", "HOME": self.tmp.name}
        out = self.proj / "out.log"
        with open(out, "w") as fh:
            proc = subprocess.Popen([sys.executable, str(self.proj / "bin" / "check"), "c", "1"],
                                    cwd=self.proj, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        pid = wait_pid(pidfile)
        self.addCleanup(lambda: self.alive(pid) and os.kill(pid, signal.SIGKILL))
        os.killpg(proc.pid, signum)
        proc.wait(timeout=20)
        # The step lives in its own session: only the wrapper can take it down.
        self.wait_for(lambda: not self.alive(pid), "step gone after signal")
        return (self.proj / ".ci" / "check" / "task-1.log").read_text(), out.read_text()

    def test_sigterm_to_check_group_takes_step_down(self):
        self._signal_check_group(signal.SIGTERM)

    def test_sigint_to_check_group_takes_step_down_without_traceback(self):
        log, out = self._signal_check_group(signal.SIGINT)
        self.assertNotIn("Traceback", log + out)

    def test_hung_step_is_gone_afterwards(self):
        pidfile = self.proj / "step.pid"
        self.write(sh_step("sleeper", "echo $$ > %s; exec sleep 30" % pidfile))
        r = self.run_check("change", "1", timeout_s="1")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.alive(wait_pid(pidfile, writer_alive=lambda: False)))

    def test_timeout_zero_means_no_bound(self):
        self.write(STEP_OK)
        r = self.run_check("change", "1", timeout_s="0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("passed", r.stdout)

    def test_signal_killed_step_fails(self):
        self.write(sh_step("crash", "kill -SEGV $$"))
        r = self.run_check("change", "1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAILED at crash", r.stdout)

    def test_green_and_red(self):
        self.write(STEP_OK)
        r = self.run_check("change", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.write('run_step("bad", ["false"])')
        r = self.run_check("change", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED at bad (round 1 of 3", r.stdout)

    def test_third_red_round_says_budget_spent_and_green_resets(self):
        self.write('run_step("bad", ["false"])')
        outs = [self.run_check("change", "1").stdout for _ in range(3)]
        self.assertIn("round 2 of 3", outs[1])
        self.assertIn("round 3 of 3", outs[2])
        self.assertIn("BUDGET SPENT: stop fixing and report", outs[2])
        self.assertNotIn("BUDGET SPENT", outs[1])
        self.write(STEP_OK)
        self.assertEqual(self.run_check("change", "1").returncode, 0)
        self.assertFalse((self.proj / ".ci" / "check" / "task-1.fails").exists())

    def test_missing_command_is_a_failed_step_not_a_traceback(self):
        self.write('run_step("nope", ["no-such-tool-xyz"])')
        r = self.run_check("change", "1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAILED at nope", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_tests_arguments_become_test_files_minus_failed(self):
        # the step exits 0 only when it got exactly a.py b.py
        self.write('run_step("args", ["python3", "-c", "import sys; sys.exit(0 if sys.argv[1:] == [\'a.py\', \'b.py\'] else 1)", *TEST_FILES])')
        r = self.run_check("--tests", "a.py", "--failed", "b.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_hang_is_hung_and_does_not_wait_extra(self):
        pidfile = self.proj / "step.pid"
        self.write(sh_step("sleeper", "echo $$ > %s; exec sleep 30" % pidfile))
        t0 = time.monotonic()
        r = self.run_check("change", "1", timeout_s="1")
        took = time.monotonic() - t0
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("HUNG: sleeper exceeded 1s", r.stdout)
        self.assertFalse(self.alive(wait_pid(pidfile, writer_alive=lambda: False)))
        # TERM ends sleep at once; a fixed extra wait would make this >= 6 s.
        self.assertLess(took, 5)


if __name__ == "__main__":
    unittest.main()
