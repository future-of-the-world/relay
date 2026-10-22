---
kind: fix
state: open
ip: 91
size: 5
found: 2026-10-22, relay review-gate design 10.6 seed 10
taken-by:
closed-by:
test:
---
# stale eval texts

Where: evals/plugin/setup-fixture.sh:4
What is wrong: stale eval texts
Failing case: evals/plugin/setup-fixture.sh:4-5 says bin/ci puts core's bin/ and a git shim (.ci/evalbin) first on PATH. bin/ci:50 puts only plugins/core/bin first, which holds only kit, and no .ci/evalbin or shim exists anywhere in the repository (git grep evalbin finds nothing outside the plans). The handover's other pointer, case.yaml:3, is the description line of every case and none of them was found wrong; if one is, name it here. Should describe what bin/ci really does
Why it matters: The comment tells the next reader how the eval run is built, and it is not so.
