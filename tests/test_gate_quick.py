"""Findings F1-F4 of the review of `relay gate`'s quick mode (queue item relay-gate-runs-the-paid-evals-unless-told-quick)."""
import os
import stat
import subprocess
import sys
import unittest

from test_gate import RELAY, ROOT, Fixture, git, read, write

GATE = 'echo "args=[$*]" > "$(dirname "$0")/args"\necho gate >> "$(dirname "$0")/trace"\nexit 0\n'


class Quick(Fixture):
    def gate(self, *args):
        return subprocess.run([sys.executable, RELAY, "gate", "-C", self.wt, *args], capture_output=True, text=True, env=self.env)

    def commit(self, name):
        write(os.path.join(self.wt, "lib", name), name + "\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", name)

    def args_seen(self):
        return read(os.path.join(self.tmp, "args")).strip()

    def quick_repo(self, gate=GATE):
        """kit.toml names ci and ci_quick; ci_quick is the same script with --quick"""
        self.repo(gate=gate)
        kit = os.path.join(self.main, ".claude", "kit.toml")
        write(kit, '[gate]\nci = "%s"\nci_quick = "%s --quick"\n' % (self.script, self.script))
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "quick")
        git(self.wt, "merge", "-q", "master")

    # F2 pass 1: a gate.ci that rejects any argument is run exactly, with no --quick
    def test_f2_a_plain_gate_adds_no_argument_when_kit_names_no_quick_mode(self):
        self.repo(gate='[ $# -eq 0 ] || exit 2\necho "args=[$*]" > "$(dirname "$0")/args"\nexit 0\n')
        done = self.gate()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        log = [line for line in read(done.stdout.splitlines()[1]).splitlines()]
        self.assertEqual(log[1], "cmd " + self.script)

    # F2 pass 2: ci_quick names the free mode
    def test_f2_a_plain_gate_runs_the_ci_quick_binding(self):
        self.quick_repo()
        self.assertEqual(self.gate().returncode, 0)
        self.assertEqual(self.args_seen(), "args=[--quick]")

    # F2 pass 3: --paid runs gate.ci alone
    def test_f2_paid_runs_gate_ci_with_no_argument(self):
        self.quick_repo()
        self.assertEqual(self.gate("--paid").returncode, 0)
        self.assertEqual(self.args_seen(), "args=[]")

    # F2 pass 4: -- args are passed unchanged in both setups
    def test_f2_explicit_args_win_in_both_setups(self):
        self.quick_repo()
        self.assertEqual(self.gate("--", "--other").returncode, 0)
        self.assertEqual(self.args_seen(), "args=[--other]")
        self.commit("c.py")
        self.assertEqual(self.gate("--", "--other").returncode, 0)

    def test_f2_relay_itself_binds_the_quick_mode(self):
        import relay_gate
        self.assertEqual(relay_gate.quick_binding(ROOT), "bin/ci --quick")

    # F1
    def paid_tool(self):
        tool = os.path.join(self.wt, "bin", "paid-cost")
        write(tool, '#!/bin/sh\ncase "$1" in estimate) echo EST;; today) echo SPENT;; esac\n'
              'echo "$1" >> "$(dirname "$0")/../../../../trace"\n', stat.S_IRWXU)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "tool")

    def test_f1_paid_prints_estimate_and_spend_before_the_gate_runs(self):
        self.quick_repo()
        # the tool and the gate both append to <tmp>/trace (the tool is at <tmp>/main/.worktrees/x/bin: four levels up)
        self.paid_tool()
        done = self.gate("--paid")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("EST", done.stderr)
        self.assertIn("SPENT", done.stderr)
        # worked out by hand: estimate, then today, then the gate's own line
        self.assertEqual(read(os.path.join(self.tmp, "trace")).split(), ["estimate", "today", "gate"])

    def test_f1_plain_and_explicit_args_print_no_cost_line(self):
        self.quick_repo()
        self.paid_tool()
        self.assertNotIn("EST", self.gate().stderr)
        self.commit("c.py")
        self.assertNotIn("EST", self.gate("--", "--other").stderr)

    def test_f1_paid_without_a_cost_tool_just_runs(self):
        self.quick_repo()
        done = self.gate("--paid")
        self.assertEqual(done.returncode, 0)
        self.assertNotIn("paid:", done.stderr)

    # F4
    def test_f4_paid_with_explicit_args_is_refused(self):
        self.quick_repo()
        done = self.gate("--paid", "--", "--quick")
        self.assertEqual(done.returncode, 2)
        self.assertIn("do not go together", done.stdout + done.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "args")))


if __name__ == "__main__":
    unittest.main()
