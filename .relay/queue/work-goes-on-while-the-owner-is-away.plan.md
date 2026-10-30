# Plan: work goes on while the owner is away

Queue item `work-goes-on-while-the-owner-is-away` (feature, ip 90, agent-chosen). Status: design done, read-only; not yet reviewed. Times are UTC unless marked local (+04:00).

Owner, 30 Oct 01:42 local, verbatim: "Сейчас ты ждал моего ответа 3 часа, ведь я отошел поспать, все это время никакой полезной работы не было выполнено, как мы можем исправить ситуацию"

Owner's answers, 30 Oct 01:45 local: "a a" to "Which review questions are decided without you" (a: principles and reversible scope cuts) and "a a" to "Who makes those decisions" (a: the reviewer; the coordinating session does not approve its own merge).

## 1. What is left of this item

The reviewed design (revision 2, `design-no-idle-while-owner-away.md`) named four fixes. Two are done as their own fix items:

| fix | item | state |
|---|---|---|
| D: the cycle fixes every other finding while a question waits | the-cycle-stops-all-fixes-at-a-question-for-the | done |
| C3: the lanes line names the next startable items; a "not reproduced" item is skipped | one-stuck-queue-pick-hides-every-other-startable | done |
| A': the reviewer decides what a principle answers | this item, part A | to build |
| C2: the coordinating session (the front, the session the owner talks to) wakes itself | this item, part B | to build |

## 2. Measured (30 Oct, this session)

All scripts and outputs are in the scratchpad folder `away/` (`gaps.py`, `questions.py`) or inline commands over git, the queue and the transcripts.

**2.1 The two landed fixes already changed the picture.** Gaps of the owner (no message for 60 minutes or more) after D landed, and the commits on master in them (first parent, so merges count once):

| owner away (UTC) | minutes | master commits | of them code (not queue/gate/check/handover) |
|---|---|---|---|
| 29 Oct 18:41 to 21:14 (the night of the complaint) | 153 | 0 | 0 |
| 30 Oct 02:37 to 04:31 | 114 | 9 | 3 |
| 30 Oct 06:06 to 08:06 | 120 | 9 | 3 |
| 30 Oct 09:14 to 10:35 | 80 | 7 | 4 |

Since 29 Oct 21:47 the front never sat with its turn ended for more than 43 minutes, and each of those 3 gaps of 30 minutes or more ended with an agent's notification, not the owner. No whole night has been measured since the fixes: tonight is the first.

**2.2 Idle front ended only by the owner, 24 to 30 Oct** (the front had ended its turn; nothing ran; the next event was the owner's message), gaps over 60 minutes:

| when (UTC) | minutes | why nothing woke it |
|---|---|---|
| 25 Oct 06:12 | 163 | Claude Code's auto-mode safety check returned errors for every command; the front wrote "Я повторю запуск при следующем событии от фоновых работ" (I will retry at the next event from background work). No event came: every agent had stopped. Owner at 08:54: "Продолжай" (continue). |
| 29 Oct 18:33 | 161 | the night of the complaint; causes fixed by D and C3 |
| 27 Oct 11:29 | 63 | owner asked a question; not checked whether work was startable |

The 25 Oct case is the one D and C3 do not touch: the front waited for an event that could not come. Only a timer covers it.

**2.3 A background command that ends wakes an idle front.** The previous design left this unverified and asked for a probe. The transcripts answer it: 97 times (78 in session 3207dc59, 19 in this one) the front had ended its turn and the next turn was started by a background Bash command's notification; the longest was 118 minutes after the turn ended (27 Oct 07:27). So a background command of up to 55 minutes both lives long enough and wakes the session. No probe needed.

**2.4 Reviewers see the principles.** 40 of 40 reviewer transcripts in this session's workflows contain "Principles this project loads" (the project's principles file reaches every agent through CLAUDE.local.md). Settles the previous design's open point 7.

