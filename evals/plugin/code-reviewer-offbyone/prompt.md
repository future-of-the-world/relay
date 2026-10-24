---
max_turns: 30
timeout_seconds: 900
runs: 3
model: haiku
allowed_tools: [Agent, Bash, Read, Glob, Grep, Skill]
---
The current directory is a git repo; branch `wt/paging` adds one function to master.

Start the agent `delegate:critic` (Agent tool, subagent_type `delegate:critic`) with this prompt, using the absolute path of the current directory for <path>:
"Review the change in <path>, branch wt/paging, range master...wt/paging. Report: <path>/.ci/code-review.json. Return your findings in your reply as well."

Then reply with the agent's findings as it gave them, nothing added.
