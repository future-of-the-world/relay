# Design: speed up the quick gate (revision 4, after the design review of 30 Oct)

Queue item `speed-up-the-quick-gate` (feature, IP 95). Worktree `~/relay/.worktrees/speed-up-the-quick-gate`.
Measured 29-30 Oct 2026, load average 13-21 on the 12-core Mac. Scripts and their output: `scratchpad/sqg/` (gates.py,
moves.py, landings3.py, landings4.py, landings5.py and their logs, land-events.log, logs/copy-tests.log).

Terms used below:
- **quick gate**: `bin/ci --quick` started by `relay gate`; its green log lets a change land.
- **inert files**: `docs/handover.md`, `.relay/queue/**`, `.relay/checks/**`, `.relay/changes/**` (lib/relay_inert.py).
  They are state, not code; relay treats a commit that changes only them as "no code change".
- **inert probe** (today): a second full quick run, beside the first, in a temporary worktree where every inert file has
  a line appended and junk files are planted; the `inert` step fails when the two runs' outcomes differ.
- **reuse**: `relay gate` does not run when a green log exists for an earlier commit and only inert files changed since
  (lib/relay_gate_logs.py `reusable`). The merge hook (`step_gate`) and `relay land` accept such a log the same way.
- **take**: `relay land` merges master into the branch before gating; **land lock**: one landing at a time per repository.
- **inert move**: master moved during a landing's gate by commits that changed only inert files; today `relay land`
  retakes and reuses the gate in seconds (`inert_moves` in its events).

## 1. What is decided and what is already done

| # | Decision | Who, when | State |
|---|---|---|---|
| D1 | Real git first on PATH through a link the front lays: "Хорошо, положи ссылку на гит, но скажи что именно и куда ты собираешься положить"; then the plain link: "на 60000 команд 7 мс это почти 7 минут теста" | owner, 29 Oct 08:33 / 08:38 | done on this Mac: `~/.local/bin/git`, `~/.local/libexec/git-core`, `~/.local/share/git-core` link into Xcode's git; 20.9 -> 6.6 ms per call. Verified 30 Oct: `which -a git` gives `~/.local/bin/git` first |
| D2 | Option a of that question also promised "relay doctor предупреждает, если посредник снова первый" | owner chose a, 29 Oct | not built |
| D3 | No second test run: "Хорошо, убираем второй прогон", to the option "Убрать второй прогон сейчас, лимит 25 минут" whose question said the result then counts only over the gate's own records, at "около 12 лишних проверок в день" | owner, 29 Oct 11:59 | to build; the price of the "own records" mechanism was wrong (section 4.2), the mechanism is asked again (section 6) |
| D4 | Quick limit 1500 s in the same change ("30 минут сейчас, 25 после ускорения") | owner, 29 Oct | to build |
| D5 | No macOS sandbox, no Linux fence in this change; the Linux gate in podman is the future ("в моих планах полностью переехать на Linux") | owner 29 Oct 10:41-10:45; front decided "no Linux fence" inside the principles | settled; the podman gate is a separate item |
| D6 | Adaptive number of gates per machine: separate item | owner, 29 Oct | out of scope |
| D7 | Measure RELAY_TEST_JOBS 4 against 6 with two gates at once | item text | to do after D3 lands |
| D8 | The one run happens on a copy of the gated tree without the inert files (B2); reuse stays | recommended by this design, 30 Oct; it changes the mechanism of the option the owner picked, so it is the owner's (section 6) | asked |

## 2. Measured now

