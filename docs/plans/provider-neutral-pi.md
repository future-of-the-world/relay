# Provider-neutral Relay: initial Pi compatibility research

> Direction corrected by the owner on 2026-10-31: Relay is the development
> principles and shared utility, not Claude Code. Preserve its working Claude
> support and add a specialized Pi adapter by extending setup/install. The
> compatibility findings below remain evidence; the migration/removal framing
> and preference for a pi-code bridge are not an approved implementation plan.
> Research replacing the Workflow runtime while reusing the existing policy and
> cycle semantics. See handover addendum 44 for the owner's exact instructions.

Research date: 2026-10-31. Repository base: c8f75cdc on master. This is a
proposal and an offline compatibility result, **not a completed runtime migration**.

## Decision in plain words

Keep Relay's Python commands, rules, role bodies, queue, gates, worktrees and
records. Run the sessions through Pi, which already handles multiple providers.
Do not replace Relay's workflow with a new framework, and do not put a provider
proxy in front of Claude Code: that would keep the harness dependency.

The closest existing compatibility package is **pi-code**. It can reuse much
more than skills, but installing it alone does not preserve this Relay setup.
Six offline checks against the published pi-code@1.6.1 package exposed specific
contracts to adapt. Recommendation: use it as a reference and possible temporary
compatibility layer; do not enable it globally until those contracts pass.
Recommendation (owner can reverse): first qualify a narrowly filtered pi-code
bridge, because reusing an existing loader and event adapter is the requested
minimal path. Use a Relay-only extension instead only if the contract tests show
that the integration would need a larger maintained shim. The common data and
Python APIs should not depend on that choice.

## Change already made outside the repository

`~/.pi/agent/settings.json` now has:

```json
{
  "defaultProvider": "openai",
  "defaultModel": "gpt-6.1-sol"
}
```

Other settings, including the existing Arsenal package, were preserved. Previously
the default was minimax/MiniMax-M3. `pi --list-models gpt-6.1-sol` lists the OpenAI
model, and a stored OpenAI credential is present. The credential's validity and a
paid model response were not tested. No credential value was displayed.

This changes the startup default, not the model executing an existing session.
Use `/model` to choose `openai/gpt-6.1-sol` in that session. Resumed sessions can
restore their previously selected model.

## What is portable, and what is not

A provider supplies a model; a harness supplies tools, lifecycle events, agents,
permissions and workflow execution. Those are different migration boundaries.
Making a model understand the prompts does not recreate the harness contracts.

