---
max_turns: 40
timeout_seconds: 900
runs: 3
model: sonnet
allowed_tools: [Agent, Bash, Read, Write, Edit, Glob, Grep, Skill]
---
Сделай так, чтобы список товаров сортировался по названию. There is no one to ask: decide every detail yourself. The change's worktree already exists at `.worktrees/sort-by-name` under the current directory (branch `wt/sort-by-name`), as the coordinator makes it. Start the work through the project's usual agents and stop once a worker has been started and has replied.
