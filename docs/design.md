# Design: relay

Decided 2026-10-19 from the `~/principles` bundle (rules, plugins, hooks,
project memories, the bridge document) and the current Claude Code platform.

## The problem, in the owner's measurements

- 1,069 subagents in one day, 81% of the day's cost; most of it build and
  plan agents on Opus (2026-10-12).
- 272 `general-purpose` agents in three days, about $18 a day of re-read
  tool definitions (16–18 Oct).
- Agent leads that waited reloaded their context 177 times, a third of
  what leads cost; requests above 300k and reloads of big sessions cost
  about $27 a day.
- Cache reads are 54% of spend and cost the same on every model; moving an
  agent from Opus to Sonnet saves its writes and outputs only.
- Rework, stale agents, oversized coordinator context, decisions the owner
  could not see (the bridge document's list).

The old system fixed these by rules the model had to remember, measured by
hand, with no way to compare two setups except by living with one for a
week. Relay keeps the rules that worked and moves the enforcement into hooks,
the measurement into a ledger, and the comparison into a command.

## Shape

```
owner ──► front (main session: talks, routes; opus; thin)
               │ brief file (scratchpad/briefs/<name>.md)
               ├──► scout   (haiku, low)    reads, answers file:line
               ├──► runner  (haiku, low)    runs, answers 3 lines
               ├──► worker  (sonnet, med)   builds in a worktree, loops on check
               ├──► fixer   (sonnet, med)   fixes listed findings
               ├──► thinker (opus, high)    designs, writes one file
               └──► critic  (opus, high)    reviews, writes findings
          10-line hand-back + report file
```

Around it:

- **observe**: hooks on nine events write `~/.relay/ledger/<day>.jsonl`.
  Transcripts (which already carry per-request model and token usage,
  main and subagents) are the source of cost; the ledger adds what
  transcripts lack: agent start/stop times, tool durations, compactions,
  what the owner typed (its size), and `agent_type` for every agent.
- **delegate**: the six agents, the routing guard (PreToolUse on Agent),
  the `delegate` skill (who does what, the brief template).
- **front**: the budget hook (handover note at 350k, wrap note for agents
  over 200k), the handover pointer after compaction, the `front` skill.
- **relay** (named core before 28 Oct): unchanged from principles (`kit`, guard, addition injection)
  plus the generic flow stage hook.
- **flows and spec methods**: `openspec` (opt-in spec steps) is a plugin with `flow.json`; the work-flow slot (where work comes from) has no plugin today.
- **profiles**: one `active.toml` and candidates; a profile is the whole
  setup (front model, tier models and efforts, rules loaded, plugins on,
  guard thresholds). `relay sync` applies it; `relay bench` compares two.

## Decisions and why

**One bindings file, `kit.toml`, kept.** Relay adds sections to it (`[flow]`,
`[delegate]`, `[observe]`) rather than introducing `relay.toml`. Kartoteka
and every migrated project keep their file; `kit get` keeps working; the
`.claude/kit/<role>.md` additions keep being injected (now for `delegate:`
and `front:` roles too).

**Plugins keep their names, except the spec plugin (and, on 28 Oct, `core`, which became `relay`; the marketplace became `amidman`).**
The marketplace is renamed `relay` because its source directory moves;
`relay setup` rewrites `*@principles` to `*@relay` in a project's settings.
The plugin first named after its method is renamed `openspec`: the earlier
decision not to rename plugins is replaced by the owner's words of 24 Oct 2026:

> мы изымаем написание спецификаций из общего пайплайна и даем опцию включить дополнительные шаги для написания спецификации, так же то что это называется sdd меня тоже не устраивает - это фактически openspec, если мы придумаем новый способ писать спецификации и захотим добавить его в relay мы добавим его рядом с openspec

**Enforce in hooks what used to be rules.** No general-purpose agents, no
forks from big sessions, no Opus for build agents without an escalation
line: a `PreToolUse` deny with the alternative named. The rules text shrinks
by 30% (every token of it is re-read by every agent on every request) and
the behaviour no longer depends on the model remembering.

**Effort is a knob before model is.** Claude Code agents take `effort:
low|medium|high|xhigh|max`. A scout at `haiku, low` is cheaper than a
scout at `haiku, high`; a critic at `sonnet, xhigh` is a candidate worth
benching against `opus, high` (profiles/candidates/sonnet-judge.toml).

**The front stays on Opus.** By the owner's own measurement cache reads
cost the same on every model and the front's output is small; what Opus
buys there is judgment in routing and in talking to the owner, which is
the product. The candidate `sonnet-front` exists to test this, not to
assume it.

**Transcripts are the cost source; the ledger is the timeline.** Both
exist without OpenTelemetry, a collector, or a dashboard. `relay report`
reads the last N days in a second. OpenTelemetry stays available for a
team later (`docs/observability.md`).

**Benchmarks use Claude's own cost figure.** A headless run prints
`total_cost_usd` and per-model usage; the bench records that, not an
estimate. The ledger's dollar figures are estimates from `prices.toml` and
say so.

**A profile is applied by rewriting agent frontmatter.** `relay sync`
writes `model:` and `effort:` into `plugins/delegate/agents/*.md` (the
`relay-tier` key marks each) and into installed copies. A session started
after that runs the new models. No `model:` in skills, ever (a skill that
sets the model switches the whole session).

**Flows are manifests.** `flow.json` declares stages, triggers, roles and
required bindings; the stage hook and `relay doctor` read it. Adding a
flow touches no code.

**Migration never deletes.** `relay migrate --apply` moves replaced files
to `.claude/relay-migration/`; the revert is `mv`.

**Adoption is logged.** `relay improve adopt` copies the previous active
profile to `profiles/history/`, appends to `improve/log.md` with the bench
reference and the reason, and syncs.

## What is enforced where

| Behaviour | Where | How |
|---|---|---|
| no general-purpose agents | delegate hook | PreToolUse deny |
| no fork over 100k | delegate hook | PreToolUse deny |
| Opus only for thinker/critic (or `Escalated:`) | delegate hook | PreToolUse deny |
| cap on parallel agents, brief for long prompts | delegate hook | note, not deny |
| handover at 350k, agent wrap at 200k | front hook | note |
| handover file after compaction | front hook | SessionStart context |
| main checkout clean, no stash, no secrets printed | core guard | PreToolUse deny |
| project additions reach shared roles | core hook | SubagentStart / Skill / prompt |
| the stage skill for a flow command | core flow hook | UserPromptSubmit context |
| the `tune` skill for a request about the setup | skill description | the model reads intent; measured by evals/plugin/tune-* |
| one reply per request, plain words, choices | front skill + rules | text; measured as reply length |
| tiers, brief files, two review passes | delegate skill + rules | text; measured in the ledger |

**No router model.** ALIX's Jev routed messages to leads with a model
call per message. The front session already reads every request and is the
one place that knows the conversation; it routes. The hooks decide the
mechanical part (which stage skill, which tier is allowed) without a model.

## What relay does not do

- It does not run agents as separate sessions (the old "leads" idea). A
  coordinator that must wait is a session the owner starts; the front
  tells the owner when that is the cheaper shape.
- It does not decide for the owner what a person sees: the product rules
  and the `product` plugin are unchanged.
- It does not ship a dashboard. `relay report` is text; the ledger is JSONL
  for anything else.
