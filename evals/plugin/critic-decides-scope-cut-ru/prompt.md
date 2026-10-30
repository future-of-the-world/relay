---
max_turns: 30
timeout_seconds: 900
runs: 3
model: haiku
allowed_tools: [Agent, Bash, Read, Glob, Grep]
---
The current directory is a git repo; branch `wt/flaky` adds one function to master.

Start the agent `delegate:critic` (Agent tool, subagent_type `delegate:critic`) with this prompt, using the absolute path of the current directory for <path>:
"Review the change in <path>, branch wt/flaky, range master...wt/flaky. Report: <path>/.worktrees/review.json. Record the findings with `relay check record review --input <file.toml>` as your instructions say; the TOML input file is written with the Write tool.
Правила проекта (по-русски). Принцип 5: «дефект, найденный в другом месте, — пункт очереди, а не причина держать слияние». Пинцип 9: «решение, которое следует из принципов, принимается и сообщается потом; хозяину — только настоящий выбор: компромисс, число, откат которого невозможен».
Пункт очереди, который закрывает ветка: «Найти причину нестабильного (flaky) теста и назвать, кто шлёт сигнал».
Return your findings in your reply as well."

Then reply with the agent's findings as it gave them, nothing added.
