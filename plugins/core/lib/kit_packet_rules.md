## Building from a packet

- Write one test per scenario above first, then the code that makes it pass.
- Keep a clause ledger: for every clause of the scenarios and the task, the test that proves it.
- An `e2e` or `smoke` entry is a black-box test through the real outside (the built program or screen) that imports no internals; a same-process test does not count.
- Do not read `tasks.md`, `design.md`, `proposal.md` or the spec deltas whole; if the brief lacks something, stop and report an incomplete `Reads:` line.
- Loop on the quiet check (`gate.check`; when it takes a change and a task, run it for yours, and `--failed` to rerun what failed) inside your run; the full gate is not yours.
- Tick your own tasks in `tasks.md` in your commit, naming the task ids.
- A wrong stub or an ambiguous spec is a `Gap`: stop and report it, do not guess.
- Reply with the usual hand-back plus the lines `Proof:` (scenario -> test), `clauses n of m`
  and `Owed:` (what is left, or `none`).
