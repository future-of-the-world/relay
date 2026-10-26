#!/usr/bin/env python3
"""Eval fixture of the design-track case: ends the run at the graded step.

A headless eval run waits for a background agent to finish, so the thinker the case asks for would run a whole design
(Opus, minutes, dollars) after the step the graders check. The Agent call is already in the trace when this hook
runs, which is what the `thinker-started` grader reads; the hook refuses it so no thinker starts. Exit 2 refuses the
call and gives stderr to the session.
"""
import sys

sys.stdin.read()
sys.stderr.write(
    "design-track fixture: the agent call is recorded and refused on purpose; no agent runs here. "
    "Do not try again and do not start another agent: reply with one line saying the brief is written.\n"
)
sys.exit(2)