**2.5 Principle 9 itself sends a scope cut to the owner.** rules/principles.md:48: "the owner gets only a real choice: a trade-off, a number, a scope cut." The reviewers of 29 Oct had this line in context. The project's instructions rank above a role text, so a judge text that says "a reversible scope cut is yours" loses to principle 9 as written.

**2.6 Review questions on built changes after the owner's answer** (30 Oct; design reviews left out, they are the owner's by design):

| change | finding | a principle or recorded decision answers it? (my reading, not a second reader) |
|---|---|---|
| the front reviews code itself | F2 MEDIUM: the pass case (critic started in 9 of 10 bench runs) was never run | no: it is a spend (paid runs) |
| relay land closes a feature | F4 LOW: after an intermediate landing, feature stays taken or goes back to open | yes: principles 3 and 10 (the front itself wrote this when it decided it) |
| setup registers a project | F3 MEDIUM: where relay's settings live | no: a real design choice |
| a just-started branch counts as landed | F3 MEDIUM: the reported failure is not reproduced | yes: the recorded `reproduced = "no"` rule |

With 29 Oct (3 by principle, 1 reversible scope cut): 6 of 8 questions would not have waited. All four of 30 Oct were answered within 5 minutes because the owner was present.

**2.7 The check stage also sends choices to the owner.** The fourth question of 29 Oct (the unknown signal) was not a review question: the fixer reported a `Gap` (a case it could not meet) and the checker passed it on, as roles/judge.md check-mode step 6 says. In the 411 stored check records, 20 verdicts are `GAP` on a HIGH or MEDIUM finding that is not outside the change; such a verdict counts as open (lib/relay_verdict.py `open_of`) until the owner's word is recorded. A text-only change to the review step leaves this path as it is.

**2.8 The front already decided a review question itself.** 30 Oct 16:24, review F4 of "relay land closes a feature": "decided by the front (an agent; owner can reverse) ... because: principles 10 and 3". It was LOW, so it held no merge. It is option b of "Who makes those decisions", which the owner turned down.

**2.9 What one wake costs.** The front's context over its 1,980 requests in this session: median 221k tokens, 90th percentile 339k. An Opus cache read is $0.20 per million tokens (plugins/delegate/lib/prices.toml), so one request is about $0.044 at the median. A wake is about 3 requests (read the timer's output, decide, start the next timer after the hook asks): about $0.13, $0.20 at the 90th percentile. Notional dollars: the owner is on a subscription. Within 55 minutes the 1-hour cache is still warm, so a wake reads and does not re-write it.

**2.10 Files.** lib/relay_lanes.py is at 600 lines, the limit of tests/test_module_sizes.py; new lanes code goes to a new module. roles/judge.md is copied into plugins/delegate/agents/critic.md and checker.md by `relay sync` (the `<!-- relay:base judge -->` block), so the text is written once.

## 3. How leading tools handle it

From their documentation and common practice, not measured here.

- **Who decides during review.** Google's code review lets a reviewer approve "LGTM with comments": the reviewer settles what the guide answers and the author applies it without another round; only what the style guide or a recorded design leaves open is escalated. Palantir's policy-bot and Mergify approve by written rules, so a rule-answered case never reaches a person. GitHub CODEOWNERS blocks only the files a person owns.
- **Waiting for a person.** GitHub auto-merge and merge queues: a wait blocks one pull request, never the worker. OpenAI Codex cloud and the Copilot coding agent never stop mid-task for a question; they finish and the person reviews later. Devin sleeps one session until the reply; others go on.
- **Waking an idle agent.** Claude Code re-invokes a session when a background command ends (2.3) and ships a `loop` skill that re-runs a prompt on a fixed interval. CI systems wake on a schedule (GitHub Actions `schedule`, cron) or on an event; none keeps a process polling for a person.

The pattern: rules decide what rules answer; a person blocks only the one decision that is theirs; a timer, not a person, restarts idle work.

