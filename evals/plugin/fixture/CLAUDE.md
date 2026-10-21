# Shelf

A tiny TypeScript library that keeps a list of stock items (name and quantity).
This is the fixture project of the principles library's eval cases.

## Principles

- A function returns a new list and never changes its input.
- A bad argument is rejected with a `RangeError`, never silently fixed.
- A number a caller may want to tune is a parameter, not a constant.

## Architecture

`src/shelf.ts` holds the functions; tests sit beside it as `*.test.ts`. No UI and no I/O
in the functions; a change that adds storage says where it lives and in what shape.

## Tests

One test per scenario, titled with the scenario's name. Run: `bun test`.

## Commands

- `bin/check <change> <task>`: the task's own check, quiet.
- `bin/ci`: the full gate.
- `bin/wt new <name> <base>`: a worktree on branch `wt/<name>`.
