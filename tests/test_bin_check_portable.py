"""bin/check template on a machine without timeout/gtimeout (macOS): green passes, a hang is HUNG."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "bin-check"
TOOLS = ["bash", "git", "python3", "date", "cat", "head", "mkdir", "rm", "cut", "printf",
         "md5sum", "md5", "sleep", "true", "dirname", "env", "sh"]


class BinCheckPortable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.proj = base / "proj"
        (self.proj / "bin").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        # A PATH of symlinks to the needed tools only: no timeout, no gtimeout.
        self.toolbin = base / "tools"
        self.toolbin.mkdir()
        for t in TOOLS:
            found = shutil.which(t)
            if found:
                (self.toolbin / t).symlink_to(found)
        self.assertFalse((self.toolbin / "timeout").exists())

    def write(self, step, drop=()):
        text = TEMPLATE.read_text().replace("run_step placeholder true", step)
        script = self.proj / "bin" / "check"
        script.write_text(text)
        script.chmod(0o755)
        for t in drop:
            (self.toolbin / t).unlink(missing_ok=True)

    def run_check(self, *args, timeout_s="30"):
        env = {"PATH": str(self.toolbin), "CHECK_TIMEOUT": timeout_s, "HOME": self.tmp.name}
        return subprocess.run([str(self.toolbin / "bash"), str(self.proj / "bin" / "check"), *args],
                              cwd=self.proj, env=env, capture_output=True, text=True, timeout=60)

    def test_green_step_passes_without_timeout(self):
        self.write("run_step ok true")
        r = self.run_check("change", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("passed", r.stdout)

    def test_hanging_step_is_hung_within_bound(self):
        # CHECK_TIMEOUT=1 and a 30 s sleep: the wrapper must kill it and report HUNG, exit 1.
        self.write("run_step sleeper sleep 30")
        r = self.run_check("change", "1", timeout_s="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("HUNG: sleeper exceeded 1s", r.stdout)

    def test_tests_key_hash_works_without_md5sum(self):
        # --tests names its state file by a hash; with no md5sum the fallback must still give one.
        self.write("run_step ok true", drop=("md5sum",))
        r = self.run_check("--tests", "a.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = [p.name for p in (self.proj / ".ci" / "check").iterdir()]
        self.assertTrue(any(n.startswith("tests-") and len(n.split(".")[0]) == len("tests-") + 8
                            for n in names), names)


if __name__ == "__main__":
    unittest.main()
