---
type: regex
pattern: "BASE_FAILS=[1-9]"
---
It fails on an assertion (`bun test` prints `(fail) <test>`), not because the file cannot be loaded: a test that merely imports a missing name has BASE_FAILS=0.
