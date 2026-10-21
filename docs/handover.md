# Handover: relay

Written 2026-10-19 by the session that built it, from the principles bundle.
Read this first in the session that installs it.

## Where it stands

Built and tested offline (no `claude` binary, no real sessions here):

- `bin/relay` with status, report (+ --compare), improve (suggest / adopt /
  log), bench (+ list), profile, sync, setup, migrate, doctor, flows, rules.
- `lib/`: config, prices, transcripts, ledger, analyze, bench, rules, setup.
- plugins: `observe` (ledger hook), `delegate` (6 agents, route guard,
  skill), `front` (budget + handover hooks, skill), `core` (from
  principles + flow stage hook), `sdd` and `product` (from principles,
  agents tagged with `relay-tier`), `issues` (new flow: 4 skills).
- 16 library tests (synthetic transcripts, a fake `claude`), 5 hook test
  suites (34 checks), lib-copy check, the principles eval grader tests.
  `bin/ci --quick` is green in about 3 seconds.
- Four bench scenarios on the shelf fixture; four profiles (active,
  baseline-old, candidates sonnet-front, sonnet-judge, lean-rules).
- Docs: design, observability, delegation, benchmark, flows, setup, improve.

## Verify first, in this order (each is minutes)

1. **Hooks fire with the expected fields.** Enable `observe@relay` for the
   user, start a session, ask for one scout, exit. `relay status` must show
   the session; `~/.relay/ledger/<today>.jsonl` must have `session_start`,
   `prompt`, `agent_start` with `agent_type`, `agent_stop` with `requests`
   and `model`, `stop` with `context`. If `agent_stop` lacks `requests`, the
   field `agent_transcript_path` is not in SubagentStop input on this
   version and the fallback (`<session>/subagents/agent-<id>.jsonl`,
   coded in both `budget.py` and `ledger.py`) did not find the file:
   look where this version keeps subagent transcripts.
2. **The route guard denies what it should.** In a session, ask for a
   `general-purpose` agent: the refusal must name the six typed agents. Ask
   for a worker with `model: opus`: refused; add `Escalated: test` to the
   prompt: allowed. If the deny is not honoured, check the hook event is
   `PreToolUse` with matcher `Agent|Task` (the tool's name on this
   version) in `plugins/delegate/hooks/hooks.json`.
3. **`relay report --today`** prices the session. Compare the agent's
   `cost_est` in the ledger with `/cost` in the session; adjust
   `prices.toml` if they differ by more than 10%.
4. **A one-run bench**: `relay bench active sonnet-front --scenario lookup
   --runs 1`. Confirms the headless flags on this version: `--agents`
   (JSON), `--append-system-prompt`, `--plugin-dir` (repeatable),
   `--permission-mode`, `--allowedTools`, `--max-budget-usd`,
   `--output-format json` with `total_cost_usd` and `modelUsage`. A flag
   the version lacks shows in the run's `.log` under
   `~/.relay/bench/<ts>/`; remove it in `relay_bench.claude_command`.
   `add-function` and `small-script` need `bun` on PATH for their
   graders.
5. **`claude plugin validate`** on `.` and every plugin; then `bin/ci`
   (full) once, which also runs the principles eval cases against the
   `evals/plugin/baseline` scores (the cases now sit under `evals/plugin/`,
   the plugin paths in `case.yaml` were adjusted).
6. **Kartoteka**: `relay migrate ~/kartoteka` (plan), then `--apply`,
   `relay doctor ~/kartoteka`, one small change through `/opsx:propose`
   to see the flow stage hook name `sdd:plan`.

## Added after the first build (same day)

- `issues` flow rebuilt from the Arsenal bundle (read/create/implement/merge,
  keyword triggers, `tea` bindings); `relay migrate` maps the Arsenal skills.
- `relay bench --set k=v`, `relay candidate <name> --copy <plugin>`, profiles
  whose `[plugins] enabled` entries are paths; `improve adopt` swaps an
  edited plugin copy in.
- `front:tune` skill + `tune-stage.py` hook + `relay` shim on the Bash
  tool's PATH: the owner types "try Haiku for workers", the session runs
  the bench. Verify: in a session say "what did this week cost?"; the
  hook's line must appear and `relay report` must run.

## Installed on the owner's Mac (2026-10-21)

- Unzipped from `~/Downloads/relay.zip` to `~/relay` (not a git repo yet).
  The zip lost the executable bits; restored with `chmod +x` on every file
  with a `#!` line.
- `relay install` ran: global CLAUDE.md written (old one at
  `~/.claude/CLAUDE.md.before-relay`), user settings merged (backup
  `~/.claude/settings.json.20261021-171627.bak`), the 4 user hooks of
  `context-budget.py` / `session-handover.py` removed, 10 projects imported
  from `~/principles/projects.toml`, marketplace added and core, observe,
  delegate, front installed at user scope (all `ok`).
