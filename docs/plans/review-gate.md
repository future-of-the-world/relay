# Review gate, worktree cleanup, work queue: part 2 design (v4)

Project: relay, the owner's kit of Claude Code rules, typed agents, flows and
hooks that `relay sync` writes into every project. This is the design for
"merge 2" of batch 3; a worker builds from it alone. Part 1 (shared role
texts, the judge's review and check method, `delegate:checker`, the inert
list and `relay changed`) is built and merged into master at 0538b8d and is
not redesigned here; where part 2 changes a part 1 text, the change is named.

It replaces part 2 of design v3 (`design-role-bases-v3.md` sections 7.6,
7.7, 8, 9, 12 "Merge 2", the T/K/G/Q tests, the 8.7 seeds) and folds in the
owner's later pipeline. Read-only on code; written in worktree
`.worktrees/review-gate`, branch `wt/review-gate` (master 0538b8d plus a
handover commit).

Contents: 0 what changed from v3; 1 terms; 2 facts; 3 the pipeline; 4 what
is stored; 5 the gate command; 6 check marks; 7 merge refused (M-A, M-B,
m-1); 8 the person's step; 9 the guard rule (m-3); 10 the work queue (m-4,
seeds); 11 worktree cleanup; 12 tests; 13 proof plan; 14 build plan;
15 what v3 parts are dropped; 16 critique; 17 questions for the owner;
18 what the brief could not answer.

## 0. What changed from v3

| # | Change | Why | Section |
|---|---|---|---|
| 1 | The owner's pipeline: free code checks first, then the review, its findings stored in git as `file:line: severity: message` lines, then the person's step, then the merge | owner, 22 Oct | 3, 4, 8 |
| 2 | Review, check report and gate log are committed beside the mark: `.relay/checks/<sha>.review.md`, `<sha>.check.md`, `<sha>.gate.log`, `<sha>.json` | owner | 4, 6 |
| 3 | New command `relay gate`: code, not an agent, runs the gate and commits its log; a runner only starts it | the gate log is evidence the merge trusts, so code writes it, as for marks | 5 |
| 4 | M-A fixed: a task branch takes the default branch by a merge commit (never a rebase); `relay changed --own` leaves out files that came in from the default branch; the gate runs again (free) when such files are code; a branch behind the default is refused with a clear message | check-design-v3 M-A | 7.2, 7.3 |
| 5 | M-B: the merged judge base already compares the gate log's head to HEAD by `relay changed` (`roles/judge.md:91-101`); part 2 adds the same rule to the merge hook and test T15 (l) | check-design-v3 M-B | 7.4 |
| 6 | The mark search is a list of marks, not v3's walk (a walk stops at the first merge commit from the default branch) | follows from 4 | 7.1 |
| 7 | m-1 fixed: the merge hook refuses a branch that closes a `fix` queue item without a test | cheap: the hook already lists the range | 7.5 |
| 8 | m-3 fixed: the guard's text rule on `.relay/checks` covers writes and inline code only; reading the stored review with `cat` or `grep` is allowed | reviewers must read stored reviews now | 9 |
| 9 | m-4 fixed: `relay queue take` lands `state: taken` on the default branch | cheap: reuses the landing path | 10.3 |
| 10 | The person's step: one chat screen plus a private page built by code from the stored files | owner | 8 |
| 11 | Seeds: v3's 12 plus the handover's later list and check-judge-fix L1-L3, deduplicated: 22 items | owner "a" | 10.6 |
| 12 | Phase-1 seed texts follow the owner's 22 Oct phase-1 decisions (old projects not touched, thin OpenSpec add-on, one shared cycle) | owner | 10.6 |
| 13 | Shared helper `lib/relay_git.py` (default branch, main checkout, `.relay/` present): `relay_setup.default_branch` returns the worktree's own branch when run in a worktree without `origin` | fact 2.8 | 2, 7 |

## 1. Terms (each defined once)

- **Default branch**: the branch merges go into; relay's is `master`. Found
  by `relay_git.default_branch(repo)`: the target of `refs/remotes/origin/HEAD`,
  else whichever of `master` or `main` exists as a local branch, else an
  error. Never the current branch (fact 2.8).
- **Task branch**: `wt/<name>`, the branch of one worktree, where a change is
  built. Queue branches `wt/queue-<slug>` are not task branches.
- **Main checkout**: the folder holding the repository's `.git` (parent of
  the git common dir), kept on the default branch and clean.
- **Inert file**: a file on the fixed list in `lib/relay_inert.py`:
  `docs/handover.md`, `.relay/queue/**`, `.relay/checks/**`. State, not code:
  no test or check outcome depends on its content (test A11).
- **Own files** of a branch between two of its commits `S` and `T`: the
  non-inert files that changed from `S` to `T` because of the branch itself,
  not because the branch took the default branch (exact rule in 7.2).
  Printed by `relay changed --own`.
- **Gate**: the project's full set of free code checks (relay: `bin/ci
  --quick`, see question 1), run by `relay gate`. Its **gate log**
  `.relay/checks/<G>.gate.log` starts with `head <G>` and ends with
  `exit <n>`; `<G>` is the commit the gate ran on.
- **Review**: the one whole-change review by the judges (critic, sdd
  reviewers), each finding with a failing case and pass-cases (part 1).
  Stored as `.relay/checks/<R>.review.md`, `<R>` the reviewed commit.
- **Linter line**: the first line of every finding, `<path>:<line>:
  <SEVERITY>: F<n> <what goes wrong>`, for example
  `lib/relay_inert.py:51: MEDIUM: F2 a merge commit from master lists master's files`.
  Editors and terminals open `path:line` directly.
- **Check**: `delegate:checker` comparing a fix with the findings' cases; its
  report ends with the **verdict** (`head`, `reviewed`, `open`, `queued`).
  Stored as `.relay/checks/<X>.check.md`, `<X>` the checked commit.
- **Check mark** (mark): `.relay/checks/<X>.json`, written and committed by a
  hook when `delegate:checker` finishes. Only `lib/relay_marks.py` reads or
  writes marks.
- **Full sha**: 40 hexadecimal characters; every name, field and message
  uses it, never an abbreviation.
- **Behind**: a task branch is behind when the default branch's head is not
  one of its ancestors; `git merge --ff-only` then fails.
- **Queue item**: `.relay/queue/<slug>.md`, kind `fix` (something wrong, with
  its failing case) or `feature`; ordered by **ip** (important points,
  integer >= 0, highest first).
- **The person's step**: one chat screen and one private page (a claude.ai
  artifact) from which the owner decides the merge.
- **`.relay/`** is a committed folder in a project (queue, checks); created
  only by `relay setup`. **`~/.relay`** is per machine, never committed
  (ledger, bench results). The hard rules of this design act only in a
  repository whose default branch has `.relay/`.

## 2. Facts (checked on the merged code, master 0538b8d)

1. The one merge the guard allows in the main checkout is `git merge
   --ff-only wt/<name>` with one positional argument
   (`plugins/core/lib/kit_guard.py:405-410`, the regex at 408); `git -C
   <dir>` is applied by `git_parts` (`kit_guard.py:367-382`). Mutating git
   inside a worktree is allowed (`guard-main.sh:188-192` blocks only in main).
