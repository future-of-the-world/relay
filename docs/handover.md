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

STATE 21 Oct ~23:30 local, session 0b953f5c (supersedes "NOW" above):
- Design of batch 3 done (scratchpad design-role-bases.md); design review
  done (scratchpad review-design-roles.md: 5 must, 9 should, 7 notes).
  Verified claims: sdd and product run in projects from
  /Users/amidman/principles (relay's sdd edits reach no project yet);
  sdd apply-review's second pass covers only the fix commits
  (`<gate base>..HEAD`, apply-review:121), the earlier "whole range" was
  wrong.
- M1 corrected by a live check: `claude plugin update` says relay plugins
  are read from their folders in ~/relay; edits take effect at the next
  session start or /reload-plugins. ~/.claude/plugins/cache/relay is an
  unused 17:16 leftover. Hooks run current code; agent texts are fixed at
  session start. So M1 becomes: after a merge, the message says open
  sessions keep the old agent texts until restart or /reload-plugins.
- Owner answers (verbatim "1. a 2. a 3. a 4. a 5. a"): refresh (done,
  no-op); fix checker = Sonnet that runs the listed cases + the fixer's
  tests and reads the callers of what the fix changed; the check reports
  new HIGH and MEDIUM problems to the owner; projects get the review
  method in phase 1; merged worktree removed right after the merge, with
  the M2-M4 guards (per-project opt-in, not the worktree the session runs
  in, not a worktree with no commits of its own).
- Work queue (owner: "a" = in batch 3): no "tech debt" term or behaviour
  (owner, citing TigerBeetle zero technical debt). Found during a change:
  wrong inside the change -> fixed in it, merge refused until fixed;
  wrong elsewhere -> queue item with a failing case, ahead of all new
  work; design wrong -> stop building on it, redesign is the next change;
  idea -> queue item ordered by the owner. Session start shows
  "queue: N wrong, M ideas". Out-of-scope owner questions: answered
  briefly, become a queue item, built later in a fresh session.
  Replaces sdd's "follow-up with id, owner, deadline".
- Folder (owner "a a"): project files of relay live in `.relay/` (queue
  in `.relay/queue/<item>.md`, committed); owner: folder must not be a
  bare `queue` because e.g. a Go module may have a `queue` package. The
  issues flow merging into the queue is the FIRST queue item, not batch 3
  (it touches ALIX and arsenal live flows).
- NEXT: thinker revises the design (brief scratchpad
  brief-revise-roles.md -> design-role-bases-v2.md), a checker confirms
  each must-fix and decision is in it, then the worker builds in
  .worktrees/batch3.

STATE 22 Oct, session 0b953f5c (after the design check):
- v2 checked (scratchpad check-design-v2.md): 20 resolved, 1 rejected
  (M1, correct), 2 HIGH (checker can't write a mark under main .git;
  any later commit deadlocks the merge), 4 MEDIUM.
- Owner: two merges ("1. a"); own worktree removed at next session start
  ("q2 - a"); later commits keep the mark only via a fixed inert-file
  list, "model shouldn't decide by self"; kinds fix|feature; ordering by
  IP ("important points, from zero to infinity, order by IP"), a new fix
  starts above every feature ("2. a"); marks written only by a hook on
  checker finish, guard blocks other writes ("1. a, yes this is a good
  mechanism"); `.relay/` for project files is "a rule"; questions open
  with a context introduction (memory questions-carry-context), goes
  into relay in part 1; queue seed adds "state from facts" (owner
  distrusts a hand-written handover).
- Marks: ~/.relay/checks/<repo-id>/<branch>.json, repo-id = root commit
  hash (coordinator's choice: folder names collide across clones).
- NEXT: thinker writes v3 (brief scratchpad brief-design-v3.md ->
  design-role-bases-v3.md), checker confirms, then build part 1.

STATE 22 Oct (v3 written: scratchpad design-role-bases-v3.md, ~2000 lines,
"v3 changes" rows 1-20). Owner's final answers (verbatim where quoted):
- Marks: committed file `.relay/checks/<full 40-char sha>.json`, written by
  a SubagentStop hook only for delegate:checker; guard blocks tool writes
  there; full sha always ("why we can't store full commit hash").
- Hard rules (merge check + worktree removal) in every repo whose default
  branch has `.relay/` ("2. a"); `.relay/` created only by relay setup.
- Per-role project additions in part 1 ("3. a"), `.claude/kit/<role>.md`.
- Queue items land on their own branch `wt/queue-<slug>`, merged at once
  by code when the only change is under `.relay/queue/` ("1. a - but
  don't lock wt/queue name ... queue worktree should be named
  differently"); retry on a moved head, 5 tries.
- state-from-facts ip 80 ("2. a").
- Question format locked: "Now your questions contains enough to make
  decision, lock it" (memory questions-carry-context).
- NEXT: checker confirms v3 (brief scratchpad brief-check-design-v3.md ->
  check-design-v3.md), then build part 1 (135 agent min).

STATE 22 Oct, part 1 built and checked (session 0b953f5c):
- Part 1 commits on wt/role-bases: d7c3006 a9ddfc0 76aa463 8854e2a
  037573e 47ca87d 36154df (build), 3c7218d (review fixes F1-F7, checked
  open 0: scratchpad check-p1.md), 156ca53 (path LOW), cff3f39 (grader +
  one reply format + quality-gate rule, checked: check-specrev.md),
  77e6a98 (HIGH lines beyond the 10-line cap; critic heading).
- First full paid run (156ca53): 14/15, spec-reviewer-flaw 2/3, $4.55.
  Diagnosis ($3.06, scratchpad diagnose-specrev.md): the grader's word
  lists, not the branch (master also failed 1/3 with a correct finding);
  found too: branch reviewer replies 24-39 lines vs 11-13, +45% cost.
  Owner: "1. a 2. a 3. a" (line-pair grader; one reply format; proof by
  replay + one full paid run). Owner on flakiness (verbatim): "you need
  more analysis of cause rather than more runs ... actor is a single of
  act (who reades and writes, do act)" -> rules/quality-gate.md, memory
  flaky-means-find-the-cause.
- Review noted: spec-reviewer now marks "a known wrong left inside the
  change" BLOCKER (was FIX), tag C19; told the owner, kept.
- Outside the change (O1, queue item for phase 1): sdd/product run from
  the principles marketplace, so these texts reach projects only then.
- Queue items to seed in part 2 besides the design's: the setup-tuning
  hook fires on any mention of cost (false trigger on "It costs about
  $3.50"); code-reviewer-offbyone grades by a phrase list.
- Running: full paid `bin/ci` on 77e6a98 (log scratchpad
  gate-p1-full2.log). Paid so far today in batch 3: $7.61 + this run.
- NEXT: if green, ask the owner for the merge of wt/role-bases; then
  part 2 (design fixes M-A, M-B from check-design-v3.md first).

## STATE 22 Oct, code-reviewer miss fixed and checked

- Owner on the diagnosis: "1a 2a 3a" = the reviewer owns the rating
  (re-rates a helper skill's severities against project rules); every
  project-rule finding gets a labelled reply line beyond the 10-line cap;
  cap raised to $22 for 6 live runs with traces kept (each checked for the
  cause: helper rated low, reply still carries DOC-RULE) plus the full run.
- Fix f8e30e0 (roles/judge.md "The rating is yours", style "unless a
  project rule makes it one", code-reviewer and spec-conformance flows),
  check check-offbyone.md: open 1 MEDIUM (3 flows' own reply lists dropped
  the line). Fix 7183617, gate gate-offbyone-2.log exit 0, check
  check-offbyone-2.md: open 0 (two LOWs).
- Explainer of the eval suite: scratchpad evals-explained.md (5 cases,
  3 of 15 agents covered, 4 wording graders; finds-off-by-one rejects a
  correct "returns 3 items; a page must hold at most 2").
- Open questions to the owner: (1) fix finds-off-by-one by the
  fact-through-form rule before the 6 paid runs (recommended a);
  (2) a live case for the per-role file .claude/kit/judge.md in this
  change, cap to ~$26 (recommended a) or a queue fix item.
- Next: on the answers, the grader fix and/or new case, check, then the
  6 runs, then the full paid run, then the owner's word on merging.
- Spend: $13.28 of $22.

## STATE 22 Oct, graders: code for facts, Jev + Sonnet for meaning

- Commits since c716a9f: 6483b6f, aa0ba22 (new case critic-role-rule for
  .claude/kit/judge.md), f9e8150, 886c9fd (review-evals.md fixes; check
  check-evals.md: open 1 MEDIUM N1 + MINOR N2, and the checker's own
  probes: regex graders pass 20 of 31 wrong answers). Not fixed by
  regex: the owner chose a judge instead.
- Owner decisions: no Woodpecker ("just git ... agent can manage
  scripts and run it"); review results and check reports stored in git
  beside the mark, merge gate local; "2a" code for facts, a judge for
  meaning; judge = TypeSafe Jev first (sure if max(p,1-p) >= 0.9),
  Sonnet below that with a reason; step 4 of the pipeline = one chat
  screen + a private page. Key in ~/.zshrc as TYPESAFE_API_KEY (live
  call OK, pinned jev-1.14.0 accepted; never print it).
- Owner's pipeline (verbatim): "Code checks run first - it's free /
  Then they passes - run review step, that have result and can store
  artifacts (like linter message with link to wrong places) / If review
  passes - we can proceed". Goes into the part 2 design.
- Design: scratchpad design-judge.md (rev 3), review review-judge.md,
  check check-judge-design.md. Lost traces: bin/ci lacks --keep-temp
  (proved by exp-nokeep.log / exp-keep.log). Two old traces kept in
  scratchpad/kept-traces/.
- Open owner questions: measurement size (rec. 10 per question, ~$3,
  cap to ~$28), when Jev counts (rec. after 0 sure-but-wrong), reviewer
  reading the rule file itself (rec. pass but flagged).
- Next: on answers, build the judge (worker), review, fix, gate, check;
  measurement; 6 live runs; full paid run; owner's word on merging.
- Spend: $13.28 + about $0.01 of $26.

## STATE 22 Oct, owner answers: Jev rejected, Haiku judges

- Owner (verbatim): "1a / 2. I think we're reject Jev with cause Haiku
  is still cheap but better / 3. a". So: measurement 10 replies per
  meaning question (cap to ~$28); no Jev, the judge is Haiku; a run where
  the reviewer reads the rule file itself passes but is flagged.
- Critique given once: "better" is unmeasured (the measurement will
  show it); Haiku samples, so the same reply can get different verdicts
  (Jev was picked for repeatable verdicts); cost still cents per batch.
- Consequence (front desk): with Jev gone, the eval tool's own llm
  grader (Claude judge, votes) may replace relay's judge step, key and
  trace copy. Being checked (eval docs lookup) before the design is
  redone; design-judge.md rev 3 is superseded on the judge part.
- Design rev 4 written (scratchpad design-judge.md, 395 lines; rev 3 in
  bk/): built-in llm graders on Haiku, rubrics carry the facts (proved
  live, $0.018, scratchpad/llm-exp/); votes + judged text stored, no
  reason; tool_used sees subagent calls; measurement = separate eval
  judging recorded reply files, 10 per question x 5 runs, bar 0 wrong
  majorities and <= 1 split; ~$2.50 total. judge.py, Jev, keep-temp,
  trace copy dropped. Design review running (review-judge-v4.md).
- Open owner questions: reasons (rec. a: votes + text + rubric only);
  Sonnet only per whole batch (rec. a).
- Owner (verbatim): "1a 2a": store votes + judged text + rubric, no
  reason (re-ask when a verdict looks wrong); if Haiku fails the
  measurement on a question, Sonnet judges the whole batch.
- Owner asked for an analysis of the sdd layer ("I think something is
  wrong with our SDD plug in system, it can be cleaner"): thinker on
  brief-sdd-layers.md -> scratchpad sdd-layers.md.
- sdd analysis done (scratchpad sdd-layers.md): sdd 1289 lines = 64%
  generic cycle / 23% spec-neutral / 13% OpenSpec; +1177 OpenSpec-only
  lines in core. No second spec format in 8 openspec projects. Rec.:
  base roles + one change cycle in delegate for every flow + thin
  OpenSpec adapter (sdd renamed openspec), 15 -> 11 agents. Problems:
  review gate written 3x and drifting; 5 of 7 sdd agents generic;
  OpenSpec code in core, kit/<agent>.md keyed by short name reaches both
  families. Owner questions open: ten checks for issues/tasks (rec. yes),
  waves stay in adapter (rec.), timing phase 1 with Kartoteka switch
  (rec.), no per-flow addition files (rec.).
- Owner answers on the sdd analysis (verbatim): "1a 2b 3a 4a / I don't
  want to maintain old projects - this is just a base for future
  projects, piece of my experience with claude, don't touch them, I'll
  start with new projects and test it there / I want to share common
  flow to all others, issue is a future follow-up, we can share it now
  and decide in future". So, phase 1: one change cycle shared by every
  flow, with the ten correctness checks everywhere and parallel waves in
  the shared cycle; thin OpenSpec add-on (sdd renamed); no per-flow
  addition files; old projects (Kartoteka, principles) NOT migrated or
  touched; tested on new projects. Issues flow joins later.
- Design review of rev 4 (scratchpad review-judge-v4.md): 0 HIGH, 7
  MEDIUM, 5 LOW; main: existing wrong replies left unmeasured, wrong
  items too short; last_message relay matched the agent's reply exactly
  in both traces (keep it). Fixer on brief-fix-judge-v4.md, then check.
- Phase 1 overview page for the owner:
  https://claude.ai/artifact/XMsv3xJxw5uZCtYk4Z3416 (source scratchpad
  relay-change-cycle.html). Proposals in it not decided: fix with no
  requirement change; design review for every refactor.
- Rev 5 (fixer) checked (scratchpad check-judge-v5.md): F1-F12 met; new
  1 MEDIUM N1 (composed "no" items keep a second mention) + 3 LOW, folded
  into the build brief (review limit reached; the build gets its own
  whole-change review). Measurement: 58 items, 870 votes, ~$4.10 (haiku 1.07 + sonnet 3.02).
- Build running: delegate:worker on brief-build-judge.md (no paid
  calls; gate log gate-judge.log). Next: review, fix, check, then the
  measurement, 6 live runs, the full paid run, owner's word on merge.
- Built: 10835dc, 6df3ce4, 8b0d445 (gate-judge.log exit 0, head
  8b0d445). Unconfirmed until a paid run: allowed_tools: [], weight
  0.001, llm focus-file graders. Whole-change review next
  (review-judge-build.md).
- Review of the build (review-judge-build.md: 1 HIGH, 1 MEDIUM, 5 LOW)
  fixed in 1f6e1dd (gate-judge-fix.log exit 0); check
  (check-judge-fix.md): all met, 0 HIGH/MEDIUM, 3 LOW open (L1 tally
  traceback on unreadable json, L2 two items less realistic, L3 runs
  count from prompt) -> to the owner, rec. queue them. Measurement 58
  items, 870 votes, ~$4.10. Runner on brief-run-measure.md (Haiku then
  Sonnet; measure-tally.txt).
- Owner: "a" -> L1-L3 (check-judge-fix.md) go to the part 2 work queue.
- Measurement (runner ran out of turns after both runs; results read
  from scratchpad measure-tally.txt): Haiku $0.49, PASS 3 questions,
  FAIL off-by-one (7 wrong verdicts of 120, all on RIGHT items yes-03
  5/5 and yes-05 2/5); Sonnet stopped partial at cost ceiling, $6.32
  (est. $3.02). Spend ~$20.09 of $28. Repo clean. Cause analysis
  running (thinker, cause-measure.md) before any rerun.
- Cause (scratchpad cause-measure.md): yes-03/yes-05 are right answers;
  Haiku keys on words of the off-by-one rubric's FAIL clause ("at most
  2" echoes "stays within size / as the doc says"; "correct end" in the
  fix). Sonnet before the ceiling: 0 wrong of 675 votes (contradiction,
  doc-rule, off-by-one incl. yes-03/05); role-rule not run. Costs: Sonnet
  ~17x Haiku per vote (not 3x); full Sonnet measure ~$8; role-rule only
  ~$1.6; Sonnet-judged batch $0.34 vs Haiku $0.02; the $4 ceiling
  overshoots at -j 4 (ran to $6.32). Queue: ceiling overshoot; FAIL
  clause wording trap. Owner asked: finish Sonnet role-rule (rec.) vs
  reword + rerun Haiku vs both.
- Owner: "a" -> finish Sonnet on role-rule only ($2 ceiling); if it
  passes, Sonnet judges whole batches (2a, $0.34/batch). Runner on
  brief-run-measure-role.md -> measure-tally-role.txt.
- Sonnet role-rule: 0 wrong of 65 verdicts, 0 splits, $1.23
  (measure-tally-role.txt). Sonnet passes all 4 questions -> Sonnet is
  the judge (2a). Spend ~$21.32 of $28. Worker on brief-judge-sonnet.md
  (bin/ci default judge sonnet). Remaining paid steps: 6 live
  code-reviewer runs (~$1.9) + full run (~$5.9; last full run $4.55 for
  15 runs) = ~$7.8 > $6.68 left: owner asked to raise cap to ~$30 or
  drop the 6 separate runs.
- Owner: "a" -> cap ~$30, both paid steps. 6 live runs started (runner,
  brief-run-live6.md -> live6.json, live6-summary.txt, live6-traces/).
- 48875ae: bin/ci default judge sonnet (gate-judge-sonnet.log exit 0);
  check running (check-judge-sonnet.md). Queue: `relay bench`'s own
  judge still defaults to haiku (bin/relay, docs/benchmark.md) - the
  measurement suggests Haiku misreads meaning; measure before changing.
- First live6 try failed to load (eval target was evals/plugin, not the
  repo root; $0); rerun with bin/ci's invocation.
- 7fbed11: judge-measure README real costs + ceilings (check
  check-judge-sonnet.md MEDIUM, fixed by front desk; goes in the final
  review). live6 (runner ran out of turns after the run; read by front
  desk): $3.37 (est. $1.90), runs 1-5 score 1.0, run 6 code graders
  pass but both meaning judges "not judged" (cost ceiling $3). Run 3
  read the rule file via Bash. The hook's injected text is not in
  traces; the DOC-RULE label only exists in the kit file, so 5 runs that
  used it without reading the file got it from the hook. Traces in
  scratchpad/live6-traces/, temp folders removed. Spend ~$24.69 of $30.
  Full run estimate unsure (cost/run ~$0.56 for this case); owner asked.
- Owner: "a" -> cap ~$35, full bin/ci run with EVALS_MAX_COST=9 (runner, brief-run-full.md -> full-ci.log, full-ci-summary.txt).
- FULL RUN GREEN on 7fbed11 (bin/ci, full-ci.log): all steps ok; 18 of
  18 runs score 1.0 (code-reviewer-offbyone, critic-role-rule,
  guard-fires, plan-one-line, spec-reviewer-flaw, worker-group, 3 each);
  0 meaning graders failed, 0 split votes; critic-role-rule run 1 read
  the rule file via Bash (flagged). Cost $4.99. Spend ~$29.68 of $35.
  Runner ran out of turns again (queue: runner turn limit when waiting).
  Check of 7fbed11 (README) running; then the owner's word on merging
  wt/role-bases.
- Check of 7fbed11 (check-readme-cost.md): met, 0 HIGH/MEDIUM, 3 LOW (queue: sonnet figures come from two runs; $10 ceiling worst case ~$13). Waiting for the owner's word on merging wt/role-bases.

## STATE 22 Oct, batch 3 part 1 MERGED (owner: "a")

- master fast-forwarded to 0538b8d (wt/role-bases, 33 commits); bin/ci
  --quick green on master (scratchpad gate-master.log). Worktree batch3
  and branch wt/role-bases removed. Open sessions keep the old agent
  texts until restart or /reload-plugins.
- Judge: code graders for facts + built-in llm graders judged by Sonnet
  (Haiku failed the off-by-one question on wording; measured).
- New worktree for part 2: .worktrees/review-gate, branch
  wt/review-gate (from 0538b8d). Start part 2 in a FRESH session.
- Next step (part 2): fix M-A and M-B in the part 2 design
  (check-design-v3.md, session 0b953f5c scratchpad), fold in the owner's
  pipeline (free code checks -> review stored as linter-form findings
  .relay/checks/<sha>.review.md/.check.md/.gate.log + <sha>.json ->
  human step: chat screen + private page -> merge refused unless gate
  exit 0, mark open 0 and the owner's word; no Woodpecker), then build,
  review, fix, check, gate.
- Queue seeds for part 2 (besides earlier ones): core plugin tests not
  in bin/ci --quick; tally.py traceback on unreadable json, two less
  realistic items, runs count from the prompt (check-judge-fix.md L1-L3);
  eval cost ceiling not firm at -j 4; cost estimates from real numbers
  (four cap raises on 22 Oct); runner runs out of turns while waiting
  (3 times on 22 Oct); off-by-one rubric FAIL clause penalises a fix's
  words; relay bench's own judge still haiku (measure first); Sonnet
  measurement figures come from two runs; guard-main reads `-C $VAR` as
  a literal path (refused `git -C $G branch -d`); 12 of 15 agents have
  no eval; stale texts (case.yaml:3, setup-fixture.sh); guard and
  $TMPDIR.
- Phase 1 decisions (owner, 22 Oct): one shared change cycle for every
  flow, ten correctness checks everywhere, waves in the shared cycle,
  thin OpenSpec add-on (sdd renamed), no per-flow addition files, old
  projects (Kartoteka, principles) not touched. Overview page:
  https://claude.ai/artifact/XMsv3xJxw5uZCtYk4Z3416
- Spend 22 Oct: ~$29.68 of the owner's $35 cap.

## STATE 22 Oct, part 2 design v4 written, critiqued, being fixed

- Session 90ec47d2 (scratchpad .../90ec47d2-c126-4eb7-9ec0-dd339c42d141/scratchpad;
  old v3 design and checks copied to its old/).
- Design v4: docs/plans/review-gate.md (commit 780b8ca). M-A (merge
  commit from master + `relay changed --own`), M-B (gate head via
  `relay changed`), m-1, m-3, m-4 addressed; owner pipeline folded in;
  23 queue seeds. Build: chain B1-B6 + C1-C2, ~250-265 agent min.
- Critique: reports/critic-design-part2.md: 2 HIGH (F1 `relay setup`
  for relay rewrites global settings; F2 queue landing retry loses
  items), 7 MEDIUM, 8 LOW. Fix running (thinker, brief
  briefs/fix-design-part2.md).
- Coordinator decisions (owner may overturn): F4 = a merged worktree is
  never removed while a session runs in it (git worktree lock); F9 = the
  front publishes the page, scripts only write HTML.
- Open owner question 1: paid evals in the merge gate (a: free gate
  decides, paid run proposed per text change, recommended; b: required;
  c: only on request). Spend 22 Oct ~$29.68 of $35.
- Next: on the fix, a checker over the design fix, then build briefs B1..

## STATE 22 Oct, building merge 2 (session 90ec47d2)

- Design v5 checked (open 0). Built on wt/review-gate: B1 313a3c9, B2 dcb470e,
  B3 4e38f26, B4 6c77939 (K9 live $0.444); B5-B6 running. On wt/work-queue
  (.worktrees/work-queue, from 313a3c9): C1 139bda3, C2 8f446e9, time display
  8d54609; readable list running; then queue-json (brief briefs/queue-json.md).
  Join notes: scratchpad join-notes.md.
- Owner decisions 22 Oct (verbatim):
  - Q1 paid evals: "a, you can run paid checks without my approve, increase limit to 50$"
  - queue time: "Store in minutes, for me display in 1h 30m"; "My head can calc this, I care about your calculation, store in minutes plain numbers, show pretty format for me"
  - queue storage: "why we can't store plain json and add scripts for working with this, in future we can add python scripts as extensions for work with it, same for show"; extensions: "a, relay only"
  - review verdicts to JSON in this change: "a"
  - principle: "I want to lock format - persist structured, operate with scripts" -> rules/structured-data.md (in queue-json brief)
- Coordinator decisions (owner may overturn): F4 lock reading; F9 front publishes the page; rules/queue.md gist-only in profiles; queue list rows ip/kind/time/what/name.
- Next: B5-B6 done -> verdict-json (brief briefs/verdict-json.md) in review-gate;
  queue-json in work-queue; then join C into B, sync-lib-copies, gate log by
  runner redirect, paid full bin/ci (~$5; day ~$30.12 of $50), two critics,
  fix, gate, checker, owner's word.

## STATE 23 Oct, merge 2 built, reviewed, fixed; full gate and check next (session 90ec47d2)

- Supersedes "building merge 2" above. wt/review-gate head 897184a holds
  both tracks: chain B (B1-B6), chain C joined by merge commit ce37c72
  (wt/work-queue, worktree .worktrees/work-queue, can be removed after
  merge 2), verdict JSON 3979192, JSON-only reports 0bfb4ec, seams d340ee2,
  fixes edf9fb0 (group A) and 897184a (group B), made in
  .worktrees/review-fix (wt/review-fix, same head; removable).
- Owner decisions since 22 Oct (verbatim):
  - "a, add analytics views to the queue" (item queue-analytics-views, ip 0)
  - "Why we're need readable report if we can store json + script that shows the readable message in single bash command ?" -> reviews/checks stored as JSON only, rendered by `relay check show`; input as TOML files (`--input`), no free text through the shell.
  - earlier: paid runs pre-approved, $50/day; queue time stored minutes, shown "1h 30m"; queue items JSON, extensions in relay only, read-only; verdicts JSON; "I want to lock format - persist structured, operate with scripts" (rules/structured-data.md).
- Coordinator decisions (owner may overturn): queue fix items close through a review record (finding Q1) and the check JSON; the owner's "F<n> is not wrong" and "moved to queue item" stored in the review JSON via `relay check owner`; rules/queue.md gist-only, its "q4 - a" line in the front skill; lock reading of q2 - a; the front publishes the page.
- Review of master...d340ee2: three critics (reports scratchpad
  reports/review-gate-half.json, review-queue-half.json,
  review-remaining.json): 2 HIGH, 16 MEDIUM, 14 LOW, all inside. Fixers:
  reports/fix-a.md (12 Fixed), fix-b.md (all Fixed; remaining F2 =
  this handover, Outside, done here).
- Paid: 23 Oct full run on d340ee2 $5.60 (18 eval cases ok; gate red
  only by the inert step, since fixed).
- Next: full gate (RELAY_GATE, paid evals, ~$5.60) on 897184a+handover
  into scratchpad gate-full-2.log; delegate:checker over the three
  findings files + fix-a.md/fix-b.md + that log; then the owner's page
  (relay check page, published by the front) and the owner's word on
  merge 2; after the merge the steps of design section 14 (relay sync,
  lock this worktree, land outside findings, trim "Open items").
- 23 Oct later: inert mode mismatch fixed (27af3e7); free gate green
  (scratchpad gate-quick-3.log, head 27af3e7, exit 0); paid 18/18 on
  6ebabfe ($5.92; texts unchanged since). Checker reports/check-merge2.json:
  32 MET, open 0, queued 0. Owner's page (hand-built from the review JSON,
  the page builder needs the new hooks): https://claude.ai/artifact/1pJFYJUFuKQHokSMepgK9T
- WAITING: the owner's word "merge". Then design section 14 steps; also
  queue two items: check ids across several review files; critic-role-rule
  eval proof weak (agent read the rule file in 2 of 3 runs).
- Paid 23 Oct: $11.52 of $50.
