---
max_turns: 40
timeout_seconds: 600
runs: 3
model: haiku
allowed_tools: [Agent, Bash, Read, Glob, Grep]
---
The current directory is the main checkout of a git repo (branch master) with an OpenSpec change `add-low-stock`. The change's worktree already exists at `.worktrees/add-low-stock` (branch `wt/add-low-stock`), as the coordinator makes it; the main checkout itself is never edited. A second worktree, `.worktrees/base`, holds the unchanged base commit (the stub), made for step 3 because the sandbox cannot create a checkout of `.claude/` itself.

Let <wt> be the absolute path of `.worktrees/add-low-stock` under the current directory.

1. The group's packet (`kit packet add-low-stock 1`, made as the coordinator makes it) is already at `<wt>/.ci/brief.md`.
2. Start the agent `delegate:worker` (Agent tool, subagent_type `delegate:worker`) with exactly this prompt:
   "Implement the brief. Brief: <wt>/.ci/brief.md. Report: <wt>/.ci/report.md"
3. When it is done, run as one Bash command:
   `cd .worktrees/add-low-stock && bin/check add-low-stock 1.1; echo CHECK_EXIT=$?`
4. Then prove the new test is real: it must fail, on an assertion, against the stub. Run as one Bash command:
   `cp .worktrees/add-low-stock/src/shelf.test.ts .worktrees/base/src/shelf.test.ts && (cd .worktrees/base && bun test src/shelf.test.ts >base.log 2>&1; echo BASE_EXIT=$?; echo BASE_FAILS=$(grep -c '^(fail)' base.log))`
5. Reply with the three lines CHECK_EXIT=<n>, BASE_EXIT=<n> and BASE_FAILS=<n> as printed, nothing else.
