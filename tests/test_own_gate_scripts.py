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

    def run_check(self, body: str) -> subprocess.CompletedProcess:
        # A throwaway git repo holding a copy of bin/check and one test file, so no state lands in relay's own .ci.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "bin").mkdir()
            script = repo / "bin" / "check"
            script.write_text((ROOT / "bin" / "check").read_text())
            script.chmod(0o755)
            (repo / "test_x.py").write_text(body)
            return subprocess.run([str(script), "--tests", "test_x.py"], cwd=repo, capture_output=True, text=True)

    def test_green_test_passes(self) -> None:
        r = self.run_check("def test_a():\n    assert True\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("passed", r.stdout)

    def test_failing_test_exits_nonzero(self) -> None:
        r = self.run_check("def test_a():\n    assert False\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED at tests", r.stdout)


if __name__ == "__main__":
    unittest.main()
