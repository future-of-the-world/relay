---
name: tune
description: Turn a request about the setup itself into a measured comparison - "try Haiku instead of Sonnet for workers", "lower the effort", "make workers plan more and take smaller tasks", "which setup is cheaper", "compare", "adopt it", "what did this week cost". Load, in any language and despite typos, whenever the owner talks about the setup itself: models, effort, what the setup or sessions cost, how agents work, comparing two setups or profiles, adopting a candidate. Not for a question about the project's own work, a change's content, or comparing code or documents. The owner never types relay commands; this skill runs them.
argument-hint: "<what to try>"
---

# Tuning the setup, in the owner's words

The owner says what to try; this session makes a candidate, benches it
against the active setup, and reports the table in plain words. The
`relay` command is on PATH (`relay help`).

## 1. What kind of change is it

| The owner says | It is | Candidate |
|---|---|---|
| a model for a role ("Haiku for workers", "Sonnet reviews") | a profile key | `relay bench active --set models.<tier>=<model>` |
| effort ("think less when building", "max effort for design") | a profile key | `--set effort.<tier>=low\|medium\|high\|xhigh\|max` |
| the front's model | a profile key | `--set session.model=sonnet` |
| fewer or more rules loaded | a profile key | `--set rules.load=a,b,c` |
| how a role works ("workers plan first", "smaller tasks", "reviews name the test") | text in an agent or skill | `relay candidate <name> --copy delegate` then edit the copy |
| a flow stage ("the issue flow should open the PR earlier") | text in a flow skill | `relay candidate <name> --copy issues` then edit the copy |
| "what did this week cost", "where does the money go" | a report | `relay report --since 7d`, `relay improve suggest` |

Tiers: look (scout), run (runner), build (worker), fix (fixer), think
(thinker), judge (critic). Several `--set` in one bench are one candidate;
two ideas the owner wants told apart are two benches.

## 2. A candidate with edited text

`relay candidate <name> --copy delegate` copies the plugin under
`profiles/candidates/<name>/plugins/delegate/` and writes
`profiles/candidates/<name>.toml` pointing at the copy. The edit is a
`delegate:worker` job with a brief: which file (an agent's `.md`, a skill's
`SKILL.md`), what the owner asked in their words, keep everything else.
"Make workers plan more and take smaller tasks" is, for example, a
`## 0. Plan` section in the copy's `agents/worker.md` (list the steps and
the check of each before editing; stop and report after N steps) plus
`maxTurns` lowered; the brief says that, the worker writes it.

## 3. Bench

```sh
relay bench active <name-or---set...> --tag cheap --runs 1      # direction, minutes, a few dollars
relay bench active <name> --tag cheap --runs 3                 # before adopting
relay bench active <name> --scenario review-offbyone           # when the judge tier changed
```

Run it detached when it may pass 4 minutes (`nohup ... > <log> &`, wait in
calls of at most 240 s); the report is saved under `~/.relay/bench/<ts>/`.
A scenario that fails under both setups is a broken scenario, not a
result: say so.

When no shipped scenario exercises what the owner changed (an issue-flow
stage, a project-specific job), make one first: copy a folder under
`evals/scenarios/`, set the fixture and prompt, and give it graders that
are commands or files (the owner's own test is the best grader). A worker
does that from a brief; then bench.

## 4. Report, in the owner's words

Not the table: the verdict and the three numbers that decided it.

> Workers on Haiku instead of Sonnet: same results on all three jobs (tests
> green, script works), 61% cheaper, a little faster, but 50% more turns:
> Haiku needs more tries. One run each; I recommend adopting after three
> runs confirm it. 1. a) run three now (about $4)  b) adopt now  c) drop it.

When quality dropped, say on which job and what failed (the grader's
note), never "score 0.67".

## 5. Adopt, and check in real use

`relay improve adopt <name> --because "<the verdict in one line>"` on the
owner's word. Say that new sessions run the new setup (this one does not).
A week later, unasked: `relay report --compare <week before> <week after>`,
two lines to the owner: cost per turn then and now, and whether to keep it.
