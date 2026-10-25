---
name: archive
description: Archive stage of an OpenSpec change. Use together with openspec-archive-change or openspec-sync-specs whenever /opsx:archive or /opsx:sync runs, or the user asks to archive or finish a change. Covers the pre-archive gate, archiving inside the change worktree, checking that no main-spec scenario was dropped, the docs sweep, and never merging on its own. Use only in a project whose rules carry "Spec steps in the change cycle" (`[specs] method = "openspec"` in `.claude/kit.toml`); a project that merely has an `openspec/` folder keeps it as docs, and this skill is not loaded for it.
argument-hint: "<change>"
---

# Archive

The project's rules for this stage arrive with this skill; they add to it and
win where they differ.

This skill adds to `openspec-archive-change` (and `openspec-sync-specs`);
where it says more, it wins. Archiving is mechanical, and the front writes no files: one `delegate:worker`
whose brief is "load `openspec:archive` and follow it" does it, after step 7 of the change cycle
(an archive-only commit after the check mark is inert for the merge guard). The
one risky step, the main-spec merge, is checked by a count (step 3).

## 1. Where and when

Archive in `<worktrees>/<change>` (`kit get project.worktrees`) on
`wt/<change>`, never in the main checkout: the archive and the code land in
`<base>` (`kit get project.default_branch`) in one merge. Before starting,
all of these hold, or stop and say which does not:

- the change cycle's check (step 7) passed with `open 0` for this branch;
- when `kit get --default false product.look_review` is `true` and the change touches what a
  person sees: the look review of step 4 ran (or its report says "not run"
  with its reason, or "skipped" with its count of identical shots), and the
  check of step 7 has `open 0`, so no defect or matter of taste is left waiting;
- every task in `tasks.md` is ticked;
- the full gate passed: `kit get gate.ci` in the worktree when
  `kit get --default local gate.final` is `local`; when `remote`, the pipeline on the pushed
  branch with `<base>` merged in (its number is in the gate report; don't run
  the full gate here);
- `openspec validate <change> --strict` and `kit spec-check <change>` pass.

## 2. Sync, then archive

When the archive workflow asks, choose "Sync now". A MODIFIED requirement
replaces the whole main-spec block.

## 3. Nothing dropped

Before archiving, record each touched main spec's scenario count (a
capability the change adds has none yet: 0):

```sh
grep -c '#### Scenario:' openspec/specs/<capability>/spec.md
```

After the sync each count is the old count, plus the scenarios the delta
ADDs, minus those it REMOVEs; a MODIFIED requirement keeps its count unless
the delta changes it. A lower count means a MODIFIED block dropped scenarios:
fix the main spec from the delta and
`git show <base>:openspec/specs/<capability>/spec.md`. Then
`openspec validate --specs --strict` passes.

## 4. Docs sweep

The change is now current behaviour, so the docs say so. Do this sweep
before the check of the change (as the last build task, committed before
the review of step 4), so the docs are reviewed and gated with the code. If
the check already passed and the sweep is still undone, do it now and run the
gate and the review again: a docs edit after the check is not inert.

- `CLAUDE.md`, if the change adds a command, a module or layer an agent must
  know, a term, a config area, or a rule every session needs.
- `README.md`, if what the product does or how to run, check or build it
  changed.
- The project's skills and docs that describe the product as it is, and the
  index page of any docs area that gained a page (the project's rules list them).
- `docs/handover.md`: where the work stands now (inert; may follow the archive).
- `git grep -n` for every term the change renamed or retired returns nothing
  outside `openspec/changes/archive/`.
- A frozen record (an approved prototype) is never edited.

The archive commit made after the check holds only `openspec/` paths (plus
`docs/handover.md`, which is inert). The merge guard treats such a commit as
inert: every path it touches is under `openspec/changes/archive/` or
`openspec/specs/`, or is a deletion under `openspec/changes/<change>/` (the
move into the archive), and the span adds a folder under the archive. It needs
no new gate and no new check. An archive commit that also changes docs or code
(or edits the change's own folder) needs a new gate and a new review, not just
a check.

## 5. Commit and report

Commit on `wt/<change>` (openspec-only, see step 4):
`Archive <change>: main specs synced (<capabilities added / amended>)`.
Report `wt/<change>, archived, ready to merge` (with the gate's pipeline
number when remote). Don't merge and don't remove the worktree: the merge is
the owner's. An agent that
archives never merges.
