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
(`<slug>.json`), read the same from every worktree. Only `relay queue` writes an item. Items are ordered by ip, highest first. Use
`relay queue` to list them, `relay queue show <slug>` to read one, `relay queue add` to add one, `relay queue take` to
start one in a worktree (a branch holds one fix item; the check states its problem as `Q1`), `relay queue done` to close a fix with its test and the branch's check, `relay queue done <feature> --evidence <merge sha or report path>` to close a finished feature; `relay queue done <fix> --fixed-by <commit> --test <file>.py::<Class>::<name>` to close a fix that a change already on the default branch fixed (relay runs the test at the commit's parent and at the commit: it must fail, then pass); `relay
queue -h` shows the rest. A view is a read-only script in relay's own `lib/queue_ext/`
(`relay queue json` prints every item, `done/` included, for scripts); extensions live in relay only, they read and
never write items. An item keeps dated events, not a state: `found_at`, `taken_at` and `taken_by`, `closed_at` and `test` (with `fixed_by` when another change fixed it) or `evidence`, `dropped_at` and
`dropped_why` (UTC times, null until it happens); open, taken, done or dropped is computed from them, and `relay queue check`
validates the files. Only in a project whose default branch has `.relay/`.

An out-of-scope question from the owner is answered in two lines and becomes a
`feature` item, built later in a fresh session. When a new request arrives while
`fix` items wait, name them (how many, the top one, its time, written 30m or 1h 30m) and let the owner
decide what goes first.

An item's `title` is one plain sentence saying what is wrong or wanted, under 60
characters; `relay queue` shows it as the "what" column, and `add` refuses a title that only repeats the name.
