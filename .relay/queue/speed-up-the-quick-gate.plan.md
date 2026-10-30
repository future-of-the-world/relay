# Design: speed up the quick gate (revision 3, after the owner's answers of 29 Oct)

Queue item `speed-up-the-quick-gate` (feature, IP 95). Worktree `~/relay/.worktrees/speed-up-the-quick-gate`.
Measured 30 Oct 2026, load average 13-15 on the 12-core Mac. Scripts and their output: `scratchpad/sqg/` (gates.py,
moves.py, landings3.py and their logs).

Terms used below:
- **quick gate**: `bin/ci --quick` started by `relay gate`; its green log lets a change land.
- **inert files**: `docs/handover.md`, `.relay/queue/**`, `.relay/checks/**`, `.relay/changes/**` (lib/relay_inert.py).
  They are state, not code; relay treats a commit that changes only them as "no code change".
- **inert probe** (today): a second full quick run, beside the first, in a temporary worktree where every inert file has
  a line appended and junk files are planted; the `inert` step fails when the two runs' outcomes differ.
- **reuse**: `relay gate` does not run when a green log exists for an earlier commit and only inert files changed since
  (lib/relay_gate_logs.py `reusable`). `relay land` leans on it after every take of master that brought only queue,
  handover or check records.
- **take**: `relay land` merges master into the branch before gating; **land lock**: one landing at a time per repository.

## 1. What is decided and what is already done

| # | Decision | Who, when | State |
|---|---|---|---|
| D1 | Real git first on PATH through a link the front lays: "Хорошо, положи ссылку на гит, но скажи что именно и куда ты собираешься положить"; then the plain link: "на 60000 команд 7 мс это почти 7 минут теста" | owner, 29 Oct 08:33 / 08:38 | done on this Mac: `~/.local/bin/git`, `~/.local/libexec/git-core`, `~/.local/share/git-core` link into Xcode's git; 20.9 -> 6.6 ms per call. Verified 30 Oct: `which -a git` gives `~/.local/bin/git` first |
| D2 | Option a of that question also promised "relay doctor предупреждает, если посредник снова первый" | owner chose a, 29 Oct | not built |
| D3 | No second test run: "Хорошо, убираем второй прогон", to the option "Убрать второй прогон сейчас, лимит 25 минут" whose text says the result then counts only over the gate's own records | owner, 29 Oct 11:59 | to build |
| D4 | Quick limit 1500 s in the same change ("30 минут сейчас, 25 после ускорения") | owner, 29 Oct | to build |
| D5 | No macOS sandbox, no Linux fence in this change; the Linux gate in podman is the future ("в моих планах полностью переехать на Linux") | owner 29 Oct 10:41-10:45; front decided "no Linux fence" inside the principles | settled; the podman gate is a separate item |
| D6 | Adaptive number of gates per machine: separate item | owner, 29 Oct | out of scope |
| D7 | Measure RELAY_TEST_JOBS 4 against 6 with two gates at once | item text | to do after D3 lands |

## 2. Measured now

| What | Number | Source |
|---|---|---|
| Quick gates before the git link (23-29 Oct) | n=555; total median 911 s, p90 1560 s; library step median 474 s; wait for the probe at the `inert` step median 259 s, p90 757 s; 80 over 1500 s | gates.py over committed gate logs |
| Quick gates after the link (29 Oct 04:38Z - 30 Oct 11:11Z) | n=209; total median 748 s, p90 1034 s, max 1785 s; library step median 708 s; probe wait median 9 s, p90 123 s; 4 over 1500 s | same |
| Why the library step got slower after the link | the test tokens (machine-wide worker pool, landed 29 Oct 15:45) split a gate's 4 tokens 2 + 2 between the run and the probe (tests/parallel_unittest.py `probe_share`), so each run has half the workers and they finish together | code read |
| Gates per day | 209 logs in 30.5 h, about 160 per day (red ones included) | same |
| Code landings since 27 Oct | 168 in 87 h (about 46 per day) | landings3.py over master's reflog |
| What lay between a landing and its deciding green gate | queue, handover or changes files: 115 of 163; only check records or nothing: 48 | same |
| `relay land` itself | 66 landings, 60 gates run, 18 gates reused after a take that brought only inert files | `relay land --stats` |
| master commits since 27 Oct | 521: 131 code, 172 check records only, 193 queue only, 9 handover only, 16 mixed inert | moves.py |
| Chance that a queue or handover commit lands on master inside a gate-long window | 15% for 10 min, 17% for 12.5 min (averaged over all hours since 27 Oct; busy hours are higher, not measured) | moves.py |
| Tracked files | 3,067, of which 2,124 inert (69%) | `git ls-files` |
| Writing a full copy of the tree | 0.98 s (`git archive HEAD` into a folder, load 13.6) | measured |
| Tests or lib code that read an inert file at `HEAD~n` | 0 places (grep) | grep |
| Static guard already in the suite | tests/test_no_live_queue_reads.py flags a test line that names ROOT and a queue path without a pinned commit; it covers the queue only, not the handover or check records, and not lib code under test | code read |

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

