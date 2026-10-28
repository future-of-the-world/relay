"""A project of plain .py files is a python project, and an unfilled template gate step fails (queue: python green check)."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import Base  # noqa: E402


# stands in for `python3 -m pytest`: runs every test_* function of every test_*.py in the folder, exit 1 on a failure
STUB_PYTEST = """import glob, sys
failed = 0
for name in sorted(glob.glob("test_*.py")):
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

    def render(self, script, stack, tool=""):
        dest = os.path.join(self.proj, "bin", script)
        self.rs.copy_template(f"bin-{script}", dest, mode_exec=True, replacements={"tool": tool, "stack": stack, "branch": "main", **self.rs.template_steps(stack)})
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
        env = {**os.environ, "PATH": shim + os.pathsep + os.environ["PATH"], "PYTHONPATH": shim}
        return subprocess.run([dest], cwd=self.proj, env=env, capture_output=True, text=True, timeout=120)

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


if __name__ == "__main__":
    unittest.main()