## 4. Critique of the picks given

- **"Build: role text in roles/judge.md plus an eval case first"** (the front's reading of the answers). Weak in two places. (1) The owner's "a" counted 4 of 4 questions of that night; the fourth came through the check stage (2.7), which the review text does not reach: built as given, 1 of 4 still waits. (2) Principle 9 tells every reviewer that a scope cut is the owner's (2.5) and outranks the role text, so the squash-type question keeps coming. Plan below adds the check stage (about 30 agent minutes, one small code change) and one clause in principle 9.
- **Front decision (1): waiting changes keep their lanes.** Looked; agree. Rests on the recount (0 to 1 lane freed that night).
- **Front decision (2): the timer is at most 55 minutes.** Agree; cost per wake is now measured at about $0.13 (2.9). The design it came from also had the timer "ending early when lanes change". That needs a process that reads git once a minute for 55 minutes; what it would catch, a lanes change that no agent's end announces, appears once in the data (29 Oct, a fifth lane that likely aged out of `lane_quiet_hours` between 22:22 and 01:14 local, not verified). Principle 7: drop it; it loses at most 55 minutes on such a change.
- **Front decision (3): no default-on-timeout.** Looked; agree.
- **The item's "What": "wakes itself when its last agent ends".** The front cannot know when its last agent ends: the only record, the ledger, counts finished agents as running (open item the-routing-guard-counts-finished-agents-as-runn). The plan starts the timer at any turn end that leaves agent work and no timer, which also covers agents that die without a notification.
- **2.8, the front deciding review F4.** Contradicts the second "a". After part A, a question that still reaches the front is a real one by the reviewer's own rule, so the front skill says: a review or check question is never a front decision.

## 5. Part A: the reviewer decides what a principle answers

### Approaches

| | A0 do nothing | A1 review text only | A2 review and check text, plus one code mark (recommended) |
|---|---|---|---|
| what changes | nothing | roles/judge.md review part, principle 9 clause, eval | A1, plus check-mode step 6, a `decided` mark on an `OUTSIDE` verdict in lib/relay_verdict.py, front skill line |
| 29 Oct night | 4 of 4 wait | 3 of 4 (the check-stage Gap waits) | 4 of 4 decided |
| 30 Oct | 4 of 4 asked | 2 of 4 asked | 2 of 4 asked |
| build | 0 | about 45 agent minutes | about 75 agent minutes |
| paid run | no | rider (role text) | rider (role text) |
| risk | idle lanes whenever the owner is away and a question is open | a check-stage Gap still holds a lane overnight | a reviewer over-decides: 2 built-change answers in 5 days went against the recommendation (previous design 1.4); each becomes a fix item after the merge |

A1 against A2: the owner's "a" said 4 of 4, so A2 is what the answer asked for. Decided (owner can reverse): A2.

### What is built (A2)

1. **Eval cases first** (evals/plugin/, shaped like `critic-role-rule`: a fixture repo, a branch, the agent `delegate:critic` started on it). The graders read the review's TOML input, which the critic writes with the Write tool; `relay check record review` itself cannot run in the eval sandbox (no git; evals/plugin/relay-stub.py covers only `queue show` and `queue note`), and the case does not need it. Three cases, run before the text change to show the first two fail today:
   - `critic-decides-principle`: the fixture's principles say "a defect found elsewhere is a queue item, never a hold"; the branch fixes a found cause of a flaky test, and its item also asked to "name who sends the signal", which the branch does not. Expected: no finding of kind `question`; the unnamed sender is one `outside` finding whose details start `Decided: principle`. Graders, code only (`tool_used` on Write, as critic-role-rule's graders are built): an input that holds `kind = "question"`, max 0; an input that holds `Decided: principle`, min 1; the critic was started (min 1).
   - `critic-decides-principle-ru`: the same, with the item and the principle text in Russian and one typo (principle 5: meaning is tested in several languages and with typos).
   - `critic-asks-a-number` (must not trigger): the branch adds a retry with a delay, and the item says "pick a sensible delay"; the principles say nothing about it. Expected: one `question` finding (min 1) and no `Decided:` line (max 0).
   - Runs: 3 each, on the critic's model. Cost not measured; the nearest case, critic-role-rule, is the reference.
