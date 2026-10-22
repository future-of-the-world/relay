---
kind: fix
state: open
ip: 93
time: 20
found: 2026-10-22, relay review-gate design 10.6 seed 2
taken-by:
closed-by:
test:
---
# A run goes past its money limit when run in parallel

What is wrong: eval cost ceiling overshoots
Failing case: `--max-cost-usd 4` at `-j 4` ran to $6.32 (Sonnet measure, 22 Oct); the README's $10 ceiling can reach about $13; should stop within one batch of the ceiling (handover "ceiling overshoot", "eval cost ceiling not firm at -j 4", check-readme-cost "$10 ceiling worst case ~$13")
Why it matters: A cost ceiling that overshoots spends the owner's money past the number they set.
