## Building from a packet

- Write one test per scenario above first, then the code that makes it pass.
- Keep a clause ledger: for every clause of the scenarios and the task, the test that proves it.
- Loop on the quiet check (`gate.check`) inside your run; the full gate is not yours.
- Tick your own tasks in `tasks.md` in your commit, naming the task ids.
- A wrong stub or an ambiguous spec is a `Gap`: stop and report it, do not guess.
- Reply with the usual hand-back plus the lines `Proof:` (scenario -> test), `clauses n of m`
  and `Owed:` (what is left, or `none`).