2. **roles/judge.md**, replacing the sentence at lines 65 to 69 ("A matter of taste or a choice only the owner can make goes under Questions for the owner ..."). Text to build:

   > **What you decide, what goes to the owner.** A choice that a principle or a recorded decision (a rule, an owner answer quoted in the prompt or in the queue item) already answers is yours: rate it as a finding with its severity and the fix the principle picks, and begin its `details` with `Decided: principle <n>` (or the decision's place and date) `(owner can reverse)`. A reversible scope cut is yours too: the part the change can do now is an inside finding (none when it is already built), and the rest is one `outside` finding beginning `Decided: scope cut, principle <n>`, which the front files as a queue item. Reversible means undoing it later costs only that item's work: no data dropped, no stored format changed, nothing a person sees. Only what no principle or decision settles is a question for the owner (`kind = "question"`): taste, a number with no rule behind it (a default, a bound, a price), a spend, a scope cut that is not reversible, what a person will see, or two principles that point different ways. Example of 29 Oct: "rebase over a file the branch also changed: keep the review or check again" is decided, principle 1 (correctness first) and rules/git.md (a re-check after a merge commit); a medium finding, fix: check again.

   The "Questions for the owner" intro text that follows stays as it is.
3. **roles/judge.md check mode, step 6**, replacing "The fixer's `Disputed:`, `Gap:` and `Outside:` lines go to the owner as they are, each with your view in one line." Text to build:

   > The fixer's `Gap:` and `Outside:` lines: when a principle or a recorded decision settles one (example, 29 Oct: a found cause lands, and naming the signal's sender is work elsewhere, principle 1), give that finding the verdict `OUTSIDE` with `decided = '''principle <n>: <why>; rest: <one line for the queue item>'''`; it then counts under outside, not open, and the front files the rest. Every other `Gap:`, `Outside:` and every `Disputed:` line goes to the owner as it is, with your view in one line.
4. **lib/relay_verdict.py**: a status may carry `decided` (text, required non-empty) only with verdict `OUTSIDE`; `open_of` does not count a finding whose verdict is `OUTSIDE` and which has `decided`; `outside_of` counts it, so the cycle's outside count tells the front to file it. `relay check show` prints `decided:` under the finding. About 15 lines (the file is on the size test's first-exempt list).
5. **rules/principles.md**, principle 9, the end of the first sentence becomes: "a trade-off, a number, a scope cut that cannot be undone (a reviewer decides a reversible one and files the rest as a queue item)." Owner can reverse: this is the owner's text, changed only to carry the answer "a"; principles reach every project that loads them.
6. **plugins/front/skills/front/SKILL.md**: one line where questions are handled: "A review's or a check's question is never a front decision: it reached you because the reviewer found no principle that settles it; ask the owner. A `Decided:` finding is filed like any outside finding: `relay queue add --from <report.json> F<n>`."
7. Then `relay sync` writes critic.md and checker.md; the paid run takes it as a rider.

### Tests that fail when a claim is false

