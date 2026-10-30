# Plan: Each change is gated in a fresh container (now: the Linux and Mac comparison)

Revision 1, 30 Oct 2026, thinker. Queue item `each-change-is-gated-in-a-fresh-container` (feature, ip 95, 180 min, taken 30 Oct
16:42Z by `wt/each-change-is-gated-in-a-fresh-containe`). Read-only: no code changed. Read against master a4733e75.

## 1. Short answer

Most of what this item asked for on 27 Oct has since been built by another item: `gates-on-the-vps-hosts-transport-watch-bring-up`
(changes 3 and 4 landed 30 Oct, e4e99dc1; change 5, the bring-up on the VPS, is still open). Every build-time gate already runs
`bin/ci --quick` in a **fresh rootless podman container** on the VPS ai.amidman.com, built from `container/Containerfile` (the
pinned Python 3.14.6 and the tools of deps.toml), with `--network none`, no host folder mounted, only `RELAY_GATE` in its
environment, and only the commit sent in a bundle (lib/relay_gate_remote.py:208-209). It **never lands anything**: the merge hook
and `relay land` read only the Mac log, pinned by tests/test_gate_remote.py:85 and :98. After each landing, one Linux gate of the
new default-branch head runs there (the **Linux watch**, lib/relay_gate_watch.py).

