# Work queue
> Nothing wrong is left behind: wrong inside a change is fixed before its merge; wrong elsewhere is a fix item in the work queue, above the features.

Something found during a change is one of four things:

1. Wrong inside the change: fixed in this change. The merge is refused until it is.
2. Wrong elsewhere: a queue item of kind `fix`, with its failing case and what that
   case is (`failing_kind`: `test`, `run` for a recorded red run, or `claim` for
   someone's word; a fix item with no `failing_kind`, queued before the field, counts as a claim). A claim is reproduced by a cheap agent before the build; one that
   does not reproduce is not built (the delegate skill, step 2). A new fix
   goes above every open feature.
3. The design itself is wrong (a finding marked `Design:`): stop building on that
   part. The redesign is a `fix` item and the next change. The current change
   finishes first only when the owner agrees it does not build on the wrong part.
4. A feature: a queue item of kind `feature`, with the important points (ip) the
   owner gives (default 0).

The queue is `.relay/queue/` on the project's default branch, one JSON file per item
(`<slug>.json`), read the same from every worktree. Only `relay queue` writes an item. Items are ordered every open fix before every open feature, then by ip, highest first. A fix added without `--ip` gets ip 0, like a feature; an explicit `--ip` is stored as given. Use
`relay queue` to list them, `relay queue show <slug>` to read one, `relay queue add` to add one, `relay queue take` to
start one in a worktree (a branch holds one fix item; the check states its problem as `Q1`), `relay queue done` to close a fix with its test and the branch's check, `relay queue done <feature> --evidence <merge sha>` to close a finished feature; `relay queue done <fix> --fixed-by <commit> --test <file>.py::<Class>::<name>` to close a fix that a change already on the default branch fixed (relay runs the test at the commit's parent and at the commit: it must fail, then pass); `relay
queue -h` shows the rest. A view is a read-only script in relay's own `lib/queue_ext/`
(`relay queue json` prints every item, closed and dropped ones included, for scripts); extensions live in relay only, they read and
never write items. An item keeps dated events, not a state: `found_at`, `taken_at` and `taken_by`, `closed_at` and `test` (with `fixed_by` when another change fixed it) or `evidence`, `dropped_at` and
`dropped_why` (UTC times, null until it happens); open, taken, done or dropped is computed from them (there is no `done/` folder: a close or a drop edits the item file in place, and `relay queue` lists the open and taken ones), and `relay queue check`
validates the files. Only in a project whose default branch has `.relay/`.

An item holds the owner's words verbatim and dated facts, never a link to a session file, and no plan: a design is
written fresh when the item is taken. What is said or measured about an item after it was created goes into it as a
note the same turn, without being asked: the owner's words (`said`), a measurement (`fact`), a question before it is
shown (`question`, `options`), the owner's whole reply when it comes (`answer`, with the front's `reading`
apart, `chosen` = the letters; `to` = the asked time when several wait or a decision of the front is on the item). A decision the front takes itself is a question note
with `chosen`, `decided_by` and `because`, never a fact, and never on a question the owner was asked. A question about no item first adds the item; one about several is noted on the item it decides.
`relay queue note <slug> --input <file.toml>` writes notes; `relay queue show <slug or words>` prints them. A session
file path (`/tmp/...`, `/private/tmp/...`, a scratchpad file) in text the front writes is refused by `add`, `drop`,
`done --evidence` and `note`; the owner's own words are kept as given.

An item's text is changed only by `relay queue edit <slug> --input <file.toml>` (field, the exact `old` fragment, `new`, `because`): it
leaves every quoted span (`"..."`, `«...»`, `'...'`) byte-equal, checked on the result, and adds a dated fact note saying why; the
earlier text is read with `relay queue history <slug>`. A new item keeps the owner's words in a `said` note (`said` in the `add` input),
never in `what` or `why`, so no edit can reach them. A fix's check counts only for the problem it judged: an edit of the item after the
check makes it stale (take the default branch, check again). Nothing but `relay queue` writes a queue file, on a task branch too: the
guard refuses a write to `.relay/queue/<slug>.json` before it is made, and the merge hook refuses a branch whose item text,
earlier notes or `test` differ from the default branch's by hand, naming `relay queue edit`. Git's own merge and conflict resolution
stay free. Every reshaping of items (a new key, a renamed one, a new shape) ships as a migrate module `lib/relay_*migrate*.py`
(run by `relay queue migrate`) in the same change; a branch that changes one is the only one the hook lets rewrite items in bulk.

An item's `time` is an estimate made from measurement, not by eye. `relay queue estimate` measures every closed change from the
agent transcripts (agent minutes: the summed durations of the agents that ran in its worktree; build minutes: its workers; wall
minutes: taken to closed), prints each closed item's estimate beside those, and prints the estimate for a new item: the median fixed cycle
of past changes (gates, review, checks, queue close) plus the median build part. A paid run checks a wave of changes, not one, so it is
not added to an item's estimate: the view prints the wave's paid-run minutes and cost on a line of its own, and the front tells the owner
that line apart from the item's time. The view also prints how many closed items had agents in the transcripts (an agent is tied to a
change by its working folder, else by the worktree its brief names). Nothing measured is stored in an item; it is computed when read.
Use the estimate for `--time`.

An out-of-scope question from the owner is answered in two lines and becomes a
`feature` item, built later in a fresh session. When a new request arrives while
`fix` items wait, name them (how many, the top one, its time, written 30m or 1h 30m) and let the owner
decide what goes first.

An item's `where` is a list of places, one string each: the place as its first word (`path`, `path:N` or `path:N-M`), then an
optional note for people after a space, for example `["lib/relay_setup.py:325-333 merge_settings", "docs/handover.md"]`. The check refuses a
string and an element whose first word has another shape; `add` and `edit` also refuse a folder, a directory name without a slash and a
pattern: name the file, a new one is fine. When the item is taken, its Q1 gets the first place (line N of N-M);
the other places go into Q1's details.

An item's `title` is one plain sentence saying what is wrong or wanted, under 60
characters; `relay queue` shows it as the "what" column, and `add` refuses a title that only repeats the name.
