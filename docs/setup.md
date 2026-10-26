# Setup and migration

## A new project

```sh
relay setup ~/new-project [--specs openspec|none] [--off <name@marketplace>]... [--license <SPDX id> [--holder <name>]]
```

Detects the stack (bun, pnpm, mix, cargo, go, python), the default branch,
an `openspec/` folder. Writes what is missing and
never overwrites:

- `.claude/kit.toml` with `[project]`, `[gate]`, `[flow]`, `[delegate]`,
  `[observe]`. A project that already has a kit.toml
  gets only the sections whose value is not what a missing section means: `[specs]` for a method other than `none`;
- `.claude/settings.json`: the relay marketplace and the plugins for the
  flow (`core`, `observe`, `delegate`, `front`, + `openspec`), `Bash(kit:*)` allowed. Relay's plugins the project does not use get `false`, and so does each plugin of
  another marketplace named with `--off <name@marketplace>` (repeat the flag; the id must be one Claude Code's registry
  knows, e.g. `--off gopls-lsp@claude-plugins-official`). A `false` in the project's file beats the user's `true`.
  A key of a plugin relay no longer ships (`issues@relay`, `product@relay`) is dropped and said in the done list, and `relay doctor` reports it until setup runs. A re-run keeps a key that is already there, except where the run's flags or kit.toml decide it; `relay doctor`
  lists the plugins that are off and reports a FIX when `core`, `observe`, `delegate` or `front` is off for the project; a backup of the old file in `<git dir>/relay-backup/` (none when git holds the file unchanged: `git restore` it);
- `bin/check`, `bin/ci`, `bin/wt` from templates that follow the contract,
  with `TODO` where the stack's commands go, and a `CLAUDE.md` skeleton and `docs/handover.md`: all of these only on
  a project's first setup (when it has no kit.toml yet). Later a missing script is a to-do line and a doctor FIX;
- the project in `projects.toml`, then `relay sync` writes its
  `CLAUDE.local.md` (never committed). In a linked worktree setup skips the sync and says so; run `relay sync`
  after the branch is merged. A sync held by a waiting paid run leaves setup at exit 0 with one line;
- the spec plugin (`openspec`) installed at project scope
  with `claude plugin install <name>@relay --scope project`; when that cannot
  run, the command is in the to-do list. `relay doctor <dir>` reports FIX for
  every plugin the project enables that is not installed;
- Nothing in `~/.claude`: `relay setup <dir>` writes only into the project. The user's own files (the marketplace and
  user-scope plugins in `~/.claude/settings.json`) are written by `relay setup --global` (or `relay install`), once per machine;
  a project setup says so in its to-do list when they are missing, and `relay doctor` checks that the marketplace path exists
  and is relay's main checkout, not a linked worktree.
  `relay sync` also writes the profile's session model and effort there, and
  `CLAUDE_CODE_RETRY_WATCHDOG=1` in its `env`: a session keeps retrying through
  a network drop (about three hours) instead of giving up after about 15
  minutes. A value you set by hand for that key is left alone. Claude Code's
  docs do not say whether subagents and workflow agents honour it, and a drop
  after thinking but before any output is re-issued only twice. `relay doctor`
  reports the key when it is missing.

A license is optional. `--license <id> --holder <name>` runs `relay license add`: it writes
LICENSE (an exact SPDX text, bundled in `data/licenses/`), `LICENSES/<id>.txt`, a `REUSE.toml`
with one annotation for `**`, and `[license] id, holder` in kit.toml; without the flag nothing
about licenses is written. `relay license add <id> --holder <name> [--headers code|config|docs]`
does the same later (the one-line `SPDX-License-Identifier` header goes only into the files of the
groups named; never into vendor/, third_party/, node_modules/ or a file that has another id).
`relay gate` runs `relay license check` itself when kit.toml has `[license]` (bin/check is not
edited): it reports a missing or changed LICENSE or LICENSES file, a REUSE.toml that does not
cover `**` with the id, a tracked vendored folder with no annotation or headers of its own, and,
with `headers = [...]` under `[license]`, files of those groups without the header.

It ends with a numbered list of what only you can finish (the stack
commands, two lines about the product) and the one Claude Code step
(`/plugin marketplace add ~/relay`, install, restart).

## `.relay/` in a project, and `~/.relay` on the machine

Two folders with similar names, different jobs:

- **`.relay/`** is committed in a project. `relay setup` writes its `README.md`; it turns on relay's
  hard rules, which act only where the project's default branch has the folder. In it: `queue/` (the
  work queue: one JSON file per item, `fix` or `feature`, highest important points first; `relay queue`, and read-only views in relay's `lib/queue_ext/`: extensions live in relay only, they read, they never write items),
  and `checks/` (per task branch: the gate log, the review, the check and the check mark a hook writes
  when the checker finishes). A merge into the default branch is refused until the branch's last commit
  has its gate, review and check; the pipeline is in `docs/plans/review-gate.md`.
