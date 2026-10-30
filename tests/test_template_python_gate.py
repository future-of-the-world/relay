"""A project of plain .py files is a python project, and an unfilled template gate step fails (queue: python green check)."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import Base  # noqa: E402


# stands in for `python3 -m pytest`: runs every test_* function of every test_*.py in the folder, exit 1 on a failure
STUB_PYTEST = """import glob, sys
failed = 0
names = [a for a in sys.argv[1:] if a.endswith(".py")] or sorted(glob.glob("test_*.py"))
for name in names:
    scope = {}
    exec(compile(open(name).read(), name, "exec"), scope)
    for key, fn in scope.items():
        if key.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
print("1 failed" if failed else "passed")
sys.exit(1 if failed else 0)
"""


class PythonGate(Base):
    def setUp(self):
        super().setUp()
        import relay_setup
        self.rs = relay_setup
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proj = tmp.name
        subprocess.run(["git", "init", "-q", self.proj], check=True)

    def write(self, rel, text):
        with open(os.path.join(self.proj, rel), "w") as handle:
            handle.write(text)

    def render(self, script, stack, tool="", args=()):
        dest = os.path.join(self.proj, "bin", script)
        self.rs.copy_template(f"bin-{script}", dest, mode_exec=True, replacements={"tool": tool, "stack": stack, "branch": "main", **self.rs.template_steps(stack)})
        self.install_shim()
        return self.run_script(dest, args)

    def install_shim(self):
        # python3 on PATH is the interpreter running this test; `-m pytest` finds a stand-in pytest in a temporary
        # folder (a few lines that run test_*.py functions), so the test needs no pytest on the machine that runs it
        shim = os.path.join(self.proj, ".shim")
        os.makedirs(os.path.join(shim, "pytest"), exist_ok=True)
        if not os.path.lexists(os.path.join(shim, "python3")):
            os.symlink(sys.executable, os.path.join(shim, "python3"))
        with open(os.path.join(shim, "pytest", "__main__.py"), "w") as handle:
            handle.write(STUB_PYTEST)
        with open(os.path.join(shim, "pytest", "__init__.py"), "w") as handle:
            handle.write("")

    def run_script(self, dest, args=()):
        shim = os.path.join(self.proj, ".shim")
        env = {**os.environ, "PATH": shim + os.pathsep + os.environ["PATH"], "PYTHONPATH": shim}
        return subprocess.run([dest, *args], cwd=self.proj, env=env, capture_output=True, text=True, timeout=1200)

    def test_test_files_without_pyproject_are_python(self):
        # tally.py + test_tally.py, no pyproject.toml: the trial of the queue item
        self.write("tally.py", "")
        self.write("test_tally.py", "")
        d = self.rs.detect(self.proj)
        self.assertEqual((d["stack"], d["tool"]), ("python", "python"))

    def test_empty_folder_stays_unknown(self):
        self.assertEqual(self.rs.detect(self.proj)["stack"], "unknown")

    def test_python_check_runs_pytest_and_goes_red_on_a_failing_test(self):
        self.write("test_tally.py", "def test_x():\n    assert 1 == 2\n")
        r = self.render("check", "python", "python")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAILED at tests", r.stdout)

    def test_python_ci_runs_pytest_and_is_green_on_a_passing_test(self):
        self.write("test_tally.py", "def test_x():\n    assert 1 == 1\n")
        r = self.render("ci", "python", "python")
        log = open(os.path.join(self.proj, ".ci", "ci.log")).read()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr + log)
        self.assertIn("ci: tests ok", r.stdout)

    def test_unfilled_placeholder_fails_check_and_says_what_to_fill_in(self):
        r = self.render("check", "unknown")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NOT CONFIGURED", r.stdout)
        self.assertNotIn("passed", r.stdout)

    def test_unfilled_placeholder_fails_ci(self):
        r = self.render("ci", "unknown")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("ci: RED", r.stdout)
        with open(os.path.join(self.proj, ".ci", "ci.log")) as handle:
            self.assertIn("NOT CONFIGURED", handle.read())

    def setup_proj(self, files):
        for name, text in files.items():
            self.write(name, text)
        _, _, done, todo = self.rs.setup(self.proj, install_runner=lambda r, k: (True, ""), uninstall_runner=lambda r, k: (True, ""))
        self.install_shim()
        return todo

    def test_setup_writes_pytest_steps_into_bin_check_and_bin_ci(self):
        # F2: the whole path through setup(); without the step marks filled, bin/check holds "{{check_steps}}" and passes
        self.setup_proj({"tally.py": "", "test_tally.py": "def test_x():\n    assert 1 == 2\n"})
        for script in ("check", "ci"):
            text = open(os.path.join(self.proj, "bin", script)).read()
            self.assertIn('"-m", "pytest"' if script == "check" else "python3 -m pytest", text)
            self.assertNotIn("{{", text)
        r = self.run_script(os.path.join(self.proj, "bin", "check"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAILED at tests", r.stdout)

    def test_setup_on_a_readme_only_folder_writes_gates_that_fail_not_configured(self):
        self.setup_proj({"README.md": "hi\n"})
        r = self.run_script(os.path.join(self.proj, "bin", "check"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NOT CONFIGURED", r.stdout)
        r = self.run_script(os.path.join(self.proj, "bin", "ci"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("ci: RED", r.stdout)

    def test_setup_todo_for_bin_wt_points_at_its_todo_on_every_stack(self):
        # F1: bin/wt has no steps and no placeholder; its line is the old "fill in the commands where it says TODO"
        todo = self.setup_proj({"tally.py": "", "test_tally.py": ""})
        self.assertIn("bin/wt: fill in the python commands where it says TODO", todo)
        self.assertTrue([t for t in todo if t.startswith("bin/check: check the python steps it was given")])
        self.assertTrue([t for t in todo if t.startswith("bin/ci: check the python steps it was given")])

    def test_setup_todo_for_bin_wt_on_an_unknown_stack_does_not_say_not_configured(self):
        todo = self.setup_proj({"README.md": "hi\n"})
        wt = [t for t in todo if t.startswith("bin/wt:")]
        self.assertEqual(wt, ["bin/wt: fill in the unknown commands where it says TODO"])
        for script in ("check", "ci"):
            self.assertTrue([t for t in todo if t.startswith(f"bin/{script}:") and "NOT CONFIGURED" in t])

    def test_check_tests_runs_only_the_named_files(self):
        # F3: test_b fails; naming only test_a must be green, no names must be red, TEST_FILES from outside still counts
        self.write("test_a.py", "def test_a():\n    assert True\n")
        self.write("test_b.py", "def test_b():\n    assert False\n")
        r = self.render("check", "python", "python", args=("--tests", "test_a.py"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        dest = os.path.join(self.proj, "bin", "check")
        self.assertEqual(self.run_script(dest, ("--tests", "test_a.py", "--failed")).returncode, 0)
        self.assertEqual(self.run_script(dest, ()).returncode, 1)
        os.environ["TEST_FILES"] = "test_b.py"
        self.addCleanup(os.environ.pop, "TEST_FILES", None)
        self.assertEqual(self.run_script(dest, ()).returncode, 1)
        os.environ["TEST_FILES"] = "test_a.py"
        self.assertEqual(self.run_script(dest, ()).returncode, 0)

    def fake_python_without_pytest(self):
        # a python3 on PATH that has no pytest: what `python3 -m pytest` prints then (wording of CPython)
        shim = os.path.join(self.proj, ".nopytest")
        os.makedirs(shim, exist_ok=True)
        fake = os.path.join(shim, "python3")
        with open(fake, "w") as handle:
            handle.write("#!/bin/sh\necho \"$0: No module named pytest\" >&2\nexit 1\n")
        os.chmod(fake, 0o755)
        return shim

    def test_ci_summary_carries_the_cause_when_the_test_tool_is_missing(self):
        # the line 'No module named pytest' matches neither FAIL nor error, so the old summary showed no cause
        shim = self.fake_python_without_pytest()
        dest = os.path.join(self.proj, "bin", "ci")
        self.rs.copy_template("bin-ci", dest, mode_exec=True, replacements={"tool": "python", "stack": "python", "branch": "main", **self.rs.template_steps("python")})
        r = subprocess.run([dest], cwd=self.proj, env={**os.environ, "PATH": shim + os.pathsep + os.environ["PATH"]}, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("ci: tests FAILED", r.stdout)
        self.assertIn("No module named pytest", r.stdout)

    def test_ci_summary_does_not_repeat_a_cause_the_filter_already_showed(self):
        self.write("test_tally.py", "def test_x():\n    assert 1 == 2\n")
        r = self.render("ci", "python", "python")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("1 failed"), 1, r.stdout)

    def test_setup_todo_names_the_red_step_when_the_test_tool_is_missing(self):
        shim = self.fake_python_without_pytest()
        with mock.patch.dict(os.environ, {"PATH": shim + os.pathsep + os.environ["PATH"]}):
            todo = self.setup_proj({"tally.py": "", "test_tally.py": ""})
        red = [t for t in todo if "pytest" in t and "bin/ci" in t]
        self.assertEqual(len(red), 1, todo)
        self.assertIn("red", red[0])
        self.assertIn('"tests"', red[0])

    def test_setup_todo_has_no_red_warning_when_the_test_tool_is_installed(self):
        todo = self.setup_proj({"tally.py": "", "test_tally.py": ""}) if self.python_has_pytest() else None
        if todo is None:
            self.skipTest("python3 on this machine has no pytest")
        self.assertEqual([t for t in todo if "stays red" in t], [])

    def python_has_pytest(self):
        return subprocess.run(["python3", "-c", "import pytest"], capture_output=True).returncode == 0


if __name__ == "__main__":
    unittest.main()
