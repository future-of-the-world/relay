#!/usr/bin/env bash
# The fixture, plus a branch wt/flaky whose one commit adds causeOfFlaky(). causeOfFlaky finds and fixes the cause of the flaky test; the item also asked to name who sends the signal, which the branch does not do: a reversible scope cut that principle 5 settles (the rest is a queue item).
# The rules the critic is given are in its prompt (prompt.md), not in a file it could skip, so only the path this case names applies.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
git checkout -q -b wt/flaky
cat >> src/shelf.ts <<'TS'

/** The cause of the flaky test: the timer fired before the shelf was built; wait for the shelf first. */
export function causeOfFlaky(builtAt: number, firedAt: number): boolean {
  return firedAt >= builtAt;
}
TS
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "Fix the cause of the flaky test"
git checkout -q master