- "Only a real choice is a question": `critic-decides-principle` and `-ru` fail on today's text (to be shown before the change); `critic-asks-a-number` fails if the text over-decides.
- "A decided OUTSIDE is not open": tests/test_verdict.py: a record with F2 MEDIUM, verdict OUTSIDE, `decided` set: open 0, outside 1. Fails today: open 1.
- "`decided` only with OUTSIDE": the same file: `decided` on a MET, GAP or NOT MET status is refused by `relay check record check`, naming the field.
- "An OUTSIDE without `decided` stays open": the same file: F2 MEDIUM, verdict OUTSIDE, no `decided`, no owner entry: open 1 (today's behaviour kept).

## 6. Part B: the front wakes itself

### Approaches

| | B0 do nothing | B1 timer started by the Stop hook (recommended) | B2 timer that also ends early on a lanes change (the reviewed design) | B3 Claude Code's `loop` skill |
|---|---|---|---|---|
| mechanism | none | `relay wake` sleeps up to 55 minutes in the background; the Stop hook asks for one when none runs and agent work exists | B1 plus a git read of the lanes every minute | the front schedules a recurring prompt on itself |
| 25 Oct outage (163 min) | 163 min | retried at about 55 and 110 minutes | same as B1 | same as B1 |
| a lanes change no agent announces | until the owner | up to 55 minutes late | about 1 minute | up to the interval |
| an agent that dies with no notification | until the owner | up to 55 minutes | same as B1 | same as B1 |
| cost per idle 7-hour night | 0 | 8 wakes, about $1.1 (2.9) | same, plus 420 lanes reads (0.7 s each, measured) | 8 or more; fires even while agents run and the owner talks |
| relay can test it | | yes (hook and command are relay's code) | yes | no: Claude Code's scheduling, outside relay's tests (principle 5) |
| build | 0 | about 60 agent minutes | about 75 | about 20, text only |

B0 rests on 2.1: since D and C3 no gap above 43 minutes in three absences of up to 2 hours. It does not cover 2.2's 25 Oct case (once in 7 days, 163 minutes). Whether to build B1 now or after a measured night is the one open question (section 8).

### What is built (B1)

1. **`relay wake --session <id>`** (new lib/relay_wake.py and a line in bin/relay's command table): writes `$RELAY_HOME/state/wake/<session>.json` with its pid and its end time, sleeps `front.wake_minutes`, removes the file, and prints one line: "Wake after <n> min: <the lanes line>. Look at the running lanes and the queue; when nothing can move without the owner, end the turn." On SIGTERM it removes the file too. The session id is checked as `[A-Za-z0-9_-]+` (the same check the stop stamp uses).
2. **The Stop hook** (plugins/front/hooks/lanes.py, Stop branch; the logic in relay_wake.py, since relay_lanes.py is at its 600-line limit). After `stop_hook_active` and the session check, as today:
   - *Agent work exists* when the lanes state has a pick, or a running lane whose queue item has no unanswered owner question (the same test the picker uses to skip an item).
   - *A wake runs* when the session's wake file exists, its pid answers `kill -0`, and now is before its end time plus 2 minutes (a reused pid after a crash is then not taken for a live wake).
   - Agent work and no wake: refuse once with a reason that names the exact command: "No wake is running and work can move without the owner: start `relay wake --session <id>` with Bash run_in_background, then end the turn." When the lanes nudge also applies (a free lane and a pick), both go in the one reason, so a turn end costs at most one refusal.
   - No agent work (every running lane waits on the owner, nothing startable): no refusal and no wake; the owner's next message wakes the session.
   - Bound: `stop_hook_active`, as today, so at most one refusal per turn end, never a loop. The `stop_nudge` stamp is not used for this rule.
   - Fails open, as the hook does now: any error or overrun prints nothing.
3. **Setting** `front.wake_minutes` in the project's `.claude/kit.toml`: default 55, bound 10 to 55. At 55: 8 wakes per idle 7-hour night, about $1.1; an outage or a dead agent noticed within 55 minutes. At 10: 42 wakes, about $5.5, noticed within 10 minutes. Above 60 every wake re-writes the 1-hour cache (40 reads' worth), so 55 is the top. Out of bounds: the default, and the wake's line says so (as `lanes_line_items` does).
4. **Front skill, Lanes section**: two sentences: the wake is the one background process the front keeps (the paid run aside); when the hook asks for it, start it and end the turn; when it fires, look, act or end the turn. hooks.json description: add "and one refusal to start a wake when agent work exists and no wake runs".
5. Paid run: hook text is a rider. One eval case: the Stop refusal naming the wake → the front calls Bash with `run_in_background` true and `relay wake` (tool_used grader, min 1) and does not start a second one in the same turn (max 1).

### Cost while the owner is present
A turn that ends with agent work and no wake costs one more request and one Bash call the owner sees, once per 55 minutes (then a wake runs and the hook is quiet). Measured front context 221k median: about $0.09 for the extra requests per hour present.

### Tests that fail when a claim is false (tests/test_wake.py, temporary folders only, never the live state)

- No wake file, a running lane whose item has no owner question, `stop_hook_active` false → a refusal naming `relay wake --session <id>`. Fails today: no refusal (the lanes rule needs a free lane and a pick).
- A live wake file (own pid, end time in the future) → no refusal.
- A wake file whose pid is dead, or whose end time passed 2 minutes ago → refusal.
- Every running lane's item has an unanswered owner question and no pick → no refusal.
- `stop_hook_active` true → no refusal, whatever the state.
- Both rules apply → one refusal whose reason names the pick and the wake.
- `relay wake` with `wake_minutes` 0.02 in a test → the file exists while it sleeps and is gone after; the printed line holds the lanes line. SIGTERM → the file is gone.
- `wake_minutes` 70 → 55 used and the line says the value was out of bounds.

## 7. Order and size

1. Part A eval cases, shown failing on today's text (`critic-decides-principle`, `-ru`); 20 minutes.
2. Part A text, principle 9 clause, verdict mark, front skill line; 55 minutes.
3. Part B command, hook rule, setting, tests, skill text, eval case; 60 minutes.

About 135 agent minutes against the item's 2 hours; one paid-run rider (judge text, principle 9, hook text, front skill). The item's `where` should name every file above (rules/principles.md, lib/relay_verdict.py, lib/relay_wake.py, bin/relay, plugins/front/skills/front/SKILL.md, plugins/front/hooks/hooks.json, evals/plugin/) so the lanes hold other items off them; a front step (`relay queue edit`).

Combined effect, estimated (not measured): on a night like 29 Oct the four questions do not wait (3 become inside fixes, 1 an outside item) and free lanes take startable work (C3); on a night like 25 Oct the front retries 55 minutes after its last event instead of waiting 163.

## 8. Open for the owner

**Build the self-wake now, or after one measured night**
When every agent has finished and the front has ended its turn, nothing restarts work until you write. A small timer would wake the front after at most 55 minutes, so it looks again and retries. Since the two fixes of 30 Oct, your three absences of 80 to 120 minutes had 7 to 9 commits each and the front never sat idle over 43 minutes; a whole night has not been measured yet. The one measured case the fixes do not cover: 25 Oct, Claude Code's safety check failed for every command, the front promised to retry "at the next event", none came, and it stood 163 minutes until you wrote "Продолжай".

| | build cost | cost per idle night | if tonight goes idle |
|---|---|---|---|
| a. now (recommended) | about 60 agent minutes, part of this item's paid rider | about $1 (8 wakes) | the timer is not ready tonight either; it is from the next night on |
| b. after tonight | the same, later, only if tonight shows an idle gap over 55 minutes | $0 until then | one more idle night is the measurement |

- a. Build now: rests on the 25 Oct case (measured, once in 7 days) and on 2.3 (the mechanism works, measured 97 times).
- b. Measure tonight first: rests on 2.1 (no idle gap over 43 minutes since the fixes, 3 absences, no whole night).

## 9. What the brief could not settle

- Cost of the three eval cases per run: not measured.
- Whether the 29 Oct fifth lane aged out of `lane_quiet_hours`: not verified; it only matters for B2, which is not recommended.
- How often a fixer's Gap is one a principle settles: 20 Gap verdicts on HIGH or MEDIUM findings in 411 check records; not read one by one.
