# Plan: Gates on the VPS ai.amidman.com, changes 3-5 (hosts, transport, watch, bring-up)

Revision 4, 30 Oct 2026 ~12:30Z, thinker, after the design review of revision 3 (11 findings, all held; the last section says what
changed). Brings the reviewed design rev 2 (`design-vps-build-gates.md`, same scratchpad; it was also this item's plan file) up to
date with master 5779db85 for its changes 3-5. Not a redesign: the approach (A), the rules and the section numbers 5.1-5.9 stay,
because landed code cites them (lib/relay_gate_logs.py:44 "plan.md 5.1", :45 and :178 "design 5.4", :98 and :188 "design 5.2").
Read-only: no code changed; on the VPS only read-only commands ran as root (2.1).

Queue item `gates-on-the-vps-hosts-transport-watch-bring-up` (feature, ip 90, taken 30 Oct 12:03Z).

Owner's words this rests on, verbatim:
- 30 Oct 01:49Z, answer "a" to: "Should a gate on the VPS ai.amidman.com decide the gates run while a change is built, with the
  Mac running only the landing gate, or should the Mac keep deciding every gate?"
- 30 Oct 02:26Z, answer "a" to: "May relay set up the gate account on ai.amidman.com itself, using the owner's root login: create
  the account relay-gate (no admin rights, no docker access), its .ssh folder and relay's key line, each command shown before it
  runs, undone by deleting the account?"
- 30 Oct 10:53Z, on the Linux comparison: "1. Сравнивать данные с удаленной машиной ai.amidman.com" (front's reading: the
  comparison reads the VPS build-time gate and the Mac landing gate, no extra run).
- 30 Oct 04:58Z: "a, разве мы не приняли решение 3 на 3 ?" (one lane now for the VPS build).

Terms (the rest are in rev 2's list and unchanged): **gate** (`relay gate`, runs `bin/ci --quick` and commits a log
`.relay/checks/<sha>.gate.log`); **remote gate** (its command ran on the VPS; log `<sha>.remote.gate.log`); **deciding host** (the
machine whose result a gate request takes); **bundle** (`git bundle`, a packed set of commits `git clone` reads like a repository;
git refuses to bundle a bare commit id, it needs a ref name, checked 30 Oct: "Refusing to create empty bundle"); **slot** (a permit
to run one gate at a time on a machine); **Linux watch** (one VPS gate of a default-branch commit after each landing; its result
kept in the git folder, never committed); **end line** (`relay-gate-exit <n>`, printed by the container after `bin/ci` returned;
only it makes a result); **pinned ref** (a temporary ref `refs/relay-gate/<sha>` made only so a bundle can carry that exact
commit, deleted after); **stop-sending rule** (after a run of "could not run" endings, lanes stop going to the host until a watch
there reaches a result; 5.6).

## 1. Short answer: what is already built, what is left, what changed

**Built and landed (change 2, master ea468ce7, 30 Oct 08:05Z):** the remote log name and every reader (5.1); the deciding-host
table and reuse over the stretch (5.2) in lib/relay_gate_logs.py `deciding_host`, `reusable`, `finished_red`; the remote branch
of `relay_gate.run` (`_remote_gate`, lib/relay_gate.py:389) that commits `relay: remote gate of <sha>`, keeps a red remote result
when the host cannot be reached, and falls back with a line otherwise. The transport is an interface a test fills:

| type (lib/relay_gate_logs.py) | what change 3 must supply |
|---|---|
| `Remote(host, run, default_red="", holds_fix=False)` | built in `cmd_gate` (bin/relay:633) from the hosts record for a quick gate: the plain form **and** a `-- <args>` form whose command equals the quick binding's (the cycle's `relay gate -C <wt> -- --quick`, decision 7); today `cmd_gate` passes no `remote`, so every gate runs on the Mac |
| `run(worktree, head, command) -> RemoteResult(code, output, host_line, wait)` | the ssh transport of 5.3-5.5 |
| `RemoteUnavailable(text)` | raised for every "could not run" case of 5.5; the text is the line after `gate: ` |
| `default_red`, `holds_fix` | change 4 fills them from the Linux watch (5.6); until then "" and False |

**Left, in order:** change 3 (hosts record, ssh transport, remote program, fallback, the quick-form fix; about 200 agent minutes),
change 4 (the Linux watch, the stop-sending rule; about 95), change 5 (bring-up on the VPS, 3 root commands shown to the owner
first, then the paid clean-image step made conditional; about 65 plus gate time). Total about 6 h of agent time; the item says
4 h, rev 3 said 4 h 20 min. The review's eleven fixes add about 100 minutes (section 9); none changes the approach.

**What changed since rev 2, and what this revision decides about it (each: owner can reverse):**
1. **The prerequisite is met:** the clean-Linux fix (`the-quick-gate-is-red-again-in-a-clean-linux-ima`) closed 30 Oct 05:37Z;
   its "keep it green" is a paid-run step running the clean image on this Mac (lib/relay_ci_image.py), which the front noted "the
   VPS Linux watch replaces later". **Decided (revised after review F4):** change 5 makes the paid run **skip** that step when a
   green watch covers its head (a green watch file on a commit of the head's inert stretch), and run it as today otherwise (VPS
   down, watch off, watch red). Linux is checked once per commit when the VPS works (principle 2; the step took about 21 min of
   this Mac at load 30-43, 30 Oct) and never silently zero times when it does not.
2. **The quick gate's time limit and the remote wait collide.** Rev 2 5.4 applied the quick gate's limit to "the whole remote run".
   The limit is 1,800 s now (lib/relay_ci.py:53) and becomes 1,500 s with `speed-up-the-quick-gate` (owner: «30 минут сейчас, 25
   после ускорения»), in build now. A gate that waits the allowed 900 s for a VPS slot, then builds a missing image (311 s cold,
   measured on this Mac 27 Oct), has 289 s left of 1,500 for a gate guessed at about 5 min: a gate with nothing wrong would be
   cut as "stopped". **Decided (5.4):** the slot wait and the image build do not count; `bin/ci`'s own limit inside the container
   decides a stop (end line `relay-gate-exit 124`, handled as today), and the Mac keeps only a backstop that starts at the
   program's `relay-gate-running` line. The constant is read from lib/relay_ci.py, never copied.
3. **`relay_gate.py` is at 586 of 600 lines** (tests/test_module_sizes.py). **Decided:** change 3 adds no line to it; the Mac side
   goes to a new `lib/relay_gate_ssh.py`, the record to `lib/relay_hosts.py`, the VPS program to `lib/relay_gate_remote.py`.
4. **The record is JSON, not TOML** (`$RELAY_HOME/gate-hosts.json`, rev 2 5.7 said .toml): relay's TOML module only reads
   (lib/relay_toml.py has `load`, `loads`, no writer), the record is written only by `relay hosts`, never by hand, so JSON from the
   standard library is the path with fewer parts (principle 7). A setting is changed by `relay hosts set <host> <name> <value>`.
