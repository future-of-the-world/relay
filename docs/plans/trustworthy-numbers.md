# Plan: trustworthy numbers for relay

Written 2026-10-21 by a thinker agent, read-only, from the branch
`fix/live-verification` (`.worktrees/live-fixes`), this session's transcripts
(0b953f5c), the ledger, `~/.claude.json`, and the Claude Code 2.1.306 program
file. Every figure below was computed on the real files today unless marked
**not checked**. The scripts that produced them are in the scratchpad
(`tn_*.py`), so a worker can re-run them.

Terms:

- **Request**: one call to the model. One request writes several lines to a
  transcript (one per piece of the answer: thinking, text, each tool call),
  all with the same `requestId`.
- **Usage**: the token counts the model service returns for a request: input
  (new, not cached), cache write, cache read, output.
- **Notional dollars**: what the tokens would cost at list price. The owner
  pays a subscription, so dollars only serve as a common weight for tokens.
- **Hidden helper**: a model request Claude Code makes on its own (a progress
  line for a background agent, a session title), billed but never written to
  any transcript.

---

## 1. Why relay's counts are low (question 1)

relay said $5.40 for this session; `/cost` said $8.43. Three causes, in order
of size. The request de-duplication is **not** a cause: it is correct.

### Cause A. Agent transcripts keep a snapshot taken mid-answer

In the **main** transcript every line of a request carries the final usage:
51 of 52 requests have `stop_reason` set, and the output count is the full
answer. In **agent** transcripts the lines are written while the answer is
still streaming: `stop_reason` is empty and `output_tokens` is the count so
far, usually the first block.

Live example, the worker of this session
(`subagents/agent-a6bda98ccec0aae6e.jsonl`, request
`req_011CgFTacV3WVfiADbyFU5Ct`, line 25): one tool call, `output_tokens` 16,
`stop_reason` null. The final count is never written anywhere on disk.

| Sonnet, this session | output tokens |
|---|---|
| relay today (first line of each request) | 673 |
| the largest value on any line of each request | 8,451 |
| `/cost` | 48,700 |

The same holds in all 19 recent sessions with agents (table in section 2):
relay sees 2-30% of agents' output. Main-only sessions match `/cost` exactly
(6 of them to the token, e.g. `amidman` 5bdf4d4b: output 5,683 both).

### Cause B. Hidden helpers: billed requests with no transcript

The ledger shows 54 `agent_stop` events for this session before 17:59 with
no agent type, no start, no transcript file and a 15-49 character reply
(`~/.relay/ledger/2026-10-21.jsonl`; 37 at effort `high`, 17 at `medium`).
Their size matches the gap between `/cost` and the transcripts:

| at 17:59 | transcripts | `/cost` | gap | gap per helper |
|---|---|---|---|---|
| Opus cache read | 9.28m | 11.2m | 1.92m | 52k (37 helpers) |
| Sonnet cache read | 3.31m | 4.3m | 0.99m | 58k (17 helpers) |
| Opus input | 314 | 56.5k | 56k | 1.5k |
| Sonnet input | 120 | 32.7k | 33k | 1.9k |
| Haiku cache read / write | 32,665 / 13,887 | 32.7k / 13.9k | none | (no helpers) |

Each helper re-reads its agent's whole context (about 50k) and adds about
1.5k new tokens. What they are is **not checked**: the program file names
"agentProgressSummaries ... the model-generated progress summary" for
background agents, which fits (one short line, effort of the agent it
describes, none for the 1-minute Haiku scout). One more check settles it:
compare the ledger's helper timestamps with the progress lines the agents
view showed. It does not change the plan: they cannot be attributed to an
agent from disk either way.

Also hidden: one Haiku request per session for the session title (about
1,200 input, 18 output, no cache; seen in 20 of 30 `~/.claude.json` entries).
Negligible: $0.0001.

### Cause C. Prices (section 3)

The table in `prices.toml` is off by model: Sonnet cache reads 2x too dear,
Haiku everything 6-20x too dear, Opus input 25% too dear and Opus main-thread
cache writes 37% too cheap. On this session the errors partly cancel:

| | relay's prices | true prices |
|---|---|---|
| relay's tokens | $5.40 (relay today) | $5.82 |
| `/cost`'s tokens | $8.71 | $8.43 (`/cost`) |

So counting is the big error (36% low); prices add +3% here, more on weeks
with more Sonnet and Haiku.

### Requests: 170 vs 43 is not a bug

`/cost`'s "Main: 43 requests" is the main thread only (my count to 17:59:
45). relay's 170 Opus requests are main plus the Opus agents (thinker, two
critics, the escalated worker).

