"""The one place that says what "every test runs with temporary folders" means, for every runner the repo uses.
pytest: tests/conftest.py's autouse fixture calls temporary_environment. unittest (bin/ci, library tests):
tests/run_unittest.py calls patch_unittest, which wraps TestCase.run the same way."""
import os
import shutil
import tempfile
import unittest
from typing import Dict, Optional


def temporary_environment(base: str) -> Dict[str, Optional[str]]:
    """The environment values a test gets under `base`; None means the variable is removed."""
    return {
        "HOME": base,
        "CLAUDE_CONFIG_DIR": os.path.join(base, ".claude"),
        "RELAY_HOME": os.path.join(base, ".relay"),
        "RELAY_CLAUDE_JSON": None,
    }


def patch_unittest() -> None:
    original = unittest.TestCase.run

    def run(self, result=None):  # type: ignore[no-untyped-def]
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
