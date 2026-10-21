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
Goal: <the result, in the owner's words>
Done when: <the check that passes / the file that exists / the question answered>
Check: <command>                                  # the quiet check to loop on
Read: <file:section>, <file:lines>, ...           # only what this job needs
Files: <paths it may touch>                       # worker/fixer
Decisions (the owner's, verbatim):
- "<quote>"
Not decided (ask, do not guess):
- <item>
Constraints: <project rules that apply; the no-attribution rule where it applies>
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
Open the report file (`head -40`) only when the first word is not DONE. Never
paste a report into the conversation: tell the owner the outcome in one or two
plain sentences, and keep the path.

A BLOCKED agent is not restarted with the same brief: fix the brief (the
missing decision, the wrong assumption) and start a fresh agent. An agent that
has been idle for over 5 minutes is not resumed: start a fresh one from the
brief and the old report.

## Review loop

After a worker's DONE on a change that will be merged: one critic, then one
fixer on its findings, then the critic again over the fix range. What is still
open after the second pass comes to the owner as a numbered list with a
recommendation. No third pass without the owner's word.
