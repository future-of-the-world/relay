---
kind: fix
state: open
ip: 95
time: 30
found: 2026-10-22, relay review-gate design 10.6 seed 1
taken-by:
closed-by:
test:
---
# core tests not in gate

Where: bin/ci:25
What is wrong: core tests not in gate
Failing case: `bin/ci:25` skips `inject-addition`, `packet`, `check-contract`, `shim`, `spec-check`, `hooks-live` unless `RELAY_CORE_TESTS=1`; part 1's per-role tests I1-I9 live in `inject-addition.test.sh`, so a regression in role injection passes `bin/ci --quick` (v3 #1; handover "core plugin tests not in bin/ci --quick")
Why it matters: A regression in role injection passes the gate, so the gate does not guard what part 1 built.
