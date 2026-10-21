---
max_turns: 25
timeout_seconds: 600
runs: 3
model: haiku
allowed_tools: [Agent, Bash, Read, Glob, Grep]
---
The current directory is a git repo with an OpenSpec change `add-saved-shelf`.

Start the agent `sdd:spec-reviewer` (Agent tool, subagent_type `sdd:spec-reviewer`) with this prompt, using the absolute path of the current directory for <path>:
"Review change add-saved-shelf in <path> (first pass). Report: <path>/.ci/spec-review.md. Return your findings in your reply as well."

Then reply with the agent's findings as it gave them, nothing added.
