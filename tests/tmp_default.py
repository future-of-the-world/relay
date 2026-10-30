"""The one place that says what "every test runs with temporary folders" means, for every runner the repo uses.
pytest: tests/conftest.py's autouse fixture calls temporary_environment. unittest (bin/ci, library tests):
tests/run_unittest.py calls patch_unittest, which wraps TestCase.run the same way; so does tests/__init__.py, so
`python3 -m unittest tests.test_x` gets it too.

Each test's folder is named for the test (`relay-home-<method>-XXXX`) and is the test's TMPDIR, so every temporary file or
folder a test makes lands under it: a process a test leaves behind shows the test's name in its path, and the gate's sweep
(lib/relay_gate.py) finds it by the prefix."""
import os
import re
import shutil
import tempfile
import unittest
from typing import Dict, Optional

REAL_HOME = os.path.expanduser("~")  # captured at import, before any runner swaps HOME


RUN_TEMP: Optional[str] = None  # the temporary folder of the whole run, before any test's own: files shared by all tests (fake_tools' cache) live there


def run_temp() -> str:
    """The run's own temporary folder (not the running test's)."""
    return RUN_TEMP or tempfile.gettempdir()


NAME_LIMIT = 40  # characters of the test's method name kept in its folder name


def folder_prefix(method: str) -> str:
    """`relay-home-<method cut to NAME_LIMIT>-`: the start of the folder name of the test called `method`."""
    return "relay-home-%s-" % re.sub(r"[^A-Za-z0-9_]", "_", method)[:NAME_LIMIT]


def temporary_environment(base: str) -> Dict[str, Optional[str]]:
    """The environment values a test gets under `base`; None means the variable is removed."""
    # uv keeps its cache (and the tools mypy/ruff it runs for bin/types-lint) under HOME; a cold cache per test
    # re-downloads them (5 s became 409 s), so uv's folders stay on the real ones. They are not ~/.claude or ~/.relay.
    return {
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or os.path.join(REAL_HOME, ".cache", "uv"),
        "HOME": base,
        "CLAUDE_CONFIG_DIR": os.path.join(base, ".claude"),
        "RELAY_HOME": os.path.join(base, ".relay"),
        # relay's own checkout holds a tracked projects.toml; without this a test that reads the registry would move it
        # out of the checkout (lib/relay_config.py projects_file) and the gate would see the tree change.
        "RELAY_PROJECTS": os.path.join(base, ".relay", "projects.toml"),
        "RELAY_CLAUDE_JSON": None,
        "TMPDIR": base,
    }


def patch_unittest() -> None:
    """Make every TestCase.run use its own folders. Called twice it patches once: a second wrapper would nest a second folder in each test."""
    if getattr(unittest.TestCase, "_relay_tmp_patched", False):
        return
    global RUN_TEMP
    RUN_TEMP = tempfile.gettempdir()
    original = unittest.TestCase.run

    def run(self: unittest.TestCase, result: Optional[unittest.result.TestResult] = None) -> Optional[unittest.result.TestResult]:
        base = tempfile.mkdtemp(prefix=folder_prefix(getattr(self, "_testMethodName", "test")))
        saved = {k: os.environ.get(k) for k in temporary_environment(base)}
        saved_tempdir = tempfile.tempdir
        for key, value in temporary_environment(base).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tempfile.tempdir = None  # tempfile re-reads TMPDIR
        try:
            return original(self, result)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            tempfile.tempdir = saved_tempdir
            shutil.rmtree(base, ignore_errors=True)

    unittest.TestCase.run = run  # type: ignore[method-assign]
    unittest.TestCase._relay_tmp_patched = True  # type: ignore[attr-defined]
