---
name: front
description: How the main session talks to the owner - one reply per request, plain words, numbered choices, no agent chatter, and the handover file that carries state between sessions. Load at the start of any session that coordinates work, before answering what was decided about something, and before replying to words the owner offers about a work-queue item (a wish, an explanation, a correction), which are recorded in the item.
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
a. <one line> (recommended)
b. <one line>
```

Before the question is shown, record it in the item it decides: `relay queue note <slug> --input <file.toml>` with
`question` (the block above), `options` (the lettered lines, each starting `a. `, `b. `, ...) and `number`; paste what the command prints, so the owner
sees what is stored. A question about no item first adds the item (`relay queue add`). When the owner replies, record
the whole reply with `answer` (every explanation included; `to = [1, 2]` when one reply answers two questions), your
reading apart in `reading`. A hook names each recorded question without an answer on every owner message until it is
recorded. Words the owner offers about an item unasked (a wish, an explanation, a correction) go in as `said`, verbatim (the
owner's own sentence, character for character, in the language he wrote it, typos included; never translated, shortened or
summarized), the same turn, without waiting for "запиши"; a measurement you show the owner goes in as `fact`. Nothing is recorded for
talk that is about no item.

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
branch hit a git conflict that a fixer could not resolve (it stopped on it; a resolved
conflict does not wait for the owner, it goes on to the gate and the recheck); (b) a finding is open
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
or runs the gate again). Texts get one paid run per wave. A wave is the train of checked-path
changes landed after a green run (plus whatever landed beside it). Start the
paid run, only when `bin/paid-cost due` lists a change and no paid run is going,
at the first of: that train has fully landed (not while it is half-landed);
`due` lists at least the number in your line "Paid run starts when
`bin/paid-cost due` lists at least: N changes" (projects.toml `wave_min`, 1-6,
default 3); the end of a work stretch, whatever `due` holds. Run the full paid
`bin/ci` yourself (no approval needed, within the owner's daily cap:
`bin/paid-cost today` prints the spend and the cap, bin/ci refuses past it) in a detached worktree of the default
branch's head, so the primary checkout stays clean, and report its cost. It takes
longer than the ~40 minutes a runner's turns cover, so never a runner: start it
with Bash `run_in_background` into a log in the scratchpad (no `&`, no polling;
the harness tells you when it exits) and, when told, read only the log's last lines.
A red run is one fix item at the top of the queue (`relay queue add`, kind fix, `failing_kind = "run"`)
naming each failing eval and the changes `due` listed; when an open fix item already names that eval, add none (only the record path, if `relay queue` can); the next paid run proves the fix. A run that is not a pass without a failing eval (money ceiling,
runs not judged, the day's cap) adds no item: tell the owner in one line and run
it again as the Lanes section says. `relay sync` waits until `bin/paid-cost due` prints
nothing; say so when you hold a sync.

## Lanes: several changes at once

The number of changes built side by side is the line "Changes built at once: N"
in your instruction file (projects.toml `lanes`, 1-8, default 4; relay's own
is 6). Each lane is its own cycle run: one queue item per Workflow call. When a
lane finishes, start the next call at once; its item is the top of
`relay queue` that no running lane has taken (`relay queue take` marks it). Do
not wait for the other lanes, and never start more than N.

While a paid run goes, lanes keep building. A change that touches the paid
run's paths waits at the landing until the run ends; `bin/paid-cost touches
<branch>` answers it (prints the matching files, exit 0; prints nothing and
exits 1 when the branch touches none; `bin/paid-cost paths` lists the globs).
The reason: the run does not cover a checked-path change landed during it, so
after a green run `bin/paid-cost due` would still list it and `relay sync`
would stay refused. Any other change lands as usual. How the waiting changes
are released depends on how the run ends:

- Green: `relay sync`, then the waiting changes land as one train (above), and
  the next paid run starts on that head.
- Red: the fix item lands first; the next paid run starts on its head at once,
  with no wave needed, and the waiting changes land after that run is green.
- Not judged (money ceiling, runs not judged, the day's cap): the waiting
  changes keep waiting; run again on the same head as soon as the cap allows,
  and they land after that run is green.

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

Decisions about a queue item and the owner's words about it go into the item (`relay queue note`), not only here; the
handover keeps a pointer to the item and the state of the session.

A session spans one change (or one phase of it), never a week. When a change
is merged or archived, update the handover file and start the next change in
a fresh session.

## A new request while fix items wait

The session start line says how many fix items wait in the work queue (`Queue: 3 fix, ...; top: <slug> (fix, ip 95, 30m)`).
When the owner brings a new request and that line named fix items, say so before starting it: how many, the top one by
name, its time, and ask what goes first. The owner decides; do not start the new request until they have. With no fix
item waiting there is nothing to say. Rule: `rules/queue.md`.

## "What did we decide about X?"

Find the item: `relay queue show <the owner's words>` (items are written in English, so try English words too; several
matches are listed, then show one by its name). Answer from its notes alone, with no memory or handover: each question
as it was asked (its title and all its lettered options, the chosen and the rejected ones, none left out), quoted exactly as
recorded: the questions were shown to the owner in the owner's language, so the recorded text is already in it; copy it,
do not translate or shorten it. A note recorded in another language gets your translation of it in the owner's language
beside the quote, marked as yours. The owner's answer in quotes, character for character as recorded ("1. a", never "you
chose a"), with any explanation, your reading marked as yours, and a question not answered yet said
so. Rule: `rules/queue.md`.

## An out-of-scope question

Answer it in two lines. Then add it to the work queue, `relay queue add --input
<file.toml>` with `kind = "feature"` (the ip is the owner's, default 0), and build it in a fresh session,
not in this one. The owner's words, character for character, go to the `said` key of the add input (`relay queue add --from`
takes no `said`: add the item, then `relay queue note` with `said`), never into `why` or `what`. Rule: `rules/queue.md`.

## Status, when asked

`relay status` prints what is running in every session, its context size and
the running agents; `relay report --today` the money. Translate into plain
words: "the Carry build is running its tests, about two minutes left; nothing
waits on you."
