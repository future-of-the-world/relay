Plan: revision 2 of the design on what .relay/checks keeps and where run artifacts go. Written 2026-10-26. Designs queue item `red-gate-and-probe-runs-keep-no-logs-to-find-a-c`.
Not built yet: nothing in this file is in the code; it is the design a worker builds from.

# Design: what .relay/checks keeps per commit, and whether more artifacts belong there (revision 2)

The owner, 26 Oct night, verbatim: "Почему мы не можем записывать это в .relay/checks в файлах репозитория, что мы вообще там храним, можем ли мы складировать в папку коммита дополнительные артефакты"

"This" is the per-class test times that the parallel test runner of the gate-speed design (section 3 C) uses to hand out
test classes longest first. That design keeps them in `.ci/test-times.json`, an ignored local file.

Revision 2 answers the review `review-design-checks-artifacts.json` (10 findings, all checked and all hold; the answers
are listed at the end). What changed: the probe running beside the outer run now decides the times question (only an
option the probe can read gives any speed gain); the miss rate is a measured 30% lower bound instead of a guessed
61%; the store for red runs has three keep points instead of one, and the committed gate log names no path.

## Summary

- **We can write the times into `.relay/checks`.** Nothing forbids it: the inert rule allows a file that changes no
  outcome, and the probe (the gate's check that inert files decide nothing) would prove it. The costs are the size of
  every gate log (26 times bigger) or merge conflicts (one shared file), not a rule.
- **The gate-speed design's pick, the cache inside the worktree, gives no gain at all once the probe runs beside the
  outer run.** The probe's fresh worktree never has the file, so the probe always orders by test count, and the gate
  waits for both runs. Even before that change it misses at a worktree's first gate: at least 30% of gates (measured:
  91 task branches for 307 gates in all history).
- **Recommended for the times: one cache per machine under `$RELAY_HOME`** (the folder relay already uses for evals, gate
  slots and the ledger). Every worktree and the probe read it; only the outer run writes it. 0 bytes in git, the same
  parts as the worktree cache. It loses only the first gate on a new machine, which runs in today's order with the
  same results.