| What | Number | Source |
|---|---|---|
| Quick gates before the git link (23-29 Oct) | n=555; total median 911 s, p90 1560 s; library step median 474 s; wait for the probe at the `inert` step median 259 s, p90 757 s; 80 over 1500 s | gates.py over committed gate logs |
| Quick gates after the link (29 Oct 04:38Z - 30 Oct 11:11Z) | n=209; total median 748 s, p90 1034 s, max 1785 s; library step median 708 s; probe wait median 9 s, p90 123 s; 4 over 1500 s | same |
| Why the library step got slower after the link | the test tokens (machine-wide worker pool, landed 29 Oct 15:45) split a gate's 4 tokens 2 + 2 between the run and the probe (tests/parallel_unittest.py `probe_share`), so each run has half the workers and they finish together | code read |
| Gates per day | 209 logs in 30.5 h, about 160 per day (red ones included) | same |
| Code landings since 27 Oct | 168 in 87 h (about 46 per day) | landings3.py over master's reflog |
| What lay between a landing and its deciding green gate (all 163 code landings with a green quick gate) | queue, handover or changes files: 115; only check records or nothing: 48. Of the 115: 107 through a take of master, 8 through the branch's own commits only | landings3.py, landings4.py |
| `relay land` landings (28 Oct 17:40Z - 30 Oct 11:13Z, events.jsonl) | 66 landed; 48 ran a gate, 18 reused it after an inert take; 44 inert moves in all | land-events.log |
| **Chance that master moves by inert files during a landing's gate** | **37 of 48 gates run inside `relay land` (77%)**; median gate 908 s | land-events.log |
| What the takes after the deciding gate brought (`relay land` landings) | 60 takes, every one with queue, handover or changes files; 0 with check records only. 55 of 66 landings had such a take or an own queue/handover commit after the gate | landings5.py |
| master commits since 27 Oct | 521: 131 code, 172 check records only, 193 queue only, 9 handover only, 16 mixed inert | moves.py |
| Tracked files | 3,067, of which 2,124 inert (69%) | `git ls-files` |
| Writing a full copy of the tree | 0.98 s (`git archive HEAD` into a folder, load 13.6) | measured |
| **Library tests on a copy of master's head (e86073da) with the inert files deleted and committed** | **0 red of 2,308, 0 skipped**, 1,050 s with 4 workers at load 16-21; the copy's tree stayed clean (no test wrote an inert file into it). Run with RELAY_QUICK=1 as the gate does, plain runner without coverage; the grader tests and plugin validate steps were not run on it | logs/copy-tests.log, 30 Oct, started 15:40 local |
| Places that read an inert file of the live repository at an older commit | 1: tests/test_queue.py:383-386 `read_ref` reads `HEAD^` when HEAD's subject is "inert probe" (written for today's probe; the only caller on ROOT reads `.relay/README.md`, not inert). Every other `HEAD~`/`HEAD^` in tests and lib is in a temporary repository | `git grep -E "HEAD[~^]" -- tests lib` |
| Static guard already in the suite | tests/test_no_live_queue_reads.py flags a test line that names ROOT and a queue path without a pinned commit; it covers the queue only, not the handover or check records, and not lib code under test | code read |

The 15-17% "chance of a master move in a gate-long window" of revision 3 (moves.py) is withdrawn: it averaged queue and
handover commits over all hours, while landings happen in the busy ones. The direct count in `relay land`'s own events
is 77%.

## 3. Part A: the git launcher, what is left

The link is laid (D1). Left:

1. **docs/macos.md section 1 gives a recipe that breaks git.** It tells the reader to symlink `xcrun --find git` into
   `~/.local/git-bin`. The front measured on 29 Oct that git started through a bare symlink looks for its helpers and
   its built-in config next to the link (`~/.local/libexec/git-core`, missing): `git init` then makes `master` instead
   of `main` and no hook templates, submodule and the keychain credential helper fail. This is a defect inside this
   item's "Where" (docs/macos.md:30): the section is rewritten with the three links actually laid (bin, libexec/git-core,
   share/git-core) or `brew install git`, and the numbers of 29 Oct (20.9 against 6.6 ms per call; 51,000-61,000 git
   starts per library run; 1225 s against 720 s).