**B1. One run on the real tree; reuse only across relay's own records** (the owner's pick as framed on 29 Oct).
The gate runs once, as today's outer run. `reusable` and `tree_moved` change their walk from "only inert files changed"
to "only files under `.relay/checks/` changed" (the walk `finished_red` already uses for red logs). A queue item, the
handover or a `.relay/changes` record changed after the gate means the gate runs again. This is how merge queues work
(GitHub merge queue, bors, GitLab merge trains): what is tested is exactly what lands, and any change of the base
re-tests.
- Gains: the verdict is about the exact tree that lands. Fewest parts: the Probe class, the `inert` step,
  lib/relay_ci_probe.py, `probe_share` and the two RELAY_INERT_* variables go (about 190 lines of code, plus their tests).
- Costs (estimate from measured rates): the 18 of 78 `relay land` gates that were reuses become runs (+23%); a take
  that must be retaken because master moved during the gate now costs a whole gate instead of a reuse (15-17% of
  gate-long windows hold such a master commit), about +0.45 gates per landing, about 20 more gates per day at 46
  landings per day. Each of them runs inside the land lock, so every other ready change waits about one more gate
  (land waits today: longest 41.6 min, ready-to-landed p90 83.7 min). The CPU still falls: 2 runs per gate today
  against about 1.2 after.
- Weak spot: a test that reads a live inert file of the tree is never found by design; it shows only when a queue
  edit turns it red later, as a "flaky" gate (rule 6 would then send someone hunting). The verdict stays correct
  for the tree it ran on.
- `land_inert_tries` (default 10, bounds 3-50): today an inert move costs a retake and a reuse, seconds; under B1 each
  costs a gate. At the bound 10 a landing could hold the land lock for about 10 gates (100+ min) in a busy hour. The
  chance of 10 moves in a row at 17% per window is about 2 in 10^8, so the default stays; the number is reported in
  the land stats already (`inert_moves`).

**B2. One run on a copy of the tree without the inert files** (new; Bazel and Nix work this way: an action sees only its
declared inputs, and its cached result is keyed on those inputs alone). Under `relay gate`, bin/ci makes a temporary
worktree of the gated commit, deletes every inert file in it, commits that as "gate copy" (parent: the gated commit),
and runs all steps there once; the step logs and results are copied back to the worktree's `.ci/`. Reuse and
`tree_moved` stay as they are: two commits that differ only in inert files produce the same copy, byte for byte (the
same git tree), so a green log of one is a true result for the other, by construction rather than by comparison.
- Gains: reuse after queue and handover takes stays (no extra gates, no longer land lock); a test that opens a live
  queue item, the handover or a check record of the tree finds nothing and goes red, so the 25 Oct kind of defect is
  still found, now on the first gate instead of by chance. Works the same in the future podman gate on Linux (D5):
  the copy is what gets mounted, and the 29 Oct finding that `git show HEAD:docs/handover.md` leaked 175,055 bytes
  inside a container is closed, because the copy's HEAD has no handover.
- Costs: the copy, about 1-2 s per gate (0.98 s measured for writing the whole tree; the copy writes 31% of it); the
  Probe's worktree code stays in a smaller form (about 80 lines kept, where B1 removes about 190); failing paths in
  logs point into the copy (the copy-back keeps `.ci/steps/*.log` where fixers read them today).