| Mechanism and current source | Reuse | Work needed for Pi without Claude models |
|---|---|---|
| Python CLI, queue, worktrees, gate, landing, licenses: `bin/relay`, `lib/` | Keep algorithms and persistent records | Remove direct config-path assumptions; isolate model-dependent steps |
| Rules: `rules/`, `lib/relay_rules.py` | Keep authored rule text | Generate native AGENTS.md targets without overwriting the existing personal AGENTS.md; do not hand-edit generated CLAUDE.local.md |
| Project bindings: `.claude/kit.toml`, `lib/relay_config.py`, `lib/relay_kit.py` | Keep TOML schema and checking parser | One common `.relay/kit.toml` resolver, used by every reader and writer |
| Role bodies: `roles/`, generated `plugins/*/agents/*.md` | Keep authored bodies and region assembly | Translate tool grants; separate provider/model selection from the role text |
| Agent routing: `plugins/delegate/hooks/route-guard.py` | Keep policy and label validation | Normalize Pi's agent/task fields and enforce policy for parallel and chained spawns, not just a single call |
| Main-checkout and shell guards: `plugins/relay/hooks/guard_main.py`, `kit_guard.py` | Reuse tested decision code | Normalize built-in and MCP-backed tool calls; retain fail-closed behavior on timeouts, invalid config and failed processes |
| Read-only and turn guards: `plugins/delegate/hooks/` | Keep policy | Carry role identity and enforce it in child sessions; account for Pi's tool grants and transcript format |
| Merge interception and cleanup: `plugins/relay/hooks/merge.py` | Keep merge semantics | Adapt before/after Bash and session lifecycle events; test against temporary repositories only |
| Additions and flow stage injection: `inject_addition.py`, `flow-stage.py` | Keep content and flow manifests | Replace Claude Skill/Agent event assumptions; expose additions before the relevant run |
| Skills: `plugins/*/skills/*/SKILL.md` | Agent Skills is already portable | Replace Claude-only tool names, aliases, paths, and Workflow assumptions in the bodies; keep support files alongside skills |
| Dynamic change cycle: `plugins/delegate/workflows/cycle.js` | Keep stage order, schemas, stop rules and exit-code handling | Replace Claude's injected `agent()`/Workflow runtime with explicit Pi-backed orchestration; importing the skill is insufficient |
| Review/check attestations: `plugins/relay/hooks/check-mark.py` | Keep verdict parsing and one-writer rules | Persist child results/transcripts and write the same check records; pi-code children use `--no-session` |
| Front: `plugins/front/hooks/` | Keep handover, owner questions and queue/lane policies | Use Pi context/token data, settlement and compaction events; bounded continuation rather than accidental Stop loops |
| Observation: `plugins/observe/hooks/ledger.py`, `relay_transcripts.py`, `relay_analyze.py` | Keep ledger/report interface | Parse Pi session envelopes, toolCall blocks, usage and provider/model identity; do not report unknown usage as zero cost |
| Benchmark: `lib/relay_bench.py` | Keep scenarios, deterministic graders and comparison logic | Add a Pi runner instead of `claude -p`, with cancellation, isolation and result normalization |
| Plugin evals, paid cap and CI: `lib/relay_ci.py`, `relay_paidcap.py` | Keep quality requirements and budget rules | Replace `claude plugin eval/validate` and Claude-only result accounting; preserve free-before-paid ordering |
| Setup/install/doctor: `lib/relay_setup.py`, `deps.toml`, `install.sh` | Keep detection and diagnostic structure | Make harness-specific dependencies conditional; Pi-only installation must not install or require the `claude` binary |
| OpenSpec: `plugins/openspec/` | Keep flow.json, steps and role bodies | Bind portable skills and common agents only for projects opting into this spec method |
| MCP tools | Keep server definitions | Installed Pi 1.4.0 supports native stdio/streamable HTTP MCP; review auth separately, do not add a second MCP adapter by default |
| Historical Claude sessions and prices | Keep read-only access | A legacy import adapter, not a requirement for new Pi sessions |

Renaming the settings file alone is unsafe. Direct readers include `relay_gate`,
`relay_git`, `relay_rules`, `plugins/relay/bin/kit`, and `guard_main.py`; setup,
branch-config comparison and validation also need the same resolver. Existing
agent additions live under `.claude/kit/<role>.md` and must be considered too.

The user's uncommitted profile and critic edits were inspected but not modified.
In particular, changing Pi's default does **not** replace Relay's active
opus/sonnet/haiku/fable selections.

## Existing bridges checked

### pi-code — most complete candidate