---

## 2. Can relay get exact counts from disk? (question 2)

**Yes, per session and model, after the session ends.** Claude Code writes
`/cost`'s own figures to `~/.claude.json`, under `projects[<folder>]`:
`lastSessionId` and `lastModelUsage` (per model: input, output, thinking,
cache read, cache write, web searches, `costUSD`). 31 of 34 folders have it
today. Limits: only the **last** session per folder (the next session in
that folder overwrites it), per model not per agent, and it is written when
the session closes (this session's folder shows nothing yet).

**Live, while a session runs:** the status-line program (a command Claude
Code runs after each answer, fed a JSON block) receives
`cost.total_cost_usd` (the `/cost` dollar total). Read from the 2.1.306
program file; the owner has no status line set, so **not checked live**.

**Per agent, never exact.** Agents' final output and hidden helpers are not
on disk anywhere. Best estimator, tested on the 30 sessions that have
`lastModelUsage`:

| estimator | sessions with agents (19) | main-only (11) |
|---|---|---|
| E0 relay today | median -24%, worst -67%, pooled -26% | median -22% |
| E1 true prices only | median -30%, worst -50% | median -2% |
| E2 true prices + agent output from visible characters | median -12%, worst -30%, pooled -14% | median -2% |
| E3 = E2 + agents' cost x 1.23 for hidden helpers | about 0 pooled; agent part within about 5% for half, worst -36% (one session) | same as E2 |

E2's rule: an agent request's output = its visible characters (text plus
tool-call input) x a factor per model, never less than the recorded count.
The factor covers the hidden thinking. Fitted medians (tokens per visible
character): Opus 1.04 (range 0.71-1.51), Sonnet 0.62 (0.46-0.86), Haiku 1.1,
Fable 0.83 (2 sessions only). E3's 1.23 is the median of `1/(1-gap)` over
those 19 sessions; the E3 spread is a hand estimate from the per-session
gaps, **not checked** by a run.

So the design: exact where Claude Code wrote a figure, E3 elsewhere, and
each number says which ("exact" / "estimate").

---

## 3. Prices (question 3)

The brief's "four unknowns, one equation per model" is not the situation: the
30 `lastModelUsage` entries give 30 equations per model. Solved by least
squares, then checked against round figures:

| per million tokens | input | output | cache read | cache write 5 min | cache write 1 h | fit |
|---|---|---|---|---|---|---|
| Opus 5.5 | 4.00 | 20.00 | 0.20 | 5.00 | 8.00 | exact on the 7 main-only sessions; median 0.1%, worst 2.4% on all 30 |
| Sonnet 5.5 | 2.00 | 10.00 | 0.10 | 2.50 | 4.00 | median 0.0%, worst 21% (1-h share unknown in one session) |
| Haiku 5.5 | 0.10 | 0.50 | 0.01 | 0.125 | 0.20 | exact on 5 sessions; the rest exact after web searches |
| Fable 5.1 | 10.00 | 50.00 | 0.25 | 12.50 | 20.00 (pattern) | 2 sessions, both fit at this table |
| Haiku 4.5 | 1.00 | 5.00 | 0.10 | 1.25 | 2.00 | exact on 11 |
| web search | $10 per 1,000 | | | | | |

Check on this session, `/cost`'s tokens at this table: Opus $7.00 (`/cost`
$6.99), Sonnet $1.434 ($1.43), Haiku $0.00313 ($0.0031).

What changes from `prices.toml`:

- Cache read is **not** $0.20 on every model: it is 0.20 on Opus, 0.10 on
  Sonnet, 0.01 on Haiku. Within each model the ratios are the same: a
  5-minute write costs 25 reads, a 1-hour write 40, an output 100. The
  rule text "on Sonnet 12.5 and 50" came from assuming the same read price
  on every model.
- The main thread writes its cache for 1 hour (every main request has
  `ephemeral_1h_input_tokens`); agents write for 5 minutes. relay must price
  the two apart; the transcript's `usage.cache_creation` says which.
- **Why Haiku costs $0.0031:** Haiku's read is 20x cheaper than Opus's and
  its input 40x. This session's scout: 32.7k read = $0.0003, 13.9k written
  = $0.0017, 1.9k output = $0.001. The same scout work on Opus would be
  $0.15, on Sonnet $0.06. Haiku is close to free, so "move it to Haiku" is
  worth more than relay's reports now say.

These are Claude Code's own list prices (what `/cost` shows). Whether the
subscription limit weighs tokens the same way is **not checked** (section 4).