- Holes, named: a test that reads the gated commit's parent (`HEAD~1:docs/handover.md`, 0 places today by grep), a
  moving ref (`master:.relay/queue/...`) or another checkout of the repository sees real content. B1 has the second and
  third holes too; the first is B2's own. The static guard (tests/test_no_live_queue_reads.py) grows to flag
  `HEAD~`/`HEAD^` reads of inert paths in tests, which closes it for test code.
- Unknown, not measured: how many tests need an inert file to be present (the probe proved content does not matter,
  not that absence does not). The first build step is one quick gate on such a copy. Every test it turns red reads
  live state, which the project's Python rules forbid ("Tests use a temporary folder and never touch the live
  .relay/queue, .relay/checks or docs/handover.md"), so it is a defect fixed in this change. Bound: up to 10 such
  tests are fixed here; more than 10 stops the build and comes back as a scope question (B1 is then the fallback).

**Rejected on the way:** keeping the probe's "append a line" form for the single run. Its tree still holds the real
content plus one line, so two commits that differ in a queue item give two different copies; reuse would be unproven
again. Only deletion makes the copies identical.

### 4.3 How leading tools solve it

| Tool | What decides that a result still holds | Matches |
|---|---|---|
| GitHub merge queue, bors, GitLab merge trains | the exact merged tree is tested; any base change re-tests | B1 |
| Bazel, Buck2, Nix | the action runs in a sandbox that holds only declared inputs; the cache key is their digest | B2 |
| Turborepo, Nx | the task hash covers declared input globs; nothing stops a task reading other files | today's inert list without the probe (unproven) |
| GitHub Actions `paths-ignore`, GitLab `rules: changes` | a change of listed paths skips CI by declaration | same, no proof |

### 4.4 Critique of the owner's pick (said once)

The pick D3 is right on CPU: 2 runs per gate become about 1.2 (B1) or 1.0 (B2). Its weak spot is where the price
lands. The 29 Oct question put it at "около 12 лишних проверок в день"; measured 30 Oct over `relay land`'s own
stats it is nearer 20 per day, and every one of them runs while the land lock is held, so it adds a gate's length to
the wait of every change queued behind (the change of 29 Oct to tokens also means each gate is about one run long,
not shorter). And B1 gives up the only live detector of tests that read state files. B2 keeps both for about 1-2 s
per gate and one build-time unknown (section 4.2). I recommend B2; the owner decides (question below), and either way
the second run goes.

## 5. Build plan

Common to B1 and B2:
1. Remove the second run: `Probe` as a parallel nested run, the `inert` step and its comparison (`outcome` in lib/relay_ci_lines.py
   has no other caller in lib, bin or tests: it goes too), `probe_share`
   (the one run gets the gate's whole token share), RELAY_INERT_PROBE and RELAY_INERT_FULL_HOOKS, the guard-suite
   remark in lib/relay_coverage.py:81, the class-times rule "only the outer run writes" (now: the run writes).
2. QUICK_LIMIT_SECONDS 1800 -> 1500 with its test (D4). Bound: RELAY_CI_QUICK_LIMIT, whole seconds >= 1. At 1500,
   measured after the link: 4 of 209 gates ran over 1500 s, all with the probe beside them; expected 0-2 per day
   without it (not measured). Outcome at the bound: the gate stops itself, exit 124; `relay land` hands back once, and a
   second stop on the same code is red ("a hang, not load").
3. The gate's last line names what the result covers, replacing "inert: skipped (runs under relay gate)":
   B1: "covers this tree and relay's check records after it"; B2: "ran on a copy without queue, handover and check
   records; covers every commit with the same code".
4. docs: docs/plans/review-gate.md section 12.6 and the tables at lines 51 and 183 describe the probe; they are
   rewritten for the chosen form. The lib/relay_ci.py module text (lines 17-22) likewise.
5. Part A (section 3): docs/macos.md section 1, the doctor check.

B1 only:
6. `reusable` (lib/relay_gate_logs.py) walks back while only `.relay/checks/` changed, as `finished_red` does;
   `tree_moved` (lib/relay_gate.py) accepts a HEAD move only under `.relay/checks/`.
7. lib/relay_ci_probe.py and its leftover cleanup go. A probe worktree left by a gate killed before the change lands
   is removed by `git worktree prune` once its temp folder is gone; `relay doctor` already lists leftover worktrees.
8. `relay land` text "gate reused: only queue records or the handover came in" becomes "only check records came in".

B2 only:
6. The copy: Probe becomes `GateCopy` (make the worktree, delete every path `relay_inert.matches`, commit, run the
   steps with cwd and RELAY_ROOT at the copy, copy `.ci/` back, remove the worktree on every way out). The leftover
   cleanup (lib/relay_ci_probe.py) stays, renamed in its texts.
7. First run: one quick gate on a copy of master's head before any test change; red tests are fixed here (bound 10,
   section 4.2).