What is left of this item is the part that item explicitly left to it (its plan, 5.6: "The Linux comparison ... Built by the
comparison item, not here"): **compare the Linux and Mac results of the same commit, per wave, and show how often they agree.**
Recommended: approach B (section 5), the same-commit pairs that already happen plus one Linux run of each commit whose landing
gate went red on the Mac, so both kinds of disagreement are seen. About 160 agent minutes; no Mac gate time added.

One thing the item's text says no longer holds and is decided here (owner can reverse): the container does **not** take over the
landing decision after 3 agreeing waves. On 29 Oct, answering exactly that question, the owner wrote "пока мы полностью не перешли
на linux продолжим делать проверки на mac". The comparison is the evidence for that move; the move itself is the owner's word.

## 2. Terms

- **gate**: `relay gate`, which runs `bin/ci --quick` and commits a log `.relay/checks/<sha>.gate.log` ending `exit <n>`.
- **landing gate**: the gate `relay land` runs on the branch after it takes the default branch; only its Mac result decides a merge.
- **remote gate**: a gate whose command ran in the container on the VPS (log `<sha>.remote.gate.log`).
- **Linux watch**: one remote gate of the default branch's head after each landing; its result is a file in the git folder
  (`.git/relay-land/linux/<sha>.remote.gate.log`), never committed. A red watch files one fix item.
- **inert files**: queue records, check records and the handover (lib/relay_inert.py `INERT`). Two commits that differ only in
  them have the same gate result, so a gate of one counts for the other (`reusable`, lib/relay_gate_logs.py:92).
- **same-commit pair**: a Mac gate result and a Linux gate result of the same commit, or of two commits that differ only in inert
  files.
- **wave**: the changes landed between two paid runs (front skill, line 176); the paid run's dated events are in
  `.git/relay-paid/events.jsonl`.
- **twin** (new, approach B): a Linux gate of the exact commit whose landing gate went red on the Mac.

## 3. Measurements (30 Oct, master a4733e75)

| what | number | source |
|---|---|---|
| remote gate logs, watch files, gate-host record | **0, 0, none**: the VPS has gated nothing yet; bring-up (change 5) not done | `.relay/checks/*.remote.gate.log`, `.git/relay-land/linux/`, `~/.relay/gate-hosts.json` |
| Mac gate logs on master | 798, 797 of them `bin/ci --quick`; 644 green, 154 red (19%) | exit lines of `.relay/checks/*.gate.log` |
| Mac reds that turned green with **no code change** (only inert files between the red commit and the next green descendant) | **16 of 154** reds, so about **2.0%** of all Mac gates are red for no reason in the code (a lower bound) | git walk from each red commit to its nearest green-gated descendant, `git diff --name-only` |
| landing attempts, 28 Oct 17:40Z - 30 Oct 16:42Z (47 h) | 100: 76 landed, 13 red, 10 conflict, 1 refused | `.git/relay-land/events.jsonl`, `done` events |
| landings that ran a new Mac gate vs reused the branch's | **56 of 76 (74%) ran a new gate** on the merged head; 20 reused (only inert files came in) | `gates_run` of the landed events |
| landing gate time | median 894 s (69 timed) | `gate_seconds` |
| paid runs (waves) | 1-3 eval records a day over 22-30 Oct; the 29 Oct note counted 10 waves in 5 days; paid events recorded only since 30 Oct 14:48Z (1 run) | `~/.relay/evals/relay/*.json`, `.git/relay-paid/events.jsonl` |
| what the container receives | `--network none`, `-e RELAY_GATE=<sha>` only, no mount; image from `container/Containerfile` | lib/relay_gate_remote.py:208-209 |

What the numbers mean for the design:

1. **The build-time remote gate and the Mac landing gate are not a fair pair.** In 74% of landings the Mac gated a commit (the
   branch plus the newly taken default branch) that no build-time gate saw. The pair the front named on 30 Oct ("its newest remote
   log and its Mac landing log") compares different code 3 times in 4. The Linux watch of the landed head is the same-commit pair;
   the VPS plan already said so.
2. **The watch alone sees only half of the disagreements.** The watch runs only after a green landing, so it can find "Linux red
   where the Mac was green" but never "Linux green where the Mac was red". 13 of 100 landing attempts were red on the Mac; one of
   them (30 Oct 06:20Z, `BlockingIOError [Errno 35]`, a git process could not start under load) was a Mac-only red by its cause.
3. **Noise decides whether a streak rule can ever be met.** 3 waves are about 1.5 days, about 57 landings at 1.6 an hour. If
   Linux had the Mac's measured 2.0% no-cause red rate, 57 green-landing pairs would all agree with probability 0.98^57, about
   **32%**; with both sides noisy, about 10%. A "N in a row" rule without a re-run of a disagreement would reset most of the time.

Not measured: anything about Linux results (no remote gate has run); Linux's own no-cause red rate; the VPS gate's time (guessed
at about 5 min in the VPS plan, from three git-heavy test files 4.6-5.6x faster there); how many landed heads the watch skips when
two landings come while it runs (its lock gates only the newest tip).

## 4. How leading tools solve it

- **Run beside, then promote by hand.** GitLab's `allow_failure: true`, GitHub Actions' `continue-on-error` and Buildkite's
  `soft_fail` let a new platform's job run beside the deciding one without blocking a merge; the switch to "required" is a person
  changing the required checks, not an automatic count. Chromium's experimental ("FYI") builders run beside the commit queue and
  are moved into it by a person after a stable period. This supports keeping the switch the owner's word.
- **Compare on the exact commit.** bors and GitHub's merge queue decide on the exact merge commit; a result of another commit is
  not evidence. Hence same-commit pairs (section 3, point 1).
- **Re-run a disagreement before calling it real.** Bazel's `--flaky_test_attempts` and Google's TAP re-run a failing test on the
  same commit and mark it flaky when the re-run passes. Hence one re-run on the cheap side (the VPS) before a disagreement counts.
- **Compare by step, not only by exit.** CI analytics tools (BuildPulse, Datadog CI Visibility) diff per-test results across
  runs; relay's logs give the first failing step (`first_failure`, lib/relay_gate_logs.py:64), which is enough to say where.

(From documentation as known to me, not re-read today.)

## 5. Approaches

| | A. Same-commit pairs from runs that already happen | B. A plus a twin of each red landing and one re-run on a disagreement (recommended) | C. A container beside every Mac gate on this Mac's podman (the item's 27 Oct text) | 0. Do nothing |
|---|---|---|---|---|
| what is compared | Mac landing gate vs the Linux watch of the landed head | the same, plus Mac-red landing heads vs their Linux twin | every Mac gate vs a container gate of the same commit | nothing; a red watch still files a fix item |
| "Linux red, Mac green" seen | yes | yes, with a flaky re-run first | yes | only as the watch's fix item, not counted |
| "Linux green, Mac red" seen | **no** | yes (about 13 per 100 landing attempts get a twin) | yes | no |
| extra Linux runs | 0 | about 6.6 a day (13 red attempts in 47 h) plus one per disagreement, on the idle VPS | about 94 a day, on this Mac | 0 |
| extra Mac time | 0 | 0 | about 21 min of container per gate at today's load (30 Oct), against the owner's 30 Oct pick of the VPS | 0 |
| agent time to build (guess, not measured) | about 100 min | about 160 min | about 200 min, mostly already built for the VPS | 0 |
| owner's evidence for the move to Linux | one-sided | both sides | both sides | none |

C is listed because it is what the item's text literally says; it is out: the owner put the comparison on ai.amidman.com (30 Oct,
"1. Сравнивать данные с удаленной машиной ai.amidman.com"), and this Mac is the loaded machine (load 20-48).

