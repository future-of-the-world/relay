"""A pytest session on a machine without relay leaves HOME empty; a gate's pool and an existing pool are kept (conftest.py)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_tokens


PYTEST = shutil.which("pytest")


def pytest_run(home: str, extra: dict) -> subprocess.CompletedProcess:
    """pytest over one quick test file, with HOME=home and no RELAY_HOME / RELAY_TEST_TOKENS unless extra gives them."""
    env = {k: v for k, v in os.environ.items() if k not in ("RELAY_HOME", relay_tokens.ENV_HOLD)}
    env["HOME"] = home
    env.update(extra)
    return subprocess.run([PYTEST or "pytest", "-q", "-p", "no:cacheprovider", "tests/test_relay_tokens.py", "-k", "test_defaults"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=200)


@unittest.skipUnless(PYTEST, "pytest is not installed")
class PytestPoolHome(unittest.TestCase):
    def test_empty_home_stays_empty(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            result = pytest_run(home, {})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(os.listdir(home), [])      # no ~/.relay/test-tokens created

    def test_gate_pool_is_used_and_no_token_taken(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as pool_home:
            hold = relay_tokens.hold_value(2, os.path.realpath(pool_home))
            result = pytest_run(home, {"RELAY_HOME": pool_home, relay_tokens.ENV_HOLD: hold})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(os.listdir(home), [])
            self.assertFalse(os.path.exists(relay_tokens.pool_dir(pool_home)))      # passed down: nothing created, nothing taken

    def test_existing_pool_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as pool_home:
            os.makedirs(relay_tokens.pool_dir(pool_home))
            result = pytest_run(home, {"RELAY_HOME": pool_home})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # the session took a shared token of this pool, so a token-N lock file appeared in it (a temporary pool would leave it empty)
            self.assertTrue([n for n in os.listdir(relay_tokens.pool_dir(pool_home)) if n.startswith("token-")])


if __name__ == "__main__":
    unittest.main()
