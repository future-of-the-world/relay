# START HERE

For the Claude Code session the owner points at this folder with something
like "install relay" or "migrate me from principles". The owner writes
short requests; you do the steps and report in plain words. Ask only what
is listed under *Ask the owner*.

## What relay is

A folder (this one), meant to live at `~/relay`: a Python 3.11 command
(`bin/relay`, no dependencies beyond `python3`, `jq`, `git`), a rules
library (`rules/`), profiles (`profiles/`), and a Claude Code plugin
marketplace (`plugins/`, manifest in `.claude-plugin/marketplace.json`).
Nothing is installed anywhere else: Claude Code loads the plugins from
this folder, `relay sync` writes `~/.claude/CLAUDE.md` and each project's
`CLAUDE.local.md`, and the ledger goes to `~/.relay/`.

## Install (one session, about ten minutes)

1. Put the folder at `~/relay` (`mv`, or `git clone`). Run
   `~/relay/bin/relay doctor` to see the machine's state.
2. `~/relay/bin/relay install` — writes the global CLAUDE.md (the old one
   is kept as `CLAUDE.md.before-relay`), registers the marketplace and the
   four user-scope plugins in `~/.claude/settings.json`, removes the two
   user hooks the front plugin replaces, imports the projects from
   `~/principles/projects.toml`, and runs `claude plugin marketplace add`
   and `claude plugin install` when `claude` is on PATH. It prints what it
   did and what is left.
3. Put `relay` on PATH: `ln -s ~/relay/bin/relay /usr/local/bin/relay`
   (ask first; it needs the owner's shell or sudo).
4. Restart Claude Code. In the new session: say "what is running?" — the
   front should run `relay status`; then `relay doctor`.

## Migrate the projects

5. `relay migrate --all` — for every imported project: copies the
   principles library's `migration/<project>/kit/*.md` drafts into the
   project's `.claude/kit/` (where absent), prints what the old setup has
   (prefixed agents, stage skills, hooks, scripts) and what replaces it.
   Nothing moves yet.
6. For each project, in the owner's order (Kartoteka first: it is already
   on the plugins): `relay migrate <dir> --apply`, then `relay doctor
   <dir>`. Old files go to `.claude/relay-migration/`, never deleted.
   Project-only rules of an old agent that the drafts do not carry: move
   them into `.claude/kit/<role>.md` by hand (a worker from a brief).
7. `relay sync`. Open the project in Claude Code, run one small real
   change through its flow (`/opsx:propose` or "#123"), confirm the stage
   line appears and agents are `sdd:*` / `delegate:*`.

## Ask the owner

- Before step 3 (a symlink in /usr/local/bin needs them).
- Before each `--apply` in step 6: name the project and what moves.
- When a project has open `wt/` branches that edit files the migration
  moves (`git branch --list 'wt/*'`): merge first, or the owner decides.
- Nothing else. Everything inside the steps is decided here and reported.

## After

- A week of use, then `relay improve suggest`: the first findings on
  real data are the first candidate.
- The handover for the next session: `docs/handover.md` (what is verified,
  what is not, open items).