Doing nothing costs no agent time and keeps the Linux watch's fix items; it loses the one number the owner asked for in the first
place ("При этом получать тот же результат"): whether Linux and the Mac give the same result.

A against B is the one real choice: section 9.

## 6. Decisions made here (each: owner can reverse)

1. **No automatic switch.** The comparison is shown, it never moves the landing decision. Rests on the owner's 29 Oct answer to the
   question about the 3-wave period ("пока мы полностью не перешли на linux продолжим делать проверки на mac") and on section 3
   point 3. The item's `what` should be amended through the queue to say so (the front does it with the owner's 29 Oct words).
2. **Pairs are same-commit only** (inert stretch allowed). The build-time remote gate is not paired with the landing gate (section
   3 point 1). This narrows the front's 30 Oct reading "its newest remote log and its Mac landing log"; the watch it relies on is
   the one the VPS plan named.
3. **Shown per wave and as a running count.** Wave boundaries are the dated paid-run events; before the first recorded run the
   group is "before the first recorded wave". Nothing new is stored: every number is computed from the logs, the watch and twin
   files and the paid events when read (principle 3).
4. **No dependency on the same-setup item.** The item's `why` says it "needs the same-setup item first"
   (`a-change-runs-with-relay-s-settings-from-the-pro`). That holds for running agents in a container (they need plugins, rules and
   hooks); the gate in a container needs none of it and already runs without it (section 3, last row). This item does not wait.
5. **Scope stops at the gate.** Agents (build, review, fix, check) in containers stay with the same-setup item and the 27 Oct
   design's approach A; nothing here starts them.
6. **Nothing in bin/ci, deps.toml or the Containerfile changes.** The item's `where` lists them; the image and the pins were done by
   the clean-Linux fixes (closed 29 and 30 Oct).

## 7. Specification (for B; A is B without 7.3 and 7.4)

### 7.1 Where the comparison shows

`relay hosts status` (lib/relay_gate_watch.py `status_lines`) gets a block per host, after the watch line. The front's wave digest
reads the same lines. Example, with made-up numbers:

```
  Linux and Mac on the same commit (last 3 waves):
    wave since 30 Oct 16:23Z: 9 landed heads, 8 paired, 8 agree; 1 without a Linux result (the watch gated a later head)
    wave 30 Oct 14:48Z-16:23Z: 5 paired, 3 agree; 1 Linux-only red, reproduced: 1a2b3c4d5e6f step library tests (fix item x);
      1 Mac-only red: 7f8e9d0c1b2a step library tests, Linux green (twin)
    agreeing pairs in a row: 12; the Mac decides landings until the move to Linux (owner, 29 Oct)
```

The same lines come from `relay hosts compare [--waves N]` for more history. Code: a new `lib/relay_gate_compare.py`
(lib/relay_gate_watch.py is at 254 lines; tests/test_module_sizes.py caps a module at 600).

### 7.2 Pairing and verdicts

For each landed head H of the default branch's first-parent line inside the shown waves:
- the Mac result: the Mac gate log `reusable(main, H, quick command, "mac")` finds (the landing gate, or a gate it reused);
- the Linux result: the watch file of H or of a commit in H's inert stretch.

