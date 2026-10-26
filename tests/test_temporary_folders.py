"""The default every test gets: relay's home and Claude's folder are temporary, never the owner's."""

import os
import subprocess
import sys
import unittest
from typing import List, Optional

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS), "lib"))
sys.path.insert(0, TESTS)

import relay_config
import tmp_default

REAL_HOME = os.path.expanduser("~")  # captured at import, before any fixture runs


def _listing(path: str) -> Optional[List[str]]:
    return sorted(os.listdir(path)) if os.path.isdir(path) else None


class TemporaryFoldersTest(unittest.TestCase):
    def test_writes_land_in_temporary_folders_not_the_real_ones(self):
        real_claude = os.path.join(REAL_HOME, ".claude")
        real_relay = os.path.join(REAL_HOME, ".relay")
        # Compared by listing and mtime of the real folders; nothing is ever written there.
        # Refuse before any write when the default is not active (F4): HOME must not be the real one and
        # both folders must lie under HOME, whatever CLAUDE_CONFIG_DIR / RELAY_HOME say.
        self.assertNotEqual(os.path.realpath(os.environ["HOME"]), os.path.realpath(REAL_HOME))
        for folder in (relay_config.claude_dir(), relay_config.home_dir()):
            home = os.path.realpath(os.environ["HOME"])
            self.assertEqual(os.path.commonpath([home, os.path.realpath(folder)]), home)
        before = [(p, _listing(p), os.path.getmtime(p) if os.path.exists(p) else None) for p in (real_claude, real_relay)]
        for folder in (relay_config.claude_dir(), relay_config.home_dir()):
            self.assertNotEqual(os.path.realpath(folder), os.path.realpath(real_claude))
            self.assertNotEqual(os.path.realpath(folder), os.path.realpath(real_relay))
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "sentinel"), "w") as handle:
                handle.write("x")
        self.assertEqual(os.path.expanduser("~"), os.environ["HOME"])
        self.assertNotEqual(os.path.realpath(os.environ["HOME"]), os.path.realpath(REAL_HOME))
        after = [(p, _listing(p), os.path.getmtime(p) if os.path.exists(p) else None) for p in (real_claude, real_relay)]
        self.assertEqual(before, after)
        self.assertNotIn("sentinel", _listing(real_claude) or [])

    def test_uv_cache_stays_on_the_real_one(self) -> None:
        # F1: with HOME replaced, uv still finds its cache, so bin/types-lint does not re-download mypy and ruff.
        env = tmp_default.temporary_environment("/base")
        self.assertEqual(env["UV_CACHE_DIR"], os.environ.get("UV_CACHE_DIR") or os.path.join(REAL_HOME, ".cache", "uv"))
        self.assertFalse(str(env["UV_CACHE_DIR"]).startswith("/base"))
        self.assertEqual(env["HOME"], "/base")  # only uv's folder is carried over

    def test_runner_runs_the_names_it_is_given(self) -> None:
        # F2: bin/ci's rules_tests passes names to tests/run_unittest.py; it must run those, not discover everything.
        one = "tests.test_temporary_folders.TemporaryFoldersTest.test_uv_cache_stays_on_the_real_one"
        root = os.path.dirname(TESTS)
        done = subprocess.run([sys.executable, os.path.join(TESTS, "run_unittest.py"), one], cwd=root,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Ran 1 test", done.stderr)


if __name__ == "__main__":
    unittest.main()
