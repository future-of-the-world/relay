"""Q1: the short rules gate (what bin/ci runs as rules_tests) must pass: no test class leaves state another one reads."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
        run = subprocess.run([sys.executable, "-m", "unittest", *names], capture_output=True, text=True, cwd=ROOT, env=env)  # no wall-clock cap: under a loaded gate this takes minutes; bin/ci bounds the whole step
        self.assertEqual(run.returncode, 0, run.stderr[-1500:])

    def test_base_restores_any_variable_a_test_sets(self) -> None:
        # F1: Bench sets RELAY_CLAUDE_BIN to a fake binary in a folder Base deletes; the key is not one of the four
        # Base sets itself, so a fixed key list misses it. After the case runs, the variable must be as it was (unset).
        from relay_testbase import Base

        class Sets(Base):
            def test_sets(self) -> None:
                os.environ["RELAY_CLAUDE_BIN"] = os.path.join(self.tmp, "claude")

        before = os.environ.pop("RELAY_CLAUDE_BIN", None)
        try:
            result = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(unittest.defaultTestLoader.loadTestsFromTestCase(Sets))
            self.assertTrue(result.wasSuccessful())
            self.assertNotIn("RELAY_CLAUDE_BIN", os.environ)
        finally:
            if before is not None:
                os.environ["RELAY_CLAUDE_BIN"] = before


if __name__ == "__main__":
    unittest.main()
