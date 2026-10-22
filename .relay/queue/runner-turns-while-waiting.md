---
kind: fix
state: open
ip: 93
time: 15
found: 2026-10-22, relay review-gate design 10.6 seed 3
taken-by:
closed-by:
test:
---
# The runner runs out of turns while it waits

What is wrong: runner turns while waiting
Failing case: the runner ran out of turns while waiting on a paid run three times on 22 Oct (measure, live6, full run); the front read the results itself; should finish and report within its turns (handover, three notes)
Why it matters: The work is lost and the front spends its own context reading results the runner should report.
