# Plan: Each change is gated in a fresh container (now: the Linux and Mac comparison)

Revision 2, 30 Oct 2026, thinker, after the design review of revision 1 (9 findings, section 13). Queue item
`each-change-is-gated-in-a-fresh-container` (feature, ip 95, 180 min, taken 30 Oct 16:42Z by
`wt/each-change-is-gated-in-a-fresh-containe`). Read-only: no code changed. Read against master a4733e75.

## 1. Short answer

Most of what this item asked for on 27 Oct has since been **built** by another item, `gates-on-the-vps-hosts-transport-watch-bring-up`
(changes 3 and 4 landed 30 Oct, e4e99dc1); it is **not running yet**: change 5, the bring-up on the VPS, is open, and the VPS has
gated nothing so far (section 3, first row). Once brought up, every build-time gate runs `bin/ci --quick` in a **fresh rootless
podman container** on the VPS ai.amidman.com, built from `container/Containerfile` (the pinned Python 3.14.6 and the tools of
deps.toml), with `--network none`, no host folder mounted, only `RELAY_GATE` in its environment, and only the commit sent in a
bundle (lib/relay_gate_remote.py:208-209). It **never lands anything**: the merge hook and `relay land` read only the Mac log,
pinned by tests/test_gate_remote.py:85 and :98. After each landing, one Linux gate of the new default-branch head runs there (the
**Linux watch**, lib/relay_gate_watch.py).

