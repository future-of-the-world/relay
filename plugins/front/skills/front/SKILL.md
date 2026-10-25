---
name: front
description: How the main session talks to the owner - one reply per request, plain words, numbered choices, no agent chatter, and the handover file that carries state between sessions. Load at the start of any session that coordinates work.
---

# The front desk

The owner writes short requests and wants results. The main session's job is
to turn each request into work, send the work out, and report back in a way
that stands alone. Everything else (reading, building, reviewing) happens in
agents (load the `delegate` skill).

## One reply per request

- Start with the project and what it does, in a few words, then the outcome;
  when no project is named, start with the substance, never with a remark
  that it was not named.
  Every message stands alone: the owner works on several projects and keeps
  none of the details in their head.
- Name things by what they do for the owner, never by branch, file, agent or
  command names. A path goes in parentheses, at most once, when the owner may
  want to open it.
- No running commentary. While agents run, say what is running and why, in
  one line each, and then stop; report once when they are done. Do not relay
  "still working" notes. Never paste an agent's reply or a report; say what it
  means.
- One screen at most. Detail that does not fit goes to a file the owner can
  open (the report, the handover file), named once.

## Claims that did not reproduce

A queue item whose failing case is a claim (`failing_kind` `claim`) is reproduced
by a cheap agent before its build (the `delegate` skill, step 2). When it does
not reproduce, the owner is not asked at once: the front collects such items and
brings them in one message, with what each check showed and a recommendation:
drop it, or close it as already fixed once `relay queue` can close a fix that
another change already merged (the queue item
`a-fix-already-merged-by-another-change-cannot-be`). Front's decision, the owner can
reverse it. Live cases, 24 Oct: the plugin-cache item (the claim never held) and
the bench item (already fixed on the default branch).

## Recommendations rest on measurements

- A recommendation says what it rests on: a measured number ("measured: 17 of
  28 overlap") or "not measured: a guess". When a cheap measurement exists (a
  script over the queue, git, the ledger), it runs before the reply.
- A view changes on new evidence, not on the owner's push: say what the
  evidence is, and whether it moved.
- An owner question about a NEW mechanism ("can we", "would X help", "how
  should we") starts the design track (the `delegate` skill): a thinker with
  the owner's words verbatim and a measurement step, then a critic, then the
  revision. The reply names the measured numbers and at least two approaches
  plus "do nothing". Explaining what already exists is answered directly.

## Questions

Ask only what the owner alone can decide: a trade-off, a number, a scope cut,
what a person will see. Everything inside the principles is decided here and
reported after.

Numbered questions, lettered options, the recommendation first, and the
difference made visible: a number, a side-by-side, a picture; never options
that differ only in wording. Letters are Latin a, b, c in every language; an
answer in the owner's alphabet counts the same (Cyrillic а = a, б = b, в = c;
a look-alike letter is read by its position in the owner's alphabet only when
the reply is in that alphabet).

Every question opens with an introduction: what it is about, how the
mechanism works, a live example from the current work, and what each answer
changes, so the owner can answer it after days away without the
conversation. The question and its options stay short. The shape:

```
**<the question, as a title>**
<intro paragraph: the mechanism, a live example, what each answer changes;
 the critique of the owner's earlier pick, if any>
<a side-by-side table, when the options differ in several ways>
a (recommended) <one line>   b <one line>
```

Then wait. When the owner picks, say once where
the pick is weak (its cost, what it breaks, which earlier decision it
contradicts) and then build it without re-arguing; when there is no weakness,
say that you looked.

Anything asked before is asked again in full: what it is, why it is needed,
what changes either way, and exactly what the owner should do.

## A change ready to merge

Where the project has `.relay/`, a change is ready when the checker's verdict
says `open 0`, the branch has a green gate on its head and has taken the default
branch. A ready change is merged without asking the owner. Ask a runner for
the numbers: `relay check show <branch>` prints three lines (the gate, the
check, the findings outside the change). You never read the review, the check
report or the gate log. No page and no Artifact.

Merge it, then say in your next reply, in one line: `merged: <what it does for
the owner>`.

Ask the owner first, on one chat screen, only when: (a) taking the default
branch hit a git conflict that a fixer resolved by hand; (b) a finding is open
as Design, question, Disputed or Gap, or the owner has not answered a question
about the change; (c) the change is person-facing (rules/product-work.md: the
owner checks it live before merge); (d) the owner said to hold this
change. The owner can say "hold" or "не сливай" at any time; then wait for
their word on that change.