5. **relay's code never runs a root command.** Rev 2 5.9 had `relay hosts remove` "run every undo above", which includes
   `userdel -r` as root: a standing root capability in code, run without the owner seeing it, against "each command shown before
   it runs". **Decided:** `relay hosts remove` deletes the record and relay's key and prints the one root command that removes the
   account; `relay hosts add`, when relay's key does not open the account, prints the 3 root commands and refuses. The front shows
   them to the owner and runs them on the owner's word (5.9).
6. **`relay hosts add` proves the host and records it; it builds nothing and gates nothing (revised after review F10).** It logs
   in as `relay-gate`, installs the program, reads `podman info` and the subuid range, and writes the record: seconds, inside one
   4-minute command. The image build and the first gate belong to the first Linux watch (change 4), which bring-up runs detached
   with a log (5.9 step 4). Rev 2's F1 case (12 failing batches on a commit the Mac passed, 30 Oct) stays closed another way:
   **until the default branch has a Linux watch result, lanes gate on the Mac** with the line `gate: ai.amidman.com has not yet
   gated the default branch (run relay gate --watch-default); this gate runs on this Mac` (change 4, 5.6).
7. **The cycle's gate is a quick gate (new, review F1).** The cycle renders `relay gate -C <wt> -- --quick`
   (plugins/delegate/workflows/cycle.js:27 and :176; pinned by tests/test_cycle_workflow.py:607), the delegate skill teaches the
   same form (plugins/delegate/skills/delegate/SKILL.md:177), and `cmd_gate` counts any `-- <args>` as not quick (bin/relay:644),
   so as rev 3 stood no lane gate would ever reach the VPS. Both forms already run the same command: the newest 400 gate logs on
   master all say `cmd bin/ci --quick` (measured 30 Oct). **Decided (principle 5, fact to code):** `cmd_gate` counts a gate as
   quick when it is not paid and its command (binding plus extra arguments) equals the quick binding's command; `-- --quick` then
   is quick, `-- <anything else>` is not. cycle.js and the skill keep their text (no second form to retire, principle 7).

## 2. Measurements

### 2.1 Re-read now (30 Oct ~12:06Z, master 93016864; the review's reads added)

| what | rev 2 (30 Oct 06:00) | now | source |
|---|---|---|---|
| VPS load, memory | load 0.03-0.07, 14.3 GB available | load 0.01, 14,281 MB available, 115 GB disk free | ssh as root, `uptime`, `free`, `df` |
| VPS account `relay-gate` | none | **none**; `/etc/subuid` empty; `useradd` fills 65,536 ids (`SUB_UID_COUNT`, /etc/login.defs) | `id`, login.defs |
| VPS Python, podman | 3.12.3, 4.9.3 | same | |
| rootless cgroup limits | not measured | **`Delegate=pids memory cpu`** in the shipped user@.service; `user.slice` passes `cpu memory pids` down | systemd 255 unit file, `/sys/fs/cgroup/user.slice/cgroup.subtree_control` |
| ssh session handling | | `UsePAM yes` (each ssh login starts the account's systemd user manager, which rootless podman needs), `Linger=no` (that manager stops when the account's last session ends), `MaxSessions 10`, `MaxStartups 10:30:100` | `sshd -T`, `loginctl` |
| containers on the VPS | 8 | the same 8 (caddy, woodpecker-server, 2 woodpecker agents, athens, forgejo, tuda-lending, mailserver); 5 `zabbix_agentd` processes (a monitor, not listed before) | `docker ps`, `ps` |
| bundle of the default branch, full history | 6,156,876 bytes, 1.17 s (3,321 commits) | **6,664,450 bytes, 0.57 s** (3,671 commits) | `git bundle create - refs/heads/master` |
| landings | 1.5 an hour (48) | **1.59 an hour** (66 landed in 41.6 h; at most 4 in one clock hour); 19 since rev 2 | `.git/relay-land/events.jsonl`: 88 `done`, 66 landed, 12 red, 9 conflict, 1 refused |
| Mac gate logs with fork exhaustion (Errno 35) | 1 seen | 1 of 757 gate logs | grep over `.relay/checks/*.gate.log` |
| Mac gates committed on master today (UTC) | | 78 Mac, 0 remote | subjects `relay: gate of` / `relay: remote gate of` |
| gate form the cycle runs (new) | | `relay gate -C <wt> -- --quick`, the cmd line of all 400 newest gate logs is `bin/ci --quick` | cycle.js:27, :176; `.relay/checks/*.gate.log` line 2 |
| default branch moves right after a landing (new) | | queue commits 2 s apart (345549cc 16:03:54, 93016864 16:03:56 local); relay land itself commits change records after each landing (lib/relay_metrics.py `record_landing`) | `git log --first-parent master` |

Three facts change the plan: the cgroup limits are delegated (rev 2 had them "not measured"; 5.4's caps can stay, still to be
seen working at bring-up); `Linger=no` gives a second orphan backstop (5.4); and the bundle grows about 1.45 KB a commit (507 KB over
350 commits since rev 2), about 1.1 MB a day at the last day's 732 commits (613 of them queue, check or handover records), so it
reaches the bound of 2.3 in about 6 weeks. The review's two reads change two more: the cycle's form (decision 7) and the moving
default branch (the watch bundles a pinned ref, 5.3.2).

### 2.2 Still not measured

- A full quick gate on the VPS: time, result and **memory**. A remote gate runs with `RELAY_GATE` set, so `bin/ci` also starts the
  inert probe, a second nested quick run beside the first (lib/relay_ci.py:519-524). The paid clean-image step never ran that
  (lib/relay_ci_image.py:25 runs `bin/ci --quick` without `RELAY_GATE`), so "the clean-Linux quick gate is green" does not cover
  it, and whether 4 GiB holds two quick runs with 4 test workers each, mypy and bun is not known. Change 5 measures it: the
  program prints the container's peak memory into every remote log (5.3.8). The about-5-min figure stays a guess (4.6-5.6x from
  three git-heavy test files, 30 Oct).
- Whether a container left by a killed program is stopped when the account's last ssh session ends (`Linger=no`): expected from
  systemd's behaviour, checked at bring-up (5.9 step 5).
- Whether the zabbix monitor alerts on gate CPU. A gate runs at `cpu_shares` 256, below the services.
- How often the default branch goes Linux-red after a landing: the watch's fix items will count it.
- How often a remote run ends "could not run": the event file of 5.6 counts it from the first day.

### 2.3 Bundle growth, the bound that would change the transport

