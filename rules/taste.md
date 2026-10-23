# Taste (experimental)
> Waste is wrong: the reviewer lists the waste a change adds before its merge, and the front lists the waste a session met after it, each queued as a fix item. Relay project only.

Waste is wrong. Signals, each counted: the same work done twice (a re-run with nothing changed,
two agents reading the same files, a step redone after a refusal); a refusal or red step that found nothing wrong;
output nobody reads; a step that exists only to satisfy another script.

- Before a merge, the reviewer lists the waste the change adds as findings whose summary starts `taste:`. Repeats on
  every run or every change: MEDIUM, fixed before the merge. A one-off: LOW.
- After a merge, the front lists the waste the session met, with numbers (minutes, runs), and queues each as a fix item
  with `found_in = "taste: <change>"` (an input key of `relay queue add --input`).
- The experiment is the next 5 merges into the default branch after the one that added this rule
  (`git log --first-parent`), even when a merge has no waste. After the 5th the front reports both counts to the owner:
  front flags = queue items whose `found_in` starts `taste: `; reviewer flags = those findings in `.relay/checks`
  review JSONs. Kept = fixed or not dropped; dropped = the owner dropped it. The owner decides on keeping the rule.

Example (23 Oct, core-tests-not-in-gate): 3 merge-path refusals that found nothing wrong, the checker run twice,
one ~8 min gate run spent because a fixer reported green before committing, the merge tried 3 times.
