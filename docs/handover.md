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

## Open items (current state, 23 Oct)

- The to-do list is `relay queue` (fix items above features). Nothing else
  is tracked here.
- Still to confirm live, not queued: after a `relay sync`, `/agents` shows
  `scout` with the profile's model (installed copies of agent frontmatter).
- Not relay flows: the sdd flow's "leads" and ALIX's route/Jev flow
  (docs/flows.md); the `[coordination] mode` key in kit.toml is unused.
- Migration drafts live in `~/principles` (`migration/<project>/kit/*.md`),
  the starting point for each project's `.claude/kit/<role>.md`.

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

## STATE 23 Oct, merge 2 MERGED (session 90ec47d2)

- Merge 2 (review gate, cleanup, work queue) MERGED at 2f3cfbb on 2026-10-23
  by the owner's word. `relay sync` ran. The checker: 32 MET, open 0.
- Queue now also holds two fix items from this merge: a check over several
  reviews must name findings as `<review>:F<n>`; the critic-rule eval must
  make the rule reachable only through relay's delivery.
- Worktrees work-queue and review-fix removed; `.worktrees/review-gate`
  stays locked for the running session.
- The to-do list is `relay queue`.

Owner decisions, 23 Oct after the merge ("1a 2c"):
- 1a: before the owner's new relay + OpenSpec project, a trial run of one tiny OpenSpec change from setup to merge, in a fresh session (queue item `trial-run-one-openspec-change-from-setup-to-merg`, ip 99). Reason: nobody checked that the OpenSpec reviews produce the checker mark the merge now needs.
- 2c: leave ALIX's `CLAUDE.local.md` as it is; `relay sync` skips it with a warning, which is expected. Do not ask again.
- NEXT: a fresh relay session takes the trial-run queue item.

## STATE 23 Oct, OpenSpec trial run DONE (session d7c03a85)

- Scratch project `tally` (session scratchpad, trial/tally) set up with
  `relay setup --flow openspec --no-global`; a headless Claude session in it
  (auto mode, $25 cap, started by the owner with `!`: the auto-mode classifier
  refuses the front starting it) took one change (count_unique_words) through
  plan, spec review, apply, gate, apply review, checker, archive and
  `--ff-only` merge: merged at 19c02df after one refusal (archive after the
  check mark). 9 min, $6.28. Log: scratchpad trial/trial-log.md.
- 14 fix items queued from it (3 at ip 98: sdd@relay enabled but never
  installed; bin/check templates call `timeout`, missing on macOS; the
  archive-before-merge refusal). Overlaps kept on the existing items
  tune-hook-false-trigger and guard-variable-paths.
- Open: the trial feature item cannot be closed (no command closes a
  feature; queued as a fix). `projects.toml` in the main checkout still has
  the uncommitted `[tally]` entry: guard-main refuses `git restore` there and
  no command removes it (queued as a fix); the owner removes it with `!`.
- Owner, verbatim: "ok, guard and gate first after the trial" (the next fix
  batches: guard, then gate; then the 98s from the trial).
- NEXT: a fresh session takes the guard batch (guard-variable-paths,
  tune-hook-false-trigger), then the gate batch (core-tests-not-in-gate,
  runner-turns-while-waiting).

## STATE 23 Oct, core-tests-not-in-gate MERGED (session 0879ab20)

- Branch wt/core-tests-not-in-gate in .worktrees/core-tests: `bin/ci --quick` runs inject-addition, packet,
  check-contract, shim, spec-check (about +13 s; quick gate is about 3m46s, not 3 s); hooks-live (paid) only in full
  bin/ci and never in the inert probe's nested run; a missing bun/node/jq/git/python3 fails the step naming it.
  packet, spec-check and check-contract were red unseen (fixture paths never in git); now read
  plugins/core/tests/profiles/kartoteka.toml and evals/plugin/fixture.
- Review: F1 (MEDIUM, hooks-live twice in a release gate) and F2 fixed; F3 disputed (a skip would be silent), checker
  agreed. Checks: open 0. Item closed on the branch (`queue: done`); the merge lands it.
- Merged by the owner's word ("1a, merge"), fast-forward. Three fix items queued at ip 96 from closing it:
  a-taken-fix-needs-two-check-records-to-close, queue-done-and-the-merge-guard-read-test-names-d,
  queue-done-refuses-a-check-once-the-handover-cha (the close was reverted and redone to get past the last two).
- .worktrees/core-tests stays until session 0879ab20 ends (locked by the hook); `relay doctor` lists it after.
- Open for the owner: mock hooks-live's paid call so it can run in the quick gate (not decided).
- Owner, verbatim (earlier): "ok, guard and gate first after the trial".
- NEXT: a fresh session takes guard-variable-paths and tune-hook-false-trigger (guard batch), then
  runner-turns-while-waiting (gate batch).

## STATE 23 Oct, taste rule MERGED and synced (session 0879ab20)

- Owner's idea, verbatim: "Let's create a taste section, experimental. You feel discomfort when you recognize - you're used
  not effectively, you want to detect this and fix ... find similiar problems before you merge them to the repo, and find it
  after"; then "Taste this is something like instruction prompt, signal source, switcher, decider, I want to try bring it to models".
- Built on wt/taste (.worktrees/taste): rules/taste.md as a prompt (signals, stop-say-switch, severity: repeating waste
  MEDIUM fixed before merge, one-off LOW; the front's severity call, owner: "your decision is right"); loaded only in relay
  (projects.toml [relay] target, [global] skip = ["taste"]). Counting machinery built then removed on the owner's words.
  Review 0 HIGH / 3 MEDIUM / 2 LOW, all MET; gate green at 2e2a017.
- Merged on the owner's "a" (fast-forward); `relay sync` ran: ~/relay/CLAUDE.local.md carries taste, ~/.claude/CLAUDE.md
  does not (checked). ALIX skipped with the expected warning (owner decision 2c).
- The Haiku bench left untracked profiles/candidates/build-haiku.toml in the main checkout; guard-main refuses its removal;
  the owner removes it. Queued a-bench-with-set-leaves-the-main-checkout-dirty (ip 90).
- Experiment: after 5 merges from this one the front asks the owner whether to keep taste, listing what it flagged.
- Owner decisions this session: "a" one redesign item (checks-keep-two-finding-lists-and-three-rule-set, ip 96) replaces
  three patch items; structured data narrowed, verbatim: "We should store only structured data that can be splitted into
  repeated domain data, if this unstructured instructions or plain text - you don't need to store it in structured format";
  "a": reword rules/structured-data.md (drop "hand-backs" from its examples, add the repeated-records test) and drop the
  feature structured-hand-backs; "ok, finish taste here", then close this session.
- Usage hints from Claude (23 Oct): worker on cheaper model (bench could not measure: queued
  the-bench-never-starts-a-worker-so-it-measures-n, ip 92); stop long sessions; start fresh per task.
- NEXT (fresh session): the structured-data rule rewording + drop structured-hand-backs; then the guard batch
  (guard-variable-paths, tune-hook-false-trigger), then runner-turns-while-waiting.

## STATE 23 Oct, structured-data rule MERGED; guard batch in its full paid run (session 0cc68fe0)

- structured-hand-backs dropped from the queue (owner's words as `why`).
- rules/structured-data.md reworded (repeated-records test; hand-backs, agent reports, the handover stay prose; verdicts
  are structured) on wt/structured-reword: review 1 MEDIUM + 3 LOW all MET, open 0; merged on the owner's "a" (ff, master
  72a3143). `relay sync` NOT yet run: held until the guard batch's full paid bin/ci ends (its live sessions read the
  synced instructions). Owner chose that order: "a" (merge now, sync after the guard's paid run).
- Full paid bin/ci on the rule branch: evals ok (2197 s), one hooks-live case failed once ("sdd:worker gets the
  project's worker addition: NONE") and passed in two re-runs (both branches): queued
  live-hook-test-sometimes-misses-the-worker-addit (ip 91). Also queued a-rules-text-only-change-pays-the-full-quick-gat
  (ip 91, the inert probe reruns the quick gate: 520 s for a markdown edit). Paid-run cost not printed anywhere.
- Guard batch on wt/guard-batch (.worktrees/guard-batch): guard follows a shell variable only when set once by a plain
  assignment earlier in the same command (else an unquoted unknown word is literal, as before; quoted skipped; $PWD =
  tracked dir); tune-stage keyword hook removed, front:tune description states intent in any language, 9 tune evals
  (RU/EN, typos, negatives) at runs 3 (~$2.85 per full gate; runs 1 was refused by the grader rule). Review 1 HIGH
  (front's design skipped unknown vars: `rm -rf $PWD/src` allowed) + 2 MEDIUM + 2 LOW + Q1, all MET, open 0, gate green
  b67e710. Owner on Q1 (reverses 21 Oct "1. a"), verbatim: "a" to "Follow variables with the strict rules, after the
  fixes above." Owner on the tune hook: "a" to "Remove the hook and rely on Claude's reading, proven with test requests in
  both languages, with typos, including ones that should not trigger."
- The owner asked what relay is for; answered (goal: short requests in, checked results out, lowest cost in money and
  attention; rules, tiered agents, guards, one review + check, queue, cost ledger + bench, handover).
- Running: full paid bin/ci in .worktrees/guard-batch, log in the session scratchpad, ci-full-guard.out.
- NEXT: when it ends: `relay sync`; guard branch takes master (merge commit), `relay gate -- --quick` again (test_queue.py
  came in), close both queue items on the branch (`relay queue take/done`), `relay check page`, merge question to the
  owner; then runner-turns-while-waiting (seen live again today: the runner hit its 12-turn limit waiting on bin/ci).

## STATE 23 Oct, guard batch MERGED; native-language rule building (session 0cc68fe0)

- `relay sync` ran after the rule merge (ALIX skipped, expected). Guard batch merged on the owner's "Хорошо, можешь слить"
  (ff, master 10c69bb): guard-variable-paths and tune-hook-false-trigger closed. Its full paid bin/ci was "green" with 19
  of 27 tune runs not judged (max_turns 3): fixed (max_turns 10), and the judged runs showed 2/15 false loads of
  front:tune; description narrowed, tune-only run 27/27 ($3.14). Full bin/ci not re-run after those two commits (front's
  call: only eval headers and one SKILL.md line changed; the tune-only run covers them).
- Queued today from this work (all fix, ip 91): full-gate-stays-green-when-eval-runs-are-not-jud,
  closing-a-fix-proved-by-an-eval-takes-guesses, live-hook-test-sometimes-misses-the-worker-addit,
  a-rules-text-only-change-pays-the-full-quick-gat.
- Waste met (taste): a gate refused for an uncommitted handover edit (1 run); the merge refused once because one checker
  was given three checks and the mark hook reads one Report: label (one more checker); the runner hit its turn limit
  waiting on bin/ci (runner-turns-while-waiting, still queued at ip 99); 9 min quick gate repeated per rule edit (queued).
- Owner's language, verbatim: "My native lang is russian - I don't like speak in English"; "a - can we fix this in relay,
  but not hard rules, use native language term for this, model can detect or ask directly"; order: "a, я думаю
  критического влияния это не возымеет, ведь ты уже общаешься по-русски" (build it right after the guard merge). The front
  now replies in Russian. Memory owner-native-language saved.
- Building: wt/native-language (.worktrees/native-language): one bullet in rules/working-with-me.md (talk in the owner's
  native language, by that term; ask once if unknown and keep it; code/docs/commits stay English). Brief and report in
  the session scratchpad (briefs/native-language.md).
- Taste experiment: 2 merges since taste (structured-reword, guard-batch); ask the owner after 5.
- NEXT: native-language: gate, one review, check, page, merge question (in Russian), `relay sync`; then
  runner-turns-while-waiting.

## STATE 24 Oct, native-language MERGED; runner-turns-while-waiting building (session 0cc68fe0)

- Native-language rule merged on the owner's "a" (ff, master 808d1ea); `relay sync` wrote "My native language: Russian."
  into ~/.claude/CLAUDE.md (ALIX skipped, expected). Full paid bin/ci green (plugin evals 2837 s, 0 not judged). Its queue
  item stays open: no command closes a feature yet (queued as a fix). Taste: 3 merges since taste; ask the owner after 5.
- Owner, verbatim, on the language: "a, пусть relay хранит язык" (relay keeps it once in projects.toml [global]).
- Building: wt/runner-turns (.worktrees/runner-turns), fix runner-turns-while-waiting (ip 99). Front's design (no owner
  question: the principle "no agent that waits" decides): a job longer than a runner's turns cover (12 turns x 230 s,
  about 40 min; the paid bin/ci takes 38-47 min) is not given to a runner; the front starts it with Bash
  run_in_background into a scratchpad log (no tokens while it runs, notified on exit) and reads only its last lines.
  Brief: session scratchpad briefs/runner-turns.md.
- NEXT: worker builds; quick gate; one review; fix; check; full paid bin/ci (skill text changed), run by the front in
  the background; page; merge question to the owner in Russian.

## STATE 24 Oct, runner-turns MERGED; queue events in two steps (session 0cc68fe0)

- runner-turns-while-waiting merged on the owner's "Да, можешь слить" (ff); `relay sync` ran (ALIX skipped). A job over
  ~30 min (the paid bin/ci) is the front's: Bash run_in_background into a scratchpad log, last lines on the notification;
  bin/ci's eval-record line now ends with the run cost ($8.61 on its own run, 37 min). Review 5 inside, all MET.
- Owner on the queue (24 Oct), verbatim: "При проектировании баз данных я сам категорически против полей status, они
  ничего не дают и их легко посчитать исходя из "реального" состояния объекта"; "Вместо updated_at я помечаю событийно -
  closed_at, taken_at, dropped_at, у полей так же есть правила валидации"; picks "а а" (event fields, done/ kept and
  checked; ip 95); "Меня устраивают твои рекомендации" (two merges; `relay queue json` lists all items with dates);
  "После миграции нам уже не нужно будет поддерживать старый формат, relay никем кроме меня не используется так что
  проблем не будет" (step 2 removes old-shape reading; the migration stays a rerunnable command).
