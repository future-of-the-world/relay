{{agents_import}}# {{name}}

<!-- Two lines: what this is, for whom. Every message to the owner starts from this. -->
What it is: TODO.

## Principles
<!-- The project's own rules, not the shared ones (those come from relay's CLAUDE.local.md). -->
- TODO

## Commands
- `bin/check <change> <task>`: the quiet check a worker loops on (format, types, lint, the task's own check).
- `bin/ci`: the full gate; prints only what needs attention, log in `.ci/ci.log`.
- `bin/wt new <name> <base>`: a worktree on branch `wt/<name>` under `.worktrees/`.

## Product surface
<!-- Delete this section if no person sees this project. -->
- Medium: TODO (the app on the phone / the page in the browser / the message in the chat)
- Preview: TODO (the skill or command that shows it)
- Reference apps: TODO (two or three leading apps of the kind)

## Workflow
Flow: see `.claude/kit.toml` `[flow]`. State: `docs/handover.md`.
