# core

Part of the relay repository (`~/relay`), unchanged from the principles library except for the flow stage hook (`hooks/flow-stage.py`, see `docs/flows.md`) and the addition injection, which serves the agents and skills of `core`, `openspec`, `product`, `delegate`, `issues` and `front` (`.claude/kit/<name>.md`) and, at an agent's start, the project's rules for its role (`.claude/kit/<role>.md`, role one of lookup, run, build, fix, think, judge; the agent's own file wins where they differ). The text below is the original reference.


**How shared agents and skills run the plugin's scripts (tested 2026-10-19,
Claude Code 2.1.302, project-scope install from a local directory marketplace,
`claude -p --model haiku`):**

- A plugin's `bin/` folder is on PATH for the Bash tool. `kit` is therefore
  called by its bare name in agent and skill text: `kit get gate.check`,
  `kit packet <change> <task>`, `kit spec-check <change>`. `command -v` showed
  the path inside the installed plugin.
- `${CLAUDE_PLUGIN_ROOT}` is substituted in skill text (the skill printed the
  plugin's directory). Agent text was not confirmed (the probe agent did not
  quote its instructions), so agent text uses `kit`, never the variable.
- Hooks use `${CLAUDE_PLUGIN_ROOT}` in `hooks/hooks.json` and reach `kit` as
  `../bin/kit` from their own folder.

