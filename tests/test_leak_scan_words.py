"""Review F1/F2 of a-land-test-leaks-gate-scripts-that-load: the leak scan names a leaked process as a process, and says
so when its working-folder half could not run."""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import leaked_gates
import run_unittest


class LeakedProcessWords(unittest.TestCase):
    def test_a_leaked_sleep_is_reported_as_a_leaked_process_and_fails_the_run(self):
        """F1 failing case and pass case 1: pid + command in a 'leaked process' line, exit 1; a stopped sleep is reaped."""
        started = []

        def leaving_test(**_):  # stands for the tests: leaves a sleep with its working folder in the run's TMPDIR
            started.append(subprocess.Popen(["sleep", "600"], cwd=os.environ["TMPDIR"], stdin=subprocess.DEVNULL))
            self.addCleanup(started[0].kill)
            return mock.Mock(result=mock.Mock(wasSuccessful=lambda: True))

        buf = io.StringIO()
        with mock.patch("unittest.main", side_effect=leaving_test), redirect_stdout(buf):
            code = run_unittest.run(["x"])
        proc = started[0]
        self.assertEqual(code, 1)
        self.assertNotIn("leaked gate", buf.getvalue())
        self.assertIn("FAIL leaked process: pid %d" % proc.pid, buf.getvalue())
        proc.wait(timeout=30)

    def test_no_leak_prints_nothing_and_keeps_the_test_code(self):
        """F1 pass case 3."""
        buf = io.StringIO()
        with mock.patch("unittest.main") as main, redirect_stdout(buf):
            main.return_value.result.wasSuccessful.return_value = True
            self.assertEqual(run_unittest.run(["x"]), 0)
            main.return_value.result.wasSuccessful.return_value = False
            self.assertEqual(run_unittest.run(["x"]), 1)
        self.assertNotIn("leaked", buf.getvalue())


class CwdScanSkipped(unittest.TestCase):
    def setUp(self):
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="relay-leak-"))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def test_a_failing_lsof_is_noted(self):
        """F2 pass case 1: lsof missing or timed out -> the note is given (and the path-based half still works)."""
        by_path = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", os.path.join(self.folder, "x")],
                                   stdin=subprocess.DEVNULL)
        self.addCleanup(by_path.kill)
        real = subprocess.run
        for failure in (OSError("no lsof"), subprocess.TimeoutExpired("lsof", 60)):
            def fake(cmd, *a, **k):
                if cmd[0] == "lsof":
                    raise failure
                return real(cmd, *a, **k)

            notes = []
            with mock.patch("os.path.isdir", return_value=False), mock.patch("subprocess.run", side_effect=fake):
                found = leaked_gates.find(self.folder, notes)
            self.assertEqual(notes, [leaked_gates.CWD_SKIPPED])
            self.assertEqual([pid for pid, _ in found], [by_path.pid])

    def test_a_working_scan_gives_no_note(self):
        """F2 pass case 2 and 3: with the scan available (/proc or lsof) a sleep with cwd in the folder is found, no note."""
        proc = subprocess.Popen(["sleep", "600"], cwd=self.folder, stdin=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        notes = []
        self.assertEqual([pid for pid, _ in leaked_gates.find(self.folder, notes)], [proc.pid])
        self.assertEqual(notes, [])
        leaked_gates.stop(self.folder)
        proc.wait(timeout=30)


if __name__ == "__main__":
    unittest.main()