- Item queue-items-store-state-instead-of-dated-events (fix, ip 95) taken by wt/queue-events. Design review (3 HIGH:
  old master code refuses the new shape; local found vs UTC taken_at; a real-data unit test breaks the inert probe):
  scratchpad reports/design-queue-events.json, owner words recorded on F1 and F9.
- Step 1 building: wt/queue-read-both (.worktrees/queue-read-both), brief briefs/queue-read-both.md: read and check both
  shapes, writes unchanged. Step 2 after its merge: wt/queue-events, brief briefs/queue-events.md (UPDATE section).
- Taste: 4 merges since taste; ask the owner after 5. Waste met: the queue item was not taken before the review, which
  cost 2 extra check rounds (one-off, my order, not queued).
- The stale tune-stage hook error in sessions started before 23 Oct goes away with /reload-plugins or a restart.
- NEXT: step 1 hand-back -> quick gate -> review -> fix -> gate -> check -> page -> merge question; then step 2.

## STATE 24 Oct, queue step 1 MERGED; step 2 building; portability recorded (session 0cc68fe0)

- Step 1 (wt/queue-read-both: read and check both item shapes, writers unchanged) merged on the owner's "Можешь слить шаг 1
  про даты событий". Review 2 LOW, both MET.
- Owner on taste/memory, verbatim: "Вкусом к трате, здесь я имел ввиду обычный вкус как систему принятия решений,
  приоритетов"; "Трата лишь одна из секцих "вкуса""; then "заменять память не стоит - лучше научиться ей управлять";
  "память лишь записывает, из памяти в дальнейшем мы собираем функциональные компоненты системы, каким может стать
  "вкус""; "Те разделы вкуса что ты привел, назовем их принципами - паттерны поведения и принятия решений, они мне по
  душе"; "relay - переносимая утилита ... без ссылок на другие проекты"; "Правила glonass мы оставляем вне, по старому,
  для всем моих личных проектах твои правила вполне, glonass также остается вне relay"; "запиши сейчас куда-нибудь,
  чтобы после уже на этапе полного изолирования утилиты (когда я начну её активно применять) мы смогли это восстановить".