---

## 4. Share of the limit (question 4)

**A local source exists.** The status-line JSON carries
`rate_limits.five_hour.used_percentage`, `rate_limits.seven_day.used_percentage`
and each `resets_at` (code read in the 2.1.306 program file; **not checked
live**). The Fable weekly bar (`model_scoped` in the usage service's answer)
is **not** passed to the status line. Nothing on disk holds the limit
percentages: searched `~/.claude` and `~/.claude.json`, no hit.

**What relay can measure from it:** the status line runs after each answer
in each open session. relay logs one ledger line `limits` (time, session,
`total_cost_usd`, the two percentages, reset times). Between two samples the
week's percentage rises by some points while all open sessions' notional
dollars rise by some amount; over a few days that gives **percent of the
week per notional dollar** (and per hour of the 5-hour window). Then every
report figure can be shown as "share of your week": a $8.43 session at, say,
0.4% per dollar reads "3.4% of your week". Until enough samples exist (setting
below), reports show shares of the period's own usage ("critics: 28% of this
week's usage"), the way Claude Code's own advice does.

The weight relay uses inside a period is the notional dollar from section 3;
that the limit uses the same weights is an assumption the fitted
"percent per dollar" tests: if it drifts between Opus-heavy and Sonnet-heavy
days, the weights differ.

---

## 5. The four open items (question 5)

**S-A. `bin/kit` needs Python 3.11.** `plugins/core/bin/kit:53-56` exits 2
without `tomllib`, and the guard then fails closed. The same plugin already
ships `lib/relay_toml.py` (`load`, `loads`; added for the 3.9 hooks). Fix:
`try: import tomllib` / `except ImportError: import relay_toml as tomllib`,
with the decode error class taken from whichever loaded. Test: run `kit get`
under a Python with `tomllib` hidden (a test that sets `sys.modules["tomllib"]
= None`); fails today with rc 2.

**S-B. "Your turns" counts things you did not type.** `lib/relay_transcripts.py`
(`_absorb`, the `kind == "user"` branch) counts every text line not flagged
meta/compact/notification; the `startswith("<")` check only guards
`prompt_chars`, not the count. Real lines from this session: `[Request
interrupted by user]` (line 180, no `origin`) counted; the typed ones carry
`origin.kind == "human"` and `promptSource` (`typed`,
`suggestion_accepted`). Fix: when the line has `origin`, a turn is
`origin.kind == "human"` only; without it (older transcripts), skip text
starting with `[Request interrupted`, `<command-name>` of a local command
(`/clear`, `/cost`, `/model`, ...), `<local-command-stdout>`,
`<local-command-caveat>`, `<bash-input>`/`<bash-stdout>`. A slash command
that runs a prompt (`/opsx:apply`) is a turn. Test: a fixture transcript with
one of each; expect 2 turns (the typed text and `/opsx:apply`); today gives 6.

**Guard and shell variables.** Reproduced today with
`plugins/core/lib/kit_guard.py`: `mkdir -p $S` gives `W /Users/amidman/relay/$S`
(a write in the main checkout); `git -C $W add -A` gives
`G /Users/amidman/relay/$W`. Cause: a bare `$NAME` outside quotes falls to
the plain-character branch (`kit_guard.py:296-299`) and never marks the word
as dynamic; only `$` inside double quotes does (`:159-160`). Fix, in this
order: (1) a static assignment `NAME=value` as its own command in the same
command string is remembered and `$NAME`/`${NAME}` expanded later in it, so
`W=/Users/amidman/relay; git -C $W add` is still refused and
`S=/tmp/x; mkdir -p $S` passes; (2) otherwise a `$` followed by a letter,
`_`, `{` or a digit marks the word dynamic, which the header
(`kit_guard.py:36`) already says is skipped; (3) in `git_parts`
(`:368-369`) a dynamic `-C` value makes the place unknown and the git
command skipped, not judged in the current folder. Tests: the four commands
above plus `echo hi > $S/a`; three of them fail today. Cost of (2), said
once: Bash state does not carry between calls, so an unset `$W` is empty and
`git -C $W add` really runs in the main checkout; the guard will let that
slip through. The header already chose "catches slips, not a determined
bypass", so I kept it.

**Two core plugins in Kartoteka.** Not "disabled": `core@principles` is
installed for `~/kartoteka` and enabled in `~/kartoteka/.claude/settings.json`
(with `sdd@principles`, `product@principles`), while `core@relay` is on for
every project. In Kartoteka both guards run on every tool call and both inject
the project addition into each agent (twice the tokens of that addition per
agent; size **not checked**). Separately, `relay sync` would rewrite the
principles plugins' agents: `installed_plugin_dirs` (`lib/relay_rules.py:166-178`)
matches by plugin name only. Fix that part regardless: match only keys
ending in `@<relay's marketplace name>` (read from
`.claude-plugin/marketplace.json`). Test: a fake `installed_plugins.json`
with `sdd@principles` and `delegate@relay`; sync must touch only the second;
fails today. `relay doctor` gains a line naming a plugin enabled from two
marketplaces in one project. Which of the two to keep in Kartoteka is
question 2.

---

## 6. Option 4: the large repeated requests (question 6)

The 7-day bucket table (explore write-up G-8): requests carrying 50-200k
context are 67% of notional spend. Two things to know before building a lever:

1. **The table must be redone with the true prices.** Cache read is most of
   that money and Sonnet's read is half what relay charged, so the share
   moves toward Opus requests. Expect the 50-200k share to stay large, but
   the figure is **not checked**.
2. **The lever that relay can measure: carried weight.** A context is big
   because earlier tool results stay in it and are re-read on every later
   request. A 20k-token file read at request 5 of a 40-request agent is
   re-read 35 times: 700k cache reads, $0.14 on Opus, $0.07 on Sonnet. relay
   can compute, per tool result in a transcript, its size (characters / 3.5)
   x the requests after it (until a compaction) x the read price, and sum by
   tool (Read, Bash, Grep, MCP) and by agent type. That gives a finding
   "F9 carried weight" with a lever per row: bounded reads (offset/limit),
   bounded command output, a scout for big reads, a fresh agent per task
   group. Whether the money concentrates in a few big results (the lever
   pays) or spreads thinly (it does not) is **not checked**: one run of that
   sum over the last 7 days (2.7 GB, 1,656 files; expect 1-3 minutes) settles
   it.

The wrap-note threshold from option 4 (default 120k, bound 60-200k) stays as
proposed there, but only after F9 shows how much of the band it would touch.

---

## 7. Work, in three worker briefs

Order: group 1 first (everything reads its numbers); group 2 is independent
and can run beside it; group 3 after group 1 and after the owner answers
question 1.

### Group 1. Exact where possible, honest estimate elsewhere (size: 5-7 h, one worker, one critic pass)

1. `prices.toml`: the table of section 3, with `cache_write_1h` added, a
   `web_search` price, `haiku-4-5` as its own key, `measured = 2026-10-21`
   and a comment naming the source (`lastModelUsage`, 30 sessions).
   `lib/relay_prices.py`: price 1-hour and 5-minute writes apart from
   `usage.cache_creation`.
2. `lib/relay_transcripts.py`: for agent traces, output = max(recorded,
   visible characters x factor); mark the agent's figure `estimated`. Main
   traces unchanged (they are exact).
3. Capture the exact figures: at `SessionStart` (observe hook,
   `plugins/observe/hooks/ledger.py`) read `projects[cwd]` from
   `~/.claude.json`; if `lastSessionId` is a session not yet recorded, write
   a ledger line `session_usage` with `lastModelUsage` (numbers only). This
   avoids depending on whether Claude Code writes the file before or after
   the `SessionEnd` hook (**not checked**). Plus `relay calibrate`: backfill
   from all current entries (31 today) and print, per model, transcript vs
   exact, and the fitted factors.
4. `relay report`: per session and model, use `session_usage` when present
   (label "exact"), else E3 (label "estimate"); the totals line says how much
   of the period is exact, e.g. "exact for 62% of usage". A line "Claude Code
   helpers (no transcript)" = exact minus what transcripts explain.
5. Docs: `docs/observability.md` (transcript snapshot, helpers, exact
   source), `rules/delegation.md` and the prices comment (ratios 25 / 40 /
   100 on every model; reads differ 20x across models).

Checks: `bin/ci --quick` green. Regression tests that fail before the fix:
(a) a fixture agent transcript whose lines carry partial usage (copied
numbers from `agent-a6bda98ccec0aae6e`, no text) plus a fake `~/.claude.json`
entry: the report shows the exact output (48.7k scale, not 673);
(b) the 7 Opus main-only sessions' token counts and `costUSD` as numeric
fixtures: priced within 0.1% (today 2-28% off); (c) a request with 1-hour
writes is priced at $8, not $5. Live check: `relay calibrate` on this Mac
reproduces section 3's table and E2's error figures.

Settings (in `prices.toml` or the relay config, each with default and bound):
chars-to-tokens factor per model (defaults 1.04 / 0.62 / 1.1 / 0.83, bound
0.3-2.0, refit by `relay calibrate`); helper uplift on agents' cost (default
1.23, bound 1.0-1.6); calibration tolerance before `relay doctor` warns
(default 2%, bound 0.5-10%).

