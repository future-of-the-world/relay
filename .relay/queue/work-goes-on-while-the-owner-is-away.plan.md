# Plan: work goes on while the owner is away

Queue item `work-goes-on-while-the-owner-is-away` (feature, ip 90, agent-chosen). Status: design, revision 2, after the design review of 30 Oct (8 findings; all held, one with a correction; section 10). Read-only; nothing built. Times are UTC unless marked local (+04:00).

Owner, 30 Oct 01:42 local, verbatim: "Сейчас ты ждал моего ответа 3 часа, ведь я отошел поспать, все это время никакой полезной работы не было выполнено, как мы можем исправить ситуацию"

Owner's answers, 30 Oct 01:45 local: "a a" to "Which review questions are decided without you" (a: principles and reversible scope cuts) and "a a" to "Who makes those decisions" (a: the reviewer; the coordinating session does not approve its own merge).

## 1. What is left of this item

The reviewed design (revision 2, `design-no-idle-while-owner-away.md`) named four fixes. Two are done as their own fix items:

| fix | item | state |
|---|---|---|
| D: the cycle fixes every other finding while a question waits | the-cycle-stops-all-fixes-at-a-question-for-the | done |
| C3: the lanes line names the next startable items; a "not reproduced" item is skipped | one-stuck-queue-pick-hides-every-other-startable | done |
| A': the reviewer decides what a principle answers | this item, part A | to build |
| C2: the coordinating session (the front, the session the owner talks to) wakes itself | this item, part B | open question (section 8) |

## 2. Measured (30 Oct)

Scripts and outputs are in the scratchpad folder `away/` (`gaps.py`, `questions.py`) or inline commands over git, the queue and the transcripts. Numbers marked "(review)" were measured by the design reviewer and are quoted from its record.

**2.1 The two landed fixes already changed the picture.** Gaps of the owner (no message for 60 minutes or more) after D landed, and the commits on master in them (first parent, so merges count once):

| owner away (UTC) | minutes | master commits | of them code (not queue/gate/check/handover) |
|---|---|---|---|
| 29 Oct 18:41 to 21:14 (the night of the complaint) | 153 | 0 | 0 |
| 30 Oct 02:37 to 04:31 | 114 | 9 | 3 |
| 30 Oct 06:06 to 08:06 | 120 | 9 | 3 |
| 30 Oct 09:14 to 10:35 | 80 | 7 | 4 |

Since 29 Oct 21:47 the front never sat with its turn ended for more than 43 minutes, and each of its 3 gaps of 30 minutes or more ended with an agent's notification, not the owner. No whole night has been measured since the fixes; tonight (30 to 31 Oct) is the first.

**2.2 Idle front ended only by the owner, 24 to 30 Oct** (the front had ended its turn; nothing ran; the next event was the owner's message), gaps over 60 minutes:

| when (UTC) | minutes | why nothing woke it |
|---|---|---|
| 25 Oct 06:12 | 163 | Claude Code's auto-mode safety check (the classifier that approves each tool call in auto mode) returned an error for every Bash and Workflow call from 06:09:12; the front wrote "Я повторю запуск при следующем событии от фоновых работ" (I will retry at the next event from background work). No event came: every agent had stopped. Owner at 08:54: "Продолжай" (continue); the first command at 08:55 passed. When the check recovered between 06:12 and 08:55 is not known (review). |
| 29 Oct 18:33 | 161 | the night of the complaint; causes fixed by D and C3 |
| 27 Oct 11:29 | 63 | owner asked a question; not checked whether work was startable |

The 25 Oct case is the one D and C3 do not touch. Section 6 shows how much of it each timer covers: less than revision 1 of this plan claimed.

**2.3 A background command that ends wakes an idle front.** 97 times (78 in session 3207dc59, 19 in this one) the front had ended its turn and the next turn was started by a background Bash command's notification; the longest was 118 minutes after the turn ended (27 Oct 07:27). So a background command of up to 55 minutes both lives long enough and wakes the session.

**2.4 Reviewers see the principles.** 40 of 40 reviewer transcripts in this session's workflows contain "Principles this project loads" (the principles reach every agent through CLAUDE.local.md).

**2.5 Principle 9 itself sends a scope cut to the owner.** rules/principles.md:48: "the owner gets only a real choice: a trade-off, a number, a scope cut." The project's instructions rank above a role text, so a judge text that says "a reversible scope cut is yours" loses to principle 9 as written.

**2.6 Review questions on built changes after the owner's answer** (30 Oct; design reviews left out, they are the owner's by design):