2. **The doctor line (D2).** On macOS only, `relay doctor` gets one machine check, "git first on PATH is the real git":
   not ok when the first `git` on PATH resolves to `/usr/bin/git` (Apple's launcher), and not ok when `git --exec-path`
   names a folder that does not exist (the broken-link case of point 1). The detail names the fix: docs/macos.md
   section 1. Linux: the check is not shown (the distribution's `/usr/bin/git` is the real one). Doctor has no warning
   level today (`(name, ok, detail)` only), and nothing found by grep runs doctor as a blocking step, so a not-ok line
   is the warning. Tests that fail when it is false: a PATH whose only git is a fake `/usr/bin/git` path gives not ok;
   a fake git whose `--exec-path` folder is missing gives not ok; a fake real git gives ok; on a non-Darwin platform
   value the check is absent.

Nothing else in Part A: relay's code does not pick git itself (the owner's 27 Oct decision, kept by D1).

## 4. Part B: one test run instead of two

### 4.1 What the second run bought

Reuse says "this green log also stands for a commit that differs only in inert files". The probe is what makes that
true: it showed, gate by gate, that no outcome changed when every inert file changed. Without it, reuse across queue
and handover commits is a claim nobody checks. So removing the probe (D3) needs one of two things: stop reusing across
those files, or make the one run unable to see them.

### 4.2 Approaches

**B0. Do nothing.** Two runs per gate. Cost: half of every gate's CPU; with tokens split, each run gets 2 workers
instead of 4 (library step median 708 s after the split against 474 s before it). Keeps the only live detector (1 real
case in 523 gates, 25 Oct) and reuse. Rejected by the owner (D3); listed for the comparison.

**B1. One run on the real tree; reuse only across relay's own records** (the mechanism the 29 Oct question described).
The gate runs once, as today's outer run. `reusable`, `tree_moved` and the merge hook's `step_gate` stop accepting a
log when a queue item, the handover or a `.relay/changes` record changed after it. This is how merge queues work
(GitHub merge queue, bors, GitLab merge trains): what is tested is exactly what lands, and any change of the base
re-tests.
- Gains: the verdict is about the exact tree that lands. Fewest parts: the Probe class, the `inert` step,
  lib/relay_ci_probe.py, `probe_share` and the two RELAY_INERT_* variables go (about 190 lines of code, plus their tests).
- Costs, measured over `relay land`'s 66 landings (section 2): every landing runs at least one gate (the 18 reuses
  become runs: their takes all brought queue files), and 77% of gates see master move by queue or handover commits
  before they end, each move costing another whole gate under B1. A landing then runs on average 1 / (1 - 0.77) =
  about 4.3 gates instead of today's 48 / 66 = 0.73, inside the land lock: about 65 minutes of lock per landing at the
  908 s median gate. At 46 code landings a day that is about 50 hours of lock a day, so ready changes pile up without
  end; at the bound `land_inert_tries` = 10 a landing hands back with chance 0.77^10, about 7%, and starts over.
  The arithmetic: 4.3 - 0.73 = about 3.6 more gates per landing x 46 landings a day = about 165 more gates a day,
  against today's about 160. The 29 Oct question gave "около 12 лишних проверок в день"; revision 3 gave "около 20".
  Both rested on the wrong window (section 2, last paragraph).
- Variant B1-own (review F5): reuse only across the gate's own log commit instead of any check record. It makes no
  measured difference: 0 of the 60 takes after a deciding gate brought check records alone.
- Weak spot besides cost: a test that reads a live inert file of the tree is never found by design; it shows only when
  a queue edit turns it red later, as a "flaky" gate.
- If B1 were ever built, the merge hook's `step_gate` (plugins/relay/hooks/merge.py:358-375) must walk like
  `finished_red` too (review F1), or a merge outside `relay land` would accept a green log with queue commits after it.

**B2. One run on a copy of the tree without the inert files** (Bazel and Nix work this way: an action sees only its
declared inputs, and its cached result is keyed on those inputs alone). Under `relay gate`, bin/ci makes a temporary
worktree of the gated commit, deletes every inert file in it, commits that as "gate copy" (parent: the gated commit;
never "inert probe", review F6), and runs the free steps there once: types and lint, plugin lib links, library tests,
hook tests, eval grader tests, plugin validate. Two commits that differ only in inert files produce the same copy, byte
for byte (the same git tree), so a green log of one is a true result for the other, by construction rather than by
comparison. Reuse, `tree_moved` and the merge hook's `step_gate` stay as they are (review F1, pass case 4).
- What runs where (review F3 and F7): the copy is only the working folder (cwd, and the root the steps read) of the free
  steps. Everything bin/ci writes stays in the real worktree: `.ci/steps/*.log`, `.ci/results.txt`, the time-limit
  message's log path, the gate log. So a gate stopped at its limit or killed by `relay gate` leaves this gate's own step
  logs where the message points; there is no copy-back. The paid part of a full run (clean-image gate, plugin evals,
  the eval `record()` and `note_paid_start`) runs on the real worktree after the copy is removed, exactly as today, so
  the eval record names the real branch and head. The paid steps were never covered by the probe either (its nested
  run was always quick); nothing about them changes.
