"""Code coverage of the gate's library tests (coverage.py, pinned in deps.toml, run through `uv run --with`, never imported by relay).
Coverage never fails a gate: the exit code is the tests' own, and a tool that cannot run leaves the plain run and a line saying so."""

from __future__ import annotations

import json
import os
import sys
from typing import Callable, Optional, TextIO

import relay_kit
import relay_toml

SOURCE = ("lib", "bin", "plugins")
MODES = ("every", "landing", "off")       # [metrics] coverage; the default is the owner's answer of 29 Oct (every gate); landing: only the gate `relay land` runs (RELAY_LAND)


def effective_mode(kit: relay_kit.Kit, env: dict[str, str]) -> str:
    """`every` or `off` for this gate: `landing` means every only in the gate `relay land` started; metrics off or an unknown value of the
    setting leaves the default (every) or off as written."""
    if kit.get("metrics", "enabled") is False:
        return "off"
    mode = kit.get("metrics", "coverage")      # a wrong value is already the default (every), with a problem
    if mode == "landing":
        return "every" if env.get("RELAY_LAND") else "off"
    return mode if mode in MODES else "every"


def pin(root: str) -> Optional[str]:
    """`coverage==<version>` from deps.toml, or None when the repository pins none."""
    try:
        with open(os.path.join(root, "deps.toml"), "rb") as handle:
            deps = relay_toml.load(handle).get("dep", [])
    except (OSError, ValueError):
        return None
    return next((d.get("uv_tool") for d in deps if d.get("name") == "coverage"), None)


def config(root: str, folder: str) -> str:
    """The rc file text. Data files are absolute paths under the ignored `.ci/coverage/`, so the worktree stays clean and a child
    started inside a test's temporary repo writes its data there. `plugins/*/lib/` counts for `lib/`."""
    return "\n".join([
        "[tool.coverage.run]", f'data_file = "{folder}/data"', "parallel = true", 'patch = ["subprocess"]',
        "source = [" + ", ".join(f'"{os.path.join(root, s)}"' for s in SOURCE) + "]",
        "[tool.coverage.paths]", f'lib = ["{root}/lib/", "{root}/plugins/*/lib/"]', ""])


def run_tests(root: str, env: dict[str, str], run: Callable[..., "object"], log: TextIO, which: Callable[[str], Optional[str]],
              cfg_mode: str) -> tuple[Optional[int], Optional[str]]:
    """(tests' exit code, the coverage line) or (None, note) when coverage did not run and the caller runs the tests plain."""
    spec = pin(root)
    if cfg_mode == "off" or spec is None or which("uv") is None:
        return None, None
    folder = os.path.join(root, ".ci", "coverage")
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        os.remove(os.path.join(folder, name))
    rc_file = os.path.join(folder, "rc.toml")
    with open(rc_file, "w", encoding="utf-8") as handle:
        handle.write(config(root, folder))
    base = ["uv", "run", "--no-project", "--python", sys.executable, "--with", spec, "python", "-W", "ignore::ResourceWarning", "-m", "coverage"]
    tests = run([*base, "run", "--rcfile", rc_file, "tests/run_unittest.py"], log, env=env).returncode   # type: ignore[attr-defined]
    out = os.path.join(folder, "total.json")
    for sub in (["combine", "--rcfile", rc_file, "--quiet"], ["json", "--rcfile", rc_file, "-o", out, "--quiet"]):
        if run([*base, *sub], log, env=env).returncode != 0:    # type: ignore[attr-defined]
            return tests, "ci: coverage not measured (coverage.py failed; see the log of library tests)"
    try:
        with open(out, encoding="utf-8") as handle:
            totals = json.load(handle)["totals"]
        return tests, (f"ci: coverage {totals['percent_covered']:.1f}% of lib, bin, plugins "
                       f"({totals['covered_lines']} of {totals['num_statements']} lines)")
    except (OSError, ValueError, KeyError):
        return tests, "ci: coverage not measured (no total in the coverage report)"


def library_tests(root: str, base: dict[str, str], quick: bool, run: Callable[..., "object"], log: TextIO,
                  which: Callable[[str], Optional[str]]) -> tuple[int, str]:
    """(exit code, coverage line or "") of the library tests: under coverage when the settings and the pin allow, else plain."""
    import relay_kit
    env = dict(base)
    # the guard suite (tests/test_hook_guard_main.py) runs its shared cases once in quick mode
    if quick:
        env["RELAY_QUICK"] = "1"
    rc, line = run_tests(root, env, run, log, which, effective_mode(relay_kit.load(root), env))
    if rc is None:
        rc = run(["python3", "-W", "ignore::ResourceWarning", "tests/run_unittest.py"], log, env=env).returncode   # type: ignore[attr-defined]
    return rc, line or ""