| change | finding | a principle or recorded decision answers it? (my reading, not a second reader) |
|---|---|---|
| the front reviews code itself | F2 MEDIUM: the pass case (critic started in 9 of 10 bench runs) was never run | no: it is a spend (paid runs) |
| relay land closes a feature | F4 LOW: after an intermediate landing, feature stays taken or goes back to open | yes: principles 3 and 10 |
| setup registers a project | F3 MEDIUM: where relay's settings live | no: a real design choice |
| a just-started branch counts as landed | F3 MEDIUM: the reported failure is not reproduced | yes: the recorded `reproduced = "no"` rule |

With 29 Oct (3 by principle, 1 reversible scope cut): 6 of 8 questions would not have waited.

**2.7 The check stage also sends choices to the owner.** The 29 Oct "unknown signal" question was not a review question: the fixer reported a `Gap` (a case it could not meet) and the checker passed it on. That finding was F2 MEDIUM, kind inside ("the 29 Oct sender is neither found nor the group theory shown"; read in the scratchpad's `check-a-gate-test-is-stopped-by-an-unknown-sig.json`). Over the 413 stored check records, the HIGH and MEDIUM findings with verdict `GAP` are (review): HIGH inside 2, HIGH feature 3, MEDIUM question 8, MEDIUM inside 4. Under the bound of section 5 (MEDIUM or LOW, not kind question or design, reversible) at most the 4 MEDIUM inside ones could be decided by a checker; the other 13 stay with the owner.

**2.8 The front already decided a review question itself.** 30 Oct 16:24, review F4 of "relay land closes a feature": "decided by the front (an agent; owner can reverse) ... because: principles 10 and 3". It was LOW, so it held no merge. It is option b of "Who makes those decisions", which the owner turned down.

**2.9 What one wake costs.** The front's context over its 1,980 requests in this session: median 221k tokens, 90th percentile 339k. An Opus cache read is $0.20 per million tokens (plugins/delegate/lib/prices.toml), so one request is about $0.044 at the median. A wake is about 3 requests: about $0.13, $0.20 at the 90th percentile. Notional dollars: the owner is on a subscription. Within 55 minutes the 1-hour cache is still warm.

**2.10 Files.** lib/relay_lanes.py is at 600 lines, the limit of tests/test_module_sizes.py; new lanes code goes to a new module. lib/relay_verdict.py is on the size test's first-exempt list (review). roles/judge.md is copied into plugins/delegate/agents/critic.md and checker.md by `relay sync`. The fixer's "A `Gap:` goes back to the coordinator, who asks the owner" is plugins/delegate/agents/fixer.md:157, in the fixer's own part (after the shared blocks), not in roles/fix.md. lib/relay_land_waits.py already has the two tests behind "waits for the owner" (`relay land` exit 5): `held_words` (the owner's hold on the branch) and `unanswered` (a question on the branch's item with no answer).

## 3. How leading tools handle it

From their documentation and common practice, not measured here.

- **Who decides during review.** Google's code review lets a reviewer approve "LGTM with comments": the reviewer settles what the guide answers; only what the guide or a recorded design leaves open is escalated. Palantir's policy-bot and Mergify approve by written rules. GitHub CODEOWNERS blocks only the files a person owns.
- **Waiting for a person.** GitHub auto-merge and merge queues: a wait blocks one pull request, never the worker. OpenAI Codex cloud and the Copilot coding agent finish and the person reviews later.
- **Waking an idle agent.** Claude Code re-invokes a session when a background command ends (2.3) and ships a `loop` skill that re-runs a prompt on a fixed interval. CI systems wake on a schedule (cron) or on an event.

The pattern: rules decide what rules answer; a person blocks only the one decision that is theirs; a timer, not a person, restarts idle work.

## 4. Critique of the picks given

- **"Build: role text in roles/judge.md plus an eval case first"** (the front's reading of the answers). Weak in two places. (1) The fourth question of 29 Oct came through the check stage (2.7), which the review text does not reach: built as given, 1 of 4 still waits. (2) Principle 9 tells every reviewer that a scope cut is the owner's (2.5) and outranks the role text. The plan adds the check stage (bounded, section 5) and one clause in principle 9. Principle 9 is the owner's text and reaches every project that loads it; the front names that edit in its report after the build.
- **Front decision (1): waiting changes keep their lanes.** Looked; agree. Rests on the recount (0 to 1 lane freed that night).
- **Front decision (2): the timer is at most 55 minutes.** Agree; cost per wake measured at about $0.13 (2.9). The "ending early when lanes change" part is dropped (principle 7): what it would catch appears once in the data, not verified.
- **Front decision (3): no default-on-timeout.** Looked; agree.
- **The item's "What": "wakes itself when its last agent ends".** The front cannot know when its last agent ends: the ledger counts finished agents as running (open item the-routing-guard-counts-finished-agents-as-runn). Part B starts the timer at any turn end that leaves work the front can move and no timer.
- **2.8, the front deciding review F4.** Contradicts the second "a". After part A, a question that still reaches the front is a real one by the reviewer's own rule, so the front skill says: a review or check question is never a front decision.
- **Revision 1 of this plan** recommended building the timer now, resting on the 25 Oct case; the review showed the timer covers that case at most once (section 6). The recommendation in section 8 changed on that evidence.

## 5. Part A: the reviewer decides what a principle answers

### Terms

- **Decided finding**: a finding the reviewer or checker settled by a principle or a recorded decision, without asking the owner. It carries a `decided` field (text: the principle or decision, and why), so scripts read a field, not a prefix in prose (principle 4).
- **Reversible scope cut**: the change does part of what the item asked for, and the rest becomes a queue item. Reversible means undoing it later costs only that item's work: no data dropped, no stored format changed, nothing a person sees. A scope cut defers new work only, never a defect: a HIGH or MEDIUM wrong behaviour inside the change is still fixed before the merge.

### Approaches

| | A0 do nothing | A1 review text only | A2 review and bounded check text, plus a `decided` field (recommended) |
|---|---|---|---|
| what changes | nothing | roles/judge.md review part, principle 9 clause, eval | A1, plus check step 6 (bounded), a `decided` field in lib/relay_verdict.py with a guard, `relay queue add --from` files a scope cut's rest as a feature, front skill lines, fixer line |
| 29 Oct night | 4 of 4 wait | 3 of 4 (the check-stage Gap waits) | 4 of 4 decided (the Gap was MEDIUM inside, 2.7) |
| 30 Oct | 4 of 4 asked | 2 of 4 asked | 2 of 4 asked |
| stored check-stage GAPs a checker may decide | 0 | 0 | at most 4 of 17 (2.7); 13 stay with the owner |
| build | 0 | about 45 agent minutes | about 130 agent minutes |
| paid run | no | rider (role text) | rider (role text) |
| risk | idle lanes whenever the owner is away and a question is open | a check-stage Gap holds a lane overnight | a reviewer over-decides: 2 built-change answers in 5 days went against the recommendation (previous design 1.4); each becomes a fix item after the merge, and the `merged:` line shows every decision (item 8) |

A2 is what the owner's "a" asked for (4 of 4). Decided (owner can reverse): A2.

### What is built (A2)

1. **Eval cases first** (evals/plugin/, shaped like `critic-role-rule`: a fixture repo, a branch, `delegate:critic` started on it). Graders read the review's TOML input, which the critic writes with the Write tool (`tool_used` graders see subagent calls, review). Each fixture is built so only one path applies, so a pass shows which rule the text taught. Run before the text change to show the first two fail today:
   - `critic-decides-principle` (English): the fixture's rules say "after a branch takes the base, the files it changed are checked again"; the branch keeps the old review when the base it takes touches a file the branch also changed (the 29 Oct rebase question). Expected: no `kind = "question"` finding; one finding with `decided` naming that rule. Graders: input holds `kind = "question"`, max 0; input matches the regex `decided\s*=\s*['"]+principle`, min 1; critic started, min 1.
   - `critic-decides-scope-cut-ru` (Russian item and principle text, one typo; principle 5): the fixture's principles say "a defect found elsewhere is a queue item, never a hold"; the branch lands a found cause of a flaky test, and its item also asked to "name who sends the signal", which the branch does not do. Expected: one `kind = "outside"` finding with `decided`, no question. Graders as above, plus input holds `kind = "outside"`, min 1.
   - `critic-asks-a-number` (must not trigger): the branch adds a retry with a delay; the item says "pick a sensible delay"; the principles say nothing about it. Expected: one `question` finding (min 1) and no `decided` (regex max 0).
   - Runs: 3 each, on the critic's model. Cost per run not measured; the nearest case, critic-role-rule, is the reference.
2. **roles/judge.md**, replacing the sentence at lines 65 to 69 ("A matter of taste or a choice only the owner can make goes under Questions for the owner ..."). Text to build:

   > **What you decide, what goes to the owner.** A choice that a principle or a recorded decision (a rule, an owner answer quoted in the prompt or in the queue item) already answers is yours: rate it as a finding with its severity and the fix the principle picks, and give it `decided = "principle <n>: <why> (owner can reverse)"` (or the decision's place and date). A reversible scope cut is yours too: the change does part of what the item asked, and the rest is one finding of kind `outside` with `decided = "principle <n>, scope cut: <the rest in one line> (owner can reverse)"`; the front files it as a feature. Reversible means undoing it later costs only that item's work: no data dropped, no stored format changed, nothing a person sees. A scope cut defers new work only: a HIGH or MEDIUM wrong behaviour inside the change is a finding, fixed before the merge. Only what no principle or decision settles is a question for the owner (`kind = "question"`): taste, a number with no rule behind it (a default, a bound, a price), a spend, a scope cut that is not reversible, what a person will see, or two principles that point different ways. Example of 29 Oct: "rebase over a file the branch also changed: keep the review or check again" is decided, principle 1 and rules/git.md (a re-check after a merge commit); a MEDIUM finding, fix: check again.

   The "Questions for the owner" intro text that follows stays as it is.
3. **roles/judge.md severity paragraph** (lines 61 to 62, "inside the change they are fixed before the merge, with no deferral"): add "; the one deferral is the rest of a reversible scope cut, which is new work, not a defect".
4. **roles/judge.md check mode, step 6**, replacing "The fixer's `Disputed:`, `Gap:` and `Outside:` lines go to the owner as they are, each with your view in one line." Text to build:

   > The fixer's `Gap:` and `Outside:` lines: when one is a reversible scope cut (definition in "What you decide") of a MEDIUM or LOW finding that is not of kind `question` or `design`, and a principle or a recorded decision settles it (example, 29 Oct: a found cause lands, and naming the signal's sender is work elsewhere, principle 1), give that finding the verdict `OUTSIDE` with `decided = "principle <n>, scope cut: <the rest in one line>"`; it then counts under outside, not open, and the front files the rest. Never on a HIGH finding, never on a question or design finding: those, every other `Gap:`, `Outside:` and every `Disputed:` line go to the owner as they are, with your view in one line.

   This agrees with cycle.js:399 ("Every question or Design finding waits for the owner"), which stays.
5. **roles/judge.md check mode, step 7**, the definition of open becomes: "the `HIGH` and `MEDIUM` findings of every kind but outside that are not `MET`, are not an `OUTSIDE` with `decided`, and have no `owner` entry".
6. **lib/relay_verdict.py** (first-exempt; about 25 lines):
   - a review finding may carry `decided` (non-empty text); a check status may carry `decided` only with verdict `OUTSIDE`, and `relay check record check` refuses it, naming the field and the reason, on a finding of rank `high` or of kind `question` or `design`;
   - `open_of` does not count a finding whose verdict is `OUTSIDE` with `decided`;
   - `outside_of` counts such a finding as well as kind `outside` (today it counts by kind only, line 311), so the cycle's outside count tells the front to file it;
   - `relay check show` prints `decided:` under the finding; `relay check record` prints one line `decided: F<n> <text>` per decided finding, which the cycle (plugins/delegate/workflows/cycle.js) carries into the landed unit's result for item 8.
7. **lib/relay_queue.py `add_from`**: a finding that is a decided scope cut (kind `outside` with `decided` holding "scope cut", or a check status `OUTSIDE` with `decided`) is queued as kind `feature` whose `what` is the rest from `decided`; every other finding is a fix, as today. bin/relay's refusal of `--kind` with `--from` stays (the kind comes from the record, not the command). The ip: the front passes the parent item's ip with `--ip`, and `why` says "ip from the parent item (agent-chosen)" (principle 1 marks an IP an agent chose). Decided (owner can reverse): the parent's ip, because the owner ranked the whole of that work there; ip 0, the default for a front-filed feature, would drop the rest below every ranked feature. About 15 lines.
8. **plugins/front/skills/front/SKILL.md**, three lines:
   - where questions are handled: "A review's or a check's question is never a front decision: it reached you because the reviewer found no principle that settles it; ask the owner."
   - where outside findings are filed: "A decided scope cut is filed like any outside finding, `relay queue add --from <report.json> F<n> --input <why.toml> --ip <the parent's ip>`; the script makes it a feature."
   - the `merged:` line (about line 129): "when the landed unit carries `decided:` lines, add one line each: `decided without you (owner can reverse): <text>`."
9. **rules/principles.md**, principle 9, the end of the first sentence becomes: "a trade-off, a number, a scope cut that cannot be undone (a reviewer decides a reversible one and files the rest as a queue item)." Owner can reverse; the front names this edit in its report after the build.
10. **plugins/delegate/agents/fixer.md:157**: "A `Gap:` goes back to the coordinator; the checker decides one that is a reversible scope cut of a MEDIUM or LOW finding, the owner every other." roles/fix.md:29 ("your flow says who decides") stays right.
11. Then `relay sync` writes critic.md and checker.md; the paid run takes it as a rider.

### Tests that fail when a claim is false (tests/test_verdict.py, tests/test_queue.py)

- "Only a real choice is a question": `critic-decides-principle` and `critic-decides-scope-cut-ru` fail on today's text (shown before the change); `critic-asks-a-number` fails if the text over-decides.
- "A decided OUTSIDE is not open": F2 MEDIUM inside, verdict OUTSIDE, `decided` set: open 0, outside 1. Fails today: open 1, outside 0.
- "Never on a HIGH": F1 HIGH inside, verdict OUTSIDE, `decided` set: `relay check record check` refuses, naming `decided` and "rank high".
- "Never on a question or design": F3 MEDIUM kind question, verdict OUTSIDE, `decided` set: refused, naming the kind.
- "`decided` only with OUTSIDE" in a check: on a MET, GAP or NOT MET status: refused, naming the field.
- "An OUTSIDE without `decided` stays open": F2 MEDIUM inside, verdict OUTSIDE, no `decided`, no owner entry: open 1 (today's behaviour kept).
- "A scope cut's rest is a feature": `add_from` on an outside finding with `decided = "principle 9, scope cut: the Linux variant"` adds kind feature, what "the Linux variant"; on an outside finding without `decided`, kind fix (today's path kept). With a queue holding a feature at ip 96 and the filed rest at ip 70, the queue order puts the ip-96 feature first.
- "The owner sees each decision": a record with one decided finding → `relay check record` prints its `decided:` line; with none → no such line.

## 6. Part B: the front wakes itself

### Approaches

| | B0 do nothing | B1 timer started by the Stop hook | B2 B1 plus ending early on a lanes change | B3 Claude Code's `loop` skill on a fixed interval |
|---|---|---|---|---|
| mechanism | none | `relay wake` sleeps up to 55 minutes as a background Bash command; the Stop hook asks for one when none runs and work can move | B1 plus a git read of the lanes every minute | the front schedules a recurring prompt on itself; each fire needs no tool call |
| 25 Oct outage (163 min; every Bash call refused) | 163 min | at most one retry, at most 55 minutes after the last wake started, only if a wake was already running; none after it while commands fail, because re-arming needs a Bash call | same as B1 | a retry every interval while the outage lasts, if the schedule was set before it (not verified that it fires during such an outage) |
| a lanes change no agent announces | until the owner | up to 55 minutes late | about 1 minute | up to the interval |
| an agent that dies with no notification | until the owner | up to 55 minutes | same as B1 | up to the interval |
| cost per idle 7-hour night | 0 | 8 wakes, about $1.1 (2.9) | same, plus 420 lanes reads (0.7 s each, measured) | 8 or more; also fires while agents run and the owner talks |
| relay can test it | | yes (hook and command are relay's code) | yes | no: Claude Code's scheduling, outside relay's tests (principle 5); how long a recurring schedule lives is not verified |
| build | 0 | about 75 agent minutes | about 90 | about 20, text only |

What the timer is for, by measured case: the 25 Oct outage is covered by B1 only if the safety check recovered within 55 minutes of the last wake (recovery time unknown: 0 or 1 useful retries, review); B3 may cover it fully, not verified. Since D and C3, no idle gap over 43 minutes in 3 absences of up to 2 hours (2.1). Whether to build now or after a measured night is the open question (section 8).

### What is built, if B1 is chosen

1. **`relay wake --session <id>`** (new lib/relay_wake.py and a line in bin/relay's command table): writes `$RELAY_HOME/state/wake/<session>.json` with its pid and its end time, sleeps, removes the file, and prints one line: "Wake after <n> min: <the lanes line>. First start the next wake if the hook asks for one, before any other command; then look at the running lanes and the queue; when nothing can move without the owner, end the turn." (Re-arming first means an outage that begins mid-turn still finds a wake armed.) On SIGTERM it removes the file too. The session id is checked as `[A-Za-z0-9_-]+`. The sleep is a function `wake(session, seconds)`; the command turns the setting into seconds.
2. **The Stop hook** (plugins/front/hooks/lanes.py, Stop branch; the logic in relay_wake.py, since relay_lanes.py is at its 600-line limit). After `stop_hook_active` and the session check, as today:
   - *Work can move* when the lanes state has a pick, or a running lane with a queue item for which `relay_land_waits.held_words` and `relay_land_waits.unanswered` both return None (the same test `relay land` uses for "waits for the owner"). A lane on hold, a lane whose item has an unanswered owner question, and an itemless `wt/*` worktree are not work the front can move. A check-only question becomes a queue question before the owner sees it (front skill: "Before the question is shown, record it in the item it decides"), so `unanswered` covers it once asked; before that, asking it is the front's own work.
   - *A wake runs* when the session's wake file exists, its pid answers `kill -0`, and now is before its end time plus 2 minutes.
   - Work can move and no wake: refuse once with a reason that names the exact command: "No wake is running and work can move without the owner: start `relay wake --session <id>` with Bash run_in_background, then end the turn." When the lanes nudge also applies, both go in the one reason.
   - Nothing can move: no refusal, no wake; the owner's next message wakes the session.
   - Bound: `stop_hook_active`, as today: at most one refusal per turn end, never a loop. Fails open: any error or overrun of the hook's time budget prints nothing.
3. **Setting** `front.wake_minutes` in the project's `.claude/kit.toml`: default 55, bound 10 to 55. At 55: 8 wakes per idle 7-hour night, about $1.1; an agent that died unannounced is noticed within 55 minutes. At 10: 42 wakes, about $5.5, noticed within 10 minutes. Above 60 every wake re-writes the 1-hour cache (40 reads' worth), so 55 is the top. Out of bounds: 55, and the wake's line says the value was out of bounds.
4. **Front skill, Lanes section**: two sentences: the wake is the one background process the front keeps (the paid run aside); when the hook asks for it, start it first and end the turn; when it fires, look, act or end the turn. hooks.json description: add "and one refusal to start a wake when work can move and no wake runs".
5. Paid run: hook text is a rider. One eval case: the Stop refusal naming the wake → the front calls Bash with `run_in_background` true and `relay wake` (tool_used grader, min 1) and does not start a second one in the same turn (max 1).

### Cost while the owner is present
A turn that ends with movable work and no wake costs one more request and one Bash call the owner sees, once per 55 minutes. About $0.09 per hour present at the measured 221k median context.

### Tests that fail when a claim is false (tests/test_wake.py, temporary folders only, never the live state)

- No wake file, a running lane whose item has no hold and no unanswered question, `stop_hook_active` false → a refusal naming `relay wake --session <id>`. Fails today: no refusal.
- A live wake file (own pid, end time in the future) → no refusal.
- A wake file whose pid is dead, or whose end time passed 2 minutes ago → refusal.
- One running lane, the owner's hold recorded on its branch, no pick → no refusal.
- Every running lane's item has an unanswered owner question and no pick → no refusal.
- An itemless `wt/*` worktree inside `lane_quiet_hours` as the only lane, no pick → no refusal.
- `stop_hook_active` true → no refusal, whatever the state.
- Both rules apply → one refusal whose reason names the pick and the wake.
- `wake(session, 0.05)` called directly (the test seam; the bound applies only where the command reads the setting) → the file exists while it sleeps and is gone after; the line holds the lanes line. SIGTERM → the file is gone.
- `wake_minutes` 70, and `wake_minutes` 5 → 55 used, and the line says the value was out of bounds.

## 7. Order and size

1. Part A eval cases, shown failing on today's text (`critic-decides-principle`, `critic-decides-scope-cut-ru`); 20 minutes.
2. Part A texts (judge review part, severity line, check steps 6 and 7, principle 9 clause, fixer line, front skill lines); 40 minutes.
3. Part A code: `decided` field, guard, `open_of`, `outside_of`, record and show output, cycle carrying `decided:` lines into its result, `add_from` feature path, tests; 70 minutes.
4. Part B, only if the owner picks it now (section 8): command, hook rule, setting, tests, skill text, eval case; 75 minutes.

Part A about 130 agent minutes; with part B about 205, against the item's 2 hours: the item's time needs raising (a front step, `relay queue edit`). One paid-run rider (judge text, principle 9, fixer line, front skill, and the hook text when part B is in). The item's `where` should name every file above: roles/judge.md, rules/principles.md, plugins/delegate/agents/fixer.md, lib/relay_verdict.py, lib/relay_queue.py, plugins/delegate/workflows/cycle.js, plugins/front/skills/front/SKILL.md, evals/plugin/, and for part B lib/relay_wake.py, bin/relay, plugins/front/hooks/lanes.py, plugins/front/hooks/hooks.json.

Combined effect, estimated (not measured): on a night like 29 Oct the four questions do not wait (3 become inside fixes, 1 an outside feature item) and free lanes take startable work (C3).

## 8. Open for the owner

**Build the self-wake now, or after one measured night**
When every agent has finished and the front has ended its turn, nothing restarts work until you write. A small timer would wake the front after at most 55 minutes so it looks again. Since the two fixes of 30 Oct your three absences of 80 to 120 minutes had 7 to 9 commits each, and the front never sat idle over 43 minutes; a whole night has not been measured yet. The one measured case the fixes do not cover is 25 Oct: Claude Code's safety check refused every command, the front promised to retry "at the next event", none came, and it stood 163 minutes until you wrote "Продолжай". The design review found the timer helps there less than first said: restarting the timer itself needs a command, so while commands are refused it retries once at most, and that one retry helps only if it falls after the check recovered (when it recovered is not known). Revision 1 recommended building now on that case; this evidence moved the recommendation.

| | build cost | cost per idle night | the 25 Oct kind of outage | if tonight goes idle |
|---|---|---|---|---|
| a. measure tonight first (recommended) | 0 now; about 75 agent minutes later, only if tonight shows an idle gap over 55 minutes | $0 until then | not covered | one more idle night is the measurement |
| b. build the timer now | about 75 agent minutes, in this item's paid rider | about $1 (8 wakes) | at most one retry | the timer is not ready tonight either; it is from the next night on |

- a. Measure tonight first: rests on 2.1 (no idle gap over 43 minutes in 3 absences since the fixes) and on the review's reading of 25 Oct (the timer gives that case 0 or 1 useful retries).
- b. Build now: also covers an agent that dies without a notification and a lanes change nobody announces, each up to 55 minutes late; neither is measured as having happened since the fixes.

If the outage case is what you want covered, only Claude Code's own recurring prompt (B3) fires without a command; whether it fires while the safety check fails is not verified, and relay cannot test it. That would be a probe first, not a pick now.

## 9. What the brief could not settle

- Cost of the three eval cases per run: not measured.
- When the 25 Oct safety check recovered between 06:12 and 08:55: not in the transcript.
- Whether Claude Code's recurring prompt fires during a safety-check outage, and how long a recurring schedule lives: not verified.
- The GAP counts in 2.7 are the reviewer's; the `.relay/checks/*.json` files in the main checkout hold only open and queued counts, so I could not recount them.

## 10. What changed after the review

The design review of 30 Oct (artifact review, 8 findings and two remarks) is not kept anywhere else; each finding, whether it held, and the fix:

| finding | held? | fix |
|---|---|---|
| F1 HIGH: the check-stage `decided` had no bound, so a checker could close a HIGH inside finding or a reviewer's question and the change would merge | held | Step 6 (section 5 item 4) limits `decided` to a reversible scope cut of a MEDIUM or LOW finding not of kind question or design; item 6 adds the code guard (`relay check record check` refuses `decided` on rank high or kind question/design); tests for the HIGH, question and MEDIUM cases. The review text also says a scope cut never defers a defect. The 29 Oct Gap was MEDIUM inside (2.7), so 4 of 4 still holds; of the 17 stored HIGH/MEDIUM GAPs, at most 4 become eligible. |
| F2 MEDIUM: B1 does not retry the 25 Oct outage at 55 and 110 minutes; re-arming needs a Bash call, which the outage refused | held | The B1 row now reads "at most one retry, only if a wake was already running"; B3 is compared on that row; the wake's line tells the front to re-arm first. The owner question's recommendation moved from "build now" to "measure tonight first", naming this evidence. |
| F3 MEDIUM: the grader `Decided: principle` failed a critic that followed the text's other prefix `Decided: scope cut, principle <n>`; the case mixed both paths | held | The decision is now a structured `decided` field with one form, `principle <n>...`, read by a regex grader; the fixtures are split so each applies one path (`critic-decides-principle`, `critic-decides-scope-cut-ru`). |
| F4 MEDIUM: the rest of a scope cut filed with `relay queue add --from` became a fix item, jumping above every feature | held | `add_from` queues a decided scope cut as a feature whose `what` is the rest, with the parent's ip marked agent-chosen; other findings stay fixes; test with an ip-96 feature ranking first. |
| F5 LOW: the test with `wake_minutes` 0.02 contradicted the 10-55 bound | held | The test calls `wake(session, seconds)` directly; the bound applies only where the command reads the setting; tests for 70 and 5. |
| F6 LOW: judge.md step 7's definition of open, the severity line "no deferral", and the fixer's "a Gap goes back to the coordinator, who asks the owner" still stated the old rule | held, with one correction | Items 3, 5 and 10 edit the three lines. The fixer's line is in plugins/delegate/agents/fixer.md's own part, not in roles/fix.md (whose "your flow says who decides" stays right), so the `where` list names fixer.md. |
| F7 LOW: "agent work exists" counted a held lane, an itemless worktree and a check-only question, so the wake would fire all night for nothing | held | "Work can move" reuses `relay land`'s owner-wait test (`held_words`, `unanswered`) and leaves out itemless worktrees; a check-only question is recorded on its item before the owner sees it, so `unanswered` covers it. Three tests added. |
| F8 LOW: nothing brought the reviewer's decisions to the owner, against principle 9's "report after" | held | `relay check record` prints a `decided:` line per decided finding, the cycle carries them into its result, and the front's `merged:` line lists each as "decided without you (owner can reverse)"; one test. |
| Remark: `outside_of` counts by kind, not verdict | held | Item 6 makes `outside_of` count an `OUTSIDE` with `decided` too. |
| Remark: principle 9 is the owner's text | held | Section 4 and item 9: the front names the edit in its report after the build. |
