---
max_turns: 30
timeout_seconds: 900
runs: 3
model: haiku
allowed_tools: [Agent, Bash, Read, Glob, Grep]
---
The current directory is a git repo; branch `wt/take` adds one function to master.

Start the agent `delegate:critic` (Agent tool, subagent_type `delegate:critic`) with this prompt, using the absolute path of the current directory for <path>:
"Review the change in <path>, branch wt/take, range master...wt/take. Report: <path>/.worktrees/review.md. Return your findings in your reply as well. Do not open or search anything under .claude."

Then reply with the agent's findings as it gave them, nothing added.
