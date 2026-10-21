---
max_turns: 60
timeout_seconds: 1500
runs: 3
model: sonnet
allowed_tools: [Agent, Bash, Read, Write, Edit, Glob, Grep, Skill]
---
/opsx:propose remove-item: Add a "remove item" operation to the shelf: removing an item by name takes it off the shelf; removing a name that is not there leaves the shelf unchanged. Plan only, no code. There is no one to ask: decide every detail yourself under the project's rules, and skip live samples and the spec review stage. The change's worktree already exists at `.worktrees/remove-item` under the current directory (branch `wt/remove-item`), as the coordinator makes it: write the change there and nowhere else. When it is written, run in that worktree `openspec validate --all --strict; echo VALIDATE_EXIT=$?` and then `kit spec-check remove-item; echo SPEC_CHECK_EXIT=$?`, and reply with the two lines as printed, nothing else.
