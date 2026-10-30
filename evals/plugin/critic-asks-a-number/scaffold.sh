#!/usr/bin/env bash
# The fixture, plus a branch wt/retry whose one commit adds retrySend(). retrySend waits 30 seconds between tries: a number with no rule behind it, so it is the owner's (a question finding, not a decided one).
# The rules the critic is given are in its prompt (prompt.md), not in a file it could skip, so only the path this case names applies.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
git checkout -q -b wt/retry
cat >> src/shelf.ts <<'TS'

/** Retries a failed send up to 3 times, waiting 30 seconds between tries. */
export async function retrySend(send: () => Promise<boolean>): Promise<boolean> {
  for (let i = 0; i < 3; i++) {
    if (await send()) return true;
    await new Promise((resolve) => setTimeout(resolve, 30000));
  }
  return false;
}
TS
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "Add retrySend()"
git checkout -q master
