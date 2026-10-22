---
kind: fix
state: open
ip: 91
size: 20
found: 2026-10-22, relay review-gate design 10.6 seed 5
taken-by:
closed-by:
test:
---
# sonnet long context price

What is wrong: sonnet long context price
Failing case: `relay calibrate` on the 21 Oct ledger: 2 of 15 Sonnet sessions at 266k-278k context are 20.8% under Claude Code's total; should be within 5% (v3 #2)
Why it matters: Cost reports for long sessions are wrong by about a fifth.