At 1.75 s per 6.2 MB (measured 30 Oct), a full-history bundle costs about 0.3 s a MB to send. It reaches 50 MB (about 14 s to
send, plus about 4 s to make) after about 43 MB / 1.45 KB ≈ 30,000 more commits: about 6 weeks at the last day's 732 commits, 9
weeks at the last week's 500 a day. Against a gate guessed at 5 min that is about 6%, so it does not change the design now. Not a
setting: when a gate's start line (5.5 prints the bytes) shows over 50 MB, that is a fix item. The two ways out, both for then:
a bundle that leaves out `.relay/` history the tests do not read (most of the growth: 613 of 732 commits of the last day touch
only queue, check or handover records), or an incremental bundle, which needs a copy kept on the VPS (owner, 28 Oct: no remote).

## 3. How leading tools solve it

Unchanged from rev 2 section 3 (Buildkite and GitLab runner tags, Bazel remote execution with local fallback, distcc host slots
over ssh, the "main is red" pipeline after each merge, woodpecker's fresh container per step). Additions:
- For the limit decision (1.2): GitLab and Buildkite count a job's timeout from when a runner picks the job up, not from when it
  was queued; Bazel's `--remote_timeout` covers one execution, not the wait for a worker. 5.4 follows them.
- For the stop-sending rule (review F3): distcc's host list marks a host that failed as down for a back-off period and compiles
  locally meanwhile (`DISTCC_BACKOFF_PERIOD`, 60 s by default); Bazel's `--remote_local_fallback` falls back per action but does
  not stop trying. Relay's gate costs minutes, not milliseconds, so a back-off by count with a probe (the watch) that clears it
  fits better than a timed one.
- For gating an exact commit (review F2): GitLab and Buildkite pipelines check out the pipeline's commit sha, never the branch
  tip at run time; the pinned ref does the same through a bundle.

## 4. Approaches

The choice between A (separate log file, bundle, rootless podman), B (host line in the same file, a bare repository, plain
processes) and doing nothing was made in rev 2 section 4 and built in change 2 (A). What is left to choose is narrower:

| for changes 3-5 | A3. Build changes 3-5 as planned (recommended) | B3. Stop after change 2: VPS used only by hand | 0. Do nothing more |
|---|---|---|---|
| Mac gate minutes per change | about 74 → about 15-17 (rev 2 2.3; holds only with decision 7) | about 74 | about 74 |
| what change 2's code does | runs | stays dead code (no caller passes `remote`) | stays dead code |
| Linux checking of the default branch | the watch after each landing (1.59 an hour); the paid clean-image step only when no green watch covers the head | the paid run's clean-image step on this Mac, about 21 min per paid run | the same |
| owner's work | see 3 root commands once | none | none |
| agent time | about 6 h | 0 | 0 |

Doing nothing leaves change 2's 55 agent minutes as code no caller reaches, and the Mac's measured cost: the landing gate's
median 789 s, 6 lanes and 2 slots at load 20-48, one fork-exhaustion red in 757 logs. Rests on: rev 2's measures and 2.1.

## 5. Specification (rev 2's sections, brought up to date)

### 5.1 The two logs and who reads which: **landed** (change 2)

As rev 2 5.1. One log per host per commit: `.relay/checks/<sha>.remote.gate.log` (lines `head`, `cmd`, `wait` = the VPS slot
wait, `host ai.amidman.com image relay-gate:<12 hex> tree <tree id>`, output, `exit <n>`) beside the Mac's `<sha>.gate.log`. The
merge hook and `relay land` read only the Mac log. Change 3 must keep the `host` line's second word the host name
(`log_sha_host` reads `line.split()[1]`).

### 5.2 Which host decides: **landed** (change 2), filled in by changes 3 and 4

As rev 2 5.2, implemented in `deciding_host` (lib/relay_gate_logs.py:187), in this order: no `remote` or not quick → Mac; no
`container/Containerfile` → Mac; the branch's newest Mac log red → Mac; `remote.default_red` and not `remote.holds_fix` → Mac;
the branch changes a toolchain file → Mac; else VPS. A landing passes no `remote`. Change 3 builds `remote` when the record
exists and the gate is quick by decision 7; change 4 sets `default_red` and `holds_fix`.

Two reasons to stay on the Mac are decided before a `Remote` exists, so landed code does not change: the builder in
lib/relay_gate_ssh.py returns either a `Remote` or a reason line, and `cmd_gate` prints `gate: <reason>; this gate runs on this
Mac` and passes no `remote`. The reasons (change 4): the default branch has no watch result yet (decision 6), and the
stop-sending rule holds (5.6). The "default branch is red" row stays where it is, because its line ("the default branch is red on
<host> ...") does not fit the other two.

### 5.3 Transport (change 3)

As rev 2 5.3, with these settled details:
1. `lib/relay_gate_ssh.py` builds the `Remote` and its `run`. On the Mac it runs ssh with a list of arguments (no local shell):
   `ssh -T -o BatchMode=yes -o ConnectTimeout=<connect_timeout_s> -o ServerAliveInterval=<keepalive_s> -o
   ServerAliveCountMax=<count> -o ForwardAgent=no -o ClearAllForwardings=yes -o IdentitiesOnly=yes -i $RELAY_HOME/keys/gate-host
   relay-gate@<host> <remote command>`, with the environment cut to `PATH`, `HOME`, `LANG`. `IdentitiesOnly` is new: without it
   ssh also offers the Mac's other keys, and the owner's root key could open the session as another user if the account's key
   line were missing. **ssh joins everything after the host into one string that the account's login shell parses (review F8),**
   so the remote command is built as one string with every argument passed through `shlex.quote`: `[ -r relay-gate-remote.py ]
   || exit 97; exec python3 relay-gate-remote.py gate <version> <ref> <sha> <tree id> <default branch> <limit s>`. Exit 97 means
   "program missing" (5.3.6).
2. Framed input: `bundle <bytes>\n` then the bytes of `git bundle create - <ref> refs/heads/<default branch>`; then standard input
   stays open until the end line arrives. End of file on it, a write error on the output, or `SIGHUP` on the VPS side:
   `podman rm -f` of its container, temp folder removed. **`<ref>` (revised after review F2):**
   - a lane gate: `refs/heads/<branch>`, and the program requires it at `<sha>` (exit 92 when the branch moved, as rev 2 5.3.4);
   - a watch: a pinned ref `refs/relay-gate/<sha>` made with `git update-ref` in the common git folder just before the bundle and
     deleted right after it (and any leftover `refs/relay-gate/*` deleted under the watch lock at the watch's start). The program
     requires the pinned ref at `<sha>` and makes the container's default branch at `<sha>` too, so a watch of any first-parent
     commit gates exactly that commit, however far the default branch has moved since (a queue commit 2 s later, relay land's
     own change-records commit, or a commit five landings back in bring-up step 5).
3. A detached head gates on the Mac with no line (rev 2 5.3.1).
4. The `<limit s>` argument is `QUICK_LIMIT_SECONDS` as the gated commit's lib/relay_ci.py sets it (1,800 now, 1,500 after
   speed-up-the-quick-gate lands), read as text, not imported. The program passes nothing to `bin/ci`, which applies the same
   constant inside the container. It serves the Mac's backstop (5.4) and the program's log line only.
5. In the container: `git clone -q --no-checkout`, `git checkout -q --detach <sha>`, `git branch <default> <default tip>` (the
   bundle's default branch for a lane gate, `<sha>` for a watch), `git remote remove origin`; `HEAD` and `HEAD^{tree}` must equal
   the arguments, else exit 92 before `bin/ci`.
6. **Versioning (revised after review F6, F7).** `<version>` is the sha256 of `git show <default branch>:lib/relay_gate_remote.py`
   read in the gated repository, and an install sends those same bytes, so the program on the VPS always comes from the default
   branch, whichever `bin/relay` runs the gate (the PATH one, as the cycle does, or a worktree's own, a live form: pids 62503 and
   62946 on 30 Oct). This is the image recipe's rule (5.4) applied to the program; rev 3's "the copy beside the running relay
   program" let a worktree's draft run there. A different copy on the VPS exits 93, a missing one 97 (5.3.1); on either the Mac
   installs and retries once. The install is a fixed shell line, never the old program: `umask 077; cat >
   .relay-gate-remote.tmp.$$ && mv .relay-gate-remote.tmp.$$ relay-gate-remote.py` with the bytes on standard input, so a
   broken or missing program can always be replaced and a gate still running the old file is not cut (the rename is atomic).
7. The program is standard library only, imports nothing of relay, and parses as Python 3.12
   (`ast.parse(source, feature_version=(3, 12))`). Its own failures are "could not run" (exits 90-99), never a red result.
8. **Memory (new, review F3).** After `bin/ci` returns and before the end line, the container prints `memory peak <MB>` from its
   own `/sys/fs/cgroup/memory.peak` (cgroup v2 with its own namespace; the line says `memory peak unknown` when the file is absent).
   It lands in the remote log's output, so the first watches show whether `memory_gib` 4 is enough.

### 5.4 Running on the VPS (change 3)

As rev 2 5.4 (account `relay-gate`, no sudo, not in the `docker` group, key line with `restrict`; image tag from the default
branch's three recipe files only, exit 94 and a Mac gate when the branch changes one; `podman create --network none --cpus
<cpus> --cpu-shares <cpu_shares> --memory <memory_gib>g --pids-limit 8192`, `podman cp` of the bundle, `podman start -a`; slot
lock files `~/slots/<k>.lock` with a non-blocking `flock`, a slot free only when no `relay-gate-s<k>-*` container runs; keep
`images_kept` newest tags). Changed:

- **The time limit (1.2).** The program prints `relay-gate-running <slot> <image>` the moment `podman start` begins. On the Mac:
  - before that line, the wait is bounded by `remote_wait_s` (slot) and the build bound below; past either the program gives up
    with exit 95 and the Mac runs the gate here with the "busy" or "still building" line (5.5);
  - after that line, `bin/ci`'s own limit inside the container decides: it prints its stop line and exits 124, the end line says
    124, and the remote log records the stop, which change 2 already treats as a stop, not a red (commit 4c991cfc, "F4 stops are
    not red");
  - the Mac's backstop is `<limit s>` + 120 s after the running line: if no end line by then, it ends ssh (the VPS removes the
    container) and the gate runs here with the line `gate: ai.amidman.com did not finish within <n> min of starting; this gate
    runs on this Mac`. No remote log: a hung remote run is "could not run", not a stop of the code.
- **Image builds (revised after review F5): a build lives and dies inside the gate that holds its slot.** One build lock per tag,
  taken **non-blocking**:
  - the gate that gets the lock builds in the foreground of its own run, inside its slot, bounded by `build_limit_s` for a lane
    gate and by 3,600 s (the top of `build_limit_s`'s bound; nobody waits on it) for a watch. Past the bound the program kills
    `podman build`, releases the lock and the slot, and exits 95 ("still building ... after 15 min"). So a build never runs
    without a slot, and the slot count holds;
  - a gate that finds the lock held falls back at once with the "still building" line: no idle wait, no slot held;
  - a build that never fits the lane bound does not burn every gate: the watch after each landing builds a missing tag with the
    longer bound (a recipe change lands, its watch builds the new tag before most lanes ask for it), and repeated give-ups count
    toward the stop-sending rule (5.6), which files one fix item naming `relay hosts set <host> build_limit_s <n>`.
- **Orphans, a second backstop:** with `Linger=no` the account's systemd manager stops when its last ssh session closes and takes
  any container left in its cgroup. The slot rule (a running `relay-gate-s<k>-*` keeps slot k busy) stays the first defence,
  because with two gates open the session count never reaches zero. Checked at bring-up (2.2).
- **Rootless limits:** `Delegate=pids memory cpu` is shipped (2.1), so `--cpus`, `--memory`, `--pids-limit` should work; if
  `podman info` at `relay hosts add` shows a controller missing, `add` stops and says which one: no silent run without caps.
  Rev 2's fallback (`nice -n 19` and a root drop-in shown to the owner) is dropped as not needed on the measured VPS; it comes
  back only if the check fails.

### 5.5 What counts as a result, fallback, and the lines (change 3)

As rev 2 5.5: only the end line `relay-gate-exit <n>` with podman's exit equal to `n`, followed by the program's
`relay-gate-result <n>`, makes a result; ssh's own exit is never the gate's exit. Every other ending raises `RemoteUnavailable`
with one line, and change 2's code adds "; this gate runs on this Mac". Lines:

| case | line | counts toward stop-sending (5.6) |
|---|---|---|
| start | `gate: on ai.amidman.com (slot 1 of 2, image relay-gate:3fa2c19e0b1d, 6.7 MB sent)` | |
| cannot connect | `gate: ai.amidman.com cannot be reached (ssh: connection timed out after 3 s); this gate runs on this Mac` | no (costs 3 s) |
| busy | `gate: ai.amidman.com was busy for 15 min (2 gates running); this gate runs on this Mac` | no (load, not a fault) |
| still building | `gate: ai.amidman.com was still building image relay-gate:3fa2c19e0b1d after 15 min; this gate runs on this Mac` (or `... is building image ... now` when the lock was held) | yes when this gate's own build gave up; no when the lock was held |
| program missing, then install failed | `gate: ai.amidman.com could not install its gate program (<the error line>); this gate runs on this Mac` | yes |
| could not run | `gate: ai.amidman.com could not run the gate (podman exited 125: <its last error line>); this gate runs on this Mac` | yes |
| killed (137, new) | `gate: ai.amidman.com could not run the gate (the container was killed, exit 137, memory peak <MB> of <memory_gib> GiB); this gate runs on this Mac` | yes |
| connection lost | `gate: the connection to ai.amidman.com was lost after 6.9 min; this gate runs on this Mac` | yes |
| backstop | `gate: ai.amidman.com did not finish within 32 min of starting; this gate runs on this Mac` | yes |
| stopped sending (new, change 4) | `gate: ai.amidman.com could not run the last 3 gates (<newest line>; fix item <slug>); gates stay on this Mac until a Linux watch there finishes; this gate runs on this Mac` | |
| no Linux result yet (new, change 4) | `gate: ai.amidman.com has not yet gated the default branch (run relay gate --watch-default); this gate runs on this Mac` | |
| no record | nothing: a gate without a record runs on the Mac as today | |

### 5.6 The Linux watch of the default branch (change 4)

As rev 2 5.6, with the parts change 3 now provides:
- `relay gate --watch-default [-C <repo>] [<sha>]` gates a commit of the default branch's first-parent line (default: the commit
  `relay land` just landed) through the same `run` (5.3) with a pinned ref (5.3.2), and writes
  `<git common dir>/relay-land/linux/<sha>.remote.gate.log`, never committed. The default branch's Linux state is the file of the
  newest commit on the first-parent line that has one, found by walking git, not by file time, so a file written later for an
  older commit (5.9 step 5) never stands for the head; nothing else is stored (principle 3).
- `relay land` starts it detached after a landing (lib/relay_land.py:312, the `if result.outcome == LANDED` block, after the done
  event and the lock) and returns at once; one watch at a time by a lock in the same folder; the running one gates once more if
  the default branch moved by non-inert files while it ran. Load: at most 1.59 extra VPS gates an hour (2.1). **The watch's
  modules are imported inside that block, never at the top of relay_land.py (revised after review F9):** plugins/front/lib and
  plugins/relay/lib hold links to lib/relay_land.py, not copies, and the merge hook loads it from its plugin folder, which has
  no relay_gate_ssh.py or relay_hosts.py (the same rule as the imports at lib/relay_land.py:274-276).
- `Remote.default_red` is read from the newest watch file: a sentence `since <sha8> (step <name>; fix item <slug>)` when it is red,
  "" otherwise; `holds_fix` is true when the branch holds that fix item (lib/relay_queue.py, the items a branch holds). No watch
  file at all on the first-parent line: no `Remote`, the "no Linux result yet" line (decision 6).
- **Red, stop and could-not-run (revised after review F11).** A watch is red when its end line says `0 < n < 127` and `n != 124`,
  the same rule `finished_red` applies (lib/relay_gate_logs.py:153). 124 is a stop of the code at its limit: file written, no
  item, `default_red` "". A watch that ends without an end line writes no file and appends a could-not-run event (below).
- Red: one fix item through relay's queue writer (`relay_queue.add`, lib/relay_queue.py:1114; landed at once as queue items are),
  `kind` fix, `failing_kind` "run" (a recorded red run), `time` 30 min (a guess; the fixer re-estimates), `found_in` "the Linux
  gate of the default branch", the failing lines and the log path as the failing case, pass case "the Linux watch of the head that
  lands the fix is green". While it is open a later red watch adds nothing.
- **Stop-sending rule (new, review F3).** Every remote attempt, lane or watch, appends one dated event to
  `<git common dir>/relay-land/linux/host-events.jsonl` (`{"at": "<UTC>", "host": ..., "outcome": "result" | "could-not-run" |
  "unreachable" | "busy", "line": "<the gate: line>"}`), written only by lib/relay_gate_ssh.py, schema-checked on read (principle
  4). Events, not a counter: the state is computed when read (principle 3). When the newest `stop_after` events of a host that
  count (5.5's last column: `result` and `could-not-run`) are all could-not-run, the builder returns the "stopped sending" reason
  instead of a `Remote`, and the event that trips it files one fix item (`failing_kind` "run", time 30 min, the 3 lines as the
  failing case, pass case "the next watch on the host reaches an end line"); while it is open no new item. The watch keeps
  running after each landing regardless: it is the probe, and its first result clears the rule. With `watch_default` off the line
  says to run `relay gate --watch-default` by hand. Why events and not the Mac logs' first lines (the review's hint): those lines
  sit in logs committed on many branches across worktrees; one file in the common git folder is read with one open. The file
  gets one line per remote attempt (about 80 a day at today's 78 gates); reads use its last 200 lines, the writer keeps 1,000.
- `watch_default` off in the record stops it (F1's failing case comes back; the record's line in `relay hosts status` says so; the
  paid run then keeps its clean-image step, decision 1).
- The Linux comparison the owner asked for on 10:53Z reads, per change, its newest remote log and its Mac landing log. Different
  heads (the landing gate runs after the default branch is taken), so a disagreement is a lead, not a proof; the watch of the
  landed head is the same-commit pair. Built by the comparison item, not here.

### 5.7 Settings (change 3; `stop_after` change 4)

`$RELAY_HOME/gate-hosts.json`, one record per host, schema-checked on every read, written only by `lib/relay_hosts.py`
(`relay hosts add/set/remove`). No record: no remote gate. Bounds and outcomes as rev 2 5.7 (`slots` 2, 1-3; `cpus` 4, 2-8;
`memory_gib` 4, 2-12; `cpu_shares` 256, 2-1024; `connect_timeout_s` 3, 1-15; `keepalive_s` 10 × 3, 5-20 × 2-6; `remote_wait_s`
900, 0-3,600; `images_kept` 3, 1-10; `watch_default` on), plus:

| setting | default | bound | at the bound |
|---|---|---|---|
| `build_limit_s` (new) | 900 | 300-3,600 | a lane gate's own image build; at 300 a cold build (311 s on this Mac, 27 Oct; the VPS not measured) gives up in every lane and the watch (bound 3,600) builds the tag after the next landing; at 3,600 a hung lane build holds a slot an hour before that gate falls back |
| `stop_after` (new) | 3 | 1-10 | at 1, one could-not-run (say a podman hiccup) sends every lane to the Mac until the next landing's watch finishes, about 38 min at 1.59 landings an hour; at 10, a host that is broken for good costs 10 remote attempts (each up to its wait and run, then a full Mac gate) before it stops |
| backstop margin (not a setting) | `<limit s>` + 120 s | fixed | the margin covers the container's clone and checkout of a 6.7 MB bundle (about 2 s measured as `git clone` here) and `bin/ci`'s own stop |

`relay hosts set` refuses a value outside its bound and names the bound. `relay hosts status` prints one line per host: the
settings, the newest watch (`default branch: last gated on ai.amidman.com at <sha12>, 3 landings ago, green`, or `stopped at its
limit`), whether the stop-sending rule holds and since which event, and the counts of remote and fallback gates of the last day
read from the event file.

### 5.8 Each "never" and "only", with its test

Rev 2 5.8's list, minus the five tests change 2 already landed (the merge hook never accepts a remote log; landing never reuses
one; the remote log decides over the stretch; no fallback over a red remote log; after a red Mac log the branch gates on the
Mac). Change 3 owns: the container runs the gated commit (both default-branch names); only an end line makes a result (podman
125, a traceback, a forged end line followed by podman exit 1); nothing of `$RELAY_HOME` or secrets goes along (environment,
`ForwardAgent=no`, `IdentitiesOnly=yes`, bundle refs); no orphan keeps a slot (stdin closed, SIGTERM); slots hold under a race;
no branch recipe is built; the program parses as 3.12 and imports only the standard library; unreachable VPS gives one line;
only relay goes remote. Restated or new with this revision:
- **Only quick gates go remote, and the cycle's form is quick (restated after F1):** with a record present and a branch eligible,
  `relay gate -C <wt>` and `relay gate -C <wt> -- --quick` both make one ssh call; `--paid` and `-- some-other-arg` make none.
- **The slot wait and the build never count against the gate's limit:** fake podman takes 20 min to build (watch bound), the
  limit is 25 min, the run after it takes 6 min: the remote log ends `exit 0`, no stop line.
- **A build never runs without a slot (F5):** a fake build longer than `build_limit_s`: the gate exits 95 and falls back, the
  fake `podman build` was killed, slot and lock are free; a second gate arriving while a build holds the lock falls back at once
  with no ssh wait beyond the lock check; two gates needing one missing tag start one build.
- **A hung remote run is not a stop of the code:** fake run prints `relay-gate-running` and then nothing: at limit + 120 s ssh is
  ended, no remote log is written, one backstop line, a Mac log.
- **The program on the VPS always comes from the default branch (F6):** a worktree whose `lib/relay_gate_remote.py` differs from
  the default branch's, gated through its own `bin/relay` and through `relay` on PATH: the `<version>` sent is the default
  branch's blob's sha256 both times, and an install sends those bytes.
- **A missing program is installed (F7):** fake host with no program file: exit 97, install through the fixed shell line, one
  retry, the gate runs remote; with a different version: 93, the same.
- **The VPS receives exactly the arguments the Mac built (F8):** a fake ssh that runs the received string through `sh -c` and
  prints its argv; a branch named `wt/a$(id);x'y` round-trips unchanged.
- **A watch gates exactly the commit it names (F2):** `relay gate --watch-default <master~5>` against fakes: the container's HEAD
  is that sha, the file `<sha>.remote.gate.log` is written, no exit 92, no `refs/relay-gate/*` left after; a commit added to the
  default branch between choosing the sha and the bundle changes nothing; a lane gate whose branch moved still exits 92.
- **relay's code never runs root:** no code path of `relay hosts` passes `root@` to ssh; `add` against a host whose key login is
  refused prints the 3 root commands and writes no record.
- **`add` builds and gates nothing (F10):** `relay hosts add` against fakes: login, install, `podman info`, record written; no
  `podman build`, no gate call.
- **The record has one writer:** a test greps lib/ and bin/ for `gate-hosts.json`: only lib/relay_hosts.py names it.

Change 4 owns:
- the watch files one item; a lane gates on the Mac while the watch is red, the fix's lane does not;
- **red is defined (F11):** a watch file ending `exit 124`: `default_red` "", no item; ending `exit 1`: one fix item with
  `failing_kind` "run", time set, the failing lines and the log path; a second red while it is open: no new item;
- **no Linux result, no lane on the VPS (F10):** a record and no watch file: the "not yet gated" line, no ssh call;
- **the stop-sending rule (F3):** fake host ending 137 on 3 gates in a row: the 4th gate makes no ssh call, prints the "stopped
  sending" line, and one fix item exists; with one result between the failures nothing stops; a watch ending 137 counts; a watch
  that reaches an end line clears it; `unreachable` and `busy` events never count;
- **the merge hook still loads (F9):** importing relay_land with only plugins/relay/lib (and, separately, only plugins/front/lib)
  on `sys.path` succeeds.

Change 5 owns:
- **Linux is never silently ungated (F4):** paid run on a head whose inert stretch holds a green watch file: the clean-image step
  is skipped with a line naming the file; no watch file in the stretch (VPS down, watch off) or a red one: the step runs as today.

### 5.9 Bring-up (change 5)

Prerequisites: changes 3 and 4 landed; the clean-Linux fix closed (done, 30 Oct 05:37Z); the owner sees the 3 root commands
before they run (owner's "a", 02:26Z: "each command shown before it runs").

| step | who, where | command | undo |
|---|---|---|---|
| 1. key | relay on this Mac | `relay hosts add ai.amidman.com --user relay-gate` creates `$RELAY_HOME/keys/gate-host` (ed25519, no passphrase) when missing, tries the login, is refused, and prints steps 2-3 with the public key filled in | `relay hosts remove` deletes it |
| 2. account | root on the VPS, run by the front after the owner sees it | `useradd --create-home --shell /bin/bash relay-gate` | `userdel -r relay-gate` (home, images, key line) |
| 3. key line | the same | `install -d -m 700 -o relay-gate -g relay-gate ~relay-gate/.ssh && printf 'restrict %s\n' '<public key>' > ~relay-gate/.ssh/authorized_keys && chown relay-gate: ~relay-gate/.ssh/authorized_keys && chmod 600 ~relay-gate/.ssh/authorized_keys` | removed with step 2 |
| 4a. check and record | relay on this Mac, as relay-gate | `relay hosts add ai.amidman.com --user relay-gate` again: login with `IdentitiesOnly`, program installed, `podman info` (rootless, cgroup v2, cpu, memory, pids), subuid range present; the record is written (seconds) | `relay hosts remove ai.amidman.com` |
| 4b. first watch | the bring-up agent, **detached with a log**, waited on by its pid in calls of at most 240 s | `relay gate --watch-default` of the default branch's head: the image build (311 s cold on this Mac; VPS not measured) and the first gate, with `RELAY_GATE` set as every remote gate (the inert probe included); its time and `memory peak` line go into the item as fact notes. A 137 or a peak within 10% of `memory_gib`: raise it with `relay hosts set` (bound 12) and run again | nothing |
| 5. measure | the bring-up agent | 3 remote gates of commits the Mac also gated (the head from 4b, and two recent landed heads by `relay gate --watch-default <sha>`, not committed, each detached with a log), compared exit by exit and step by step with the Mac logs; the time and memory peak of each; whether a killed `relay gate` leaves a container after the session closes (2.2) | nothing |
| 6. Linux once, not twice | the bring-up agent, a code change | after 3 green watches: the paid run skips the clean-image step when a green watch file covers its head's inert stretch, and runs it otherwise (decision 1; lib/relay_ci.py:544-546, lib/relay_ci_image.py, their tests) | revert the commit |

The 3 root commands are steps 2 and 3 (`useradd`, `install -d`, the key file with its owner and mode). Nothing is installed on
the VPS, no service or setting changes. Times and results go into the queue item as fact notes the same turn they are read.

If the first watch (4b) is red, the record stays: the fix item lands, lanes keep gating on the Mac by 5.2's "default branch red"
row, and step 6 waits until 3 watches are green. Until 4b has a result, lanes gate on the Mac (decision 6).

## 6. Critique

**Of the owner's picks, once.** I looked again with today's numbers. "a" (the VPS decides build-time gates) still rests on the
same arithmetic: landings 1.59 an hour (was 1.5), the VPS idle (load 0.01), nothing to install. Its four costs from rev 2
section 6 stand: Linux-only failures (now a fix item via the watch, not a red in every lane), a Mac-only break caught only at
landing, 23% of code landings losing their gate reuse (+0.23 Mac gates per landing, about 13 min each), and toolchain changes
gating on the Mac. A fifth, from the review: a VPS that fails in a way relay does not foresee costs every lane its remote time and
then a full Mac gate, `stop_after` times, before the rule stops it (5.6). The second "a" (relay creates the account itself) costs
nothing new in exposure, and here is why it is worth saying: **root ssh to ai.amidman.com already works from this Mac with no
prompt** (this revision's read-only probe logged in as root with `BatchMode=yes`). So any agent on this Mac can already run root
commands on the server that holds mail, forgejo and woodpecker; the gate account narrows what gates can do, but not what agents
can do. That is outside this item; it is the one question below.

**Of the brief's and the earlier revisions' own picks.**
- Rev 2 5.4 "the quick gate's limit applied to the whole remote run" breaks with the 25-min limit (1.2); fixed here.
- Rev 2 5.7 "gate-hosts.toml" needs a TOML writer relay does not have; JSON instead (1.4).
- Rev 2 5.9 "relay hosts remove runs every undo" put a root command in code; removed (1.5).
- Rev 3's own fix of rev 2 5.3.7 (send "the copy beside the running bin/relay") was wrong: a worktree's `bin/relay` is a live
  form, so the draft would run on the VPS. The default branch's blob is sent now (5.3.6, F6).
- Rev 3 treated "quick" as cmd_gate's notion and so missed that the cycle never asks for it (F1). The section 4 saving (74 → 15-17
  Mac gate minutes per change) rested on gates that, as written, would never have gone remote.
- Rev 3 retired the clean-image step outright (F4): one day of VPS outage would have meant about 38 landings with no Linux check
  and green paid runs.
- The brief's "3 gates on commits the Mac also gated" needs a remote gate of a chosen commit without committing a log;
  `relay gate --watch-default <sha>` gives it, and with the pinned ref it can actually gate an older commit (F2). Its test: a
  watch file of an older commit written after the head's does not change the state `relay hosts status` prints.
- The brief's "4h" for changes 3-5: the honest figure is about 6 h. The growth is the review's fixes, each small (section 9);
  nothing in it is optional for correctness, so no scope cut is offered.

## 7. Order of work and what each change needs first

| order | change | needs first | touches | agent minutes |
|---|---|---|---|---|
| 3 | hosts record and command (`add` checks and records only), ssh transport with quoted remote command and pinned-ref support, remote program (install line, exit 97, memory line, build bound), fallback lines, `cmd_gate`'s quick rule, the change-3 tests of 5.8 with fake ssh and podman | change 2 (landed); nothing from the owner; no VPS access (fakes only) | new lib/relay_hosts.py, lib/relay_gate_ssh.py, lib/relay_gate_remote.py, tests; bin/relay `cmd_gate` (the quick rule, build the `Remote` or print the reason) and a thin `cmd_hosts`; reads `QUICK_LIMIT_SECONDS` | 200 (rev 3: 165; +10 quick rule F1, +5 pinned-ref support F2, +10 build bound F5, +5 default-branch version F6, +10 install line and exit 97 F7, +5 quoting F8, +5 memory line F3, −15 `add` no longer builds or gates F10) |
| 4 | the Linux watch: `relay gate --watch-default [<sha>]` with the pinned ref, its start from `relay land` (imports inside the block), `default_red`/`holds_fix`, the "no Linux result" reason, the red and stop rule and the fix item's fields, the event file and the stop-sending rule with its item and `stop_after` | change 3 | lib/relay_land.py (one file; the plugin entries are links), lib/relay_gate_ssh.py, lib/relay_hosts.py (`stop_after`), bin/relay | 95 (rev 3: 45; +10 pinned ref F2, +5 import test F9, +5 red rule and fields F11, +5 no-result reason F10, +25 stop-sending rule F3) |
| 5 | bring-up (5.9), then the paid clean-image step made conditional | changes 3 and 4 landed; **the owner present to see 3 root commands** | the VPS (3 root commands, then the account only); lib/relay_ci.py, lib/relay_ci_image.py and their tests | 65 (rev 3: 50; +15 conditional skip F4), plus gate wall time (one image build, about 4 gates) |

Lanes beside it: `speed-up-the-quick-gate` (in build; bin/ci, lib/relay_ci.py, tests/parallel_unittest.py) shares no file with
changes 3-4; it changes the limit constant change 3 reads, so whichever lands second runs against the other's value with no edit.
Change 5's step 6 touches lib/relay_ci.py, which that lane also changes: it is built after that lane lands. 
`tests-build-a-new-git-repo-for-every-case` (in build) shares none.

## 8. Recommendation

Build changes 3, 4, 5 in that order with the seven decisions of section 1 (owner can reverse each). Rests on: the landed interface
read from the code (lib/relay_gate_logs.py:15-37 and 186-200, lib/relay_gate.py:389-450, bin/relay:633-661); the cycle's gate
form and the 400 identical `cmd bin/ci --quick` lines (decision 7); git's refusal to bundle a bare commit (5.3.2); the VPS re-read
today (2.1: idle, no account yet, cgroup limits delegated, nothing to install); the limit constant (1,800 s, lib/relay_ci.py:53)
and the owner's 25 min; a cold image build of 311 s measured on this Mac. Not measured, a guess: the VPS gate's time (about 5
min) and its memory with the inert probe; change 5 measures both.

## Open for the owner

**Should agents on this Mac keep root access to ai.amidman.com?**

Found while measuring for this work, outside its scope. Your server ai.amidman.com runs mail, forgejo, woodpecker and a site. Today
any program on this Mac can log in to it as root with no prompt: this plan's own read-only check did (`ssh root@ai.amidman.com`
with no password, no question). The VPS gate design gives gates an account with no admin rights, but every agent session here
still has a root key a mistyped or confused command could use. relay's guard (the check that already refuses some commands to
agents) could refuse `ssh root@…` to agents, with a one-time allowance the front asks you for at bring-up (steps 2-3 of 5.9).

| | what agents can do on your server | your work | cost |
|---|---|---|---|
| a. guard refuses root ssh to agents | only what the `relay-gate` account can (no admin, no docker) | say yes at bring-up for the 3 commands | one fix item, about 30 agent minutes (not measured); your own terminal is unaffected |
| b. leave as it is | anything root can | none | none now; one wrong command can touch mail or forgejo |

- a. The guard refuses it (recommended). Rests on: the root login measured working from this Mac today; the server's role (8
  live services).
- b. Leave it.

Not asked, decided inside the principles (owner can reverse): the limit counts from the run's start, not the queue (1.2); JSON
record (1.4); no root in relay's code (1.5); `add` checks and records, the first watch builds and gates (1.6); the paid
clean-image step is skipped only when a green watch covers the head (1.1); `-- --quick` is the quick gate (1.7); `stop_after` 3
and the fix items' 30 min (5.6, 5.7).

## What the brief could not answer

- The VPS gate's time, memory and whether it is green there; whether the first image build on the VPS fits the watch's 3,600 s
  and a lane's 900 s. Change 5 measures them.
- Whether a container survives its account's last session under `Linger=no`; checked at bring-up.
- Whether the paid run's clean-image step has run green on master since the fix closed (no paid run found in master's log since
  05:37Z); the first watch gives the same answer on the VPS, and the step keeps running until watches cover the heads.

## 9. What changed after the review

The design review of revision 3 (30 Oct ~12:20Z) raised 11 findings. Each was checked against the code before the fix; all held.

| finding | held? | fix (where) |
|---|---|---|
| F1 HIGH: the cycle runs `relay gate -C <wt> -- --quick`, which `cmd_gate` counts as not quick, so no lane gate would reach the VPS | held: cycle.js:27/:176, bin/relay:644, test_cycle_workflow.py:607 read; the delegate skill teaches the same form; all 400 newest logs say `cmd bin/ci --quick` | `cmd_gate` counts a gate as quick when its command equals the quick binding's (decision 7; 5.8 first new row). Chosen over changing cycle.js's default because the skill and docs also use `-- --quick`, and the same command is the same gate (principle 5) |
| F2 MEDIUM: the watch bundles `refs/heads/<default>` and requires it at `<sha>`, so a watch of an older commit always exits 92 and the head watch races later commits | held: git refuses to bundle a bare commit (checked); relay land commits change records after each landing; queue commits 2 s apart | a watch bundles a pinned ref `refs/relay-gate/<sha>`, deleted after; the container's default branch is made at `<sha>`; lane gates keep exit 92 when their branch moved (5.3.2, 5.3.5, 5.6; 5.8 row) |
| F3 MEDIUM: a repeated "could not run" (137, podman 125) files nothing and stops nothing; the inert probe under `RELAY_GATE` was never run in a container and its memory is unknown | held: lib/relay_ci.py:519-524 and lib/relay_ci_image.py:25 read; memory not measured | the stop-sending rule over a dated event file, one fix item, the watch as the probe that clears it (5.6, `stop_after` in 5.7); the program prints the container's memory peak (5.3.8); bring-up 4b records it and raises `memory_gib` if needed (2.2, 5.9) |
| F4 MEDIUM: retiring the paid clean-image step leaves Linux ungated whenever the watch is off or the VPS down | held | the step is skipped only when a green watch covers the head's inert stretch, else runs as today (decision 1; 5.9 step 6; 5.8 change-5 row) |
| F5 MEDIUM: at `build_limit_s` the build's fate was undefined: left running it holds no slot, killed it never finishes | held | a build runs inside its gate's slot and is killed at the bound; a held build lock means fall back at once; the watch builds with a 3,600 s bound so a long build still finishes; repeated give-ups trip the stop-sending rule (5.4, 5.7, 5.8 row) |
| F6 LOW: the program version came from the copy beside the running `bin/relay`, a branch draft when a worktree's `bin/relay` runs | held: a worktree's `bin/relay gate` is a live form | version and install bytes from `git show <default branch>:lib/relay_gate_remote.py` (5.3.6; 5.8 row) |
| F7 LOW: the program installed itself only on exit 93; a missing program never installs, a broken one can never be replaced | held | the remote command checks the file first (exit 97); install is a fixed shell line `cat > tmp && mv`, on 93 and 97, one retry (5.3.1, 5.3.6; 5.8 row) |
| F8 LOW: ssh joins the remote arguments into one string for the login shell | held | every remote argument through `shlex.quote`; a test with a fake ssh that runs `sh -c` (5.3.1; 5.8 row) |
| F9 LOW: the plugin "copies" of relay_land.py are links; the real rule is to import the watch's modules inside the LANDED block | held: both are symlinks to ../../../lib/relay_land.py | the sentence replaced; an import test per plugin folder (5.6; 5.8 change-4 row) |
| F10 LOW: `relay hosts add` (change 3) ran the first watch, which change 4 builds, and its build plus gate outlasts the 4-minute command bound | held | `add` checks and records only; the first watch is bring-up step 4b, detached with a log; lanes stay on the Mac until a watch result exists (decision 6; 5.2, 5.6, 5.9) |
| F11 LOW: the watch's red was undefined for 124, and its fix item lacked `failing_kind` and time, which `relay_queue.add` refuses | held: lib/relay_queue.py:1132-1137 read | red is `0 < n < 127`, `n != 124`; 124 is a stop with no item; the item carries `failing_kind` "run" and 30 min (5.6; 5.8 change-4 row) |

Rev 2's ten findings stay where rev 3 put them:

| finding (rev 2 review) | where it is now |
|---|---|
| F1 nothing gates the default branch on Linux | change 4 (5.6); the first watch is bring-up 4b, and lanes wait for it (decision 6) |
| F2 the container checked out /src's HEAD | change 3, 5.3.5 and its test |
| F3 ssh's exit taken as the gate's | change 3, 5.5 (end line only); the backstop row writes no log |
| F4 standard input both carries and signals | change 3, 5.3.2 |
| F5 slot count, start race, builds without a slot | change 3, 5.4 (builds now bounded inside their slot) |
| F6 `relay verdict` refused a remote log | landed (change 2) |
| F7 the fix round after a red Mac landing gate | landed (change 2, `_last_mac_red`) |
| F8 image builds run branch code with network | change 3, 5.4 recipe rule; extended to the program itself, from the default branch (5.3.6) |
| F9 "never laundered" only for the same sha | landed (change 2, stretch rule) |
| F10 the cycle's recovery did not know the remote subject | landed (cycle.js:192 names both subjects) |