- **More artifacts per commit: keep them outside git**, in a per-machine store with a time limit, and only for red
  runs. Three places keep: the gate (its step logs), the probe (its nested run's logs, which today it deletes), and
  the paid run (the failing eval runs). The folder is found from the commit's sha by one fixed rule, so the committed
  gate log names nothing. Git keeps every byte forever, and logs carry content nobody chose. Live example: one red
  gate log holds a single line of 61,667 characters (an assertion that printed a whole source file).
- `.relay/checks` has no folder per commit today: each commit gets up to three flat files named after its sha.

## Measurements (26 Oct night, master, read-only)

| What | Number |
|---|---|
| Files in `.relay/checks` | 666: 300 gate logs (174 KB), 183 check records (1.86 MB), 183 marks (53 KB). `du` shows 4.1 MB because of 4 KB disk blocks |
| Red gate logs | 47 of 300 (16%), 1,985 bytes on average; a green one is about 300-335 bytes |
| Command in the gate logs | all 303 gate logs: `cmd bin/ci --quick`. No paid run has ever gone through `relay gate` |
| Gate commits per day, all branches | 15 (23 Oct, the first day), 132, 94, 65. Check commits: 7, 82, 54, 48 |
| Gates and task branches, all history | 307 gate commits; 91 distinct `wt/<name>` branches named in commit subjects (18 of them trains) |
| Files added to the folder on master per day | 32, 350, 198, 149 |
| History of the folder | 1,704 file versions, 5.3 MB raw, 1.25 MB in git's storage |
| The folder's own listing (git "tree" object) | rewritten by every commit that touches the folder: 596 versions, 51 KB each now (about 77 bytes per file) |
| Whole repository | packed 3.56 MiB; loose 4,495 objects holding 14.7 MB of data (27.5 MiB is git's disk-block figure). Of the 14.7 MB: checks listings over 40 KB 4.3 MB (29%), other listings 6.3 MB, file contents 4.0 MB (reviewer's breakdown) |
| Test classes | 202 found by `unittest` (212 class lines in `tests/test_*.py` counting helpers), names 29 bytes on average |
| A gate log with a times section | 8,860 bytes, against 335 today (one line `time <module.Class> <seconds>` per class) |
| Packing, simulated: 100 gate commits in a scratch clone, then `git gc` | plain logs: +152 KiB; logs with a times section: +280 KiB (**+1.3 KB per gate**); a separate times file rewritten each time: +258 KiB (**+1.1 KB per gate**) |
| Machine paths in stored files | `/Users/...` appears in 35 of 183 check records and 1 gate log; secret-like words (token, api key, secret) in 0 gate logs |
| Longest line in a committed gate log | 61,667 characters (gate log `9927265…`, 15 lines in all) |
| Full step logs of one run (`.ci/`, ignored) | `ci.log` 83 KB (a concatenation of the step logs); hook tests 59 KB, plugin validate 11 KB, grader tests 11 KB |
| Eval records already kept outside git | `$RELAY_HOME/evals`: 19 records, 2.0 MB |

How the packing estimate was made: three clones of master into the scratchpad (`sim/`, made by `sim/sim.py`). Each
got 100 commits of the same shape a gate makes, then a `git gc`, and `size-pack` was read before and after. The times
in the simulation vary by -20% to +25% between runs, as real times would. The real repository was not changed.

## 1. What `.relay/checks` holds, plainly

All three kinds are named after the commit they are about (its full sha). Only relay's own code writes them: the
`guard-main` hook refuses any other write, and `lib/relay_marks.py` is the one module that reads and writes the folder.

| File | What it is | Who writes it | Who reads it | Why it is committed |
|---|---|---|---|---|
| `<sha>.gate.log` | The result of a gate: `head <sha>`, the command, the wait for a slot, then **the whole quiet output of `bin/ci`** (one line per step with its seconds, and for every failing step up to 8 lines matching `FAIL`, `Error`, `error` or `✗`, each copied whole, of any length), then `exit <n>` | `relay gate` (`lib/relay_gate.py`). It is committed alone as "relay: gate of <sha>" | `relay gate` itself: a later gate on the same code (only inert files changed since) reuses a green log and runs nothing; the reuse reads only the first, second and last lines. The checker's record cites it. The merge hook reaches it through the mark | The merge hook trusts it because code wrote it, not a model. It must travel with the branch to the merge, and it lets a gate be reused across worktrees |
| `<sha>.check.json` | The check record: the item's problem, the reviewers' findings with their failing and passing cases, one verdict per finding | The checker, through the check hook (`plugins/core/hooks/check-mark.py`) and `relay_marks` | The merge hook (refuses while a finding is open), `relay check show`, a fixer | The merge decision rests on it. It has to be readable from the branch at merge time and afterwards ("why was this merged") |
| `<sha>.json` | The mark: a small pointer `{commit, check, gate, verdict: {open, queued}, time}` | The check hook, in the same commit as the record | The merge hook and `relay_marks` (they find the newest mark among the head's ancestors) | It ties a commit to its check and its gate, so the hook does not have to parse the large record to decide |

**Inert** (defined in `lib/relay_inert.py`) means that the folder's content never decides a check or a merge. Two
things follow:
1. A commit that changes only inert files keeps the green gate of the code before it (this is how a gate log's own
   commit does not need a new gate).
2. The gate proves the rule on every run. Its last step, `inert` (`bin/ci` `inert_probe`), checks out the same commit
   in a fresh worktree, appends the line `inert probe line` to every inert file, adds fake files (`zz.json`,
   `zz.check.json`, and a `zz.gate.log` holding `head 0` / `exit 0`), runs the quick gate again, and fails if any step
   result or test count differs. Then it deletes that worktree and its log.

**Side finding (repeats on every commit, so it is a fix item for the front, not a question).** Git stores the folder's
listing as one object of 51 KB, and every gate or check commit writes a new one: about 50 KB per commit before packing
(15.2 MB raw over 596 versions so far), about 1.5 KB after packing (the simulation's plain case). These listings are
4.3 MB of the 14.7 MB held loose (29%), so they are the largest single kind but not most of it. The listing grows by
about 77 bytes per file, so the cost per commit keeps growing.

A folder per commit (`.relay/checks/<sha>/gate.log`, `check.json`, `mark.json`) would cut the listing to one entry per
commit instead of up to three, but it still grows. Splitting by the first two characters of the sha (as git does with
its own objects) makes each commit rewrite the top listing (up to 256 entries of about 29 bytes, about 7.4 KB) plus one
small sub-listing. Worked values: at today's 666 files, about 7.6 KB against 51 KB (about 1/6); at 3,000 files, about
8.3 KB against 231 KB (about 1/28). That changes every reader in `relay_marks` and needs a migration (`relay check
migrate` is the precedent). It pays off when the folder passes a few thousand files (in about two weeks at the measured
150-350 files a day). LOW today because packing absorbs it.

## 2. Where the per-class times live

What the times are for: ordering only. A worker that finishes asks for the next class, and the longest classes go
first, so no worker ends with one long class while the others sit idle. Without times the design falls back to test
count. That guess is poor (measured tonight): `tests/test_installer_doctor.py::BrokenAndMissing` has 6 tests taking
about 58 s, while other classes run 14 tests in under 1 s. The results never depend on the order, as long as classes
share no state.

**What decides this question: the probe runs beside the outer run** (gate-speed design, section B). Both runs start
together and the gate waits for both, so a gate is as fast as the slower of the two. If the outer run has times and
the probe does not, the probe's count-guessed order sets the gate's time and the ordering gain is lost. So an option
gives a gain only if the probe reads the same times.

What a bad order costs is not measured. The bound is one 58 s class handed out last, which ends about 58 s after the
other workers. That is 12-17% of a 345-470 s library run at 4 jobs (an estimate built on the gate-speed design's
range).

| | A. Do nothing: `.ci/test-times.json` per worktree, ignored | B. A section of the committed gate log | C. One committed times file, rewritten by each gate | **D. One cache per machine under `$RELAY_HOME`** |
|---|---|---|---|---|
| Where | `<worktree>/.ci/` | `.relay/checks/<sha>.gate.log`, lines `time <class> <s>` before `exit`; the reader takes the newest log among HEAD's ancestors (`relay_marks.newest`) | `.relay/checks/test-times.txt` | `$RELAY_HOME/test-times/<repo>.json` (key rule below) |
| The probe (beside the outer run) | never has the file: always guesses, so **the gate gets no gain at any gate** | a strict reader sees the planted line after `exit` and guesses (no gain); a reader that skips lines it does not know gets the same times | the same as B | reads the same file: the same order as the outer run |
| Outer run at a fresh worktree's first gate | no times: at least 30% of gates (measured lower bound, 91 task branches for 307 gates) | yes, from master's history | yes | yes, after the machine's first gate |
| Fresh machine | no | yes | yes | no, for one gate |
| Git growth | 0 | +1.3 KB per gate packed (simulated), so +85-170 KB a day at 65-132 gates. The checked-out folder grows by 8.5 KB per gate, 0.55-1.1 MB a day, about 17-34 MB a month | +1.1 KB per gate packed; the checked-out file stays at about 8.5 KB | 0 |
| Parts added | the cache writer and reader | the reader of git history; either `bin/ci` prints 202 lines only under `relay gate`, or `relay gate` appends a file the command left behind (a new rule for every project's gate) | writer and reader, plus conflict handling | the same as A; only the path changes, plus one flag that keeps the probe from writing |
| What breaks | nothing; it just never helps | the gate log stops being a short summary, which every reader and checker has to read past. 99% of the stored times are dead weight: only the newest log is read | every branch rewrites the same file, so taking master into a branch conflicts whenever both sides gated, which is nearly every change. Nothing resolves inert conflicts by itself today (no merge driver, no conflict code in `merge.py`), and by the owner's rules a conflict a fixer resolves by hand sends the merge to the owner | the two runs of one gate now share one file: the outer run writes it, the probe only reads it (rules below) |
| Principles | 2 (waste): a cache that never shortens a gate | 3 holds (each log is a dated event); 2 fails (dead bytes forever) | 3 fails (a state file that is overwritten); 7 fails (conflict handling) | 7 and 2 hold; 3 is untouched (a cache, not a record) |

A fifth path from a leading tool: **pytest-split** commits a `.test_durations` file into the repository and refreshes
it only through a deliberate `--store-durations` run. Here that would be a normal, not inert, file such as
`tests/durations.txt`, refreshed by hand now and then. It travels, the probe reads it unchanged (it is not inert, so
nothing is planted in it), and it never conflicts in daily work; but it goes stale and needs someone to remember it
(new classes fall back to the count guess). One refresh command and one commit per refresh. A fair second choice if
the owner wants the times to travel without the gate log growing.

### D, the rules that make it safe

1. **Key.** `<repo>` is the folder name of the main checkout, from `git rev-parse --git-common-dir` (as
   `bin/eval-record` does; `relay_git.main_checkout` already computes it, so both use that one helper). Every worktree
   of relay resolves to `relay.json`; the worktree `.worktrees/fake-tools` does not get a `fake-tools.json` of its
   own. Two different projects with the same folder name would share a file: harmless for a hint.
2. **One writer: the outer run.** `inert_probe` adds `RELAY_INERT_PROBE=1` to the nested run's environment (beside the
   `env -u RELAY_GATE` it already uses); the runner writes times only when that is unset. The probe reads the cache and
   never writes it. Without this, the nested run (with planted lines, under the outer run's load) would overwrite the
   outer run's times.
3. **Merge, write only after a complete run.** The runner reads the cache, replaces the times of the classes it ran,
   and writes only when the library step ran every class it found; classes no longer found are dropped then. A run of
   a subset, or one that stopped early, writes nothing. The write goes to a temporary file named with the process id,
   then is renamed over the cache in one step, so a reader sees the old or the new file, never half of one. Two outer
   runs that finish at once can lose one another's update: the next gate orders a few classes by older times, nothing
   more.
4. **Tests never touch the live cache.** Every test already runs with a temporary `RELAY_HOME` (inside
   `TestCase.run`, queue item done 26 Oct); the runner's controller runs outside that, so it sees the live cache. The
   runner's own tests set `RELAY_HOME` to a temporary folder.

**Amendment the gate-speed design needs** (for the front; this design writes one file only). Section B says: "The two
runs share no writable state: each has its own worktree and `.ci/`". Under D it should read: "The two runs share one
input: the times cache in `$RELAY_HOME/test-times/`, which only the outer run writes and the probe only reads, for
ordering. Each has its own worktree and `.ci/`." This matters for the open item
`the-inert-gate-step-went-red-then-green-on-the-s`, whose first suspect is "shared state between the two runs": the
times cache is shared, but read-only for the probe and used for order only, and case 7 proves order changes nothing.

**Recommendation: D.** It rests on measured numbers: with the probe beside the outer run, A shortens no gate (by
reading `bin/ci:55`: the probe's worktree is fresh, and the gate waits for both runs); before that change A misses at
least 30% of gates (91 task branches for 307 gates). B costs 26 times the gate log (+0.55-1.1 MB a day checked out)
and needs a reader that skips unknown lines to help the probe. C conflicts on nearly every change (inferred from 1.6
gates per change on master; conflicts not counted). D adds 0 bytes and one flag. The owner's portability goal
("свежая копия relay + <project> работает одинаково на всех машинах") holds, because the order never changes a result,
only the speed of one gate on a new machine.

Settings: none new. A class missing from the cache is ordered by its test count. The tests that fail when a rule above
is false:
- "the order never changes results": case 7 of the gate-speed design (an outer run with times and a probe without
  gives `inert ok`), plus `RELAY_TEST_JOBS=1` against 4 giving the same `Ran N`;
- "only the outer run writes": a cache of 202 classes, an outer run and a probe run together; afterwards the cache
  holds the outer run's times, and a probe run alone leaves the file byte for byte unchanged;
- "a partial run keeps the others": a cache of 202 classes, a run of 30 classes; afterwards 202 classes, none changed;
- "one key per repository": the main checkout and a worktree resolve to the same file, two repositories to two files.

## 3. More artifacts per commit

What would be worth keeping:
- **Full step logs of a red gate.** Today the committed gate log keeps the step lines and up to 8 matching lines per
  failing step. The full `.ci/steps/*.log` files go with the worktree after the merge. Size: about 80 KB a run, mostly
  hook tests. A red run is 16% of gates.
- **The nested run's logs of a red probe.** `inert_probe` deletes its worktree and `nested.log` before the step
  returns (`bin/ci:69`), so only the 3-line difference survives. Live: the gate of `93e522d` (`wt/it-terms`, 25 Oct)
  was red only in `inert`, with "eval grader tests FAILED" from the nested run; the nested `eval-grader-tests.log`, the
  one log the open item `the-inert-gate-step-went-red-then-green-on-the-s` needs, is gone.
- **The traces of a red paid eval run.** Queue item `a-red-paid-run-keeps-no-traces-to-find-its-cause` (IP 93):
  `bin/ci` does not pass `--keep-temp` ("Preserve scaffold dirs for debugging"), so a red run's transcripts are
  deleted. A paid run is a full `bin/ci` started by the front, never `relay gate` (all 303 gate logs are
  `bin/ci --quick`, and the eval step runs only without `--quick`). Size and the folder `--keep-temp` uses: not
  measured.
- **Timings:** per step (already in the gate log) and per class (section 2).

What must not go into git:
- **Anything large or kept only for diagnosis.** Git never forgets: every clone carries every version, and nothing
  expires.
- **Text nobody chose.** Live: gate log `9927265…` holds one line of 61,667 characters, an `AssertionError` that printed
  a whole source file. Transcripts carry tool output, which can include environment output, so a secret could reach
  git through them. Removing it means rewriting history and rotating the key.
- **Machine details.** `/Users/...` already appears in 35 check records and 1 gate log. That works against the
  portable-tool and public-repository items in the queue.

How leading tools solve it (from their documentation, not checked live today):
- **GitHub Actions:** artifacts are uploaded outside the repository and tied to the run, kept 90 days by default
  (configurable). Caches are keyed and evicted after 7 days unused, 10 GB per repository.
- **CircleCI:** stores test timings from earlier runs outside the repository, and `circleci tests split
  --split-by=timings` uses them. The closest analogue to section 2, and it matches D: a store beside the code, not in
  it.
- **Bazel:** test logs and results stay local (`bazel-testlogs/`). The Build Event Protocol streams logs and timing
  profiles to a service (such as BuildBuddy) with its own retention. The remote cache is keyed by content hash and
  evicted by the server.
- **git notes** (`refs/notes/*`): data attached to a commit outside its file tree; Gerrit keeps review data this way.
  Notes are not fetched or pushed by default, and merging them is manual.
- **An orphan branch** (a branch with its own separate history, such as `gh-pages`): a separate history for data. It
  stays permanent and is cloned unless excluded.

| | G0. Do nothing | **G1. A per-machine store for red runs, with a time limit** | G2. Commit full red step logs into `.relay/checks` | G3. git notes or an orphan branch |
|---|---|---|---|---|
| Where | nowhere; the summary stays in the gate log | `$RELAY_HOME/artifacts/<repo>/<sha>/` with `gate/`, `inert/`, `evals/<record name>/` (rules below); nothing added to the committed gate log | `.relay/checks/<sha>/steps/*.log` | `refs/notes/relay` or a branch `relay-artifacts` |
| Size | 0 | at the default of 14 days: 16% x about 100 gates a day x about 80 KB x 14, about 18 MB, plus about 80 KB per red probe and the eval traces (not measured) | packed about 20 KB per red gate (estimate: 80 KB at about 4:1), so about 0.3 MB a day, forever | the same as G2, forever |
| Secrets and paths | none added | stay on the machine and expire | in history; the public-repository item would need a history rewrite | the same as G2 if pushed |
| Probe and inert rule | — | outside the tree; the probe does not see it, and nothing reads it for an outcome | inert; every log gets a planted line | outside the tree |
| Parts | — | one small module (path rule, copy, cleanup) and three calls to it | a copy step | a copy step, plus fetch and push setup that no agent knows today |
| What it loses | the cause of a red run once the worktree is gone (both queue items stay open) | traces older than the limit; the traces of a run made on another machine | nothing, at the cost of size and history | Git's permanence without its visibility: agents and the owner do not see notes |

### G1, the rules

- **One path rule, stored nowhere.** The folder is `$RELAY_HOME/artifacts/<repo>/<sha>/`, `<repo>` by the same key
  rule as section 2. It is derived from the sha, so no committed file names it (principle 3): a red gate's committed
  log stays as it is today and carries no home path. The rule lives once, in a small module (say
  `lib/relay_artifacts.py`: `folder(sha)`, `keep(sha, part, paths)`, `prune()`), and is written in the gate's
  docstring. `relay gate`'s reply to the caller (not committed) names the folder of a red run.
- **Three keep points, each where its run happens:**
  1. `relay gate`, after a red exit: copies the worktree's `.ci/steps/` and `.ci/results.txt` into `gate/` (not
     `ci.log`, which repeats the step logs).
  2. `inert_probe` in `bin/ci`, when the comparison differs and before it removes its worktree: copies the nested
     run's `.ci/steps/`, `nested.log` and `diff.txt` into `inert/`.
  3. The eval step of a full `bin/ci`: passes `--keep-temp`; when the run is red, the failing runs' kept folders are
     moved into `evals/<record name>/`, where `<record name>` is the eval record's file name
     (`2026-10-26T01-47-23Z-master`), so two paid runs on one commit do not collide; the rest of the kept folders are
     deleted. A green paid run keeps nothing.
- **Cleanup.** Every `keep` first removes folders older than the limit. No separate job.
- **The paid-run item's pass case** asks for "a path the record names". Under principle 3 the record (outside git, in
  `$RELAY_HOME/evals`) needs no path field: the folder follows from the record's head sha and its own file name. If the
  front prefers the literal pass case, a path field in a file outside git costs nothing in history; it is a choice
  inside the principles, not the owner's.

Setting `RELAY_ARTIFACT_DAYS`: default 14, bound 1 to 90. At 1, a red gate from Friday has lost its logs by Monday.
At 90, about 115 MB plus traces sit on the disk. The tests that fail when a rule is false:
- "a green run keeps nothing": a green `relay gate` in a temporary `RELAY_HOME` leaves `artifacts/` empty, and the
  probe's temporary worktree is still removed;
- "a red outer step keeps its logs": a red library step leaves `gate/library-tests.log`;
- "a red probe keeps the nested logs": a probe whose comparison differs leaves `inert/` with the nested
  `eval-grader-tests.log` and `nested.log`;
- "a red paid run keeps its traces": a red full `bin/ci` (with the eval tool faked) leaves `evals/<record name>/`;
- "no path is committed": a red gate's committed log holds no absolute path, and the reuse parser
  (`relay_gate.py:134-155`) still accepts red and green logs.

**Recommendation: G1.** It rests on measured numbers (16% red, about 80 KB of step logs, a 61,667-character line, 35
records with machine paths, all 303 gates `--quick`) and on one guess (the size of the eval traces). It serves both
open items: the flaky probe (keep point 2) and the red paid run (keep point 3).

The small, safe facts a later step reads on any machine (step seconds, the verdicts) stay committed as they are,
with one fix outside this design, below.

## What rests on what

Measured: everything in the Measurements table, the packing simulation, the 16% red share, the 1.6 gates per check on
master, 307 gates against 91 task branches. Read from the code: the probe's fresh worktree and its cleanup
(`bin/ci:53-69`), the gate log writer (`lib/relay_gate.py:234`), the repository key (`bin/eval-record:164`). Not
measured: the gain from ordering by times (a bound of 12-17% of the library run), the conflict rate under C, the size
and location of the eval tool's kept folders, and the leading tools' current retention numbers (from documentation).

## Critique of the brief's pick

The pick carried in from the gate-speed design is the ignored `.ci/test-times.json` per worktree. It is weak, and
weaker than revision 1 said: that same design runs the probe beside the outer run in a fresh worktree, so the probe
never has the file and the gate never gets faster from it (0% of gates); even with the probe in series, at least 30%
of gates are a worktree's first and miss. Moving the cache to `$RELAY_HOME` with a read-only probe keeps every other part
of the design.

## Answers to the review

| Finding | Holds? | What changed |
|---|---|---|
| F1 (MEDIUM) the probe and the outer run share a writable file under D | yes | D rule 2: only the outer run writes (`RELAY_INERT_PROBE=1`); the probe reads. The amendment for the gate-speed design's "share no writable state" line is written out in section 2, with its test |
| F2 (MEDIUM) the 61% was not measured and misses the parallel probe | yes | 61% replaced by the measured lower bound of 30% (91 task branches, 307 gates); the parallel probe is now the deciding point: A gives 0% gain, B and C help only with a lenient reader |
| F3 (MEDIUM) no paid run goes through `relay gate` | yes | G1 split into three keep points; the paid-run traces are kept by `bin/ci`'s eval step, under the eval record's name |
| F4 (MEDIUM) a red probe deletes its nested logs before any copy | yes | keep point 2: `inert_probe` copies the nested `.ci/steps`, `nested.log` and `diff.txt` before cleanup, with the `93e522d` case as its test |
| F5 (MEDIUM) the committed `artifacts <path>` line repeats derivable data and adds home paths | yes | the line is dropped; one path rule derived from the sha; the gate's uncommitted reply names the folder |
| F6 (LOW) D's key undefined | yes | D rule 1: the main checkout's folder name, through `relay_git.main_checkout`, shared with `bin/eval-record` |
| F7 (LOW) a partial run wipes other classes' times | yes | D rule 3: merge, write only after a complete run, temporary file named with the pid |
| F8 (LOW) the side finding's numbers | yes | 29% share of loose data stated; the split's saving given as 1/6 now and 1/28 at 3,000 files, with the arithmetic |
| F9 (LOW) the gate log is the whole quiet output, lines uncut | yes | section 1's row and section 3's "today" line corrected |
| F10 (MEDIUM, outside) copied failure lines are not cut in length | yes | a fix item for the front, below; not this design's change |

## For the front (inside the principles, the owner can reverse)

1. **Fix item, MEDIUM (from F10): cut the failure lines the gate log copies.** `bin/ci:27` copies up to 8 matching
   lines per failing step, whole, into the quiet output, and `relay gate` commits it; gate log `9927265…` holds a
   61,667-character line. Cut each copied line to 300 characters with a `... (<n> more)` tail; the full text stays in
   `.ci/steps/` and, under G1, in the store. Setting: default 300, bound 80 to 2,000. At 80 a typical
   `FAIL: test_x (tests.test_mod.Class.test_x)` line of 70-100 characters loses its class name; at 2,000 one failing
   step can still commit 16 KB. Test: a step log with a 61,667-character FAIL line gives a gate-log copy of at most
   300 characters plus the tail; short lines are unchanged; the probe's comparison is unaffected (it reads
   `results.txt` and the step logs, not this copy).
2. **Fix item, LOW: the `.relay/checks` listing.** Rewritten by every commit (51 KB, about 77 bytes more per file).
   Split it by sha prefix when it passes a few thousand files: the saving grows from 1/6 now to about 1/28 at 3,000.
3. **The gate-speed design's line on shared state** needs the amendment in section 2 once the owner picks 1 a.

## Open for the owner

1. **Where the test times live.** The faster gate hands test classes to 4 processes longest first, using last run's
   times; the order only changes speed, never a result. The faster gate also runs its probe (the second run that
   proves inert files decide nothing) at the same time as the main run, in a fresh copy, and waits for both, so only
   times the probe can read make the gate faster. You asked why not keep them in `.relay/checks`: it works, at the
   cost below.

   | | Gate faster from times | Git growth | New machine |
   |---|---|---|---|
   | a) one file per machine in `$RELAY_HOME` | yes, at every gate after the machine's first | 0 | first gate in today's order |
   | b) a section of each committed gate log | yes, if its reader skips the probe's planted lines | gate log 335 bytes to 8.9 KB; +0.55-1.1 MB a day in the folder | works at once |
   | c) as designed, a file inside each task's copy | never (the probe's fresh copy has no file) | 0 | — |

   a) per machine (recommended); b) in the committed gate logs; c) as designed.

2. **Where a red run's full logs and eval traces go.** Today they are lost: the gate's step logs when the task's copy
   is removed, the probe's logs at once, the paid run's transcripts at the end of the run. On the machine they stay out
   of git and expire after a set number of days; in git they stay forever and travel, with whatever the logs printed
   (one red log already holds a 61,667-character line).
   a) on this machine for 14 days (about 18 MB plus traces), found from the commit (recommended);
   b) committed into `.relay/checks`: about 0.3 MB a day forever, machine paths and anything printed go into history;
   c) nothing: both open items (the flaky probe, the red paid run) stay without their causes.
