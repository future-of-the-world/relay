"""Waits in the gate tests are bounds that only a real hang reaches, never a clock a busy machine overruns.

Measured 28-29 Oct: with 5 lanes gating, load average reached 27-35 on 12 cores and a test that takes seconds
alone took minutes; a 30 s or 200 s wait failed three gates that found nothing wrong. A quiet-machine wait here
is under 60 s, so 10 times that (600 s) is a bound only a hang reaches. Each wait polls its condition, so a pass
still returns at once."""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
HANG = 600   # seconds: ten times the slowest quiet-machine wait in these files

sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_precheck  # noqa: E402
import test_ci_python  # noqa: E402
import test_gate  # noqa: E402
import test_gate_slots  # noqa: E402
import test_gate_stops  # noqa: E402


GATE_TEST_FILES = (
    "test_delegate_small_builds.py", "test_gate.py", "test_gate_not_judged.py", "test_gate_quick.py",
    "test_gate_reuse.py", "test_gate_slots.py", "test_gate_stops.py", "test_rules_gate.py",
    "test_template_python_gate.py", "test_ci_hook_tests.py", "test_ci_python.py", "test_principles_rule.py",
)
# the rest of the files that held a fixed 20-120 s limit (28-29 Oct item); test_numbers.py and
# test_rules_gate_isolation.py belong to the scaffolding branch and stay out
OTHER_FILES = (
    "test_setup.py", "test_read_only_guard.py", "test_temporary_folders.py", "test_parallel_unittest.py",
    "test_cycle_workflow.py", "test_help_is_safe.py", "test_spec_steps.py", "test_hooks_live_keeps_output.py",
    "test_front_cd.py", "test_front_measures.py", "test_ledger_workflow_fields.py", "test_turn_limit.py",
    "test_bin_check_portable.py", "test_queue.py", "test_land.py", "test_hook_check_contract.py",
    "leaked_gates.py", "parallel_unittest.py",
)


def short_waits(text: str) -> list[int]:
    """Every literal `timeout=N)` or `wait_pid(x, N,` under HANG, except lines marked `# expected timeout`
    (a command meant to outlive its limit)."""
    found: list[int] = []
    for line in text.split("\n"):
        if "# expected timeout" in line:
            continue
        for m in re.findall(r"timeout=(\d+)[,)]|wait_pid\(\w+, (\d+),|^WAIT = (\d+)", line):
            n = int(m[0] or m[1] or m[2])
            if n < HANG:
                found.append(n)
    return found


def precheck_caps(text: str) -> list[int]:
    """Every literal `CHANGED_TESTS_TIMEOUT = N` under HANG in the precheck's source."""
    return [int(n) for n in re.findall(r"^CHANGED_TESTS_TIMEOUT = (\d+)", text, re.M) if int(n) < HANG]


class HangLimits(unittest.TestCase):
    def test_precheck_changed_tests_step_is_a_hang_bound(self) -> None:
        # 29 Oct: 16 changed test files took 199 s at load 8 and went past 230 s at load 17-35 with every test passing
        self.assertGreaterEqual(relay_precheck.CHANGED_TESTS_TIMEOUT, HANG)
        with open(os.path.join(HERE, "..", "lib", "relay_precheck.py")) as f:
            self.assertEqual(precheck_caps(f.read()), [])

    def test_the_guard_flags_a_fixed_230_s_precheck_cap(self) -> None:
        self.assertEqual(precheck_caps("CHANGED_TESTS_TIMEOUT = 230   # budget"), [230])
        self.assertEqual(precheck_caps("CHANGED_TESTS_TIMEOUT = 600"), [])

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
        for name in GATE_TEST_FILES:
            with open(os.path.join(HERE, name)) as f:
                self.assertEqual(short_waits(f.read()), [], name)

    def test_the_other_files_with_fixed_limits_are_hang_bounds_too(self) -> None:
        for name in OTHER_FILES:
            with open(os.path.join(HERE, name)) as f:
                self.assertEqual(short_waits(f.read()), [], name)

    def test_no_test_asserts_on_the_elapsed_wall_clock(self) -> None:
        # a loaded machine fails these with nothing wrong; the outcome (HUNG, the child dead) is what they assert
        for name in ("test_hook_check_contract.py", "test_bin_check_portable.py"):
            with open(os.path.join(HERE, name)) as f:
                self.assertNotRegex(f.read(), r"assertLess\((took|time\.monotonic)", name)

    def test_the_guard_flags_every_literal_wait_under_the_hang_bound(self) -> None:
        # 30 and 45 are neither 60 nor 120, the only values the first guard knew
        self.assertEqual(short_waits("gate.wait(timeout=30)\nsubprocess.run([], timeout=45)"), [30, 45])
        self.assertEqual(short_waits("wait_pid(pid_file, 20, writer_alive=f)"), [20])
        self.assertEqual(short_waits("run(a, timeout=30, check=True)\nWAIT = 60  # s\nBarrier(2, timeout=30)"), [30, 60, 30])

    def test_the_guard_passes_hang_bounds_and_marked_expected_timeouts(self) -> None:
        self.assertEqual(short_waits("wait_pid(pid_file, 600, writer_alive=f)\nx.run(a, timeout=1200)"), [])
        marked = "self.gate(self.wt, timeout=3, started=p)  # expected timeout"
        self.assertEqual(short_waits(marked), [])
        self.assertEqual(short_waits(marked + "\ngate.wait(timeout=30)"), [30])


if __name__ == "__main__":
    unittest.main()
