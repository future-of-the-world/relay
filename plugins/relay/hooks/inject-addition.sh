#!/usr/bin/env bash
# SubagentStart, PostToolUse(Skill) and UserPromptSubmit hook: a project's addition in front of the shared role. The work is in inject_addition.py.
exec python3 -I "$(dirname "$0")/inject_addition.py"
