#!/usr/bin/env bash
# The fixture, plus a branch wt/paging whose one commit adds page() with an
# off-by-one: the slice end is start + size + 1, so a page holds size + 1 items.
# It also adds pageCount() with no doc comment: a violation of the project rule
# DOC-RULE that only the fixture's .claude/kit/critic.md states, so a
# reviewer that reports it proves the project's addition was injected.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
git checkout -q -b wt/paging
mkdir -p .claude/kit && cp "$(dirname "$0")/critic-rule.md" .claude/kit/critic.md
cat >> src/shelf.ts <<'TS'

/** One page of the shelf: pages count from 0, each holds at most `size` items. */
export function page(items: readonly Item[], pageNo: number, size: number): Item[] {
  const start = pageNo * size;
  return items.slice(start, start + size + 1);
}

export function pageCount(items: readonly Item[], size: number): number {
  return Math.ceil(items.length / size);
}
TS
cat >> src/shelf.test.ts <<'TS'

test('Page 0 of an empty shelf is empty', () => {
  expect(page([], 0, 2)).toEqual([]);
});
TS
sed -i.bak "s/import { addItem, total } from '.\/shelf';/import { addItem, page, total } from '.\/shelf';/" src/shelf.test.ts && rm src/shelf.test.ts.bak
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "Add page()"
git checkout -q master
