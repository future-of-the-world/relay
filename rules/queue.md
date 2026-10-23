# Work queue
> Nothing wrong is left behind: wrong inside a change is fixed before its merge; wrong elsewhere is a fix item in the work queue, above the features.

Something found during a change is one of four things:

1. Wrong inside the change: fixed in this change. The merge is refused until it is.
2. Wrong elsewhere: a queue item of kind `fix`, with its failing case. A new fix
   goes above every open feature.
3. The design itself is wrong (a finding marked `Design:`): stop building on that
   part. The redesign is a `fix` item and the next change. The current change
   finishes first only when the owner agrees it does not build on the wrong part.
4. A feature: a queue item of kind `feature`, with the important points (ip) the
   owner gives (default 0).

The queue is `.relay/queue/` on the project's default branch, one JSON file per item
(`<slug>.json`), read the same from every worktree. Only `relay queue` writes an item. Items are ordered by ip, highest first. Use
`relay queue` to list them, `relay queue show <slug>` to read one, `relay queue add` to add one, `relay queue take` to
start one in a worktree, `relay queue done` to close one with its test; `relay
queue -h` shows the rest. A view is a read-only script in relay's own `lib/queue_ext/`
(`relay queue json` prints the items for scripts); extensions live in relay only, they read and
never write items. Only in a project whose default branch has `.relay/`.

An out-of-scope question from the owner is answered in two lines and becomes a
`feature` item, built later in a fresh session. When a new request arrives while
`fix` items wait, name them (how many, the top one, its time, written 30m or 1h 30m) and let the owner
decide what goes first.

An item's `title` is one plain sentence saying what is wrong or wanted, under 60
characters; `relay queue` shows it as the "what" column, and `add` refuses a title that only repeats the name.