### Group 2. The four open items (size: 3-4 h, one worker, one critic pass)

S-A, S-B, the guard and variables, and `relay sync` matching only relay's
marketplace, exactly as in section 5, each with the regression test named
there (each fails before its fix). Plus `relay doctor`: a plugin enabled from
two marketplaces in one project. Not in scope: changing Kartoteka's settings
(question 2). After merge, the installed plugin copies in
`~/.claude/plugins/cache/relay/` must be updated, or the fixes do nothing
(explore G-4). Check: `bin/ci --quick` green; the guard commands of section 5
give the expected rows.

### Group 3. Share of the limit, then the carried-weight finding (size: 4-5 h, one worker, one critic pass; after group 1 and question 1)

1. A status-line command in the observe plugin: reads the JSON on stdin,
   appends a `limits` ledger line at most once per interval, prints the line
   chosen in question 1. `relay install` sets it in `~/.claude/settings.json`
   only if none is set (never replaces the owner's).
2. `relay report`: "percent of week per notional dollar" fitted from the
   `limits` lines; period, model, agent-type and session figures shown as
   share of the week once the fit has enough data, else share of the
   period's usage.
3. Finding F9 "carried weight" (section 6), in `lib/relay_analyze.py`, with
   the 7-day sum run once and its result written into the doc.

Checks: tests with fixture status-line JSON (two samples, two sessions:
expected percent per dollar); a fixture transcript with one big early tool
result: F9 names it with the expected re-read count. Live: one session with
the status line on shows `limits` lines in the ledger (this is the first
live check of the `rate_limits` field).

Settings: status-line sample interval (default 60 s, bound 10-600 s); fit
needs at least this much change in the week's percentage (default 5 points,
bound 2-20) and at least 2 days of samples; F9 lists results over a size
(default 5k tokens, bound 1k-50k).

