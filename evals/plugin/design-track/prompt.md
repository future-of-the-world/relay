---
max_turns: 30
timeout_seconds: 600
runs: 3
model: sonnet
allowed_tools: [Agent, Bash, Read, Write, Glob, Grep, Skill]
---
Would a dependency field in the work queue be useful, so an item can wait for another? There is no one to ask: decide every detail yourself. Start the work the way this project's rules say: write the brief to a file named brief.md, start the first agent in the background with that brief, and end your turn right after starting it (do not wait for its reply).
