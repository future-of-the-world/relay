"""Every test runs with HOME, CLAUDE_CONFIG_DIR and RELAY_HOME pointing at a fresh temporary folder,
so a test that forgets to set them cannot read or write the owner's ~/.claude, ~/.relay or ~/.claude.json.
The path functions in lib/relay_config.py read the environment at call time, so setting it is enough.
ROOT stays the checkout (RELAY_ROOT is not touched). A test that sets these itself overrides this
for its own duration; no test needs the real folders, so there is no opt-out.
The autouse fixture also applies to unittest-style classes."""

import os
import sys
from typing import Iterator

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tmp_default  # the shared definition; bin/ci's unittest runner (tests/run_unittest.py) uses it too


@pytest.fixture(autouse=True)
def _temporary_relay_and_claude(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    base = tmp_path_factory.mktemp("home")
    for key, value in tmp_default.temporary_environment(str(base)).items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    yield