- **`~/.relay`** is per machine and never committed: the ledger and bench results.

`relay setup --relay-folder [<dir>]` writes only `.relay/README.md` (nothing else: no kit.toml, no
settings, no project entry) and does nothing when the file exists. It is the only form to run for relay
itself: plain `relay setup` inside a relay worktree would point every project's plugins at that worktree.
Old projects (Kartoteka, principles) are not given a `.relay/` folder.

## An existing project

```sh
relay migrate ~/kartoteka            # the plan: what the old setup has, what replaces it
relay migrate ~/kartoteka --apply    # moves the replaced files to .claude/relay-migration/, then setup
relay doctor ~/kartoteka
```

What migration recognises from the principles era:

| old | replaced by |
|---|---|
| `.claude/agents/<project>-worker.md` etc. | `openspec:<role>` (OpenSpec) or `delegate:<tier>`; project-only rules into `.claude/kit/<role>.md` |
| `.claude/skills/<project>-plan` etc. | `openspec:<stage>`; project-only rules into `.claude/kit/<stage>.md` |
| `.claude/hooks/guard-main.sh`, `opsx-stage.sh` + their settings entries | the core plugin (entries removed) |
| `bin/packet`, `bin/spec-check` | `kit packet`, `kit spec-check`; `bin/kit` shim written |
| `*@principles` plugins, the principles marketplace | `*@relay`, the relay marketplace |
| user hooks `context-budget.py`, `session-handover.py` | the front plugin (entries removed) |

Run in a linked git worktree, setup names the project after its main checkout and registers that folder, and writes the files into the worktree, so they reach the default branch through that branch's merge.

Kept as they are: `.claude/kit.toml` (sections added), `.claude/kit/*.md`
additions, project-only skills and agents (ALIX's safety reviewers, run
skills, stack skills), project-only hooks (Kartoteka's `format.sh`).

Revert: `mv .claude/relay-migration/<file> <back>`; the settings backup is in
`<git dir>/relay-backup/` (none when git holds the file unchanged: `git restore .claude/settings.json`).

A project that already ran on the principles plugins (Kartoteka) needs only
the settings change and the sections: `relay migrate` finds nothing to move
and does that.

## The whole machine at once

`relay install` does the machine part (global CLAUDE.md, user settings,
`claude plugin marketplace add` + installs). It registers no project;
`relay setup <dir>` adds one. `relay migrate --all --primary` (plain `--all` skips primary checkouts, which is where projects live) prints the plan for
every registered project and copies the principles library's
`migration/<project>/kit/*.md` drafts into each project's `.claude/kit/`;
`relay migrate <dir> --apply` moves one project. `START_HERE.md` is the
same procedure written for the session that runs it.

## Order for the owner's projects

1. `relay sync --adopt global`; run `relay setup --global` once on the machine.
   Start one session anywhere: `relay status` must show it.
2. Kartoteka (already on the plugins): `relay migrate ~/kartoteka --apply`.
3. Clean, Mind, Sight, Glyph, Noisegate (OpenSpec, their own agents):
   `relay migrate <dir>` to read the plan, move the project-only rules of
   each old agent into `.claude/kit/<role>.md` (the migration/<project>/kit
   drafts from principles are the starting point), then `--apply`.
4. Arsenal, linter, testenv (issue flows): relay no longer ships an issues flow; their own issue skills stay project-only until they move to the queue.
5. ALIX: as 3, plus keep its safety and funds reviewers; its lead/route
   flow is not a relay flow until it is written as one (docs/flows.md).
6. Glonass repositories: the `glonass` rule loaded (it is in the active profile).

## Editing roles and agents

A worker in a worktree assembles the agent files with `<worktree>/bin/relay
sync agents` only: never the `relay` on PATH (it is the main checkout's), never
a full `relay sync` (it would render the unmerged `rules/` into
`~/.claude/CLAUDE.md`), and it never sets `RELAY_ROOT`. The coordinator runs the full `relay sync` once from the main checkout
after the wave's paid run is green (it waits until `bin/paid-cost due` prints nothing).

## Rollback of the whole thing

`relay` writes only: `~/.claude/CLAUDE.md` (backup `.before-relay`),
`~/.claude/settings.json` (timestamped backup), per project
`.claude/settings.json` (backup in `<git dir>/relay-backup/`, none when git holds
the file unchanged), `kit.toml` (the same when sections are added), `CLAUDE.local.md`, and the moved files. Restore the backups,
remove the marketplace, and the old system is back; `~/principles` is not
touched.
