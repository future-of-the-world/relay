"""Q1: the short rules gate (what bin/ci runs as rules_tests) must pass: no test class leaves state another one reads."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class RulesGateIsolation(unittest.TestCase):
    def test_rules_tests_command_passes_in_the_order_unittest_runs_them(self) -> None:
        # The names come from the same loader bin/ci uses; before the fix TestPrinciplesRule errored on a deleted
        # fixture root that test_roles had left in RELAY_ROOT.
        names = subprocess.run([sys.executable, os.path.join(ROOT, "lib", "relay_textonly.py"), "tests"],
                               capture_output=True, text=True, check=True, cwd=ROOT).stdout.split()
        self.assertTrue(names)
        names = [n for n in names if n != "tests.test_rules_gate_isolation"]
        env = {k: v for k, v in os.environ.items() if k not in ("RELAY_ROOT", "RELAY_HOME", "RELAY_PROJECTS", "CLAUDE_CONFIG_DIR")}
        run = subprocess.run([sys.executable, "-m", "unittest", *names], capture_output=True, text=True, cwd=ROOT, env=env, timeout=200)
        self.assertEqual(run.returncode, 0, run.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
