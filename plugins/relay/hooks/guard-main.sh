#!/usr/bin/env bash
# PreToolUse hook: keep the main checkout clean. The work is in guard_main.py (its header says what it blocks).
command -v python3 >/dev/null 2>&1 || { echo "guard-main: python3 is not installed, so the guard cannot read Bash commands. Install Python 3." >&2; exit 2; }
exec python3 -I "$(dirname "$0")/guard_main.py"
