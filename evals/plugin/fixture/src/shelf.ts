export interface Item {
  readonly name: string;
  readonly qty: number;
}

/** Adds an item; an existing name gets its quantity increased. Rejects qty <= 0. */
export function addItem(items: readonly Item[], name: string, qty: number): Item[] {
  if (qty <= 0) throw new RangeError('qty must be positive');
  const found = items.some((i) => i.name === name);
  if (!found) return [...items, { name, qty }];
  return items.map((i) => (i.name === name ? { name, qty: i.qty + qty } : i));
}

/** The total quantity of all items. */
export function total(items: readonly Item[]): number {
  return items.reduce((sum, i) => sum + i.qty, 0);
}

/** Wave-0 stub: the items with `qty <= limit`, in shelf order. Not implemented yet. */
export function lowStock(_items: readonly Item[], _limit: number): Item[] {
  return [];
}
