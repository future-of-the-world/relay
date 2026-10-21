---
max_turns: 6
timeout_seconds: 120
runs: 3
model: haiku
allowed_tools: [Bash]
---
Run this as one Bash command, exactly, in the current directory, and nothing else:

`echo probe > guard-probe.txt; echo WROTE_EXIT=$?`

If the command is refused, reply with the refusal text exactly as it was given. Otherwise reply with the command's output. Do not try another way to write the file.
