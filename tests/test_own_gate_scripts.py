"""relay's own bin/check and bin/wt exist, so `relay doctor` shows no FIX for gate.check or gate.wt."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class OwnGateScripts(unittest.TestCase):
    def test_scripts_exist_and_run(self) -> None:
        for name in ("check", "wt"):
            path = ROOT / "bin" / name
            self.assertTrue(path.is_file() and os.access(path, os.X_OK), name)

    def run_check(self, body: str, args: list[str] | None = None, types_lint_rc: int | None = None) -> subprocess.CompletedProcess:
        # A throwaway git repo holding a copy of bin/check and one test file, so no state lands in relay's own .ci.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "bin").mkdir()
            script = repo / "bin" / "check"
            script.write_text((ROOT / "bin" / "check").read_text())
            script.chmod(0o755)
            (repo / "test_x.py").write_text(body)
            if types_lint_rc is not None:
                lint = repo / "bin" / "types-lint"
                lint.write_text(f"#!/bin/sh\nexit {types_lint_rc}\n")
                lint.chmod(0o755)
            argv = ["--tests", "test_x.py"] if args is None else args
            r = subprocess.run([str(script), *argv], cwd=repo, capture_output=True, text=True)
            r.logs = sorted(p.name for p in (repo / ".ci" / "check").glob("*.log")) if (repo / ".ci" / "check").exists() else []  # type: ignore[attr-defined]
            return r

    def test_green_test_passes(self) -> None:
        r = self.run_check("def test_a():\n    assert True\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("passed", r.stdout)

    def test_failing_test_exits_nonzero(self) -> None:
        r = self.run_check("def test_a():\n    assert False\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED at tests", r.stdout)

    def test_usage_errors_run_nothing(self) -> None:
        # Contract: exit 2 and nothing run for bare, --tests without a file, and the task form.
        for args in ([], ["--tests"], ["--tests", "--failed"], ["some-change", "1.1"]):
            r = self.run_check("def test_a():\n    assert False\n", args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("usage: bin/check --tests", r.stderr)
            self.assertEqual(r.logs, [], args)  # type: ignore[attr-defined]

    def test_types_lint_failure_fails_check(self) -> None:
        r = self.run_check("def test_a():\n    assert True\n", types_lint_rc=1)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED at types and lint", r.stdout)

    def test_types_lint_clean_then_tests(self) -> None:
        r = self.run_check("def test_a():\n    assert True\n", types_lint_rc=0)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
