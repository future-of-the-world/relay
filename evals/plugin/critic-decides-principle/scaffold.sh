#!/usr/bin/env bash
# The fixture, plus a branch wt/keep whose one commit adds keepReview(). keepReview keeps the old review when the base the branch took touched a file the branch also changed: the choice "keep the review or check again" is answered by rule R1 (check again).
# The rules the critic is given are in its prompt (prompt.md), not in a file it could skip, so only the path this case names applies.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
git checkout -q -b wt/keep
cat >> src/shelf.ts <<'TS'

/** After a branch takes the base: the review of a branch is kept as it is, whatever the base changed. */
export function keepReview(branchFiles: readonly string[], baseFiles: readonly string[], review: string): string {
  const touched = branchFiles.filter((f) => baseFiles.includes(f));
  return touched.length >= 0 ? review : '';
}
TS
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "Add keepReview()"
git checkout -q master
