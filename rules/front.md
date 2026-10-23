# Front desk
> The main session stays under 400k tokens, updates the handover file at 350k, spans one change; every reply stands alone, one screen, plain words, numbered choices. Load the `front` skill at the start of a coordinating session.

- The coordinating session stays under 400k tokens. At 350k (the hook says
  so), after a merge, or after about 150 tool calls: bring `docs/handover.md`
  up to date (state, decisions and who made them, the owner's latest
  instructions verbatim, open questions, the exact next step, paths in
  progress), then continue; compaction happens by itself and the file is
  named to you after it. Read it again before acting. Never ask the owner to
  /clear or to repeat anything.
- A session spans one change or one phase of it, never a week: after a merge
  or an archive, update the handover file and start the next change fresh.
- Large results stay out of the session: a pull request, a pipeline, an
  issue, a test run go to a runner that replies in 3 lines. A job over about
  30 minutes (the paid `bin/ci`) is the front's: Bash `run_in_background` into
  a scratchpad log, read by its last lines when it exits.
- Use `git -C <worktree>`, not `cd`, so the project's instruction files are
  not loaded again.
- Every reply stands alone: the project and what it does first; outcomes in
  the owner's terms, not branch, file or agent names; at most one screen;
  detail in a named file. Questions numbered, options lettered, the
  recommendation first with the difference made visible. Critique the owner's
  picks once, plainly, then build them. Say what is running and why, once.

### Compact Instructions

When compacting, write the summary as a handover report: where the work
stands, the decisions made and who made them, the owner's most recent
instructions verbatim, open questions, the exact next step, and the paths of
the handover file and of the files in progress.
