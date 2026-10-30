# Benchmark: two setups, side by side

`relay bench <A> <B> [--scenario <name>... | --tag <tag>] [--runs N]
[--max-cost USD] [--isolate] [--keep] [--judge-model haiku]`

## What a profile is

`profiles/<name>.toml` or `profiles/candidates/<name>.toml`:

```toml
[profile]  name, description
[session]  model, effort, permission_mode     # the front
[models]   look, run, build, fix, think, judge  # one model per tier
[effort]   the same keys                        # low | medium | high | xhigh | max
[rules]    load = [...]                         # rules loaded in full
[plugins]  enabled = [...]                      # plugin dirs passed with --plugin-dir
[delegate] typed_only, fork_limit, max_parallel, build_tier_opus (profile data; the kit.toml names are typed_agents_only, no_session_copy_above_tokens, max_agents_at_once, opus_for_builders)
[env]      extra environment for the run
```

The bench applies a profile to a headless run through flags only:
`--model` (the front), `--agents` (the six agents with the profile's model
and effort), `--append-system-prompt` (the rules), `--plugin-dir` per
plugin, and the environment. Nothing is installed or changed on the
machine.

## Trying one change without writing a profile

```sh
relay bench active --set models.build=haiku                      # Haiku instead of Sonnet for workers
relay bench active --set effort.build=low                        # same model, less thinking
relay bench active --set models.judge=sonnet --set effort.judge=xhigh --scenario review-offbyone
relay bench active --set rules.load=working-with-me,delegation,secrets --tag cheap
```

`--set key=value` (repeatable) makes profile B from A with those keys
changed, names it after the changes, and writes it to
`profiles/candidates/<name>.toml`, so `relay improve adopt <name>` works
when the verdict says so. Keys are the profile's dotted keys: `models.<tier>`,
`effort.<tier>`, `session.model`, `session.effort`, `rules.load` (comma
list), `plugins.enabled`, `delegate.<key>`.

## What a scenario is

`evals/scenarios/<name>/scenario.toml` + `prompt.md` (+ `scaffold.sh`):

```toml
name, description, tags
fixture = "../../plugin/fixture"      # copied into a fresh workspace per run
scaffold = "scaffold.sh"              # run inside the workspace (git init, a branch, ...)
max_turns, timeout_s, runs, permission_mode, allowed_tools, max_cost_usd
[[graders]] name, type, ... (one or more)
```

Graders (free unless noted):

| type | passes when |
|---|---|
| `regex` | `pattern` matches the final reply (`flags = "i"`) |
| `file_exists` | `path` exists in the workspace (`exists = false` inverts) |
| `command` | `command` exits 0 in the workspace (tests, grep, a build) |
| `agent_used` | the ledger shows an agent whose type matches `agent_type` started in the run's session (`exists = false` inverts; the observe plugin must be in the profile) |
| `tool_called` | the run's session or a subagent called a tool whose name matches `tool` (regex, default `^Bash$`) and whose command or path matches `input` (regex); `count` calls at least, `exists = false` inverts. Read from the session transcripts; secret-looking environment values are redacted first |
| `llm` | a cheap model says PASS to `rubric` over the reply (paid) |

`add-function` and `small-script` start in a linked worktree (their scaffold), because the core plugin's main-checkout guard blocks every write in a primary checkout and the graders read the workspace itself; their prompts do not order a worker, so `delegated-to-a-worker` measures whether the setup's rules make the session delegate. The bench runs a copy of the delegate plugin with the profile's model and effort per tier, since the session starts the plugin's own `delegate:worker`.

Four ship: `add-function` (a feature with tests), `small-script` (the "Opus
wrote a simple script" case), `lookup` (a question), `review-offbyone` (a
review with a planted bug). Tag `cheap` selects the first three.

## Reading the table

Per scenario: quality (mean and worst run), cost (Claude's own
`total_cost_usd`, with the share per model tier), time, turns, reply
length, and the delta B−A with a percentage. Below it, every failed grader
with its note. Then the verdict, by the rule:

1. B must be no worse in quality (worst run) on every scenario; a cheaper
   run that fails is not cheaper.
2. Then cheaper wins.
3. Then faster.

Results: `~/.relay/bench/<timestamp>/report.md`, `results.json`, one log
per run, and the agents/rules files each profile ran with. `relay bench
list` shows past runs.

## Cost and honesty

- Every run is a real session. Three scenarios × two profiles × one run is
  six sessions; the `cheap` set is a few dollars. `--max-cost` stops the
  bench and marks it partial.
- Profiles are interleaved per run so the time of day affects both alike.
- One run per scenario tells you about big differences; three runs
  (`--runs 3`) before adopting.
- Without `--isolate`, the run also loads your user settings, CLAUDE.md
  and installed plugins (as a real session does). With `--isolate` it
  gets a throwaway config dir: only what the profiles declare differs.
  If sign-in fails in isolation on your machine, bench without it.
- A scenario that scores 1.0 under both profiles does not separate them;
  it is still worth keeping as a regression check.

## Plugin evals are a different question

`evals/plugin/` holds the `claude plugin eval` cases from principles: does a
plugin's agent or hook do what it must (the guard fires, the reviewer finds
the planted bug). They run in `bin/ci` against a baseline. The bench asks
the other question: which setup does the same work better, cheaper, faster.

The runner sets `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` and `--setting-sources user`, so a
`CLAUDE.md` or `CLAUDE.local.md` a scaffold writes never loads. A rule a case needs reaches the
session through `append_system_prompt` in its `prompt.md`, written from `rules/*.md` by
`python3 evals/plugin/system_rules.py`. `tests/test_claudemd_fixes.py` fails a scaffold that writes an instruction file.
