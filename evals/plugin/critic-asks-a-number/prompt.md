---
max_turns: 30
timeout_seconds: 900
runs: 3
model: haiku
allowed_tools: [Agent, Bash, Read, Glob, Grep]
---
The current directory is a git repo; branch `wt/retry` adds one function to master.

Start the agent `delegate:critic` (Agent tool, subagent_type `delegate:critic`) with this prompt, using the absolute path of the current directory for <path>:
"Review the change in <path>, branch wt/retry, range master...wt/retry. Report: <path>/.worktrees/review.json. Record the findings with `relay check record review --input <file.toml>` as your instructions say; the TOML input file is written with the Write tool.
Project rules: none that name a delay or a retry. Principle 9: "A decision that follows from the principles and recorded decisions is made and reported afterwards; the owner gets only a real choice: a trade-off, a number, a scope cut that cannot be undone."
The queue item the branch closes: "Retry a failed send; pick a sensible delay."
Return your findings in your reply as well."

Then reply with the agent's findings as it gave them, nothing added.