For each twin file (7.3): its commit's Mac log, found in the default branch's `.relay/checks` or, when the branch has not landed,
on the branch the twin file names; a branch dropped since means "no Mac result" and no pair.

Verdicts: **agree** (both green, or both red); **Linux-only red** and **Mac-only red**, each "reproduced" or "flaky" by the re-run
(7.4); **no Linux result** (the watch skipped the head, stopped at its limit with exit 124, or could not run): never counted as
agreement. Red means `0 < n < 127` and `n != 124`, the rule `is_red` already uses. A disagreement line names the first failing step
of the red side (`first_failure`). "In a row" counts pairs, newest first, until the first reproduced disagreement; a flaky one
does not break it.

### 7.3 The twin (B)

After a landing ends **red at its gate** (not conflict, not refused), `relay land` starts, after the done event and outside its lock
(as `_start_watch` does, lib/relay_land.py:313), a detached `relay gate --twin <sha> -C <main>` of the commit its gate judged, when a
host is recorded and `twin_red_landings` is on. It runs the watch's remote path on that exact commit (the pinned ref
`refs/relay-gate/<sha>` already carries any commit) and writes `.git/relay-land/linux/twin/<sha>.remote.gate.log` with one header
line `branch <name>`. A twin files no fix item and is never read by `default_red`, the stop-sending rule's "default branch" logic,
or the merge hook. A twin that cannot run appends the usual could-not-run event (it counts toward the stop-sending rule like any
remote attempt).

This reverses one existing test on purpose: tests/test_gate_watch.py:250
`test_a_landing_that_does_not_land_starts_nothing` becomes "a landing that is red at its gate starts the twin; a conflict or a
refusal starts nothing".

### 7.4 One re-run of a disagreement (B)