2. `guard-main.sh:60-61`: `anchor="${CLAUDE_PROJECT_DIR:-$cwd}"`, then `git
   -C "$anchor" rev-parse ... || exit 0`: a deleted anchor makes the guard
   allow everything (v3's M3; fixed in 11.2). Write/Edit are judged at
   `guard-main.sh:108-115`, Bash write rows `W` at 176-183.
3. Core's `hooks.json` registers `PreToolUse` (guard), `SubagentStart`,
   `UserPromptSubmit` and `PostToolUse` on `Skill` only; no `SubagentStop`,
   no `SessionStart`, no Bash `PostToolUse`. The front's `hooks.json` has
   `SessionStart` -> `plugins/front/hooks/handover.py` (timeout 5 s).
4. `lib/relay_inert.py:11-15` holds the fixed list; `changed(repo, since,
   until="HEAD")` (48-55) lists non-inert files of `git diff --name-only
   --no-renames since..until`. `bin/relay:408-415` is `relay changed [-C
   <repo>] <sha>`. There is no `--own` and no copy in `plugins/core/lib/`.
5. The judge base's check mode (`roles/judge.md:71-120`): step 1 uses `relay
   changed -C <path> <Reviewed sha>`; step 2's gate rule (91-101) already
   says the gate's sha is HEAD "or `relay changed -C <path> <sha>` lists no
   file" (M-B's text fix, made in merge 1); step 7 counts `queued` only "when
   the project has a work queue".
6. `plugins/delegate/agents/checker.md`: prompt line `Check: ... Fixes: ...
   Worktree: ... Check command: ... Gate: <log or none>. Report: <path>.`;
   verdict of five lines; "where the project has check marks, a hook adds it
   when you finish". The delegate skill's Review loop
   (`plugins/delegate/skills/delegate/SKILL.md:79-143`) has the seven steps,
   the gate log format `{ echo "head $(git rev-parse HEAD)"; <gate>; echo
   "exit $?"; } > <log>` (101-108) and "Commit the handover after the
   check" (110-111).
7. `bin/ci` (51 lines): `--quick` runs the free steps (library tests, hook
   tests, lib copies identical, grader tests, plugin validate); without it,
   also the paid plugin evals (`--max-cost-usd ${EVALS_MAX_COST:-15}`, judge
   Sonnet). The last full run cost $4.99 (18 runs). Hook tests run every
   `plugins/*/tests/*.test.sh` except a deny list (`bin/ci:25`):
   `hooks-live`, `packet`, `check-contract`, `shim`, `spec-check` and
   `inject-addition`, which run only with `RELAY_CORE_TESTS=1`. So part 1's
   per-role tests I1-I9 (in `inject-addition.test.sh`) are not in the gate.
   New `merge.test.sh` and `check-mark.test.sh` run in every gate unless
   added to that list. `lib copies identical` checks every
   `plugins/<p>/lib/relay_*.py` against `lib/` automatically.
8. `lib/relay_setup.py:59-67` `default_branch(root)`: `origin/HEAD`, else
   `git rev-parse --abbrev-ref HEAD`. Relay has no remote (`git remote -v`
   is empty), so in `.worktrees/review-gate` it returns `wt/review-gate`.
   Part 2 code must not use it; it uses `relay_git.default_branch` (term 1).
9. The ledger hook already finds an agent's transcript on `SubagentStop`:
   `agent_transcript_path`, else `<session transcript>/subagents/agent-<id>.jsonl`
   (`plugins/observe/hooks/ledger.py:90-96`).
10. Relay has no `.relay/` folder and no `.claude/kit.toml`; the gate binding
    `gate.ci` defaults to `bin/ci` (`plugins/core/README.md:199`).
11. v3 F.9 (live, 21 Oct): every typed agent's `SubagentStop` carries
    `agent_type`, `agent_id`, `cwd`; 369 untyped stops of unknown origin
    exist; a rule on `agent_type == "delegate:checker"` ignores them.

## 3. The pipeline (owner, 22 Oct)

Owner, verbatim: "Code checks run first - it's free / Then they passes - run
review step, that have result and can store artifacts (like linter message
with link to wrong places) / If review passes - we can proceed". Gate local,
no Woodpecker. Merge refused unless the gate exits 0, the mark says `open 0`,
and the owner says so.

| Step | Who | What is stored on the task branch | Cost (agent min, money) |
|---|---|---|---|
| 1 Build | worker | code commits | per brief |
| 2 Gate | runner starts `relay gate`; red goes back to the worker or a fixer, then 2 again | `<G1>.gate.log` | 2-4 runner, free |
| 3 Review | judges, once, over `<default>...HEAD`, only after a green step 2 | (copied in step 6) | 15-20 |
| 4 Fix | fixer, when HIGH or MEDIUM inside the change | fix commits | 10-15 |
| 5 Gate again | runner, `relay gate`, when step 4 made commits | `<G2>.gate.log` | 2-4, free |
| 6 Check | `delegate:checker`; the finish hook commits the mark with the review and the check report | `<X>.json`, `<X>.check.md`, `<R>.review.md` | 3-5 |
| 7 Take the default branch | runner, `git -C <wt> merge --no-edit <default>`, only when the branch is behind; `relay gate` again when code came in (7.3) | a merge commit; maybe `<G3>.gate.log` | 1, or 3-5 |
| 8 The person's step | front: one chat screen, one private page (8) | nothing | 1-2 |
| 9 Merge | front, on the owner's word: `git merge --ff-only wt/<name>` in the main checkout; the merge hook refuses unless 7.1 holds; the cleanup hook removes the worktree | the files arrive on the default branch | 0 |

A review with nothing inside the change goes from step 3 to step 6 with
`Fixes: none` (the gate log of step 2 is the gate). Step 7 can come any
time before step 9; when the default branch has not moved, it is skipped.

Why step 2 is before the review: a red build reviewed is 15-20 minutes of
the big model on code that will change; the gate is free. Why the gate runs
again in step 5: the fix is new code. Why the commits of steps 2, 5 and 6 do
not need another check: they hold only inert files.

## 4. What is stored, and in what form

### 4.1 The folder `.relay/checks/` on the task branch

| File | Named by | Written by | Content |
|---|---|---|---|
| `<G>.gate.log` | the commit the gate ran on | `relay gate` (5) | `head <G>`, `cmd <command>`, the gate's own output (quiet: one line per step), `exit <n>` |
| `<R>.review.md` | the reviewed commit (`Reviewed:` sha) | the check hook (6), copied from the findings files the checker's prompt names | the findings files, joined, each under `# <file name>` |
| `<X>.check.md` | the checked commit (`head` of the verdict) | the check hook, copied from the checker's report | the report, ending in the verdict |
| `<X>.json` | the checked commit | the check hook | `{"commit": X, "verdict": {"open": n, "queued": m, "reviewed": R}, "review": "<R>.review.md", "check": "<X>.check.md", "gate": "<G>.gate.log", "time": "<iso>"}` |

In the common case `G = X` (the gate ran on the fixed head and the check on
the same head), so a change carries `X.gate.log`, `X.check.md`, `X.json`
and `R.review.md`: the owner's four names. A file is named by the commit it
is about, so nothing is renamed when a handover commit lands between steps.

Size: relay's quiet gate output is about 15 lines (1 KB); a review 10-30 KB;
a check 3-10 KB. About 20-50 KB per change, kept in history after the merge
(about 5 MB per 100 changes). Nothing is pruned (the history keeps it
anyway).

### 4.2 The linter form

Part 1's judge base asks for `F<n>, severity, where (file:line)`. Part 2
changes `roles/judge.md` "Each finding" so that every finding starts with one
linter line (term 1), then the fields as today (failing case, pass-cases,
CONFIRMED or PLAUSIBLE, size, smallest fix):

```
lib/relay_inert.py:51: MEDIUM: F2 a merge commit from master lists master's files as the branch's own
Failing case: ...
```

- `<path>` is relative to the repository root; `<line>` is the line in the
  reviewed commit; a finding about a whole file or a missing file names line
  1 of the file that should hold the fix. Severity is `HIGH`, `MEDIUM` or
  `LOW` (spec-reviewer keeps `BLOCKER`, `FIX`, `NIT` as today, mapped in its
  flow part).
- Findings outside the change use the same line under `## Outside this
  change`.
- The checker gives each finding one status line: `F2 MET tests/test_inert.py:88`
  or `F2 NOT MET <why>`; the page (8) reads these.

Links: relay has no web forge (no remote), so a link is the `path:line`
text itself, which the terminal, Claude Code and editors open. The page (8)
shows, under each linter line, the five lines of code around it at the
reviewed commit, so the owner does not need to open anything.

The existing eval grader `names-file-and-line` matches `src/shelf.ts:27`,
which the linter line still contains; the paid run of 13.2 confirms the
judges still pass with the new first line.

## 5. The gate command, `relay gate`

`relay gate [-C <worktree>] [-- <args>]`, code in `lib/relay_gate.py`:

1. Refuses where the default branch has no `.relay/` ("run relay setup here
   first"), in the main checkout ("the gate runs on a task branch"), and in
   a worktree with tracked changes or untracked files that are not ignored
   ("commit first: the gate must run on a commit"; the log names a commit,
   so the code it ran must be that commit).
2. `G = git rev-parse HEAD` (full). Runs the binding `gate.ci` (`kit get
   gate.ci`, default `bin/ci`) with `<args>`, in the worktree, output to
   `<worktree>/.ci/gate.out` (ignored), no timeout of its own.
3. Writes `.relay/checks/<G>.gate.log`: `head <G>`, `cmd <the command line>`,
   the output, `exit <n>`; commits only that file with `relay_marks.commit_file`
   (the same `--only`, `--no-verify`, retry path as marks; message
   "relay: gate of <G>", no tool attribution).
4. Prints three lines: `gate <G>: exit <n>`, the log path, and the first
   failing step's lines when red. Exit status = the gate's.

A runner starts it detached with the limits recipe when the gate can take
over 4 minutes. For relay the coordinator passes the arguments question 1
decides (recommended: `relay gate -- --quick`).

The checker's prompt names the log in the worktree: `Gate:
<worktree>/.relay/checks/<G>.gate.log`. The judge base's gate rule (fact
2.5) applies as merged; the remote-pipeline form stays for other projects.

Why code and not a runner's redirect (v3): the merge trusts the log, and a
runner could write a log for the wrong commit or one that never ran. Here
`head` is read by the code that ran the gate, and the guard (9) refuses any
agent's write to `.relay/checks/`.

## 6. Check marks, written by a hook (v3 7.7, revised)

Unchanged from v3: the checker writes only its report; a `SubagentStop`
hook copies its verdict into a committed mark; no model writes a mark or
decides which later commits keep it. New: the hook also copies the review
and the check report into `.relay/checks/`, so they outlive the scratchpad.

`plugins/core/hooks/check-mark.py`, registered under `SubagentStop` in
core's `hooks.json`, timeout 10 s, always exit 0 (it never blocks):

1. Does nothing unless `agent_type` is exactly `delegate:checker` and the
   worktree's repository has `.relay/` on its default branch (untyped stops,
   fact 2.11, are ignored by this rule).
2. Finds the agent's transcript as `ledger.py:90-96` does (fact 2.9), reads
   its first line (the prompt) and parses the labels `Check:`, `Worktree:`,
   `Gate:`, `Report:`; that line's `timestamp` is the agent's start.
3. Reads the report; takes its last `## Verdict` block; requires its four
   lines, `head` and `reviewed` as full shas that resolve in the worktree
   (an abbreviation is refused), `head` equal to the worktree's HEAD or an
   ancestor of it, and the report's mtime after the agent's start.
4. Copies the findings files of `Check:` into `.relay/checks/<reviewed>.review.md`
   (replaced when it exists with other content: a re-check after
   `Owner: F3 is not wrong` carries that line), the report into
   `<head>.check.md`, writes `<head>.json` (4.1), and commits the two or
   three files in one commit, "relay: check of <head>", with
   `relay_marks.put`.
5. On any failure it writes no mark, removes an existing mark for that head
   (a stale clean mark never outlives a failed re-check), and says in
   `systemMessage`: "check mark not written for wt/x: <reason>".

`lib/relay_marks.py` (copied to `plugins/core/lib/`; `bin/ci` checks the
copy, fact 2.7) is the only code that touches `.relay/checks/`:
`put(worktree, commit, mark, files)`, `commit_file(worktree, path,
message)`, `get(repo, ref, commit)`, `drop(worktree, commit)`,
`marks(repo, ref) -> [(commit, mark)]`, `gate_logs(repo, ref) -> [(commit,
exit)]`. Commits are `git -C <wt> add -- <files>`, then `git -C <wt>
commit --no-verify --only -m <message> -- <files>`: other staged changes
stay staged and out; the project's commit hooks do not run; no tool
attribution. A locked index: wait 1 s, retry, `MARK_COMMIT_RETRIES = 3`
(constant, bound 1-8: at 8 the waits take 8 s, the most the 10 s hook
timeout leaves room for), then "index busy" and no mark (the merge then
refuses "no check mark" and the checker is run again).

What follows (v3, still true): a mark travels with the branch; the mark's
own commit is inert, so it keeps the mark valid; a rebase or amend after
the check changes the checked sha and needs a new check (3-5 agent minutes)
and a new gate; 1-3 mark commits per change.

## 7. Merge refused (v3 7.6, revised)

`plugins/core/hooks/merge.py`, `PreToolUse` on Bash, behind the cheap
prefilter of 11.1 (`merge.sh` exits at once unless the input contains
`merge`). For each merge `wt/<name>` that the guard allows
(`kit_guard.allowed_merges`, 11.1), in a repository whose default branch
`D` has `.relay/`; elsewhere it does nothing and prints nothing.

### 7.1 The rule, in order (the first that fails refuses, exit 2, one line)

| Step | Test | Refusal (shas in full) |
|---|---|---|
| 1 | `D` is an ancestor of `wt/x` (`git merge-base --is-ancestor D wt/x`) | "merge refused: wt/x is behind master by 2 commits; take master first: git -C .worktrees/x merge --no-edit master (then relay gate if code came in)" |
| 2 | every file of `git diff --name-only D...wt/x` is inert: allow now (a handover-only branch) | (none) |
| 3 | a mark: among `relay_marks.marks(repo, wt/x)`, keep those whose commit `X` is an ancestor of `wt/x` and not of `D`; pick the newest `X` (topological order) with `relay changed --own X wt/x` empty | none at all: "merge refused: no check mark for wt/x (run delegate:checker on its head)"; marks but none current: "merge refused: after the check of <X>, wt/x changed lib/a.py, which is not inert; check again" (the newest mark's list, at most 5 names) |
| 4 | that mark's `verdict.open` is 0 | "merge refused: the check of <X> left 2 things inside the change wrong (report: .relay/checks/<X>.check.md)" |
| 5 | a gate: among `relay_marks.gate_logs(repo, wt/x)`, one whose commit `G` is an ancestor of `wt/x`, with first line `head <G>`, last line `exit 0`, and `relay changed G wt/x` (every non-inert file, no `--own`) empty | "merge refused: no green gate for the code at wt/x's head (last gate <G>: exit 1, or: code changed since: lib/b.py); run relay gate in .worktrees/x" |
| 6 | every file the range adds under `.relay/queue/done/` with `kind: fix` and `state: done` has a `test: <file>::<name>` line, `<file>` exists at `wt/x` and holds `<name>` | "merge refused: queue item core-tests-not-in-gate is closed without a test (relay queue done --test ...)" |
| 7 | allow | |

The owner's word is not in this table: a hook cannot tell an owner's "a" in
answer to "merge?" from an "a" to another question, and the owner writes
in any language (critique 16.3). It stays the rule it is today: the front
runs step 9 of the pipeline only on the owner's word in this conversation.

Step 3 replaces v3's walk. v3 walked `D..wt/x` newest first and stopped at
the first commit touching a non-inert file without a mark; after step 7 of
the pipeline the newest such commit is the merge commit from master, whose
diff to its first parent shows master's files, so the walk found no mark
and refused every branch that had taken the default branch. Listing the
marks (usually 1-3 per branch) and asking `--own` for each has no such
case.

### 7.2 How a task branch takes the default branch (M-A)

Decided: by a merge commit, `git -C <worktree> merge --no-edit <default>`,
run by a runner; never `git rebase`. A rebase gives every commit a new sha:
the mark names the old one, so every rebase costs a new check (3-5 agent
minutes) and a gate, and a branch can be rebased several times a day once
queue items land on master at once (owner's q3). A merge keeps every sha,
so the mark still names a commit on the branch.

What the mark and `relay changed` do with files that came in from the
default branch: they leave them out, by this rule (`relay_inert.changed(repo,
since, until, own=True)`, printed by `relay changed --own [-C <repo>]
<since> [<until>]`, `<until>` defaulting to HEAD):

- `B_S` = merge-base(`since`, `D`): the default-branch commit the branch
  stood on at `since`. `B_U` = merge-base(`until`, `D`): the one it stands
  on now (the master commit it merged, or the old one if it merged none).
- A non-inert file `p` of `git diff --name-only since..until` is left out
  exactly when the branch had not touched it at either end: `p` at `since`
  equals `p` at `B_S`, and `p` at `until` equals `p` at `B_U` (blob ids from
  `git ls-tree -r`, four trees, one call each; missing on both sides counts
  as equal).

Worked values (relay's own case: `wt/review-gate` checked at `X`, then a
batch that changed `lib/relay_queue.py` merged into master, then the branch
merges master as `Y`):

| File | at `B_S` | at `X` | at `B_U` | at `Y` | Listed by `--own X Y`? | Why |
|---|---|---|---|---|---|---|
| `lib/relay_queue.py` | v1 | v1 | v2 | v2 | no | only master changed it |
| `.relay/queue/foo.md` | none | none | new | new | no | inert anyway |
| `lib/relay_marks.py`, changed by the branch before `X`, untouched after | none | a | none | a | no: not in the `X..Y` diff | the checked code |
| `plugins/core/hooks/merge.py`, edited by the branch after `X` | none | a | none | b | yes | new code after the check |
| `lib/relay_inert.py`, fixed before `X`, then the fix reverted | v1 | v1+fix | v1 | v1 | yes | at `X` the branch had touched it: a revert of a checked fix is listed |
| `bin/relay`, changed by both, merged by git without conflict | v1 | v1+a | v2 | v2+a | yes | the combined file is code nobody checked |

Without a merge from master `B_U = B_S`, and the rule lists exactly what
today's `changed` lists (a file equal at both ends is not in the diff).

Where `--own` is used, and where it is not:
- the checker's step 1 (fix range and scope): `relay changed --own -C <path>
  <Reviewed sha>` (part 2 edits `roles/judge.md:76`). Without it, a fix
  checked after the branch took master would list master's files as "NOT
  MET (scope)";
- the merge hook's step 3 (mark still current);
- not for the gate (step 5, and the judge base's gate rule): the gate must
  have run on all the code at the head, master's included.

The other choice the check named, "accept a re-check", does not work on
its own: the checker's step 1 would list master's files the same way and
count them as out of scope or "changed since the review", so the re-check
fails too unless it has this rule. With the rule, a re-check is needed only
when the branch's own files changed.

Cost per merge of the default branch into a task branch (agent minutes):

| What came in | Chosen: `--own` and a re-gate | Re-check every time | Rebase |
|---|---|---|---|
| only queue items (the common case: `relay queue add`) | 1 (the runner's merge) | 1 + 3-5 check | 1 + 3-5 check + 2-4 gate |
| code from another merged change | 1 + 2-4 gate (free) | 1 + 2-4 gate + 3-5 check | same |
| a conflict, resolved | fixer 5-10 + gate 2-4 + check 3-5 | same | same, plus all marks lost |

A conflict resolution is a fix: the coordinator writes a one-finding file
(`Reviewed: <head before the merge>`, `<file>:<line>: MEDIUM: F1 conflict
with master resolved`, failing case "the gate fails or the merge does not
apply", pass-case "the gate passes"), a fixer resolves, `relay gate`, then
the checker; its `--own` list is the resolved files, which F1 names, so
scope holds.

### 7.3 The walk-through of v3 7.6, corrected (M-A)

`wt/x` at `X`; the critic finds a wrong thing outside the change.

1. `relay queue add --from <report> F7` lands `.relay/queue/<slug>.md` on
   master at once (10.4): master moves from `M` to `Q`.
2. The checker checks `X` (`open 0`); the hook commits `X.json`, `X.check.md`,
   `R.review.md` as `X+1`; the gate log `X.gate.log` was committed before.
3. The handover is committed: `X+2`.
4. The owner says merge. `git merge --ff-only wt/x` in main: refused by step 1,
   "wt/x is behind master by 1 commit ...". (v3 said "the merge passes"; git
   itself would have answered "Not possible to fast-forward".)
5. A runner: `git -C .worktrees/x merge --no-edit master` -> `Y` (brings only
   `.relay/queue/<slug>.md`).
6. The merge again: step 2 no (code in the range); step 3 `--own X wt/x`
   empty -> mark `X`; step 4 open 0; step 5 `relay changed X wt/x` lists
   nothing (only inert files after `X`) -> the gate of `X` counts; step 6
   nothing closed; allowed. Fast-forward succeeds (`Y` contains `Q`).

Variant: master also received `lib/b.py` from another change. Step 5 refuses
"code changed since: lib/b.py; run relay gate"; the runner runs `relay
gate` on `Y` (log `Y.gate.log`, commit `Y+1`); the merge passes with the
same mark `X`. A commit touching `lib/a.py` on the branch after `X` is
refused by step 3, "check again".

### 7.4 M-B: the gate's head and the commits after it

The merged judge base already accepts a gate log for commit `F` when
`relay changed -C <path> F` lists no file (fact 2.5). The merge hook uses the
same rule (7.1 step 5). The case the check named, now test T15 (l): the
gate log is for `F`; HEAD is `F` + the mark commit + a handover commit; the
mark says `open 0`; the merge is allowed. Same with the checker: a re-check
after `Owner: F3 is not wrong` reads the same gate log and does not count it
as "another head" (the judge base text, unchanged).

### 7.5 m-1: a `fix` item closed without its test

v3 enforced the test only in `relay queue done`. A hand move of the item
file into `done/` skipped it. Step 6 of 7.1 closes that: the merge that
closes a `fix` item needs the `test:` line, and the test name present at the
branch head. Whether that test fails without the fix stays the checker's
job (judge base step 2, `From queue:`); the hook only refuses a close with
no test at all. Cost: one `git show` per closed item in the range.

### 7.6 Where the hard rules act

Every repository whose default branch has `.relay/` (`git cat-file -e
<default>:.relay`, read from git, so the main checkout and every worktree
agree). `.relay/` is created only by `relay setup` (it writes
`.relay/README.md` saying what the folder turns on; the front asks the
owner before running it in a project). Every relay command that writes into
`.relay/` (`relay gate`, `relay queue add|take|done|drop|ip|land`) refuses
where the default branch has none. Read-only commands (`relay changed`,
`relay queue`, `relay queue count`, `relay check show`, `relay check page`)
work everywhere. In batch 3 only relay gets `.relay/` (part C2); ALIX, the
Glonass repositories and the old projects (Kartoteka, principles) do not.

## 8. The person's step: one chat screen and a private page

Owner: "one chat screen + a private page (claude.ai artifact)".

### 8.1 The page, built by code

`relay check page [-C <repo>] <branch> [-o <file>]` (`lib/relay_checkpage.py`)
reads only the files in `.relay/checks/` at the branch head and git, and
writes one Markdown file (default `<scratchpad or .ci>/page-<name>.md`):

1. Title: the project and the branch's purpose (the first line of the
   newest `R.review.md`'s heading, else the branch name).
2. Verdict line: "Free checks: green (gate of <date>). Review: 3 found
   inside the change, all fixed and checked; 2 outside, queued. Open: 0."
3. Each finding: its linter line, the checker's status line (`MET
   tests/...:88` or `NOT MET ...`), the five lines of code around
   `path:line` at the reviewed commit (`git show R:<path>`), and the failing
   case in one paragraph.
4. Outside the change: linter line and the queue item's slug (from the
   default branch), or "not queued".
5. The gate: the step lines of the newest green gate log.
6. The branch's own files with their line counts (`git diff --stat
   D...<branch>`).

`PAGE_MAX_LINES = 400` (constant; bound 100-2000). At the bound the rest is
cut with "N more findings in .relay/checks/<R>.review.md". A page over the
bound costs the front about 6-8 thousand tokens to publish (8.3).

### 8.2 The chat screen

The front's reply when a branch is ready (the front skill gains this
section, "A change ready to merge"), at most one screen:

```
relay (the owner's kit of rules and agents): the review gate is ready to merge.
What it does for you: a merge is refused until the free checks pass and the
review's findings are fixed and checked; merged worktrees are removed.
Checks: free checks green. Review: 3 inside the change, all fixed and checked;
2 outside, added to the work queue. Page: <link>
1. Merge it now?
   a (recommended) merge   b hold (say what to change)
```

The numbers come from `relay check show <branch>` (three lines: gate, mark,
outside items), run by a runner; the front never reads the stored files.

### 8.3 Publishing the page

The front publishes the page file as a private claude.ai artifact and puts
the link in the chat screen. Whether the coordinating session in Claude
Code has an artifact tool, and whether a subagent can publish one, is not
known from here (an overview page was published on 22 Oct, by a means the
handover does not record): the worker of part B6 confirms it live. When no
tool is available, the chat screen gives the page's file path instead, and
the owner opens it in the editor.

## 9. The guard rule for `.relay/checks/` (v3, narrowed: m-3)

The guard (`guard-main.sh`, every session and agent, every project; core is
enabled account-wide) refuses, with the message "guard-main: files in
.relay/checks are written only by relay (the check hook, relay gate); run
the checker or relay gate instead":

- Write, Edit, MultiEdit, NotebookEdit on a path with a part sequence
  `.relay/checks/`, in the main checkout or any worktree (checked before the
  main-checkout test at `guard-main.sh:113`);
- a Bash `W` row (redirect, `tee`, `cp`, `mv`, `rm`, `sed -i`, ...) under
  `.relay/checks/`, anywhere (today `W` rows are judged only in main);
- `git add`, `git rm`, `git mv`, `git checkout ... --`, `git restore`,
  `git update-index` naming `.relay/checks`;
- inline code naming `.relay/checks`: `python`/`python3 -c`, `node -e`,
  `perl -e`, `ruby -e` (the guard cannot see inside them).

Allowed (the m-3 fix): every read (`cat`, `grep -rn .relay/checks`, `ls`,
`git show`, `git log`, the Read tool), `relay gate`, `relay check show`,
`relay check page`. v3 refused "any other Bash text naming `.relay/checks`",
which refused a critic's `grep -rn ".relay/checks" plugins/core` and every
`cat >> report <<'EOF'` that mentions the folder; now reviewers must read
stored reviews, so reads are allowed. Cost: none of v3's tests G1-G3 is
weakened (they are writes or inline code).

Hooks are not tool calls, so the hook's and `relay gate`'s own commits pass.
A path built at run time passes (a variable, a joined string): the guard
stops mistakes, not an adversary. `guard-diff.test.sh` (309 commands, none
naming `.relay/checks`) keeps its golden output.

## 10. The work queue (v3 section 8, revised)

### 10.1 The rule

Something found during a change is one of four things:
1. wrong inside the change: fixed in this change; the merge is refused until
   it is (7.1);
2. wrong elsewhere: a queue item of kind `fix`, with a failing case, ip
   above every open feature;
3. the design is wrong (`Design:`): stop building on it; the redesign is a
   `fix` item and the next change; the current change finishes first only
   when the owner agrees it does not build on the wrong part (the coordinator
   appends `Owner: F<n> moved to queue item <slug> ("<owner's words>")` to
   the findings file; the checker counts it as `queued` when the item exists
   on the default branch);
4. a feature: a queue item of kind `feature`, with the ip the owner gives
   (default 0).

An out-of-scope question from the owner is answered in two lines and
becomes a `feature` item, built later in a fresh session. A new request
while `fix` items wait: the coordinator names them (how many, the top one,
its size) and the owner decides what goes first (owner "q4 - a").

New rule file `rules/queue.md`, first two lines `# Work queue` and the gist
`> Nothing wrong is left behind: wrong inside a change is fixed before its
merge; wrong elsewhere is a fix item in the work queue, above the features.`
(`lib/relay_rules.py` requires that shape). The phrases "tech debt" and
"technical debt" appear nowhere in it (test A6). Listed in `projects.toml`
in every target that lists `delegation`. Text names `.relay/queue/`, the
two kinds, ip, and `relay queue`.

### 10.2 The item file

`.relay/queue/<slug>.md`, committed; `<slug>` lowercase words joined by
`-`, at most 48 characters, unique among the default branch's
`.relay/queue/` and `done/` and the `wt/queue-*` branches. Closed items move
to `.relay/queue/done/`.

```
---
kind: fix              # fix | feature
state: open            # open | taken | done | dropped
ip: 95                 # important points, integer >= 0; highest first
size: 30               # agent minutes, the finder's estimate
found: 2026-10-22, check of batch 3 part 1 (bin/ci:25)
taken-by:              # the task branch working on it
closed-by:             # the branch whose merge closed it
test:                  # fix items, at close: <test file>::<test name>
---
# Core plugin tests that never run in the gate

What is wrong: ...
Failing case: ...
Pass-cases: (optional, 2-5)
Why it matters: ...
```

A `fix` without `Failing case:` is refused by `relay queue add` and shown as
"malformed" by `relay queue`. A `feature` has "What" and "Why it matters".

### 10.3 Order, pick-up, close (m-4 fixed)

- Order: ip descending; equal ip, older `found` first, then slug.
- A new `fix` gets ip = 1 + the highest ip among open features (0 when
  none) unless `--ip` is given; a new `feature` gets the owner's ip, default
  0. `relay queue ip <slug> <n>` changes it.
- Take: `relay queue take <slug> -C <worktree> --findings <path>`:
  1. refuses when the item is `taken` on the default branch ("taken by
     wt/other");
  2. lands `state: taken`, `taken-by: wt/<branch>` on the default branch
     through the landing path of 10.4 (the code check then allows exactly a
     change of that one file); this is the m-4 fix: a second session sees
     the item as taken at once, not after the first branch merges;
  3. in the worktree runs `git merge --no-edit <default>` (a fresh worktree:
     a fast-forward; the branch then holds the `taken` state, so its later
     `done` move does not conflict with master);
  4. for a `fix`, writes the findings file at `<path>`: `Reviewed:
     <merge-base of the branch and the default branch>`, `From queue:
     <slug>`, finding `Q1` (HIGH) with the item's failing case and
     pass-cases, its linter line naming the place the item names.
- `relay queue release <slug>` lands `state: open` again (a task branch that
  was abandoned); `relay doctor` lists items taken by a branch that no longer
  exists. `ip` and `drop` refuse a taken item ("taken by wt/x; release it
  first"), so master never edits a file a task branch is about to move.
- Close: `relay queue done <slug> -C <worktree> --test <file>::<name>
  --check <checker report>` refuses unless the test file exists at HEAD and
  holds `<name>` and the report's verdict names `Q1 MET`; then moves the
  file to `done/` with `state: done`, `closed-by`, `test`, and commits on
  the task branch. The item is closed by the merge; the merge hook refuses a
  close without the test (7.5).
- Drop: only on the owner's word, `relay queue drop <slug> --why "<the
  owner's words>"`, landed like `add`, moved to `done/` with `state: dropped`.

### 10.4 Landing on the default branch (v3 8.4, unchanged in method)

`relay queue add` (and `take`, `release`, `ip`, `drop`) refuses where the
default branch has no `.relay/`. Otherwise:

1. Slug from the title; taken names get `-2`, `-3`, ...; the final slug is
   printed.
2. One commit on the current default head, touching no checkout:
   `hash-object -w`, `read-tree` and `update-index` on a temporary
   `GIT_INDEX_FILE`, `write-tree`, `commit-tree`, message `queue: <slug>`;
   branch `wt/queue-<slug>` set to it with `update-ref` (a name of its own
   per item, so concurrent sessions never share one: owner, q3).
3. Code check: `git diff --name-only <default>..wt/queue-<slug>` is exactly
   the one allowed file (for `drop`, its move to `done/`); anything else
   stops and deletes the branch.
4. Land: `git -C <main> merge --ff-only wt/queue-<slug>` in the main
   checkout, which must be on the default branch ("the main checkout is not
   on master"). On a moved head or a held lock: rebuild step 2 on the new
   head and retry, `QUEUE_LAND_TRIES = 5` (constant, bound 1-20; at 20 a
   landing can take about 20 s), waiting 0.2-1 s between tries. Then `git
   branch -d wt/queue-<slug>`.
5. Prints "queued <slug> (fix, ip 91), landed on master at <full sha>"; after
   the last failed try, "not landed after 5 tries: <git's last line>; kept
   on wt/queue-<slug>; relay queue land <slug> tries again". `relay doctor`
   lists leftover `wt/queue-*` branches.

This is the one merge into the default branch without the owner's word; it
runs inside `relay`, so the guard and the merge hook do not see it, and step
3 is its only gate (test Q9). Every such landing makes open task branches
behind (7.2); the cost is one runner merge per task branch before its own
merge (critique 16.4).

Commands:

```
relay queue add --from <report> F7       # a finding outside the change, or Design:, becomes a fix item
relay queue add --kind feature --title "..." --why "..." --size 15 [--ip 40]
relay queue                              # the ordered list, one line each
relay queue count                        # "10 fix, 12 feature; top: core-tests-not-in-gate (fix, ip 95, 30 min)"
relay queue land <slug>
relay queue ip <slug> <n>
relay queue take <slug> -C <worktree> --findings <path>
relay queue release <slug>
relay queue done <slug> -C <worktree> --test <file>::<name> --check <report>
relay queue drop <slug> --why "..."
```

Code: `lib/relay_queue.py` (plain-text frontmatter parse, no new
dependency), copied to `plugins/front/lib/` (checked by `bin/ci`),
`cmd_queue` in `bin/relay`. The coordinator runs these through a runner
when it should not hold the output.

### 10.5 The line at every session start

`plugins/front/hooks/handover.py` adds, when the default branch has
`.relay/queue/`: "Queue: 10 fix, 12 feature; top: core-tests-not-in-gate
(fix, ip 95, 30 min). relay queue lists them." It reads the default
branch's `.relay/queue/*.md` (not `done/`) with `git ls-tree` and one `git
cat-file --batch`, never the working tree, so every worktree sees the same
queue. It goes to the model as `additionalContext` and to the owner as
`systemMessage` (that the owner sees it is confirmed live, Q5; if not, the
front says it in its first reply). No folder, or zero open items: nothing.

### 10.6 The seed items (written by part C2 as plain files on its branch)

Fixes go above features (owner "2. a"). Among fixes the ip is the finder's
estimate of harm: 95 for a hole in the gate itself, 93 for money or turns
lost on every paid run, 92 for wrong estimates, 91 for the rest (the default
a new fix gets: 1 + the top feature's 90). Features keep the owner's order
from v3 (issues flow, state from facts, status line, OpenSpec stages, phase
1), then the rest in steps of 5-10. Sources: v3 8.7 (list 1); the handover's
"Queue seeds for part 2" and "Queue:" notes of 22 Oct, and check-judge-fix
L1-L3 (list 2). Duplicates merged as named in the last column.

| # | Slug | Kind | ip | Size | Failing case or what (source; merged duplicates) |
|---|---|---|---|---|---|
| 1 | `core-tests-not-in-gate` | fix | 95 | 30 | `bin/ci:25` skips `inject-addition`, `packet`, `check-contract`, `shim`, `spec-check`, `hooks-live` unless `RELAY_CORE_TESTS=1`; part 1's per-role tests I1-I9 live in `inject-addition.test.sh`, so a regression in role injection passes `bin/ci --quick` (v3 #1; handover "core plugin tests not in bin/ci --quick") |
| 2 | `eval-cost-ceiling-overshoots` | fix | 93 | 20 | `--max-cost-usd 4` at `-j 4` ran to $6.32 (Sonnet measure, 22 Oct); the README's $10 ceiling can reach about $13; should stop within one batch of the ceiling (handover "ceiling overshoot", "eval cost ceiling not firm at -j 4", check-readme-cost "$10 ceiling worst case ~$13") |
| 3 | `runner-turns-while-waiting` | fix | 93 | 15 | the runner ran out of turns while waiting on a paid run three times on 22 Oct (measure, live6, full run); the front read the results itself; should finish and report within its turns (handover, three notes) |
| 4 | `paid-run-estimates-from-ledger` | fix | 92 | 20 | estimates were low: Sonnet measure $3.02 estimated, $6.32 spent; live6 $1.90 estimated, $3.37 spent; four cap raises on 22 Oct; the judge-measure README's Sonnet figures come from two runs; should come from the ledger's measured costs (handover "cost estimates from real numbers", "Sonnet measurement figures come from two runs") |
| 5 | `sonnet-long-context-price` | fix | 91 | 20 | `relay calibrate` on the 21 Oct ledger: 2 of 15 Sonnet sessions at 266k-278k context are 20.8% under Claude Code's total; should be within 5% (v3 #2) |
| 6 | `guard-variable-paths` | fix | 91 | 15 | from the main checkout `git -C $G branch -d x` (a worktree in `$G`) is refused: the guard takes an unquoted `$NAME/...` word as a path under the current folder (`guard-main.sh:39-41`); the same mechanism refuses writes to `$TMPDIR/...` and `mkdir -p $S` (handover "guard-main reads -C $VAR as a literal path", "guard and $TMPDIR", earlier note at handover:144; the `$TMPDIR` case is the coordinator's shorthand, confirmed by the taker) |
| 7 | `tally-unreadable-json` | fix | 91 | 3 | `python3 tally.py /dev/null --expect-model haiku` prints a traceback and exits 1, which means "a bar is exceeded"; should exit 2, "not judged" (L1) |
| 8 | `tally-runs-from-prompt` | fix | 91 | 2 | tally compares the run count with the prompt's `runs:`; `--runs 3` on the CLI with `runs: 5` in the prompts gives "not judged"; should compare with what was run, or the README says they must match (L3) |
| 9 | `offbyone-rubric-fail-clause` | fix | 91 | 10 | the off-by-one rubric's FAIL clause words ("stays within size", "as the doc says") made Haiku fail right answers yes-03 (5 of 5) and yes-05 (2 of 5); Sonnet unaffected, the trap stays for any weaker judge (handover cause-measure) |
| 10 | `stale-eval-texts` | fix | 91 | 5 | the handover names `case.yaml:3` and `evals/plugin/setup-fixture.sh` as stale; the C2 worker reads both and writes the exact failing case into the item (5 min) or, if nothing is wrong, leaves it out and says so |
| 11 | `issues-flow-into-queue` | feature | 90 | 60 | the issues flow (`.issues/<slug>/`, `plugins/issues`) merges into the queue; joins the shared change cycle (phase-1 decision); touches ALIX and arsenal live flows (v3 #3) |
| 12 | `state-from-facts` | feature | 80 | 60 | rebuild session state from git (branches, worktrees, merges, marks), the queue, the ledger and reports; keep by hand only the owner's words and decisions; at session start name each difference between the handover and the facts (owner, q4 "a"; v3 #4) |
| 13 | `status-line-limit-share` | feature | 70 | 40 | visible status line `5h % · week % · $` that also logs (v3 #5) |
| 14 | `openspec-stages-by-meaning` | feature | 60 | 45 | stages by meaning in any language with typos; doctor and setup check the openspec CLI and `/opsx:` commands; about 15 paid Haiku prompts (about $0.30) (v3 #6) |
| 15 | `phase-1-self-contained` | feature | 50 | 120 | marked block in `~/.claude/CLAUDE.md`, relay's rules apart from the owner's personal set, project list in `~/.relay`, ship the OpenSpec coordinator skill, `relay uninstall`, paths at install. Not touched (owner, 22 Oct): Kartoteka, principles. v3's "kartoteka's kit.toml moves into .relay" is dropped. Per-project inert probe (A11) for projects that get `.relay/` (v3 #7, revised) |
| 16 | `one-change-cycle` | feature | 40 | 90 | one shared change cycle for every flow, ten correctness checks everywhere, waves in the shared cycle, a thin OpenSpec add-on (sdd renamed), no per-flow addition files (owner's phase-1 decisions, 22 Oct; replaces v3 #8 `openspec-as-adapter`) |
| 17 | `evals-for-every-agent` | feature | 35 | 60 | 12 of 15 agents have no eval case (handover) |
| 18 | `large-repeated-requests` | feature | 30 | 30 | carried-weight finding, including about $0.30 of session start-up (v3 #9) |
| 19 | `bench-judge-model-measured` | feature | 25 | 20 | `relay bench`'s own judge still defaults to Haiku (`bin/relay`, `docs/benchmark.md`); the 22 Oct measurement shows Haiku misreads meaning; measure before changing (handover) |
| 20 | `front-noise-measured` | feature | 20 | 15 | bench reply length before any Stop hook (v3 #10) |
| 21 | `issue-bindings-forgejo-gitlab` | feature | 15 | 20 | `[issues]` commands for Arsenal and Glonass (v3 #11) |
| 22 | `bench-isolate-keychain` | feature | 10 | 10 | `--isolate` sign-in on keychain Macs unverified (v3 #12) |
| 23 | `judge-measure-realistic-items` | feature | 5 | 15 | two "no" items (off-by-one 24, role-rule 13) are less natural than the rest; the "no" templates say "5 problems" with 4 listed (L2: labelled right, so not wrong) |

Not seeded: "Agents' models in installed copies" (closed by v3 fact F.1).
After merge 2 the handover's "Open items" keeps state only and points at
`relay queue`.

### 10.7 Where the old wording goes (v3 8.6, unchanged)

| Place | Today | Becomes |
|---|---|---|
| `plugins/sdd/agents/reviewer.md` check 5 | "a known problem left without a follow-up id" | "a known wrong left in code without its queue item" |
| `plugins/sdd/agents/spec-reviewer.md` check 5 | "deferred work has a follow-up id, an owner and a deadline stated as an event" | "work the plan leaves out is a queue item; a known wrong left inside the change is a BLOCKER" |
| `apply-review/SKILL.md`, `parallel-apply/SKILL.md`, `spec-review/SKILL.md` | follow-up wording | "a queue item" |
| `docs/variants/apply-review.md`, `spec-review.md`, `spec-reviewer.md` | follow-up wording | queue wording, "(was: follow-up with id, owner, deadline)" |
| delegate skill table "wrong outside the change" | "listed for the owner under Outside this change" | "a fix item: `relay queue add --from <report> F<n>`" |
| `rules/delegation.md` | "listed for the owner under Outside this change" | "a fix item in the work queue (rules/queue.md)" |
| front skill | | section "An out-of-scope question": answer in 2 lines, `relay queue add --kind feature`, build it in a fresh session |

The C2 worker finds the current line numbers with `git grep -n -i
'follow-up'` in the C2 worktree (they moved in merge 1).

## 11. Removing a merged task's worktree and branch (v3 section 9, facts re-checked)

Owner (v1): "remove the stale, add the rule for do it automatically"; then:
right after the allowed merge; never the worktree the session runs in (it
goes at the next session start, "q2 - a"); never a branch with no commits
of its own; changed, untracked and locked worktrees kept; a hard rule where
the default branch has `.relay/` (no switch).

### 11.1 The hook

- `plugins/core/hooks/hooks.json` gains `PreToolUse` and `PostToolUse`,
  matcher `Bash`, command `merge.sh`. `merge.sh` reads stdin and exits 0 at
  once unless the input contains `merge` (a shell `case`, about 5 ms; no
  python on other Bash calls); else it pipes to `python3 merge.py`, which
  reads `hook_event_name`: `PreToolUse` = the merge gate (7), `PostToolUse`
  = the cleanup below.
- Parse: `kit_guard.py` gains `allowed_merges(cmd, cwd) -> [(dir, branch)]`,
  built on `parse`, `strip_prefix`, `git_parts` and `git_write` (fact 2.1):
  every simple command that `git_write` lets through as the allowed merge.
  `cd <main> && git merge --ff-only wt/t`, `git -C <main> merge --ff-only
  wt/t` and two merges joined by `&&` are all seen. The guard's own output
  is unchanged (guard-diff, 309 commands, 0 differences).
- For each merge `(dir, wt/<name>)`, in a repository whose default branch
  has `.relay/`, the hook checks git itself (not the tool's exit status):
  1. `dir` is the main checkout, on the default branch (`relay_git`).
  2. Merged: `git merge-base --is-ancestor wt/<name> HEAD`.
  3. Has commits of its own: `git reflog show --format=%H
     refs/heads/wt/<name>` has more than one entry; else kept, "kept wt/n:
     it has no commits of its own (a fresh worktree)".
  4. The worktree on `refs/heads/wt/<name>` from `git worktree list
     --porcelain` (names and branches differ in practice); none: only the
     branch goes (step 7).
  5. Not the session's own: the worktree path (`pwd -P`) contains neither
     the hook's `cwd` nor `$CLAUDE_PROJECT_DIR`; else kept, "kept
     .worktrees/x: this session runs in it; it goes at the next session
     start".
  6. Ignored paths listed first (`git status --ignored --porcelain`, `!! `
     lines, at most 5 named, then "and N more"); then `git worktree remove
     <path>` (never `--force`): git refuses changed, untracked and locked
     worktrees, and the hook keeps it and says why, naming up to 5 files.
  7. `git branch -d wt/<name>` (never `-D`); a refusal keeps the branch:
     "branch kept: not merged into its upstream".
- Message (`additionalContext`), one line per merge: "Removed
  .worktrees/review-gate and branch wt/review-gate (merged), with 2 ignored
  paths gone: .ci/, __pycache__/", or the keep reason. When the range
  touches `plugins/*/agents/`, `plugins/*/skills/` or `roles/`: "Agent and
  skill texts changed: open sessions keep the old texts until restarted or
  /reload-plugins." When it touches `rules/` or `roles/` in relay: "Run
  relay sync once from the main checkout."
- A worktree an agent may still read is removed when every guard passes;
  rare, because the front merges after the hand-back.

### 11.2 The guard when its anchor is gone

`guard-main.sh:60-61` today: a deleted `$CLAUDE_PROJECT_DIR` makes `git -C`
fail and the guard exit 0 (allow everything). New: if `$CLAUDE_PROJECT_DIR`
is set but not a directory, use `cwd`; if neither is a directory, refuse:
"the session's folder <path> no longer exists, so the guard cannot tell the
main checkout; start the session again from the main checkout or a
worktree". Outside any repository it still exits 0.

### 11.3 Session start and `relay doctor`

- Session start sweep (owner "q2 - a"): `merge.py sweep`, a core
  `SessionStart` hook (timeout 5 s), in a repository with `.relay/`, removes
  every worktree whose branch passes guards 2-7 of 11.1, except the one the
  session starts in. One line: "Removed 1 merged worktree: .worktrees/x
  (wt/x)".
- `relay doctor` (read-only) adds: merged worktrees still present (ancestor
  of the default branch or of `origin/<default>` as last fetched, with
  commits of their own); `wt/*` branches whose upstream is gone ("probably
  merged on the server (squash)", listed, never removed); the unused
  `~/.claude/plugins/cache/relay/` copy (informational); leftover
  `wt/queue-*` branches; queue items `taken` by a branch that no longer
  exists.

### 11.4 The rule text

`rules/git.md`, after "Merge into the default branch only when I ask":
"After a merge into the default branch its worktree and branch are removed
(the core plugin does it where the project has `.relay/`; `relay doctor`
lists any left over). Nothing lives only in a task worktree: commit it, or
keep it in the session scratchpad; ignored files there go with it. Before
its merge a task branch takes the default branch by a merge commit, never a
rebase (a rebase loses the check). One merge needs no word from me: `relay
queue` lands a queue item on the default branch at once, and its code
refuses when anything but that one file under `.relay/queue/` would
change."

## 12. Tests

All hook tests build throwaway repositories (temp `HOME`, a committed
`.relay/`, a worktree `.worktrees/t` on `wt/t` with one commit) and feed the
hook the JSON a tool call would carry. Every keep-case asserts the hook's
message; a case whose right output is silence runs a positive control in
the same test, so a disabled hook fails it.

### 12.1 Cleanup, `plugins/core/tests/merge.test.sh` (runs in every gate)

| # | Case | Expect |
|---|---|---|
| T1 | `git merge --ff-only wt/t` in main, clean | folder and branch gone; "Removed" |
| T2 | `git -C <main> merge --ff-only wt/t` from elsewhere | same |
| T3 | no `.relay/`; then the folder committed and the same input | first: kept, no output; second: removed |
| T4 | hook `cwd` = `.worktrees/t` | kept, "this session runs in it" |
| T5 | fresh `wt/n` at master, no commit | kept, "no commits of its own" |
| T6 | tracked file changed in the worktree | kept, file named; branch kept |
| T7 | untracked file | kept, named |
| T8 | locked worktree | kept, "locked" |
| T9 | merge refused (not a fast-forward) | nothing removed; positive control T1 in the same run |
| T10 | `git -C .worktrees/t log`; a merge run inside a worktree | nothing; positive control |
| T11 | `wt/t` with no worktree | branch deleted |
| T12 | two merges joined by `&&`; `cd <main> && git merge --ff-only wt/t` | both handled |
| T13 | guard: `CLAUDE_PROJECT_DIR` a deleted folder, cwd = main, `touch a` | refused (today: allowed) |
| T14 | ignored file under `.ci/` | removed; message names `.ci/` |
| T16 | sweep: one merged worktree, one unmerged, the session's own merged | only the first removed |
| T17 | doctor (`tests/test_tidy.py`): merged, unmerged, fresh, upstream gone, cache dir, leftover `wt/queue-x`, item taken by a gone branch | exactly those lines |

### 12.2 The merge gate, T15 (same file)

Each case starts from: `wt/t` with a commit touching `lib/a.py`, a green
gate log and a clean mark for that commit, unless the case says otherwise.

| Case | Setup | Expect |
|---|---|---|
| (a) | no mark | refused, "no check mark for wt/t" |
| (b) | mark `open 2` | refused, "left 2 things inside the change wrong" |
| (c) | clean mark and green gate on head | allowed |
| (d) | (c), then a `docs/handover.md` commit | allowed |
| (e) | (c), then a `lib/a.py` commit | refused, "after the check of <X>, wt/t changed lib/a.py" |
| (f) | range only inert, no mark, no gate | allowed |
| (g) | no `.relay/` on the default branch, no mark | allowed, silent; positive control (a) in the same run |
| (h) M-A | (c); then a `.relay/queue/x.md` commit lands on master | refused, "wt/t is behind master by 1 commit"; after `git -C .worktrees/t merge --no-edit master`: allowed, and the real `git merge --ff-only` succeeds |
| (i) M-A | (c); master gains `lib/b.py` from another branch; `wt/t` merges master | refused, "code changed since: lib/b.py; run relay gate"; after `relay gate` (green): allowed with the same mark |
| (j) | (c) with the mark on a fix commit; then a commit restoring `lib/a.py` to master's content | refused, "changed lib/a.py" (a reverted checked fix is not "from master") |
| (k) | the branch changed `bin/x` before the mark; master changes another part of `bin/x`; the branch merges master without conflict | refused, "changed bin/x"; after a check of the merge commit (fixture mark): allowed |
| (l) M-B | gate log for `F`; mark for `F` with `open 0`; HEAD = `F` + mark commit + handover commit | allowed |
| (m) | only a red gate log (`exit 1`) for head | refused, "last gate <G>: exit 1" |
| (n) m-1 | the range moves `fix` item `x` to `done/` with no `test:` line; then with `test: tests/t.sh::case_x` present in `tests/t.sh` | refused, "closed without a test"; then allowed |

Plus `tests/test_relay.py` A14 `test_relay_changed_own`: the six rows of
7.2's worked values on a fixture repository, each listed or not as the
table says, and `relay changed` without `--own` listing `lib/relay_queue.py`
(master's file) for the same pair.

Regression proof (run with each part disabled, the named cases fail): step 1
removed: (h) first half; `--own` replaced by plain `changed` in step 3: (i)
second half; the `since` half of the own rule removed: (j); step 5 compared
by equality instead of `changed`: (l); step 5 removed: (i) first half and
(m); step 6 removed: (n) first half; the merge commit handled as in v3's
walk: (h) second half.

### 12.3 Check-mark hook and guard, `plugins/core/tests/check-mark.test.sh`

| # | Case | Expect |
|---|---|---|
| K1 | `SubagentStop`, `delegate:checker`, fixture transcript whose first line is a check prompt, valid report | one commit holding only `.relay/checks/<head>.json`, `<head>.check.md`, `<reviewed>.review.md`; json fields as 4.1; every sha 40 characters |
| K2 | same with `delegate:critic`, then K1's input | no commit, then the mark commit |
| K3 | empty `agent_type` | no commit |
| K4 | report without `## Verdict`, an earlier clean mark on that head | no mark; a commit removing the old one; `systemMessage` names the reason |
| K5 | report older than the transcript's first timestamp | no commit |
| K6 | `head` not in the worktree's history, or abbreviated | no commit, reason named |
| K7 | no `.relay/` on the default branch | nothing; positive control K1 |
| K8 | another file staged; the index locked for 2 s | the commit holds only the hook's files; the other stays staged; the locked case lands on a retry |
| K10 | `Check: a.md, b.md` (review and a `Q1` file) | `<reviewed>.review.md` holds both under their headings |
| K11 | re-check of the same head after `Owner: F3 is not wrong` was appended | the review file is replaced with the new content; the mark's `open` changes |
| K9 | live, once (paid, 13.2): a real `delegate:checker` on a fixture repo with the worktree's plugins | the mark commit exists when the hand-back arrives, or the delay is measured; whether `agent_transcript_path` is in the input, recorded |
| G1 | Write/Edit on `<worktree>/.relay/checks/x.json` and on main's | refused, the guard's message |
| G2 | `printf x > .relay/checks/a.json` in a worktree, `cp a .relay/checks/`, `git add .relay/checks`, `git checkout other -- .relay/checks` | refused |
| G3 | `python3 -c` naming `.relay/checks` | refused |
| G4 | the checker's own write: Write on `<scratchpad>/check.md` and `<worktree>/.ci/check.md`, real guard, `CLAUDE_PROJECT_DIR` = the worktree | allowed |
| G5 | `relay check show wt/x`; `relay gate`; `git log` | allowed |
| G6 (m-3) | `grep -rn ".relay/checks" plugins/core`; `cat .relay/checks/x.review.md`; `cat >> <scratchpad>/r.md <<'EOF'` whose body names `.relay/checks` | allowed |

Regression proof: agent-type test removed: K2; mtime test removed: K5;
guard rule removed: G1-G3; v3's text rule restored: G6.

### 12.4 The gate command and the page, `tests/test_gate.py`

R1 refuses without `.relay/` (message names `relay setup`); R2 refuses a
worktree with a changed tracked file and one with an untracked file, and
accepts an ignored one; R3 green fixture gate: log `head <G>`, `cmd`, the
output, `exit 0`, committed alone (a staged file stays staged); R4 red
fixture gate: exit status 1, log ends `exit 1`; R5 refused in the main
checkout. P1 `relay check page` on a fixture branch holds each linter line,
its status line and five lines of code at the reviewed commit; P2 a fixture
with 600 lines of findings is cut at `PAGE_MAX_LINES` with the "more" line;
P3 `relay check show` prints exactly three lines.

### 12.5 Queue, `tests/test_queue.py` (fixtures only)

Q1 order (ip, then found, then slug); Q2 `fix` without `Failing case:`
refused by `add`, "malformed" in `relay queue`; Q3 `add --from <report>
F7` copies the fields of a fixture report (linter line included); Q4
`count` ignores `done/` and reads the default branch only; Q5 the
SessionStart line in a session whose cwd is a worktree shows the default
branch's items, nothing without `.relay/queue/` (live part after merge 2:
the owner's next session shows the line or the front says it); Q6 `add`
refuses without `.relay/`; lands from main and from a worktree, leaves the
worktree's `git status --porcelain` empty, deletes `wt/queue-<slug>`,
suffixes `-2`; Q7 `done` refuses without `--test`, with a name the file
lacks, with a report lacking `Q1 MET`; Q8 a new `fix` gets 1 + the top open
feature's ip; Q9 two `add`s at once from two worktrees, 10 rounds, both
land, no branch left; with `index.lock` held 2 s it still lands; with
`QUEUE_LAND_TRIES` = 1 and a moved head it reports "not landed" and keeps
the branch; a queue branch touching a second file is refused and deleted;
Q10 (m-4) `take` lands `state: taken` on the default branch; a second
`take` from another worktree is refused "taken by wt/a"; `ip` and `drop`
refuse a taken item; `release` lands `state: open`; the task branch's later
`done` merges into the default branch without a conflict.

### 12.6 Wording and the inert probe

- A6 (part 1's test) gains the part-2 phrases: "follow-up with an id",
  "follow-up id"; `rules/queue.md` holds neither "tech debt" nor
  "technical debt".
- A11 `bin/ci` step `inert`, in `--quick` too (the merge gate is the free
  gate, question 1, and a mark kept across an inert commit relies on it;
  cost: one more quick run inside the gate, free, a few minutes): in a temporary worktree at HEAD,
  every inert file gets a line appended and each inert folder probe files
  (`.relay/queue/zz-probe.md` malformed, `.relay/checks/zz.json`,
  `zz.review.md`, `zz.gate.log`); `bin/ci --quick` runs again; fails when
  its result or test count differs from the unchanged run. Proves that no
  outcome depends on an inert file, which keeping a mark relies on.
- A15 `test_judge_base_part2`: `roles/judge.md` names `relay changed --own`
  in check step 1 and the linter line in "Each finding"; the checker's flow
  part and the delegate skill name `relay gate`.

## 13. Proof plan (part 2 rows)

### 13.1 Agent and skill texts part 2 changes

Each part that touches an agent, skill or role text saves a word diff per
file against master (`git diff --word-diff master -- <file>`) to
`<scratchpad>/agent-diffs/<file>.diff` and tags every hunk with one of:

- **C15** follow-up wording becomes queue items (10.7); the delegate skill
  gains `relay queue add --from`; `rules/delegation.md` gains its part-2
  sentence; the front skill gains "An out-of-scope question".
- **C18** check mode: `relay changed --own` in step 1 (`roles/judge.md:76`);
  the gate log is `.relay/checks/<G>.gate.log` where the project has
  `.relay/`.
- **C20** every finding starts with its linter line; the checker writes one
  status line per finding (4.2).
- **C21** the pipeline: the delegate skill's Review loop gains step 2 (gate
  before review, `relay gate`), step 5 by `relay gate`, step 7 (take the
  default branch by a merge commit, never a rebase; re-gate when code came
  in; a conflict is a one-finding fix), and the person's step (8.2); the
  front skill gains "A change ready to merge".

An untagged hunk is a finding for the critic.

### 13.2 Paid runs (money against the owner's daily cap)

| Run | When | Estimate | Worst case |
|---|---|---|---|
| P-1 K9: one real `delegate:checker` on a fixture repository, through `claude -p` with the worktree's plugin folder | part B4 | about $0.50 (Sonnet, about 20 requests) | about $1 |
| P-2 full `bin/ci` (the 18 plugin eval runs), `EVALS_MAX_COST=9` | once, on the chain head after C merges into B, before the review | about $5 (the last full run: $4.99) | about $12-14 (ceilings overshoot: a $4 ceiling ran to $6.32 on 22 Oct; the README puts a $10 ceiling's worst case at about $13; seed 2) |
| P-3 full `bin/ci` again | only when the fixes touch `roles/`, `plugins/*/agents/` or `plugins/*/skills/`, and only on the owner's word | about $5 | about $12-14 |

Expected total about $5.50; worst about $29 (P-3 included). The runner
starts P-2 detached and waits in calls of at most 4 minutes; seed 3 says
it can run out of turns while waiting, so the brief gives it the log path
to report even when it stops early.

Free and live, no money: Q5 (the owner sees the session-start line, first
session after merge 2), 8.3 (publishing the page, the front, part B6).

## 14. Build plan (merge 2)

Every part is one brief for one `delegate:worker` (Sonnet), loops on `bin/ci
--quick` in its worktree, ends with it green, and carries verbatim: "Run
`<worktree>/bin/relay sync agents` only; never the `relay` on PATH, never a
full `relay sync`, never set RELAY_ROOT." Branch names avoid `wt/queue-`.

Chain B in `.worktrees/review-gate` (`wt/review-gate`, exists). Chain C in
`.worktrees/work-queue` (`wt/work-queue`), branched from `wt/review-gate`
after B1 (C needs `lib/relay_git.py`). At most 4 agents at once.

| Part | Builds | Check | Agent min |
|---|---|---|---|
| B1 | `lib/relay_git.py` (default branch, main checkout, `.relay/` present; never the current branch, fact 2.8) and its core copy; `kit_guard.allowed_merges`; `merge.sh`, `merge.py` cleanup (11.1); `hooks.json`; `rules/git.md` (11.4); T1-T12, T14 | `bin/ci --quick` (runs the hook tests and guard-diff) | 25 |
| B2 | guard fallback (11.2); session-start sweep (11.3); T3 control, T13, T16 | same | 15 |
| B3 | doctor lines (11.3); `tests/test_tidy.py` T17 | same | 12 |
| B4 | `lib/relay_marks.py` and core copy; `check-mark.py` on `SubagentStop` copying review and report (6); the guard's `.relay/checks` rule, narrowed (9); `relay check show`; K1-K8, K10, K11, G1-G6; K9 live (P-1, about $0.50) | same | 30 |
| B5 | `relay gate` (5); `relay_inert.changed(own=True)`, `relay changed --own`, core copy of `relay_inert.py`; the merge gate 7.1 steps 1-6 (M-A, M-B, m-1); T15 (a)-(n), A14, A11 in quick mode with the new probe files; `roles/judge.md` (C18, C20), the checker's flow part and the delegate skill (C21) | same, plus A15 | 35 |
| B6 | `relay check page` (8.1); the front skill's "A change ready to merge" (8.2); publishing confirmed live or the fallback written (8.3); P1-P3, R1-R5 | same | 15 |
| C1 | `lib/relay_queue.py` and front copy; `relay queue` add, land, count, ip, take (landed, m-4), release, done, drop; the session-start line (10.5); Q1-Q10 | `bin/ci --quick` | 32 |
| C2 | `relay setup`'s `.relay/README.md` step and the refusals (7.6), run once for relay (creates relay's `.relay/`); `rules/queue.md`; the 23 seeds of 10.6 (reading the two stale-text places for seed 10); the rewording of 10.7 (C15); A6 part-2 phrases; `docs/` note on `.relay/` versus `~/.relay`, marks, gate logs and the pipeline | same | 28 |

Building: 192 agent minutes (B 132, C 60). Then: a runner merges
`wt/work-queue` into `wt/review-gate` (in its worktree, a merge commit),
`relay gate -- --quick` green, P-2 (paid, about $5), then the review of the
pipeline over `master...wt/review-gate`: two critics in one message (one for
B's files, one for C's), 15-20 minutes each; fixers 10-15; gate 3; the
check by the real `delegate:checker` (the coordinating session must have
started after merge 1, so the agent exists), 5. About 55-70. Total about
250-265 agent minutes; wall time about 200 minutes (chain B plus review; C
runs beside B).

Merge 2 is not refused by its own hook: hooks run the main checkout's code,
and Claude Code reads `hooks.json` at session start. After the merge, in
order: `relay sync` once from the main checkout; the front tells the owner
that open sessions keep the old texts and hooks until restarted or
`/reload-plugins` (only the owner can type it); the worktree goes at the
next session start (11.3, the session runs in it); the handover's "Open
items" becomes state plus a pointer to `relay queue`. From then on every
merge in relay goes through the pipeline of section 3.

## 15. What v3 parts are dropped or replaced

| v3 | Now | Why |
|---|---|---|
| 7.6 `find` walk over `D..wt/x` | list of marks, newest current one (7.1 step 3) | the walk stops at a merge commit from the default branch (M-A) |
| 7.6 walk-through "the merge passes" | 7.3 | it did not pass (M-A) |
| 7.7 "the report path points at a scratchpad later deleted; the mark keeps the numbers" | the report and the review are copied into `.relay/checks/` | owner: results stored in git |
| 7.1 step 5 and the delegate skill's runner redirect for the gate log, in projects with `.relay/` | `relay gate` | the log is evidence; code writes it (the redirect stays for projects without `.relay/`) |
| 7.7 guard: "any other Bash text naming `.relay/checks`" refused | writes and inline code only | m-3; reviewers now read stored reviews |
| 8.3 `take` commits `taken` on the task branch only | landed on the default branch | m-4 |
| 8.7 seed 8 `openspec-as-adapter`; seed 7's Kartoteka move | `one-change-cycle`; Kartoteka not touched | owner's phase-1 decisions, 22 Oct |
| `relay_setup.default_branch` for the hooks | `relay_git.default_branch` | fact 2.8 |
| merge 1 rows of section 12 | built and merged | |

Nothing of v3's worktree cleanup (section 9) is dropped.

## 16. Critique (said once; then built as given)

I looked at each owner decision this design builds on and at the brief's own
picks.

1. **Results stored in git beside the mark.** About 20-50 KB per change stays
   in history for good (4.1). A secret quoted in a review would be committed
   and, once merged, in history for good: the judges' limits already forbid
   printing secrets, and the owner is told at once to rotate if one appears.
   Accepted as given.
2. **Free checks before the review.** I looked for a weakness and found none
   beyond 2-4 runner minutes per change; it saves a 15-20 minute review of a
   red build.
3. **"Merge refused unless ... the owner's word."** The first two conditions
   are code (7.1); the owner's word cannot be: a hook sees the owner's
   message, but an "a" that answers "merge?" looks like any other "a", and
   the owner writes in many languages with typos, so a fixed phrase would be
   a trigger by wording, which relay avoids. It stays the rule it is today,
   followed by the front.
4. **Queue items land on master at once (q3).** Each landing makes every
   open task branch behind, so before its merge each branch takes master
   (one runner minute), and its history gets one merge commit per such
   catch-up. With 23 seeds written on C2's branch (not landed one by one)
   merge 2 itself avoids this; in daily use it is about one extra runner
   call per merge.
5. **Hard rules with no switch.** Once relay's master has `.relay/`, a bug
   in `merge.py` that refuses every merge also refuses the merge of its own
   fix: the allowed merge is the only one the guard lets through. The way out
   is the owner running `git merge --ff-only wt/<fix>` in a terminal outside
   Claude Code (hooks run only inside it). The front says so in its message
   when a refusal names a reason that contradicts the stored files. No switch
   is added.
6. **The brief's pick for M-A, "diff against the merge base".** Taken, as
   the own-files rule of 7.2. Its weak spot: when master changes a function
   the branch calls, in a file the branch did not touch, nothing is
   re-reviewed; only the gate (re-run because code came in) catches the
   interaction. A re-check would not catch it either (the checker reads the
   fix range, not master's files), so the gate is the right place.
7. **Links in the linter form.** Relay has no forge, so "link to wrong
   places" is the `path:line` text, which the terminal opens, plus a code
   excerpt on the page. A clickable web link would need a forge (Forgejo in
   arsenal); not now.
8. **A local gate, no Woodpecker.** A log is trusted because `relay gate`
   wrote it; an agent that pieces a path together at run time could still
   write one. Same level as marks: it stops mistakes, not an adversary.

## 17. Questions for the owner

**1. Do the paid eval runs belong to the merge gate?**

Relay's gate has two halves. `bin/ci --quick` runs the free checks (python
and hook tests, copies, grader tests, plugin validate) in a few minutes. The
full `bin/ci` also runs 18 plugin eval cases, where real agents run on
fixtures and Sonnet judges their replies; the last full run cost $4.99, and
it is the only check that sees whether an agent still does its job after
its text changed. Your pipeline says "code checks run first - it's free", so
the merge gate (the one the merge hook requires) is the free half; the
question is when the paid half runs. Live example: part 2 itself changes
the judge base (every finding now starts with a `path:line` line). If that
broke how the critic reports, only the eval `names-file-and-line` in the
paid run would notice; the free gate stays green.

| | a (recommended) | b | c |
|---|---|---|---|
| Merge gate | free | free, plus paid when agent, skill, role or rule texts changed | free |
| Paid run | proposed on the chat screen, with its cost, for each change that edits those texts; runs on your word | required by the merge hook for those changes | only when you ask |
| Money per such change | about $5, when you say yes | about $5, plus about $5 again after fixes to those texts | none |
| At the $35 daily cap | you choose per change | at most 3 such merges a day | no limit |
| A broken agent text | caught when you say yes | always caught | caught only when you ask |

a (recommended) free gate; paid run proposed per text change, on your word
b paid run required for text changes   c free only; paid when you ask

What changes: under a and c `relay gate -- --quick` is what the merge needs;
under b the merge hook also looks for a green full-run log for those
changes.

## 18. What the brief could not answer

- Whether the coordinating session in Claude Code (or a subagent) can
  publish a private claude.ai artifact, and how the 22 Oct overview page was
  published (8.3): part B6 confirms it live; the fallback is the file path.
- Whether `SubagentStop` input carries `agent_transcript_path`, and whether
  the hook has finished before the checker's hand-back reaches the front
  (K9; a late mark only delays the merge by seconds).
- Whether SessionStart's `systemMessage` is shown to the owner (Q5).
- How long relay's free gate takes end to end (estimated 2-4 minutes; B5
  measures it).
- What exactly "guard and $TMPDIR" and the stale `case.yaml:3` refer to in
  the handover (seeds 6 and 10 say how the taker settles them).
