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
shown (`question`, `options`, `number`), the owner's whole reply when it comes (`answer`, with the front's `reading`
apart). A question about no item first adds the item; one about several is noted on the item it decides.
`relay queue note <slug> --input <file.toml>` writes notes; `relay queue show <slug or words>` prints them. A session
file path (`/tmp/...`, `/private/tmp/...`, a scratchpad file) in text the front writes is refused by `add`, `drop`,
`done --evidence` and `note`; the owner's own words are kept as given.

An out-of-scope question from the owner is answered in two lines and becomes a
`feature` item, built later in a fresh session. When a new request arrives while
`fix` items wait, name them (how many, the top one, its time, written 30m or 1h 30m) and let the owner
decide what goes first.

An item's `where` is a list of places, one string each: the place as its first word (`path`, `path:N` or `path:N-M`), then an
optional note for people after a space, for example `["lib/relay_setup.py:325-333 merge_settings", "docs/"]`. The check refuses a
string and an element whose first word has another shape. When the item is taken, its Q1 gets the first place (line N of N-M);
the other places go into Q1's details.

An item's `title` is one plain sentence saying what is wrong or wanted, under 60
characters; `relay queue` shows it as the "what" column, and `add` refuses a title that only repeats the name.
