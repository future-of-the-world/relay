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

The queue is `.relay/queue/` on the project's default branch, one file per item,
read the same from every worktree. Items are ordered by ip, highest first. Use
`relay queue` to list them, `relay queue add` to add one, `relay queue take` to
start one in a worktree, `relay queue done` to close one with its test; `relay
queue -h` shows the rest. Only in a project whose default branch has `.relay/`.

An out-of-scope question from the owner is answered in two lines and becomes a
`feature` item, built later in a fresh session. When a new request arrives while
`fix` items wait, name them (how many, the top one, its time, written 30m or 1h 30m) and let the owner
decide what goes first.
