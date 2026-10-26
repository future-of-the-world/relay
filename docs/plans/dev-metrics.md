Plan: revision 3 of the per-change development metrics design, after its review. Written 2026-10-27. Designs queue item `each-change-records-its-stage-times-cost-and-cov`.
Not built yet: nothing in this file is in the code; it is the design a worker builds from.

Owner's answers, 27 Oct, to section 9: "1. a" and "2. a".

Decided for the build: the counts are computed by relay's code in one function. A change's commits are
`git rev-list --first-parent --no-merges <base>..<head>`, fixed by tests on the real samples of section 2
(ci-python: 4 gates, 4 findings; bench-set: 20 vs 103 min). The measured trap: `git log --first-parent` without
`--no-merges` lists the master files a merge commit brought in, 13 gate logs for ci-python instead of 4.

# Design revision 3 (after its review): per-change development metrics, judged on informativeness, brevity and flexibility

Revision 3, 27 Oct 2026, from revision 2 (the session scratchpad (not kept)) and the owner's decisions in
`docs/handover.md` ("STATE 27 Oct, early morning", addenda 1-4), now revised against its review
(the session scratchpad (not kept), 13 findings: 9 MEDIUM, 4 LOW; all 13 hold and are fixed here,
see 0). Measured on this Mac at master 29146a5, read-only; scratch scripts in the session scratchpad (not kept). Nothing in the repository
changed.

Terms (each defined once; the rest of the text uses them as defined here).
- **Change**: one task branch `wt/<name>` from its first commit to its landing on the default branch.
- **Landing**: the moment the default branch moves to the change's head: `git merge --ff-only wt/<name>`, which the
  merge hook (`plugins/core/hooks/merge.py`) judges and then cleans up after. A **train** (`wt/train-<n>`) lands several
  ready changes at once. `relay land` (owner: "Скрипт вливает сам") prepares a landing; the final fast-forward stays a
  plain Bash merge the hook sees, so everything below that hangs on the landing hangs on that hook.
- **Stage**: one part of a change's life, named by the agent's label: build, gate, review, fix, check, ... (list in 4.2).
- **Label**: the agent's description in the form `<stage>[ N]: <name>[, <name>...]`, e.g. `gate 1: bench-set`.
- **Ledger**: the observe plugin's per-machine log, `$RELAY_HOME/ledger/<day>.jsonl`, one JSON line per hook event.
- **Change record**: what this design adds: one small JSON file per landed change, `.relay/metrics/<name>-<head 8>.json`,
  committed in the project's repository. Non-landing records (question 1) are named in 4.1.
- **Inert probe**: the second, quick run of relay's own gate in a copy of the commit where every record file has a line
  appended; it proves no test reads those files. It runs beside the main run.
- **Changed-lines coverage** (Codecov: "patch coverage"): of the lines the change added or modified, the share the tests
  ran. **Repo coverage**: the same over the whole project.
- **First-parent line** of a change: the commits `git rev-list --first-parent <base>..<head>` lists, i.e. the branch's
  own commits and its "Merge branch 'master' into wt/<name>" commits, without the commits those merges brought in.

## 0. What the review changed

