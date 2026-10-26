Plan: revision 2 of the design of the workflow script as relay's one unit of run. Written 2026-10-26. Designs queue item `change-cycle-workflow-scripts-move-into-relay`.
Not built yet: nothing in this file is in the code; it is the design a worker builds from.

# Design: the workflow script as relay's one unit of run, and how it reaches users

Revision 2, 26 Oct 2026, after the design review the session scratchpad (not kept) (9 findings: 1 HIGH,
7 MEDIUM, 1 LOW; all 9 hold and are fixed here; the table at the end says where). Revision 1 is not kept.

Queue item `change-cycle-workflow-scripts-move-into-relay` (IP 96, owner's word). Owner, 27 Oct small hours, verbatim:
"a, как мы можем это унифицировать, я заметил что ты запускаешь этот скрипт не тольк для feature или fix из очереди, это
базовая единица запуска, в том числе для экспериментов и анализа, как это будет доставляться до пользователей"

Nothing in the repository was changed. Measurement scripts (wfmeasure.py, wfagg.py, wfagg2.py, front.py) were in the session scratchpad (not kept) (over this session's 128 run records `workflows/wf_*.json`, their journals, the agents' meta files and the
front's transcript). Claude Code facts were read from the installed binary, version 2.1.310 (its strings,
the session scratchpad (not kept)); each is marked **verified in code** (read, not run), **measured** (seen in this
session's files) or **not verified**.

Terms used below:
- **Workflow tool**: Claude Code's tool that runs a JavaScript **workflow script**; the script starts agents with
  `agent()`, runs lists with `pipeline()` / `parallel()`, and returns one JSON result to the front.
- **Run**: one call of the Workflow tool. **Unit**: one piece of work inside a run (a change, a design, an analysis).
  **Stage**: one agent inside a unit, named by its label `<stage>[ N]: <name>`, for example `gate 2: where-list`.
- **Saved workflow**: a script Claude Code finds by name, so the front calls `{name: "..."}` instead of a path.
- **Resume**: calling the tool again with `resumeFromRunId`; agents whose prompt and options did not change return their
  old result at once, only changed or new ones run again.
- **Landing**: putting a ready change on the default branch: take the default branch into the task branch, gate again if
  code came in, then one fast-forward. A **train** is a throwaway branch `wt/train-<n>` that merges several ready changes,
  is gated once and lands with one fast-forward.
- **Merge hook**: relay's core hook (`plugins/core/hooks/merge.py`) that judges every `git merge --ff-only wt/<name>` into
  the default branch before it runs (behind? queue rules? gate green on the head?) and, after it, removes the worktree and
  branch (and, once the observability build lands, writes the change's record).

## 0. In short

- The two scripts are already the base unit: **128 runs in 3 days** (24-26 Oct), 761 agents finished inside them,
  against 50 agents the front started by hand. They ran five kinds of work, not two: new changes, fix rounds, re-checks
  of a change or a train, designs, and (by hand, outside the scripts) analyses.
- One shape covers all of them: a run is a list of **units**, each with a **kind** (`change`, `built`, `fix`, `recheck`,
  `design`, `analysis`, `experiment`). The kind names the fixed list of stages the unit runs; nothing is inferred from
  which optional fields happen to be present.
- **Delivery: one file in relay's `delegate` plugin, `plugins/delegate/workflows/run.js`, which the delegate skill
  calls by path**, not by name. By path the tool reads the file at every call, so a merge into relay's default branch
  reaches the very next run. Claude Code also lists it by name (`delegate:run`), but that copy is loaded once per session.
  Another user gets it with relay's code, and one pull updates the script, the CLI and the hooks together.
- Workflows are **off by default on the Pro plan** (verified in code). `relay install` turns them on when the user has not
  set them, and `relay doctor` names the cause when they are off.
- Stage events need no new channel: the observability design reads stages from the agent labels. This design writes the
  full stage list, and a test fails when the script uses a label outside it.
- Landing moves into the script as a **run-level stage**: it runs after every unit has ended and lands all the ready units
  of the run at once (a train when there are two or more). A new Python command, `relay land`, prepares the landing. The
  final fast-forward stays a plain `git merge --ff-only` that a runner runs, so the merge hook judges and cleans up as
  today. Whether the script lands by itself is the one real choice (question 1).

## 1. What "one unit of run" means here

### 1.1 What ran, measured

Run records `workflows/wf_*.json` of this session, 24 Oct 03:50 to 26 Oct 23:02 UTC:

| Kind (from the run's args) | Runs | Agents (sum / median per run) | Tokens per run (median) | Minutes per run (median) |
|---|---|---|---|---|
| change (build to check) | 48 | 392 / 7 | 241k | 65 |
| change, already built (`built` given: starts at the gate) | 7 | 43 / 7 | 187k | 51 |
| change + design in one run | 5 | 98 / 21 | 831k | 95 |
| design only (thinker, critic, thinker) | 5 | 13 / 3 | 301k | 21 |
| fix cycle (fix, gate, check) | 63 | 225 / 3 | 73k | 28 |

- 10 designs ran on the thinking stages. Judging by their names, several were analyses rather than designs of a feature
  (`regate`, `gate-speed`, `checks-artifacts`, `portable-r3`; I did not read their contents).
- The fix cycle held 75 units: **32 with a fix prompt, 43 without one** (a gate and a check only: a re-check). The re-checks
  covered a change after it took the default branch (`where-list` 4 times), a train (`train-8` 3 times, `train-15` 3
  times), and a change whose paid run was red (`wave-red` 4 times).
- Analysis and experiments ran by hand, outside the scripts. Of the front's 50 hand-started agents: 4 thinkers ("Assess
  porting relay to pi", "Analyse time per change", "Find cause of red paid run", "Throwaway demo and release readiness")
  and 1 scout ("Estimate vs actual time analysis"). The rest: 22 runners (19 of them gates: a train head, or a branch
  after it took the default branch), 9 checkers (trains, re-checks), 6 fixers (4 for merge conflicts), 5 workers (2 landing
  or migrating a train). So the scripts lack exactly three things today: analysis, trains, and taking the default branch.
- Resumes: 6 of 139 Workflow calls used `resumeFromRunId`; 4 runs reused 7 finished agents.
- The scripts were edited by hand while in use: **11 different script texts** over 128 runs (change cycle 6, fix cycle 5),
  all inside this one session, all called by `scriptPath`. Each edit took effect at the next call. The two files share
  their gate function, the three result shapes, the "fails without the fix" paragraph and the queue check loop, copied
  word for word.
- Outcomes of the 151 units the scripts returned: 93 ready, 58 not. Where the 58 stopped: queue check 10, crash 10 (the
  unit came back empty, which the script calls `crash`; its function threw, see 1.4), owner 8, gate after fix 7, queue
  done 7, build 4, gate 3, fix 2, no stop recorded 7.
- Agents that did not finish: 6 left "in progress" (5 gate runners and 1 thinker, all in the 5 runs the front killed), 4
  ended in error (2 builds, 2 fixes). Gate runners: 218 agents, **3.32M of 26.15M tokens (12.7%)**, median 8 tool calls
  each.
- Labels, from the agents' meta files (791 workflow agents): gate 226, check 100, fix 92, build 75, check queue item 71,
  review 70, close queue item 61, check show 44, design 13, fix red gate 12, design review 12, design revise 11,
  **fix red gate after fix 4**. That last label is not in the observability design's fixed list (section 3.1).

### 1.2 What each kind needs and gives

| Kind | Needs | Gives back | Stages, in order |
|---|---|---|---|
| `change` (queue fix or feature) | name, worktree, brief, quiet check command, queue items it closes | ready or where it stopped, review counts, queue items closed, gate log | build, gate, (fix red gate, gate), review, (fix, gate), check queue item, close queue item, check, check show |
| `built` (code written by hand, not yet reviewed) | the same, without the brief | the same | gate, (fix red gate, gate), review, (fix, gate), check queue item, close, check, check show |
| `fix` (a fix round after a review) | worktree, fix prompt, findings file, earlier fix reports, check command, queue items | the same, without review | fix, gate, (fix red gate, gate), check queue item, close, check |
| `recheck` (a change after it took the default branch, a train, a red paid run) | worktree, findings file (`relay check findings` lists the `M<n>` merges), check command | open count, gate log | gate, (fix red gate, gate), check |
| `design` | brief, output path, review path | the design path, the review's main point, the revision's summary | design, design review, design revise |
| `analysis` | brief, output path | the report path and its 10-line summary | analysis (and design review, design revise when `review: true`) |
| `experiment` (a measurement, not a code change: a bench, a timing; never a paid run) | brief, worktree or none, output path | the data path and the thinker's reading of it | measure, analysis |

- An experiment that changes code (the bench change `bench-worker`) is a `change`, not an experiment: it lands.
- **A paid run is never a stage.** The rule says a job over about 30 minutes (the paid `bin/ci`) is the front's, run with
  Bash `run_in_background`. A measure step whose brief needs a paid run returns `stopped_at: "measure"` with the command
  for the front to run. An `analysis` unit then reads the result in a later run. This is the test that fails if a paid run
  slips in: the `measure` stage's prompt is data in `run.js`, and a unit test asserts it holds the line "if the
  measurement is a paid run (bin/ci), do not start it: return the command".

### 1.3 One shape

```
args = { scratch, settings?, land?: true, units: [ { name, kind, ...fields of that kind } ] }
change:     { wt, check, brief, queue?: [{slug, findings}] }
built:      { wt, check, queue? }
fix:        { wt, check, fix, findings, fixes?: [paths], queue? }
recheck:    { wt, check, findings }
design:     { brief, out, review }
analysis:   { brief, out, review?: false }
experiment: { brief, out, wt? }
result = { units: [ { name, kind, outcome: "ready" | "done" | "stopped" | "owner", stopped_at?, detail?,
                      reports: [paths], review?, queue?, gate_log? } ],
           land?: { outcome: "landed" | "stopped" | "owner" | "off", train?, landed: [names], left: [{name, why}] } }
```

- **The kind, not the fields, picks the stages** (this fixes revision 1's `from: "gate"`, which meant either "built,
  review it" or "re-check, no review" depending on whether `findings` was present). The arg check refuses a unit whose
  fields do not belong to its kind, with one line: `unit where-list: kind recheck takes wt, check, findings; got fix`.
  Tests: `{kind: "built"}` runs gate, review, fix, gate, check; `{kind: "recheck", findings}` runs gate, check only;
  `{kind: "built", findings}` is refused, not guessed.
- One file, `run.js`, holds every stage function once. Each kind keeps its own stage list, the prompt of each stage, and
  the result schema of each agent. A script cannot import another file ("Self-contained workflow script", verified in
  code), so one file is the only way to keep one copy of the gate stage (principle 7; today's copy-paste is principle 2).
- `workflow(name, args)` exists (verified in code: "run another workflow inline as a sub-step ... Nesting is one level
  only"), so a later split into named sub-workflows stays possible; it is not needed now.

### 1.4 Settings

Each setting goes in `args.settings`, with a default, a bound, and what happens at the bound:

| Setting | Default | Bound | At the bound |
|---|---|---|---|
| `gate_turns`: turns a gate runner has | 40 (stop and report at 35) | 20 to 80 | at 20 a 60-minute gate (measured max 61 min) ends "still running" and the unit stops at `gate`; at 80 a stuck runner costs about twice the tokens |
| `measure_turns`: the same bound for the measure stage | 40 | 20 to 80 | as `gate_turns`; a measurement over about 4 minutes runs detached, the same way a gate runner waits |
| `retry_dead`: a fresh agent when one ends without its result | 1 | 0 to 2 | 0 is today: the unit stops; at 2 a stuck gate costs up to 3 runners (about 45k tokens at the measured 15k median) |
| `gate_fixes`: fix-red-gate rounds per gate | 1 | 0 to 3 | 0: a red gate stops the unit; 3: up to 3 fixer runs on one red step before the owner sees it |
| `review_continue`: fresh judges after "remaining" | 1 | 0 to 2 | the delegate skill's rule (a second "remaining" goes to the owner) is the default |
| `land_rounds`: take-default, gate, check rounds before landing gives up | 2 | 1 to 4 | at 1, a single landing elsewhere during the gate stops the landing at `land`; at 4, up to 4 extra gates (about 60k tokens and 4 gate times) before the owner hears of it |
| `land_wait`: minutes to wait for another landing's lock | 10 | 0 to 30 | 0: a busy lock stops the landing at once with "land busy"; at 30 a run holds its result for half an hour |

**How the retry works** (fixes revision 1, which assumed a dead agent returns `null`). When an agent ends without its
structured output, Claude Code first nudges it once. If it still has none, Claude Code **throws**: `agent({schema}):
subagent completed without calling StructuredOutput (after in-conversation nudge)` (verified in code). `null` comes back
only when the user skips the agent. So each `agent()` call goes through one wrapper:
`try { r = await agent(...) } catch (e) { r = { dead: String(e) } }`. On `dead` it retries up to `retry_dead` times with
the same label. On `null`, or when the retries run out, the unit stops at that stage, with `detail` holding the error
text. Revision 1 called that `crash`.
The first fix for the gate runners' deaths is still the bounded wait (queue item
`a-gate-waited-on-by-a-runner-dies-at-its-turn-li`, principle 6); the retry only catches what is left. A retried gate
runner cannot start a second gate on the same worktree: `relay gate` waits on the worktree lock and then reuses the log
(`lib/relay_gate.py:145-158`, read by the review).

## 2. Where the script lives and how it reaches a project

Verified in Claude Code 2.1.310's code (read, not run):
- Claude Code looks for workflows in three places: the user's `~/.claude/workflows/*.js`, each project folder's
  `.claude/workflows/*.js` (a project file overrides a user file of the same name), and plugins. A plugin's `workflows/`
  folder is loaded by itself, and the manifest field `workflows` may list other paths instead. A plugin workflow is named
  `<plugin name>:<meta.name>`. A file over 524288 bytes, or one whose `meta` does not parse, is skipped with a warning.
- **The named list is built once per session** (`workflows ??= ...`). A function clears it, and the same function clears
  the plugin commands, agents, skills and output styles (`Ie().workflows=void 0`, called from the plugin cache reset).
  Whether `/reload-plugins` calls that reset is not verified.
- **`scriptPath` is read at every call**. The tool's own description says: "To iterate, edit that file with Write/Edit and
  re-invoke Workflow with the same `scriptPath`" (verified in code). This session confirms it: 131 of 139 calls used
  `scriptPath`, and all 11 edited texts took effect at the next call (measured).
- The tool's on-off switch, in order: the runtime must support it; `CLAUDE_CODE_WORKFLOWS` false turns it off; an org
  policy (`allow_workflows`) can turn it off; the user setting `enableWorkflows`; with no setting, **it is on except on the
  Pro plan** (`defaultOn: plan !== "pro"`). The first run asks a usage-consent question. All verified in code.
- **Core hooks fire inside workflow agents** (measured: 26 refusals by the core `guard-main` hook in the Bash calls of
  workflow agents, across 14 runs: an anonymous `git stash`, a write to `.relay/checks`, an environment dump). So a
  `git merge --ff-only` that a workflow runner runs passes through the merge hook just as the front's would.
- Plugin text gets `${CLAUDE_PLUGIN_ROOT}` replaced with the plugin's folder (verified in code). Which kinds of plugin
  text get the replacement (hooks for certain; skill bodies not traced) is checked live in build step 1.

### A. One file in relay's `delegate` plugin, called by path (recommended)

The file is `plugins/delegate/workflows/run.js`, with `meta.name: "run"`. The delegate skill calls it with
`scriptPath: ${CLAUDE_PLUGIN_ROOT}/workflows/run.js`. relay's plugins load from relay's main checkout, so that path is
the main checkout's file. If the replacement does not reach skill text, the skill names the path through `relay doctor`'s
output line `workflow script: <path>`, from the same `marketplace_root()` relay already uses. The delegate plugin also owns
the agent types the script starts (`delegate:worker`, `delegate:runner` ...), so the two travel together.
- **Updates on this machine**: a merge into relay's default branch is used by the next run, in every session that is
  already open (fixes revision 1's "seen by the next session": the measured front session lasted 3 days and held 11
  texts). An open session's `delegate:run` by name stays stale until the session ends; the skill never calls it by name.
  A user who types `delegate:run` in a fresh session gets the current text.
- **Updates for a user on another machine**: relay's code is one git checkout (`install.sh` puts it at `RELAY_ROOT`,
  default `~/relay`), and the plugins, the CLI, the hooks and `run.js` all come from it. So one `git pull` updates all
  four together, and they never drift against each other. There is no update command today. `relay update` (a
  fast-forward-only pull of that checkout, then `relay sync`) is build step 7. Without it the user runs the pull by hand.
  No releases or version pins: relay has no outside users yet (memory: no consumers, speed first).
- **Workflows off**: `relay install` already merges the user's settings (marketplace and plugins, `merge_user_settings`).
  It adds `enableWorkflows: true` **only when the key is unset**; an explicit `false` stays the user's choice and is
  reported. Rests on: on the Pro plan workflows are off unless set (verified), and a change through the script cost about
  165k agent tokens and about 0 front turns, against 236-277k and about 22 by hand (24 Oct measurement in the queue
  item). Turning them on lowers a Pro user's spend, it does not raise it. `relay doctor` adds one line naming the cause
  when they are off. The causes it can read are `CLAUDE_CODE_WORKFLOWS`, read by name, and `enableWorkflows: false`. An
  org policy or the plan it cannot read, so it says "on unless your plan is Pro or your organisation turned workflows off;
  `enableWorkflows: true` in ~/.claude/settings.json turns them on". The consent question is Claude Code's, asked once;
  relay does not skip it.
- **Project override**: through the args. Each project's check command and gate already come in as args, and a project's
  `kit.toml` can hold extra stage text later. A project that needs another cycle saves its own `.claude/workflows/x.js`
  under another name; it cannot replace `delegate:run` by name, because plugin names carry the prefix. Decided: override by
  args only until a second project needs more (principle 7; owner can reverse).
- **Breaks**: with workflows off (above, or `--safe-mode`, or a non-native Claude Code: verified messages exist for each)
  there is no Workflow tool, and the delegate skill keeps the hand path. The session's persisted copy of a run's script
  (every call saves one under the session folder) is not the source; the skill says to edit `run.js` in a worktree, never
  that copy. Not verified: whether a `scriptPath` outside the project folder asks for permission in another project. This
  session's 131 calls used paths outside the repository (the session folder) and none asked; build step 2 checks it in
  a second project.

### B. `relay setup` / `relay sync` write a copy into each project's `.claude/workflows/`

- **Updates**: only at `relay sync`. At this week's pace (11 script texts in 3 days) that is 11 syncs times every project,
  and each open session still keeps its old named copy.
- **Override**: the project edits its copy. Then sync must know not to overwrite it (a marker or a diff check), which is a
  second part to build.
- **Breaks**: a built file sits beside its source in every project (principle 3), and the folder is on Claude Code's
  protected-path list, so every write asks; the copies drift. This is what the queue item's text says ("reach every project
  relay sets up as saved workflows"). I recommend against that wording for these reasons.

### C. Kept in relay's repo outside any plugin, named by path or symlinked into `~/.claude/workflows/`

- **Updates**: by path, the same as A. With the symlink, the name has no prefix, and a project file of the same name
  overrides it (verified order: user first, project folders after); by name it has the same once-per-session staleness.
- **Breaks**: the file is not bound to the plugin whose agent types it starts. `relay install` gains a symlink to keep
  alive (`relay doctor` would check it).
- **Wins over A only** when a project needs to override the script under the same name. No project needs that today.

### D. Do nothing

The scripts stay in this session's folder. Measured cost: a new session copies them from an old session's folder (the
front did so this week, from session `0cc68fe0-...`). Claude Code removes old session folders after its clean-up period
(not checked on this Mac). No test covers them, and the 11 hand edits went untested. No other project and no other user
has them, and the observability record cannot rely on the labels staying in the fixed list (4 of 791 labels are already
outside it).

### 2.1 How relay's gate tests a script it cannot run

The Workflow tool cannot run inside a unit test. But the script is plain JavaScript over seven globals (`agent`,
`pipeline`, `parallel`, `workflow`, `phase`, `log`, `budget`), with no file or shell access, and `Date.now` and
`Math.random` refused (verified in code). So:
- **A fake runtime under Bun** (Bun is already a gate tool, `lib/relay_ci.py:47`): a small harness defines those globals,
  answers each `agent()` from a scripted table keyed by label, runs `run.js`, and records the labels in order. A table
  entry can return a result, return `null`, or `throw: "<text>"`, the last mirroring Claude Code's StructuredOutput error.
  Python test cases (stdlib `unittest`, `subprocess` with an argument list) call it and assert:
  - green `change`: labels `build: x, gate 1: x, review: x, check: x, check show: x`; unit `ready`;
  - red gate: `fix red gate 1: x` then `gate 2: x`; a second red stops at `gate`;
  - red gate after a fix: `fix red gate 3: x` (revision 1's `fix red gate after fix` is gone);
  - review with a Design or question finding: stops at `owner`, no fix runs;
  - a gate entry that throws once, then returns green: one retry with the same label, unit continues; throws twice with
    `retry_dead: 1`: stops at `gate`, `detail` holds the error text; returns `null`: stops at once;
  - `fix` and `recheck` reproduce today's fix-cycle sequences; `{kind: "built", findings}` is refused;
  - landing (section 3.2): one ready unit lands alone; two ready units make one `train: <n>` call; a unit that stopped is
    left out and named in `land.left`;
  - every label matches `^(<stage list>)(?: \d+)?: [a-z0-9][a-z0-9-]{0,63}$`. **This is the test that fails when "the
    script only uses stage names from the list" is false.**
- **The stage list is one list**: `run.js` holds it as a constant; a test reads it and compares it with the list in
  `lib/relay_metrics.py` (the observability design's home for it). It fails when the two differ.
- **The meta block parses** as a pure literal, and the file is under 524288 bytes: a test, mirroring Claude Code's rules.
- **Prompts are data**: the measure stage's paid-run line (1.2) and the land stage's "run exactly the printed command"
  line are asserted by a test.
- **Not testable in the gate**: whether real agents follow the prompts. That stays with one real run per wave on relay
  itself (it runs every change anyway), not a paid eval.

## 3. Stage events, and the front's hand steps

### 3.1 Stage events and the full stage list

The observability design (`docs/plans/dev-metrics.md`, sections 2 and 5.2) reads stages from what Claude Code already writes: the
observe hook copies each agent's label into the ledger when the agent stops, if the label matches the fixed pattern. A
workflow script cannot write a file anyway (no file access). So the script's whole duty is the label. Every `agent()` call
is labelled `<stage>[ N]: <name>`, with the stage from the list below. `<name>` is the branch name without `wt/`, or the
design, analysis or train name.

The stage list (this replaces the stage list of `docs/plans/dev-metrics.md` (sections 4.2 and 7 step 1), which is to live in `lib/relay_labels.py`, not built yet):

| Stage | Kind or step | New? |
|---|---|---|
| build | change | |
| gate N | change, built, fix, recheck, land | |
| fix red gate N (N = the gate it fixes) | the same | replaces `fix red gate` and `fix red gate after fix` |
| review | change, built | (a second judge after "remaining" is `review 2`) |
| fix | change, built, fix | |
| check queue item N, close queue item N | change, built, fix | |
| check, check show | change, built, fix, recheck, land | |
| design, design review, design revise | design; analysis with review | the thinking stages keep the `design` prefix, so a design review is never counted as a code review of a change with the same name |
| analysis | analysis, experiment | new |
| measure | experiment | new |
| take default | land | new |
| fix conflict | land | new |
| train | land | new |
| land | land | new |

Critique of the brief's pick: "the scripts must report stage events" reads as a second event channel. That would repeat
what the labels already carry (principle 3), so I build on the labels only. An analysis or experiment never lands, so it
gets no per-change record (that design records at landing). Its agents still sit in the ledger under their labels.
Decided so (owner can reverse). A train's own stages (`gate 1: train-19`) belong to no single change. Whether the
per-change record shares them among the riders is for the observability build to decide; this design only keeps the names
distinct.

### 3.2 What the front did by hand around the runs, and the land stage

Front Bash calls whose command text contains each step, 24-26 Oct (1109 Bash calls in all; a few are reads that only
mention the command, so these are upper bounds):

| Step | Calls | Where it goes |
|---|---|---|
| `git merge --ff-only` into the default branch | 112 | the land stage (a runner runs it; the hook judges) |
| merge the default branch into a task branch | 73 | the land stage, through `relay land --take` |
| a train (`wt/train-<n>`) built, gated or merged | 69 | the land stage, through `relay land --train` |
| `relay gate` run by the front itself | 83 | already in the script; the retry setting removes the fallback |
| `git worktree add` | 100 | stays with the front for now: the brief names the worktree before the run starts |
| `relay queue take` / `add` / `done` | 56 / 102 / 30 | `done` is in the script; `take` and `add` stay with the front (`add` carries the owner's words and the IP) |
| `bin/ci` (the paid run) | 105 | stays with the front (rule: a job over 30 minutes is the front's); never a stage (1.2) |
| `relay sync` | 74 | stays with the front |

**The land stage runs once per run, after every unit has ended** (fixes revision 1, where each unit landed by itself, so
the second of two ready units took the first one's code, needed a new gate, and never formed a train). It collects the
units with outcome `ready` when `args.land` is on:

```
ready units          none -> land.outcome "off"
                     one  -> take default -> (code came in: gate, check) -> ff
                     two+ -> train -> gate -> check -> ff of wt/train-<n>
ff refused (the default branch moved meanwhile) -> back to take default, at most land_rounds times, then stop at "land"
```

`relay land` (Python, stdlib) does the git work up to the fast-forward, never the fast-forward itself:
- `relay land --take wt/x`: holds the landing lock (the rule "only one landing at a time while a train is open"; waits
  at most `land_wait`, then prints `land busy` and exits non-zero). It merges the default branch into `wt/x` with a merge
  commit, never a rebase, and prints one of `took: nothing`, `took: inert` (only queue or handover files came in:
  `relay changed` lists nothing, the old gate still counts) or `took: code` (the land stage then runs `gate N` and `check`,
  and `relay check findings` lists the `M<n>` merge). On a conflict it aborts the merge and prints the files. The land
  stage starts a `fix conflict` fixer; after it the unit's outcome is `owner`, because the rule asks the owner before a
  merge whose conflict a fixer resolved by hand.
- `relay land --train wt/a wt/b ...`: builds `wt/train-<n>` from the default branch and merges the riders with `--no-ff`.
  A rider that conflicts is aborted, dropped and named (`land.left`); the others go on. When `relay changed --own` lists
  files both riders changed, it says the train's check needs a merge review.
- `relay land --ready wt/x`: calls the merge hook's own `judge()` as a dry run (imported, not copied: one judge) and
  prints either the refusal line or the exact command `git -C <main> merge --ff-only wt/x`.
- **The fast-forward is the runner's own Bash call of that printed command** (fixes F1, the review's main point). The core
  hooks fire inside workflow agents (measured, section 2), so the merge hook judges this merge exactly as it judges the
  front's. After the merge it removes the worktree and branch, and it will write the observability record (that design
  writes it from `merge.py post`, `docs/plans/dev-metrics.md` section 5.1). A Python program's own `git merge` would pass through no
  hook. Then the guard, the clean-up and the record would all be skipped, so `relay land` never merges into the default
  branch itself. **This is the test that fails when that "never" is false**: in a temporary repo, `relay land --take`,
  `--train` and `--ready` are run against a branch that is ready, and the test asserts the default branch's head is
  unchanged after each.

The open fix item `a-train-cannot-recheck-a-queue-item-its-branch-c` (a checker on a train cannot record a check of an item
its branch closed) must land first, or trains that carry a closed item stop at the merge hook.

Tests for `relay land` (temporary repos, never the live `.relay/`):
1. The default branch has not moved since the gate: `--take` prints `took: nothing`, makes no merge commit; `--ready`
   prints the ff command; running it through the hook fast-forwards and removes the worktree and branch.
2. The default branch moved with only inert files: a merge commit, `took: inert`, `--ready` still prints the command.
3. The default branch moved with code: a merge commit, `took: code`; `--ready` prints the hook's "no green gate for the
   code at ...'s head" line, not the command.
4. The branch is behind and was not taken: `--ready` prints the hook's "is behind ... take ... first" line.
5. A rebase never happens: the branch's earlier commit sha is unchanged after `--take`.
6. Two riders with a conflict: the second is dropped and named; the train holds the first.
7. The lock is held: the second caller waits `land_wait` (set to 0 in the test) and exits with `land busy`, never hangs.
8. The front's own `git merge --ff-only wt/x` keeps being judged by the hook exactly as today (the hook's existing tests,
   unchanged).

## 4. How leading tools do this

- **GitHub Actions**: a *reusable workflow* (`on: workflow_call`, typed `inputs` and `outputs`) is called by reference,
  `owner/repo/.github/workflows/x.yml@<ref>`; a *composite action* bundles steps and ships as a versioned repository.
  Callers pin a tag or a sha and override through inputs, never by editing the shared file. Lesson taken: the shared
  script lives in one repository, and projects pass inputs. Not taken: version pins, since relay has one user and lands on
  its default branch (memory: no consumers, speed first). Calling by path to the main checkout is the same as
  `@main`.
- **Nx / Turborepo**: the pipeline is data (`turbo.json` tasks with `dependsOn`, Nx `targetDefaults`), shared through a
  preset or plugin; a task whose inputs did not change does not run again (a cache keyed by a hash of the inputs). The
  Workflow tool's resume (an unchanged prompt returns its old result) and relay's gate reuse (`relay check show` before a
  second gate) are the same idea. Kinds mapping to fixed stage lists (1.3) is Nx's named targets.
- **Dagger**: pipelines are code in a real language, published as modules and called by reference; the same engine runs
  them on a laptop and in CI, so a pipeline is tested by running it. Lesson taken: test the script's control flow by
  running it, here under a fake runtime.
- **Temporal**: workflow code must be deterministic (no clock, no random: the same two bans Claude Code puts on workflow
  scripts), because a run is resumed by replaying its history. Side effects live in *activities*, and tests run the
  workflow in a test environment with mocked activities. Code changed while runs are in flight is guarded by versioning
  markers. Lesson taken: the fake-runtime test is Temporal's mocked-activity test. Each call reads `run.js` afresh, but
  a run in flight keeps the text it started with, so no marker is needed while a run lasts one call. Temporal also
  separates the decision from the side effect, and so does `relay land`: it prepares, while the side effect (the
  fast-forward) goes through the one guarded door.

## 5. Recommendation, what it rests on, and the build order

Recommended: one script `run.js` in `plugins/delegate/workflows/`, called by path (approach A); the kind-based shape of 1.3;
labels from the stage list of 3.1; the Bun fake-runtime tests; a run-level land stage over `relay land`, with the
fast-forward left to the hook-guarded Bash call; `enableWorkflows` set at install when unset.

Rests on:
- measured: 128 runs of 5 kinds; 43 of 75 fix-cycle units were re-checks; 11 hand-edited texts, each picked up by the
  next `scriptPath` call; the front's 112 / 73 / 69 landing calls; 26 core-hook refusals inside workflow agents; 4 of 791
  labels outside the fixed list;
- verified in code, not run: plugin workflows and the `<plugin>:<name>` form; the once-per-session named list; `scriptPath`
  read per call; Pro default-off; the StructuredOutput throw;
- not measured: the token saving of moving landing into the script. The 24 Oct figure (about 165k agent tokens per change
  against 236-277k by hand, about 0 front turns against about 22) covers the cycle without landing. Also not measured:
  the extra wait the end-of-run landing puts on the first ready unit of a run, since the spread of unit end times
  within one run was not measured.

Build order (sizes in agent minutes, a Sonnet worker unless named):

1. `plugins/delegate/workflows/run.js`: all seven kinds, the settings, the retry wrapper, labels from the constant list,
   no land stage yet. The delegate skill's steps 1-9 say "the script does these; the steps are the hand path when
   workflows are off", so the flow is not written down twice. Also a live check of `${CLAUDE_PLUGIN_ROOT}` in the skill
   text. The Bun harness and the Python tests of 2.1. About 60 minutes.
2. A real run on relay itself, called by path, with the next queue change, plus one run from a second project to check
   that a path outside the project asks no permission. About 10 minutes of the front.
3. The fix item `a-train-cannot-recheck-a-queue-item-its-branch-c` (already queued, 45 minutes estimated). Before 4.
4. `relay land --take / --train / --ready` with the tests of 3.2. About 90 minutes.
5. The land stage in `run.js` (`take default`, `fix conflict`, `train`, `gate`, `check`, `land`, the round bound and
   the lock wait), shaped by question 1; the front skill's merge section points at it. About 30 minutes.
6. `relay install` sets `enableWorkflows` when unset; `relay doctor` adds the workflows line, the `workflow script:
   <path>` line, and a check that `run.js` is present and its meta parses. About 20 minutes.
7. `relay update`: a fast-forward-only pull of relay's code checkout, then `relay sync`. It refuses with a line when the
   checkout has local commits or is not on its default branch. About 20 minutes.

The stage list in `lib/relay_metrics.py` comes from the observability build. If step 1 lands first, `run.js`'s list is
the source, and the metrics build copies it and adds the comparison test then.

## Review findings: where each went

| Finding | Holds? | Where it is fixed |
|---|---|---|
| F1 HIGH `relay land` merges from Python, so the merge hook never fires | holds | 3.2: `relay land` never fast-forwards; the runner runs the printed command and the hook judges and cleans (measured: core hooks fire in workflow agents); the "never" has its test |
| F2 taking the default branch makes the old gate stale; no loop or bound | holds | 3.2: `--take` reports nothing / inert / code; code means gate and check, then land; `land_rounds` bounds it (1.4) |
| F3 landing per unit never forms a train; the lock refusal has no next step | holds | 3.2: one run-level land stage over all ready units; `land_wait` bounds the lock (1.4) |
| F4 the named copy is frozen for the session | holds | 2.A: the skill calls by `scriptPath`, read per call (verified, and measured by 11 edits); the name stays only for discovery |
| F5 Pro default-off, org policy, consent; remote updates | holds | 2.A: install sets `enableWorkflows` when unset, doctor names the cause; one checkout, one pull, `relay update` (step 7) |
| F6 a dead agent throws; it does not return null | holds | 1.4: the try/catch wrapper; the fake runtime can throw (2.1) |
| F7 a paid run inside the experiment kind | holds | 1.2: a paid run is never a stage; the measure stage returns the command; `measure_turns` |
| F8 `from: "gate"` meant two flows | holds | 1.3: `kind` picks the stages; an unclear combination is refused |
| F9 thinking-stage names clash; `fix red gate after fix` is outside the list | holds | 3.1: the full list; the `design` prefix stays; `fix red gate N` |

One critique of the brief: it gives the install as "code in `$RELAY_HOME/src`", but `install.sh` today reads the code
from `RELAY_ROOT` (default `~/relay`) and keeps `RELAY_HOME` for state. The design uses what the code does. Where the code
should live is the install decision's to settle; it changes no part of this design, since every path here comes from
`marketplace_root()`.

## Open for the owner

**1. Does the script land a ready change by itself?**
Today every run ends with the front landing by hand. It takes the default branch into the branch, builds a train when
several changes are ready, gates it, and fast-forwards: about 112 + 73 + 69 front calls in 3 days, each a front turn that
re-reads the front's whole context. With the land stage the script does the same under the same rules: the merge hook
judges the fast-forward, a conflict a fixer resolved goes to you first, and an open Design or question finding stops it.
The front then reads one line per landed change. Live example: on 26 Oct `wt/train-19` needed a merge, a gate, a refused
merge, two re-checks and a fresh merge, all done by the front. Revision 1's weak point, a landing the hook never saw, is
fixed: the hook now judges the script's merge exactly as it judges the front's.

| | Front turns per landing | Who sees it first | Risk |
|---|---|---|---|
| a. script lands (`land: true` by default) | about 0 | the front, from the result | a wrong rule in the land stage reaches the default branch before anyone looks; the hook's judge still refuses what it refuses today |
| b. script prepares (takes the default branch, builds the train, gates, checks), front runs the one fast-forward | 1 | the front, before the merge | none new; one front turn per landing stays |
| c. as today | several | the front | none new; the 250-odd hand calls stay |

- a. The script lands (recommended: the rules already let the front merge without asking; this only moves the hands, and
  the same hook guards both).
- b. The script prepares; the front runs the one fast-forward.
- c. Keep landing by hand.

## Not verified, for the build

- Whether `/reload-plugins` calls the reset that clears the named workflow list (the design no longer depends on it).
- Whether `${CLAUDE_PLUGIN_ROOT}` is replaced in skill text (build step 1; the doctor line is the fallback).
- Whether a `scriptPath` outside the current project asks for permission (build step 2).
- Claude Code's cap on agents running at once inside one run (a `pipeline` over many units hits it).
