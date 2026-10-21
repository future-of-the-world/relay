---
name: read
description: Listing, searching and reading issues (.issues/<slug>/description.md on their branches, the tracker's open issues) without changing anything. Use when the owner asks what issues exist, what an issue says, which are open, what depends on what. Read-only; done by a scout.
argument-hint: "[slug | #number | a search word]"
---

# Read issues

The truth about an issue is in two places: its file,
`.issues/<slug>/description.md`, which lives on branch `<slug>` until the
work merges (then on the default branch), and the tracker issue
(`kit get issues.view`, with `{n}`). There is no status field anywhere: a
branch that exists is in progress; a tip that is in the default branch's
history is done.

One `delegate:scout` does the reading and replies in at most 10 lines:

- **List**: `git branch -r --list` for in-progress slugs plus
  `ls .issues/` on the default branch for done ones; the tracker's open
  list (`kit get --default "" issues.list`) when the owner asks "what is
  open". One line per issue: slug, title, dependencies, state (in
  progress / merged / only in the tracker).
- **Read one**: the summary, the acceptance criteria (or the spec file they
  point at), the dependencies, and the decisions in `decisions.md` with who
  made each. Where the file is on an unmerged branch:
  `git show origin/<slug>:.issues/<slug>/description.md`.
- **Search**: `git grep -n <word> -- '.issues/'` across the default branch
  and `git grep -n <word> origin/<slug> -- '.issues/'` for open branches.

Tell the owner in their terms: what the issue is about, what it depends
on, whether it is in progress, and the open questions, if any. Never paste
the file.