---

## 8. Decisions I made (inside the principles)

- Counting before prices, both in group 1: prices fitted on wrong counts
  would be wrong.
- Prices from `lastModelUsage` least squares, not the vendor pattern: the
  data gave exact fits, so no assumptions were needed.
- Exact figures captured at the next `SessionStart` rather than
  `SessionEnd`, because the write order is unknown and the next start is
  certain to see the file.
- Every report number says "exact" or "estimate"; the estimate is E3.
- Guard: unknown variables skipped (the header's existing rule); assignments
  in the same command expanded.
- `relay sync` touches only relay's own marketplace: the current name match
  is a bug.
- The rule text on price ratios is corrected as a fact, not a choice.

## 9. Questions for the owner

**Q1. A status line at the bottom of every Claude Code session.** relay needs
one to read your limit percentages; it is something you will see.
- (a) *Recommended:* a short line, e.g. `5h 12% · week 3% · session $8.43`.
  You get the limit at a glance without `/usage`; relay gets its samples.
  Costs one line of screen.
- (b) A silent one that logs and prints nothing. Same data for relay; you see
  nothing new.
- (c) None. relay reports only shares of its own usage ("critics: 28% of this
  week"), never "% of your week"; no way to tell whether limit weights match
  the dollar weights.

**Q2. Kartoteka runs two copies of the core plugin** (relay's and the older
principles one): two guards on every tool call, the project addition injected
twice into each agent.
- (a) *Recommended:* switch relay's copy off in Kartoteka only, until
  Kartoteka moves to relay (one line in its settings). Kartoteka keeps
  working as today; loses: relay's newer guard fixes (the variable fix) there.
- (b) Remove the principles copy now. One guard, relay's; risk: the
  principles `sdd` and `product` plugins Kartoteka still uses may call the
  principles core's helper (**not checked**), and a broken call stops its
  OpenSpec flow.
- (c) Leave both. Costs the double addition per agent (size not checked) and
  about 30 ms per tool call.

## 10. What the brief could not answer

- What the hidden helpers are (progress summaries is the likely answer, not
  checked); they are counted either way.
- Whether `~/.claude.json` is written before the `SessionEnd` hook (avoided
  by design).
- The `rate_limits` field live (read from the program file only).
- Whether the subscription limit weighs tokens like the list prices (group 3
  measures it).
- The 50-200k share at true prices and the carried-weight sum (one 7-day run
  each).
