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
- Git: owner chose (2a) to make ~/relay a repo on `master` (first commit
  930f84b, the install as found). Fixes are on branch
  `fix/live-verification` in `.worktrees/live-fixes`: c9ae99c, 625e8ae,
  434e926 (worker), b9e6e2a (fixer, after review 1: 1 must + 6 should),
  f88542c (exec bits). Review 2: all review-1 findings closed; merge
  ready apart from the open items below. Not merged: owner has not asked.
- Agent pairing now by id from the main transcript: 3,175 of 3,185
  Agent calls in 30 days matched (the 10 others refused or errored).
- Outage fixed 2026-10-21: the zip had lost the exec bit on 9 scripts
  (`plugins/core/bin/kit`, `plugins/front/bin/relay`, templates, eval
  fixture). Without `bin/kit` the core guard failed closed (rc 2) on every
  tool call in ~/kartoteka (the one project with `.claude/kit.toml`).
  Fixed in the installed cache (`~/.claude/plugins/cache/relay/{core,
  front}/0.1.0`) by chmod, and in the source on the branch (f88542c).
  Guard re-tested: rc 0.
- Open after review 2 (to the owner with a recommendation):
  - S-A: `plugins/core/bin/kit` needs Python 3.11 (tomllib); on 3.9 the
    guard fails closed. On this Mac `python3` on PATH is Homebrew 3.14,
    so it works unless a hook runs without Homebrew on PATH.
  - S-B: "your turns" counts "[Request interrupted by user]", `/clear`
    and local-command output as owner turns (today 5 counted, 4 typed).
  - The guard does not expand shell variables: `git -C $W add` and
    `mkdir -p $S` are taken as writes in the main checkout and refused.
  - Full `bin/ci` paid eval step not run; its `--eval-dir` fix untested.
  - core@principles is still installed (disabled); core@relay enabled.
- Owner's answers this session (verbatim): "1a 2a" (1a = will paste
  `/cost`; 2a = git repo on master, fixes on a branch), "go ahead".
  Then: "Now - let's explore this utility - what it can how can be
  expanded and what is the goals". The thinker's write-up was in the
  session scratchpad (explore-relay.md); summary: goals = less spend for
  the same work ($1,738/7d estimated, $1.52 per typed turn, uncalibrated),
  block known waste, change setup only after a measured bench, same rules
  in 10 projects (0 synced). Ranked options: 1 trustworthy numbers,
  2 repair+calibrate bench (it likely gives both profiles the same agent
  models; unverified), 3 wire the 10 projects, 4 a finding for 50-200k
  context requests (67% of spend, untargeted), 5 bench tasks from own
  commits, 6 weekly digest, 7 hard limits.
- Step 3 done: owner's `/cost` screenshot for session 0b953f5c: $8.43
  (Opus $6.99, Sonnet $1.43, Haiku $0.0031); relay's report said $5.40,
  36% low. Cause is mostly token counting, not prices: relay saw Sonnet
  output 673 tokens vs 48.7k, Opus output 39k vs 118.4k, Opus input 344
  vs 56.5k. Per-model figures in memory `relay-cost-calibration`. Fix
  counting first, then refit prices.toml.
- The screenshot shows the owner is on a subscription with usage limits
  (2% session, 0% week): dollars are notional; the goal is work per
  limit. Claude Code's own advice there: critic is 28% of usage, "give
  delegate:critic a cheaper model" (the `sonnet-judge` candidate profile).
- Owner's answers (verbatim): "1a 2a" (run the paid eval step, then
  merge and reinstall; next = trustworthy numbers, then option 4), cap
  "b" ($15), then "1a 2b" (1a = visible status line `5h % · week % · $`
  that also logs; 2b = remove the older principles guard from kartoteka).
  Owner asked whether estimates were human-hours: they were; from now on
  estimates are agent minutes + % of limit (memory
  `estimates-in-agent-time`; measured: build+review+fix+review ~30 min).
- Full `bin/ci` green after two fixes: bin/ci passed an unexported `$root`
  into `bash -c` (eb8b14c); fixture `bin/check` needed git, which the eval
  sandbox lacks (d504103). Paid evals: 4/5 in the full run ($3.23), then
  worker-group 3/3 after the fix ($0.26); about $3.75 in all incl. the
  fixer's three 1-run probes.
- Merged: master fast-forwarded to d504103 via `wt/live-verification`
  (guard allows only `git merge --ff-only wt/<name>` in the main
  checkout: name task branches `wt/<name>`). Old worktree
  `.worktrees/live-fixes` and branches fix/ + wt/live-verification can go.
- Plugins: `claude plugin update` says relay plugins are read from their
  folders in ~/relay/plugins (directory marketplace), so the
  `~/.claude/plugins/cache/relay` copies are unused and stale; merged
  changes are live at the next session start or /reload-plugins. This
  closes the open item "Agents' models in installed copies".
- Kartoteka: `core@principles` turned off in
  `~/kartoteka/.claude/settings.local.json` (listed in kartoteka's
  `.git/info/exclude`; its tracked settings.json untouched). relay's
  `kit` is byte-identical to the principles one and answers there, so
  sdd@principles / product@principles still find `kit`.
- Two Opus agents (critic, thinker) hit the 40-turn limit without a
  report; resumed with "write now". Add to group 2: raise the limit or
  make agents write the report file early.
- Batch 1 (group 1 of plan-trustworthy-numbers.md, kept in the session
  scratchpad; tn_*.py evidence scripts beside it) is building in
  `.worktrees/numbers` on `wt/trustworthy-numbers`.

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

Batch 1 on `wt/trustworthy-numbers`: worker, then critic, fixer, critic
(two reviews at most); then the owner's OK to merge. Then group 2 (S-A
kit on Python 3.9, S-B "your turns" counting interrupts/`/clear`, guard
not following shell variables, the 40-turn limit), then group 3 (status
line per 1a, share of the limit, carried-weight finding = option 4).
The plan file lives in the session scratchpad; if it is gone, its
group list is above.
