# Taste (experimental)
> Waste is wrong: the reviewer lists the waste a change adds before its merge, and the front lists the waste a session met after it, each queued as a fix item. Relay project only.

Waste is wrong. Signals, each counted: the same work done twice (a re-run with nothing changed,
two agents reading the same files, a step redone after a refusal); a refusal or red step that found nothing wrong;
output nobody reads; a step that exists only to satisfy another script.

- Before a merge, the reviewer lists the waste the change adds.
- After a merge, the front lists the waste the session met, with numbers (minutes, runs), and queues each as a
  fix item whose `why` starts with `taste: <change>` (`relay queue add` always writes its own `found_in`).
- Counting: `relay queue json`, items whose `why` starts with `taste:`; kept = state not `dropped`, dropped = `dropped`.
  Kept or dropped after 5 changes (5 distinct `<change>` values), by how many flags the owner keeps.

Example (23 Oct, core-tests-not-in-gate): 3 merge-path refusals that found nothing wrong, the checker run twice,
one ~8 min gate run spent because a fixer reported green before committing, the merge tried 3 times.
