Plan: revision 2 of the design on why relay's library tests are slow. Written 2026-10-27. Designs queue item `relay-s-merge-and-queue-code-start-git-too-often`.
Not built yet: nothing in this file is in the code; it is the design a worker builds from.

# Design: why relay's library tests take ~10 minutes, and whether Rust or parallel runs fix it

Revision 2 (27 Oct), against the review in the session scratchpad (not kept) What changed is listed in section 9.

Owner's question (verbatim, 27 Oct): "Почему наши тесты вообще выполняются 10 минут даже с оптимизацией, ускорится ли это вместе со сменой технологии, возьмем максимально возможную - rust, или параллельной обработки будет достаточно, что делает тесты долгими ?"

Measured 26-27 Oct on the owner's 12-core Mac, master at 0682eb7 (revision 2 runs at 814b7e7). Every test run was one test file in one process (see "How it was measured"). The machine was shared: the parallel-runner builder's gates, a virtual machine at 165% CPU, a coverage run, and XprotectService (the macOS scanner) at 37% CPU. Load average ranged from 2 to 63. Because of that, only **paired** runs (the same file, back to back, at the same load) are used for comparisons. Counts (how many processes) do not depend on load. Times do.

## 1. Short answer

- **What makes the tests long:** the tests mostly wait for other programs to start. The suite (1003 tests) starts **30,865 processes**, and **29,317 of them (95%) are `git`**. That is about 29 git runs per test, and up to 74 per test in tests/test_queue.py. In every git-heavy file, some child process is running for 99-100% of the test's wall time. Python's own work inside the test process is about 1-1.5% of the time.
- **81% of those git runs come from relay's own code under test** (the merge, queue and inert code in lib/), 19% from the tests' own setup. Measured over the whole suite (23,750 of 29,387 git runs; section 2.2).
- **Half of each git run is Apple's launcher, not git.** `/usr/bin/git` on macOS is a small launcher program (Apple calls it the xcrun shim). On each call it looks up where the developer tools live and then starts the real git; on this Mac that is Xcode's copy, `/Applications/Xcode.app/Contents/Developer/usr/bin/git`, because the developer folder is set to Xcode. Measured on a quiet machine: launcher 11.8-15 ms per start, real git 4.0-5 ms, a bare process (`/usr/bin/true`) 2.1 ms. Under load the gap grows: 35 ms against 10 ms.
- **Pointing the tests at the real git binary** cut the git-heavy files by **55-61%** in paired runs at low load: test_merge_train -55%, test_check_mark_hook -58%, test_check_record -60%, test_queue -61%. The saving per git run is 8-12 ms in each pair, the same as the launcher's measured cost per start. 172 tests across 6 files passed with it, none failed. Estimate for the whole serial suite: ~600-650 s -> ~360-380 s (-40%; not a paired full run, see 2.4).
- **The gate you wait on is longer than the tests.** Each `relay gate` runs the free checks twice at once: the normal run and the "inert probe" (a second copy of the same checks in a separate worktree, which proves that queue items, check records and the handover file never change a check's result). Since 26 Oct 19:07 the two run side by side; the gate takes a median **938 s (~16 min)**, of which the library tests step is **762 s**. The probe makes the machine busier, so each run is slower than alone (section 2.5).
- **"Even with the optimization":** tonight's fix (tests/fake_tools.py) removed the macOS scan of fake programs in the installer tests (72 s -> 11 s). That was a real cost in a few files, but not the main one: git starts are.
- **Rust:** no. A rewrite would shrink only Python's own execution, which is at most ~5-10% of the time (section 3). Git, process starts and the disk stay the same. The one real gain a rewrite could bring is reading git data inside the process, without starting git. Python can get the same gain with the standard library (approach B).
- **Parallel runs help, but each start gets slower as the machine fills up.** One git start costs 15-19 ms when the machine is quiet and 35-44 ms at load 20-50. More jobs means each start waits longer, and a gate already runs two suites at once. A cheaper start (approach A) also makes the parallel runner scale better.

## 2. Where the time goes

### 2.1 Measured per file (serial, one process)

| file | tests | processes | git runs | git runs per test | wall, launcher git | wall, real git | load | usable for A's size |
|---|---|---|---|---|---|---|---|---|
| test_queue | 97 | 7,221 | 7,164 | 74 | 143.1 s (120.2 s quiet, 123.9 s) | 55.9 s (41.4 s at load 3, not paired) | ~11 | yes: 12.2 ms per git run |
| test_merge_train | 34 | 4,702 | 4,696 | 138 | 70.6 s | 31.8 s | 3-7 | yes: 8.3 ms |
| test_check_record | 41 | 5,584 | 5,584 | 136 | 76.2 s | 30.4 s | 3 | yes: 8.2 ms |
| test_check_mark_hook | 7 | 2,084 | 2,068 | 295 | 29.6 s; again 32.3 / 32.6 s | 12.3 s; again 13.8 / 13.7 s (Xcode git) | 2-3 | yes: 8.4-9.0 ms |
| test_rules_gate_isolation | 2 | 851 | 698 | 349 | 17.5 s | 12.5 s | 2 | yes |
| test_guard_test_name | 3 | 1,606 | 1,606 | 535 | 125.6 / 121.7 s | 40.7 / 41.5 s | 19-51 | **no**: 53 ms saved per git run, 5x the per-start cost; the same file took 56.6 s under the launcher in another run. Load noise |
| test_gate | 21 | 1,152 | 1,010 | 48 | 132.8 / 175.9 s (1 failure in each) | 84.6 / 32.7 s | 40-60 | **no**: 50-140 ms per git run implied. Load noise |
| test_installer_doctor | 30 | 92 | 10 | 0 | 15.9 s | - | ~20 | - |
| the other 68 files | 768 | 7,573 | 6,481 | 8 | - | 150.1 s | 9-11 | - |
| **all 76 files** | **1003** | **30,865** | **29,317** | **29** | | | | |

Processes by kind, whole suite: git 29,317; python3 744 (mostly `bin/relay` and hooks); other programs 624 (fake tools, ruff, pytest fakes); sh/bash 180.

### 2.2 By kind of work (test_queue, real git, 55.9 s; partly estimated)

| kind of work | share | rests on |
|---|---|---|
| starting and running git (7,164 runs x ~5-6 ms) | ~65-75% | measured: count, and per-start cost from the microbench |
| starting Python children (`bin/relay`, 53 runs, 72 ms each: ~22 ms interpreter, the rest imports and work) | ~4-7% | measured: 3.8 s self time with the launcher |
| git setup: `git init` (104 runs, 80 ms each) and first commits | included above, ~10-15% | measured: init+add+commit 62.5 ms against copying a ready repo 7 ms |
| Python's own logic in the test process | ~1-1.5% | measured: wall time minus time with a child running (merge_train 209.8 against 207.1 s; check_record 219.7 against 216.7 s) |
| sleeps | ~0 | static: every `time.sleep` is a 0.01-0.1 s poll waiting for an event (test_gate, test_gate_slots, test_ci_python, test_bin_check_portable). There are no fixed waits |
| the macOS first-run scan of a newly written program | small outside a few files | measured: test_gate writes a new `gate.sh` per test, 13 runs at 758 ms each = 9.9 s of a 42 s file (~0.75 s each is the scan). test_rules_gate_isolation: 6 fake `claude` at 408 ms, 9 fake `pytest` at 270 ms |

**Who starts the git runs.** Every git run was logged with the place in relay that started it. test_queue was re-run on 27 Oct with that logging (its first log had no caller field), so the split now covers the whole suite:

- **80.8% (23,750 of 29,387)** come from relay's own code under test: lib/relay_git.py, lib/relay_queue.py, lib/relay_inert.py, lib/relay_marks.py. In test_queue alone: 5,934 of 7,234 (82%), mostly `relay_git.git` (3,082) and `relay_queue._git` (2,763).
- **18.9% (5,540)** come from the tests' own setup helpers. 97 runs (0.3%) have no known caller.

So the tests are slow mostly because the programs they test call git many times. The test fixtures are the smaller part. One example: `relay_inert.absorbed` calls `merge-base`, `rev-list` and `ls-tree` once per branch and runs `is-ancestor` per pair of branches. This is the same cost the merge hook pays on the owner's machine.

### 2.3 Microbench (quiet machine, average of 40 runs unless stated)

| what | ms |
|---|---|
| `/usr/bin/true` (the cheapest process start) | 2.1 |
| real git `--version` | 4.3-4.5 |
| `/usr/bin/git --version` (launcher) | 12.6-14.9 (15.1 with DEVELOPER_DIR set, so that setting does not help) |
| `git rev-parse`, launcher / real, interleaved runs | 15.1 / 5.1 |
| `git rev-parse HEAD`, launcher / Xcode git / Command Line Tools git, 30 interleaved rounds (the reviewer's run, load 1.4) | 11.8 / 4.1 / 4.0 |
| the same under load 20-50 | 35.4 / 9.8 |
| `python3 -S -c pass` / `python3 -c pass` / `bin/relay --help` | 14.7 / 22.0 / 67.8 |
| `git init` + add + commit / copying a template repo | 62.5 / 7.0 |
| one query to an already running `git cat-file --batch-check` | 0.17 |

### 2.4 The whole suite, one run (estimate)

- **With the launcher, serial, quiet:** about 600-650 s. This is the paired quiet numbers of the heavy files plus the other 68 files with ~10 ms added per git run. It matches the library tests step of the gates while the probe ran after the outer steps: median 625 s, range 560-790 s (24 green gates, 26 Oct).
- **With real git:** about 360-380 s. Built from the per-run saving (8-12 ms x 29,317 runs = 235-350 s), not from the two load-affected pairs.
- **Not measured:** a paired full-suite run. The builder was measuring at the time, and the brief forbids it.

### 2.5 The gate around the library tests (measured from the gate logs)

A `relay gate` runs `bin/ci --quick` and, beside it, the inert probe: a second `bin/ci --quick` in a temporary worktree of the same commit where every inert file has a line added (lib/relay_ci.py lines 17-21 and 446-461; the inert files are docs/handover.md, .relay/queue/**, .relay/checks/**). At the `inert` step the gate waits for the probe and fails if any step result or test count differs.

Medians of the green gates since 26 Oct 12:00, split by whether the gated commit has 27d4bd0 ("inert probe runs beside the outer steps instead of after them", 26 Oct 19:07):

| | gates | library tests | hook tests | inert (waiting for the probe) | whole gate |
|---|---|---|---|---|---|
| probe after the outer steps (older branches) | 24 | 625 s (560-790) | 144 s | 772 s (706-884) | **1549 s** (1403-1830) |
| probe beside the outer steps (now) | 4 | 762 s (635-840) | 162 s | 4.5 s (4-11) | **938 s** (797-1021) |

- The review's figure "inert median 769 s, gate 1535 s" (last 35 green gates) is true of those logs, but 24 of them gated branches made before 27d4bd0. Today the probe no longer adds its own run time; it adds load: the library tests step is 22% slower (625 -> 762 s) and the hook tests 13% slower, because two suites share the machine. That is a comparison of medians, not paired, with only 4 gates on the new side.
- **Cost of the probe today (estimate):** ~137 s + ~18 s = ~155 s of a 938 s gate, ~17%.
- **After A (estimate):** both runs in a gate speed up, and each starts fewer launcher processes, so they compete less. The library tests step: 762 s -> ~455 s (-40%). The hook tests (17 bash scripts, 239 lines that name git, 162 s) are not measured with A, so they are counted unchanged. The gate: 938 s -> ~630 s (-33%) before the parallel runner.
- **With the parallel runner:** a gate runs 2 x RELAY_TEST_JOBS test processes plus the hook tests, so its job count must be measured under `relay gate` (with the probe), not with a bare `bin/ci`.

## 3. The Rust question, on these numbers

- **What a compiled language would shrink:** Python's own execution. That is the test process's logic (~1-1.5%) plus the Python children's start and imports (~4-7% in test_queue; the 744 python3 runs suite-wide). Rust at ~2-5 ms per start instead of 22-70 ms saves **at most ~5-10%** of the suite.
- **What it would not touch:**
  - 29,317 git starts. A Rust relay that runs the git command still pays them.
  - The macOS launcher and the macOS scan.
  - File system work in temporary folders.
  - The tests' polling loops.
  - The probe's second run of everything in each gate.
- **Rewriting only the tests changes nothing they wait on.** The code under test is relay's Python programs and hooks, and 81% of the git runs come from them.
- **Where a rewrite could win:** reading git objects inside the process with a git library (libgit2, gitoxide), so no git process starts at all. That is approach B, and Python can do it with the standard library: one long-running `git cat-file --batch` answers a lookup in 0.17 ms instead of 5-15 ms for a new process. Python git libraries (pygit2, dulwich) are not in the standard library, so relay's rule rules them out.
- **Cost of a rewrite:** relay's Python rule ("stdlib only", "Bash moving to Python") and the owner's direction run the other way. It would mean a toolchain the gate does not have and rewriting about 15k lines of tests and all of lib/. That is many agent-days for at most 10%.

## 4. Approaches

The parallel runner on wt/test-jobs is already being built and is not repeated here. Savings are percent of the serial suite and assume approach A is not done unless stated.

### A. Call the real git binary, not Apple's launcher (recommended; decided within the principles, owner can reverse)

- **The rule (one function, in lib/relay_git.py):** given a PATH, find the git that PATH would run. Link nothing unless that git resolves to `/usr/bin/git` **and** `xcrun --find git` prints a different path. Then make a folder with one link `git` -> the printed path, and return the folder to put first on PATH. The rule asks "would this run use the launcher?", not "is /usr/bin/git a launcher?", so:
  - PATH already finds Homebrew git (owner question 1a): nothing is linked, the run uses Homebrew git;
  - a nested run (the probe's `bin/ci`, `run_unittest.py` started by `bin/ci`) sees the link already first on PATH and links nothing again.
- **Where it is called (one definition for every test run):**
  - lib/relay_ci.py, once per gate run: the folder goes first on PATH in `self.env`, which every step gets (library tests, hook tests, the probe's nested run). It is created in `prepare` and removed when `main` ends.
  - tests/tmp_default.py, for direct runs that do not go through bin/ci: `python3 tests/run_unittest.py` (and the parallel runner, which inherits its parent's environment, tests/parallel_unittest.py:183) and pytest through tests/conftest.py. This keeps the recorded rule that unittest and pytest give tests the same environment.
- **Saving:** measured -55% to -61% on git-heavy files at low load; estimated -40% on the suite and -33% on the gate (2.5). Clears the 25% bar.
- **Test power:** kept. It is the binary the launcher itself starts on this Mac (`xcrun --find git` = Xcode's git, Apple Git-155, git 2.50.1); `--version` and `--exec-path` through the link equal the launcher's (both print Xcode's `libexec/git-core`). The 26 Oct runs linked the Command Line Tools copy instead; a paired re-run on 27 Oct with Xcode's copy gave the same time (test_check_mark_hook 13.8 / 13.7 s with Xcode git, 13.8 / 13.6 s with CLT git, 32.3 / 32.6 s with the launcher, load 2-3). 172 tests in 6 files passed through the link, plus 104 more in the 27 Oct re-run.
- **Size:** ~30 lines (the function, two callers), plus the tests below.
- **Setting:** `RELAY_TEST_GIT`.
  - default `real`: the rule above;
  - `launcher`: link nothing, which gives today's behaviour and serves for A/B measurement;
  - at the bound: if `xcrun` is missing or fails (Linux, no Command Line Tools), nothing is linked and the tests run as today, slower but correct.
- **Tests that fail when a claim is false:**
  - "same git": `git --version` and `git --exec-path` through the run's PATH equal those of `/usr/bin/git`;
  - "only when the run would use the launcher": with PATH finding another git first (a fake folder holding a `git` before `/usr/bin`), nothing is linked and `git --version` in the run equals that git's;
  - "same under every runner": a test that runs `git` through PATH sees the link under pytest, under tests/run_unittest.py and under the parallel runner;
  - "hook tests too": in the gate's hook-tests step, `command -v git` inside a `*.test.sh` resolves to the link (plugins/core/tests/shim.test.sh sets its own `PATH=/usr/bin:/bin` and keeps the launcher on purpose);
  - "only inside the run": after the run the link folder is gone and the parent's PATH is unchanged;
  - "no effect where tests set their own PATH": test_installer_doctor still passes, because its PATH holds only its own fakes;
  - "off switch": `RELAY_TEST_GIT=launcher` links nothing even when PATH finds `/usr/bin/git`;
  - "no xcrun": with `xcrun` absent from PATH, nothing is linked.
- **Timing:** it touches tests/run_unittest.py and the parallel runner, which wt/test-jobs also changes, so it should follow that merge or join it.

### B. Fewer git runs inside relay's own code (a design item, not a test change)

- **How:** batch what relay asks git:
  - one long-running `git cat-file --batch` per command, for lookups of commits, revs and trees;
  - one `rev-parse a b c` call instead of three;
  - one `for-each-ref --merged`/`--contains` call instead of pairwise `merge-base --is-ancestor`.
- **Saving:** 81% of the suite's git runs start here (measured, whole suite). Halving them is an estimate of -25-35% before A, and -15-25% after A (not measured: the log keeps only the first 4 arguments, so repeated identical calls were not counted).
- **Side effect:** it also speeds the merge hook and the gate on the owner's machine.
- **Test power:** kept. The same tests check the same behaviour.
- **Risk:** this is the merge guard's code. A long-running git must see refs that change during one command; to check: whether `cat-file --batch` reads loose refs fresh on every query. relay_queue's lock-free races also go through these calls.
- **Size:** medium to large, in lib/relay_git.py, relay_inert.py, relay_marks.py and relay_queue.py. Needs measurement first: count the identical calls in one merge-hook run.

### C. One template repo per test fixture instead of `git init` + commits per test

- **How:** build each fixture shape once per run and copy it per test with `shutil.copytree`: 7 ms against 62.5 ms.
- **Saving:** test-side git is 19% of the runs. In test_queue, the 104 inits plus first commits are ~10-15%. Suite estimate -5-10%.
- **Test power:** kept, as long as each test still gets its own copy.
- **Size:** moderate: each test file has its own `repo()` helper, so it is adopted file by file.
- **Verdict:** below the 25% bar and not small, so not now, by the owner's rule.

### D. Two small cleanups (a fix item, decided by principle 2: waste that repeats on every run)

- **Duplicate installer tests:** in tests/test_installer_doctor.py, `Routes`, `PythonStep` and `BrokenAndMissing` (lines 235, 290, 328) inherit from `InstallScript` without their own tests. So `InstallScript`'s two tests (lines 183, 201) run 4 times each: 6 duplicate runs, ~3 s now, 47 s in the old 735 s log. Fix: move the helpers to a mixin without tests.
- **Fresh programs that trigger the scan:** test_gate writes a new `gate.sh` per test, so each pays the 0.75 s scan: 9.9 s. test_rules_gate_isolation does the same with its fake `claude` and `pytest`: ~5 s. Fix: keep the text fixed (pass the folder through an environment variable) and link it with tests/fake_tools.py.
- **Saving:** ~15-20 s, ~3-5% of the suite. Small; it goes in for the waste, not the speed.

### E. Test tiers: fast unit tests for the worker loop, integration tests at the gate

- **Leading practice:** Google's small/medium/large test sizes (Bazel `size=`); pytest `-m "not slow"`.
- **Saving:** large for the worker loop. Most of the 1003 tests start git, so a "no processes" tier would hold maybe a few hundred tests. Not measured.
- **Loses:** a defect in a git-touching path is found at the gate, not in the loop.
- **Verdict:** not now. After A plus parallel jobs the library tests are expected at a few minutes, which removes most of the need. Revisit if the library tests step of a 4-job gate after A stays above ~3 minutes.

### F. Calling functions in the test process instead of running bin/relay (looked at, not recommended)

- **Measured:** 744 python3 starts in the whole suite; ~70 ms each with the launcher, so ~3-7% of time.
- **Loses:** the check of the command line: argument parsing, exit codes, environment.
- **Verdict:** below the bar, and it loses test power. Not recommended.

### G. Rust rewrite: not recommended (section 3)

At most ~5-10% saving, it breaks the stdlib-only rule, and it costs many agent-days.

### H. The inert probe's second run (looked at; keep it as it is, decided within the principles, owner can reverse)

What the probe buys: proof, on every gate, that no check result depends on the queue, the check records or the handover file. That proof is what lets a queue item land on the default branch with no gate of its own.

| option | saving on today's gate (estimate) | what the inert check loses | size |
|---|---|---|---|
| H0, do nothing: keep it beside the outer steps (since 26 Oct 19:07) | 0 (the earlier move from "after" to "beside" already took the gate 1549 s -> 938 s) | nothing | none |
| H1, run the probe only on the gate that lands on the default branch (the train or the last gate), not on every branch gate | ~17% (~155 s) on branch gates; 0 on the landing gate | a code change that starts reading an inert file is found at landing, not when the branch is first gated: a later, costlier fix | small, in lib/relay_ci.py and the merge hook |
| H2, the probe reruns only the test files that can read an inert file | ~10-15% | which files "can read" one is a judgment, not a fact a script can check exactly (principle 5); a miss means a dependence that is never caught | medium |
| H3, the probe runs with fewer test jobs than the outer run | less load on the outer run, but the gate still waits for the slower probe at the `inert` step | nothing | small, after the parallel runner |

- **Verdict:** H0. The largest option, H1, saves ~17% by an unpaired estimate, below the owner's 25% bar, and it weakens a safety proof. A also shrinks the probe, by the same ~40%. Re-measure the probe's share once A and the parallel runner are in.

### Do nothing

The suite stays at ~600-650 s serial on a quiet machine, and ~3x that when the machine is loaded: test_merge_train took 210 s at load 20-28 against 70.6 s quiet. The gate stays at ~938 s. The parallel runner then has to fight the launcher's growing start cost, twice per gate.

## 5. How leading projects keep big suites fast

- **git's own test suite.**
  - It is about a thousand shell scripts that start git thousands of times. It is known to be slow where process starts are expensive (Windows, macOS), which is the same cause as here.
  - Answers: run the scripts in parallel with `prove -j`, slowest first (`--state=slow,save`), and skip expensive tests by default (`GIT_TEST_LONG` / the EXPENSIVE prerequisite).
  - More recently, unit tests in C (t/unit-tests) call the internal functions without starting git.
  - The `--state=slow,save` order is what wt/test-jobs does with its saved class times.
- **pytest-xdist:** splits by process, `-n auto`, `--dist loadscope` keeps a class on one worker. This is the same model as RELAY_TEST_JOBS.
- **Long-running git:** GitLab's Gitaly and many git tools keep one `git cat-file --batch` process alive per repository instead of starting git per object (approach B).
- **Mercurial:** `chg`, a command server that keeps Python running so each `hg` call skips interpreter start-up. This is the same lesson for Python children.

## 6. Recommendation

1. **Do A now** (~30 lines). It rests on measured paired runs: -55% to -61% on the git-heavy files at low load, a saving per git run equal to the launcher's measured cost, and an estimated -40% on the suite and -33% on the gate, which clears the 25% bar. It should follow the wt/test-jobs merge, or ride on it, because both change the test runners. Then measure the gate at RELAY_TEST_JOBS 1/4/6 again under `relay gate`: the builder's current numbers include the launcher's cost and the probe's load.
2. **Add D as a fix item** (small; waste on every run).
3. **Put B in the queue as a design item.** It needs its own measurement of identical calls per merge-hook run, and it also speeds relay on the owner's machine.
4. **Keep the probe as it is (H0)** and re-measure its share after A and the parallel runner.
5. **Not now:** C and E (below the bar, or not needed after A). Not recommended: F and G.

## 7. Weak spots in the brief's own picks (said once)

- **The brief's leading guesses were measured to be small levers:** running bin/relay inside the test process (F, ~3-7%) and shared fixtures (C, ~5-10%). Most git runs come from the code under test.
- **The brief scoped the work to the library tests,** but the wait the owner sees is the gate, which runs the library tests twice at once (2.5).
- **The parallel runner's default of 4 jobs** was chosen on numbers that include the launcher. After A, the best job count may differ, and in a gate it is 4 jobs twice.
- **Load-sensitive test:** test_gate failed one test in each of two launcher runs at load 40-60, and none with real git. That suggests a test sensitive to load: a flaky test is a bug by the quality-gate rule. The per-test log records only wall times, so the fix item must start with one re-run at high load that records the failing test's id. The case: "test_gate at load ~50, launcher git: 1 of 21 fails".

## 8. Open for the owner

**1. Should relay's own programs on your Mac also skip Apple's launcher, not only the tests?**

Every hook that Claude Code runs, and the merge and gate commands, call `git`. On macOS each call first goes through Apple's launcher, which costs ~8-12 ms (measured), and ~25 ms when the machine is busy. Approach A fixes this only inside test runs. For example, a test in test_merge_train makes ~140 git calls on average (setup included), about 1.2 s of launcher. A real merge of a train pays the same per call; how many calls one real merge makes is not measured.

| | what changes | cost | covers |
|---|---|---|---|
| a | you install Homebrew git (`brew install git`); `/opt/homebrew/bin` is already ahead of `/usr/bin` on your PATH; A then links nothing | zero code; one machine change; relay is then tested and run on Homebrew's newer git, not on the Apple git 2.50.1 a stock Mac has, so a difference between the two would not show on your machine | everything on your machine, Claude Code's own git included |
| b | relay's programs use A's function (lib/relay_git.py) to find the real git once per program | 43 call sites in 27 files; medium change; Apple's git stays | relay on any Mac |
| c | tests only (A) | nothing more | test time only |

- a) Homebrew git (recommended: no code, the widest gain; not measured on Homebrew's build, which is expected near the real binary's 4 ms)
- b) relay finds the real git in code
- c) tests only

**2. Queue B (fewer git runs inside relay's merge and queue code) as a design item now?**

81% of the suite's git runs come from relay's own code (23,750 of 29,387, measured over every test file), not from the tests. Batching them would speed both the tests and every real merge. But it touches the merge guard, the code that decides whether a merge is allowed. The expected saving after A is an estimate: -15-25%.

- a) yes, as a design item ranked below A and D (recommended)
- b) not now; revisit after A and the parallel runner are measured

## 9. Revision against the review (27 Oct)

| finding | verdict | what changed |
|---|---|---|
| F1 the gate's inert probe left out | holds in part | Added 2.5 (gate step times, split by probe placement) and approach H. Does not hold: "inert wait ~769 s" describes gates of branches made before 27d4bd0; since then the probe runs beside and the wait is 4-11 s (4 gates). Its cost today is load, ~17% of the gate (estimate). Kept as decided (H0), not an owner question: below the 25% bar and it weakens a safety proof |
| F2 A's rule ignores the git PATH would run | holds | The rule now checks the git the run's PATH finds; a test for the Homebrew case and the off switch added |
| F3 A placed in run_unittest.py only | holds | One function in lib/relay_git.py, called from lib/relay_ci.py (every step, the probe included) and tests/tmp_default.py (pytest and direct unittest runs); tests for each runner and the hook tests added |
| F4 the runs linked the CLT git, the launcher starts Xcode's | holds | A links what `xcrun --find git` prints (Xcode's here). A paired re-run with Xcode's git gave the same times as with CLT's; `--exec-path` equality added to the "same git" test |
| F5 -67% and 122-126 s -> 41 s are load noise | holds | Headline is -55-61% from the four consistent pairs; test_guard_test_name and test_gate marked not usable |
| F6 81% left out test_queue | holds | test_queue re-run with caller logging: 82% of its git runs come from lib; whole-suite share is 80.8% of 29,387 runs, no longer a partial figure |
| remark: test_gate fix item cannot name the test | holds | The fix item starts with a high-load re-run that records the failing id (section 7) |
| remark: 1a changes the git version tests run on | holds | Named in question 1's cost column |

## How it was measured

- **Logging:** a `sitecustomize.py` hook, loaded through PYTHONPATH into every Python process, logged every `subprocess.Popen`: what was started, the parent, start and end times, and the relay file that started it. Files: the session scratchpad (not kept), with the per-test runner the session scratchpad (not kept) and the session scratchpad (not kept) beside it.
- **Raw data:** the session scratchpad (not kept) (26 Oct) and the session scratchpad (not kept) (27 Oct: the Xcode/CLT/launcher pairs in ab3.log, the test_queue caller log sp-test_queue.jsonl), made by the session scratchpad (not kept)
- **Gate step times:** parsed from .relay/checks/*.gate.log (green gates since 26 Oct 12:00), split by `git merge-base --is-ancestor 27d4bd0 <gated commit>`.
- **What the hook does not see:** processes started by bash or sh scripts (install.sh's fake tools) are counted inside their script.
- **Real git:** the 26 Oct runs put a link to `/Library/Developer/CommandLineTools/usr/bin/git` first on PATH (the session scratchpad (not kept)); the 27 Oct runs also linked Xcode's git (the session scratchpad (not kept)), which is what the launcher starts here.
- **Coverage:** every file ran serially, one process at a time, never the full suite at once.