What is left is the part that item left to this one (its plan, 5.6: "The Linux comparison ... Built by the comparison item, not
here"): **compare the Linux and Mac results of the same code, per wave, and show how often they agree**, plus one re-run on the VPS
of a red Linux result before it counts or files a fix item.

Recommended: approach B (section 5): the same-code pairs that already happen, plus one Linux run (a **twin**) of each commit whose
landing gate went red on the Mac when no Linux result of that code exists yet. About 185 agent minutes (guess); no Mac gate time added.

Two choices are the owner's (section 11): whether the container's result ever takes over the landing decision by itself (the
item's 27 Oct promise; revision 1 dropped it on its own, which the review rightly called a scope cut), and whether to add the twins.

## 2. Terms

- **gate**: `relay gate`, which runs `bin/ci --quick` and commits a log `.relay/checks/<sha>.gate.log` ending `exit <n>`.
- **landing gate**: the gate `relay land` runs on the branch after it takes the default branch; only its Mac result decides a merge.
- **remote gate**: a gate whose command ran in the container on the VPS (log `<sha>.remote.gate.log`).
- **Linux watch**: one remote gate of the default branch's head after each landing; its result is a file in the git folder
  (`.git/relay-land/linux/<sha>.remote.gate.log`), never committed. A red watch files one fix item.
- **red**: an end line `exit n` with `0 < n < 127` and `n != 124` (`is_red`, lib/relay_gate_watch.py:36). 124 is a stop at the
  time limit, neither green nor red.
- **inert files**: queue records, check records and the handover (lib/relay_inert.py `INERT`). Two commits that differ only in
  them have the same gate result, so a gate of one counts for the other (`reusable`, lib/relay_gate_logs.py:92).
- **inert stretch of X**: X and the commits before it on its own first-parent line back to the first commit after which a
  non-inert file changed (the walk `reusable` does).
- **same-code pair**: a Mac gate result and a Linux gate result of two commits in one inert stretch (the same commit included).
- **Linux result of X**: the newest of the remote runs of X's inert stretch: a committed build-time remote gate log, a watch file,
  a twin file, or a re-run file of any of them.
- **judged commit**: the commit a landing gate ran on (the branch after the take); for a green landing it is the landed head.
- **wave**: the changes landed between two paid runs (front skill, line 176); the paid run's dated `synced` events are in
  `.git/relay-paid/events.jsonl`.
- **twin** (new, approach B): a Linux gate of the judged commit of a landing whose gate went red on the Mac.
- **re-run** (new): one more VPS gate of the same commit after a red Linux result, before that result counts.

## 3. Measurements (30 Oct, master a4733e75)

| what | number | source |
|---|---|---|
| remote gate logs, watch files, gate-host record | **0, 0, none**: the VPS has gated nothing yet; bring-up (change 5) not done | `.relay/checks/*.remote.gate.log`, `.git/relay-land/linux/`, `~/.relay/gate-hosts.json` |
| Mac gate logs on master | 798, 797 of them `bin/ci --quick`; 644 green, 154 red (19%) | exit lines of `.relay/checks/*.gate.log` |
| Mac reds that turned green with **no code change** (only inert files between the red commit and the next green descendant) | **16 of 154** reds, so about **2.0%** of all Mac gates are red for no reason in the code (a lower bound) | git walk from each red commit to its nearest green-gated descendant, `git diff --name-only` |
| landing attempts, 28 Oct 17:40Z - 30 Oct 16:42Z (47 h) | 100: 76 landed, 13 red, 10 conflict, 1 refused (reproduced by the review) | `.git/relay-land/events.jsonl`, `done` events |
| landings that ran a new Mac gate vs reused the branch's | **56 of 76 (74%) ran a new gate** on the merged head; 20 (26%) reused (only inert files came in) | `gates_run` of the landed events |
| the commit a red landing judged | **not recorded**: all 13 red done events have `sha` None (`Event.sha` is "done: the landed head", lib/relay_land.py:55) | events.jsonl |
| what followed each red landing | 13 of 13 had a later landing attempt of the same branch: 9 landed, 2 red, 2 conflict; whether the branch's code changed in between is not recorded (`code_moves` absent in those events) | events.jsonl, next `done` of the same branch |
| retries of a red landing gate | **none**: `_locked` raises `Stop(RED)` on the first non-zero exit (lib/relay_land.py:389-390); each red event has `gates_run` 1 | code, events.jsonl |
| landing gate time | median 894 s (69 timed) | `gate_seconds` |
| paid runs (waves) | 1-3 eval records a day over 22-30 Oct; the 29 Oct note counted 10 waves in 5 days; paid events recorded only since 30 Oct 14:48Z (1 run) | `~/.relay/evals/relay/*.json`, `.git/relay-paid/events.jsonl` |
| what the container receives | `--network none`, `-e RELAY_GATE=<sha>` only, no mount; image from `container/Containerfile` | lib/relay_gate_remote.py:208-209 |

What the numbers mean for the design:

1. **The build-time remote gate and the Mac landing gate are a fair pair only when the take brought inert files.** In 74% of
   landings the Mac gated a commit (the branch plus the newly taken default branch code) that no build-time gate saw; in the other
   26% the code is the same and the pair is fair. The Linux watch of the landed head is a same-code pair every time.
2. **The watch alone sees only half of the disagreements.** It runs only after a green landing, so it can find "Linux red where the
   Mac was green" but never "Linux green where the Mac was red". 13 of 100 landing attempts were red on the Mac; one of them (30 Oct
   06:20Z, `BlockingIOError [Errno 35]`, a git process could not start under load) was a Mac-only red by its cause.
3. **Noise decides whether a streak can ever be met.** 3 waves are about 1.5 days, about 57 landings at 1.6 an hour. The Mac side of
   a watch pair is always green (the head landed; `reusable` returns only green logs), so only Linux noise breaks those pairs. At
   the Mac's measured 2.0% no-cause red rate, 57 pairs all agree with probability 0.98^57, about **32%** without a re-run; with one
   re-run, a flake breaks the streak only when both runs are red, 0.02² per pair, so about **98%** (0.9996^57, assuming the two
   runs fail independently; not measured).

Not measured: anything about Linux results (no remote gate has run); Linux's own no-cause red rate; the VPS gate's time (guessed
at about 5 min in the VPS plan, from three git-heavy test files 4.6-5.6x faster there); how many landed heads the watch skips when
two landings come while it runs (its lock gates only the newest tip); how often a red landing's branch is gated again on the Mac
with no code change.

## 4. How leading tools solve it

- **Run beside, then promote by hand.** GitLab's `allow_failure: true`, GitHub Actions' `continue-on-error` and Buildkite's
  `soft_fail` let a new platform's job run beside the deciding one without blocking a merge; the switch to "required" is a person
  changing the required checks, not an automatic count. Chromium's experimental ("FYI") builders run beside the commit queue and
  are moved into it by a person after a stable period.
- **Compare on the exact code.** bors and GitHub's merge queue decide on the exact merge commit; a result of other code is not
  evidence. Hence same-code pairs (section 3, point 1).
- **Re-run a failure before calling it real.** Bazel's `--flaky_test_attempts` and Google's TAP re-run a failing test on the same
  commit and mark it flaky when the re-run passes. Hence one re-run on the cheap side (the VPS).
- **Compare by step, not only by exit.** CI analytics tools (BuildPulse, Datadog CI Visibility) diff per-test results across
  runs; relay's logs give the first failing step (`first_failure`, lib/relay_gate_logs.py:64), which is enough to say where.

(From documentation as known to me, not re-read today.)

## 5. Approaches

| | A. Same-code pairs from runs that already happen, plus the re-run | B. A plus a twin of each red landing with no Linux result (recommended) | C. A container beside every Mac gate on this Mac's podman (the item's 27 Oct text) | 0. Do nothing |
|---|---|---|---|---|
| what is compared | landed heads vs their Linux result (watch, or the branch's remote log when only inert files were taken); red landings vs a remote log of their stretch, when one exists | the same, plus red landings vs their twin | every Mac gate vs a container gate of the same commit | nothing |
| "Linux red, Mac green" seen | yes, re-run first | yes, re-run first | yes | only as the watch's fix item, not counted |
| "Linux green, Mac red" seen | only for red landings whose take brought inert files (about 26% if the landed share holds; not measured) | every red landing that reached a gate | yes | no |
| a Linux flake files a fix item and sends lanes to the Mac | no (the re-run decides) | no | n/a | yes, as today |
| extra Linux runs | one per red Linux result | that, plus at most 6.6 a day (13 red attempts in 47 h), about 4.9 if 26% have a remote log already | about 94 a day, on this Mac | 0 |
| extra Mac time | 0 | 0 | about 21 min of container per gate at today's load (30 Oct), against the owner's 30 Oct pick of the VPS | 0 |
| agent time to build (guess, not measured) | about 135 min | about 185 min | about 200 min, mostly already built for the VPS | 0 |

C is listed because it is what the item's text literally says; it is out: the owner put the comparison on ai.amidman.com (30 Oct,
"1. Сравнивать данные с удаленной машиной ai.amidman.com"), and this Mac is the loaded machine (load 20-48).

