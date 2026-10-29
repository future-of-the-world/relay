"""Port of plugins/relay/tests/check-contract.test.sh: the contract of a project's check script (README, "The check-script
contract"), the behaviour the shared worker and fixer rely on. Runs against the eval fixture's bin/check (a temporary copy);
KIT_CONTRACT_PROJECT=<clean checkout> runs it against that project's own gate.check instead, adding the probe change
openspec/changes/contract-probe and, for the tests mode, the two probe test files named by CONTRACT_PASS_FILE and
CONTRACT_FAIL_FILE (relative to the project; they must exist: one passing, one failing). Both probes and .ci/check are removed."""
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from typing import Tuple

from hook_helpers import ROOT, SoftCases

KIT = os.path.join(ROOT, "plugins", "relay", "bin", "kit")
FIXTURE = os.path.join(ROOT, "evals", "plugin", "fixture")
TASKS = """## 1. Probes

Wave 1 · depends on: none

- [ ] 1.1 Green. Reads: none. Tests: none. Files: none. Check: `true`
- [ ] 1.2 Red. Reads: none. Tests: none. Files: none. Check: `echo probe-finding >&2; false`
- [ ] 1.3 Hangs. Reads: none. Tests: none. Files: none. Check: `sleep 30`
- [ ] 1.4 Flips. Reads: none. Tests: none. Files: none. Check: `test -f .ci/probe-ok`
- [ ] 1.5 Third. Reads: none. Tests: none. Files: none. Check: `false`
"""
PROJECT = os.environ.get("KIT_CONTRACT_PROJECT")


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd, check=True, capture_output=True)


