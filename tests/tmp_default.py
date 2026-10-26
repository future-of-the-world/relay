"""The one place that says what "every test runs with temporary folders" means, for every runner the repo uses.
pytest: tests/conftest.py's autouse fixture calls temporary_environment. unittest (bin/ci, library tests):
tests/run_unittest.py calls patch_unittest, which wraps TestCase.run the same way."""
import os
import shutil
import tempfile
import unittest
from typing import Dict, Optional

REAL_HOME = os.path.expanduser("~")  # captured at import, before any runner swaps HOME


def temporary_environment(base: str) -> Dict[str, Optional[str]]:
    """The environment values a test gets under `base`; None means the variable is removed."""
    # uv keeps its cache (and the tools mypy/ruff it runs for bin/types-lint) under HOME; a cold cache per test
    # re-downloads them (5 s became 409 s), so uv's folders stay on the real ones. They are not ~/.claude or ~/.relay.
    return {
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or os.path.join(REAL_HOME, ".cache", "uv"),
        "HOME": base,
        "CLAUDE_CONFIG_DIR": os.path.join(base, ".claude"),
        "RELAY_HOME": os.path.join(base, ".relay"),
        "RELAY_CLAUDE_JSON": None,
    }


def patch_unittest() -> None:
    original = unittest.TestCase.run

    def run(self: unittest.TestCase, result: Optional[unittest.result.TestResult] = None) -> Optional[unittest.result.TestResult]:
        base = tempfile.mkdtemp(prefix="relay-home-")
        saved = {k: os.environ.get(k) for k in temporary_environment(base)}
        for key, value in temporary_environment(base).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            return original(self, result)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(base, ignore_errors=True)

    unittest.TestCase.run = run  # type: ignore[method-assign]
