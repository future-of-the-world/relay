---
kind: fix
state: open
ip: 91
size: 10
found: 2026-10-22, relay review-gate design 10.6 seed 9
taken-by:
closed-by:
test:
---
# offbyone rubric fail clause

What is wrong: offbyone rubric fail clause
Failing case: the off-by-one rubric's FAIL clause words ("stays within size", "as the doc says") made Haiku fail right answers yes-03 (5 of 5) and yes-05 (2 of 5); Sonnet unaffected, the trap stays for any weaker judge (handover cause-measure)
Why it matters: A weaker judge fails right answers, so a measurement of it is wrong.
