# The improvement loop

```
relay report --since 7d            what happened, in money and counts
relay improve suggest              numbered findings, each with a saving and a lever
      │
      ▼  write profiles/candidates/<name>.toml (or edit a rule / a skill)
relay bench active <name> --tag cheap [--runs 3]
      │  verdict: no scenario worse in quality, then cheaper, then faster
      ▼
relay improve adopt <name> --because "<the verdict in one line>"
      │  active.toml replaced, previous kept, improve/log.md appended, sync
      ▼
relay report --compare <before> <after>     a week later, in real use
```

## In the owner's words

The owner does not run this loop; the session does, through the `front:tune`
skill (named by a hook when a prompt is about models, effort, cost, or how
agents work). "Try Haiku for workers" becomes `relay bench active --set
models.build=haiku`; "make workers plan more and take smaller tasks" becomes
`relay candidate plan-first --copy delegate`, a worker editing the copy's
`agents/worker.md` from a brief, then a bench; "adopt it" becomes `relay
improve adopt`, which also swaps the edited plugin copy in (the previous
one kept under `profiles/history/`).

## What can be a candidate

- a model per tier (`[models]`), an effort per tier (`[effort]`);
- the front's model;
- the rules loaded in full (`[rules] load`): fewer is cheaper on every
  request; the bench shows whether anything is lost;
- a plugin on or off;
- guard thresholds (`[delegate]`).

A change to a skill's or an agent's text: `relay candidate <name> --copy
<plugin>` makes a copy under `profiles/candidates/<name>/plugins/`, the
profile points at it (`[plugins] enabled` takes paths), the bench loads the
copy with `--plugin-dir` and builds the `--agents` definitions from it.

## What to bench against

The `cheap` tag (a feature with tests, a script, a lookup) runs in minutes
for a few dollars and separates most profile changes. Add `review-offbyone`
when the candidate touches the judge tier. Add a scenario from your own
work when a change is about it: copy a scenario folder, change the
fixture and the graders; a scenario whose graders are commands (`bun test`,
`grep -q`) costs nothing to grade.

## Reading the measurements honestly

- Per-turn figures compare periods; totals compare nothing (a busier week
  costs more).
- One bench run shows a direction; three runs show a difference.
- A candidate that is cheaper and equal on the bench and worse in real use
  a week later is reverted: `relay improve adopt <previous from
  profiles/history/>`. The log says what it was.
- The ledger's dollar figures are estimates; the bench's are Claude's.
  When they disagree by more than 10%, re-measure `prices.toml`.
