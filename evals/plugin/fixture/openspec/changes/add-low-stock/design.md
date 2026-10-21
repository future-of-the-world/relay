## Context

A pure function over the item list; no state.

## Decisions

### D1. Limit is inclusive

`lowStock(items, limit)` returns the items with `qty <= limit`, in shelf order, as a new array.

## Interfaces

`lowStock(items: readonly Item[], limit: number): Item[]` in `src/shelf.ts`.
