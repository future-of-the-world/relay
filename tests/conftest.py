"""Every test runs with HOME, CLAUDE_CONFIG_DIR and RELAY_HOME pointing at a fresh temporary folder,
so a test that forgets to set them cannot read or write the owner's ~/.claude, ~/.relay or ~/.claude.json.
The path functions in lib/relay_config.py read the environment at call time, so setting it is enough.
ROOT stays the checkout (RELAY_ROOT is not touched). A test that sets these itself overrides this
for its own duration; no test needs the real folders, so there is no opt-out.
The autouse fixture also applies to unittest-style classes."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))


@pytest.fixture(autouse=True)
def _temporary_relay_and_claude(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(base))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(base / ".claude"))
    monkeypatch.setenv("RELAY_HOME", str(base / ".relay"))
    monkeypatch.delenv("RELAY_CLAUDE_JSON", raising=False)
    yield
