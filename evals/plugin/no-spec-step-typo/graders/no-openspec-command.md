---
type: tool_used
tool: Bash
input_match: "(?:\"command\":\\s*\"|[;&|(]|\\\\n)\\s*(?:(?:env|npx|bunx|[A-Z_][A-Z0-9_]*=\\S*)\\s+)*openspec(?:\\s+[a-z-]|\\s*\")|/opsx:"
min: 0
max: 0
---
Spec steps are off in this project (it has an openspec/ folder but no [specs] setting): no openspec command runs. A command that only names the openspec/ folder (`find openspec`, `ls openspec`) is a read of the project's docs, not a spec step: the pattern matches the program `openspec <subcommand>` at the start of a command, or a `/opsx:` command.
