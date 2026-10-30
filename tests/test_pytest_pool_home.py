"""A pytest session on a machine without relay leaves HOME empty; a gate's pool and an existing pool are kept (conftest.py)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_tokens


PYTEST = shutil.which("pytest")


# A plugin for the pytest child: after collection it writes what the session's conftest holds, to the file named by SEEN_FILE.
SPY = """
import json, os, sys

def pytest_collection_finish(session):
    mods = [m for n, m in sys.modules.items() if n.endswith("conftest") and hasattr(m, "_session_base")]
    base = mods[0]._session_base[0]
    with open(os.environ["SEEN_FILE"], "w") as f:
        json.dump({"passed": base.passed, "workers": base.workers, "temp_homes": list(mods[0]._session_temp_homes),
                   "hold": os.environ.get("RELAY_TEST_TOKENS")}, f)
"""


def pytest_run(home: str, extra: dict, spy_dir: str = "") -> subprocess.CompletedProcess:
    """pytest over one quick test file, with HOME=home and no RELAY_HOME / RELAY_TEST_TOKENS unless extra gives them.
    With spy_dir, the spy plugin is loaded and writes spy_dir/seen.json."""
    env = {k: v for k, v in os.environ.items() if k not in ("RELAY_HOME", relay_tokens.ENV_HOLD)}
    env["HOME"] = home
    env.update(extra)
    plugin = []
    if spy_dir:
        with open(os.path.join(spy_dir, "relay_spy.py"), "w") as f:
            f.write(SPY)
        env["PYTHONPATH"] = spy_dir + os.pathsep + env.get("PYTHONPATH", "")
        env["SEEN_FILE"] = os.path.join(spy_dir, "seen.json")
        plugin = ["-p", "relay_spy"]
    return subprocess.run([PYTEST or "pytest", "-q", "-p", "no:cacheprovider", *plugin, "tests/test_relay_tokens.py", "-k", "test_defaults"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=200)


@unittest.skipUnless(PYTEST, "pytest is not installed")
class PytestPoolHome(unittest.TestCase):
    def test_empty_home_stays_empty(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            result = pytest_run(home, {})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(os.listdir(home), [])      # no ~/.relay/test-tokens created

    def test_gate_pool_is_used_and_no_token_taken(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as pool_home, tempfile.TemporaryDirectory() as spy:
            hold = relay_tokens.hold_value(2, os.path.realpath(pool_home))
            result = pytest_run(home, {"RELAY_HOME": pool_home, relay_tokens.ENV_HOLD: hold}, spy)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(os.listdir(home), [])
            self.assertFalse(os.path.exists(relay_tokens.pool_dir(pool_home)))      # passed down: nothing created, nothing taken
            with open(os.path.join(spy, "seen.json")) as f:
                seen = json.load(f)
            # the session kept the gate's base (a temporary pool with a token of its own would give passed False)
            self.assertEqual(seen, {"passed": True, "workers": 2, "temp_homes": [], "hold": hold})

    def test_existing_pool_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as pool_home:
            os.makedirs(relay_tokens.pool_dir(pool_home))
            result = pytest_run(home, {"RELAY_HOME": pool_home})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # the session took a shared token of this pool, so a token-N lock file appeared in it (a temporary pool would leave it empty)
            self.assertTrue([n for n in os.listdir(relay_tokens.pool_dir(pool_home)) if n.startswith("token-")])


if __name__ == "__main__":
    unittest.main()
