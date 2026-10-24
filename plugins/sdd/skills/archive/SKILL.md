---
name: archive
description: Archive stage of an OpenSpec change. Use together with openspec-archive-change or openspec-sync-specs whenever /opsx:archive or /opsx:sync runs, or the user asks to archive or finish a change. Covers the pre-archive gate, archiving inside the change worktree, checking that no main-spec scenario was dropped, the docs sweep, and never merging on its own.
argument-hint: "<change>"
---

# Archive

The project's rules for this stage arrive with this skill; they add to it and
win where they differ.

This skill adds to `openspec-archive-change` (and `openspec-sync-specs`);
where it says more, it wins. Archiving is mechanical, so the coordinator does it (in a Sonnet session
when the owner starts one for it; this skill never switches the model). The
one risky step, the main-spec merge, is checked by a count (step 3).

## 1. Where and when

Archive in `<worktrees>/<change>` (`kit get project.worktrees`) on
`wt/<change>`, never in the main checkout: the archive and the code land in
`<base>` (`kit get project.default_branch`) in one merge. Before starting,
all of these hold, or stop and say which does not:

- the `sdd:apply-review` gate ran with no open high finding (its report is in
  this session or in a `Review fixes` commit on the branch);
- when `kit get --default false product.look_review` is `true` and the change touches what a
  person sees: the report's `Look:` line has no open defect and no matter of
  taste waiting for the owner; "not run" carries its reason and "skipped" its
  count of identical shots, or the look review runs first;
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

The change is now current behaviour, so the docs say so:

- `CLAUDE.md`, if the change adds a command, a module or layer an agent must
  know, a term, a config area, or a rule every session needs.
- `README.md`, if what the product does or how to run, check or build it
  changed.
- The project's skills and docs that describe the product as it is, and the
  index page of any docs area that gained a page (the project's rules list them).
- `docs/handover.md`: where the work stands now.
- `git grep -n` for every term the change renamed or retired returns nothing
  outside `openspec/changes/archive/`.
- A frozen record (an approved prototype) is never edited.

When `gate.final` is `remote`, the archive changes only `openspec/` and docs,
so it needs no new pipeline: run the tests that read docs. If it must change
anything else, the gate runs again before the branch is reported ready.

Archive after the check of the change, in its own commit. The merge guard
treats a commit that only archives as inert: every path it touches is under
`openspec/changes/archive/` or `openspec/specs/`, or is a deletion under
`openspec/changes/<change>/` (the move into the archive). That commit needs no
new gate and no new check. Any other file in it (code, docs, an edit of the
change's own folder) makes the merge ask for both again.

## 5. Commit and report

Commit on `wt/<change>`:
`Archive <change>: main specs synced (<capabilities added / amended>)`.
Report `wt/<change>, archived, ready to merge` (with the gate's pipeline
number when remote). Don't merge and don't remove the worktree: the merge is
the owner's, or the lead's where the project's rules grant it. An agent that
archives never merges.
