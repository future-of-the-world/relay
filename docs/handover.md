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

Batch 1 MERGED (master 6a4b713, 21 Oct): worker, critic, fixer, critic,
then a third review the owner chose ("b"), a last fixer pass ("a", proven
by the reviewer's repro tests), full bin/ci green incl. paid evals 15/15
($3.44, owner chose to run it: "b"). Live check: relay $20.11 estimate vs
/cost $19.25 (+4.5%). `relay calibrate` run on the real ledger
(~/.relay/calibration.json): Opus worst +2.3%, Haiku -4.6%, Sonnet
-20.8% on 2 of 15 sessions (both 266-278k context; long-context price
suspected, unverified); whole-session estimate median 2.9%.
Overview page for the owner: https://claude.ai/artifact/NgVrUz62oU7nCEgnPyQxwb
(source in the session scratchpad, relay-overview.html).

Batch 2 building on `wt/open-items` in `.worktrees/batch2` (brief: live
check of when Claude Code writes session totals and whether resume
restarts the count (N3/F3), SessionEnd hook speed (N4), kit on Python
3.9 (S-A), "your turns" counting (S-B), guard and shell variables,
critic/thinker maxTurns 40 -> 60 with write-early text). Then review,
fix, review, owner's OK to merge. Then group 3 (status line per 1a,
share of the limit, carried-weight finding = option 4), plus two owner
picks of 21 Oct: (1) "a": `relay doctor`/`setup` check the openspec CLI
is installed and working and the `/opsx:` commands exist in OpenSpec
projects; (2) "a, model should recognize it, I can typo text in many
languages, with misstypings and common language errors": OpenSpec
stages triggered by the model's understanding (stage intents in the
injected instructions, the hook adds the open change names per prompt,
`/opsx:` kept as fast path), proven by ~15 paid Haiku eval prompts in
Russian and English with typos incl. negatives (~$0.30). Memory:
`natural-language-triggers`. Also verify the
Sonnet long-context price with the claude-api skill. Old worktrees
`.worktrees/live-fixes`, `.worktrees/numbers` are merged and can go.
The plan: docs/plans/trustworthy-numbers.md.

STATE at the 350k handover (21 Oct, ~22:45 local), session 0b953f5c:
- Batch 2 (wt/open-items, .worktrees/batch2) is merge-ready: whole-change
  review (0 must, 4 should: A1 session-end speed, D1 guard header, D2
  Python docs, D3 observability doc) fixed in bb3d9ed and checked against
  the review's own pass-cases: all pass, nothing outside scope
  (scratchpad review-batch2-whole.md, section "Check of bb3d9ed").
- Running: full `bin/ci` with the paid evals, cap $15 (owner: "a" = run
  it, then merge if green). Log: scratchpad ci-batch2.log; results
  .ci/evals.json in the worktree.
- DONE: full ci green (paid evals 15/15, $3.52); batch 2 MERGED, master
  7f07ede, main checkout clean.
- NOW: batch 3 in `.worktrees/batch3` on `wt/role-bases`. Step 1: a
  thinker designs the shared role bases + review-method wording
  (scratchpad brief-role-bases.md -> design-role-bases.md); then a
  critic reviews the DESIGN; then a worker builds; then one thorough
  whole-change review with pass-cases; fix checked against them.
- Then batch 3, in order: (1) shared role bases for delegate + sdd agents
  with the new review method in the judge base (design review first);
  (2) reword rules/delegation.md review rule; (3) OpenSpec stages by
  meaning in any language + doctor/setup checks for the openspec CLI and
  /opsx commands; (4) status line + limit share; (5) large repeated
  requests finding (incl. ~$0.30 session start-up). Then phase 1
  (self-contained, OpenSpec as adapter).
- Owner's latest words: "a" (paid run before merge), "a" (OpenSpec as
  adapter in phase 1), "a a" (shared role bases, in batch 3), "a" (split
  personal rules), "One good review is better than several bad reviews,
  and cheaper".
- Old worktrees `.worktrees/live-fixes` and `.worktrees/numbers` are
  merged and can be removed.

Decisions of 21 Oct evening (owner's words verbatim where quoted):
- Review method: "our review - fix - review flow is wrong we move in
  cycle fixing the same problems. One good review is better than several
  bad reviews, and cheaper". Earlier: skipping a review is
  "unacceptable". New shape: design review before risky builds; one
  thorough whole-change review that writes the cases a correct version
  must pass; the fix is checked against those cases. Reword
  rules/delegation.md ("Review runs twice at most") in batch 3. Memory
  `always-review-fixes`.
- Guard: variable-following dropped ("1. a"); kit_guard.py and
  guard-main.sh back to 6a4b713 behaviour (a2b5753), proven by
  guard-diff.test.sh: 309 commands, 0 differences vs a golden file.
- Resume: owner's live test: /cost 0.3238, newer session 0.2823, resumed
  first session 0.3238 again: Claude Code continues a resumed session's
  count; F3 cannot happen. A bare "hi" session costs ~$0.30 on Opus.
- Self-contained relay ("pluggable, all in one"): phase 1 AFTER batch 3
  ("2. a"); rules in a marked block in ~/.claude/CLAUDE.md that relay
  owns, the owner's text outside it untouched ("3. a"); split rules into
  relay's set and the owner's personal set (working-with-me, shell,
  glonass) chosen at install ("a"). Also in phase 1: project list per
  machine in ~/.relay (not committed), ship the OpenSpec coordinator
  skill, `relay uninstall`, paths resolved at install, retire principles
  leftovers. Design notes: session scratchpad selfcontained.md (its
  claim that plugins run from a stale cache is WRONG: the ledger shows
  merged code live from ~/relay within minutes).
- OpenSpec natural-language triggers and doctor checks: batch 3 (see
  above).
- Agent families ("a a"): sdd agents are separate full copies of the
  delegate roles (only model/effort synced by tier via relay sync,
  lib/relay_rules.py:133-163). Batch 3: one shared base per role
  (judge, build, fix, think, look, run) written once; each agent file
  assembled from base + its flow-specific part by `relay sync`; a ci test
  fails if any assembled file is stale. The new review method goes into
  the shared judge base so both families get it: every finding with a
  concrete failing case and the pass-cases for the fix; sdd apply-review
  already reviews the whole range on its second pass (keep that), but
  its reviewers lack the failing-case rule. Design review (critic on the
  thinker's design) BEFORE building, per the new review method.
- OpenSpec as an adapter ("a", phase 1): relay owns one generic change
  cycle (plan -> build -> review -> fix -> finish) used by every flow
  (sdd, issues, plain tasks); OpenSpec plugs in as the spec format: its
  file rules (`openspec instructions`), `validate --strict` gate, and
  `archive` that merges requirement deltas into openspec/specs (the
  standing description). Keep OpenSpec-specific stages in the adapter
  (spec review against openspec/specs). Owner's framing: "openspec it
  just a notes for spec writing and reading ... addition to our base".