8. tests/test_no_live_queue_reads.py grows to the handover and check records and to `HEAD~`/`HEAD^` reads.

After either lands (D7):
9. Jobs 4 against 6: a runner starts pairs of quick gates at once on master's head (`relay gate --again`), per-gate
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
| No probe worktree is made (B1) | `git worktree list` is the same before and after a fixture gate |
| The one run has the gate's whole token share | the share function gives 4 of 4 (today 2) |
| Limit is 1500 | QUICK_LIMIT_SECONDS == 1500 and `quick_limit({})` == 1500 |
| B1: no reuse across a queue edit | a green log at X, then a commit editing `.relay/queue/x.json`: `reusable` gives None; a commit adding only `.relay/checks/y.check.json`: gives the log |
| B1: a HEAD move by a queue commit during the gate is refused | `tree_moved` returns a reason naming the file |
| B2: no test sees an inert file | a fixture test that opens ROOT's `docs/handover.md`, one that lists `.relay/queue`, one that runs `git show HEAD:docs/handover.md`: each makes the fixture gate red |
| B2: the copies of two commits that differ only in inert files are the same tree | `git rev-parse <copy>^{tree}` equal for both |
| B2: the copy is removed on every way out | a gate stopped at its limit and a gate ended by SIGTERM leave no worktree and no temp folder |
| Doctor (Part A) | section 3, point 2 |

## 6. Open for the owner

**Как сделать единственный прогон тестов независимым от очереди и handover**

Сейчас каждая проверка перед merge гоняет тесты дважды; второй прогон доказывает, что результат не зависит от
служебных файлов (очередь, handover, записи проверок), и только поэтому зелёную проверку можно засчитать снова,
когда после неё пришёл лишь commit очереди. Вы решили убрать второй прогон. Остаётся выбрать, чем заменить это
доказательство. Пример из замеров 30 Oct: из 78 проверок в `relay land` 18 были засчитаны повторно именно так, а
в 15-17% десятиминутных окон в master приходит commit очереди, и merge приходится начинать заново.

| | a. Копия без служебных файлов | b. Только точное дерево |
|---|---|---|
| Как работает | тесты идут на копии дерева, где очереди, handover и записей проверок нет вовсе | тесты идут на настоящем дереве; любой commit очереди или handover после проверки требует новой проверки |
| Лишние проверки | 0 | около 20 в день (оценка по замерам), каждая внутри очереди на merge, около 10 мин ожидания для стоящих за ней |
| Тест, читающий живую очередь (как 25 Oct) | краснеет на первой же проверке | не виден, всплывёт позже как flaky |
| Цена | 1-2 с на проверку, около 80 строк кода; неизвестно, сколько тестов требуют наличия файлов (до 10 чиним здесь, больше: вернусь с вопросом) | около 190 строк кода удаляется, проще всего |
| Не видит | чтение родительского commit (сегодня 0 мест), master и других checkout | master и других checkout |

- a. Копия без служебных файлов (рекомендация: без лишних проверок и без удлинения очереди на merge; так работают Bazel и Nix; та же копия пойдёт в будущую проверку в podman на Linux)
- b. Только точное дерево (как в вопросе 29 Oct: проще, но около 20 лишних проверок в день)

## 7. What the brief could not answer

- Whether busy hours raise the 15-17% chance of a master move during a gate: the average is over all hours since
  27 Oct; not measured per hour.
- The gate's length without the probe: not measured (estimate: the library step near its pre-token median of 474 s,
  because the one run gets all 4 workers back).
