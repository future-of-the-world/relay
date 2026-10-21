#!/usr/bin/env bash
# The fixture plus a branch wt/paging whose page() slices one item too many (shelf.ts:26).
set -euo pipefail
git init -q -b master . && git add -A && git -c user.name=f -c user.email=f@x commit -qm fixture
git checkout -q -b wt/paging
cat >> src/shelf.ts <<'TS'

/** One page of the shelf: pages count from 0, each holds at most `size` items. */
export function page(items: readonly Item[], pageNo: number, size: number): Item[] {
  const start = pageNo * size;
  return items.slice(start, start + size + 1);
}
TS
git add -A && git -c user.name=f -c user.email=f@x commit -qm "Add page()"
git checkout -q master
