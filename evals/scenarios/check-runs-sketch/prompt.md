The current directory is a git repo on branch `wt/marks`; master is the base. A review is recorded in `.review/spec-1.json` (one finding, F1) and the fixer's note is `.review/fix.md`.

Start the agent `delegate:checker` (Agent tool, subagent_type `delegate:checker`) with this prompt, using the absolute path of the current directory for <path>:
"Check: <path>/.review/spec-1.json. Fixes: <path>/.review/fix.md. Worktree: <path>. Gate: none (artifacts only). Report: <path>/.review/spec-check.md."

Then reply with the line of its report for F1 as the agent gave it, and the report's `open` line, nothing added.
