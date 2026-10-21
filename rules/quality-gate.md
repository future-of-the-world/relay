# Quality gate
> A worker loops on the quiet check; the full gate is green before a branch is reported done; a flaky test is a bug, proven fixed with max(20, ⌈3/p⌉) clean runs.

- Two commands, named in the project's file: a quiet check a worker loops
  on (format, types, lint, the task's own check) and the full gate (all
  tests, build, end-to-end). The gate prints only what needs attention and
  keeps the full log in a file. It is green before a branch is reported as
  done.
- **Flaky tests are unacceptable.** A test that fails and then passes on a
  rerun is a bug, never "a flake, passed alone". Whoever sees it reports the
  test's name and file; the coordinator starts a fix at once in its own
  worktree. Tests wait on a condition (a locator, an effect, a returned
  value), never on time or a longer timeout; time in unit tests is driven by
  hand; each test owns its state; suspect the code under test first.
  Reproduce the flake under load and measure its failure rate p, then prove
  the fix with at least max(20, ⌈3/p⌉) clean runs under the same load.
- **Find the cause before running more.** For a flaky test or eval, analyse
  in this order: state shared by several actors (an actor is any single act
  that reads or writes: a test, a hook, a process, a run); a slow
  environment, timeouts and turn limits; races; for an agent, a changed
  output form (its reply got longer, shorter or differently worded than the
  grader expects); model sampling last. Clean runs prove a fix; they do not
  find the cause. "You need more analysis of cause rather than more runs."
- After editing a hook or a script, run its own test.