- The copy's environment has no RELAY_GATE (as the probe's nested run has none today, lib/relay_ci.py:157), so a test
  cannot find the gated commit's sha from the environment (review F8).
- Gains: reuse after queue and handover takes stays (no extra gates, no longer land lock); a test that opens a live
  queue item, the handover or a check record of the tree finds nothing and goes red, so the 25 Oct kind of defect is
  found on the first gate instead of by chance. Works the same in the future podman gate on Linux (D5): the copy is
  what gets mounted, and the 29 Oct container finding (`git show HEAD:docs/handover.md` gave 175,055 bytes) is closed
  for HEAD.
- Holes, named: the copy's parent is the gated commit in the shared `.git`, so `git show HEAD~1:docs/handover.md` still
  gives the real handover (review F8); so do a moving ref (`master:.relay/queue/...`), another checkout of the
  repository, and relay's own lib code, which finds the main checkout from any worktree through the shared `.git`
  (lib/relay_land.py, relay_queue). Today's probe and B1 have all of these too except the first. The static guard
  (tests/test_no_live_queue_reads.py) grows to the handover and check records and to `HEAD~`/`HEAD^` reads of inert
  paths in tests, which closes the parent hole for test code (today 0 such reads, section 2).
- Considered and not taken: a parentless copy (`git commit-tree` with no parent) would close the parent hole for lib
  code too, but tests that walk ROOT's history would break (how many: not measured); the guard closes the hole where a
  read has been found so far (tests), at no risk.
- Costs: the copy, about 1-2 s per gate (0.98 s measured for writing the whole tree; the copy writes 31% of it); the
  probe's worktree code stays in a smaller form (about 80 lines kept, where B1 removes about 190; the leftover cleanup
  in lib/relay_ci_probe.py stays, renamed in its texts); failing paths inside test output point into the copy.
- Tests that need an inert file to be present: 0 of 2,308, measured on a copy of master's head (section 2). A test that
  later goes red only because the files are absent reads live state, which the project's Python rules forbid ("Tests
  use a temporary folder and never touch the live .relay/queue, .relay/checks or docs/handover.md"), so it is a defect
  fixed where it is found.

**Rejected on the way:** keeping the probe's "append a line" form for the single run. Its tree still holds the real
content plus one line, so two commits that differ in a queue item give two different copies; reuse would be unproven
again. Only deletion makes the copies identical.

### 4.3 How leading tools solve it

| Tool | What decides that a result still holds | Matches |
|---|---|---|
| GitHub merge queue, bors, GitLab merge trains | the exact merged tree is tested; any base change re-tests. They keep that affordable because the base moves only by merges that went through the queue; relay's master also moves by direct queue and handover commits, about one every 10 minutes in landing hours (77% per 15-minute gate) | B1 |
| Bazel, Buck2, Nix | the action runs in a sandbox that holds only declared inputs; the cache key is their digest | B2 |
| Turborepo, Nx | the task hash covers declared input globs; nothing stops a task reading other files | today's inert list without the probe (unproven) |
| GitHub Actions `paths-ignore`, GitLab `rules: changes` | a change of listed paths skips CI by declaration | same, no proof |

### 4.4 Critique of the owner's pick (said once)

The pick D3 is right on CPU: 2 runs per gate become 1. Its weak spot was the price it was shown with. The 29 Oct
question priced "the result counts only over its own records" at about 12 extra gates a day; measured in `relay land`'s
own events it is about 3.6 extra gates per landing, about 165 a day, every one inside the land lock (section 4.2, B1).
At that price the mechanism of the chosen option cannot carry 46 landings a day. The pick itself, "убираем второй
прогон", stands; only the mechanism behind its wording changes.

### 4.5 Recommendation (D8, asked in section 6)

B2. Rests on: the 77% measured chance of an inert move per landing gate (37 of 48) and the 60 of 60 takes that brought
queue files, which make B1 cost about 4.3 gates per landing against about 1.0 for B2; principle 1 (correctness first:
B2 also finds a test that reads live state on its first gate) and principle 2 (waste: B1 would rerun about 165 gates a
day that change nothing). The owner chose to remove the second run, not to pay 165 gates a day for it; B2 is the only
measured way to honour both D3 and the 46 landings a day, and the copy turned no test red (0 of 2,308). It is still
asked, not decided: the option the owner picked on 29 Oct described B1's mechanism, and changing what an owner's answer
said is not inside the recorded decisions.