- `relay` on PATH via `~/.local/bin/relay` (already on PATH, no sudo), not
  `/usr/local/bin`. Fixed `bin/relay`: `HERE` used `abspath`, so a symlinked
  `relay` could not find `lib/`; now `realpath`.
- `relay doctor`: 10 ok, 2 to fix — "rules in sync" for the 10 projects
  (that is `relay sync`, step 7 of START_HERE, after migration) and "ledger
  has entries" (fills once a session runs with the plugins).
- `bin/ci --quick`: red on one test,
  `Bench.test_candidate_with_plugin_copy_drives_agents_and_plugin_dir`:
  on macOS the temp dir is `/var/...` but the command line carries
  `/private/var/...` (one side is realpath'd). Test/bench path issue, not
  install. Not fixed yet.
- Not done: "verify first" steps 1-6 above, `relay migrate --all`, any
  project `--apply`, `relay sync`.

## Verified live (2026-10-21, second session, 0b953f5c)

- Step 1 passed with gaps: ledger gets `session_start`, `prompt`,
  `tool_pre/post`, `agent_start` (with `agent_type`), `agent_stop` (with
  `requests`, `model`, `context`, `cost_est`). `relay status` shows the
  session. Gaps (to fix):
  - `agent_start.prompt_chars` is always 0: the prompt field name in
    SubagentStart input differs on this version.
  - `agent_stop` fires twice per agent (second one after the hand-back
    message, `reply_chars` 0). `relay report` already counts the agent
    once; `reply_chars` is 0 when the reply arrives as a hand-back.
  - The `tune-stage.py` hook fires on background-agent notifications
    (UserPromptSubmit carrying `<task-notification>`), not only on owner
    text: it should skip those.
  - Report finding F1 ("build agents ran on Opus") counts an agent whose
    prompt had `Escalated:`; it should exempt those.
- Step 2 passed: `general-purpose` refused naming the six agents; worker
  with `model: opus` refused; with `Escalated: test` allowed, ran on Opus.
- Red test cause (scout): `tests/test_relay.py:222` compares the
  unresolved `/var/...` copy with the `realpath`'d path that
  `lib/relay_bench.py:62` (`plugin_dir()`) emits. Fix the test: compare
  with `os.path.realpath(copied[0])`; line 223 likewise against
  `realpath(root)`. Keep lib canonical.
- Step 3 waits on the owner's `/cost` figure for session 0b953f5c
  (`relay report --today` estimated it at $0.39 at that point).
- ~/relay is still not a git repo, so fixes have no branch to go on.

## Open items (decisions for the owner or work not done)

- **Agents' models in installed copies.** `relay sync` rewrites agent
  frontmatter in the source and in every path `installed_plugins.json`
  lists for a relay plugin. With a directory marketplace Claude Code may
  load the source in place (then the rewrite of copies is harmless) or
  from a cache copy (then it matters). Confirm with `/agents` after a
  sync that `scout` shows the profile's model.
- **The sdd flow's "leads" and ALIX's route/Jev flow** are not relay flows.
  ALIX keeps its own until its flow is written as a `flow.json` plus
  skills (docs/flows.md). The `[coordination] mode` key stays in kit.toml
  unused by relay.
- **Front noise is measured, not enforced.** A `Stop` hook could refuse a
  reply over N characters; it was left out because a blocked reply costs
  a re-generation. Bench `reply length` first.
- **Prices.** `prices.toml` encodes the owner's measured 2026-10 ratios,
  not a vendor price list. Step 3 above calibrates it.
- **`--isolate` for benches** copies `.credentials.json` into a throwaway
  config dir; on a Mac with keychain credentials this may or may not sign
  in. Documented as "try; else bench without it".
- **Issue flow bindings** ship with GitHub examples; Arsenal (Forgejo),
  Glonass (GitLab + Tracker) need their commands filled in `[issues]`.
- **The principles migration drafts** (`migration/<project>/kit/*.md`) were
  not copied into relay; they live in `~/principles` and are the
  starting point for each project's `.claude/kit/<role>.md`.
- **Core tests from principles** (`packet`, `check-contract`, `shim`,
  `guard-main`, `inject-addition`, `kit`) need bun or the fixture's
  node_modules; `bin/ci` runs them only with `RELAY_CORE_TESTS=1`.

## Decisions made here (the owner may overturn)

- One bindings file (`kit.toml`) and the old plugin names kept; the
  marketplace renamed to `relay`.
- Enforcement moved into hooks; the rules text cut by about 30%.
- Front on Opus by default; `sonnet-front` is a candidate to bench.
- Migration moves files aside; nothing is deleted by any command.
- Profiles are the unit of change; adoption is logged.

## Next step

Step 1 of "verify first". Then `relay improve suggest --since 7d` on the
real transcripts: the first list of findings on real data is the first
candidate profile.