class CheckContract(SoftCases):
    pass_file = ""
    fail_file = ""

    @classmethod
    def setUpClass(cls) -> None:
        if PROJECT:
            cls.P = os.path.realpath(PROJECT)
            cls.tmp = ""
            cls.pass_file = os.environ.get("CONTRACT_PASS_FILE", "")
            cls.fail_file = os.environ.get("CONTRACT_FAIL_FILE", "")
        else:
            cls.tmp = os.path.realpath(tempfile.mkdtemp())
            cls.P = os.path.join(cls.tmp, "project")
            shutil.copytree(FIXTURE, cls.P, symlinks=True)
            git(cls.P, "init", "-q", "-b", "master", ".")
            git(cls.P, "add", "-A")
            git(cls.P, "commit", "-q", "-m", "fixture")
            cls.pass_file, cls.fail_file = "src/probe-pass.test.ts", "src/probe-fail.test.ts"
            for name, expect in ((cls.pass_file, "1"), (cls.fail_file, "2")):
                with open(os.path.join(cls.P, name), "w") as handle:
                    handle.write("import { expect, test } from 'bun:test';\ntest('probe', () => { expect(1).toBe(%s); });\n" % expect)
        done = subprocess.run([KIT, "get", "gate.check"], cwd=cls.P, capture_output=True, text=True)
        cls.check = done.stdout.strip()
        assert os.access(os.path.join(cls.P, cls.check), os.X_OK), "%s is not executable" % cls.check

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.tmp:
            shutil.rmtree(cls.tmp, ignore_errors=True)
        else:
            shutil.rmtree(os.path.join(cls.P, "openspec", "changes", "contract-probe"), ignore_errors=True)
            shutil.rmtree(os.path.join(cls.P, ".ci", "check"), ignore_errors=True)

    def setUp(self) -> None:
        change = os.path.join(self.P, "openspec", "changes", "contract-probe")
        os.makedirs(change, exist_ok=True)
        with open(os.path.join(change, "tasks.md"), "w") as handle:
            handle.write(TASKS)
        os.makedirs(os.path.join(self.P, ".ci"), exist_ok=True)
        shutil.rmtree(os.path.join(self.P, ".ci", "check"), ignore_errors=True)  # each case starts a fresh failure count
        self.flag = os.path.join(self.P, ".ci", "probe-ok")
        if os.path.exists(self.flag):
            os.remove(self.flag)

    def run_check(self, *args: str, cwd: str = "", **env: str) -> Tuple[int, str]:
        done = subprocess.run(["./" + self.check if not cwd else os.path.join(self.P, self.check)] + list(args), cwd=cwd or self.P,
                              env=dict(os.environ, **env), capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

    def test_green_is_quiet_exit_0(self) -> None:
        rc, out = self.run_check("contract-probe", "1.1")
        self.assertEqual(rc, 0)
        self.assertIn("passed", out)
        self.assertLessEqual(len(out.strip().splitlines()), 3)
        self.assertNotRegex(out, "BUDGET SPENT|HUNG|TIME BUDGET SPENT")

    def test_red_rounds_and_budget_spent_on_the_third(self) -> None:
        rc, out = self.run_check("contract-probe", "1.2")
        self.assertEqual(rc, 1)
        self.assertRegex(out, "probe-finding|FAILED")
        self.assertIn("round 1 of 3", out)
        self.assertNotIn("BUDGET SPENT", out)
        log = re.search(r"log: ([^)]+)\)", out)
        self.assertTrue(log and os.path.isfile(os.path.join(self.P, log.group(1))), "the log path it names exists")
        rc, out = self.run_check("contract-probe", "1.2", "--failed")
        self.assertEqual(rc, 1)  # --failed is accepted
        self.assertIn("round 2 of 3", out)
        self.assertNotIn("BUDGET SPENT", out)
        self.assertIn("BUDGET SPENT", self.run_check("contract-probe", "1.2")[1])

    def test_a_pass_resets_the_count(self) -> None:
        self.run_check("contract-probe", "1.4")
        self.run_check("contract-probe", "1.4")
        open(self.flag, "w").close()
        self.assertEqual(self.run_check("contract-probe", "1.4")[0], 0)
        os.remove(self.flag)
        self.run_check("contract-probe", "1.4")
        # two failures since the pass: a third would spend the budget, the second does not
        self.assertNotIn("BUDGET SPENT", self.run_check("contract-probe", "1.4")[1])

    def test_a_hung_check_is_killed_and_reported(self) -> None:
        start = time.monotonic()
        rc, out = self.run_check("contract-probe", "1.3", CHECK_TIMEOUT="1")
        self.assertEqual(rc, 1)
        self.assertIn("HUNG", out)
        self.assertLess(time.monotonic() - start, 15)  # the sleep 30 was killed, not waited for

    def test_time_budget(self) -> None:
        self.assertIn("TIME BUDGET SPENT", self.run_check("contract-probe", "1.5", CHECK_WORKER_MINUTES="0")[1])
        rc, out = self.run_check("contract-probe", "1.1", CHECK_WORKER_MINUTES="0")
        self.assertIn("TIME BUDGET SPENT", out)
        self.assertEqual(rc, 0)  # a green run still exits 0

    def test_usage_and_unreadable_tasks_exit_2(self) -> None:
        self.assertEqual(self.run_check()[0], 2)
        self.assertEqual(self.run_check("contract-probe", "9.9")[0], 2)
        self.assertEqual(self.run_check("no-such-change", "1.1")[0], 2)

    def test_from_a_subfolder(self) -> None:
        sub = os.path.join(self.P, "sub")
        os.makedirs(sub, exist_ok=True)
        self.addCleanup(shutil.rmtree, sub, True)
        self.assertEqual(self.run_check("contract-probe", "1.1", cwd=sub)[0], 0)

    def test_tests_mode(self) -> None:
        if not (self.pass_file and self.fail_file):
            self.skipTest("set CONTRACT_PASS_FILE and CONTRACT_FAIL_FILE")
        self.assertEqual(self.run_check("--tests", self.pass_file)[0], 0)
        rc, out = self.run_check("--tests", self.fail_file)
        self.assertEqual(rc, 1)
        self.assertIn(self.fail_file, out)
        self.assertEqual(self.run_check("--tests", self.fail_file, "--failed")[0], 1)
        self.assertIn("BUDGET SPENT", self.run_check("--tests", self.fail_file)[1])  # the third failure in a row
        self.assertEqual(self.run_check("--tests")[0], 2)


if __name__ == "__main__":
    unittest.main()
