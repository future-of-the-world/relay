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
| a design, a plan, options with costs, the cause of a hard bug | `delegate:thinker` | the big model where judgment pays; writes one file |
| a review before merge, a design critique | `delegate:critic` | adversarial, read-only, findings with cases |
| the check of a fix against the review's cases | `delegate:checker` | reads the findings, the fixer's report and the gate log; ends with a verdict |

A job longer than about 30 minutes, such as the full paid `bin/ci`, is not a
runner's (its turns end mid-wait): the front starts it in the background (see
the front skill).

Never `general-purpose` (every tool, 30k tokens re-read each request) and
never `fork` from a session over 100k tokens: the routing guard refuses both.
A worker or fixer gets `model: opus` only with a line `Escalated: <reason>` in
its prompt, after a Sonnet agent failed the same brief.

Each agent's model and effort come from the active profile (`relay profile`);
do not set `model:` on a call unless escalating.

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
Check: <command>                                  # the quiet check to loop on
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

One good review, then a checked fix; never a new open review. After a
worker's DONE on a change that will be merged:

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

2. **Build.**
3. **Gate before the review.** Where the project has `.relay/`, a
   `delegate:runner` runs `relay gate` (detached, with the limits recipe: it
   takes minutes) in the worktree, with the project's arguments (relay:
   `relay gate -- --quick`). It runs the free checks on the committed head and
   stores the result as `.relay/checks/<G>.gate.log`. A red gate goes back to
   the worker or a fixer, then this step again: a red build is never reviewed.
   Elsewhere the gate is the project's own command, run by a runner into a
   log whose first line is `head <sha>` and last `exit <code>` (`{ echo "head
   $(git -C <wt> rev-parse HEAD)"; <gate>; echo "exit $?"; } > <log> 2>&1`);
   a remote pipeline gives `Gate: pipeline #<n> on <full sha> passed`; a flow
   with no gate by design (a spec review) passes `Gate: none (artifacts only)`.
4. **One whole-change review.** Every judge the flow names runs once, in one
   message, over `<base>...HEAD`, after a green step 3.
5. **Fix.** One `delegate:fixer` per group of findings; it ends with one of
   four outcomes per finding (Fixed, Disputed, Gap, Outside).
6. **Gate again.** When fix commits exist, a `delegate:runner` runs `relay
   gate` (or the project's gate, as in step 3) on the fixed head, after the
   last fix and before the check. A red gate goes to a fixer, then this step
   again.
7. **Check.** `delegate:checker` on the findings file, the fixer's report and
   the gate log (with `Fixes: none` after a review with nothing inside the
   change; the gate log of step 3 is the gate). Its report is the JSON it
   recorded (`relay check record check`) at the `Report:` path, and where the
   project has `.relay/` a hook commits the check mark and the review and check
   data. Start it with the one-line check prompt below, never `Brief: <file>`:
   the hook reads the `Report:` label and, from that JSON, everything else.
   Then run `relay check show <branch>` (a runner; it waits while the hook is
   committing) before the front commits the handover, so the branch carries
   the state it was merged in and the commit does not meet the hook's lock.
8. **Take the default branch.** When the default branch has moved (the merge
   says "behind"), a runner runs `git -C <wt> merge --no-edit <default>`: a
   merge commit, never `git rebase` (a rebase gives every commit a new sha, and
   the mark names the old one). When code came in, run `relay gate` again. If
   `relay changed --own -C <wt> <checked sha>` lists a file (a conflict, or a
   file both sides changed that git combined), that change is a fix: record a
   findings file (`relay check record review`, `reviewed` = the head before the
   merge) with one finding per file, `<file>:1: MEDIUM: F<n> combined with master's change by the merge`,
   failing case "the gate fails or the merge does not apply", pass-case "the
   gate passes"; a fixer resolves a conflict first (none for a clean
   combination, `Fixes: none`); then `relay gate`, then the checker. Files that
   only the default branch changed need no new check.
9. **To the owner.** What is NOT MET, new, Disputed, Gap or Outside comes as a
   numbered list with a recommendation. Another fix runs on the owner's word
   and is checked the same way (a fix, a gate, a check). Every change that
   will be merged gets step 4 and a verdict. When the verdict is `open 0` the
   front shows the person's step (the front skill's "A change ready to
   merge"); the merge itself is the front's, on the owner's word.

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
| marked `Design:` (the design itself is wrong) | stop building on that part; it stays open and goes to the owner |
| a feature (a judge's suggestion, an out-of-scope question) | listed for the owner |
| a question for the owner | asked with its introduction; the answer is a decision recorded in the design or brief |

The owner can say a finding is not wrong: keep the word as data, then run the
checker again. Write a TOML file with `words = '''<the owner's words, verbatim>'''`
and run `relay check owner <review.json> F3 --input <file.toml>`: it appends the
words and the date to the `owner` list of that review's JSON, and refuses an id
the review does not have. The checker counts a finding with an owner entry as
not wrong; `relay check show` prints the words under the finding.

When the owner moves a finding (a `Design:` one, say) to a queue item, keep that as
data too: the same TOML with `queue = "<slug>"` beside `words`. The item must be on the
default branch (else nothing is recorded and the finding stays open); the checker
counts such a finding under `queued`, not `open`, and `relay check record check`
refuses a `queued` below their number.

Prompts:

> Review the change. Range: `<base>...HEAD` in `<worktree>`. Report: `<path>.json`.

> Check: `<findings file>`. Fixes: `<fixer report>`. Worktree: `<path>`. Check command: `<cmd>`. Gate: `<log>`. Report: `<path>.json`.

This check prompt is the one line, never `Brief: <file>`. Under `relay gate`,
`Gate:` is `<worktree>/.relay/checks/<G>.gate.log`.

The review method (scope, cases, severity, the check of a fix) is the judge
base, carried by every reviewer (relay's copy: `~/relay/roles/judge.md`).