Where B2 is weak, said once: it keeps reuse across queue and handover commits, which is wider than the 29 Oct option
text ("только поверх её собственных записей"); it keeps about 80 lines of worktree code that B1 would delete; and its
correctness rests on deletion being complete, which the test of section 5.1 ("copies of two commits that differ only
in inert files are the same tree") proves on every build.

## 5. Build plan (B2)

1. Remove the second run: `Probe` as a parallel nested run, the `inert` step and its comparison (`outcome` in
   lib/relay_ci_lines.py has no other caller in lib, bin or tests: it goes too; the "called by other programs" remark at
   lib/relay_ci.py:42 is stale), `probe_share` (the one run gets the gate's whole token share), RELAY_INERT_PROBE and
   RELAY_INERT_FULL_HOOKS, the guard-suite remark in lib/relay_coverage.py:81-83, the class-times rule "only the outer
   run writes" (now: the run writes). In tests/test_queue.py, `read_ref`'s "inert probe" branch (lines 383-386) and the
   test of the probe commit (`test_the_seed_items_are_read_from_before_the_inert_probe_commit`, near line 553) go;
   `committed_text(ROOT, ".relay/README.md")` (line 513) keeps reading the README, which is not inert.
2. The copy: Probe becomes `GateCopy`. Under RELAY_GATE: make a detached worktree of the gated commit in a temporary
   folder, delete every tracked path that `relay_inert.matches`, commit as "gate copy" with `--no-verify`, run the six
   free steps with cwd and the step root at the copy and RELAY_GATE removed from their environment; `.ci/` and the gate
   log are written through `Ci.path()` at the real root (no copy-back); remove the worktree and the folder in the same
   `finally` that ends the free steps, before any paid step. The leftover record and cleanup of lib/relay_ci_probe.py
   stay (relay gate's SIGKILL leaves no time for `finally`), renamed in their texts.
3. Full mode (`relay gate --paid`, the front's plain `bin/ci`): the free steps as in step 2 when RELAY_GATE is set;
   the paid steps (clean image, plugin evals, `record()`, `note_paid_start`) on the real worktree, unchanged. A plain
   `bin/ci` without RELAY_GATE makes no copy, as today it makes no probe.
4. The first build step is one quick gate on the copy before any other change, to confirm the 0 red of section 2 on
   the build's base (master moves; the grader tests and validate were not in the measurement). A test it turns red
   is fixed to read a temporary folder or a pinned commit. Bound (a setting of this plan, not of the code): up to 10
   such tests are fixed here; above 10 the build stops and the count comes back as a scope question. At the bound 0
   any red test stops the build; at a high bound this change grows by one test fix each (about 5-10 agent minutes per
   test, not measured). Expected: 0, from the measurement.
5. tests/test_no_live_queue_reads.py grows to the handover and check records and to `HEAD~`/`HEAD^` reads of inert
   paths of ROOT.
6. QUICK_LIMIT_SECONDS 1800 -> 1500 with its test (D4). Bound: RELAY_CI_QUICK_LIMIT, whole seconds >= 1. At 1500,
   measured after the link: 4 of 209 gates ran over 1500 s, all with the probe beside them; expected 0-2 per day
   without it (not measured). Outcome at the bound: the gate stops itself, exit 124; `relay land` hands back once, and a
   second stop on the same code is red ("a hang, not load").
7. The gate's last line, replacing "inert: skipped (runs under relay gate)": "ran on a copy without queue, handover and
   check records; covers every commit with the same code".
8. docs: docs/plans/review-gate.md section 12.6 and the tables at lines 51 and 183 describe the probe; they are
   rewritten. The lib/relay_ci.py module text (lines 17-22) likewise.
9. Part A (section 3): docs/macos.md section 1, the doctor check.

After it lands (D7):
10. Jobs 4 against 6: a runner starts pairs of quick gates at once on master's head (`relay gate --again`), per-gate
    tokens 4 then 6 (setting file `per-gate`, bounds 2-8) with RELAY_TEST_JOBS equal, interleaved, 3 pairs each;
    it records the library step's seconds and reds. About 60 min of both gate slots; run when no lane is gating.
    Default moves to 6 only when the pair median is at least 10% shorter and no new test goes red (setting: the 10%
    threshold; at 0% any gain moves it, at the bound 8 tokens two gates take 16 workers on 12 cores, which the
    27 Oct numbers already showed slower: 3 gates at once 1058 s each against 698 s for 2). The number goes into this
    queue item the same turn.

### 5.1 Tests that must fail when a rule is false

| Rule | Test |
|---|---|
| A gate under `relay gate` runs the test suite once | a gate fixture whose fake test runner appends a line per start to a file: exactly one line (today two) |
| The one run has the gate's whole token share | the share function gives 4 of 4 (today 2) |
| Limit is 1500 | QUICK_LIMIT_SECONDS == 1500 and `quick_limit({})` == 1500 |
| No test sees an inert file | a fixture test that opens ROOT's `docs/handover.md`, one that lists `.relay/queue`, one that runs `git show HEAD:docs/handover.md`: each makes the fixture gate red |
| The copies of two commits that differ only in inert files are the same tree | `git rev-parse <copy>^{tree}` equal for both |
| The copy has no RELAY_GATE | a fixture test that prints the variable: empty in the copy |
| The copy's commit is not "inert probe" | its subject is "gate copy" |
| The copy is removed on every way out | a gate stopped at its limit and a gate ended by SIGTERM leave no worktree and no temp folder; a SIGKILLed gate's leftover is removed by the next gate of that worktree |
| Step logs are this gate's on every way out (review F7) | a gate stopped at its limit during library tests: `.ci/steps/library-tests.log` in the real worktree holds this gate's output; a green gate: `.ci/results.txt` is this gate's |
| Paid records name the real branch (review F3) | `relay gate --paid` fixture on `wt/x` at G: the eval record names `wt/x` and G, never the default branch, never the copy's sha; a plain `bin/ci` on a detached master head records master and that head (works today, must keep) |
| Reuse across inert commits still works and the merge hook is unchanged | a green log at G, then a commit editing `.relay/queue/x.json`: `reusable` gives the log; `step_gate` accepts; a code commit after G: both refuse (works today, must keep) |
| Doctor (Part A) | section 3, point 2 |

## 6. Open for the owner

**Как сделать единственный прогон тестов независимым от очереди и handover**

Перед каждым merge relay запускает проверку (gate). Сейчас она гоняет все тесты дважды: второй раз с испорченными
служебными файлами (очередь задач, handover, записи проверок), чтобы доказать, что результат от них не зависит.
Только поэтому зелёная проверка засчитывается снова, когда после неё в master пришёл лишь commit очереди. 29 Oct вы
решили убрать второй прогон; вопрос тогда говорил, что проверка будет действовать только поверх своих записей, ценой
около 12 лишних проверок в день. Эта цена оказалась неверной. Замер 30 Oct по 66 merge через `relay land`: в 37 из 48
проверок (77%) за время проверки (около 15 минут) в master приходил commit очереди или handover. При «только точном
дереве» каждый такой commit требует новой проверки, и новая с той же вероятностью снова устаревает: в среднем 4.3
проверки на один merge вместо 0.73 сегодня, около 165 лишних в день, и около 65 минут, пока остальные готовые
изменения ждут своей очереди на merge. При 46 merge в день это больше 24 часов ожидания в сутки. Другой путь: тесты
идут на копии дерева, где служебных файлов нет вовсе; тогда два commit, различающиеся только очередью, дают одну и ту
же копию, и проверку можно честно засчитать снова. Замер: на такой копии master все 2,308 тестов зелёные.

| | a. Копия без служебных файлов | b. Только точное дерево (как в вопросе 29 Oct) |
|---|---|---|
| Как работает | тесты идут на копии, где нет очереди, handover и записей проверок | тесты идут на настоящем дереве; commit очереди или handover после проверки требует новой |
| Проверок на один merge | около 1 (как сегодня без второго прогона) | около 4.3 (замер: 77% проверок устаревают за время прогона) |
| Лишние проверки в день | 0 | около 165 |
| Ожидание в очереди на merge | как сегодня | около 65 мин на каждый merge |
| Тест, читающий живую очередь (как 25 Oct) | краснеет на первой же проверке | не виден, всплывёт позже как flaky |
| Цена | 1-2 с на проверку; около 80 строк кода остаются; 0 тестов чинить (замер) | около 190 строк кода удаляется |
| Чего не видит | чтение родительского commit (сегодня 0 мест в тестах), master и других checkout | master и других checkout |

- a. Копия без служебных файлов (рекомендация: лишних проверок нет, очередь на merge не растёт, тесты уже готовы; так работают Bazel и Nix; та же копия пойдёт в будущую проверку в podman на Linux)
- b. Только точное дерево (проще по коду, но около 165 лишних проверок в день)

## 7. What the brief could not answer

- The gate's length without the probe: not measured (estimate: the library step near its pre-token median of 474 s,
  because the one run gets all 4 workers back).
- Whether the 77% chance of an inert move holds when gates get shorter: a shorter gate is a shorter window, so it
  should fall; it does not matter under B2, where an inert move costs seconds.

## 8. What changed after the review

The design review of revision 3 (8 findings, 5 MEDIUM, 3 LOW) and what became of each. The review is not kept elsewhere.

| Finding | Held? | Fix in this revision |
|---|---|---|
| F1 (MEDIUM) B1's plan changed `reusable` and `tree_moved` but not the merge hook's `step_gate`, which would still accept a green log with queue commits after it | Held, for B1 | B1's text says `step_gate` must walk like `finished_red` if B1 is ever built; B2 says `step_gate` stays, and section 5.1 has a test that it is unchanged. B1 is no longer recommended (F2), so its build steps are dropped from the plan |
| F2 (MEDIUM) B1's "about 20 extra gates a day" rested on 18 of 78 `relay land` reuses, while landings3 showed 115 of 163 landings relied on inert reuse | Held, and both numbers were too low | Measured directly in `relay land`'s events: 77% of its gates (37 of 48) saw master move by inert files; every one of the 60 takes after a deciding gate brought queue or handover files. B1 costs 1 / (1 - 0.77) = 4.3 gates per landing against 0.73 today: 3.6 x 46 = about 165 more a day. The 115/163 count covers all landings since 27 Oct, most made before `relay land` existed (28 Oct) through the merge hook; `relay land` is the path every landing takes now, so its events are the base; 115/163 = 71% points the same way. Section 2, 4.2, 4.4 and the owner's table use the one number |
| F3 (MEDIUM) B2 ran every step in the copy, so `relay gate --paid` would file the eval record as the default branch at the copy's sha | Held (traced by reading) | The copy holds the six free steps only; the paid steps (clean image, evals, `record()`, `note_paid_start`) run on the real worktree after the copy is removed, as today. Test row "Paid records name the real branch" |
| F4 (MEDIUM) how many tests need the inert files present was left to the build though one run measures it | Held | Measured: library tests on a copy of master's head without the inert files, 0 red of 2,308, 0 skipped (section 2). The bound of 10 stays as a guard for the build's base; the owner's table says 0 |
| F5 (MEDIUM) B1 reused across any `.relay/checks/` change while D3 was worded as "only over the gate's own records" | Held as an inconsistency of the text | Named as variant B1-own; measured to make no difference (0 of 60 takes brought check records alone). B2 is wider than the 29 Oct wording (it reuses across queue and handover too): said in 4.5 and the reason the question goes back to the owner |
| F6 (LOW) "0 places read an inert file at HEAD~n" missed tests/test_queue.py:383-386 `read_ref`, which reads `HEAD^` when HEAD's subject is "inert probe" | Held | Section 2 row corrected (`HEAD~` and `HEAD^`, the one place named); build step 1 removes `read_ref`'s probe branch and its test; the copy's commit is "gate copy", with a test |
| F7 (LOW) the copy-back of `.ci/` would not run when the gate stops at its limit or is SIGKILLed, leaving the previous gate's step logs | Held | No copy-back: `.ci/` and the gate log are written at the real root through `Ci.path()`; only cwd and the step root point at the copy. Test row "Step logs are this gate's on every way out" |
| F8 (LOW) "the container leak is closed" overstated B2: `git show HEAD~1:docs/handover.md` still gives the handover | Held | Reworded to "closed for HEAD"; the parent, a moving ref, other checkouts and lib code that finds the main checkout are named as holes; RELAY_GATE is removed from the copy's environment, with a test; a parentless copy was considered and not taken (4.2) |

Also from the review's notes (not a finding): relay's own lib finds the main checkout from any worktree, so lib code
called with the copy's root can still read the live queue. Named among B2's holes; today's probe and B1 share it.
