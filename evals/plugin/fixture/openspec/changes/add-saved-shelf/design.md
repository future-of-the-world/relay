## Context

The shelf is saved as JSON text: an array of `{ name, qty }`.

## Decisions

### D1. One file

`saveShelf(path, items)` writes the whole array; `loadShelf(path)` reads it.

### D2. A corrupt file

A file that is not valid JSON is moved aside to `shelf.json.bad` and a fresh empty file is written, so the next save cannot overwrite what the person had.

## Interfaces

`saveShelf(path: string, items: readonly Item[]): void` and `loadShelf(path: string): Item[]` in `src/store.ts`.
