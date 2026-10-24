---
max_turns: 40
timeout_seconds: 900
runs: 3
model: sonnet
allowed_tools: [Agent, Bash, Read, Write, Edit, Glob, Grep, Skill]
---
Make the stock list sort by name. There is no one to ask: decide every detail yourself. The change's worktree already exists at `.worktrees/sort-by-name` (branch `wt/sort-by-name`). Plan only, no code: stop when the spec step has written the change.
