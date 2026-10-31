---
name: delegate
description: How the main session hands work to agents without losing context - the routing table, the brief file, and how to read a hand-back. Load when a request needs more than a few lines of reading or any edit, before starting the first agent.
---

# Delegating

The main session is the front desk: it talks to the owner, decides who does
what, and keeps the conversation. It does not read long files, run long
commands, write code, or hold documents. Each of those goes to one typed agent
with one brief, and comes back as at most 10 lines.

## Who does what

| The request needs | Agent | Why this one |
|---|---|---|
| an answer from what is already in this conversation, in a few lines | nobody: answer | the cheapest agent is none |
| reading more than two files, a search, "where is / what reads / what does" | `delegate:scout` | reads a lot, says little; cheap model, low effort |
| a command, test run, pipeline read, PR create or merge, API call | `delegate:runner` | the output stays out of this session |
| writing or changing code, docs, a script, a test; a group of tasks | `delegate:worker` | builds from a brief in a worktree, loops on the check |
| fixing listed findings or a red gate | `delegate:fixer` | narrow scope, no new design |
| the owner asks about a NEW mechanism (a field, a command, a step: "can we", "would X help", "how should we") | `delegate:thinker`, then `delegate:critic`, then the revision | the design track: the brief holds the owner's words verbatim and says to measure live data first and to give at least two distinct approaches plus "do nothing" and how leading tools solve it; the owner gets the revised design, not the front's first idea; the thinker keeps the plan beside the item with `relay queue plan <slug> --input <file>` as its last step, never in `docs/` |
| explaining a mechanism that already exists | nobody, or `delegate:scout` | the front answers; no design track |
| a design, a plan, options with costs, the cause of a hard bug | `delegate:thinker` | the big model where judgment pays; writes one file |
| any request to review code (a function, a file, a diff, a branch), a review before merge, a design critique | `delegate:critic` | adversarial, read-only, findings with cases; however small the code, never read it and judge it yourself: the front's own review is the cheap path that skips the judge model |
| the check of a fix against the review's cases | `delegate:checker` | reads the findings, the fixer's report and the gate log; ends with a verdict |

The table has no row for "small": one function, one test or one edited line is
still `delegate:worker`. The front's own file reads and edits would stay in
this session's context and be re-read on every later request of a long
session; a worker builds in a worktree, loops on the check and gets the review.
The front never writes the change itself, whatever its size.

A job longer than about 30 minutes, such as the full paid `bin/ci`, is not a
runner's (its turns end mid-wait): the front starts it in the background (see
the front skill).

Never `general-purpose` (every tool, 30k tokens re-read each request) and
never `fork` from a session over 100k tokens: the routing guard refuses both.
A worker or fixer gets `model: opus` only with a line `Escalated: <reason>` in
its prompt, after a middle-model agent failed the same brief.

Each agent's model and effort come from the active profile (`relay profile`);
never set `model:` on a call. The one exception is the escalation above.
At most `[delegate] max_agents_at_once` agents run at once (default 4, bound 1 to 8);
the route guard notes the cap.

## The brief file

Context is not lost when it is written down. Before starting a worker, fixer
or thinker, write `<scratchpad>/briefs/<name>.md` (the session's scratchpad
directory; `mkdir -p` it):

```
# <what, in one line>
Project: <name>, <what it does in a few words>
Worktree: <absolute path> (branch <name>)        # for worker/fixer
Assembly: run `<worktree>/bin/relay sync agents` only (never the `relay` on PATH, never a full `relay sync`, never set RELAY_ROOT)   # where the job touches roles/ or agents
Goal: <the result, in the owner's words>
Done when: <the check that passes / the file that exists / the question answered>
Check: <command>                                  # the quiet check to loop on; in a project with `.relay/`: `relay precheck -C <worktree> && (<command>)`
Read: <file:section>, <file:lines>, ...           # only what this job needs
Files: <paths it may touch>                       # worker/fixer
Decisions (the owner's, verbatim):
- "<quote>"
Not decided (ask, do not guess):
- <item>
Constraints: <project rules that apply; the no-attribution rule where it applies>; commit the handover after the check
Report: <scratchpad>/reports/<name>.md
```

Then the prompt is one line:

