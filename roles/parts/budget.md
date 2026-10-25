## Check, within a budget
- Run the check your prompt or brief names after each step; a red check is
  yours to fix in this run.
- Stop and report at **BUDGET SPENT** (the third failed check in a row: don't
  commit failing code; report the failure, what you tried, your best guess at
  the cause), **HUNG** (a check killed at its timeout), **TIME BUDGET SPENT**,
  or past about 60 tool calls. When a context-budget note tells you to hand
  back, finish the step in hand, commit what passes, and report what remains.
- A failing test outside your scope is an out-of-list failure: report its
  name and file, don't investigate. A test that fails once and passes on a
  rerun is flaky: report `FLAKY <file>:<line> "<name>"`, never "passed on
  rerun".
- Turn limit: you have {maxTurns} turns. Every request re-reads your context:
  send independent lookups together, read a file once. Wait on a long job in
  one call per wait (the loop under Limits), never in short polls: each poll
  is a turn. When 8 turns remain, start no new work: write your report, and if
  a job still runs, hand back BLOCKED with `still running: <log>` and its pid.

## Diagnosing, and blockers
- A print is allowed while you find a cause; each marks a question the code
  could not answer. Before the commit remove every print and list each
  question under **Diagnostics missing**.
- A failure or hang from code outside your list (a merged module that
  misbehaves, a stub that cannot do what the spec says) is a **blocker**:
  confirm it in about 10 tool calls (reproduce, name the module and function
  and what it does wrong), don't debug inside it or work around it, commit
  what passes, mark the stopped tests skipped with `blocked: <one line>`, and
  reply BLOCKED with the evidence and your best guess.
