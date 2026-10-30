#!/usr/bin/env python3
"""The "types and lint" step of bin/ci: one mypy call and ruff's pyflakes rules (F), both pinned and run through uv,
configured in pyproject.toml of the directory (default: the repository root). A missing uv, or no network for the first
download, fails with one line; the step never skips silently.
  bin/types-lint [dir]"""
import glob
import os
import shutil
import subprocess
import sys

MYPY = "1.18.2"
RUFF = "0.13.3"
# bin/relay has no .py suffix; plugin lib files are links to lib/, so only lib/ is checked; kit_* are the plugin-only modules
PATTERNS = ["lib/**/*.py", "bin/relay", "plugins/*/hooks/*.py", "plugins/*/lib/kit_*.py"]


def mypy_files(root: str) -> list[str]:
    """The files the one mypy call is given, as paths relative to root, sorted. lib/ is walked recursively."""
    found: set[str] = set()
    for pattern in PATTERNS:
        for path in glob.glob(os.path.join(root, pattern), recursive=True):
            if os.path.isfile(path):
                found.add(os.path.relpath(path, root))
    return sorted(found)


def find_uv() -> str | None:
    uv = shutil.which("uv")
    if uv:
        return uv
    fallback = os.path.join(os.path.expanduser("~"), ".local", "bin", "uv")
    return fallback if os.access(fallback, os.X_OK) else None


def run_tool(uv: str, args: list[str]) -> tuple[int, str]:
    proc = subprocess.run([uv, "tool", "run", *args], capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def tail(text: str, n: int = 40) -> str:
    return "\n".join(text.rstrip("\n").splitlines()[-n:])


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    target = argv[1] if len(argv) > 1 else os.path.dirname(here)
    if not os.path.isdir(target):
        print(f"FAIL types and lint: {target} is not a directory")
        return 1
    os.chdir(target)
    uv = find_uv()
    if uv is None:
        print("FAIL types and lint needs uv on PATH: install uv (https://docs.astral.sh/uv/)")
        return 1
    rc = 0
    code, out = run_tool(uv, [f"mypy=={MYPY}", *mypy_files(".")])
    if code != 0:
        print(f"FAIL mypy {MYPY}:")
        print(tail(out))
        rc = 1
    code, out = run_tool(uv, [f"ruff@{RUFF}", "check", "."])
    if code != 0:
        print(f"FAIL ruff {RUFF} (pyflakes rules):")
        print(tail(out))
        rc = 1
    if rc == 0:
        print(f"types and lint: mypy {MYPY} and ruff {RUFF} clean")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