> Implement the brief. Brief: `<path>`. Report: `<path>`.

Several independent jobs go out in one message. A group of related tasks goes
to one agent with one brief (fewer, longer agents are cheaper than many short
ones: every fresh agent re-pays its first read). A scout question needs no
brief: ask it in the prompt, several questions at once.

**Label of an agent started by hand.** Where the project has `.relay/`, the
description of every hand-started agent begins with `<stage>[ n]: <item id>`
(`build`, `gate 2`, `review`, ...; `land: <item id>` for a landing runner,
`other: <name>` for work that belongs to no change), and free words may follow
after ` - `. Example: `other: docker-deps - read the lockfile`. The label puts
the agent's time and cost into the change's record; the route guard refuses a
description without one.

## Lanes

Up to "Changes built at once: N" changes (front skill, "Lanes") are built side
by side, each by its own cycle run with its own worktree and briefs. The 4-agent
cap counts agents inside one change. A free lane is filled with
`relay queue start <slug> --scratch <folder>` (an item that overlaps a running
branch's files waits; `relay queue start` refuses it unless `--despite-wait` is given, with a stated reason). While a paid run goes, lanes keep
building; a change for which `bin/paid-cost touches <branch>` prints files waits at the landing
until the run ends, then lands through `relay land`.

## Reading a hand-back

The reply is at most 10 lines and starts with DONE, BLOCKED or BUDGET SPENT.
Open the report file (`head -40`) only when the first word is not DONE. A
judge's report path is its JSON (`.json`): read it with `relay check show
--brief <path>` (ten lines; without `--brief` the whole readable text). Never
paste a report into the conversation: tell the owner the outcome in one or two
plain sentences, and keep the path.

A BLOCKED agent is not restarted with the same brief: fix the brief (the
missing decision, the wrong assumption) and start a fresh agent. An agent that
has been idle for over 5 minutes is not resumed: start a fresh one from the
brief and the old report.

## Review loop

One good review, then a checked fix; never a new open review. When this
project's rules carry a list "Spec steps in the change cycle", each listed step
runs at the step number it names. After a worker's DONE on a change that will
be merged:

The script `${CLAUDE_SKILL_DIR}/../../workflows/cycle.js` runs the build of step 2 and
steps 3-7 for each change in a run (the reproduce step of step 2 comes before
the run); the steps below are the hand path when workflows are off.
Call the Workflow tool with that file as `scriptPath` (a path is read at every
call; the named copy `delegate:cycle` stays as the session first saw it). Args:
`base` (the default branch), `relay` (true where the project has `.relay/`),
`scratch`, and in a project without `.relay/` also `gate` (its own gate
command); a missing one stops the run in one line. Each unit has a `kind`:
`change`, `built`, `fix`, and in a project without `.relay/` `recheck` (its gate
runner first merges the default branch itself and a conflict stops it at gate with
"take conflict: <files>" for a fixer, then a new recheck). In relay mode `relay land`
takes the default branch and gates; a take conflict comes back as a `fix` unit of
the shape `relay land` prints (findings = the branch's last review JSON, no item). The script runs one
checker per change, as step 7 says.
Unit fields: `name`, `wt`, `check`, `branch` (relay mode), `item` (one fix-item
slug); `fix` also takes `fix`, `fixes`, `findings`; `recheck` takes `findings` and, when the
branch had a fix round, `fixes` (the fix report); `built` takes `built`; every kind also takes `land`. In relay mode the cycle
lands a ready unit itself, through `relay land`, as its last stage (the run
settings `land`, `land_fixes`, `land_reruns` and a unit's own `land` are in the
script's header); `land: false`, on the run or on one unit, keeps it at ready
for the front to land.

1. **Design review before a risky build.** A `delegate:critic` reviews the
   design or plan before a worker starts, when a trigger holds or the owner
   asks. The triggers are settings:

   | Trigger | Default | Bound |
   |---|---|---|
   | stored data shape or migration | on | on/off |
   | a hook or guard that runs on every tool call or session | on | on/off |
   | secrets, auth, network writes | on | on/off |
   | a shared base (`roles/`) or a rule (`rules/`) | on | on/off |
   | planned files changed | more than 8 | 3 to 30 |

2. **Build.** Before it, the reproduce step for a queue item whose `failing_kind` is
   `claim` (`relay queue show` prints it as "Failing case (claim)"). A fix item with
   no `failing_kind` (queued before the field existed) counts as a claim. The failing
   case is someone's word (a reviewer's, a scout's, the front's), not a failing
   test or a recorded red run. A `delegate:runner` or `delegate:scout` reproduces
   it on the live system, from the main checkout and before `relay queue take`
   (a read needs no worktree, so a held item is never left taken), when that is cheap (a command, a read, a test; a paid
   run is not: it stays the build's first step) and reports reproduced or not,
   with what it showed. Reproduced: the build starts. Not reproduced, either
   because the claim never held or because the failing case no longer fails
   (already fixed): no build; the item is held for the front, who brings all
   such items to the owner in one message with a recommendation (drop it, or
   close it as already fixed once `relay queue` can). The front decides this
   and the owner can reverse it; the owner is not asked one item at a time.
   Items with `failing_kind` `test` or `run`, and features, go straight to the
   build. Live cases, 24 Oct: the plugin-cache item (a reviewer's claim that
   sessions load a stale copy; a 30-second `claude -p` run disproved it after
   about 200k tokens of build and review), and the bench item (already fixed on
   the default branch that morning; one change cycle spent about 34 minutes and
   123k tokens before finding nothing to do).
3. **Gate before the review.** Where the project has `.relay/`, a
   `delegate:runner` runs `relay gate` (detached, with the recipe under Limits in every agent file: nohup, a log, a `kill -0` wait loop;
   macOS has no `timeout` program, so no agent calls it; it takes minutes) in the worktree, with the project's arguments (relay:
   `relay gate -- --quick`). It runs the free checks on the committed head and
   stores the result as `.relay/checks/<G>.gate.log`. A red gate goes back to
   the worker or a fixer, then this step again: a red build is never reviewed.
   `relay gate` on code that already has a green gate (only inert files
   changed since) reports that gate and runs nothing; a reused gate is the gate. A finished red
   gate with only `.relay/checks/` commits since is reported the same way
   (stderr says so); `relay gate --again` runs the command anyway, for a red
   that came from outside the code (killed, load, a missing tool).
   A runner that replies RUNNING with a log leaves the job running: start a
   fresh runner that waits on that pid and log; never start the gate again. A
   worker or fixer that hands back BLOCKED with still running: <log> is handled
   the same way, then a fresh agent goes on from its report.
   Elsewhere the gate is the project's own command, run by a runner into a
   log whose first line is `head <sha>` and last `exit <code>` (`{ echo "head
   $(git -C <wt> rev-parse HEAD)"; <gate>; echo "exit $?"; } > <log> 2>&1`);
   a remote pipeline gives `Gate: pipeline #<n> on <full sha> passed`; a flow
   with no gate by design (a spec review) passes `Gate: none (artifacts only)`.
4. **One whole-change review.** Every judge runs once, in one message, over
   `<base>...HEAD`, after a green step 3: `delegate:critic`, plus
   the judges the spec steps add.
5. **Fix.** One `delegate:fixer` per group of findings; it ends with one of
   four outcomes per finding (Fixed, Disputed, Gap, Outside).
6. **Gate again.** When fix commits exist, a `delegate:runner` runs `relay
   gate` (or the project's gate, as in step 3) on the fixed head, after the
   last fix and before the check. A red gate goes to a fixer, then this step
   again.
7. **Check.** `delegate:checker` on the findings file, the fixer's report and
   the gate log (with `Fixes: none` after a review with nothing inside the
   change; the gate log of step 3 is the gate). Its report is the JSON it
   recorded (`relay check record check`) at the `Report:` path: ONE record
   that holds the fix item's problem (`Q1`), every finding of every review (`F`),
   one verdict for each and the gate result. Where the project has `.relay/` a
   hook commits the check mark and that record. One checker run covers the
   queue check, the whole-change check and the merge check; `relay queue done`
   and the merge guard read the same record. Start it with the one-line check prompt below, never `Brief: <file>`:
   the hook reads the `Report:` label and, from that JSON, everything else.
   Then run `relay check show <branch>` (a runner; it waits while the hook is
   committing) before the front commits the handover, so the branch carries
   the state it was merged in and the commit does not meet the hook's lock.
8. **Take the default branch.** `relay land` takes it (the cycle's land stage runs it; the front runs it for a unit stopped at land or kept at ready by `land: false`) (a merge
   commit, never `git rebase`: a rebase gives every commit a new sha, and the mark
   names the old one), runs `relay gate` on the result and fast-forwards on
   green; no agent re-checks a clean take. A conflict comes back as a fix unit of
   the shape `relay land` prints: a fixer resolves it (`Fixes:` names the resolved
   files), then `relay gate`, then the checker, whose `relay check findings` lists
   exactly the resolved files as `M<n>`; then `relay land` again. Files that only
   the default branch changed, and files git combined by itself, need no new check.
9. **To the owner.** What is NOT MET, new, Disputed, Gap or Outside comes as a
   list of questions, each with its bold title, and a recommendation. Another fix runs on the owner's word
   and is checked the same way (a fix, a gate, a check). After the owner answers a question the cycle left open, run a
   `kind = "fix"` unit: `findings` is the review JSON, `fixes` the earlier fix report and the new one, `fix` the owner's
   answer as the task; when the answer needs no code, the fixer commits nothing and says so, and the gate and the check
   still run and close the queue item. Every change that
   will be merged gets step 4 and a verdict. When the change is ready (the front
   skill's "A change ready to merge": `open 0`, the gate green on the head, the
   default branch taken) the front merges the change and reports it in one line, or shows the person's
   step first in the cases the front skill's "A change ready to merge" lists;
   the merge itself is the front's.

A judge that hands back with "remaining" is continued at once by a fresh
judge with `Remaining: <report>` and the same range, before any triage or
fix; the fix starts only on a complete review. A second "remaining" on the
same review comes to the owner (split the change, or continue once more).

Where findings go:

| What the review found | Where it goes |
|---|---|
| HIGH or MEDIUM inside the change | fixed in this change |
| LOW inside the change | fixed with its group when cheap, else listed in the report and dropped |
| wrong outside the change | a fix item: `relay queue add --from <report.json> F<n> --input <file.toml>` (the TOML holds `why` and `time`) |
| marked `Design:` (the design itself is wrong) | stop building on that part; it stays open and goes to the owner; it counts as open until the owner's answer is kept with `relay check owner <review.json> F<n>` and the checker runs again |
| a feature (a judge's suggestion, an out-of-scope question) | listed for the owner; it counts as open until the owner's answer is kept with `relay check owner <review.json> F<n>` (`queue = "<slug>"` after `relay queue add --input` moves it to the queue), then the checker runs again |
| a question for the owner | the front records it on the item it decides (`relay queue note`, `question`, `options`; no number) and asks it with its introduction; the owner's whole reply is recorded with `answer`, and also kept with `relay check owner <review.json> F<n>` (words), then the checker runs again |

A measurement a design makes and the owner sees becomes a `fact` note on its item (`relay queue note`).

The owner can say a finding is not wrong: keep the word as data, then run the
checker again. Write a TOML file with `words = '''<the owner's words, verbatim>'''`
and run `relay check owner <review.json> F3 --input <file.toml>`: it appends the
words and the date to the `owner` list of that review's JSON, and refuses an id
the review does not have. The checker counts a finding with an owner entry as
not wrong; `relay check show` prints the words under the finding.

When the owner moves a finding (a `Design:` one, say) to a queue item, keep that as
data too: the same TOML with `queue = "<slug>"` beside `words`. The item must be on the
default branch (else nothing is recorded and the finding stays open); the checker
counts such a finding under `queued`, not `open`; the record derives both counts.

Prompts:

> Review the change. Range: `<base>...HEAD` in `<worktree>`. Report: `<path>.json`.

> Check: `<findings file>`. Fixes: `<fixer report>`. Worktree: `<path>`. Check command: `<cmd>`. Gate: `<log>`. Report: `<path>.json`.

This check prompt is the one line, never `Brief: <file>`. Under `relay gate`,
`Gate:` is `<worktree>/.relay/checks/<G>.gate.log`.

The review method (scope, cases, severity, the check of a fix) is the judge
base, carried by every reviewer (relay's copy: `~/relay/roles/judge.md`).