When a watch or a twin disagrees with its Mac result, the VPS runs the same commit once more before the verdict is final; the
watch files its fix item only when the re-run is red too. The Mac side is never re-run by the comparison (a Mac gate costs a median
894 s on the loaded machine; the landing's own retry already re-gates).

### 7.5 Settings

In the gate-host record (`$RELAY_HOME/gate-hosts.json`), written only by `relay hosts set` (lib/relay_hosts.py), schema-checked:

| setting | default | bound | at the bound |
|---|---|---|---|
| `twin_red_landings` (B) | on | on/off | off: Mac-only reds are never seen; the block says "Mac-red landings are not twinned" |
| `rerun_disagreement` (B) | 1 | 0-3 | 0: every Linux flake counts as a disagreement and files a fix item; 3: a real Linux-only failure costs 4 VPS gates (about 20 min, guess) before its fix item |
| `compare --waves` (argument, not stored) | 3 | 1-20 | 1: only the current wave; 20: about 10 days, one line per wave |

## 8. Tests (each "never" and "only" names the test that fails when it is false)

1. Green Mac log and green watch file on H: one pair, agree.
2. Green Mac log on H, red watch on a queue-only commit after H: paired through the inert stretch, Linux-only red, step named.
3. **A missing Linux result never counts as agreement:** watch exit 124, a could-not-run event and no file, a skipped head: each
   is "no Linux result" and leaves "in a row" unchanged.
4. **The comparison only reads:** a run over a fixture repository leaves the tree, `git status`, the refs and `.git/relay-land`
   byte-identical (checksums before and after).
5. **The container never lands anything:** already pinned by tests/test_gate_remote.py:85 (the merge hook refuses a head with only
   a remote log) and :98 (a landing never calls the remote); a twin file beside a red Mac log changes neither.
6. (B) A landing red at its gate starts `relay gate --twin <sha>` once, after the done event; conflict and refused start nothing;
   a twin start that fails is one line and never changes the outcome.
7. (B) A red twin files no fix item and leaves `default_red` "".
8. (B) Watch red, re-run green: verdict "flaky", no fix item, "in a row" unbroken; watch red, re-run red: "reproduced", one fix item.
9. Waves split at the dated `synced` events; with none, one group "before the first recorded wave".
10. Settings out of bound are refused by `relay hosts set` with the bound in the message.

All in temporary folders with the fake ssh and podman of tests/test_gate_watch.py; none reads the live queue, checks or handover.

## 9. Order and estimate

One change, built now with fakes; the first real numbers come after the VPS bring-up (change 5 of
`gates-on-the-vps-hosts-transport-watch-bring-up`, which needs the owner present for 3 root commands). A: about 100 agent minutes
with review and fix; B: about 160 (the item says 180). Guesses scaled from the VPS plan's change 4 (95 min), not measured.

## 10. Critique

**Of the owner's picks, once.**
- **27 Oct "3. A"** (the Mac re-gates until 3 waves in a row agree, then the container decides): as a rule it would rarely fire.
  At the Mac's measured 2.0% no-cause red rate, about 57 pairs in 3 waves all agree with probability about 32% if Linux is as
  noisy, 10% if both sides can flake; without a re-run of each disagreement it resets most of the time. It is also superseded:
  the owner's 29 Oct answer to the same question keeps the Mac deciding until the move to Linux. This plan follows 29 Oct.
- **30 Oct "a"** (the VPS decides build-time gates) moved build gates into the container with no agreement period at all. That is
  sound only because the Mac landing gate still decides every merge; its costs are listed in the VPS plan (section 6) and stand.
- **30 Oct "1. Сравнивать данные с удаленной машиной ai.amidman.com"**: I looked; no weakness in the place itself (the VPS is idle,
  load 0.01). The weakness is in the front's reading of it, next.

**Of the brief's and the item's own picks.**
- The front's reading "the comparison reads those two results and starts no extra run" pairs the build-time remote gate with the
  Mac landing gate: different code in 74% of landings (56 of 76), and it never sees a Mac-only red. Replaced by same-commit pairs
  (decision 2); whether to add the twin runs is the question below.
- "Needs the same-setup item first": not for the gate (decision 4). Waiting for it would hold this item behind 180 minutes of
  unrelated work.
- The item's `where` (bin/ci, deps.toml, a container image) is already done elsewhere; the real files are lib/relay_gate_watch.py,
  lib/relay_land.py, lib/relay_hosts.py and a new lib/relay_gate_compare.py.
- The brief's `why` says "IP 84 chosen by the front"; the item's record says ip 95. Not decided here; the front can set one.

## 11. Open for the owner

**Linux twin of each red landing**

The comparison puts a Mac result and a Linux result of the same commit side by side. Today the only Linux run of a landed commit is
the watch, which starts after a **green** landing, so it can only catch "Linux fails where the Mac passed". The other half, "Linux
passes where the Mac failed", needs a Linux run of the commit the Mac rejected. Live example: on 30 Oct at 06:20Z the landing gate
of the clean-Linux fix went red on the Mac because a git process could not start under load (`Errno 35`); nothing was wrong in the
code, and today no record says so. With twins, the VPS would have gated that same commit and the comparison would show "Mac-only
red". The front read the owner's 30 Oct words as "no extra run"; this option reverses that reading.

| | twins on red landings | only runs that already happen |
|---|---|---|
| extra VPS gates | about 6.6 a day (13 red of 100 landing attempts in 47 h) + 1 per disagreement | 0 |
| extra Mac time | 0 | 0 |
| sees Mac-only reds | yes | no |
| Linux flake files a fix item | no (one re-run first) | yes, as today |
| agent time | about 160 min | about 100 min |

- a. Twin each red landing on the VPS and re-run a disagreement once (recommended; rests on 13 of 100 attempts red and 16 of 154
  Mac reds with no code cause, measured).
- b. Compare only the runs that already happen: the watch and the landing gate.

## 12. What the brief could not answer

- No Linux result exists yet (bring-up not done), so the agreement rate, Linux's noise and the VPS gate time are not measured.
- Whether the owner still wants a number that would trigger the move to Linux (for example "N reproduced-free waves"), or only the
  shown evidence: the 29 Oct answer says the Mac decides "until we fully move to Linux", without a test for "fully". Not asked:
  it is the owner's own plan for his machines, and nothing here needs it.
