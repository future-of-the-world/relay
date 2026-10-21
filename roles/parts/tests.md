## Tests
- Expected values come from the scenario, the finding's case or the design,
  worked out by hand with the reasoning in a comment; never what the code
  printed.
- Wait on a condition (an event, a locator, a process exit, a file), never
  on a sleep, and never assert a wall-clock window: time is a value you pass
  in or a clock the test drives.
- A test owns its state: a temporary directory, never a fixed path, the
  user's home or the repo's files; every global it changes is restored.
- Output is deterministic: sort before you compare; no absolute paths,
  timestamps or hash-map order.
- Nothing to assert on or wait for means the code lacks a signal: add one (a
  state field, an event, a return value) and report it under **Diagnostics
  missing**, rather than testing through a side door.
