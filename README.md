# relay

The system of work for Claude Code: the main session is a front desk that
relays between you and typed agents; every session is measured; two setups
can be compared side by side; the better one is adopted with a record of why.

It carries forward what worked in `~/principles` (the `kit` bindings, the
main-checkout guard, the OpenSpec stage skills, the plugin evals) and adds
what was missing: a ledger, a benchmark, a router, a flow interface, a setup
and migration procedure, and an improvement loop.

## You don't type commands; you type requests

In a Claude Code session, as before:

> try Haiku instead of Sonnet for workers
> make workers plan more and take smaller tasks, compare the results
> what did this week cost?
> ok, adopt it

The `front` plugin recognises a request about the setup itself, loads the
`tune` skill, and the session does the rest: makes a candidate (a profile
change, or an edited copy of a plugin for a change in how a role works),
benches it against the active setup, and tells you the verdict in plain
words with the three numbers that decided it. The commands below are what
it runs; you can run them too.

## The five things the session runs (or you can)

| You want | You type |
|---|---|
| what is running, what it costs | `relay status`, `relay report --today` |
| where the money went this week and what to change | `relay improve suggest` |
| compare two setups on the same work | `relay bench active <candidate>` |
| take the better one | `relay improve adopt <candidate>` |
| a project onto the system | `relay setup <dir>` (new) or `relay migrate <dir> --apply` (existing) |
| a change in how a role works, to bench | `relay candidate <name> --copy delegate`, edit the copy, `relay bench active <name>` |

Everything else is `relay doctor` when something feels off, and `relay help`.

## What it is, physically

One folder, meant to live at `~/relay`: a Python command (`bin/relay`;
needs `python3` 3.11+, `jq`, `git`, nothing to pip-install; the gate adds `uv` and pinned `ruff`, `mypy`, `pytest`: all listed in `deps.toml`), the rules
(`rules/`), the profiles (`profiles/`), and a Claude Code plugin
marketplace (`plugins/`). Nothing is copied elsewhere: Claude Code loads
the plugins from here; `relay sync` writes `~/.claude/CLAUDE.md` and each
project's `CLAUDE.local.md`; the ledger and bench results go to `~/.relay/`.

## Install

Put the folder at `~/relay`, open a Claude Code session there and say
"install relay" — `START_HERE.md` is written for that session. By hand:

```sh
sh ~/relay/install.sh --dry-run    # what is missing or too old, from deps.toml; changes nothing
sh ~/relay/install.sh              # installs it (official installers first: uv's, jq's release binary, `uv python install`, Claude's own; Homebrew or apt-get only as the fallback), then runs `relay doctor`
~/relay/bin/relay install          # global CLAUDE.md, user settings, plugins (registers no project; `relay setup <dir>` adds one)
ln -s ~/relay/bin/relay /usr/local/bin/relay
relay migrate --all --primary      # the plan for every project (plain --all skips primary checkouts, where projects live); then per project: relay migrate <dir> --apply
relay doctor
```

On a Mac, see [docs/macos.md](docs/macos.md) for what slows relay down and how to fix it.

## How it answers the six requirements

1. **Observability and benchmark** — the `observe` plugin writes a ledger of
   every session, prompt, agent, tool call and compaction; `relay report`
   turns transcripts into cost by model, by agent type, by session;
   `relay bench` runs the same scenarios under two profiles and prints
   quality, cost, time and turns side by side with a verdict.
   `docs/observability.md`, `docs/benchmark.md`.
2. **Delegation** — six typed agents by tier, model and effort set by the
   active profile; a brief file per agent so no context is lost; a routing
   guard that enforces it. `docs/delegation.md`.
3. **Pluggable flows** — a flow is a plugin with a `flow.json` (stages,
   triggers, roles, bindings); the project binds one in `kit.toml`; the
   stage hook is generic. OpenSpec ships; a second is a manifest
   and skills. `docs/flows.md`.
4. **Setup and migration** — `relay setup` for a new project (bindings,
   settings, scripts from templates, handover file, rules); `relay migrate`
   lists what an existing project carries and, with `--apply`, moves it
   aside (never deletes). `docs/setup.md`.
5. **Self-improvement** — `relay improve suggest` reads the ledger for
   measured anti-patterns with a saving and a lever each; a candidate
   profile is benched against the active one; `adopt` records the change
   and the bench that justified it; `relay report --compare` checks it in
   real use a week later. `docs/improve.md`.
6. **User-friendly** — the `front` plugin and skill: one reply per request,
   the project first, outcomes in your terms, lettered choices with a
   recommendation, state in `docs/handover.md`, never a paste of agent
   output. Reply length per turn is measured, so it can be benched.

## Layout

```
bin/relay            the command           lib/                 the library (python 3.11, no dependencies)
profiles/            active + candidates   rules/               one rule per file -> CLAUDE.md
plugins/relay         kit, guard, flow hook plugins/observe      the ledger hook
plugins/delegate     agents + route guard  plugins/front        budget + handover hooks, front skill
plugins/openspec      OpenSpec spec steps   evals/plugin         `claude plugin eval` cases (regression)
evals/scenarios      bench scenarios       templates/           files a new project gets
docs/                design and manuals    improve/log.md       every adopted change and why
```

`bin/ci --quick` runs every free test (about 3 s: 16 library tests, 34 hook checks, the eval grader tests); `bin/ci` adds
`claude plugin validate` and the plugin evals. A change of only `rules/*.md` files runs just the rules text tests under
`--quick` (the list is in `lib/relay_textonly.py`); any other file, committed or not, gets the full quick gate.

## State of this build

Built and tested offline on 2026-10-19: the library, hooks and CLI are
covered by tests with synthetic transcripts and a fake `claude`. Not yet run
against a live Claude Code on your machine: the hook input fields are taken
from the current hooks reference (`agent_transcript_path`,
`last_assistant_message`, `scratchpad_dir`, `prompt_cache_likely_expired`),
and the headless flags (`--agents`, `--plugin-dir`, `--append-system-prompt`,
`--max-budget-usd`) from the CLI reference. `docs/handover.md` lists what to
verify first and in what order.
