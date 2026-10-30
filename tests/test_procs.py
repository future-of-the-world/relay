"""lib/relay_procs.py: the one parser of `ps`, and the one stop (SIGTERM, then SIGKILL after STOP_GRACE)."""
import os
import signal
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import relay_procs


class Parse(unittest.TestCase):
    def test_a_line_becomes_a_record_with_a_start_time_and_the_whole_command(self):
        """pid 1469 ppid 1 pgid 1469, started Thu Oct 29 09:05:12 2026, command with spaces kept whole."""
        text = "  1469     1  1469 Thu Oct 29 09:05:12 2026 /bin/sh /tmp/relay-run-x/relay-gate-y/gate.sh --a  b\n"
        [proc] = relay_procs.parse_ps(text)
        self.assertEqual((proc.pid, proc.ppid, proc.pgid), (1469, 1, 1469))
        self.assertEqual(proc.command, "/bin/sh /tmp/relay-run-x/relay-gate-y/gate.sh --a  b")
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.started)), "2026-10-29 09:05:12")

    def test_a_line_of_another_shape_is_skipped_not_guessed(self):
        text = "PID PPID PGID\n12 1 12 garbage garbage\n7 1 7 Thu Oct 29 09:05:12 2026 sleep 1\n"
        self.assertEqual([p.pid for p in relay_procs.parse_ps(text)], [7])

    def test_the_real_ps_shows_this_process_with_its_parent(self):
        mine = {p.pid: p for p in relay_procs.read_procs()}[os.getpid()]
        self.assertEqual(mine.ppid, os.getppid())
        self.assertEqual(mine.pgid, os.getpgrp())


class Stop(unittest.TestCase):
    def test_a_target_that_ignores_sigterm_is_killed_after_the_grace_as_a_group(self):
        """Alive throughout: SIGTERM first, then, once STOP_GRACE (0.2 s here) has passed, SIGKILL, both to the group."""
        sent = []
        with mock.patch.object(relay_procs, "send", lambda pid, group, sig, reason="": sent.append((pid, group, sig))), \
                mock.patch.object(relay_procs, "_still", return_value=True), mock.patch.object(relay_procs, "STOP_GRACE", 0.2):
            killed = relay_procs.stop([(1469, True)])
        self.assertEqual(sent, [(1469, True, signal.SIGTERM), (1469, True, signal.SIGKILL)])
        self.assertEqual(killed, [(1469, True)])

    def test_a_target_that_ends_on_sigterm_is_not_killed(self):
        sent = []
        with mock.patch.object(relay_procs, "send", lambda pid, group, sig, reason="": sent.append((pid, group, sig))), \
                mock.patch.object(relay_procs, "_still", return_value=False):
            killed = relay_procs.stop([(500, False)])
        self.assertEqual(sent, [(500, False, signal.SIGTERM)])
        self.assertEqual(killed, [])


if __name__ == "__main__":
    unittest.main()
