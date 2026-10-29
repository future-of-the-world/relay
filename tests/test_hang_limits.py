"""Waits in the gate tests are bounds that only a real hang reaches, never a clock a busy machine overruns.

Measured 28-29 Oct: with 5 lanes gating, load average reached 27-35 on 12 cores and a test that takes seconds
alone took minutes; a 30 s or 200 s wait failed three gates that found nothing wrong. A quiet-machine wait here
is under 60 s, so 10 times that (600 s) is a bound only a hang reaches. Each wait polls its condition, so a pass
still returns at once."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
HANG = 600   # seconds: ten times the slowest quiet-machine wait in these files

import test_ci_python  # noqa: E402
import test_gate  # noqa: E402
import test_gate_slots  # noqa: E402
import test_gate_stops  # noqa: E402


class HangLimits(unittest.TestCase):
    def test_waits_are_hang_bounds_not_quiet_machine_clocks(self) -> None:
        limits = {
            "test_gate_slots.BOUND": test_gate_slots.BOUND,
            "test_gate_stops.WAIT": test_gate_stops.WAIT,
            "test_ci_python.WAIT": test_ci_python.WAIT,
            "test_gate.GATE_STOP_GRACE": test_gate.GATE_STOP_GRACE,
        }
        short = {name: v for name, v in limits.items() if v < HANG}
        self.assertEqual(short, {})

    def test_template_gate_and_orphan_waits_are_hang_bounds(self) -> None:
        import re
        for name in ("test_template_python_gate.py", "test_gate.py"):
            with open(os.path.join(HERE, name)) as f:
                text = f.read()
            # a literal timeout= or wait_pid(..., N, ...) number under the hang bound is a clock a loaded machine overruns
            small = [m for m in re.findall(r"timeout=(\d+)\)|wait_pid\(\w+, (\d+),", text)
                     if any(m) and int([x for x in m if x][0]) in (60, 120)]
            self.assertEqual(small, [], name)


if __name__ == "__main__":
    unittest.main()
