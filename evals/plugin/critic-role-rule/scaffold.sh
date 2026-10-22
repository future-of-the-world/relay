#!/usr/bin/env bash
# The fixture, plus a branch wt/take whose one commit adds takeItem(): correct,
# documented and tested, but its quantity parameter is called `amount`.
# The project rule ROLE-RULE (a quantity parameter is named `qty`) is stated
# only in .claude/kit/judge.md, the project's file for the whole judge role,
# written here and by no other case. The fixture has no .claude/kit/critic.md,
# so a critic that reports the breach proves the role file reached it.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
git checkout -q -b wt/take
cat >> src/shelf.ts <<'TS'

/** Takes `amount` off the named item; an item that reaches 0 leaves the shelf. Rejects amount <= 0 and more than is on the shelf. */
export function takeItem(items: readonly Item[], name: string, amount: number): Item[] {
  if (amount <= 0) throw new RangeError('amount must be positive');
  const have = items.find((i) => i.name === name)?.qty ?? 0;
  if (amount > have) throw new RangeError('not enough on the shelf');
  return items.map((i) => (i.name === name ? { name, qty: i.qty - amount } : i)).filter((i) => i.qty > 0);
}
TS
cat >> src/shelf.test.ts <<'TS'

test('Take part of an item: quantity decreases', () => {
  expect(takeItem([{ name: 'bolt', qty: 5 }], 'bolt', 2)).toEqual([{ name: 'bolt', qty: 3 }]);
});

test('Take all of an item: it leaves the shelf', () => {
  expect(takeItem([{ name: 'bolt', qty: 5 }], 'bolt', 5)).toEqual([]);
});
TS
sed -i.bak "s/import { addItem, total } from '.\/shelf';/import { addItem, takeItem, total } from '.\/shelf';/" src/shelf.test.ts && rm src/shelf.test.ts.bak
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "Add takeItem()"
git checkout -q master
mkdir -p .claude/kit
cat > .claude/kit/judge.md <<'MD'
Project rule ROLE-RULE: a parameter that carries a quantity is named `qty`. Any other
name for it (`amount`, `count`, `n`, `num`) is a CONFIRMED high finding: label it
`ROLE-RULE`, name the function and the parameter.
MD