- [Repository and README](https://github.com/ilovepixelart/pi-code)
- [Plugin loading](https://github.com/ilovepixelart/pi-code/blob/main/docs/plugins.md)
- [Hooks](https://github.com/ilovepixelart/pi-code/blob/main/docs/hooks.md)
- [Agents](https://github.com/ilovepixelart/pi-code/blob/main/docs/subagents.md)
- Published package inspected: **1.6.1**, npm SHA-1
  `a074ca093afb0ca9409f0a4c5c3e03bf508fe394`.

It loads Claude resources into Pi and is not itself an Anthropic-model bridge.
It supports plugin hooks, command/args hooks, agent frontmatter and multiple Pi
providers. Its broad feature set also adds memory, commands, web tools, goals,
status UI and agent behavior; loading everything may conflict with existing
Arsenal/Pi tools. Select resources only after testing the interactions.

Upstream main documentation is not necessarily the published release. Findings
below use the actual npm tarball, not just README claims.

### Other candidates

| Candidate | What it does | Assessment for Relay |
|---|---|---|
| [harness-bridge](https://github.com/barnuri/harness-bridge) | Shares skills, commands and instructions through links; translates some MCP config | Useful for text resources, not Relay's hooks, agents or Workflow runtime. Some Pi/MCP statements in its README are older than installed Pi 1.4.0 |
| [pi-claude-plugins](https://github.com/ross-jill-ws/pi-claude-plugins) | Imports enabled marketplace skills and commands | No hooks, agents or plugin runtime. Also not a match for Relay's live directory-source plugins without more work |
| [pi-claude-hooks](https://github.com/jordyvanvorselen/pi-claude-hooks) | Maps Claude command hooks onto Pi events | Narrow candidate, but no complete plugin/agent migration. README says timed-out hooks never block: not acceptable as the sole safety layer |
| [pi-claude-bridge](https://github.com/elidickinson/pi-claude-bridge) | Uses Claude Code/Agent SDK as a Pi model provider | Wrong direction for this goal: retains Claude Code and Claude model dependency |
| [pi-subagents](https://github.com/nicobailon/pi-subagents) | Pi children, custom agents and scripted workflows | Possible portable agent runtime, not a drop-in executor for Relay's cycle.js or its hook contracts. Do not stack two subagent systems by default |

None of these packages was installed into the live Pi configuration.

## Offline probe: six checked contracts

Run from the repository with Bun and a reviewed, unpacked pi-code tarball:

```sh
bun evals/compat/pi-code.ts /path/to/unpacked/pi-code/package
```

The probe creates an isolated home/config directory and temporary Git repository,
imports selected package modules (not the extension factories), and deletes its
fixtures afterward. It runs no model calls, no live lifecycle/merge hooks and no
subagents. Like any source import, it executes third-party code: review the
package first. Do not use arbitrary package paths from an untrusted checkout.

Result on pi-code@1.6.1: **all six assertions passed, zero model calls**.
Passing here means the compatibility findings were reproduced, not that Relay
can run unchanged.

1. **Directory-source plugin discovery fails.** A known marketplace and installed
   record pointing to Relay's source folder yield no discovered plugins. The
   loader walks the Claude cache tree. Relay currently loads its live folders,
   not those cache copies; activating old cached copies would run stale code.
2. **Cached plugin hook parsing works.** A synthetic cache entry loads Relay's
   actual core hooks. Plugin-root substitution and the Python command/args form
   survive. This checks parsing only, not every hook's execution semantics.
3. **Main file guard works at the narrow tool boundary.** A Pi built-in edit
   input is translated to an absolute Claude file_path; Relay's actual guard
   rejects it in the fixture's primary checkout. This is not proof for MCP-backed
   Bash/Edit/Write tools, nested calls, children, or every command variant.
4. **Agent input is incompatible.** pi-code uses agent/task fields; Relay's
   routing hook expects subagent_type/prompt/description/model. The fixture
   invoking delegate:worker is interpreted as general-purpose and denied.
5. **Claude model aliases are not a no-Claude guarantee.** The model lookup for
   opus chooses the available Claude model even when an OpenAI model is also
   available. Availability-dependent fallback is not an explicit role policy.
6. **Pi accounting silently disappears in the current parser.** A Pi-format
   assistant entry carrying input/output/cache usage and a nonzero cost produces
   zero requests, zero cost and zero reply characters in relay_transcripts.

Additional source findings, not end-to-end runtime tests: pi-code passes its Pi
session file as transcript_path; child invocation uses `--no-session`, so
agent_transcript_path is absent on SubagentStop; no implementation of Claude's
Workflow tool/injected agent() environment was found. These affect budget,
turn-limit, check-mark, observation and the automated cycle independently of
whether a hook can be launched.

## Minimum migration sequence

1. **Common configuration and model policy.** Add one config resolver and an
   explicit settings migration, covering gates, branch comparisons, guards and
   setup. Move, do not maintain two writable copies. Preserve existing files
   until the move succeeds; refuse conflicting canonical/legacy files rather
   than silently ignoring one. Keep one checked schema and one writer. Make
   `.relay/kit.toml` the common project location; `.pi/` holds Pi adapter settings
   only. Keep credentials in Pi's private user configuration.
2. **Working Pi compatibility slice.** Load Relay's live plugin sources, normalize
   every agent invocation and tool boundary, explicitly bind all roles to
   configured provider/model pairs, and preserve primary-checkout protection,
   merge authorization, read-only roles and check attestations. Resolve whether
   a filtered pi-code adapter or a Relay-only extension is the smaller maintained
   surface using these contract probes, not a feature-count claim.
3. **Cycle and observability.** Replace Workflow execution with explicit Pi-backed
   orchestration and normalize Pi transcripts/usage. Preserve cancellation,
   concurrency bounds, label identity and bounded retries. A model/token limit
   cannot stay hard-coded for an Opus-sized context window.
4. **Bench, evals and installation.** Pi-backed runners must pass the same
   scenarios/graders before removing Claude from required dependencies. Then
   update install/doctor, generated instructions and user documentation. Keep
   historical Claude import optional. No Claude CLI fallback without an explicit
   user selection.

For an initial correctness baseline, bind every role to the requested Sol model;
keep independent per-role provider/model/thinking overrides so cheaper tiers can
be selected later. Do not claim this is the cheapest or quality-equivalent
mapping before benchmarks. A configured model that is missing, unauthenticated
or lacks required capabilities should stop with a useful diagnostic, not fall
back to an available Claude alias.

## Customizing models and providers today

Pi already supplies this; do not build a second credential/model catalog.

- `/login`, `/model` and `/thinking` select available providers and models.
- User defaults: `~/.pi/agent/settings.json`; trusted project overrides:
  `.pi/settings.json`.
- Custom compatible endpoints/models: `~/.pi/agent/models.json`.
- Saved credentials: `~/.pi/agent/auth.json`, never in Relay's repository.
- Nonstandard protocols/authentication: a Pi provider extension.

Pi supports OpenAI-compatible, Anthropic-compatible and Google-compatible
endpoints as well as built-in providers. This does not mean every model can run
every workflow: tool use, structured results, context limits, cancellation and
accounting still need capability checks. Pin provider + exact model identity,
not an ambiguous substring or just an Anthropic tier name.

Local implementation references inspected: installed Pi 1.4.0 README and docs
`configuration.md`, `settings.md`, `models.md`, `models-configuration.md`,
`providers.md`, `skills.md`, `prompt-templates.md`, `packages.md`, `extensions.md`
and `mcp.md` under the installed pi-coding-agent package. The native MCP docs
explicitly describe importing Claude mcpServers entries, with legacy SSE excluded.

## Acceptance before calling this migrated

- A clean environment without a `claude` executable or Anthropic credentials can
  install Relay's Pi mode, pass its free gate and run a complete change cycle.
- Primary checkout, unauthorized merges, protected check/queue records and
  read-only roles stay protected for built-ins, MCP-backed tools and nested calls.
- All configured roles run the exact provider/model requested; no implicit
  Anthropic alias selection or different-model fallback.
- Child completion yields the expected check record, including interrupted,
  capped, failed and background children.
- Pi usage/cost is recorded accurately; missing provider cost metadata is shown
  as unknown rather than a fabricated zero; historical Claude records remain
  readable without being required for new sessions.
- Existing projects migrate their bindings without data loss; gates examine the
  same settings the branch actually executes.
- Front continuation, compaction, owner holds and cancellation retain bounded
  behavior. No provider-specific context assumptions remain in common policy.
- Bench and paid eval decisions no longer require Claude Code's CLI or result
  format. Live paid checks happen only after deterministic checks pass.

## Verified handoff

Worktree: `.worktrees/provider-neutral-pi`, branch `wt/provider-neutral-pi`.
This report and `evals/compat/pi-code.ts` were added in the task worktree, and a
research addendum was appended to its handover. No runtime migration, package
activation, merge or paid check has occurred.
The startup-model change is already active in the user's Pi settings, outside
Git. Primary-checkout user edits remain unchanged.

Exact next step: qualify the filtered pi-code integration with the discovered
agent/source/transcript contracts, and implement the shared settings resolver and
provider-qualified role policy with failing-capable regression tests before
moving live settings or enabling hooks. No wholesale rewrite or bridge activation
is justified by the current six checks.