| Finding | Criterion | Holds? | What changed |
|---|---|---|---|
| F1 label refusal blocks hand agents with no change or two changes | flexibility | yes (re-read: 53 hand agents, 2 built-in `claude-code-guide`) | built-in agents pass unlabelled; stage `other` for no-change work; a label may list several names, each record gets the agent with `of` (4.2, 5.5, question 2) |
| F2 off switch does not reach the refusal | simplicity, order | yes | the guard refuses only where `.relay/` exists and `[metrics] record` is true (5.5) |
| F3 Q8 joined through first-parent queue files, which never hold the close | informativeness | yes (re-run: `d31f5ad` not on master's first-parent line) | Q8 joins the queue item by `taken_by == "wt/<name>"`; sample bench-set: estimate 20, real 103 min (2, 3) |
| F4 Q5 counts re-checked findings twice | informativeness | yes (re-read both records) | findings distinct by id across the change's check records, last verdict wins; ci-python 4 (3 MEDIUM, 1 LOW) (1.2, 2) |
| F5 Q11 answer misleading (front cost excluded) | informativeness | yes | Q11 narrowed to agents; "is hand work cheaper per change" moved to the cannot-answer list; per day with the front beside (2) |
| F6 non-landing records have no file name; revisions overwrite | flexibility | yes (this design ran 3 times under one name) | `<kind>-<name>-<UTC start>.json`; the reader never reads meaning from file names (4.1) |
| F7 required keys per kind undefined | flexibility, order | yes | required-key table in 4.4; fixture (2) has no base/head; the reader of step 4 accepts any kind |
| F8 "one value in the `by` list" contradicted by `by` from `workflowPhase` | flexibility | yes | `by` from an explicit launcher signal `RELAY_LAUNCHER`, then `workflowPhase`, then `front`; a harness without Claude Code hooks needs an adapter (4.1, 5.2) |
| F9 a coverage failure can turn the inert step red | simplicity | plausible, accepted | coverage only when it imports; any coverage error or a result difference under coverage falls back to a plain run that alone decides inert (5.3) |
| F10 train `changes` derivable | brevity | yes (train-19: 2 changes, one merged twice) | cut; derived from the train's first-parent merge commits (3) |
| F11 13 gate logs, really 14 | number | yes (re-run: 14) | corrected in 1.2 and 6 |
| F12 stage list built after the hooks that need it | order | yes (`sync-lib-copies` refreshes only copies a plugin already has) | `lib/relay_labels.py` built first, placed in observe, delegate and core (7) |
| F13 probe does not plant in `.relay/metrics/` | order | yes (`lib/relay_ci.py:142-152`) | build step 4 adds the folder to the inert list, the probe's appended lines and planted files |

## 1. Ledger and change record, side by side, with real data

The change shown: **ci-python** (bin/ci ported to Python), landed 26 Oct 21:50:27 +0400 (`master@{2026-10-26 21:50:27}`
in the reflog, "merge wt/ci-python: Fast-forward"). Base `0eae20e` (master when the branch started, 18:37), head
`8bc8f23` (the commit "relay: gate of ff18504", 21:50:03).

### 1.1 What the ledger holds for it (real excerpt, three of its 253 lines)

The ledger has **253 lines, 74,963 bytes** for this change's 9 agents (measured): per agent one `agent_start`, one
`agent_stop`, and a `tool_pre` + `tool_post` pair per tool call (the worker alone made 86 calls: Bash 76, Read 4, Write 4,
StructuredOutput 2). The build worker's start, its first tool call, and its stop, with the session id, the tool id and
the folder replaced (`<session>`, `<id>`, `$RELAY_ROOT` = the main checkout); the review re-read them against the ledger:

```json
{"ts": "2026-10-26T14:38:08.868Z", "event": "agent_start", "session_id": "<session>", "cwd": "$RELAY_ROOT", "agent_id": "a8f49a57a2353f943", "agent_type": "delegate:worker", "prompt_chars": 0, "input_keys": ["agent_id", "agent_type", "cwd", "hook_event_name", "prompt_id", "scratchpad_dir", "session_id", "transcript_path"]}
{"ts": "2026-10-26T14:38:16.408Z", "event": "tool_pre", "session_id": "<session>", "cwd": "$RELAY_ROOT", "agent_id": "a8f49a57a2353f943", "agent_type": "delegate:worker", "effort": "medium", "tool": "Read", "tool_use_id": "<id>"}
{"ts": "2026-10-26T15:10:09.434Z", "event": "agent_stop", "session_id": "<session>", "cwd": "$RELAY_ROOT", "agent_id": "a8f49a57a2353f943", "agent_type": "delegate:worker", "effort": "medium", "requests": 42, "context": 131681, "model": "claude-sonnet-5-5", "cost_est": 1.3548, "reply_chars": null}
```

What these lines **do not** say: which change the agent worked for (no label: the `cwd` is the main checkout although
the worker edited `.worktrees/ci-python` through `git -C`), the tokens by kind (only a dollar estimate), and anything
about gates, findings or the landing. To learn that the worker above built ci-python one must open Claude Code's own
file `agent-a8f49a57a2353f943.meta.json`, which holds `"description": "build: ci-python"`.

### 1.2 The change record revision 3 writes for the same change (hand-built)

Built by hand from the ledger, the 9 agents' transcripts (token counts through `lib/relay_transcripts.py`) and their
meta files; git gave base and head. Written one agent per line, which is how the writer will format it:

```json
{"schema": 1, "kind": "change", "name": "ci-python", "base": "0eae20e5af63f768156608b343d3de02495c6062", "head": "8bc8f2357296f8e9e97d1876e453973ca4d8493a", "agents": [
{"stage": "build", "model": "claude-sonnet-5-5", "start": "2026-10-26T14:38:08Z", "seconds": 1921, "requests": 42, "tokens": {"input": 84, "output": 63539, "cache_read": 4066275, "cache_write_5m": 125030}},
{"stage": "gate", "model": "claude-haiku-5-5", "start": "2026-10-26T15:10:14Z", "seconds": 1055, "requests": 8, "tokens": {"input": 16, "output": 2838, "cache_read": 112495, "cache_write_5m": 13219}},
{"stage": "review", "model": "claude-opus-5-5", "start": "2026-10-26T15:27:52Z", "seconds": 450, "requests": 24, "tokens": {"input": 48, "output": 36080, "cache_read": 1503567, "cache_write_5m": 98810}},
{"stage": "fix", "model": "claude-sonnet-5-5", "start": "2026-10-26T15:35:25Z", "seconds": 755, "requests": 10, "tokens": {"input": 20, "output": 10704, "cache_read": 385395, "cache_write_5m": 47534}},
{"stage": "gate", "model": "claude-haiku-5-5", "start": "2026-10-26T15:48:06Z", "seconds": 1036, "requests": 8, "tokens": {"input": 16, "output": 2763, "cache_read": 111642, "cache_write_5m": 13031}},
{"stage": "check", "model": "claude-sonnet-5-5", "start": "2026-10-26T16:05:26Z", "seconds": 48, "requests": 5, "tokens": {"input": 10, "output": 2231, "cache_read": 89835, "cache_write_5m": 26062}},
{"stage": "check show", "model": "claude-haiku-5-5", "start": "2026-10-26T16:06:18Z", "seconds": 15, "requests": 2, "tokens": {"input": 4, "output": 418, "cache_read": 13499, "cache_write_5m": 14647}},
{"stage": "fix conflict", "model": "claude-sonnet-5-5", "start": "2026-10-26T17:07:21Z", "seconds": 636, "requests": 10, "tokens": {"input": 20, "output": 3081, "cache_read": 267843, "cache_write_5m": 34623}, "by": "front"},
{"stage": "check", "model": "claude-sonnet-5-5", "start": "2026-10-26T17:33:32Z", "seconds": 102, "requests": 5, "tokens": {"input": 10, "output": 2801, "cache_read": 95523, "cache_write_5m": 28716}, "by": "front"}
]}
```

**1,841 bytes** compact (measured on `ci-python.r3.json`), 2.5% of the ledger's 74,963 bytes for the same 9 agents.

Two live facts this hand-build turned up, both changing the design:
- **The last two agents were started by the front by hand** with free-text descriptions ("Resolve ci-python merge
  conflict", "Check ci-python after conflict merge"). Revision 2's label rule (`<stage>: <change>` or nothing) would
  have **dropped them**: 2 of 9 agents, $0.25 of $3.50 (7.3%) of this change. Across the session at measurement time:
  **0 of 52 hand-started agents** carry a label, $13.72 of $241.86 (5.7%); 802 of 802 workflow agents do (the review
  re-counted later: 0 of 53 and 804 of 804). The record above shows them as revision 3 would label them (question 2),
  marked `"by": "front"`.
- **Revision 2's gate rule over-counts.** It said "gate logs in the range base..head"; `git diff 0eae20e 8bc8f23` names
  **14** gate logs, because the two "Merge branch 'master' into wt/ci-python" commits bring in the gate logs of changes
  that landed meanwhile (relay-home, gate-lock). The change's own gates are the **4** gate logs added by commits on its
  first-parent line (11 commits). Revision 3 derives every git fact from the first-parent line.

What the record does **not** hold, because git already has it (all read when the record is read):

| Fact for ci-python | Value (measured) | From |
|---|---|---|
| Landing time | 26 Oct 21:50:27 | the record's own commit time (written seconds after the landing) |
| Gates | 4, all green; library tests 840 / 836 / 688 / 635 s | the 4 gate logs on the first-parent line |
| Rounds | 2 check runs; **4 distinct findings** (F1 MEDIUM, F2 LOW from the review, re-checked in run 2; M1, M2 MEDIUM from the merge, new in run 2): 3 MEDIUM, 1 LOW, all MET | `.check.json` records with `"branch": "wt/ci-python"`, findings keyed by id, the last verdict wins |
| Coverage | not measured (nothing measures it yet) | the last green gate log's coverage line (5.3) |
| Cost per stage | build $1.35, review $1.52, fix $0.26, check $0.21, fix conflict $0.14, gates $0.01, check show $0.00; total $3.50 | tokens x `prices.toml`, at reading |
| Queue item, estimate | none: no queue item has `"taken_by": "wt/ci-python"` | the queue item joined by `taken_by` (Q8) |

### 1.3 Properties, side by side

| Property | Ledger | Change record |
|---|---|---|
| Who writes it | observe's hook (`plugins/observe/hooks/ledger.py`) | core's merge hook through `lib/relay_metrics.py`, the one writer |
| When | at every hook event of every session: 47,818 tool events, 1,461 agent starts, 4,589 agent stops in 6 days | once per change, at its landing (and by `relay metrics backfill` when that failed) |
| Where | `$RELAY_HOME/ledger/<day>.jsonl` | `$RELAY_ROOT/.relay/metrics/<name>-<head 8>.json` |
| In git | no | yes, inert (no gate reruns because of it; the probe proves it, 7 step 4) |
| Scope | one machine; all projects mixed (relay 11.7 of 16.6 MB, then alix, blogger, sorm-adapter) | one project, one change |
| Size | 16.6 MB in 6 days, **2.8 MB a day**; 75 KB for ci-python (measured) | **1.8 KB** for ci-python (measured); about 19 changes and trains a day (65 in 24-27 Oct) = about 35 KB a day (estimate) |
| Kept | until someone deletes it: no code removes ledger files (searched `ledger.py`, `relay_ledger.py`); oldest file 21 Oct | as long as the repository: every clone has it |
| Privacy | session ids, absolute folders, tool names, prompt sizes; prompt text when a project turns `log_prompts` on | stage names from a fixed list, change names, model ids, commit shas, UTC times, integers; no paths, ids or text (5.6) |
| What reads it | the usage and tune views; at landing, the merge hook (to copy this change's agents); `relay metrics` in a project without `.relay/` | `relay metrics` (per change, trend, turning point, `--all`) on any machine with a clone |
| Lost if deleted | the machine's per-session and per-tool detail; records already written keep their numbers; a change not landed yet gets `"agents": null` | that change's time and cost per stage, for good (the ledger is on one machine); gates, rounds and coverage survive in the gate logs and check records |

In one sentence, in the owner's words: "ledger является источником данных для metric, позволяющий записать её лишь
однажды, данные аккумулируются в ledger". **The ledger is the raw tape of everything on one Mac, kept accumulating; the
change record is a 2 KB extract of the part of that tape that belongs to one change, written once at the landing and
kept with the code it describes.** The record's only new information, beyond what git already has, is the agents (who
worked on the change, how long, with which model, at which token cost) and the change's range (base, head), which is
lost when the branch is deleted.

### 1.4 The flow

```
 Claude Code hook events (every session, every project on this Mac)
   agent start / stop, tool pre / post, prompt, stop, session start / end
        |  one JSON line each                         (observe plugin)
        v
 $RELAY_HOME/ledger/<day>.jsonl   machine-local, all projects mixed, 2.8 MB/day, not in git, accumulates
        |  new: agent_stop also carries stage, names, by, tokens by kind (5.2)
        |
        |      relay gate  --> .relay/checks/<sha>.gate.log    in git: steps, started, took, others, coverage
        |      relay check --> .relay/checks/<sha>.check.json  in git: findings, verdicts
        |      relay queue --> .relay/queue/**                 in git: found_at, taken_at, taken_by, closed_at, time
        v
 landing: git merge --ff-only wt/<name>   (merge hook, after the merge, before the branch is deleted)
        |  picks this project's agents labelled <name> since the previous record of <name>   (written ONCE)
        v
 .relay/metrics/<name>-<head 8>.json   in git, ~1.8 KB: base, head, agents (nothing else)
        |
        v  relay metrics   (read-only; computed every time, nothing stored)
 per-change table | trend + turning point | gate steps over time | --all projects
   = record agents + gate logs + check records + queue items + git times + prices.toml
```

## 2. Informativeness: the questions the metrics answer

Sample answers are computed from this session's data where possible (scripts in the session scratchpad (not kept)); "not measured"
where the data does not exist yet.

| # | Question | Who asks, when | Answered by | Sample answer (real data) |
|---|---|---|---|---|
| Q1 | How long did each stage of a change take? (owner) | owner, front: after a slow day, when tuning the cycle | record `start`, `seconds` per agent; gate wall time from gate logs (`started`, `took`) | ci-python: build 32.0 min, gate runs 17.6 + 17.3, review 7.5, fix 12.6, check 0.8, check show 0.25, fix conflict 10.6, check 1.7; two more gates the front ran without an agent (about 15 and 14 min, from commit times) |
| Q2 | What did each stage cost in model use? (owner) | owner, tune skill: before a profile change | record `tokens` + `model` x `prices.toml`; an agent with `of: n` counts 1/n per change | ci-python: review $1.52 (43%), build $1.35 (39%), fix $0.26, check $0.21, fix conflict $0.14, gates $0.01; total $3.50. Session, all agents: review 27.3%, build 19.7%, design 10.8%, fix 9.8%, design review 8.6%, design revise 8.0%, gate 0.4% of $241.86 |
| Q3 | What share of the code, and of the change's own lines, do tests run? (owner) | owner, critic: at review and at landing | last green gate's coverage line (counts) | not measured (no coverage yet) |
| Q4 | How long does a gate take, step by step, and how much of it is machine sharing? | front, a thinker on gate speed | gate logs: step seconds, `took`, `others` | library tests in ci-python's 4 gates: 840, 836, 688, 635 s; `others` not measured yet (no such line) |
| Q5 | How many find-and-fix rounds did a change need, with what findings? | owner, critic: is review catching things early | `.check.json` with `branch` = the change; runs counted per record, findings **distinct by id** across the records (the last verdict wins) | ci-python: 2 check runs, 4 distinct findings (3 MEDIUM, 1 LOW), 2 of them new in run 2 (M1, M2 from the merge), all MET. Across 89 branches: 1 run in 21, 2 in 43, 3 in 17, 4 in 6, 5 in 2 (revision 2) |
| Q6 | How many gates went red and how many fixer runs did that take? | front: is the quiet check good enough | gate logs on the first-parent line (`exit 1`) + agents with stage `fix red gate` | ci-python: 0 of 4 red. Session: 12 `fix red gate` + 4 `fix red gate after fix` agents, $1.92 |
| Q7 | Where did a change wait: idle gaps, wait to land, total cycle? | owner: why did this take 3 hours | record `start` + `seconds` and the landing time (record commit) | ci-python: cycle 192 min (build start 18:38 to landing 21:50); agents 100 min; **61 min with no agent at all** (16:06-17:07 UTC: the front was landing gate-lock and relay-home, then the conflict); last agent to landing 15 min (one gate) |
| Q8 | Was the queue item's estimate right? | owner, front: when ordering the queue | the queue item with `taken_by == "wt/<name>"`: `time` (the estimate, agent minutes) against `taken_at..closed_at` and the record's agent minutes | **bench-set** (item a-bench-with-set-leaves-the-main-checkout-dirty): estimate 20 min; taken 19:45:14 to closed 21:28:31 UTC = 103 min; its 9 agents ran 103.6 agent minutes (build alone 52), $1.52: **5.2x the estimate**. ci-python: "no queue item". 69 of 93 closed items carry `taken_by` (measured) |
| Q9 | Did a metric degrade, and which change started it? | owner, front: daily | series of Q1-Q4 per change, detect + locate (5.8) | real series too short today (6 of the last 40 landings have a gate log as head: library tests 565, 418, 414, 614, 591, 635 s); on synthetic series the rule located the cause in all 4 review cases (revision 2, 2.11) |
| Q10 | Which model tier did each stage use, and did escalation pay? | tune skill, owner | record `stage` + `model` | ci-python: review on Opus, build/fix/check on Sonnet, gates and check show on Haiku; no escalation |
| Q11 | What do hand-started agents cost against workflow agents? | owner (the scripts move got IP 96 on this) | record `by` per agent (agents only; the front's own tokens are not in it) | session: 52 hand agents $13.72 vs 802 workflow agents $227.95. This is **not** "is hand work cheaper per change": see the list below |
| Q12 | What did work that never lands cost (designs, analyses, experiments)? | owner: is design time well spent | records of kind `design` / `analysis` / `experiment` (question 1), else the ledger view | session: design stages $66.31 + hand thinker/critic $10.92 = **$77.23, 31.9% of agent spend**, none of it in any change record under revision 2 |
| Q13 | How do projects compare? | owner | `relay metrics --all` over `projects.toml` | not measured (only relay has `.relay/`) |
| Q14 | How many agents carry no label, so are missing from records? | front, the critic of this design | ledger, per project per day (not per change) | session: 52 of 854 agents (6.1%), all hand-started |
| Q15 | What does the front itself cost per day, beside its agents? | owner | ledger `session_usage` (per session, per model, 83 events) next to the day's agents by `by` | not measured here; whether `session_usage` already includes the session's agents is not measured either, and the build checks it before showing both side by side |
| Q16 | Why did a stage cost what it cost: many requests or a large context? | tune skill | record `requests` + `tokens` (context per request = input + cache read + cache write over requests) | ci-python build: 42 requests, about 100k tokens re-read per request; review: 24 requests, about 67k |

**Questions the design cannot answer, and that matter:**
- **Is hand work cheaper per change than a workflow change?** The front's own tokens carry no change label (6.2), so a
  change the front does mostly itself shows almost no agent cost and reads as cheap, the opposite of the 24 Oct
  measurement (165k agent tokens by workflow vs 236-277k by hand, counting the front). Only a per-day comparison is
  honest: Q11's agents by `by` and Q15's front cost on the same day, both shown. A per-change answer needs the front to
  work under a change label, which no tool gives today.
- **Did a change cause a later defect?** (DORA's "change failure rate".) A fix item found later names a file or a
  behaviour, not the change that broke it; linking them needs judgment. The reader can at most list fix items found
  within N days after a change that touch its files, which is a hint, not an answer.
- **How long did a change wait for the owner?** An owner answer is a prompt in the front's session, not tied to a change.
  Q7 shows the gap but not its cause (in ci-python's 61 minutes, the cause was other landings, not the owner).
- **Agents that ran on another machine**: the record holds the landing machine's ledger only. One Mac today, so no loss yet.
- **Why** a review found what it found: numbers only, by design (privacy).

## 3. Brevity: every field earns its place

The rule, in the owner's words: "краткость сегодня, возможность расширения в будущем, это не противоречие а дизайн":
store only what answers a question today; add later through the format version (4.4). "Derivable" means git, the queue,
`.relay/checks`, the ledger at landing or `prices.toml` already holds it (principle 3).

| Field | Serves | Kept? | Why |
|---|---|---|---|
| `schema` | versioning (4.4) | kept | the reader picks its parser by it |
| `kind` | Q11, Q12, reader layout | kept | `change` / `train` / (question 1) `design` / `analysis` / `experiment`; parsing a name prefix like `train-` would be a guess |
| `name` | every question | kept | the branch is deleted at landing; non-landing kinds have no branch |
| `base` | Q3, Q4, Q5, Q6 (the first-parent line) | kept, change and train only | not derivable after landing: a fast-forward leaves master's line identical to the branch's, so where the branch started is lost |
| `head` | the same | kept, change and train only | derivable from the record commit's parent only for a record written at landing; a backfilled or train record sits elsewhere |
| `landed_at` (backfill only) | Q7 | kept, backfill only | otherwise the record's commit time is the landing time |
| agent `stage` | Q1, Q2, Q6, Q10 | kept | from the label; nothing else says what an agent did |
| agent `model` | Q2, Q10 | kept | prices differ 5x between tiers |
| agent `start` | Q7 | kept | idle gaps need when, not only how long |
| agent `seconds` | Q1, Q7 | kept | |
| agent `requests` | Q16 | kept | the owner's cost model is requests times context |
| agent `tokens.input`, `.output`, `.cache_read`, `.cache_write_5m` | Q2, Q16 | kept, **a key is left out when 0** | needed to reprice exactly |
| agent `tokens.cache_write_1h`, `.early_cache_read` | Q2 (exact price) | kept, **left out when 0** | 0 in 854 of 854 agents (measured), so 0 bytes today; a 1-hour write costs 1.6x a 5-minute one, so it stays possible |
| agent `by` | Q11, Q14 | kept, **only when not `script`** | absent = started by a workflow script |
| agent `of` | Q1, Q2 totals | kept, **only when the label names more than one change** | the agent sits in each named change's record; `of: 2` lets the reader count it once in any sum (no agent id is stored, so it cannot be de-duplicated otherwise). 1 of 53 hand agents this session ("Gate two ready changes") |
| `changes` (train, revision 3 first draft) | none | **cut** (review F10) | derived from the train's first-parent merge commits: train-19's line holds "Merge branch 'wt/leaked-gate'" twice and "Merge branch 'wt/front-cd'" once, read as 2 changes |
| agent `role` (revision 2) | none | **cut** | stage plus model answer Q2 and Q10; an escalated worker shows as `build` on an Opus model |
| `tokens.output_estimated` (revision 2) | none | **cut** | true in 854 of 854 agents (measured): the flag carries no information; the reader states once that agent output counts are estimates |
| gates, red gates, step seconds, coverage | Q3, Q4, Q6, Q9 | not stored | gate logs on the first-parent line |
| rounds and findings | Q5 | not stored | `.check.json`, findings keyed by id |
| dollars | Q2 | not stored | tokens x `prices.toml` (a stored dollar figure freezes an old price) |
| landing time, cycle time, wait | Q7 | not stored | record commit time and agent times |
| queue item, estimate, taken and closed times | Q8 | not stored | the queue item whose `taken_by` is `wt/<name>` (its close commit is a `queue: done` commit on master, outside the branch, so the join is by field, not by git range) |
| agent effort, context, tool counts | none of Q1-Q16 | not stored | the ledger has them on the machine for the tune skill |

Size per change, measured on ci-python (`build_rec.py`); the review's fixes add nothing to it (one change, no `of`, no
train):

| Shape | Agents | Bytes (compact) | Per agent |
|---|---|---|---|
| revision 2 (role, seven token fields, the flag) | 7 (the 2 hand agents dropped) | 2,004 | 264 |
| revision 3, the same 7 agents | 7 | 1,442 (**-28%**) | 187 |
| revision 3, all agents | 9 | 1,841 | 187 |

Records are written only where they answer something: a landing whose first-parent line holds **no gate log and no
labelled agent** gets no record. In 24-27 Oct that leaves out 232 `relay queue` landings (queue items: their own commit
dates them) and 23 handover changes (none of 24 handover landings checked has a gate log on its first-parent line), and
keeps 50 changes and 15 trains (measured from the reflog). The test that fails when this is false: a temporary
repository lands a branch holding one docs commit and no gate log, and `.relay/metrics/` stays empty; the same
repository lands a branch with one gate log and gets one record.

## 4. Flexibility: how the format takes what comes next

The design rule that makes this work: **closed lists in the writer, open reading in the reader.** The writer refuses a
value not in its list (a typo is caught where it is made); the reader shows any value under its own name and never
drops a record for an unknown value. The lists (stages, kinds, `by` values) and the label parser live in one small
module, `lib/relay_labels.py`, copied into observe, delegate and core (7, step 1). So most additions are one new value
in one list, no reader change, and old records stay as they are. The reader never reads meaning from a file name: it
lists `.relay/metrics/*.json` and goes by each record's content.

### 4.1 New ways of making a change

| Way | Seen 24-27 Oct (measured) | What is written | What the reader shows | Code change |
|---|---|---|---|---|
| Workflow-script change (units `change`, `built`, `fix`, `recheck` of the scripts design) | 50 changes | `kind: change`, agents labelled by the script | one row per change | none |
| Hand change by the front | 52 hand agents, 0 labelled; ci-python had 2 | the same record; hand agents carry `"by": "front"` once labelled (question 2) | the same row; Q11 splits by `by` | the label check at agent start (question 2), once |
| Train | 15 | `kind: train` (name, base, head, the train's own agents), and one `kind: change` record per change in it, holding that change's own agents; all in one commit | a train row with its changes listed under it, read from its merge commits | none |
| An agent serving two changes (e.g. one gate for two ready changes) | 1 of 53 hand agents | the agent in each named change's record with `of: 2` | counted once in every sum | none beyond the label form |
| `relay queue land` (queue-only) | 232 | nothing | a count per day from `queue:` commits, if ever asked | none |
| Handover or docs change, no gate, no labelled agent | 23 | nothing (rule of section 3) | not listed | none |
| Design-only run | 5 design-only runs, 10 designs; 31.9% of agent spend with design and hand thinkers | question 1 a: `kind: design`, `name`, agents; no `base`/`head`; written at the run's end by the workflow script through `relay metrics record`, file `design-<name>-<UTC start, e.g. 20261026T2303Z>.json`, so revisions 1, 2 and 3 of this design are three files, never one overwritten | a "did not land" row; runs of one name summed under it | `design` in the kind list + one call in the script's end stage |
| Analysis or experiment run (owner: the workflow script is "базовая единица запуска, в том числе для экспериментов и анализа") | 5 hand analyses; experiment kind proposed in the scripts design | `kind: analysis` / `experiment`, the same shape and naming | the same "did not land" row | one value each in the kind list |
| A Claude Code launcher that does not exist yet (example: a headless `claude -p` job relay starts) | 0 | the same record; the launcher sets `RELAY_LAUNCHER=<value>` in the job's environment, the ledger hook (a child of that Claude Code) copies it into `by` | shown under the new `by` value | one value in the `by` list, and the launcher sets one variable |
| Another harness without Claude Code hooks (example: pi) | 0 | `"agents": null` until an adapter writes ledger lines of the same shape (`agent_stop` with stage, names, by, model, tokens) | "agents not recorded" for that change; git-derived numbers still shown | an adapter for that harness (not measured; size unknown until such a harness is used) |

Two parts of revision 2 would have blocked the last rows and were changed: the model check `^claude-[a-z0-9.-]+$` (a
non-Claude model would be refused) becomes `^[a-z0-9][a-z0-9.-]{0,63}$`, and a model without a price shows tokens and
"price unknown"; and the stage is no longer parsed out of free text with a pattern that silently drops what does not
match (4.2).

### 4.2 A new stage, role, model, metric, or test tool

- **A new stage.** One list in `lib/relay_labels.py`: design, design review, design revise, analysis, measure, build,
  gate, fix red gate, fix red gate after fix, review, fix, fix conflict, check, check queue item, close queue item, check
  show, land, and **`other`** for work with no fitting stage (a lookup, a proof script, a queue repair). Revision 2's list
  lacked `fix red gate after fix` (4 agents this session), `fix conflict` (ci-python), `analysis`, `measure` and `land`;
  that is the cost of a closed list read silently. Revision 3 checks the label **when the agent is started** (question 2),
  so an unknown stage is refused with one line naming the list, at the moment the label is typed, instead of being lost
  at landing. The workflow script's own test fails when it uses a stage outside the list (scripts design 3.1). Adding a
  stage: one value in the list; old records untouched; the reader shows it as a new column.
- **The name part.** One change name, several separated by commas (`gate: leaked-gate, front-cd`), or, for work that
  serves no change, the job's own short name (`other: queue-records`); such an agent never meets a landing, so it is
  counted in the ledger view per day, or in a non-landing record under question 1 a.
- **A new role.** Nothing: the record does not store roles.
- **A new model.** Nothing in the record; one price line in `prices.toml` for dollars; without it the reader shows tokens
  and "price unknown", never $0.
- **A new metric about the code** (example: lint warnings). The gate writes one more line into its log
  (`lint warnings 12`); the reader derives it per change from the last green gate on the first-parent line. The record does
  not change. Rule: what the gate measures lives in the gate log; only what agents do lives in the record.
- **A new metric about agents** (example: tool calls per agent). A new optional key under `agents`; old records lack it and
  the reader shows "-". No schema bump (4.4). Records written before it can be backfilled from the ledger, which keeps
  every tool event, as long as the ledger file of that day exists.
- **Another project's test tool and coverage format.** One setting names the report path (5.3). The format is told from
  the file's first bytes (`TN:` or `SF:` for LCOV, `<?xml` and `<coverage` for Cobertura): an exact fact, so code decides
  (principle 5). A third format (JaCoCo XML for Java, Go's own cover profile) is one more parser function in one table
  keyed by that detection; the gate log line names the format it read.

### 4.3 What stays fixed

The join key (this project's folders, the label's names, the time since the previous record of the same name), the
first-parent rule for git facts, and "unknown is `null`, never 0" (`"agents": null` where the ledger has none; no
coverage line where coverage was not measured).

### 4.4 Versioning

Required keys of a schema-1 record, by kind (the reader of build step 4 checks exactly this table, so it accepts a kind
added later without a change):

| Kind | Required | Optional |
|---|---|---|
| every kind, including one the reader does not know | `schema`, `kind`, `name`, `agents` (a list or `null`) | any key the reader does not know (ignored) |
| `change`, `train` | also `base`, `head` | `landed_at` (backfill) |
| every agent | `stage`, `model`, `start`, `seconds`, `requests`, `tokens` | `by`, `of`, any unknown key |

- **Additive changes do not bump `schema`**: a new optional key, a new value in `kind`, `stage` or `by`. A reader that does
  not know a key ignores it; one that does not know a value shows it by name.
- **A breaking change bumps `schema`** (a key renamed, a unit or meaning changed). The reader keeps one small upgrade
  function per old version (`v1 -> v2`, applied in memory); old files are never rewritten.
- **A record newer than the reader** (`schema` above what it knows) is skipped with one line: `1 record from a newer
  relay skipped (schema 2): update relay`. Never a crash, never a guess.
- **A record that breaks the table above** (a missing `name`, a `change` without `base`, a negative count) is named and
  skipped; the writer refuses to write one.
- The test that proves it: five fixture records in a temporary folder: (1) a plain v1 change record; (2) a v1 record of
  kind `experiment` with no `base` and no `head`, an unknown key `lint` and a stage `lint fix`; (3) a `schema: 2` record;
  (4) a v1 record with `"seconds": -5`; (5) a v1 `change` record with no `base`. `relay metrics` prints a row for (1)
  and a "did not land" row for (2) with `lint fix` and `experiment` shown by name, prints the "newer relay" line for (3),
  names (4) and (5) as invalid; exit 0 in all. The writer refuses (2) (unknown key and stage), (4) and (5).

## 5. The rest of the design, updated to the owner's decisions

### 5.1 Where and when the record is written (approach A of revision 2, kept)

The merge hook writes the record right after a landing succeeds (`merge.py` `post`) and before `clean()` deletes the
branch and the worktree: it reads the ledger with the join key, takes base and head from git, writes
`.relay/metrics/<name>-<head 8>.json` and commits it on the default branch as `relay: metrics of wt/<name>` (the way
`relay queue` lands an item file). `relay land` changes nothing here: it prepares; the final fast-forward is still the
Bash merge the hook sees. A train writes its record and one per change in that one commit. If the write fails, the
landing stands (the hook fails open), `relay metrics` lists the change as "landed, no record", and `relay metrics
backfill <name>` writes it later from the same sources while the ledger and the reflog still have them.
Revision 2's alternatives stay rejected for the reasons it measured: B (each command appends on the branch) needs many
writers and an agent hook that runs in the session folder, not the worktree; C (a nightly digest) shows a degradation a
day late and depends on the local reflog.

### 5.2 The ledger hook copies the label, the launcher and the tokens (observe plugin)

At agent stop the hook already opens the agent's transcript; it also reads `agent-<id>.meta.json` beside it (about 300
bytes) and adds to the `agent_stop` line:
- `stage` and `names` when the description is a label with a stage from the list (anything else adds nothing; the
  description itself is never copied);
- `by`, in this order: the value of `RELAY_LAUNCHER` when set and in the `by` list; else `script` when the meta file has
  a `workflowPhase` (828 of 1,096 meta files on this Mac have one); else `front`. Claude Code's own
  `CLAUDE_CODE_ENTRYPOINT` (here `cli`) is not used: what it reads for a `claude -p` job is not measured, and one
  signal relay sets itself is simpler than mapping another tool's values;
- the token counts in the six fields of section 3.

The tests: hook input with `RELAY_LAUNCHER=headless` and no `workflowPhase` gives `by: headless`; a meta file with
`workflowPhase` gives `script`; neither gives `front`; an unknown `RELAY_LAUNCHER` value gives `front` and one stderr line.
This is all that changes in observe.

### 5.3 Coverage: the project's own report, read on every gate (owner: "Замеряем метрики на каждом gate", format "a")

- **Setting** in the project's `kit.toml`: `[metrics] coverage_report = "<path>"`, the file the project's own test tool
  writes (LCOV or Cobertura: coverage.py `coverage xml` or `coverage lcov`, Jest / c8 / istanbul `--reporters=lcov`,
  `cargo llvm-cov --lcov`, Go through a converter). Default: none, and the change reads "coverage: not measured".
- **After the project's test step**, relay's gate reads the report only if it was written after the gate started (a
  stale report from an earlier run is never read: case, a report dated before the gate's `started` line gives no
  coverage line), parses it with the standard library (`xml.etree`, plain text for LCOV), and computes changed-lines
  coverage against `git diff -U0 $(git merge-base <default> HEAD) HEAD`.
- **Stored plain, in the gate log** (principle 4: numbers plain, shown readably):
  `coverage cobertura lines 4190 6828 changed 34 40`. The reader prints "repo 61.4%, changed 85.0% (34 of 40)". A gate
  with no line reads "not measured", never 0%.
- **Relay's own gate**: the inert probe runs the library tests under coverage.py 7.11.0 (pinned in `deps.toml`, built on
  the gate's own `python3`, child processes measured through `[run] patch = subprocess`), then `coverage combine` and
  `coverage xml` into a file outside the worktree; the same reader then reads it. coverage.py is only relay's own producer
  (owner: "coverage.py не общее для всех ... мы должны иметь способ динамически получать его для разных проектов").
- **Coverage never decides the inert verdict.** The probe's job (`lib/relay_ci.py:17-21`) is to fail `inert` when a
  step's result or test count differs from the main run. So: (1) the probe runs under coverage only when `import
  coverage` works in the gate's `python3`; else it runs plainly and writes no coverage line; (2) when coverage itself
  fails (combine or xml exits non-zero, no data), the probe's verdict stands and no coverage line is written; (3) when
  the probe's result differs from the main run under coverage, the probe runs the differing step once more without
  coverage, and that plain result alone decides inert; a test that fails only under coverage is a slow-sensitive test,
  a fix item (principle 6), not an inert failure. The tests: coverage not importable, outer and probe agree: inert ok,
  no coverage line; coverage working: inert ok, a coverage line; a planted test that reads an inert file: inert FAIL, as
  today. Cost of (3): one extra step run, only on a difference (not measured how often; 0 expected).
- **The report must not sit in the worktree unignored**: the gate refuses a worktree that changed while it ran
  (`lib/relay_gate.py:306-308`). `relay doctor` names a `coverage_report` path that is inside the worktree and not
  ignored (`git check-ignore`).
- **Off**: `RELAY_COVERAGE=off` skips reading the report and the probe's coverage run.
- **Cost** (revision 2's estimate, not measured on a whole gate): +30-100 s per gate in relay's probe. ci-python ran 4
  gates: +2-7 min on a 192-minute cycle (1-3.5%). The build measures one gate with and without coverage on an idle Mac.

### 5.4 Gate log lines

`started <UTC>`, `took <seconds>`, `others <at start> <at end>` (gate slots held by other gates when this one took its
slot and when it finished; one non-waiting sweep over the machine's slot files each time), the coverage line; all
written before `exit`, which stays the last line (`reusable()` and `relay_marks.gate_logs` read lines 1, 2 and the last).
About 60-110 bytes per gate.

### 5.5 Settings and the off switch

| Setting | Where | Default | Bound | At the bound |
|---|---|---|---|---|
| `[metrics] record` | project `kit.toml`, written by `relay setup --off metrics` | true | true / false | false: no record is written **and the label check is off**; gate log lines and the ledger labels stay (they are facts other views use) |
| `[metrics] coverage_report` | project `kit.toml` | none | a path | none: "coverage: not measured" |
| `RELAY_COVERAGE` | environment | on | on / off | off: no coverage line; an unmeasured gate log may be reused for a measured one, so one change may read "not measured" |
| `window` W | `relay metrics` argument | 10 changes | 3-50 | 3: one contended gate is flagged; 50: a turn is flagged after about 25 changes (1-2 days) |
| `threshold` T | the same | 25% | 10-100% | 10%: machine sharing alone (+14-30%, measured 26 Oct) flags nearly every change; 100%: only a doubling |
| `run` R | the same | 3 | 1-W | 1: a single slow change just before the real cause is named; W: the locator names nothing unless the new level holds for a whole window |
| label check at agent start | delegate plugin's route guard | refuse (question 2), **only in a project with `.relay/` and `[metrics] record` true, and only for relay's typed agents** (`delegate:*`); built-in agents such as `claude-code-guide` and every agent elsewhere pass and are only counted per day | refuse / warn | warn: unlabelled hand agents are only counted per day (Q14), and lost from records |

The guard reads `[metrics] record` through `relay_config.py`, which `plugins/delegate/lib` already carries. Its tests:
(1) `record = false`, a `delegate:fixer` described "Resolve merge conflict": allowed, no line; (2) `record = true` in a
project with `.relay/`, the same call: refused with one line naming the form and the stage list; (3) a project with no
`.relay/`: allowed; (4) `claude-code-guide` described "Claude Code config lookup rules": allowed; (5) `delegate:runner`
described "gate: ci-python": allowed, and its `agent_stop` carries stage `gate`, names `ci-python`.

### 5.6 Privacy and Glonass (kept from revision 2)

Into git only: stage names and `by` values from fixed lists, change names, model ids (the pattern of 4.1), commit shas,
UTC times, integers. Never prompt text, descriptions, transcript text, folder paths, session or agent ids. The writer
builds the record field by field from the typed ledger record and never copies a line. The test that fails when this is
false: a planted ledger with a prompt line "SECRET-PROMPT", a free-text description "SECRET-LABEL", a `cwd` of
`/Users/x/secret-dir`, a session id `sess-SECRET`; the record must contain none of the four strings, no absolute path,
and no key outside the schema. A repository whose remote is on `gitlab.aoglonass.ru` gets no record in git (the Glonass
rule bans Claude authorship credit there); its `relay metrics` reads the ledger only.

### 5.7 Projects with observe but without `.relay/` (owner: "метрики становятся частью стандартного пакета relay")

`relay metrics` there reads the ledger on this machine for agents whose folder is under the project, grouped by label
name: time and cost per stage per name (Q1, Q2, Q10, Q11, Q16), nothing in git, no gates, rounds or coverage, and no
label refusal (5.5). The records' writer lives in the standard relay package (core): `relay_metrics.py`,
`relay_labels.py`, `relay_ledger.py` and `relay_config.py` are placed in `plugins/core/lib` and kept identical by
`bin/sync-lib-copies` and the gate's "lib copies identical" step.

### 5.8 Degradation: detect, then locate (kept from revision 2, 2.11)

Detect: for each metric, the median of the last W changes against the median of the W before; a move by more than T flags
it. Locate: the first change j in the last W such that j and the R-1 changes after it all lie past the old median by more
than T. Printed as `gate minutes: 9.0 -> 22.5 (+150%) starting at change <name> (<sha>, <date>); seen at change <name>`.
On synthetic series (the session scratchpad (not kept), W=10, T=25%, R=3): a step at c21 located at c21; a single spike, no turn;
a spike then a step, located at the step; flat noise of +/-20%, 1.5% false flags; a noisy step, located right in 964 of
1000 series.

### 5.9 Flexibility, simplicity, order (owner: "Гибкость - Простота - Порядок")

- **Flexibility**: a new stage, kind, launcher or code metric is one value in one list or one gate log line (4.1, 4.2);
  the reader accepts unknown values and kinds by the required-key table (4.4).
- **Simplicity**: one writer (the merge hook through `relay_metrics.py`), one list module, one join key, one record
  shape for every kind; nothing stored that git, the queue or the checks hold; one launcher signal.
- **Order**: the ledger accumulates first; the record is written once, at the landing, from it; the reader computes
  everything else at reading. In the build, the lists come before the hooks that use them, and the reader's
  required-key table before the kinds that rely on it (7).

## 6. Decided inside the principles (owner can reverse)

1. **Records carry only the range and the agents**; everything git holds is derived on reading (principle 3). Rests on:
   ci-python's record is 1,841 bytes against 74,963 in the ledger, and every other fact of 1.2 was derived from git, the
   checks or the queue.
2. **A change's cost is its agents only; the front's own cost is shown per day from the ledger** (revision 2's question 2).
   Rests on: nothing invented; an even split of the front's day would add the same amount to a 15-second check-show change
   and to a 3-hour change. As a result Q11 compares agents only and "hand work per change" is listed as unanswerable (2).
3. **Git facts come from the first-parent line.** Rests on: measured, 14 gate logs in ci-python's diff, 4 its own.
4. **`role`, `output_estimated` and the train's `changes` are cut; zero token fields are left out.** Rests on: measured,
   854 of 854 agents; train-19's merge commits.
5. **Queue items join by `taken_by`, findings count distinct by id.** Rests on: measured, bench-set's close commit is
   off the first-parent line; ci-python's second check record restates the first's two findings.
6. **An agent serving several changes goes into each record with `of`.** Rests on: 1 of 53 hand agents; an even share
   is invented, but without it a sum over changes counts that agent twice, which is a wrong number.

## 7. Build order (agent minutes are estimates, not measured)

After the scripts move (`change-cycle-workflow-scripts-move-into-relay`, IP 96), as the handover orders it.

1. `lib/relay_labels.py`: the stage, kind and `by` lists and the label parser (stage, optional N, one or more names),
   placed in `plugins/observe/lib`, `plugins/delegate/lib` and `plugins/core/lib` (so `bin/sync-lib-copies` keeps them
   identical from then on). Gate log lines `started`, `took`, `others`; the first-parent rule; `relay metrics gates`
   (gate steps over time with detect and locate, from gate logs alone). About 55 agent minutes.
2. Ledger hook: `stage`, `names`, `by` (with `RELAY_LAUNCHER`), six token fields at agent stop (observe), with the
   privacy test and the three `by` tests. About 35.
3. Label check at agent start (if question 2 is a), in the route guard that already reads the call
   (`plugins/delegate/hooks/route-guard.py:139`), on only where 5.5 says, with its five tests. About 25.
4. `lib/relay_metrics.py` and its core copy: record, closed-list writer, open reader with the required-key table and the
   five-fixture test, the join key, `of`, the merge hook call before `clean()`, trains (changes from merge commits), the
   no-gate-no-agent rule, Glonass, backfill; `.relay/metrics` added to `relay_inert`'s list and to `Probe.start`'s
   appended folders and planted files (`.relay/metrics/zz.json`), so a test reading the live records fails the inert
   step. About 110.
5. `relay metrics`: per-change table, Q5 distinct findings, Q8 join by `taken_by`, trend, unlabelled agents per day,
   agents by `by` and the front per day, `--all`, the observe-only view. About 65.
6. Coverage: the `coverage_report` setting, LCOV and Cobertura readers, changed lines against the diff, freshness check,
   doctor's ignore check, relay's probe producing Cobertura with coverage.py and its three fallbacks. About 80.
7. Non-landing records (if question 1 is a): `relay metrics record --kind design|analysis|experiment`, file names with
   the UTC start, and its call in the script's end stage. About 20.
8. Rule text: the label form (with `other` and name lists) in the `delegate` skill's brief section; the
   `coverage_report` setting in the setup notes. About 10.

Total about 400 agent minutes (6.7 agent hours), estimate; the review's fixes added about 55.

## 8. Critique of the picks I build on

- **"Замеряем метрики на каждом gate", inside the probe**: this holds for relay only. The inert probe is relay's own gate
  step; another project's gate is its own command, so there coverage costs whatever its test tool costs, on every gate
  where the tool writes the report. Relay's own cost is still an estimate (+30-100 s per gate, 1-3.5% of ci-python's
  cycle), and inside the probe it needs the fallbacks of 5.3 so it cannot turn `inert` red.
- **Coverage format "a"**: LCOV and Cobertura cover coverage.py, Jest, c8, istanbul and cargo llvm-cov, but not Go's own
  profile or Java's JaCoCo without a converter; and a report written into the worktree without an ignore line would make
  every gate refuse (5.3 has the doctor check for it).
- **"Метрики становятся частью стандартного пакета relay"**: the standard package then reads observe's ledger format
  through copied modules; with observe off, records hold `"agents": null` and only git-derived numbers.
- **"краткость сегодня, возможность расширения в будущем"**: sound, with one cost: a field added later reaches back only
  as far as the ledger of those days. Today no code deletes the ledger (oldest file 21 Oct, 2.8 MB a day, about 1 GB a
  year), so a backfill works; if a ledger cleanup is ever added, every later field starts empty for older changes.
- **The three criteria** catch a missing question, a needless field and a format that cannot grow, but not a wrong
  number: revision 2 passed them and would have counted 14 gates for ci-python instead of 4; revision 3's first draft
  counted 6 findings instead of 4 and read "no estimate" for every change. Each derivation in section 2 now has a real
  sample, and the build's reader tests use those samples (ci-python 4 gates, 4 findings; bench-set estimate 20, real 103).

## 9. Open for the owner

**1. Should work that never lands get its own record?**
A change record is written at a landing. Designs, analyses and experiments never land: a design run ends with a report in
the scratchpad. This session they took a large share of agent spend: design, design review and design revise agents cost
$66.31 and hand-started thinkers and critics $10.92, together **$77.23 of $241.86 (31.9%)**, measured from the agents'
transcripts. Without a record that cost is visible only in the ledger, on this Mac. With a, the workflow script's end
stage writes a record of kind `design`, `analysis` or `experiment` (name and agents only, about 0.5 KB, one commit at the
run's end; each run its own file, so this design's three revisions are three records).

| | a. record at the run's end | b. ledger view only |
|---|---|---|
| Q12 "what did designs cost" | answered from git, on any machine | answered on this Mac while the ledger lasts |
| Extra commits | one per non-landing run (about 5-10 a day this session) | none |
| Build | +20 agent minutes | 0 |

- a. A record at the run's end (recommended; rests on the measured 31.9%).
- b. The ledger view only.

**2. Must the front label every agent it starts by hand?**
The record finds a change's agents by their label, `<stage>: <name>`. Workflow scripts write it (804 of 804 labelled);
the front, starting agents by hand, wrote free text in **all 53 cases** this session ("Resolve ci-python merge conflict"),
$13.72 (5.7%) of spend. In ci-python that lost 2 of 9 agents, 7.3% of its cost, and the whole conflict-fix round from Q5
and Q7. With a, the guard that already refuses `general-purpose` agents also refuses a relay agent whose description is
not a label, naming the form and the stage list; the front re-sends with one, one extra turn. It applies only in
projects with `.relay/` and metrics on, and never to built-in agents (2 of the 53). Work with no change gets `other:
<short name>`, work for two changes lists both: every one of the 51 relay hand agents of this session has a valid label
under these rules. With b, such agents are only counted per day.

| | a. refuse at start | b. count only |
|---|---|---|
| Hand agents in records | all relay agents (51 of 53 this session) | none (0 of 53) |
| Cost to the front | one re-sent call when it forgets | none |
| New stage word | refused until added to the list (one line), or `other` | silently lost |
| Where it acts | projects with `.relay/` and `[metrics] record` true | nowhere |

- a. Refuse at start (recommended; rests on the measured 0 of 53 labelled by hand).
- b. Count only.