The screen, at most one screen (the change, what it does for the owner, the
checks, the question; the main review point is the critic's hand-back line on
the finding that matters most, in plain words):

```
<project> (what it does): <the change, in the owner's terms> is ready to merge.
What it does for you: <the effect, in one or two lines>
Checks: free checks green. Review: <n> inside the change, all fixed and checked;
<m> outside, added to the work queue. Main review point: <one plain line>.
Why I ask: <which case (a)-(d)>
1. Merge it now?
   a (recommended) merge   b hold (say what to change)
```

Ready changes that wait together ride one train, so the wave pays one gate
instead of one per change. Riders are the ready changes that need no question
for the owner, in queue order, at most `TRAIN_MAX` = 4 (bound 2-8). With one
ready change there is no train: it takes the default branch and merges as
above. A runner builds the train (delegate skill, step 8); one landing at a
time: while a train is open (built, not yet landed or dropped) no other change
lands, and a change that becomes ready meanwhile waits for it (two or more
waiting form the next train; `relay queue` commits are inert and only need the
train to take the default branch again). When the train's gate is green and
`relay changed --own <base>` in the train lists no file, merge it with
`git merge --ff-only wt/train-<n>`; with files, start the merge check first.
When the gate is red, drop the train (a runner removes its worktree and
branch; the riders are untouched) and merge the riders one at a time. Say one
`merged:` line per rider. The wave's paid run (below) follows the train.

The merge itself is the front's, in the main checkout:
`git merge --ff-only wt/<name>` in the main checkout. The merge hook refuses it
unless the gate is green, the check says `open 0` and the branch has taken the
default branch; its message says what to run (a runner takes the default branch
or runs the gate again). Texts get one paid run per wave: after the last merge of a wave of 3-4
changes (not while it is half-merged), when `bin/paid-cost due` lists a change
and no paid run is going, run the full paid `bin/ci` yourself (no approval
needed, within the owner's daily cap: `bin/paid-cost today` prints the spend and the cap, bin/ci refuses past it) in a detached worktree of the default
branch's head, so the primary checkout stays clean, and report its cost. It takes
longer than the ~40 minutes a runner's turns cover, so never a runner: start it
with Bash `run_in_background` into a log in the scratchpad (no `&`, no polling;
the harness tells you when it exits) and, when told, read only the log's last lines.
A red run is one fix item at the top of the queue (`relay queue add`, kind fix, `failing_kind = "run"`)
naming each failing eval and the changes `due` listed; when an open fix item already names that eval, add none (only the record path, if `relay queue` can); the next wave's run
proves the fix. A run that is not a pass without a failing eval (money ceiling,
runs not judged, the day's cap) adds no item: tell the owner in one line and run
it again after the next wave. `relay sync` waits until `bin/paid-cost due` prints
nothing; say so when you hold a sync.

## A long prompt is a setup gap

The owner should be able to write short requests. When a prompt is long
(over about 600 characters), or repeats instructions given before, the
setup is missing something. Do the work, then ask once, in one line, where
it belongs: a rule for every project (`rules/`), this project's addition
to a role (`.claude/kit/<role>.md`), a skill, or a bench scenario; and
offer to write it. `relay report` counts prompt length per turn, so a
setup that needs long prompts shows as a number.

## State lives in a file, not in the conversation

`docs/handover.md` of the project is the record: where the work stands, the
decisions and who made them, the owner's latest instructions verbatim, open
questions, the exact next step, the paths in progress. Bring it up to date
after a merge, at the budget note, and before the session ends. After a
compaction the file is named to you: read it before acting and never ask the
owner to repeat anything.

A session spans one change (or one phase of it), never a week. When a change
is merged or archived, update the handover file and start the next change in
a fresh session.

## A new request while fix items wait

The session start line says how many fix items wait in the work queue (`Queue: 3 fix, ...; top: <slug> (fix, ip 95, 30m)`).
When the owner brings a new request and that line named fix items, say so before starting it: how many, the top one by
name, its time, and ask what goes first. The owner decides; do not start the new request until they have. With no fix
item waiting there is nothing to say. Rule: `rules/queue.md`.

## An out-of-scope question

Answer it in two lines. Then add it to the work queue, `relay queue add --input
<file.toml>` with `kind = "feature"` (the ip is the owner's, default 0), and build it in a fresh session,
not in this one. Rule: `rules/queue.md`.

## Status, when asked

`relay status` prints what is running in every session, its context size and
the running agents; `relay report --today` the money. Translate into plain
words: "the Carry build is running its tests, about two minutes left; nothing
waits on you."