Doing nothing costs no agent time; it loses the one number the owner asked for in the first place ("При этом получать тот же
результат"), and it keeps today's defect that one Linux flake files a fix item and sends every lane gate to the Mac until the
next landing.

A against B is the second question of section 11.

## 6. Decisions made here (each: owner can reverse)

1. **Pairs are same-code only.** The Linux result of a commit is the newest remote run of its inert stretch (section 2). A
   build-time remote log pairs with the landing gate only when the take brought inert files; otherwise the watch (green landing)
   or the twin (red landing) gives the Linux side. This narrows the front's 30 Oct reading "its newest remote log and its Mac
   landing log", which compares different code in 74% of landings.
2. **Landed heads come from done events, not from the first-parent line.** Landings fast-forward, so master's first-parent line
   also carries every branch's own commits (on 30 Oct: 134 commits, 31 gate-log commits, 19 take merges). The comparison takes
   the `sha` of each `landed` done event inside the wave, and the `judged` commit (decision 3) of each red one.
3. **One new dated fact, the rest computed when read.** A done event whose landing gate ended red by `is_red` records the commit
   that gate judged in a new field `judged`. Not in `sha`: lib/relay_metrics.py:522 matches done events by `sha` alone, and a
   branch re-landed with the same take would then match its red event too. Everything else (pairs, verdicts, waves, streak) is
   computed from the logs, the watch, twin and re-run files and the paid events (principle 3).
4. **The re-run is in the base plan, not a choice.** It costs only idle VPS time (load 0.2) and removes a defect that exists
   today: a Linux flake files a false fix item and sends every lane to the Mac. It needs no twin.
5. **Nothing switches until the owner answers section 11's first question.** This change builds the comparison; a switch rule,
   if chosen, is a follow-on change of its own.
6. **No dependency on the same-setup item.** The item's `why` says it "needs the same-setup item first"
   (`a-change-runs-with-relay-s-settings-from-the-pro`). That holds for agents in a container (they need plugins, rules and hooks);
   the gate in a container needs none of it (section 3, last row). This item does not wait.
7. **Scope stops at the gate.** Agents (build, review, fix, check) in containers stay with the same-setup item and the 27 Oct
   design's approach A.
8. **Nothing in bin/ci, deps.toml or the Containerfile changes.** The item's `where` lists them; the image and the pins were done by
   the clean-Linux fixes (closed 29 and 30 Oct).

## 7. Specification (for B; A is B without 7.3)

### 7.1 Where the comparison shows

`relay hosts status` (lib/relay_gate_watch.py `status_lines`) gets a block per host, after the watch line. The front's wave digest
reads the same lines. Example, with made-up numbers:

```
  Linux and Mac on the same code (last 3 waves):
    wave since 30 Oct 16:23Z: 9 landed heads, 8 paired, 8 agree; 1 without a Linux result (the watch gated a later head)
    wave 30 Oct 14:48Z-16:23Z: 5 landed, 2 red landings; 5 agree; 1 Linux-only red, reproduced: 1a2b3c4d5e6f step library tests
      (fix item x); 1 Mac-only red, not re-run on the Mac: 7f8e9d0c1b2a step library tests, Linux green (twin)
    agreeing pairs in a row: 12; 2 unresolved; the Mac decides landings (owner, 29 Oct)
```

The same lines come from `relay hosts compare [--waves N]` for more history. Code: a new `lib/relay_gate_compare.py`
(lib/relay_gate_watch.py is at 254 lines; tests/test_module_sizes.py caps a module at 600).

### 7.2 Pairing and verdicts

Inside the shown waves:
- for each `landed` done event, H is its `sha`; the Mac side is green (the landing gate or the log it reused); the Linux side is
  the Linux result of H;
- for each `red` done event with `judged` J, the Mac side is red; the Linux side is the Linux result of J. A red event with no
  `judged` (a stop at the limit twice, exit 124) is not a pair and is not listed. Conflict and refused events are listed nowhere.

Verdicts:
- **agree**: both green, or both red.
- **Linux-only red**: "flaky" when the re-run (7.4) is green, "reproduced" when it is red too.
- **Mac-only red**: the Mac side is resolved from the next Mac gate of the same code, which costs no new Mac run: a Mac gate log,
  on the default branch or on the branch the red event names, of a commit whose inert stretch holds J (for example the branch's
  next `relay land` after only inert files came in). Green: "flaky on the Mac"; red: "reproduced on the Mac"; none: "not re-run
  on the Mac".
- **no Linux result**: the watch skipped the head, stopped at its limit, could not run, sending was stopped, or no twin ran.

"In a row" counts pairs, newest first, until the first **reproduced** disagreement (on either side). Flaky ones neither break nor
extend it; "no Linux result" and "not re-run on the Mac" neither break nor extend it and are shown as "unresolved" with their
count, so a gap is visible, never counted as agreement. A disagreement line names the first failing step of the red side
(`first_failure`).

### 7.3 The twin (B)

After a landing ends red at its gate with `is_red(code)` (not 124, not conflict, not refused), `relay land` records `judged` and,
after the done event and outside its lock (as `_start_watch` does, lib/relay_land.py:313), starts a detached
`relay gate --twin <sha> -C <main>` when all hold: a host is recorded, `twin_red_landings` is on, sending is not stopped (the
stop-sending rule, `relay_gate_ssh.stopped`), and J's inert stretch has no Linux result yet (a branch whose take brought only inert
files already has its build-time remote log: no twin).

