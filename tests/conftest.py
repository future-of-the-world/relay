"""Every test runs with HOME, CLAUDE_CONFIG_DIR and RELAY_HOME pointing at a fresh temporary folder,
so a test that forgets to set them cannot read or write the owner's ~/.claude, ~/.relay or ~/.claude.json.
The signal log (RELAY_SIGNAL_LOG) is one temporary file for the whole session, never ~/.relay/signals.log (tmp_default.pin_signal_log).
The path functions in lib/relay_config.py read the environment at call time, so setting it is enough.
ROOT stays the checkout (RELAY_ROOT is not touched). A test that sets these itself overrides this
for its own duration; no test needs the real folders, so there is no opt-out.
The autouse fixture also applies to unittest-style classes."""

import os
import shutil
import sys
import tempfile
from typing import Iterator

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import relay_tokens  # the machine-wide pool of test tokens (lib/relay_tokens.py)
import run_unittest  # own_pool_home: the same pool choice as bin/ci's unittest runner
import tmp_default  # the shared definition; bin/ci's unittest runner (tests/run_unittest.py) uses it too

tmp_default.RUN_TEMP = tempfile.gettempdir()      # before any test's own TMPDIR
tmp_default.pin_signal_log(os.environ)      # one signal log for the whole session, before the per-test RELAY_HOME switch


@pytest.fixture(autouse=True)
def _temporary_relay_and_claude(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
                                request: pytest.FixtureRequest) -> Iterator[None]:
    base = tmp_path_factory.mktemp(tmp_default.folder_prefix(request.node.name))      # pytest adds a number: relay-home-<test>-0
    monkeypatch.setattr(tempfile, "tempdir", None)      # tempfile re-reads TMPDIR (set below), then the cache is put back
    for key, value in tmp_default.temporary_environment(str(base)).items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    yield


_session_base: list[relay_tokens.RunBase] = []
_session_temp_homes: list[str] = []      # a pool folder made for a machine without relay; removed at the end


def pytest_sessionstart(session: pytest.Session) -> None:
    """A pytest session is one test run: it takes one shared token of the machine's pool (waiting, with a line saying so) unless a
    holder above it passed a base down. This runs before the per-test RELAY_HOME switch, so it reads the real pool; on a machine
    with no pool yet (and none passed down) it uses a temporary one, so HOME is left as it was."""
    environ = dict(os.environ)
    home = run_unittest.own_pool_home(environ)
    if home != relay_tokens.run_home(environ):
        _session_temp_homes.append(home)
        environ["RELAY_HOME"] = home
    base = relay_tokens.acquire_run_base(environ, lambda line: print("pytest: " + line, file=sys.stderr, flush=True))
    _session_base.append(base)
    if not base.passed:      # the session's children (tests that start runners on this pool) find the base it holds
        os.environ[relay_tokens.ENV_HOLD] = relay_tokens.hold_value(1, base.home)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    for base in _session_base:
        base.held.release()
    _session_base.clear()
    for home in _session_temp_homes:
        shutil.rmtree(home, ignore_errors=True)
    _session_temp_homes.clear()
