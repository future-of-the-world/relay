---
kind: fix
state: open
ip: 91
time: 3
found: 2026-10-22, relay review-gate design 10.6 seed 7
taken-by:
closed-by:
test:
---
# The tally crashes on unreadable input

What is wrong: tally unreadable json
Failing case: `python3 tally.py /dev/null --expect-model haiku` prints a traceback and exits 1, which means "a bar is exceeded"; should exit 2, "not judged" (L1)
Why it matters: A tally that crashes reads as 'a bar is exceeded', a wrong answer about the judge.
