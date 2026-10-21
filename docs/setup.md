# Setup and migration

## A new project

```sh
relay setup ~/new-project [--flow openspec|issues|none] [--product|--no-product] [--no-global]
```

Detects the stack (bun, pnpm, mix, cargo, go, python), the default branch,
an `openspec/` folder, issue skills, a screen. Writes what is missing and
never overwrites:

- `.claude/kit.toml` with `[project]`, `[gate]`, `[flow]`, `[delegate]`,
  `[observe]` (and `[issues]` or `[product]` when they apply);
- `.claude/settings.json`: the relay marketplace and the plugins for the
  flow (`core`, `observe`, `delegate`, `front`, + `sdd` / `issues` /
  `product`), `Bash(kit:*)` allowed; a backup beside it;
- `bin/check`, `bin/ci`, `bin/wt` from templates that follow the contract,
  with `TODO` where the stack's commands go;
- `CLAUDE.md` skeleton and `docs/handover.md`;
- the project in `projects.toml`, then `relay sync` writes its
  `CLAUDE.local.md` (never committed);
- `~/.claude/settings.json`: the marketplace and the user-scope plugins
  (skip with `--no-global`).

It ends with a numbered list of what only you can finish (the stack
commands, two lines about the product) and the one Claude Code step
(`/plugin marketplace add ~/relay`, install, restart).

## An existing project

```sh
relay migrate ~/kartoteka            # the plan: what the old setup has, what replaces it
relay migrate ~/kartoteka --apply    # moves the replaced files to .claude/relay-migration/, then setup
relay doctor ~/kartoteka
```

What migration recognises from the principles era:

| old | replaced by |
|---|---|
| `.claude/agents/<project>-worker.md` etc. | `sdd:<role>` (OpenSpec) or `delegate:<tier>`; project-only rules into `.claude/kit/<role>.md` |
| `.claude/skills/<project>-plan` etc. | `sdd:<stage>`; project-only rules into `.claude/kit/<stage>.md` |
| `.claude/hooks/guard-main.sh`, `opsx-stage.sh` + their settings entries | the core plugin (entries removed) |
| `bin/packet`, `bin/spec-check` | `kit packet`, `kit spec-check`; `bin/kit` shim written |
| `*@principles` plugins, the principles marketplace | `*@relay`, the relay marketplace |
| user hooks `context-budget.py`, `session-handover.py` | the front plugin (entries removed) |

Kept as they are: `.claude/kit.toml` (sections added), `.claude/kit/*.md`
additions, project-only skills and agents (ALIX's safety reviewers, run
skills, stack skills), project-only hooks (Kartoteka's `format.sh`).

Revert: `mv .claude/relay-migration/<file> <back>`; the settings backup is
beside the file.

A project that already ran on the principles plugins (Kartoteka) needs only
the settings change and the sections: `relay migrate` finds nothing to move
and does that.

## The whole machine at once

`relay install` does the machine part (global CLAUDE.md, user settings,
`claude plugin marketplace add` + installs, the projects from
`~/principles/projects.toml`). `relay migrate --all` prints the plan for
every imported project and copies the principles library's
`migration/<project>/kit/*.md` drafts into each project's `.claude/kit/`;
`relay migrate <dir> --apply` moves one project. `START_HERE.md` is the
same procedure written for the session that runs it.

## Order for the owner's projects

1. `relay sync --adopt global`; `relay setup --global` happens inside it.
   Start one session anywhere: `relay status` must show it.
2. Kartoteka (already on the plugins): `relay migrate ~/kartoteka --apply`.
3. Clean, Mind, Sight, Glyph, Noisegate (OpenSpec, their own agents):
   `relay migrate <dir>` to read the plan, move the project-only rules of
   each old agent into `.claude/kit/<role>.md` (the migration/<project>/kit
   drafts from principles are the starting point), then `--apply`.
4. Arsenal, linter, testenv (issue flows): `relay migrate <dir>` finds
   `issue-reader/creator/implementer` and `issue-stage.sh` and maps them
   to `issues:read/create/implement/merge`; move the Arsenal-only rules
   (Hard Rules, the preflight script, born-archived OpenSpec) into
   `.claude/kit/<stage>.md`; fill `[issues]` with the `tea` commands.
5. ALIX: as 3, plus keep its safety and funds reviewers; its lead/route
   flow is not a relay flow until it is written as one (docs/flows.md).
6. Glonass repositories: `[issues] attribution = "none"` and the `glonass`
   rule loaded (it is in the active profile).

## Editing roles and agents

A worker in a worktree assembles the agent files with `<worktree>/bin/relay
sync agents` only: never the `relay` on PATH (it is the main checkout's), never
a full `relay sync` (it would render the unmerged `rules/` into
`~/.claude/CLAUDE.md`), and it never sets `RELAY_ROOT`. After the owner-approved
merge, the coordinator runs the full `relay sync` once from the main checkout.

## Rollback of the whole thing

`relay` writes only: `~/.claude/CLAUDE.md` (backup `.before-relay`),
`~/.claude/settings.json` (timestamped backup), per project
`.claude/settings.json` (backup), `kit.toml` (backup when sections are
added), `CLAUDE.local.md`, and the moved files. Restore the backups,
remove the marketplace, and the old system is back; `~/principles` is not
touched.