The twin does not go through the watch: it takes its own lock `linux/twin.lock` (blocking: twins run one at a time, in order, and
never write `watch.again`), and pins the commit under its own prefix `refs/relay-twin/<sha>` (the pinned prefix becomes an argument
of `relay_gate_ssh.gate`), which the watch's cleanup of `refs/relay-gate` never matches; under its lock the twin first deletes
leftover `refs/relay-twin/*` refs of a killed twin. It writes `.git/relay-land/linux/twin/<sha>.remote.gate.log` with one header
line `branch <name>`. A twin files no fix item and is never read by `default_red`, the stop-sending rule's "default branch" logic,
or the merge hook. A twin that cannot run appends the usual could-not-run event.

This reverses one existing test on purpose: tests/test_gate_watch.py:250 `test_a_landing_that_does_not_land_starts_nothing`
becomes "a landing red at its gate starts the twin; a conflict, a refusal or a stop at the limit starts nothing".

### 7.4 One re-run of a red Linux result (both A and B)

When a watch or a twin ends red, the same process runs the same commit once more on the VPS, up to `rerun_disagreement` times,
while it still holds its lock. Each run is a file of its own beside the first: `<sha>.rerun-<k>.remote.gate.log`, k = 1, 2, 3
(the first run keeps today's name). The **newest run of a commit is its Linux state**: `newest_watch` and the Linux result of 7.2
read it, so `default_red` is "" after a red run followed by a green re-run, and lane gates go back to the VPS. The fix item is
filed only when the last re-run is red too. While a re-run runs (about 5 min, guess) the first red file is the state, so lanes go
to the Mac for that time: the safe direction, and nothing is filed.

The Mac side is never re-run by the comparison (a Mac gate costs a median 894 s on the loaded machine); revision 1's reason "the
landing's own retry already re-gates" was false (section 3: no retry); the Mac side is resolved as in 7.2.

### 7.5 Settings

In the gate-host record (`$RELAY_HOME/gate-hosts.json`), written only by `relay hosts set` (lib/relay_hosts.py), schema-checked:

| setting | default | bound | at the bound |
|---|---|---|---|
| `rerun_disagreement` | 1 | 0-3 | 0: today's behaviour, every Linux flake files a fix item and sends lanes to the Mac until the next landing; 3: a real Linux-only failure costs 4 VPS gates (about 20 min, guess) before its fix item |
| `twin_red_landings` (B) | on | on/off | off: red landings without a remote log of their stretch show as "no Linux result (not twinned)", with their count |
| `compare --waves` (argument, not stored) | 3 | 1-20 | 1: only the current wave; 20: about 10 days, one line per wave |

## 8. Tests (each "never" and "only" names the test that fails when it is false)

1. Green landed head H, green watch file on H: one pair, agree.
2. Green landed H, red watch on a queue-only commit after H, re-run red: paired through the inert stretch, Linux-only red,
   reproduced, step named.
3. **A missing Linux result never counts as agreement:** watch exit 124, a could-not-run event and no file, a skipped head, a red
   landing with no twin: each is "no Linux result", counted as unresolved, and leaves "in a row" unchanged.
4. **The comparison only reads:** a run over a fixture repository leaves the tree, `git status`, the refs and `.git/relay-land`
   byte-identical (checksums before and after).
5. **The container never lands anything:** already pinned by tests/test_gate_remote.py:85 and :98; a twin file beside a red Mac
   log changes neither.
6. **Landed heads come only from done events:** a fixture branch with a red take merge then a green landing gives one landed head
   (the done event's sha), not the red take; two landings each with a gate-log commit give two pairs.
7. **Re-run, flaky:** watch red, re-run green on H: two files; verdict "Linux-only red, flaky"; no fix item; `build_remote` returns
   `default_red` "" and `deciding_host` returns "vps".
8. **Re-run, reproduced:** watch red, re-run red: one fix item; `default_red` names the step and the item.
9. `rerun_disagreement` 0: watch red files the fix item at once and `default_red` is set (today's behaviour); watch green: one
   file, no re-run.
10. (B) **The twin starts only on a red gate:** a landing red with Mac exit 1 records `judged` and starts the twin once, after the
    done event; Mac exit 124 twice, conflict and refused start nothing and record no `judged`; a twin start that fails is one line
    and never changes the outcome.
11. (B) Red landing whose take brought only inert files and whose branch has a remote log of the stretch: paired from that log, no
    twin started.
12. (B) Stop-sending rule holds: no twin is sent; the comparison shows "no Linux result (sending stopped)".
13. (B) **A twin never touches the watch:** a twin started while a watch runs writes no `watch.again`; a watch starting during a
    twin's bundle step leaves `refs/relay-twin/<sha>` in place; both files appear.
14. (B) A red twin files no fix item and leaves `default_red` "".
15. Mac-only red: twin green and a later Mac gate of the same code green gives "flaky on the Mac"; red with the same first step
    gives "reproduced on the Mac" and breaks "in a row"; no later Mac gate gives "not re-run on the Mac", unresolved.
16. A done event with `judged` set is never matched by relay_metrics' `sha` lookup (a re-landing of the same take records one
    landing, not two).
17. Waves split at the dated `synced` events; with none, one group "before the first recorded wave".
18. Settings out of bound are refused by `relay hosts set` with the bound in the message.

All in temporary folders with the fake ssh and podman of tests/test_gate_watch.py; none reads the live queue, checks or handover.

## 9. Order and estimate

One change, built now with fakes; the first real numbers come after the VPS bring-up (change 5 of
`gates-on-the-vps-hosts-transport-watch-bring-up`, which needs the owner present for 3 root commands). A: about 135 agent minutes
with review and fix; B: about 185 (the item says 180). Guesses scaled from the VPS plan's change 4 (95 min) plus the review's
size notes (15 + 15 + 20 + 5 min), not measured. If the owner picks the automatic switch, it is a second change after this one,
about 60 more minutes (guess).

## 10. Critique

**Of the owner's picks, once.**
- **27 Oct "3. A"** (the Mac re-gates until 3 waves in a row agree, then the container decides): without a re-run it would rarely
  fire, about 32% over 57 pairs at a 2% flake rate; with the re-run of 7.4 it becomes reachable, about 98% (section 3, point 3;
  independence assumed). Whether it should still fire by itself is the first question below.
- **30 Oct "a"** (the VPS decides build-time gates) moved build gates into the container with no agreement period at all. That is
  sound only because the Mac landing gate still decides every merge; its costs are listed in the VPS plan (section 6) and stand.
- **30 Oct "1. Сравнивать данные с удаленной машиной ai.amidman.com"**: I looked; no weakness in the place itself (the VPS is idle,
  load 0.01-0.2). The weakness is in the front's reading of it, next.

**Of the brief's and the item's own picks.**
- The front's reading "the comparison reads those two results and starts no extra run" pairs the build-time remote gate with the
  Mac landing gate: different code in 74% of landings (56 of 76), and it never sees a Mac-only red. Replaced by same-code pairs
  (decision 1); whether to add the twin runs is the second question below.
- The front's reading of the 29 Oct reply ("пока мы полностью не перешли на linux продолжим делать проверки на mac") as the end
  of the 3-wave switch, which revision 1 took over as a decision: that reply answered a question offering "three waves side by
  side" or "no period", picked neither, and came with "Останови docker"; on 30 Oct the owner then moved build gates to the VPS.
  It does not name the switch, so the switch goes to the owner (first question).
- "Needs the same-setup item first": not for the gate (decision 6).
- The item's `where` (bin/ci, deps.toml, a container image) is already done elsewhere; the real files are lib/relay_gate_watch.py,
  lib/relay_gate_ssh.py, lib/relay_land.py, lib/relay_hosts.py and a new lib/relay_gate_compare.py.
- The brief's `why` says "IP 84 chosen by the front"; the item's record says ip 95. Not decided here; the front can set one.

## 11. Open for the owner

**Does Linux take over the merge decision by itself?**

The item (27 Oct, your "3. A") promised: the Mac and the Linux container check side by side, and after 3 waves in a row agree
(about 1.5 days) the container's result decides merges by itself, while the Mac host still does the landing. On 29 Oct you wrote
"пока мы полностью не перешли на linux продолжим делать проверки на mac", in answer to a question about that period, without
naming the switch; revision 1 read it as "no switch" on its own. Live example: as planned now, even 10 agreeing waves change
nothing until you say the move is made; with the switch, the VPS would decide merges after 3 agreeing waves, and one reproduced
disagreement would hand the decision back to the Mac. The switch also reverses a pinned rule: today the merge hook refuses a head
that has only a remote log (tests/test_gate_remote.py:85). Leading CI tools move a new platform to "required" by a person, not by
a count. Not measured: how often a Mac-only break reproduces (no Linux result exists yet).

| | show only, you decide the move | automatic switch after N agreeing waves |
|---|---|---|
| who moves merges to Linux | you, after reading the counts | the count, after N = 3 waves (setting, bound 1-10; 1: about half a day) |
| a Mac-only break while you still work on the Mac | caught: the Mac decides every merge | lands once the switch fired, until a reproduced disagreement hands back |
| extra agent time | 0 | about 60 min (guess), a second change |
| Mac landing gate time saved after the switch | 0 until you decide | median 894 s per landing |

- a. Show only; the Mac decides merges until you say the move is made (recommended; rests on your 29 Oct words, on how GitLab,
  GitHub and Chromium promote a platform, and on there being no Linux result yet).
- b. Automatic switch after 3 agreeing waves, as the item said on 27 Oct.

**Linux twin of each red landing**

The comparison puts a Mac result and a Linux result of the same code side by side. Today the only Linux run of a landed commit is
the watch, which starts after a **green** landing, so it can only catch "Linux fails where the Mac passed". The other half, "Linux
passes where the Mac failed", needs a Linux run of the commit the Mac rejected. Live example: on 30 Oct at 06:20Z the landing gate
of the clean-Linux fix went red on the Mac because a git process could not start under load (`Errno 35`); nothing was wrong in the
code, and today no record says so. With twins, the VPS gates that same commit and the comparison shows "Mac-only red". The front
read your 30 Oct words as "no extra run"; this option reverses that reading. The re-run of a red Linux result is in both options.

| | twins on red landings | only runs that already happen |
|---|---|---|
| extra VPS gates | at most 6.6 a day (13 red of 100 landing attempts in 47 h), about 4.9 if 26% already have a remote log | 0 |
| extra Mac time | 0 | 0 |
| Mac-only reds seen | every red landing that reached a gate | only those whose take brought inert files (about 26%, not measured for red ones) |
| agent time | about 185 min | about 135 min |

- a. Twin each red landing that has no Linux result yet (recommended; rests on 13 of 100 attempts red and 16 of 154 Mac reds with
  no code cause, measured).
- b. Compare only the runs that already happen.

## 12. What the brief could not answer

- No Linux result exists yet (bring-up not done), so the agreement rate, Linux's noise and the VPS gate time are not measured.
- How often a red landing's branch is gated again on the Mac with no code change, which decides how many Mac-only reds stay
  "not re-run on the Mac": the done events do not record the branch's own code moves.

## 13. What changed after the review

The design review of revision 1 had 9 findings (3 MEDIUM, 6 LOW) and one wording note. All held; the fixes are in this revision.

| finding | held? | fix |
|---|---|---|
| F1 MEDIUM: the re-run had no file of its own; a flaky red watch kept every lane on the Mac with no fix item | held (gate_commit writes one file per sha; newest_watch reads only it; relay_gate_logs.py:197) | 7.4: one file per re-run (`<sha>.rerun-<k>.remote.gate.log`); the newest run is the commit's Linux state, read by `newest_watch` and `default_red`; tests 7-9 |
| F2 MEDIUM: a Mac-only red could not be judged; "the landing's own retry already re-gates" was false | held (relay_land.py:389-390, no retry; 13 red events each `gates_run` 1) | claim struck; Mac side resolved from the next Mac gate of the same code: "flaky on the Mac", "reproduced on the Mac" or "not re-run on the Mac" (unresolved, neither breaks nor extends the streak); test 15 |
| F3 MEDIUM: a red landing without a twin left no trace | held (13 of 13 red done events have `sha` None) | decision 3: a new `judged` field on red-at-gate done events (not `sha`, which relay_metrics.py:522 matches alone); 7.2 pairs from done events, a red event with no Linux result shows as "no Linux result"; tests 3, 16 |
| F4 LOW: the twin's relation to the watch lock and ref cleanup was unspecified | held (read, not run) | 7.3: own lock `twin.lock`, own ref prefix `refs/relay-twin/`, no `watch.again`; no twin while sending is stopped; tests 12, 13 |
| F5 LOW: decision 2 refused same-code pairs its own definition allows, so some twins repeated a Linux gate | held (20 of 76 landings took only inert files) | decision 1: the Linux result of a commit is the newest remote run of its inert stretch; no twin when one exists; test 11 |
| F6 LOW: landed heads were not said to come from done events | held (134 first-parent commits on 30 Oct, 31 gate-log commits, 19 take merges) | decision 2 and 7.2: landed heads are the `sha` of `landed` done events; test 6 |
| F7 LOW: a red landing from two limit stops (exit 124) got a twin that could never pair | held (relay_land.py:385-388) | 7.3: twin and `judged` only when `is_red(code)`; test 10 |
| F8 LOW: twins and the re-run were tied into one option; the 10% figure does not apply to watch pairs | held (the Mac side of a watch pair is always green) | decision 4: the re-run is in the base plan; the twin question stands alone; the 10% figure removed, 32% kept and the with-re-run figure added (section 3, point 3) |
| F9 LOW (question): dropping the item's 3-wave switch was the owner's choice, not the plan's | held (the 29 Oct reply does not name the switch) | revision 1's decision 1 moved to section 11 as the first question; decision 5 builds nothing that switches until answered |
| wording: section 1 said gates "already run" on the VPS while none has | held | section 1 says built, not running until the bring-up |
