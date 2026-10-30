"""One signal log per test run (findings F1, F2 of the review of a-sigterm-in-a-gate-does-not-name-its-sender): the log is in a
temporary folder of the run, shared by every test (each has its own RELAY_HOME), never the owner's ~/.relay/signals.log."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import relay_procs
import tmp_default

READER = "import sys, time; sys.path.insert(0, %r); import relay_procs; print(relay_procs.sent_by_relay(int(sys.argv[1]), float(sys.argv[2])))" % os.path.join(os.path.dirname(HERE), "lib")


class SignalLogPerRun(unittest.TestCase):
    def test_f2_a_log_passed_down_by_a_gate_is_replaced_by_one_in_the_runs_own_folder(self):
        owner = os.path.join(os.path.expanduser("~"), ".relay", "signals.log")      # what relay_gate.run passes to bin/ci
        environ = {"RELAY_SIGNAL_LOG": owner}
        made = tmp_default.pin_signal_log(environ)
        self.assertEqual(environ["RELAY_SIGNAL_LOG"], made)
        self.assertNotEqual(made, owner)
        self.assertTrue(os.path.basename(os.path.dirname(made)).startswith("relay-signals-"))
        self.assertTrue(os.path.isdir(os.path.dirname(made)))

    def test_pass_a_run_log_already_passed_down_is_kept(self):
        environ = {"RELAY_SIGNAL_LOG": os.path.join(tempfile.gettempdir(), "relay-signals-abc", "signals.log")}
        before = dict(environ)
        self.assertIsNone(tmp_default.pin_signal_log(environ))
        self.assertEqual(environ, before)

    def test_f2_the_running_test_is_not_writing_the_owners_log(self):
        log = os.environ.get("RELAY_SIGNAL_LOG", "")
        self.assertTrue(os.path.basename(os.path.dirname(log)).startswith("relay-signals-"), log)

    def test_f1_a_stop_recorded_under_one_relay_home_is_found_under_another(self):
        start = time.time() - 1
        with mock.patch.dict(os.environ, {"RELAY_HOME": os.path.join(tempfile.gettempdir(), "relay-home-a")}):
            relay_procs.record_sent(4242, False, 15, "leftover sweep: test")
        env = dict(os.environ, RELAY_HOME=os.path.join(tempfile.gettempdir(), "relay-home-b"))      # another test's own RELAY_HOME
        out = subprocess.run([sys.executable, "-I", "-c", READER, "4242", str(start)], env=env, capture_output=True, text=True, timeout=60).stdout
        self.assertIn("leftover sweep: test", out)      # pass case 1: both resolve the same log
        self.assertNotIn("None", out)


if __name__ == "__main__":
    unittest.main()