Install (from the local marketplace; the owner's `claude plugin marketplace add ~/principles` first):
`/plugin install core --marketplace ~/principles`. Also `openspec`;
it needs `core` (their agents and skills start with `kit get ...`, which exists
only while core is enabled), so enable core wherever you enable them.

Needs Python 3.9+ (kit and the hooks run on macOS /usr/bin/python3; only the `relay` command itself needs 3.11+ for `tomllib`), `jq`, and bash. Bindings: `.claude/kit.toml`
of the project (`migration/kartoteka/kit.toml` is a full example; `kit dump`
prints the parsed file). A project with no `.claude/kit.toml` is an error for
every `kit` command but `path` (exit 1, naming the file); `--default` covers a
missing key in an existing file, never a missing file.

**Permissions.** Every shared agent calls `kit`, so a project allows it in its
`.claude/settings.json`: `Bash(kit:*)`. Without it each agent's first Bash call
waits on a permission prompt (a background agent stops there).

`kit path <plugin>/<file>` prints the absolute path of a file shipped in a
plugin (`kit path product/scripts/measure.mjs`, `kit path openspec/skills/plan/SKILL.md`).
It resolves the version this project runs, never "the newest": a source
checkout beside core first; then Claude Code's `installed_plugins.json` (the
`project`/`local` entry whose `projectPath` is this project or its main
checkout, else the `user` entry); then the same version as the running core.
When nothing matches it is an error. (`KIT_INSTALLED_PLUGINS` overrides the
registry's location, for tests.)

## What core holds, and what it does not

Core is for every project: the `kit` helper, the main-checkout guard and the addition
injection. It ships no agents. The generic `worker` and `reviewer` (for projects
that do not enable the `openspec` plugin; they take a brief file and reply in a few lines,
and know nothing of OpenSpec) are personal agents: one source in the library's
`agents/`, written to `~/.claude/agents/` by `bin/principles sync` (with the
generated-file marker; a hand-written file there is never overwritten without
`--adopt agents`). A project with spec steps on uses `delegate:worker` and
`delegate:critic` like any other. The stage hook (`/opsx:*` names its stage
skill or note) is core's and reads `[flow] kind` and `[specs] method`.

**The name `kit`.** `kit` is a common command name (KitOps ships a `kit` CLI). Claude
Code puts a plugin's `bin/` on the Bash tool's PATH after the user's own entries
(verified 2026-10-19: with a fake `kit` first on PATH, an agent's `kit get ...` ran
the fake), so another `kit` would silently take over every agent's call.
`tests/kit-name.test.sh` fails when one exists on this machine's PATH (none does).
A rename was weighed and deferred: it touches every agent and skill text, every
project's `Bash(kit:*)` permission and the migration script.

## Project additions are injected

A project keeps its rules for a shared role in `.claude/kit/<role>.md`. Core's
`hooks/inject-addition.sh` hands that file to the agent or session itself, so
no agent has to obey a "read your addition" line:

- `SubagentStart`: for an agent `<plugin>:<role>` (`agent_type`), the file
  becomes the agent's additional context at its start;
- `PostToolUse` with matcher `Skill`: for the skill `<plugin>:<role>`
  (`tool_input.skill`), the file reaches the session right after the skill loads
  through the Skill tool;
- `UserPromptSubmit`: for a stage the owner types as a slash command
  (`/openspec:archive ...`: the prompt starts with `/<plugin>:<role>`). No Skill call
  happens then, so the second hook never fires; this one covers it. (Verified
  live 2026-10-19: without it a typed `/openspec:archive` returned no addition.)

Only the framework's own plugins are served: `core:`, `openspec:`, `delegate:` and `front:`
names. Another plugin's `code-reviewer` never receives a project's
`code-reviewer.md`. The hooks reach Claude Code's sessions; one thing is not
verified: whether the text survives an automatic compaction of a long session.

The project root is the git top-level of the hook's cwd (inside a worktree, that
worktree's own root); no file means nothing is injected. An addition wins where it
differs from the shared text. A rule an agent needs while serving a stage (the
author's wave-planning rules, say) goes in that agent's own addition
(`.claude/kit/author.md`), not in the stage skill's. Both hook inputs were
verified on Claude Code 2.1.302 (`UserPromptSubmit` on 2.1.303).

## Scripts outside Claude

`kit` is on PATH only for Claude's Bash tool. A project script that must run in a
terminal or in CI (its `bin/ci` calling the spec check, say) copies
`templates/kit-shim` to `bin/kit` and calls `bin/kit spec-check --path
openspec/specs`. The shim finds core by `$KIT`, else the core installed for this
project (the registry, as `kit path` does), else a source checkout
(`$PRINCIPLES_DIR`, default `~/principles`), and says what to do when it finds none.
It needs Python 3.9+ on PATH (the `relay` command itself needs 3.11+). Tested by `tests/shim.test.sh`.

## The check-script contract

`gate.check` is the project's own script (the stack differs), but the shared
`delegate:worker` and `delegate:fixer` rely on all of the following. A project's script
follows it, and `tests/check-contract.test.sh` proves it (the eval fixture's
`bin/check` is the reference implementation; run the test against a project's own
script with `KIT_CONTRACT_PROJECT=<clean checkout>`).

Forms (the script is `<check>`):

| Call | Meaning |
|---|---|
| `<check> <change> <task>` | the task's own checks: the project's quick steps on the changed files (format, typecheck, lint, as the stack has them), then the task's `Check:` command from `openspec/changes/<change>/tasks.md` |
| `<check> <change> <task> --failed` | a rerun after a failure: the test files that failed last round run first, for a fast answer, then the whole check, so a pass always means all of it. With no failed list it is the plain run |
| `<check> --tests <file>... [--failed]` | review-fix mode: the quick steps, then these test files (or filters) instead of a task's `Check:` |

Behaviour:

1. **Quiet.** Green: one line saying `passed` (plus the time note). Red: only the
   first findings (about 30 lines) and the failed test files, then the failure
   line `FAILED at <step> (round N of 3; log: <path>)`. The full output is in
   `.ci/check/<key>.log` (key `task-<task>`, or `tests-<hash>`); state files
   (`<key>.fails`, `<key>.started`, `<key>.failed-tests`) live beside it.
2. **Exit codes.** 0 only when green. 1 when the check failed (a hang and a
   spent budget are failures). 2 for a usage error, an unknown change or task, or
   a task with no `Check:` command; nothing was run.
3. **Round budget.** Each failure adds one to the task's counter; the third in a
   row also prints a line with **`BUDGET SPENT`** and the order to stop fixing.
   A pass deletes the counter. The workers stop at this word.
4. **Hang.** The check runs under a timeout (`CHECK_TIMEOUT` seconds, default
   300; a project may also accept a name with its own prefix). Past it, the whole
   process group is killed, a line with **`HUNG`** is printed, and it counts as a
   failure.
5. **Time budget.** Every run, green or red, prints the minutes since the task's
   first check; once they reach `CHECK_WORKER_MINUTES` (default 40) it also
   prints a line with **`TIME BUDGET SPENT`**. Workers stop at this word too.
6. **Own ports.** A check that starts a server (end-to-end tests) gives each run a
   free port of its own, so workers in different worktrees never share one.
7. **Where it runs.** From any folder of a checkout; it works at that checkout's
   root, so a worktree gets its own state.

The stop words are exactly `BUDGET SPENT`, `HUNG`, `TIME BUDGET SPENT`.

## What `guard-main` does

`hooks/guard-main.sh` (PreToolUse on Edit, Write, MultiEdit, NotebookEdit and Bash)
keeps the main checkout clean and secrets out of the output. Tests:
`tests/guard-main.test.sh`.

- **Writes by file tools** inside the main checkout, outside the worktrees folder.
- **Writes through the shell** in the main checkout: a redirect or heredoc, `tee`,
  `sed -i`, `perl -i`, `cp`, `mv`, `rm`, `touch`, `mkdir`, `ln`, `install`,
  `truncate`, `find -delete`, `xargs rm`, `rsync`, `patch`, `tar -x`, `unzip`,
  `curl -o`, `wget -O`, `dd of=`. A git-ignored target (`.ci/` logs) is let through.
  Option values are not paths (`touch -t 202601010000 f`, `install -m 755 a b`,
  `mkdir -m 755 d`), and `$(( ))` / `(( ))` arithmetic is no redirect. Not seen: a
  write made by a program's own code (`python3 -c "open(p, 'w')"`, `node -e`).
- **Mutating git** in the main checkout, decided from the parsed words, so
  `git -c k=v commit`, `time git reset`, `nohup git checkout -b x`,
  `bash -c "git commit"`, `eval` and `... | xargs git reset` all count; also
  `branch -f/-D/-m`, `tag -d/-f`, `update-ref`. Not blocked: `git merge --ff-only
  wt/<name>` (the front's merge of a ready branch), `--help`. And the project's
  `[[guard.block]]` commands.
- **Compound commands** are split into their simple commands (`;`, `&&`, `||`,
  `|`, newlines, subshells, quotes and heredocs understood), and each part is
  judged by the directory it runs in: the tracked `cd` / `pushd` / `popd` / `cd -`
  (a directory it cannot know counts as the main checkout), overridden by its
  `git -C` or a target flag's value. `git -C wt/a log && git merge x` still blocks the merge.
  Shell variables are not followed: an unquoted `$S/f.md` is taken literally, as a
  path under the current directory (refused in the main checkout), while a quoted
  `"$S/f.md"` is skipped (a write to it is not refused, even when it lands in main).
  The guard catches slips, not a determined bypass.
- **Anywhere:** an anonymous `git stash` (bare, `-u`, `push` without `-m`), every
  `git stash pop`; shell tracing; verbose curl on an authenticated request; and
  environment dumps (`env`, `printenv`, `export -p`).
- **A guard that cannot read its bindings blocks**, with the reason: a
  `.claude/kit.toml` that does not parse, `jq` or `python3` missing. It never
  silently drops the project's rules. (A project with no kit.toml at all gets the
  generic rules.)

## Every binding key

"Required" means a missing key stops the reader with an error naming it (the
shared files call `kit get <key>` without a default). A key with a default
works when absent. A section marked "if X" is required only when X applies.
Patterns are regular expressions: Python `re` in `packet.*` and `spec_check.*`,
ERE (`grep -E`) in `guard.*`. In `packet.*` a pattern is searched anywhere in the
path (write `^` to anchor it); `files` and `files_exclude` work the same way.

| Key | Required or default | Meaning | Example |
|---|---|---|---|
| `project.name` | informational | project name | `"kartoteka"` |
| `project.default_branch` | required | branch worktrees start from and merge into | `"master"` |
| `project.worktrees` | required (guard: `.worktrees`) | folder of the project's worktrees | `".worktrees"` |
| `project.stack_skills` | required (may be `[]`) | skills a worker or fixer loads | `["ts-dev"]` |
| `gate.wt` | required | worktree tool: `new <name> <base>`, `rm <name>`, `ls` | `"bin/wt"` |
| `gate.check` | required | the quiet loop; follows "The check-script contract" below (three forms, exit codes, round budget, `HUNG`, time budget) | `"bin/check"` |
| `gate.ci` | required | the full gate; prints only what needs attention | `"bin/ci"` |
| `gate.ci_quick` | none (a plain `relay gate` runs `gate.ci` as it is) | the free mode of the gate, run by a plain `relay gate`; `relay gate --paid` runs `gate.ci` | `"bin/ci --quick"` |
| `gate.ci_log` | required | file holding the full gate log, read by fixers | `".ci/ci.log"` |
| `gate.final` | `local` | where the final gate runs: `local` (here) or `remote` (CI pipeline on the pushed branch) | `"local"` |
| `coordination.mode` | `leadless` | `leadless`, `single-lead` or `multi-lead` | `"leadless"` |
| `product.medium` | required if the project has a person-facing surface | what the person looks at | `"the site on a phone"` |
| `product.run_skill` | required if `[product]` | project skill that launches the app | `"kartoteka-run"` |
| `packet.module` | none (module refs off) | module-contract kind: `typescript`, `rust` or `elixir` | `"typescript"` |
| `packet.install_hint` | `install the project's dependencies` | said when the compiler is missing | `"run \`bun install --frozen-lockfile\`"` |
| `packet.module_dirs` | `["lib", "test/support"]` (elixir) | folders searched for a module | `["lib"]` |
| `packet.max_source_files` | `4` | most source files one task lists (unless `Size: mechanical`) | `4` |
| `packet.source` | none (size not checked) | regexes of source files | `['^src/.+\.tsx?$']` |
| `packet.source_exclude` | none | regexes removed from `source` | `['\.test\.tsx?$']` |
| `[[packet.required_test]]` | none | a kind of test a task must name when it lists matching files: `kind`, `files` (regexes; group 1 = name), `files_exclude`, `waiver` (allow `<kind> none (<reason>)`), `command` (`{name}`), `name_dash`, `missing` and `brief` (message and brief templates with `{item}`, `{kind}`, `{title}`, `{name}`) | see Kartoteka's `e2e` |
| `[[spec_check.group]]` | none (form check only) | a kind of requirement that needs failure scenarios: `name`, `trigger` (regex on name and prose), `[…cases]` table of `"Case title" = 'regex'` | see Kartoteka's `stored data` |
| `guard.target_flags` | `[]` | flags whose value is the directory a command acts on | `["--cwd"]` |
| `guard.secret_patterns` | `[]` | more ERE patterns marking a curl as authenticated | `["X-Auth"]` |
| `[[guard.block]]` | none | commands blocked in the main checkout: `pattern` (ERE, `{start}` = where a command can start), `unless` (ERE), `reason` | `pattern = '{start}bun[[:space:]]+add'` |

## Tests and the gate

`tests/*.test.sh`, all run by the library's `bin/ci` (`bin/ci --no-evals` ends
`ci: green (QUICK MODE: evals skipped, not a release gate)`; only the full gate,
with the evals, may release). `tests/hooks-live.test.sh` is the hook smoke test: four
`claude -p --model haiku` calls (about 10 s, a few cents) prove in a real session that a
typed `/openspec:archive` and the `openspec:author` agent get the project's additions and that the
guard refuses a shell write in main but not in a worktree; it is skipped, loudly, when
`claude` is missing or `HOOKS_LIVE=0`. `tests/packet.test.sh` installs its own TypeScript
compiler from `tests/ts-deps/` (pinned by `bun.lock`) on first run.
