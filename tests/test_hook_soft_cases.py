"""SoftCases (tests/hook_helpers.py): a failing case in a multi-case method is named, and the cases after it still run
(F2 of the review: the bash suites reported every failing case; plain asserts stop at the first)."""
import glob
import os
import subprocess
import unittest

from hook_helpers import SoftCases

HERE = os.path.dirname(os.path.abspath(__file__))


ran_after: list[bool] = []


def make() -> type:
    """The sample is built inside a function so that no runner collects it as a test of its own."""
    class Sample(SoftCases):
        def test_two_bad_cases(self) -> None:
            self.assertEqual(1, 2)                    # CASE-FIRST-BAD
            self.assertIn("a", "abc")                 # passes
            self.assertEqual(3, 4)                    # CASE-LATER-BAD
            ran_after.append(True)

        def test_all_good(self) -> None:
            self.assertEqual(1, 1)
            self.assertNotIn("z", "abc")
    return Sample


def run(name: str) -> unittest.TestResult:
    result = unittest.TestResult()
    make()(name).run(result)
    return result


class Soft(unittest.TestCase):
    def test_a_failure_does_not_hide_the_cases_after_it(self) -> None:
        # two asserts of three are wrong by construction (1!=2, 3!=4): both are named, and the code after them ran
        ran_after.clear()
        result = run("test_two_bad_cases")
        self.assertEqual(len(result.failures), 1)
        text = result.failures[0][1]
        self.assertIn("2 failed asserts", text)
        self.assertIn("CASE-FIRST-BAD", text)
        self.assertIn("CASE-LATER-BAD", text)
        self.assertNotIn("assertIn(\"a\"", text)   # the passing case is not listed
        self.assertEqual(ran_after, [True])   # the last line of the method ran after both failures


    def test_a_method_of_passing_cases_passes(self) -> None:
        result = run("test_all_good")
        self.assertEqual((result.failures, result.errors, result.testsRun), ([], [], 1))

    def test_every_hook_suite_uses_it(self) -> None:
        # each tests/test_hook_*.py (this file apart) builds its cases on SoftCases, none on a bare TestCase
        for path in sorted(glob.glob(os.path.join(HERE, "test_hook_*.py"))):
            if path.endswith("test_hook_soft_cases.py"):
                continue
            with open(path, encoding="utf-8") as handle:
                self.assertNotIn("(unittest.TestCase)", handle.read(), os.path.basename(path))


class Docs(unittest.TestCase):
    def test_the_plugin_readme_names_test_files_that_exist_from_the_repository_root(self) -> None:
        # F4: `tests/test_hook_*.py` in plugins/relay/README.md is the repository's tests/, not plugins/relay/tests/
        import re
        root = os.path.dirname(HERE)
        with open(os.path.join(root, "plugins", "relay", "README.md"), encoding="utf-8") as handle:
            text = handle.read()
        names = sorted(set(re.findall(r"tests/(test_hook_\w+\.py)", text)))
        self.assertIn("test_hook_check_contract.py", names)
        for name in names:
            self.assertTrue(os.path.exists(os.path.join(root, "tests", name)), name)
        self.assertIn("KIT_CONTRACT_PROJECT=<clean checkout> python3 tests/test_hook_check_contract.py", text)

    def test_no_current_doc_names_a_deleted_test_sh(self) -> None:
        import subprocess
        root = os.path.dirname(HERE)
        done = subprocess.run(["git", "grep", "-n", r"\.test\.sh", "--", "docs/delegation.md", "docs/variants/scripts.md", "tests/test_spec_flaw.py"],
                              cwd=root, capture_output=True, text=True)
        # the one left names kartoteka's own spec-check test (another repository), not a file of this one
        self.assertEqual([ln for ln in done.stdout.splitlines() if "kartoteka" not in ln], [])


class Wrappers(unittest.TestCase):
    """F1: the hook wrappers hold a few lines that exec python3 on a .py beside them; the work is in Python."""

    def test_no_hook_wrapper_holds_more_than_a_few_lines(self) -> None:
        root = os.path.dirname(HERE)
        found = sorted(glob.glob(os.path.join(root, "plugins", "*", "hooks", "*.sh")))
        self.assertIn("guard-main.sh", [os.path.basename(f) for f in found])
        for path in found:
            with open(path, encoding="utf-8") as handle:
                code = [ln for ln in handle.read().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
            # merge.sh keeps its 8-line pre-filter (no python on a Bash call that does not mention merge); the others are 3 lines
            self.assertLessEqual(len(code), 8, os.path.basename(path))
            if os.path.basename(path) in ("guard-main.sh", "inject-addition.sh"):
                self.assertLessEqual(len(code), 3, os.path.basename(path))
                self.assertTrue(os.path.exists(os.path.join(os.path.dirname(path), os.path.basename(path).replace("-", "_")[:-3] + ".py")), path)

    def test_the_guard_works_with_a_path_that_holds_no_gnu_coreutils(self) -> None:
        # only bash, git, python3, grep and dirname on PATH (no timeout, no md5sum, no jq): a write into the main checkout is still refused
        import json
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tools = os.path.join(tmp, "tools")
            os.mkdir(tools)
            for tool in ("bash", "git", "python3", "grep", "dirname", "env"):
                found = shutil.which(tool)
                self.assertIsNotNone(found, tool)
                os.symlink(found or "", os.path.join(tools, tool))
            repo = os.path.realpath(os.path.join(tmp, "repo"))
            subprocess.run(["git", "init", "-q", repo], check=True)
            event = {"tool_name": "Write", "cwd": repo, "tool_input": {"file_path": os.path.join(repo, "a.txt")}}
            hook = os.path.join(os.path.dirname(HERE), "plugins", "relay", "hooks", "guard-main.sh")
            done = subprocess.run([os.path.join(tools, "bash"), hook], input=json.dumps(event), capture_output=True, text=True,
                                  env={"PATH": tools, "HOME": tmp})
            # exit 2 and the reason: the main checkout is the repo itself, a.txt is inside it and outside .worktrees
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn("writes to the main checkout", done.stderr)


if __name__ == "__main__":
    unittest.main()