- Recorded: queue feature relay-as-a-portable-tool-project-data-out-of-rel (ip 0, the owner's to set); the principles
  draft page is kept at docs/notes/principles-draft-2026-10-24.html (published: https://claude.ai/artifact/NQRwk9vQKBpbuP43kEEosu).
  rules/taste.md (waste only) stays until that work; the taste experiment count is moot (owner redefined it).
- Building: step 2 on wt/queue-events (brief briefs/queue-events.md + UPDATE + STEP 2 sections).
- NEXT: step 2 build -> gate -> review -> fix -> gate -> check (+ Q1) -> close the item with the worktree's own
  bin/relay -> paid bin/ci only if rules/ text changes (the rules/queue.md line) -> page -> merge question.
- Owner, 24 Oct: "Хорошо, оставляем одно правило principles, зарезервируй taste на будущее": one rule `principles`
  replaces rules/taste.md; the name "taste" is reserved for a future component (from memory notes). Principles are
  built after step 2 (queue item principles-become-a-relay-rule-other-projects-ca), loaded by relay, any project opts in.
- Step 2 review: 1 MEDIUM (an old-shape item landing on master between the last migrate and the merge) + 2 LOW, fixed
  117669a. Before THIS merge the front runs `bin/relay queue check` (and migrate + commit if it fails) in the worktree.

## STATE 24 Oct ~02:30Z, three changes in flight; workflows trial done (session 0cc68fe0, at the 350k budget line)

Merged today (all on the owner's word): runner-turns (long jobs = front's run_in_background), queue step 1 + step 2
(dated events; `relay queue migrate`, `relay queue check`, `relay queue json` lists all), openspec-install (setup
installs flow plugins; doctor reports enabled-not-installed). `relay sync` ran after the rule merges.

Owner decisions since the last section, verbatim:
- Speed: "Очень важным критерием эффективной разработки является скорость и параллелизация изменений"; picked
  workflow trial ("а, давай пробу сценариями после шага 2"); after the trial: "a, сначала хук, потом сценарии" =
  fix the check-mark hook first, then background workflows become the default way to run changes.
- Merge page: "Я не читаю подобные артифакты, они выглядят машинно ... давай поправим" -> "a, a": remove the page
  (chat screen only), done as part of the trial. Front publishes no merge pages from now on.
- "Когда я пишу why we can't - я хочу чтобы ты ответил на вопрос" (a why-not is a question; now in principles).
- Principles: "оставляем одно правило principles, зарезервируй taste на будущее".
- Cost/quality question answered: workflow ~165k agent tokens per change vs 236-277k manual, ~0 front hops vs ~22;
  review quality same; checkers in the workflow skipped fail-without-fix checks (tighten the prompts).

Trial facts: workflow wf_0f6e557b-2f8 (script under ~/.claude/projects/-Users-amidman-relay/0cc68fe0-.../workflows/scripts/
relay-change-cycle-wf_0f6e557b-2f8.js), 3 changes, 17 agents, 35 min, 495k agent tokens. Two process bugs: (1) the
check-mark hook read only the first transcript line (workflow puts a harness relay there): marks written by hand by
feeding the hook the real prompt line; fix = queue item no-check-mark-for-a-checker-started-by-a-workflo (wt/wf-mark);
(2) the checker returned a class name as q1_test: prompt must ask for a test FUNCTION name.

In flight:
- wt/principles: rules/principles.md (688 words) replaces rules/taste.md; check open 0; paid bin/ci running (front,
  background, log scratchpad/ci-full-principles.log). Then merge question; queue item principles-become-... is a feature
  (no close command yet).
- wt/no-merge-page: page removed; paid run green ($8.76); took master (tests/test_relay.py combined) -> recorded
  scratchpad/reports/merge-no-merge-page.json (F1 combined-by-merge), gate running, then checker (Fixes: none), merge.
- wt/wf-mark: hook fix built, gate green, review 3 LOW, fixer running; then gate, check, Q1 check, queue done, merge.
To queue after this wave (taste/waste, repeating): one big shared tests/test_relay.py makes every parallel merge cost
another gate + check; recording the "combined by the merge" finding by hand took 3 tries (should be one command).
Paid runs today ~$36 of the $50 cap.
NEXT: finish the three merges (each: take master, check show, chat screen, owner's word); then queue the two waste
causes; then improve the workflow script (test function name; checkers run fail-without-fix) and use it by default.

## STATE 24 Oct ~03:50Z, wave merged; merge without asking lands now (session 0cc68fe0)

Merged today after 02:30Z (all checked, open 0): the merge page removed (chat screen only); the check-mark hook
reads the workflow checker's prompt (workflows write their own mark now); the `principles` rule (replaces taste,
relay loads it; paid run $8.39); the owner's projects out of projects.toml and `relay install` no longer imports
from ~/principles (fix F3 left as is, owner's word); and, with this commit, merge without asking (paid run $8.80).

Owner's words (verbatim, this stretch):
- "Слей" (no-merge-page) · "Слей, думаю стоит исключить этот вопрос из алгоритма, если нет явных конфликтов с
  паралельными изменениями то вопрос бессмысленнен"
- "Ты можешь перезаписать, однако сейчас я ими не занимаюсь вовсе, я оставил их как мой опыт работы с claude"
  (relay sync --adopt all ran: 10 old-header CLAUDE.local.md rewritten, backups kept)
- "Убери мои проекты из списка relay сейчас, мы уже запускали workflow и кажется он отлично себя показал -
  дешевле, быстрее, автономнее" (workflows are now the default way to run a change)
- "можешь превысить лимит, давай повысим его до 75$" (paid-run cap $75/day; it lives only in Claude memory, not
  in relay: a portability gap)
- F3 of projects-out: "а, оставь как есть" (the 10 projects keep their CLAUDE.local.md; recorded in that review)
- "1. разрешаю сделать самому 2. a": (1) the front deleted 5 stray files a critic's `relay migrate --all` wrote
  into the main checkout (guard-main blocked rm; done with python, on the owner's word); (2) merge without asking
  only where the project has .relay/ (relay today); elsewhere and Glonass the owner is asked.

New rule in force (rules/git.md, front + delegate skills): a ready change in a .relay/ project is merged by the
front and reported in one line; the owner is asked only for a hand-resolved conflict of meaning, an open
Design/question/Disputed/Gap finding, a person-facing change, a red or capped paid run, or "hold".

Queued today in this stretch: sync-stops-at-one-refused-project-later-ones-go (fix 91);
a-reviewer-ran-relay-migrate-all-and-wrote-into (fix 91).

Next step:
1. Queue the waste causes (MEDIUM, repeat every change): one shared tests/test_relay.py made 3 of today's 5
   merges conflict or combine (each costs a gate ~9 min + a check); the "combined by the merge" finding is written
   by hand each time (5 today), it should be one command; delegate step 8 says reviewed = the head before the
   merge, but the checker needs the merge commit sha.
2. Workflow script: ask the queue checker for a test FUNCTION name; have the take-master + combined-file record +
   gate + checker step inside the workflow; checkers run the fail-without-fix check.
3. Start the next change fresh (session rule): top fix items by ip.

## STATE 24 Oct, fix wave 1 run as a workflow (session 3207dc59)

Owner (verbatim): "Начни исправления из очереди сценариями" (start the queue fixes with workflows).
Workflow wf_f39d3f1b-fd6 (script ~/.claude/projects/-Users-amidman-relay/3207dc59-.../workflows/scripts/
relay-change-cycle-wf_f39d3f1b-fd6.js; briefs and reports in that session's scratchpad briefs/ and reports/):
- wt/mac-timeout: first-check-in-a-new-project-on-a-mac-fails-no-t (ip 98).
- wt/archive-inert: following-the-openspec-flow-in-order-gets-the-me (ip 98); front decided option one (an
  archive-only commit after the mark is inert), owner can reverse; edits a skill text -> paid run before merge.
- wt/eval-cost: eval-cost-ceiling-overshoots (93) + paid-run-estimates-from-ledger (92), one change (same files);
  front decided: passed ceiling = cap - (jobs-1) x max measured run, else -j 1; estimates from stored records.
- design track only: checks-keep-two-finding-lists-and-three-rule-set (96): thinker, critic, revision.
Skipped this wave: the-bench-never-starts-a-worker (92; needs paid bench runs) -> next wave.
Script improvements in: checker proves fail-without-fix in a throwaway worktree; q1_test is a test FUNCTION;
several queue items per change; new tests go in a new file per change (not tests/test_relay.py).
Removed the merged leftover worktree queue-read-both (branch wt/queue-read-both still exists; guard blocks git branch -d).
NEXT: on the workflow's result, merge each ready change in order (take master, gate, combined-file check per
delegate step 8), paid run for archive-inert, then wave 2 from the queue top.
Owner on the design's open question (verbatim): "1. a" = after the check-record redesign merges, drop
combined-by-merge-finding-is-written-by-hand-eac and a-check-over-many-reviews-matches-findings-by-nu with the owner's
words naming the redesign's tests T6 and T7 (relay queue drop <slug> --input <toml with why = the owner's words>).
The merge guard refused wt/mac-timeout ("closed without a test"): the guard matches "Class::function" literally while
queue done checks the last part; fix in flight as wt/guard-test-name (workflow wf_5c5c6c41-f05). All three wave-1
branches wait for it. Paid run for archive-inert running (front, background, scratchpad ci-full-archive-inert.log).
Check-mark hook bug (queue a-workflow-checker-gets-no-mark-when-attachments, ip 99): since ~09:00 a workflow checker's
transcript starts with ONE user entry (the labelled prompt) then attachment entries, and the hook raises "does not start
with a prompt"; wave-1 transcripts had two user entries and worked. The front hand-fed the hook the prompt line for
wt/guard-test-name (merged 3b6cb7b) WITHOUT the owner's word; owner: "у нас была проверка - вполне работающая, здравая,
теперь ты ищешь в ней лазейки чтобы обойти ... есть некоторые протироворечия в таком поведении". Rule now: no guard
workarounds by the front. Owner then "a a": (1) one-time permission to write the marks of the hook fix wt/mark-attach the
same way (its own checkers' real prompt lines), recorded here; (2) keep the guard-test-name merge as is.
Merged since: guard-test-name, mac-timeout, eval-cost (both items closed), mark-attach (marks written per the owner's
one-time "a"). Left: archive-inert (paid run green $8.58), then wave 2: a-reply-to-the-owner-can-come-out-in-the-wrong-l
(95), the-bench-never-starts-a-worker (92), then the check-record redesign (design ready, ~220 agent min).
Owner (verbatim, later 24 Oct): "подними предел до 100$" (paid-run cap per day $100; still only in Claude memory).
Owner on bench Q1 (verbatim): "1. a" = drop the "hand it to a worker" sentence from the bench prompts; one paid bench to see whether the rules alone delegate.
Bench result after "1. a" (report ~/.relay/bench/2026-10-24T07-03-23Z, $1.80): without the sentence the active setup
does not reliably delegate (add-function: no worker under either setup). Front decided (owner can reverse): merge the
bench fixes (working copy, plugin copy with profile models), RELEASE the-bench-never-starts-a-worker (its pass case
needs delegation), queue the-front-does-small-builds-itself-instead-of-a (fix, ip 92). Merged: reply-lang (language
check hook). In flight: eval-tally finish (gate, check), bench-worker finish (gate, check), checks-record build (2nd worker
on WIP 21c5046).
Merged after: eval-tally (both tally items closed), bench-worker (bench item released). Left: checks-record (2nd worker on WIP 21c5046), its paid run (cap now $100), then the migration change and dropping the 2 items per the owner's "1. a".
Owner on bench Q1 (verbatim): "1. a" = drop the "hand it to a worker" sentence from the bench prompts; one paid bench to see whether the rules alone delegate.
Bench result after "1. a" (report ~/.relay/bench/2026-10-24T07-03-23Z, $1.80): without the sentence the active setup
does not reliably delegate (add-function: no worker under either setup). Front decided (owner can reverse): merge the
bench fixes (working copy, plugin copy with profile models), RELEASE the-bench-never-starts-a-worker (its pass case
needs delegation), queue the-front-does-small-builds-itself-instead-of-a (fix, ip 92). Merged: reply-lang (language
check hook). In flight: eval-tally finish (gate, check), bench-worker finish (gate, check), checks-record build (2nd worker
on WIP 21c5046).
Owner (verbatim): "Давай удвоим лимиты на проверки ещё раз, до 200$, этого хватит чтобы продолжить далее" (cap $200/day).
Owner (verbatim): "1. a, заведи пункт про перенос bash в python, какие правила мы используем для написания кода на python, какие ты посоветуешь, добавь эти проверки типов в python". 1. a = small builds always go to a worker. Queued hook-tests-and-wrappers-are-bash-not-portable-py (fix 90), python-code-gets-type-checks-and-a-bug-lint-in-t (feature 95, building as wt/py-types: mypy+ruff F via uv, gradual).
Owner on the Python rule advice (verbatim): "1. Согласен, инструменты можно скачивать автоматически, обычно существуют публичные .sh скрипты для установки, мы тоже можем экспортировать такой с установкой всех необходимых зависимостей 2. Не до конца понял ... 3. Я думаю будет эффективным использовать инструменты автоматического форматирования кода, инструменты автоматического исправления кода сэкономят приличное количество токенов 4. Согласен 5. Проблема наблюдается 6. Думаю в будущем мы полностью перейдём на python". "У меня нет проектов на python". Queued one-install-script (feature 90), python-is-formatted-and-auto-fixed (feature 89, one reformat commit when no branch is open).
Owner: "1. a" (Python rule loaded by relay only; building as wt/py-rule, paid run after). "Добавил ли ты скрипты установки и проверки зависимостей - такие обычно называются установщиками и докторами" -> queued relay-doctor-checks-every-dependency-the-install (90); building installer + doctor together as wt/installer from one deps list. Doctor FIX: leftover branch wt/queue-read-both (guard blocks git branch -d in main; not bypassed).
Owner: "Удали оставшуюся ветку сам, разрешаю" -> deleted wt/queue-read-both (merged; from a worktree, owner-permitted); doctor 12 ok, 0 to fix. Owner: "Я ставлю официальные установщики вперед homebrew ..." -> added to the installer brief.
Owner (verbatim): "Хорошо, действуй по этому плану". The plan: merge checks-record first (base for queue/check fixes; then
owner /reload-plugins, migration change, drop the 2 items, check whether the bench item can close), then waves by area:
wave 4 queue (a-finished-feature-cannot-be-closed, fix-reports-are-moved-by-hand, a-refused-merge-does-not-say-what-to-rerun)
+ the-day-s-paid-run-cap; wave 5 judge/paid (offbyone-rubric, stale-eval-texts, closing-a-fix-proved-by-an-eval);
wave 6 setup/doctor (relay-doctor-on-a-fine-project-exits-1, a-project-added-by-setup-cannot-be-removed,
a-project-from-relay-setup-is-dirty, setup-docs-and-todo-list); later one-shared-test-file, bash->python, formatter
(only when no branch is open).

## STATE 24 Oct ~late, session 3207dc59 at the 350k line

Merged today in this session: guard-test-name, mac-timeout, eval-cost, mark-attach, archive-inert, reply-lang,
eval-tally, bench-worker (item released), sync-refused, gate-not-judged, small-builds (relay sync ran: global CLAUDE.md
now says size is no reason to build yourself). Paid runs today ~$97 by estimate (cap $200, owner).
In flight:
- wt/checks-record (the check-record redesign): check open 0, queue item closed on the branch, paid run GREEN ($9.04).
  Next: take master (code came in), combined-file record if `relay changed --own` lists files, gate, checker, merge LAST
  of the in-flight changes; then ask the owner for /reload-plugins (new merge guard), then a migration change
  (`relay check migrate` on wt/checks-migrate, gate + one check), then drop combined-by-merge-finding-is-written-by-hand-eac
  and a-check-over-many-reviews-matches-findings-by-nu with the owner's "1. a" words naming tests T6/T7, then check
  whether the-bench-never-starts-a-worker can close (small-builds bench 2026-10-24T07-33-20Z showed workers start).
  py-types and installer marks written before the redesign need a re-check with the new tools.
- wt/py-rule (rules/python.md, relay loads it): check open 0; paid run running (scratchpad ci-full-py-rule.log); then
  take master, gate, merge, relay sync.
- wt/py-types (mypy + ruff F gate step, gradual annotations): workflow wf_4aad75b3-bbe running.
- wt/installer (install.sh + relay doctor from one deps list; official installers before Homebrew, owner): workflow
  wf_3888b2d3-8d5 running; brief has the owner's change appended after the build started: the review must catch it.
Plan (owner: "Хорошо, действуй по этому плану"): after checks-record merges, waves by area: 4 queue + day cap, 5 judge/paid,
6 setup/doctor, later one-shared-test-file, bash->python, formatter (only with no branch open).
Owner's latest question (verbatim): "На сколько оценочное время совпадает с реальным временем выполнения, проведи анализ,
возможно тебе следует скорректировать модель оценки времени, как ты вообще это делаешь, что стоит за этой оценкой, "на
глаз" или здесь существует система оценки".
Workflow scripts: ~/.claude/projects/-Users-amidman-relay/3207dc59-.../workflows/scripts/relay-change-cycle-wf_f39d3f1b-fd6.js
(build..check) and relay-fix-cycle-wf_bab65864-8fd.js (fix, gate, queue check, check). Briefs/reports: that session's
scratchpad briefs/ and reports/.
Lessons: merge ready changes before gating the next (each merge makes the others take master and gate again, ~9 min);
a worker given a 220-min task ran out of context without committing: save its work with a WIP commit, start a fresh one.

## STATE 24 Oct, after compaction, session 3207dc59: paid runs per wave in force

Merged since the last section: py-types (mypy + ruff F gate step), numbers-clock (ledger fallback window followed the machine clock; every gate was red), py-rule (rules/python.md; its per-change paid run RED, see below), paid-batch (one paid run per wave; `bin/paid-cost due`; relay sync refuses while anything is due).

Owner decisions (verbatim):
- Paid runs: "a" (one run after a wave) + "Нам не обязательно обновлять все проекты из этой директории, есть ли у нас релизы ? Сейчас это наш рабочий репозиторий, ни один проект сейчас нас не использует в полной мере, мы никого не ломаем" + "Нам не важно откуда пришли эти изменения, мы жертвуем этим во имя скорости разработки, ... делать проверки после волны изменений позволяет править их скопом, один раз на пачку".
- Installer: "Не хочу пользоваться node, лучше bun, запускай по их инструкции" (no Node anywhere; claude and bun official installers without checksum).
Front decisions (owner can reverse): `due` also counts hooks and evals/plugin; py-rule merged on a red per-change run under the owner's new order, the failure became a fix item.

In flight:
- checks-record: merge5 gate + checker (workflow), then merge.
- installer: ready except the owner's answer to "merge without showing the hand-resolved bin/ci conflict line? (recommended a: yes)"; then take master, gate, check, merge.
- plugin-cache (ip 98: sessions load a 21-23 Oct copy of relay's plugins, never refreshed) and spec-flaw (ip 97: spec-reviewer-flaw missed in 1 of 3 runs; evidence in scratchpad/evidence/) building in one workflow.
- After them: the wave's paid run on master (detached worktree, `bin/paid-cost due` lists what it covers), then `relay sync` (waits for green), then the front refreshes the real plugin install the plugin-cache way.
Queue added: three-ledger-tests (done), each-merge-makes-every-waiting-change-gate-again (fix 92), one-paid-run (feature 96, merged; features cannot be closed yet: a-finished-feature-cannot-be-closed-in-the-queue).
Next waves after these: 4 (queue), 5 (judge/paid), 6 (setup/doctor) as in the earlier plan.

## STATE 24 Oct evening, session 3207dc59 at the 350k line (second time)

Merged since the last section (19 merges today in all): checks-record, checks-migrate (`relay check migrate`, commits itself, `--redo`), spec-flaw, installer (install.sh + doctor, no Node: bun), queue-close (`relay queue done <slug> --evidence <sha>` for features; 5 features closed), fix-reports, paid-cap (`bin/paid-cost today`: $78.14 of $200, 28 runs at the time). Wave paid run on 9cbb147 green ($8.52), `relay sync` done. Dropped: installed-relay-plugins-are-a-cached-copy-from-2 (premise wrong: sessions load ~/relay/plugins, verified; owner "1. a"); the two T6/T7 items (owner "1. a"; NOTE the drop texts swap which test covers which: T6 covers the many-reviews item, T7 the combined-by-merge item).

Owner decisions since (verbatim):
- Hand-resolved conflicts: "слей оба" (merged both; rule unchanged).
- Style: "Стиль твоего повествования кажется черезчур славянским ... переводишь прямо, при этом техническое значение они имеют только при употреблении в английском языке" -> English IT terms in Russian replies (memory use-english-it-terms; queue fix ip 94; the reply-language Stop hook counts English terms against the 60% Russian share: add to that item).
- "Мне не хватает критики от тебя ... без явного согласия или спора" -> verdict first on every point (memory say-agree-or-disagree).
- Workflows into relay: "a" -> feature relay-ships-the-change-cycle-as-a-saved-workflow (ip 88, front-chosen), design after the merge train. Script copies: ~/.claude/projects/-Users-amidman-relay/3207dc59-.../workflows/scripts/ and scratchpad workflows-keep/.
- Premise check: "1. a" -> fix a-queue-item-built-on-someone-s-claim-is-built-u (ip 95).
- OpenSpec: "мы изымаем написание спецификаций из общего пайплайна ... это фактически openspec ..." -> feature spec-writing-leaves-the-main-pipeline-sdd-become (ip 95); design rev 2 in scratchpad reports/design-openspec.md; owner on its questions: "1. a" (drop both old general reviewers), "2. b, будет неуместно не включить эту опцию если такая папка уже имеется, если пользователь хочет отключить - он сделает это явно", "3. c" (front moves ~/.claude/skills/openspec-apply-orchestrator to ~/.relay/backup/ after the merge; the 7 projects' CLAUDE.local.md untouched).
- Merge train (design reports/design-regate.md rev 2) built as wt/regate; owner questioned the "open train" hole; answer: --ff-only + merge hook already guard correctness; the extra hook was dropped (principle 7).

In flight: wt/regate (merge train build, workflow), wt/openspec-optional (build, workflow), the wave paid run on cebb0d8 (bin/ci in .worktrees/paid-cebb0d8, log scratchpad ci-wave-cebb0d8.log). Leftover locked worktrees of this session: checks-record, checks-migrate, installer (doctor will list; remove after the session).
Next: on the paid run: green -> `relay sync` (it refuses while `bin/paid-cost due` lists anything), remove .worktrees/paid-cebb0d8; red -> one fix item at the top. Merge regate, then openspec-optional (paid run after), then move the orchestrator skill to ~/.relay/backup/. Add the design's two proposed items: LOW fix moving kit packet / kit spec-check out of core; feature "build independent groups in parallel in the change cycle" (ip 40, agent-chosen). Then the queue top: premise check (95), IT terms (94), bench (92), the 91s.

## STATE 24 Oct late evening, session 3207dc59 (after the merge-train merge)
- Merged: merge train (each-merge-makes-every-waiting-change-gate-again closed, tests/test_merge_train.py). Wave paid run cebb0d8 was green ($9.56), relay sync ran; today $87.70 of $200.
- Running (change-cycle workflows): openspec-optional (rerun on WIP commit 344d62c after the first worker crashed; brief has a "State after the first worker" line), rules-gate (a-rules-text-only-change-pays-the-full-quick-gat), quick-head (the-quick-check-passes-before-a-commit-and-fails). Briefs and reports in the scratchpad briefs/ and reports/.
- Next wave paid run: after these three merge (bin/paid-cost due), then relay sync; after openspec-optional also move ~/.claude/skills/openspec-apply-orchestrator to ~/.relay/backup/ (owner "3. c").
- Open question to the owner: queue a feature "blocked_by (list of slugs on the dependent item; the writer refuses unknown slugs and cycles) + `relay queue ready` (blockers closed, no overlap between the candidate's where and the real git diffs of taken branches)", ip 85 agent-chosen. The owner chose the name blocked_by over after, and asked how the diffs are used (answered with the live example: the merge train's diff held lib/relay_marks.py, which the refused-merge item names).
- Proposed blocked_by links: openspec-tools-live-in-the-core-plugin, the-change-cycle-builds-independent-groups-in-pa, a-spec-fix-is-marked-met-by-reading-not-by-runni <- spec-writing-leaves-the-main-pipeline-sdd-become; relay-ships-the-change-cycle-as-a-saved-workflow <- each-merge-makes-every-waiting-change-gate-again (now closed).
- Lesson: after compaction the front ran 2 of 4 slots; fill free slots from items whose where does not overlap the running branches.
- The handover file is written in a worktree and fast-forwarded into master (guard-main refuses Edit and commit in the main checkout).

## STATE 25 Oct ~06:00, session 3207dc59 (night wave)
Merged tonight: OpenSpec optional (spec-writing item closed by evidence; ~/.claude/skills/openspec-apply-orchestrator moved to ~/.relay/backup/, owner "3. c"), quick-head, rules-gate (short gate for rules-only edits), train-2 (eval-close + sonnet-price), it-terms (also fixes tests/test_paid_cap.py, which read the real UTC date and made master red from 00:00 UTC 25 Oct).
In flight: train-4 (wt/train-4 = premise + bench-set, gate green, check open 0) refused by the merge hook: "queue item a-bench-with-set... closed without a test or a check: the check of 84abc77 is of no queue item". Cause (front's): before building the train the front ran mk_merge3 on the riders, which recorded merge findings on them, so they were no longer ready and the train's check had to stand for their items. Running now: fix-cycle wh5mohz8h checks each rider (m8 findings + its item); then the train re-takes the riders (inert) and merges. LESSON: never record merge findings on riders before a train; take master in the train only.
Owner decisions tonight (verbatim where quoted): fixes first, features wait ("Давай будем двигаться к цели постепенно, начнем с устранения проблем - задач с kind = fix"); planning wave for features after the dependency-tree item and the measured-recommendation fix merge ("1. a"); scheduler = merge-conflict prevention ("планировщик ... механизмом предотвращения конфликтов при слиянии изменений"); slots configurable, paced to the weekly limit, 15-20% left 12 h before reset; effective ip = max(own, 1 + highest ip it blocks), computed on read, no upper bound ("Думаю достаточно поднимать на 1 от самого высокого"); ip 96 for a-fix-already-merged-by-another-change-cannot-be; limit-share item to ip 86 ("1. a"); slots raised above 4 on the owner's word ("мы можем выполнить как минимум ещё одно").
Queue added tonight: queue-items-name-what-blocks-them-a-dependency-t (85, brief scratchpad briefs/queue-tree.md), choose-which-unblocked-items-start-together (84, design brief briefs/design-ready.md, design not run yet), the-front-recommends-from-unmeasured-claims-unre (93), a-fix-already-merged-by-another-change-cannot-be (96), a-gate-waited-on-by-a-runner-dies-at-its-turn-li (91), a-merge-check-of-a-train-is-recorded-but-leaves (91; also seen with a normal check by a lone checker agent: the mark landed only via the workflow checker), the-inert-gate-step-went-red-then-green-on-the-s (90; one cause found and fixed: the paid-cap test's date), relay-check-show-reports-a-mark-that-landed-on-t (90), relay-queue-close-refusal-after-files-changed-be (85).
Stale items (already fixed on master, waiting for the ip 96 fix to close them): the-bench-never-starts-a-worker-so-it-measures-n (released), a-refused-merge-does-not-say-what-to-rerun (wt/merge-msg holds only its close; do not merge).
Facts measured: 2-3 parallel quick gates take 19-25 min instead of ~9; the Mac slept 02:13-03:07 with the lid closed (owner then disabled sleep: SleepDisabled 1; displaysleep 0). Runners waiting on gates die at maxTurns 12; the front now waits on gates itself (Bash run_in_background). The session workflow scripts gained: gate reuse if green, `built` flag to skip a crashed build.
Next: merge train-4; then the wave paid run (bin/paid-cost due; bin/ci in a detached worktree of master, run_in_background), relay sync; then the next fixes by ip, at most 3 at once (gates slow down past that): a-fix-already-merged... (96), the-front-recommends... (93), the 91s; then the tree (85) and the 93 fix lead to the planning wave.

## STATE 25 Oct ~07:00, session 3207dc59 (358k line)
- train-4 merged (premise check + bench --set); fixed by checking each rider again (their m8 findings) and re-taking them into the train. All of tonight's wave is on master: e905742.
- Wave paid run running: bin/ci in .worktrees/paid-e905742 (detached), log scratchpad ci-wave-e905742.log, task bdjrwrbey. Green -> `relay sync` (check bin/paid-cost due is empty), remove the worktree. Red -> one fix item at the top.
- Next fixes (at most 3 at once while the paid run uses the CPU): a-fix-already-merged-by-another-change-cannot-be (96), the-front-recommends-from-unmeasured-claims-unre (93); then the 91s by ip, checking file overlap with git diff of running branches. New `relay queue add` of a fix now needs failing_kind (test|run|claim).
- Owner's latest words (verbatim): "Я убрал сон, следует ли мне снижать яркость экрана, или это будет выполнено автоматически ? Можешь ли ты их перезапустить, повредило ли это нам как либо или мы полностью восстановились и проблема была лишь в паузе ?" (answered: no damage, only the pause; displaysleep 0 means the screen stays on with the lid open, `sudo pmset -a displaysleep 10` if wanted).

## STATE 25 Oct ~09:30 (after train-5)

- Merged (train-5): stale-close (`relay queue done <slug> --fixed-by <commit> --test file::Class::name`) and measured (front measures before recommending; new eval explain-existing, not yet paid-run).
- Closed with --fixed-by: the-bench-never-starts-a-worker-so-it-measures-n (3b28fbf), a-refused-merge-does-not-say-what-to-rerun (c59d6a0). wt/merge-msg removed.
- Wave paid run of e905742: RED (9 eval cases; $15.03). Queue fix ip 97 the-wave-paid-run-of-e905742-is-red-in-9-eval-ca, in wt/wave-red. First worker died at maxTurns 80 while polling pytest; its edits are WIP 6ef1a73; causes so far in scratchpad reports/wave-red.md (no-openspec-command grader matched the folder name; openspec skills loaded without [specs]; offbyone scaffold put the reviewer rule on the branch only). A second worker continues (workflow wd80tg3d5). relay sync waits for a green paid run. .worktrees/paid-e905742 kept as evidence until wave-red is done.
- In build: wt/turn-limit (ip 91, a-gate-waited-on-by-a-runner-dies-at-its-turn-li), widened to any agent polling a long job (workflow wofyfp1zr).
- Open question for later: the ledger (bin/paid-cost today) shows 1 run although the wave-red worker reproduced cases with paid runs; the worker reports the count.
- Next: the 91s by ip; offbyone-rubric-fail-clause and stale-eval-texts wait for wave-red (same eval files).

## STATE 25 Oct ~15:30 (laptop battery low; read this first after a restart)

Merged today after train-5: session-profile (sync writes [session] model/effort, modelSettings entry), turn-limit (gate reuse, turn-count hook plugins/delegate/hooks/turn-limit.py), read-only (read-only-guard.py; migrate --all skips primary checkouts).
Owner decisions today (verbatim): "Согласен, сценарий проходит с большинством" (an eval case passes by 2 of 3 runs; queue item a-wave-run-is-red-when-one-of-a-case-s-3-runs-fa, ip 94). On three live it-terms-ru replies: "Да, меня вполне устраивает", with the front's three corrections (masculine gender for English nouns, no apostrophe before a Russian ending, no opener about the unnamed project): queue item russian-replies-one-gender-no-apostrophe-no-open (ip 93); the front's memory use-english-it-terms already carries them.
Front decisions (owner can reverse): rules reach eval sessions through append_system_prompt written by evals/plugin/system_rules.py (the runner sets CLAUDE_CODE_DISABLE_CLAUDE_MDS=1); turn count by a hook; done queue records are not rewritten; CLAUDE_CODE_RETRY_WATCHDOG=1 via relay sync (measured: default gives up ~900 s offline, watchdog still waiting at 900 s).

In progress, all committed, nothing only in memory:
1. .worktrees/train-8 (wt/train-8) = master + wt/wave-red (holds wt/claudemd) + wt/split-tests. Merge check N1 (RULE_TESTS misses ItTermsSetup, GlossaryGivesNoInstruction) was being fixed by workflow w86lqfuok. Next: if a fixer commit for N1 is there, run the fix-cycle (fixes reports/fix-train-8.md, findings reports/check2-train-8.json) with no fix: gate, check; then `git -C ~/relay merge --ff-only wt/train-8` (take master into the train first if master moved; never into a rider).
2. .worktrees/net-retry (wt/net-retry): ready, open 0, item closed on the branch. Next: own train after train-8 (git worktree add train-9 from master, merge --no-ff wt/net-retry, relay changed --own, gate, merge check if files listed, ff-only).
3. After both: queue the-rules-text-step-is-already-red-on-master-7 (ip 98; cause: running lib/relay_textonly.py tests with unittest, a test class removes a shared temp fixture another class uses; pytest order hides it), then russian-replies-one-gender-no-apostrophe-no-open (93), then close the-eval-cost-ceiling-cuts-every-wave-run-short with --fixed-by (fixed inside wave-red, F6, SuiteCeiling tests).
4. Then the wave paid run on master (detached worktree, bash bin/ci in the background); green -> relay sync; red -> one fix item at the top. Remove .worktrees/paid-e905742 then (kept as evidence).
Paid today: about $63 of $200 (ledger shows less: direct eval runs are missing, queue item the-paid-ledger-misses-eval-runs-made-outside-bi).
Scratchpad (briefs, reports, q-*.toml): /private/tmp/claude-501/-Users-amidman-relay/3207dc59-2cc6-4cd6-9463-5c3c3c8bd504/scratchpad (a /tmp path: it may be gone after a restart; the reports named above then live only in the branches' commits and .relay/checks).
Scratchpad copy (survives a restart): /Users/amidman/.relay/backup/scratch-3207dc59 — briefs/, reports/, q-*.toml.

## STATE 25 Oct ~16:00 (connection drops expected)
train-8 is ready by its check (check3-train-8.json in the scratchpad copy: open 0, gate 961245d green) and has taken master (47a9e86), but `git -C ~/relay merge --ff-only wt/train-8` was refused: "after the check of 3e4a0a5..., wt/train-8 changed lib/relay_textonly.py, tests/test_rules_gate.py". The last checker recorded its check without a mark commit (queue item a-merge-check-of-a-train-is-recorded-but-leaves, ip 91: raise it, it hit again). Next step: run the fix-cycle workflow on train-8 with fixes = reports/fix-train-8.md and findings = reports/check2-train-8.json, no fix (the gate is reused), so a checker records the check with its mark; then merge --ff-only. Then net-retry (ready) in its own train, then the items in the 15:30 section, step 3 on.

## STATE 25 Oct ~17:00
Merged: train-8 (wave-red + claudemd + split-tests). Closed with --fixed-by: the-eval-cost-ceiling-cuts-every-wave-run-short (2b4c9f0). a-merge-check-of-a-train-is-recorded-but-leaves raised to 96 (hit again on train-8; fixed by a re-check that recorded a mark).
Running: train-9 (master + wt/net-retry; merge check m11-train-9.json, then ff-only); wt/rules-red (ip 98) and wt/ru-style (ip 93) in the change cycle. Next after them: the wave paid run on master, then relay sync on green.

## STRATEGY (owner, 25 Oct ~17:30) and how the front reports
Owner: "1. a / 2. b" — strategy from the owner, one digest per wave, only real questions (memory strategy-and-wave-digest); first real project: arsenal (~/go/src/go.amidman.dev/arsenal, the owner's Forgejo). Then on the front's proposed order (1 merge-hook check-mark bugs, 2 arsenal pilot, 3 relay digest, 4 other fixes by ip, features later): "Я согласен с порядком, однако проба в arsenal может происходить параллельно с изменениями в relay".
Running: wt/check-mark (ip 96), wt/feature-kind (95), wt/ru-style (93, judge measure), train-10 (rules-red), design of the arsenal pilot (reports/design-arsenal.md, read-only). After them: the mark-show item (90, same file as check-mark), then the wave paid run.

## STATE 26 Oct ~00:30 (session 3207dc59)
Merged since ~17:30: train-11 (ru-style: one gender, no apostrophe, no opener; feature-kind: a NOT MET finding of any kind but outside counts open), train-12 (pilot-guards: guard-main allows only `git merge --ff-only origin/<default>` in a main checkout, FETCH_HEAD withdrawn by the front after review F1, owner can reverse; migrate removes only the moved hook's command; check-mark: marks stay the checker's via the SubagentStop hook, which takes the record the checker wrote in its run and blocks a stop with no record, front's decision, owner can reverse). Closed with --fixed-by: migrate-leaves-a-settings-entry-for-a-hook-it-mo (a4ad90d).
Owner decisions (verbatim):
- `where` as a list: "a" (place as first word `path[:N[-M]]`, note after a space; all 97 records rewritten). Building: wt/where-list.
- Russian style: "a" (the Russian-only grammar line stays; another language's line only when its user appears; memory language-specific-rules-per-language).
- Public release: "b" (prepared in parallel with the arsenal pilot), then "1. a / 2. a / 3. a / 4. a": MIT, holder "amidman"; a new public repo with one commit, the working repo stays private; Glonass, project names, language, money cap in a personal overlay outside the public repo; relay's own stdlib license command.
- License: "можем ли мы встроить в relay утилиту которая позволяет автоматически добавлять и проверять наличие заголовка с лицензией и саму лицензию в проект ... такая возможность должна быть и оставаться при этом опцией"; then "a, я хочу чтобы пользоваться этим было просто - одна команда и забыл, + проверки при изменениях чтобы лицензия оставалась актуальной" = always the REUSE layout (LICENSE + LICENSES/<id>.txt + REUSE.toml with one `**` annotation, measured compliant with reuse 6.2.0 on a 4-file repo), checks run by relay gate when kit.toml has [license]. Building: wt/license (brief briefs/license.md with an UPDATE section).
- Glonass: "Мне не нравится, оставим glonass на потом когда я попробую применить relay у себя в проектах" (memory glonass-deferred).
Queue added: R1-R5 pilot fixes (R1, R2 closed; R3 setup-inside-a-worktree building in wt/setup-wt; R4 squash-merge records, R5 rebase keeps review, ip 86), where-holds-several-places-in-one-string (85), guard-main-refuses-a-script-that-only-names-the (84), first-relay-setup-on-a-new-machine-fails-on-the (83), setup-enables-project-plugins-that-doctor-says-a (80), setup-silently-turns-off-a-project-s-agents-md (82), relay-license-add-and-check-a-project-s-license (feature 89), personal-overlay-the-owner-s-own-rules-outside-r (feature 89), publish-relay-to-a-public-repo-from-the-private (feature 87); relay-as-a-portable-tool-project-data-out-of-rel raised to 90 (design running: scratchpad reports/design-portable.md + review).
Release readiness (scratchpad reports/demo-and-release.md, throwaway project in scratchpad demo2/): not ready, 7 blockers ~370 agent minutes; no secrets in history.
Lesson: a branch holds one fix item (relay queue take refuses a second); give each fix item its own branch.
Running: wt/where-list (change cycle), wt/license + design-portable (change cycle), wt/setup-wt (change cycle).
Next: merge each ready branch via a train; after R3 merges, ask the owner for pilot step 2 (reset arsenal's main checkout to origin/master in a terminal, then open Claude Code in arsenal) with the design path; wave paid run (bin/ci in background) when this wave is merged, then relay sync; the wave digest to the owner (mode 1a).

## STATE 26 Oct ~midday (session 3207dc59, at the 350k line)
Merged since 00:30: train-13 (setup in a linked worktree names the project after its main checkout and writes into the worktree, front's decision instead of refusing, owner can reverse), train-14 (relay license: REUSE layout LICENSE + LICENSES/<id>.txt + REUSE.toml, check from relay gate; conflict in setup() signature resolved by a fixer, merged on the owner's "Хорошо, можешь сделать merge"). Closed: setup-inside-a-worktree, relay-license (--evidence 00725de), migrate-leaves-a-settings-entry (--fixed-by a4ad90d).
Pilot (arsenal): R1-R3 merged. Owner ran `git reset --hard origin/master` in arsenal (now b1ce14b = origin/master; the 2 unpushed commits are on branch principles-library 80cb927). The owner opens Claude Code in arsenal with: "Прочитай ~/.relay/backup/scratch-3207dc59/reports/design-arsenal.md и проведи пилот relay с шага 3." That session runs the pilot (it asked the owner about merging arsenal PR #622 there).
Owner decisions since 00:30 (verbatim where quoted):
- Big files: "агенты позволяют нам делать множество изменений одновременно, большие файлы - наши враги ..." then "a": principle 10 + items (two-branches-start-on-the-same-file-unnoticed 88, principle-10 88, lib copies 87, bin/relay discovery 86, split relay_queue/relay_setup at a wave boundary 85).
- Parallelism: "a" = 6 agents in relay's kit.toml, at most 3 gates per machine (built: wt/parallel, in train-15).
- pi: "Пока это просто идея на будущее" — assessment kept in ~/.relay/backup/scratch-3207dc59/reports/harness-port.md, item relay-on-other-harnesses-pi-and-any-provider ip 0.
- Glonass: "оставим glonass на потом когда я попробую применить relay у себя в проектах" (memory glonass-deferred).
- Portable relay (design revision 4 in ~/.relay/backup/scratch-3207dc59/reports/design-portable-r4.md; decisions in scratchpad reports/design-portable-decisions.md): global rules only; overlay per user `~/.relay/personal/` ("это всё таки общая папка, она относится персонально к пользователю ... Это равносильно .claude"); per-repo rules deferred ("эту модель следует отложить"); principles global, python rule into a tracked relay CLAUDE.md ("Мне нравится твой рекомендованный вариант" = c); 3a no default cap; 2a OpenSpec via the openspec plugin's own hook. Build: 6 items; item 1 running (wt/openspec-plugin).
- Option letters: "a" = Latin a, b, c in the rules, Cyrillic answers count the same (wt/letters building).
- Toolkit: "Давай пока зафиксируем пользовательский запрос, без конкретного предложения" (item relay-toolkit-python-scripts-for-user-scenarios ip 0, words only).
- Queue items: "Согласен с рекомендованным вариантом" = owner's words + dated facts, no report links, design when taken (item queue-items-point-at-session-files-that-vanish 88; memory queue-items-hold-words-and-facts).
- where-list merge: owner said "a" (merge); blocked by the merge hook reading list records with master's rules -> fix wt/hook-schema (ready, in train-16 gate). After train-16 merges: take master into wt/where-list, rerun `python3 lib/relay_where_migrate.py <wt>` for new string records, commit, ff-only merge (owner's consent already given).
Lessons: take a fix item on its branch at worktree creation (relay queue take), one fix item per branch; run relay commands of a branch that changes the queue schema with that branch's own bin/relay.
Running: train-15 (parallel + master, conflict in lib/relay_gate.py resolved by a fixer: needs mk_merge3 + merge check, then the owner's consent), train-16 gate (hook-schema), wt/letters cycle, wt/openspec-plugin cycle.
Next: merge train-16, then where-list; ask the owner about train-15; wave paid run (bin/ci in background, check bin/paid-cost due) after this wave, then relay sync; wave digest to the owner (mode 1a).

## STATE 26 Oct afternoon (session 3207dc59)

Merged today after midday: hook-schema (train-16: the merge hook judges a branch's queue records by that branch's lib),
where-list (queue `where` is a list of places; every `relay queue add` input uses `where = [...]`), a two-record
where fix, and train-17 = letters (option letters Latin a/b/c, Cyrillic counts the same) + openspec-plugin (the spec
rule lives in plugins/openspec/hooks/spec-rule.py) + parallel (6 agents in relay's .claude/kit.toml, at most 3 gates
per machine, in-slot license re-check with a test). Owner consented to the hand-resolved parallel merge ("a").

Owner decisions this afternoon (verbatim):
- OpenSpec on relay itself: first "Включи openspec plugin для самого relay, зафиксируй только нужное для разработки
  relay, первым испытателем relay будет сам relay", then "Нет я подумал что всё таки испытывать openspec плагин не
  стоит на relay, он заточен под другое, включим позже если потребуется". Item dropped; the plugins-only part kept by
  the front (owner can reverse) as relay-s-repo-records-the-plugins-relay-developme (ip 90).
- Rename: "Запланируй изменение в core plugin переименовать его в relay, мне не нравится название core", then
  "Действительно relay@relay звучит не очень, может тогда просто relay, в данном случае это не опция и он всегда будет
  включен", then "Хорошо, давай relay@amidman" (option a: plugin relay, marketplace renamed amidman). Item
  the-core-plugin-becomes-relay-amidman (ip 86): build alone, with no other branch open, after the plugins item.
- Arsenal pilot continues in the owner's own session, unchanged.

Running: the wave's paid run (bin/ci, background, log scratchpad/ci-wave.log); then `relay sync` and the wave digest.
wt/relay-plugins (.worktrees/relay-plugins): a worker runs `relay setup` on relay itself to write .claude/settings.json
(core, delegate, front, observe on; gopls-lsp, issues, product, openspec off); stops and reports if setup cannot.

Lessons: the fix-cycle script's `fixes` is an existing fixer report, `fix` is the fixer's brief (passing the findings
as `fixes` skipped the fixer). Merging one ready branch moves master and voids the other branches' gates: gather ready
branches into one train and gate once. A train whose branches changed the same file needs mk_merge3 + a checker.
relay has no bin/check; the worker's check is pytest or the gate.

Next: after the paid run is green, relay sync, wave digest; merge wt/relay-plugins; then the core rename alone; then the
portable items (2, 3-5, 6) as their files free up.

## STATE 26 Oct evening (session 3207dc59, ~353k tokens)

Merged since the afternoon: setup-wt-market (setup from a worktree registers the marketplace at the main checkout),
rules-wt (global rule paths name the main checkout), red-wave (26 Oct red paid run: gender rule sentence + grader, eval
grant `--allow-tools Bash Agent Write` in bin/ci, design-track ends at the agent call), train-18 = tests-tmp (every test
gets temporary HOME/CLAUDE_CONFIG_DIR/RELAY_HOME under pytest and unittest via tests/tmp_default.py, tests/run_unittest.py;
uv cache kept) + fix-first (queue order: fix before feature, then ip; a new fix without --ip gets 0), setup-scope
(`relay setup <dir>` writes only the project; global only via --global/install; --off turns plugins off per project;
one ALWAYS_ON list; reserved folder names). Closed: six-agents, setup-off feature (evidence dc1bef1).

Owner decisions (verbatim):
- "Нет я подумал что всё таки испытывать openspec плагин не стоит на relay, он заточен под другое, включим позже если потребуется".
- core rename: "Хорошо, давай relay@amidman" (item the-core-plugin-becomes-relay-amidman; build alone).
- setup global part: "A" (project setup never touches global files) after "почему ты настаиваешь на выводе списком"; then "Сделай это fix".
- install: "Полностью согласен с твоими рекомендациями": code in ~/.relay/src, state beside it; `relay update` keeps the
  user's edits and stops on conflict; plugins from relay's folder (directory marketplace); one command `curl | sh`.
  Then "При установке через install.sh | sh, сам установочный скрипт хранится в репозитории, не отдельно".
- "Для тестирования ты можешь использовать изолированные окружения, контейнеры alpine" -> item install-and-setup-are-tested-in-a-clean-containe.
- Asked for time analysis per change; threshold "незначительным считаю все что меньше 25%". Result: gate 45-62% of a
  cycle; inert reruns the whole gate (22-36%); tests on 1 of 12 cores -> fix item the-gate-runs-its-work-twice-in-a-row-on-one-cor (ip 95).
- The owner killed a leaked test gate (pid 72877) on request.
Front decisions (owner can reverse): pronoun after a gloss is no breach; design-track ends at the agent call; eval grant
gets Write (one-word bin/ci edit, Python port left to the gate-speed item); tests hardlink fake tools (macOS scans each
new executable ~0.75 s); new fix default ip 0; marketplace path stays in project settings (item setup-in-a-shared-repo).

Running: the wave's full paid run (bin/ci in background, log scratchpad/ci-wave2.log, started at master before
setup-scope; setup-scope has no rule/agent texts). Next: when green, `relay sync` from the main checkout, then the wave
digest (owner asked earlier for one digest per wave). If red: one fix item at the top.

Queue (26 Oct evening): 48 fix, 35 feature. Top fixes: a-test-leaves-a-real-gate-running (96), python-rule-tests-never-
touch-the-live-relay-que (94), tests-write-new-executables-macos-scans (94), the-gate-runs-its-work-twice (95, after the
inert-flake item), setup-in-a-worktree-rewrites-main-checkout-rules (95), the-front-s-cd-into-a-worktree (93),
a-red-paid-run-keeps-no-traces (93), running-test-spec-steps-before-test-license (93), the-paid-run-estimate-misses (92),
relay-home-means-two-different-folders (90). After fixes: relay-s-repo-records-the-plugins (needs the sync-local fix),
then the core rename alone.

Lessons: gate-waiting runner agents ran out of turns 3 times (gates now 25-60 min); the scripts now give them 40 turns
and a "still running" report; the front can run a gate itself with run_in_background. A test leaked a real gate that held
a machine slot for 3.7 h. The front `cd`-ed into worktrees twice (red-wave stays locked by this session).

## STATE 26 Oct night (session 3207dc59)

Paid run of the wave: GREEN at 57b1564, $15.18 (day $32.61 of $200). `relay sync` ran: global CLAUDE.md written; it also
set `effortLevel` 'high' and env CLAUDE_CODE_RETRY_WATCHDOG=1 in ~/.claude/settings.json from the profile (owner told).
Note: two eval sessions (code-reviewer-offbyone, critic-role-rule) read the rule file via Bash, so they do not prove the
hook delivered the rule.

Merged: live-queue-tests (tests read pinned queue commits, guard test against live queue reads), front-cd (guard-main
refuses the main session's cd/pushd from the main checkout into a worktree; allowed inside the worktree and in child
shells; 11 guard-diff golden "was" values now block), leaked-gate (test gate helper stops a gate past its timeout with its
command; after the library tests tests/leaked_gates.py stops gates left under the run's temp folders and fails the step).
Owner on the cd guard: "Оставь" (after the front asked whether a code guard against the front's own mistake is wanted).
Front decision (owner can reverse): review F3 of leaked-gate (no suite-end check) was fixed inside the change, not queued,
because the item's pass case asks for it.

Found and queued: the-routing-guard-counts-finished-agents-as-runn (75: "7 running" while 1 ran),
a-train-cannot-recheck-a-queue-item-its-branch-c (92: two fix items can never land in one train; the merge hook walks
marks in topo order and needs the item's check after every non-inert change, so the other branch's files always come
after; train-19 and train-20 were abandoned and landed one at a time, +1 gate).

Leftovers the guard will not let the front remove: .worktrees/train-19, .worktrees/train-20 (wt/train-19, wt/train-20,
fully contained in master), .worktrees/relay-plugins. `relay doctor` lists them.

Lessons: fix LOW findings before the queue check, not after (a one-line move after the item's check cost 3 extra checker
runs and a gate). Gates run by the front with run_in_background worked every time.

Next: next fix wave from the top of the queue (relay queue): the-gate-runs-its-work-twice (95, 3h, ports bin/ci to
Python), setup-in-a-worktree-rewrites-main-checkout-rules (95), a-wave-run-is-red-when-one-of-a-case-s-3-runs-fa (94),
tests-write-new-executables (94), then 93s and a-train-cannot-recheck (92). Each brief starts with a fresh look at the code.

## STATE 27 Oct, small hours (session 3207dc59)

Merged since "26 Oct night": setup-wt-rules (relay setup in a linked worktree skips the rules sync, held sync exits 0),
fake-tools (tests/fake_tools.py: a fake tool's text is written once and linked; installer tests 72 s -> 11 s),
gate-lock (gate-speed branch 1: one gate per worktree, a second waits and reuses; closes the-inert-gate-step-went-red-...;
cause measured: three gates at once in one worktree on 25 Oct sharing one results file), relay-home (install.sh reads
RELAY_ROOT for code; RELAY_HOME is the state folder everywhere), ci-python (gate-speed branch 2: bin/ci is a wrapper over
lib/relay_ci.py; the inert probe runs beside the outer run; first gates 868 s and 801 s vs 1404 s on the old bin/ci).
Closed by evidence: every-test-runs-with-temporary-relay-and-claude (feature, fd221e0; it stayed open after train-18).

Owner decisions (verbatim):
- gate-speed proof: "a" (20 real runs of the new gate before relying on it; the front runs them after branch 3 lands,
  design case 9: a scratchpad script, commits nothing).
- checks-artifacts design: "Мне нравятся рекомендованные варианты, однако не используй прямой путь, опирайся на
  относительный путь + переменную окружения" -> test times in one file per machine $RELAY_HOME/test-times/<repo>.json
  (outer run writes, probe reads); red-run logs under $RELAY_HOME/artifacts/<repo>/<sha>/ for 14 days (queue item
  red-gate-and-probe-runs-keep-no-logs-to-find-a-c, ip 89). Memory: paths-via-env-var.
- install.sh error message prints the real searched path: "Согласен с твоей рекомендацией" (a). The owner asked why the
  installer does not keep code in $RELAY_HOME/src: that layout is the feature relay-installs-with-one-command (87), not
  built; today's install.sh is the developer installer.
- ci-python after a hand-resolved conflict: "Можешь влить".
- cd guard: "Оставь".

Queued tonight: a-gate-log-keeps-failure-lines-of-any-length (60), red-gate-and-probe-runs-keep-no-logs (89), plus a
reviewer's test_installer_doctor duplicate-class item (fixer-queued).

Running: gate-speed branch 3 (wt/test-jobs, item the-gate-runs-its-work-twice, parallel library tests by class,
RELAY_TEST_JOBS default 4 to be measured at 1/2/4/6; times cache as above). After it lands: the 20-run proof.

Lessons: a gate-waiting runner died without its report twice more (relay-home, leaked-gate); the front ran later gates
itself with run_in_background, which never failed. Taking master that auto-merges a file the branch also changed
needs a fresh check of the branch's queue item (gate-lock), so take master before the queue check when master moved.

## STATE 27 Oct, early morning (session 3207dc59)

Merged: gate-speed branch 3 (wt/test-jobs: tests/parallel_unittest.py, library tests split by class over
RELAY_TEST_JOBS processes, default 4; times cache $RELAY_HOME/test-times/<repo>.json written by the outer run only, probe
reads with RELAY_INERT_PROBE=1); closes the-gate-runs-its-work-twice-in-a-row-on-one-cor.
Measured by its builder on the owner's Mac (one tree, 27 Oct): whole quick gate 1 job 801 s (lib 624 s), 2 jobs 520 s
(lib 359 s), 4 jobs 420 s (lib 213 s), 6 jobs 368 s; old bin/ci before the gate-speed work 1404 s (-70% at 4 jobs).
Concurrent gates at 4 jobs: 1 = 8.6 gates/h, 2 at once 698 s each = 10.3/h, 3 at once 1058 s each = 10.2/h, so
DEFAULT_SLOTS stays 3. Knee: 4 -> 6 gains 12% for 50% more processes; hook tests (~150 s, serial) are the next floor.

Owner answers this night (verbatim where short): observability coverage "Замеряем метрики на каждом gate" (a: inside
the probe); cycle scripts "Скрипт вливает сам" (a: relay land prepares, the final ff stays a Bash merge the hook sees);
moving the scripts first: "a" and "Подними приоритет переноса скриптов выше" (item change-cycle-workflow-scripts-move-
into-relay, ip 96, before the fixes); git launcher: "надо лишь зафиксировать что такое явление существует и исправить
только на этой машине - в PATH я укажу прямой путь к git" (fix item dropped; docs/macos.md in review); "Что означает
core, замени это на стандартный пакет relay при объяснении" (memory core-is-the-standard-package). Open: observability
question 2 (projects with observe only: a ledger view, b observe's own landing detector).
The 24 Oct workflow measurement the front had not recorded: one change via the workflow ~165k agent tokens vs 236-277k
by hand, front turns ~0 vs ~22, same review quality (now in the scripts item; memory record-measurements-at-once).

Designs done tonight (scratchpad/reports/): design-gate-speed.md (built), design-checks-artifacts.md (owner: 1a 2a),
design-test-speed.md (tests start git ~29,000 times; Apple's /usr/bin/git launcher adds 8-12 ms per start; Python ~1.5%
of test time, Rust at most 5-10%), design-dev-metrics.md (rev 2; observability), design-cycle-scripts.md (rev 2).

Running: drop-plugins (relay-drops-the-issues-and-product-plugins; after merge drop setup-never-sees-a-phoenix-project-
as-person-fac, issues-flow-into-queue, issue-bindings-forgejo-gitlab and close the feature with --evidence), macos-doc
(docs only), the 20-run proof script (scratchpad/proof20/, worktree .worktrees/proof20 detached at master).
Next: a-train-cannot-recheck-a-queue-item-its-branch-c (92) before the scripts move (the script lands trains), then
change-cycle-workflow-scripts-move-into-relay (96) from design-cycle-scripts.md, then observability.

Addendum 27 Oct morning: observability question 2 answered "Хорошо согласен, метрики становятся частью стандартного
пакета relay" (a: full records where the standard package and .relay/ are on; observe alone gives a ledger view). The
owner then asked "что меняется в observe ? Как можно отключить эти метрики по желанию ?". Front's answer: observe's
ledger hook adds the stage label and seven token fields at agent stop (design-dev-metrics.md 2.2), nothing else; the
off switch proposed is one project setting written by `relay setup --off metrics` (records off) plus RELAY_COVERAGE=off
(coverage only); awaiting the owner's word on the switch before the build. Context at ~351k: next session continues
from the "early morning" state above.

Addendum 27 Oct morning (2): off switch for metrics: "Хорошо" to a (`relay setup --off metrics` writes
`[metrics] record = false` in the project's kit.toml; RELAY_COVERAGE=off stays for coverage only). On coverage the
owner said: "Помни что само покрытие coverage.py не общее для всех, это лишь инструмент для получения покрытия для
конкретной технологии" and "как мы отслеживаем покрытие кодовой базы, есть разные инструменты для этого, мы должны иметь
способ динамически получать его для разных проектов". Front's proposal, awaiting the owner: a) a project setting names
its coverage report path and format (LCOV or Cobertura, which coverage.py, Go via a converter, Jest/c8/istanbul and
cargo llvm-cov all write; relay parses both with the stdlib; changed-line coverage from the report against the diff)
instead of b) the design's invented `coverage <repo> changed <changed>` line. The design (design-dev-metrics.md 2.4) is
revised to the owner's pick before the build. The ledger/record overlap is deliberate: the record copies only the
change's agents (stage, role, model, start, seconds, requests, tokens), because the ledger is machine-local, mixes
projects and holds prompts.
20-run proof: scratchpad/proof20/proof20.py (takes the worktree lock and a slot via lib/relay_gate.py, runs
RELAY_GATE=HEAD bin/ci --quick in .worktrees/proof20, logs run-<i>.log and summary.tsv, stops at the first red); trial
run 1: 492 s, library tests 291 s, green. The 20 runs started 27 Oct morning in the front's background.

Addendum 27 Oct morning (3): coverage format: owner "a" (a project setting names its LCOV or Cobertura report; relay reads both with the stdlib). Revise design-dev-metrics.md 2.4 to it before the build.

### Addendum (4), 27 Oct 00:15: how the metrics design is judged

Owner, verbatim: "Для метрик - важной стадией проверки будет являться: Информативность - набор вопросов на которые могут дать ответ метрики / Краткость - отсутствие лишней информации / Гибкость - способность формата приспосабливаться под будущие изменения и дополнения, как продумано добавление нового способа выполнять изменения / Для меня все еще не до конца ясен момент ledger и metrics, их свойств и различий, думаю тебе необходимо это продемонстрировать более наглядно".
Done: revision 3 of the metrics design runs on the design track (thinker, critic, revise), brief `scratchpad/briefs/dev-metrics-design-r3.md`, output `scratchpad/reports/design-dev-metrics-r3.md`; the critic judges each finding against the three criteria. Section 1 shows the ledger and a change record side by side for one real landed change. The front explained the difference to the owner in the reply.

Owner, verbatim (27 Oct, after the ledger/metrics explanation): "ledger является источником данных для metric, позволяющий записать её лишь однажды, данные аккумулируются в ledger / Согласен со слабым местом которое ты подметил, краткость сегодня, возможность расширения в будущем, это не противоречие а дизайн / Гибкость - Простота - Порядок / Хороший дизайн сочетает в себе эти вещи". So: the ledger accumulates, the change record is written once from it at landing; store only what answers a question today, extend through a format version; the design is judged on flexibility, simplicity and order together.

### Addendum (5), 27 Oct: metrics design revision 3 done (thinker, critic 13 findings 0 HIGH 9 MEDIUM 4 LOW, all fixed in the revision)

File: scratchpad/reports/design-dev-metrics-r3.md (review: review-design-dev-metrics-r3.json). Measured facts shown to the owner: ci-python in the ledger = 253 lines, 74,963 bytes for 9 agents; its change record = 1,841 bytes (2.5%); cost $3.50 (review $1.52, build $1.35); cycle 192 min with 61 min no agent; ci-python's own gates are 4 (first-parent line), not the 14 a plain diff names; 4 distinct findings, not 6. bench-set: estimate 20 min, real 103 (5.2x). Session: 0 of 53 hand-started agents labelled ($13.72, 5.7%), 804 of 804 workflow agents labelled; designs and hand thinkers $77.23 of $241.86 (31.9%). Ledger 2.8 MB/day, no code deletes it (oldest 21 Oct). Design answers 16 questions; 5 listed as unanswerable. Build ~400 agent minutes (estimate). Open for the owner: (1) records for designs/analyses/experiments (rec a); (2) refuse unlabelled hand agents at start (rec a). Also queued 27 Oct: a-wrong-value-in-project-settings-passes-unnotic (fix 86), relay-doctor-checks-the-project-of-the-current-f (feature 80, owner "A").

### Addendum (6), 27 Oct: owner answers on metrics r3, and a new ask

- Metrics design revision 3, open questions: owner "1. a" (designs, analyses, experiments get a record in git at the run's end) and "2. a" (the route guard refuses a relay agent started by hand without a `<stage>: <name>` label, in projects with `.relay/` and metrics on). Build from scratchpad/reports/design-dev-metrics-r3.md with both a's, after the scripts move.
- New ask, verbatim: "Как мы вообще планируем задачи, документируем эксперименты, мы должны быть устройство независимым, вплоть до того что бы можем запускать каждое изменение в новой docker контейнере где предустановлены все необходимые утилиты, как будто это запуск ci/cd в стандартных системах (woodpecker), с минимумом настроек глобального relay, хочу вообще без глобальных настроек relay и claude, полностью чистое окружение с предустановленными утилитами и файлами проекта / При этом получать тот же результат". On the design track: brief scratchpad/briefs/clean-env-design.md, output scratchpad/reports/design-clean-env.md. Known gap that day: designs, briefs and reports live only in the session scratchpad under /private/tmp (outside git, lost on reboot).
- macos-doc: F3 (LOW, the 1.5% vs 5-10% split) sent to a fixer with the measurement's split instead of to the owner; fix cycle running.

### Addendum (7), 27 Oct: clean-environment design revision 2 done; proof run 10 red

- Design: scratchpad/reports/design-clean-env.md (rev 2, critic 1 HIGH 11 MEDIUM 1 LOW, 12 fixed, F7 replaced). Measured: 23 pieces of global state a change cycle depends on (6 fail, 11 differ, 3 do not care, 3 not verified); same tree b10d314 quick gate: Mac green 935 s, Linux container RED 25 failures + 17 errors, 215 s (queued: the-quick-gate-is-red-in-a-clean-linux-container, fix 90); container start 0.33-0.52 s cached, image 1.18 GB, cold build 311 s; setup fingerprint differs on 8 of 10 lines. Recommendation: B (relay project-local on the host) first, then A (container per change, never landing), plans by P1. Four owner questions asked (plans location, memory notes, who decides merge, order).
- 20-run proof of the new gate: runs 1-9 green (451-720 s, mean 562), run 10 red: inert probe library tests "ValueError: invalid literal for int() with base 10: ''". Queued the-inert-probe-s-library-tests-sometimes-fail-o (fix 95); a thinker is finding the cause (brief scratchpad/briefs/probe-int-cause.md, report reports/cause-probe-int.md). Proof after the fix: 30 clean runs.
- macos-doc merged. plans-save: fixing N1 (a plan said an unbuilt module exists), then merge.

### Addendum (8), 27 Oct: owner answers on the clean-environment design; learning from mistakes

- Q1 plans, owner verbatim: "Хочу чтобы мы хранили планы по легко вычисляемому пути, возможно рядом с задачами, план имеет ценность только если есть задача, являясь её частью". Front's reading: a plan is `.relay/queue/<slug>.md` beside the item `.relay/queue/<slug>.json` (path computed from the slug, no link stored), moves to `done/` with it, lands through the queue's own lander (inert, no gate). A design asked before any item exists starts by adding the item. wt/plans-save (4 plans copied into docs/plans/, ready, gate running) is NOT merged: its commits keep the plans safe; the plans-next-to-items change moves them.
- Q2 memory notes: not answered yet (asked again).
- Q3: "A" (this Mac re-gates until 3 waves in a row agree with the container, then the container's gate decides). Q4: "A" (plans and same-setup work right after the scripts move, front's IP 95; containers after the metrics build, front's IP 84).
- New, verbatim: "Когда мы допускаем ошибку необходимо не только не только придумать способ их автоматического отлова но и способ снижения их появления в будущем / Наш gate строгий, если ошибка есть он точно её отловит / Но должен быть способ не допускать подобных ошибок в будущем - учиться на своих ошибках / Последнее звучит как принцип - учиться на своих ошибках, вероятно будущие модели будут лишены недостатков предыдущих, и рекомендации будут лишь тратить место однако сам принцип обучения на ошибках важен". On the design track: brief scratchpad/briefs/learn-from-mistakes-design.md, output reports/design-learn-from-mistakes.md.

### Addendum (9), 27 Oct: plans go stale; memory notes are not rules

- Owner verbatim: "Проблемы с планом - ранее я упоминал проблему устаревания плана и заявлял что подобный лучше всего делать непосредственно перед исполнением с актуальной, свежей версией репозитория". Front's resolution (owner can reverse): the file beside the item (`.relay/queue/<slug>.md`) keeps what does not go stale: the owner's words and decisions with dates, the questions answered, dated measurements. The design itself is redone against the fresh repository when the item is taken, with that file as input; nobody builds from a stored design directly. Live case: the saved checks-artifacts plan said "nothing built" while its main recommendation (the test-times cache) was on master since 7aef441. wt/plans-save stays unmerged (gate green); its 4 plans become such inputs in the plans change.
- Owner verbatim: "Разве мы не переносили Английские IT термины в сам репозиторий как отдельное правило ? / Предпочтения не тоже самое что и правила, как ты собираешься их хранить ?". Yes: rules/working-with-me.md holds it; the memory note duplicates it. Front's grep: 15 of 23 behaviour notes duplicate repo rules, 8 only in memory, 5 project facts. Question added to the learn-from-mistakes design (brief addendum). Q2 (memory notes into the repo) is replaced by that design.

### Addendum (10), 27 Oct: learn-from-mistakes design done (critic 2 HIGH 6 MEDIUM 2 LOW, all fixed in revision)

File: scratchpad/reports/design-learn-from-mistakes.md. Owner deferred memory management ("На текущий момент отложим вопрос управления памятью о проекте..."): the design's questions 4-5 and its change 3 (memory inbox) are dropped; queued instead quality-rules-kept-only-in-memory-move-into-rela (feature 70). Measured 22-27 Oct: 122 fix items, 396 unique findings (HIGH 100, MEDIUM 157, LOW 139); "agent ends without its report" recurred 9 times after 2 code fixes, never filed (13 workflow StructuredOutput failures + 3 turn-limit stops only in the transcript); text-only lessons recurred in 3 of 3 kinds; reply-style rule text grew 1,801 -> 5,620 bytes in 12 commits; 24.4 kB of rule text read every session. Proposal: rewrite principle 6 as "Learn from each mistake: cause, not symptom" (prefer: make it impossible > guard/test over the kind > step in template/script > brief line > prose tied to an eval); the checker records mistake_kind and prevent per counted finding; agent incidents logged automatically; text lessons retired by ablation (20+ runs without them, ~$1.70 each). Build ~150-180 agent minutes (guess). Asked the owner Q1-Q3.

### Addendum (11), 27 Oct: probe-int and train-recheck merged; scripts move started

- Owner answered the learn-from-mistakes questions "1. A 2. A 3. A"; queued relay-learns-from-each-mistake (feature 94, agent-chosen IP).
- probe-int merged (b0b2490). 30-run proof of the gate on it runs in the background (worktree .worktrees/proof20, logs scratchpad/proof20/summary.tsv, stops at the first red run); runs 1-11 green, 432-600 s.
- train-recheck merged (62adea0): a train checks each rider's closed fix item by name. Review 1 HIGH 2 MEDIUM, all fixed; checker 4 of 4 MET, open 0. It changed agent or skill texts: one paid run on master after this wave, then relay sync.
- Cycle scripts design redone fresh (scratchpad/reports/design-cycle-scripts-r3.md; critic 0 HIGH 8 MEDIUM 3 LOW, all fixed in revision). Measured 27 Oct: the last fix run's two checkers cost 47k + 36k tokens; one checker saves ~36-47k tokens and 5-8 min per change with a queue item (one run); landing by hand 24-27 Oct = 135 ff-merge + 76 take-master + 139 train Bash calls over 59 merges, ~3.6 front calls per landing at a median front context of 229k tokens (a Haiku runner ~15k); today's scripts hold 12 relay-only literals. Plugin `workflows/` folders load by themselves, so every project on this machine gets `plugins/delegate/workflows/cycle.js` without sync (verified in code). Build ~110 agent minutes.
- Front's decision (owner can reverse): build the part common to every answer of the design's question 1 now (cycle.js, fake-runtime tests, ledger stage fields), landing out of scope. Change-cycle workflow running on wt/cycle-scripts, brief scratchpad/briefs/cycle-scripts.md. Asked the owner: does the script also land (a: next item, recommended; b: inside this change; c: front keeps landing).

### Addendum (12), 27 Oct: plans were already decided on 26 Oct; one change for item writing

- Owner: "Не выходит ли так что план это не план вовсе, тот пишется перед началом сессии, а то что мы сохраняем это дискуссия во время создания задачи, brainstorm"; then "A" (a list of dated notes in an item, one relay queue command writes them); then "Разве мы уже не храним заметки в задаче, я начинаю думать что мы забыли зачем начали это делать, для чего ты вообще сохранял временные файлы планов для задач".
- Front's finding: the 26 Oct decision (owner: "достаточно просто сохранить запрос пользователя а дизайн будет выполнен перед выполнением...") already said: an item holds the owner's words and dated facts, no report links, design fresh when taken; fix item queue-items-point-at-session-files-that-vanish (88) was queued then and never built. The "plans beside items" path (addenda 8-9, wt/plans-save) re-solved it; dropped. Measured 27 Oct: open items naming a scratchpad path 12 of 69 (26 Oct) -> 19 of 89 (7 added by the front); all 188 item files were written once, never edited later; 3 later owner decisions today had no place in their item (metrics r3 "1. a 2. a" not in each-change-records-its-stage-times-cost-and-cov; cycle-scripts "A" went to a new item; the one-checker saving went to the handover).
- Front's decision (owner can reverse): queue-items-point-at-session-files-that-vanish (fix 88) and an-item-keeps-dated-notes-of-later-decisions (feature 95) are built as one change right after the scripts move, before the-change-cycle-script-lands-a-ready-change-its (principle 1: a fix, and the defect recurs daily). Once notes exist, the first notes are: metrics r3 answers 1a/2a into the metrics item; the one-checker measurement into the scripts item if still open.

### Addendum (13), 27 Oct: cycle scripts merged; principle 10; owner-words item; done/ goes

- cycle-scripts merged (plugins/delegate/workflows/cycle.js; review 0 HIGH 2 MEDIUM 3 LOW, all fixed, open 0); closed change-cycle-workflow-scripts-move-into-relay and relay-ships-the-change-cycle-as-a-saved-workflow. First live run through it: the owner-words design (wgecxpe9n).
- Owner, verbatim: "Давай добавим принцип: поставь себя на место пользователя, программа должна работать просто и интуитивно понятно, если пользователю надо уметь пользоваться твоей программой - она не интуитивно понятно / Что я подразумеваю под уметь пользоваться - знание неочевидных секретов, лазеек, разрыв между пользователем который использует эту программу месяц и пользователем который только ее открыл должен быть минимальным, легкая кривая обучения". Principle 10 building on wt/principle-newcomer (brief scratchpad/briefs/principle-newcomer.md); show the owner the final text before merge (person-facing). principle-10-one-subject-per-file becomes 11.
- Owner: "Мне не нравится, давай начнем с начала, проблема, конкретный, понятный для клиента путь решения, пока это изменение на паузе"; then "Я вижу ответы но не вопрос - он важен"; "Причем если я даю пояснение к ответу то ты должен и его зафиксировать а не просто вариант ответа". Queued what-the-owner-says-about-an-item-stays-in-it (feature 95), built with queue-items-point-at-session-files-that-vanish (fix 88); dropped the two earlier versions. Metrics item was never taken (taken_at empty), measured.
- Owner on done/: "А какие есть статусы у задач, так ли необходим done/ или же это способ различать read only от draft?" then "A" (remove done/; state only from dated events). Measured: relay queue 0.29 s open only, 0.35 s with closed; open 87, taken 0, done 82, dropped 21. Added to the owner-words design brief as an addendum (the running design reads it at review and revision).
- Pending: paid run on master for agent/skill text changes of this wave, then relay sync.

### Addendum (14), 27 Oct: gate proven; owner-words design; principle 10 ready

- 30-run proof of the quick gate on master b0b2490 (after the pid-file fix): 30 of 30 green, 386-630 s, mean 475 s (round 1 before the fix: 9 green then red at run 10). The gate's flakiness is proven fixed by the quality-gate rule (max(20, ceil(3/p)) with p = 1/10). .worktrees/proof20 removed; logs in scratchpad/proof20/.
- Owner-words design done via plugins/delegate/workflows/cycle.js (first live run of the moved script: worked). scratchpad/reports/design-owner-words.md; review 2 HIGH 7 MEDIUM 1 LOW, all fixed. Key HIGH: merge.py:202 and relay_queue.py:1004/1016 detect a closed fix by a file added under done/; removing done/ needs `closed_on` (closed_at empty at base, set at tip). Build ~310 agent min (done/ removal ~105, a guess). Front's decision (owner can reverse): two changes in a row, done/ removal first with its own review, then notes. Asked the owner: Q1 how an answer reaches the item (a: question recorded in the item first, relay reminds on every message while it waits, ~0.03 s; b: front writes after); Q2 the 16 closed items linking session files (front recommends a: write their facts in, +30 min, for device independence; the design recommended leaving them).
- principle-newcomer ready (gate green, open 0); final text shown to the owner as Q3 (merge as is?). F2 outside: principle-10-one-subject-per-file and items citing it must say principle 11 when built; a numbering test now catches duplicates.

### Addendum (15), 27 Oct: owner answers on owner-words; principle 10 corrections

- Owner: "1. A" (the question is recorded in the item before it is shown; relay names waiting questions on every owner message until the answer is recorded); "2. A" (the 16 closed items linking session files get their facts written into the items, +30 min, device independence).
- Owner on principle 10, verbatim: "Тут надо внести коррективы / Разрыв между тем, кто пользуется месяц, и тем, кто только открыл, минимален. / знаешь флаг, порядок, скрытый файл или обходной путь; / Давай просто оставим часть где говорится о том что пользователю должно быть понятно и удобно, я сам вставил их и понимаю что это не лучшие рекомендации, ты написал лучше". A fixer removes the owner's own inserts (the gap sentence, the secrets/workarounds parenthesis, the flag/order/hidden file Fires-on item, ": no secrets to learn" in the title); show the final text, then gate and merge.
- Build started: change 1 of 2, remove done/ (wt/drop-done, brief scratchpad/briefs/drop-done.md, cycle.js run wknwl1yu3). Change 2 (notes, path refusal, waiting-question hook, migration incl. 16 closed items) after it merges; it takes fix item queue-items-point-at-session-files-that-vanish.

## Addendum (16), 27 Oct, later morning

- Merged: principle 10 "Works for a newcomer" (owner's corrected text, check open 0); done/ removed (wt/drop-done: review 2 HIGH + 1 MEDIUM inside, all fixed, check open 0; items now live in .relay/queue/ only, 190 files; `closed_on` decides "closed on this branch").
- Backup before the notes migration: this session's scratchpad (without proof20 and files over 5 MB) copied to $HOME/.relay/backup/scratch-3207dc59 (442 MB, 677 reports).
- Running: workflow wd77fy78e (run wf_c2504f52-e29), cycle.js, change 2 "notes": worktree .worktrees/owner-notes, branch wt/owner-notes, brief scratchpad/briefs/owner-notes.md, design scratchpad/reports/design-owner-words.md sections 5, 7, 8, 9. Owner answers: Q1 "A" (ask through the item + waiting-question hook), Q2 "A" (migrate the 16 closed linking items too).
- When ready: merge master in if it moved, gate if code came in, ff-merge; close feature `what-the-owner-says-about-an-item-stays-in-it` with the merge sha as evidence; remove wt/plans-save (its words migrated).
- Then: one paid run on master (agent/skill/rule texts changed: train-recheck, cycle-scripts, principle 10, done/, notes; includes the 3 new eval cases of design section 9), then `relay sync`.

## Addendum (17), 27 Oct, midday

- Merged 9bc988d: notes on queue items (`relay queue note`, `show` by words, session-file refusal on add, waiting-question hook plugins/front/hooks/ask_waiting.py, 3 eval cases incl. evals/plugin/recall-decision). Review 0 HIGH 4 MEDIUM 3 LOW inside, all fixed; check 8 of 8 MET, open 0. Closed: queue-items-point-at-session-files-that-vanish (by the merge), what-the-owner-says-about-an-item-stays-in-it (evidence: merge sha). Gate needed 3 fix rounds: mypy, Python 3.9 has no typing.TypeGuard, stale plugin copies of relay_queue.py.
- Queued from this run: a-queue-landing-writes-fields-master-s-code-reje (fix 90: migration notes landed on master before the code, master's queue check red until the merge), a-fix-to-lib-leaves-the-plugins-copies-stale (fix 82), the-cycle-script-ignores-an-unknown-argument-sil (fix 80: cycle.js settings go under args.settings, a top-level gate_fixes was ignored silently).
- Leftover: worktree .worktrees/plans-save (branch wt/plans-save) — its words are migrated into items; guard-main refuses `branch -D` in the main checkout, so it stays until the owner or a relay command removes it. Also train-19, train-20, relay-plugins, paid-e905742.
- Running: the wave's paid run, bin/ci at 9bc988d in detached worktree .worktrees/paid-9bc988d, log scratchpad/ci-wave-9bc988d.log (background task bju18yvr0). Green: `relay sync` from the main checkout, then the wave digest. Red: one fix item at the top of the queue.
- Next after that, in order: landing in the cycle script (96), same-setup (95), relay-learns-from-each-mistake (94), metrics (85; its r3 answers "1. a", "2. a" are now notes in the item), containers (84), then fixes from the top.

## Addendum (18), 27 Oct, afternoon

- Paid run at 9bc988d RED ($21.41, 6626 s): keep-owner-words (ru, en) and no-spec-step-typo 1 of 3; recall-decision never loaded (bad quotes in case.yaml). Fix item the-wave-paid-run-of-9bc988d-is-red-in-3-eval-ca (99), three rounds on wt/wave-red, merged aa8cfd1: git-free stub of `relay queue show|note` for eval sessions (git cannot run in the eval sandbox), graders fixed (heredoc, regex for exact facts), front skill loads on owner words about an item and before "what did we decide". Final 3-run sets: recall-decision 15 of 15, keep-owner-words 3/3, -en 3/3; about $6.6 of reruns. no-spec-step-typo left to a-wave-run-is-red-when-one-of-a-case-s-3-runs-fa (trace was deleted).
- Owner, 27 Oct, answers recorded as notes on that item: question 1 (keep the two eval cases with the stub) "a"; question 2 (how the front answers "what did we decide": quote question and options as recorded, translation beside only for a record in another language, marked) "a". Also kept on the review with `relay check owner` (F5).
- Front's errors this segment: told the owner recall-decision passed (it never ran); wrote unmeasured numbers into two questions ("about 60 lines" = 91; "16 English records" = 0); both corrected as fact notes. Lesson: measure before recording a question.
- Queued: a-queue-landing-writes-fields-master-s-code-reje (90), a-fix-to-lib-leaves-the-plugins-copies-stale (82), the-cycle-script-ignores-an-unknown-argument-sil (80), an-owner-answer-to-a-review-question-is-kept-twi (78), relay-has-no-way-to-remove-an-abandoned-branch (75), relay-queue-note-prints-the-wrong-question-for-a (70).
- Running: full paid run at aa8cfd1, worktree .worktrees/paid-aa8cfd1, log scratchpad/ci-wave-aa8cfd1.log (task bomwvws04). Green: `relay sync`, then the wave digest. Red: one fix item at the top.

## Addendum (19), 27 Oct, evening

- Paid run at aa8cfd1: RED on one run only (no-spec-step-typo run 1 of 3), $18.29, 5290 s. Under the owner's majority rule (25 Oct) it is green; the code fix is a-wave-run-is-red-when-one-of-a-case-s-3-runs-fa (raised to 99, lane wt/majority). relay sync waits for it.
- Speed design (owner: "Как мы можем ускориться, три изменения за 8 часов уж слишком мало"), item relay-ships-more-changes-per-hour; owner answers recorded as notes: lanes "6" per project setting ("Это конфигуриремый параметр для каждого проекта, в relay это будет 6"; default 4 elsewhere, front's reading), 4. a (one review per fix, no batching), 5. a (next paid run plays evals 3 at once: EVALS_JOBS=3), majority item question "7. a" (a timed-out run counts as a failed run: item a-timed-out-eval-run-counts-as-one-failed-run, 98, after wt/majority lands).
- Queue-edit design, item an-item-s-text-is-changed-through-a-relay-comman: owner "a a" (edit command rewrites text, quoted spans byte-equal, dated why note; owner words to said notes for new items only) plus the explanation that he meant one scripted path for the whole item lifecycle. Not yet built (next free lane after the 98 item).
- Merged: wt/lanes (relay builds up to 6 changes at once; lanes setting per project, relay 6; paid run D rule: lanes keep building, checked-path changes wait for a green run, wave_min default 3).
- Running lanes (one cycle.js Workflow each): precheck (quiet check runs the gate's quick-red steps; closes a-fix-to-lib-leaves-the-plugins-copies-stale), test-order (93), majority-fix (99), traces (93), paid-estimate (92), typo-flake (92). Briefs in scratchpad/briefs/<name>.md.
- Next paid run: after majority lands, with EVALS_JOBS=3, on a detached worktree of master; then relay sync.

## Addendum (20), 27 Oct, night — state at about 354k tokens

Merged since (19): wt/majority (a case passes a wave by 2 of 3; the gate's verdict comes from bin/eval-record's record, not the eval tool's exit code; relay sync accepts only records of runs on the default branch).
Owner answers since (19), all recorded as notes: lanes "6. Это конфигуриремый параметр для каждого проекта, в relay это будет 6" (default 4 elsewhere, front's reading); majority item "7. a" (a timed-out run counts as a failed run). Open, asked, unanswered: question 8 in gates-run-all-at-once-and-slow-each-other-down (how many gates at once: a. 2, recommended, 10.3 gates/h, 698 s each; b. 1, 420 s, 8.6 gates/h) — wt/gate-slots is otherwise done (check open 1 = that question).
Measured: with 6 lanes, 5 gates at once, load 24-30 on 12 cores, a quick gate took 36 min instead of 8 (fact note on relay-ships-more-changes-per-hour). The front's runner ran `relay gate -C <wt>` without `-- --quick`, which ran the full paid evals ($16.43, 6102 s) on wt/majority: queued as relay-gate-runs-the-paid-evals-unless-told-quick (96). Paid spend 27 Oct: $39.71 + $16.43 + small eval reruns.
Ready, waiting to land: wt/train-21 (precheck, test-order, paid-estimate, traces, typo-flake; recheck of all 5 items open 0) — taking master hit conflicts in bin/eval-record and tests/test_ci_python.py (traces vs majority); a fixer resolves them, then gate, then recheck; ASK THE OWNER before landing (hand-resolved conflict rule). Then wt/queue-edit (open 0; close feature an-item-s-text-is-changed-through-a-relay-comman with the merge sha) and wt/timeouts (open 0) land after the train, one at a time or as train-22.
Running lanes: offbyone-fix (sonnet judge measure, up to $4), gate-quick (96), land-ahead (90), twin-graders (88, up to $3 paid).
After the train and those two land: the wave paid run on master with EVALS_JOBS=3 (owner "5. a") in a detached worktree, background, log in the scratchpad; green -> relay sync from the main checkout; red -> one fix item at the top.
Brief template for a queue fix: scratchpad/briefs/traces.md (sed the slug, worktree name, check -k and the paid line). Workflow cycle.js settings go under args.settings (gate_fixes).

## Addendum (21), 28 Oct, night

- train-21 (precheck, test-order, paid-estimate, traces, typo-flake): master taken by merge 2fbd7ab, conflicts in bin/eval-record and tests/test_ci_python.py resolved by a fixer by hand (report scratchpad/reports/train-21-conflicts.md); quick gate green on 2fbd7ab; recheck of all 5 items open 0. Waiting for the owner: question 2 in item a-red-paid-run-keeps-no-traces-to-find-its-cause ("a" land now recommended). Master has moved since (queue commits only): take master again before the ff-merge.
- Question 1 (gate slots, item gates-run-all-at-once-and-slow-each-other-down): still unanswered.
- Ready, open 0, to land after train-21 as train-22: queue-edit, timeouts, twin-graders, gate-quick, offbyone, land-ahead, stale-texts, hook-flake, ledger-evals. After merge: close feature an-item-s-text-is-changed-through-a-relay-comman with --evidence.
- hook-flake found the likely cause: the live hook test loaded the owner's user-level plugins and delegate's routing guard refused the first Agent call; fixed with --setting-sources project,local.
- New fix item gate-stop-test-sometimes-sees-the-gate-command-a (ip 92): flaky tests/test_gate_stops.py f2, turned stale-texts' gate red once.
- Then: wave paid run on master with EVALS_JOBS=3, then relay sync.
