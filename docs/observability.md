# Observability

Two sources, one command.

## Transcripts: where the money is

Claude Code writes every session to `~/.claude/projects/<slug>/<session>.jsonl`
and every subagent to `<slug>/<session>/subagents/agent-<id>.jsonl` (with
`agent-<id>.meta.json` naming the agent type). Each assistant line carries
the model and the token usage of its request: input, cache write, cache
read, output. `lib/relay_transcripts.py` reads them (one request counted
once by `requestId`), `lib/relay_prices.py` prices them from `prices.toml`,
and `lib/relay_analyze.py` aggregates.

`relay report [--since 7d | --today | --session <id>]` prints:

- the period: sessions, agents, your turns (what you typed: background-agent
  notifications and compaction summaries are not turns), estimated cost, the agents'
  share, cost per turn, average reply length, compactions;
- by model: requests and the four token kinds;
- by agent type: count, models, requests, average largest context, cost, share;
- the 15 most expensive sessions;
- the top three findings (see `relay improve suggest`).

`relay report --compare 2026-10-10..2026-10-13 2026-10-14..2026-10-17`
puts two periods side by side, normalised per turn of yours, with the
share of cost on each model tier. Use it a week after adopting a change.

## The ledger: when things happened

The `observe` plugin registers one hook script on nine events and appends
one JSON line per event to `~/.relay/ledger/<YYYY-MM-DD>.jsonl`:

| event | fields beyond ts/session_id/cwd |
|---|---|
| session_start | source, model; on resume: context_tokens, prompt_cache_likely_expired, estimated_cache_write_usd |
| prompt | chars, prompt_id, kind (`owner`, or `notification` for a background-agent message: judged by the harness's `origin` when it sends one, else by a marker at the very start of the text), slash (the command if the prompt starts with one) |
| agent_start | agent_id, agent_type, effort, input_keys (the names of the fields this Claude Code sends, never values), prompt_chars (always 0 on this Claude Code: SubagentStart carries no prompt) |
| agent_stop | agent_id, agent_type, reply_chars, requests, context, model, cost_est. The harness fires it twice for an agent that wrote plain text and was then sent back to hand back: requests, context and cost_est are cumulative, so the last stop per agent is the figure. reply_chars is what the caller receives: the length of the `SubagentHandback` message when the agent used it, else of its final text, and `null` (unknown, not 0) when neither is visible |
| tool_pre / tool_post | tool, tool_use_id (+ subagent_type, model, prompt_chars, escalated for Agent calls: the prompt's length and whether it has an `Escalated: <reason>` line, read by the same rule as the routing guard); agent_id inside an agent. A call the guard refuses has a tool_pre and no tool_post and starts no agent, so never pair Agent calls to agents by order |
| stop | reply_chars, context |
| compact | trigger (auto/manual) |
| session_end | reason |

Never text, unless the project sets `[observe] log_prompts = true`
(the first 200 characters of each prompt). The hook fails open and reads
at most the tail of one transcript.

`relay status` reads the last 12 hours: each session's last activity,
context size, and the agents started but not stopped.

## Findings

`relay improve suggest` (and the tail of `relay report`) lists measured
anti-patterns, each with evidence, an estimated saving and the lever:

| id | finding | saving estimate |
|---|---|---|
| F1 | build agents on Opus (agents whose prompt said `Escalated: <reason>` are left out: they were sent there on purpose; the prompt is read from the parent transcript, paired to the agent by id, so older sessions work too) | their cost minus the same tokens at Sonnet rates |
| F2 | general-purpose agents | 20k tokens per request at cache-read price |
| F3 | forks | none (a count) |
| F4 | sessions over 400k | a quarter of their cost |
| F5 | agents that paused over 5 minutes (cache lost) | cache-write minus cache-read on the re-written tokens |
| F6 | many agents with 3 requests or fewer | half their first reads |
| F7 | compactions | none (a count) |
| F8 | replies over 2,500 characters per turn | none (a measure of noise) |

Findings are sorted by saving. The estimates are deliberately simple and
say so; the bench gives the real figure.

## Prices

`prices.toml` holds USD per million tokens by tier with a `measured` date;
`relay doctor` warns when it is over 90 days old. To re-measure: run one
`relay bench` (its cost is Claude's own), compare with the ledger's
`cost_est` for the same session ids (the last `agent_stop` per agent: an
agent stopped twice would be counted twice otherwise), and adjust the
table until they agree within 10%.

## OpenTelemetry (optional, for a team)

Claude Code exports `claude_code.cost.usage` and `claude_code.token.usage`
with model and agent attributes when `CLAUDE_CODE_ENABLE_TELEMETRY=1` and an
OTLP exporter are set. The hook input's `prompt_id` matches the telemetry
`prompt.id`, so ledger lines can be joined to spans later. Relay does not
need it.
