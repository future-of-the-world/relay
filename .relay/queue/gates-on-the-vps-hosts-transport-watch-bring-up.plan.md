# Plan: Gates on the VPS ai.amidman.com, changes 3-5 (hosts, transport, watch, bring-up)

Revision 3, 30 Oct 2026 ~12:10Z, thinker. Brings the reviewed design rev 2 (`design-vps-build-gates.md`, same scratchpad; it was
also this item's plan file) up to date with master 93016864 for its changes 3-5. Not a redesign: the approach (A), the rules and the
section numbers 5.1-5.9 stay, because landed code cites them (lib/relay_gate_logs.py:44 "plan.md 5.1", :45 and :178 "design 5.4",
:98 and :188 "design 5.2"). Read-only: no code changed; on the VPS only read-only commands ran as root (2.1).

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
machine whose result a gate request takes); **bundle** (`git bundle`, a packed set of commits `git clone` reads like a repository);
**slot** (a permit to run one gate at a time on a machine); **Linux watch** (one VPS gate of the default branch's head after each
landing; its result kept in the git folder, never committed); **end line** (`relay-gate-exit <n>`, printed by the container after
`bin/ci` returned; only it makes a result).

## 1. Short answer: what is already built, what is left, what changed

**Built and landed (change 2, master ea468ce7, 30 Oct 08:05Z):** the remote log name and every reader (5.1); the deciding-host
table and reuse over the stretch (5.2) in lib/relay_gate_logs.py `deciding_host`, `reusable`, `finished_red`; the remote branch
of `relay_gate.run` (`_remote_gate`, lib/relay_gate.py:389) that commits `relay: remote gate of <sha>`, keeps a red remote result
when the host cannot be reached, and falls back with a line otherwise. The transport is an interface a test fills:

| type (lib/relay_gate_logs.py) | what change 3 must supply |
|---|---|
| `Remote(host, run, default_red="", holds_fix=False)` | built in `cmd_gate` (bin/relay:633) from the hosts record, only for a plain (quick) gate; today `cmd_gate` passes no `remote`, so every gate runs on the Mac |
| `run(worktree, head, command) -> RemoteResult(code, output, host_line, wait)` | the ssh transport of 5.3-5.5 |
| `RemoteUnavailable(text)` | raised for every "could not run" case of 5.5; the text is the line after `gate: ` |
| `default_red`, `holds_fix` | change 4 fills them from the Linux watch (5.6); until then "" and False |

**Left, in order:** change 3 (hosts record, ssh transport, remote program, fallback; about 165 agent minutes), change 4 (the Linux
watch; about 45), change 5 (bring-up on the VPS, 3 root commands shown to the owner first, then the clean-image paid step
retired; about 50 plus gate time). Total about 4 h 20 min of agent time (the item says 4 h).

**What changed since rev 2, and what this revision decides about it (each: owner can reverse):**
1. **The prerequisite is met:** the clean-Linux fix (`the-quick-gate-is-red-again-in-a-clean-linux-ima`) closed 30 Oct 05:37Z;
   its "keep it green" is a paid-run step running the clean image on this Mac (lib/relay_ci_image.py), which the front noted "the
   VPS Linux watch replaces later". **Decided:** change 5 retires that step once 3 watches are green (5.9, 7), so Linux is
   gated once, not twice (principle 2; the step took about 21 min of this Mac at load 30-43, 30 Oct).
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
6. **`relay hosts add` proves the host before it records it** (5.9): it logs in as `relay-gate`, copies the program, reads
   `podman info`, builds the image and runs the first Linux watch of the default branch's head in the foreground. The record is
   written whatever that gate says; a red first watch files the fix item and keeps lanes on the Mac (5.6), so no lane goes red
   for code it did not touch (rev 2's F1 case: 12 failing batches on a commit the Mac passed, 30 Oct).

## 2. Measurements

### 2.1 Re-read now (30 Oct ~12:06Z, master 93016864)

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

Three facts change the plan: the cgroup limits are delegated (rev 2 had them "not measured"; 5.4's caps can stay, still to be
seen working at bring-up); `Linger=no` gives a second orphan backstop (5.4); and the bundle grows about 1.45 KB a commit (507 KB over
350 commits since rev 2), about 1.1 MB a day at the last day's 732 commits (613 of them queue, check or handover records), so it
reaches the bound of 2.3 in about 6 weeks.

### 2.2 Still not measured

- A full quick gate on the VPS: time and result. Change 5 measures it. The about-5-min figure stays a guess (4.6-5.6x from three
  git-heavy test files, 30 Oct).
- Whether a container left by a killed program is stopped when the account's last ssh session ends (`Linger=no`): expected from
  systemd's behaviour, checked at bring-up (5.9 step 5).
- Whether the zabbix monitor alerts on gate CPU. A gate runs at `cpu_shares` 256, below the services.
- How often the default branch goes Linux-red after a landing: the watch's fix items will count it.

### 2.3 Bundle growth, the bound that would change the transport

At 1.75 s per 6.2 MB (measured 30 Oct), a full-history bundle costs about 0.3 s a MB to send. It reaches 50 MB (about 14 s to
send, plus about 4 s to make) after about 43 MB / 1.45 KB ≈ 30,000 more commits: about 6 weeks at the last day's 732 commits, 9
weeks at the last week's 500 a day. Against a gate guessed at 5 min that is about 6%, so it does not change the design now. Not a
setting: when a gate's start line (5.5 prints the bytes) shows over 50 MB, that is a fix item. The two ways out, both for then:
a bundle that leaves out `.relay/` history the tests do not read (most of the growth: 613 of 732 commits of the last day touch
only queue, check or handover records), or an incremental bundle, which needs a copy kept on the VPS (owner, 28 Oct: no remote).

## 3. How leading tools solve it

Unchanged from rev 2 section 3 (Buildkite and GitLab runner tags, Bazel remote execution with local fallback, distcc host slots
over ssh, the "main is red" pipeline after each merge, woodpecker's fresh container per step). One addition for the new limit
decision (1.2): GitLab and Buildkite count a job's timeout from when a runner picks the job up, not from when it was queued;
Bazel's `--remote_timeout` covers one execution, not the wait for a worker. 5.4 follows them.

## 4. Approaches

The choice between A (separate log file, bundle, rootless podman), B (host line in the same file, a bare repository, plain
processes) and doing nothing was made in rev 2 section 4 and built in change 2 (A). What is left to choose is narrower:

| for changes 3-5 | A3. Build changes 3-5 as planned (recommended) | B3. Stop after change 2: VPS used only by hand | 0. Do nothing more |
|---|---|---|---|
| Mac gate minutes per change | about 74 → about 15-17 (rev 2 2.3) | about 74 | about 74 |
| what change 2's code does | runs | stays dead code (no caller passes `remote`) | stays dead code |
| Linux checking of the default branch | the watch after each landing (1.59 an hour) | the paid run's clean-image step on this Mac, about 21 min per paid run | the same |
| owner's work | see 3 root commands once | none | none |
| agent time | about 4 h 20 min | 0 | 0 |

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
exists; change 4 sets `default_red` and `holds_fix`.

### 5.3 Transport (change 3)

As rev 2 5.3, with these settled details:
1. `lib/relay_gate_ssh.py` builds the `Remote` and its `run`. It runs ssh with a list of arguments (no shell): `ssh -T -o
   BatchMode=yes -o ConnectTimeout=<connect_timeout_s> -o ServerAliveInterval=<keepalive_s> -o ServerAliveCountMax=<count> -o
   ForwardAgent=no -o ClearAllForwardings=yes -o IdentitiesOnly=yes -i $RELAY_HOME/keys/gate-host relay-gate@<host> python3
   relay-gate-remote.py gate <version> <branch> <sha> <tree id> <default branch> <limit s>`, with the environment cut to `PATH`,
   `HOME`, `LANG`. `IdentitiesOnly` is new: without it ssh also offers the Mac's other keys, and the owner's root key could open
   the session as another user if the account's key line were missing.
2. Framed input: `bundle <bytes>\n` then the bytes of `git bundle create - refs/heads/<branch> refs/heads/<default branch>`; then
   standard input stays open until the end line arrives. End of file on it, a write error on the output, or `SIGHUP` on the VPS
   side: `podman rm -f` of its container, temp folder removed.
3. A detached head gates on the Mac with no line (rev 2 5.3.1).
4. The `<limit s>` argument is `QUICK_LIMIT_SECONDS` as the gated commit's lib/relay_ci.py sets it (1,800 now, 1,500 after
   speed-up-the-quick-gate lands), read as text, not imported. The program passes nothing to `bin/ci`, which applies the same
   constant inside the container. It serves the Mac's backstop (5.4) and the program's log line only.
5. In the container: `git clone -q --no-checkout`, `git checkout -q --detach <sha>`, `git branch <default> origin/<default>`,
   `git remote remove origin`; `HEAD` and `HEAD^{tree}` must equal the arguments, else exit 92 before `bin/ci`.
6. Versioning: `<version>` is the sha256 of the `lib/relay_gate_remote.py` that the running `relay` program sits beside (the
   relay checkout `bin/relay` is run from, not the gated worktree's copy), so a branch that edits the program cannot run its
   draft on the VPS (the same rule as the image recipe, 5.4). A different copy on the VPS exits 93; the Mac sends its file over the same key
   (`relay-gate-remote.py install <bytes>` with the file framed on standard input) and retries once.
7. The program is standard library only, imports nothing of relay, and parses as Python 3.12
   (`ast.parse(source, feature_version=(3, 12))`). Its own failures are "could not run" (exits 90-99), never a red result.

### 5.4 Running on the VPS (change 3)

As rev 2 5.4 (account `relay-gate`, no sudo, not in the `docker` group, key line with `restrict`; image tag from the default
branch's three recipe files only, exit 94 and a Mac gate when the branch changes one; `podman create --network none --cpus
<cpus> --cpu-shares <cpu_shares> --memory <memory_gib>g --pids-limit 8192`, `podman cp` of the bundle, `podman start -a`; slot
lock files `~/slots/<k>.lock` with a non-blocking `flock`, a slot free only when no `relay-gate-s<k>-*` container runs; one
blocking build lock per tag; a build holds its slot; keep `images_kept` newest tags). Changed:

- **The time limit (1.2).** The program prints `relay-gate-running <slot> <image>` the moment `podman start` begins. On the Mac:
  - before that line, the wait is bounded by `remote_wait_s` (slot) and `build_limit_s` (image build); past either bound the
    program gives up with exit 95 and the Mac runs the gate here with the "busy" line (5.5);
  - after that line, `bin/ci`'s own limit inside the container decides: it prints its stop line and exits 124, the end line says
    124, and the remote log records the stop, which change 2 already treats as a stop, not a red (commit 4c991cfc, "F4 stops are
    not red");
  - the Mac's backstop is `<limit s>` + 120 s after the running line: if no end line by then, it ends ssh (the VPS removes the
    container) and the gate runs here with the line `gate: ai.amidman.com did not finish within <n> min of starting; this gate
    runs on this Mac`. No remote log: a hung remote run is "could not run", not a stop of the code.
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
with one line, and change 2's code adds "; this gate runs on this Mac". Lines, unchanged except the two new rows:

| case | line |
|---|---|
| start | `gate: on ai.amidman.com (slot 1 of 2, image relay-gate:3fa2c19e0b1d, 6.7 MB sent)` |
| cannot connect | `gate: ai.amidman.com cannot be reached (ssh: connection timed out after 3 s); this gate runs on this Mac` |
| busy | `gate: ai.amidman.com was busy for 15 min (2 gates running); this gate runs on this Mac` |
| image build too long (new) | `gate: ai.amidman.com was still building image relay-gate:3fa2c19e0b1d after 15 min; this gate runs on this Mac` |
| could not run | `gate: ai.amidman.com could not run the gate (podman exited 125: <its last error line>); this gate runs on this Mac` |
| connection lost | `gate: the connection to ai.amidman.com was lost after 6.9 min; this gate runs on this Mac` |
| backstop (new) | `gate: ai.amidman.com did not finish within 32 min of starting; this gate runs on this Mac` |
| no record | nothing: a gate without a record runs on the Mac as today |

### 5.6 The Linux watch of the default branch (change 4)

As rev 2 5.6, with the parts change 3 now provides:
- `relay gate --watch-default [-C <repo>]` gates the default branch's head through the same `run` (5.3), with `<branch>` = the
  default branch, and writes `<git common dir>/relay-land/linux/<sha>.remote.gate.log`, never committed. The default branch's
  Linux state is the file of the newest commit on the default branch's first-parent history that has one, found by walking git,
  not by file time, so a file written later for an older commit (5.9 step 5) never stands for the head; nothing else is stored
  (principle 3). `relay gate --watch-default <sha>` gates a named commit of the default branch the same way (bring-up uses it).
- `relay land` starts it detached after a landing (lib/relay_land.py:312, the `if result.outcome == LANDED` block, after the done
  event and the lock) and returns at once; one watch at a time by a lock in the same folder; the running one gates once more if
  the default branch moved by non-inert files while it ran. Load: at most 1.59 extra VPS gates an hour (2.1). Every plugin copy of
  relay_land.py changes with it (plugins/front/lib, plugins/relay/lib).
- `Remote.default_red` is read from the newest watch file: a sentence `since <sha8> (step <name>; fix item <slug>)` when it is red,
  "" otherwise; `holds_fix` is true when the branch holds that fix item (lib/relay_queue.py, the items a branch holds).
- Red: one fix item through relay's queue writer (`relay_queue.add`, lib/relay_queue.py:1114; landed at once as queue items are),
  `found_in` "the Linux gate of the default branch", the failing lines and the log path as the failing case, pass case "the Linux
  watch of the head that lands the fix is green". While it is open a later red watch adds nothing.
- `watch_default` off in the record stops it (F1's failing case comes back; the record's line in `relay hosts status` says so).
- The Linux comparison the owner asked for on 10:53Z reads, per change, its newest remote log and its Mac landing log. Different
  heads (the landing gate runs after the default branch is taken), so a disagreement is a lead, not a proof; the watch of the
  landed head is the same-commit pair. Built by the comparison item, not here.

### 5.7 Settings (change 3)

`$RELAY_HOME/gate-hosts.json`, one record per host, schema-checked on every read, written only by `lib/relay_hosts.py`
(`relay hosts add/set/remove`). No record: no remote gate. Bounds and outcomes as rev 2 5.7 (`slots` 2, 1-3; `cpus` 4, 2-8;
`memory_gib` 4, 2-12; `cpu_shares` 256, 2-1024; `connect_timeout_s` 3, 1-15; `keepalive_s` 10 × 3, 5-20 × 2-6; `remote_wait_s`
900, 0-3,600; `images_kept` 3, 1-10; `watch_default` on), plus:

| setting | default | bound | at the bound |
|---|---|---|---|
| `build_limit_s` (new) | 900 | 300-1,800 | at 300, a cold build (311 s on this Mac, 27 Oct; the VPS not measured) gives up and every gate of that toolchain runs on the Mac until a build finishes; at 1,800, a hung build holds a slot 30 min before the gate falls back |
| backstop margin (not a setting) | `<limit s>` + 120 s | fixed | the margin covers the container's clone and checkout of a 6.7 MB bundle (about 2 s measured as `git clone` here) and `bin/ci`'s own stop |

`relay hosts set` refuses a value outside its bound and names the bound. `relay hosts status` prints one line per host: the
settings, the newest watch (`default branch: last gated on ai.amidman.com at <sha12>, 3 landings ago, green`), and the counts of
remote and fallback gates from git subjects of the last day.

### 5.8 Each "never" and "only", with its test

Rev 2 5.8's list, minus the five tests change 2 already landed (the merge hook never accepts a remote log; landing never reuses
one; the remote log decides over the stretch; no fallback over a red remote log; after a red Mac log the branch gates on the
Mac). Change 3 owns: only quick gates go remote (`--paid` and `-- <args>` make no ssh call); the container runs the gated commit
(both default-branch names); only an end line makes a result (podman 125, a traceback, a forged end line followed by podman exit
1); nothing of `$RELAY_HOME` or secrets goes along (environment, `ForwardAgent=no`, `IdentitiesOnly=yes`, bundle refs); no orphan
keeps a slot (stdin closed, SIGTERM); slots hold under a race; no branch recipe is built; the program parses as 3.12 and imports
only the standard library; unreachable VPS gives one line; only relay goes remote. Change 4 owns: the watch files one item; a
lane gates on the Mac while the watch is red, the fix's lane does not. New with this revision:
- **The slot wait and the build never count against the gate's limit:** fake podman takes 20 min to build, the limit is 25 min, the
  run after it takes 6 min: the remote log ends `exit 0`, no stop line.
- **A hung remote run is not a stop of the code:** fake run prints `relay-gate-running` and then nothing: at limit + 120 s ssh is
  ended, no remote log is written, one backstop line, a Mac log.
- **A branch cannot run its own draft of the program on the VPS:** a worktree whose `lib/relay_gate_remote.py` differs from the
  copy beside the running `bin/relay`: the `<version>` sent is that copy's, and an install sends that copy's bytes.
- **relay's code never runs root:** no code path of `relay hosts` passes `root@` to ssh; `add` against a host whose key login is
  refused prints the 3 root commands and writes no record.
- **The record has one writer:** a test greps lib/ and bin/ for `gate-hosts.json`: only lib/relay_hosts.py names it.

### 5.9 Bring-up (change 5)

Prerequisites: changes 3 and 4 landed; the clean-Linux fix closed (done, 30 Oct 05:37Z); the owner sees the 3 root commands
before they run (owner's "a", 02:26Z: "each command shown before it runs").

| step | who, where | command | undo |
|---|---|---|---|
| 1. key | relay on this Mac | `relay hosts add ai.amidman.com --user relay-gate` creates `$RELAY_HOME/keys/gate-host` (ed25519, no passphrase) when missing, tries the login, is refused, and prints steps 2-3 with the public key filled in | `relay hosts remove` deletes it |
| 2. account | root on the VPS, run by the front after the owner sees it | `useradd --create-home --shell /bin/bash relay-gate` | `userdel -r relay-gate` (home, images, key line) |
| 3. key line | the same | `install -d -m 700 -o relay-gate -g relay-gate ~relay-gate/.ssh && printf 'restrict %s\n' '<public key>' > ~relay-gate/.ssh/authorized_keys && chown relay-gate: ~relay-gate/.ssh/authorized_keys && chmod 600 ~relay-gate/.ssh/authorized_keys` | removed with step 2 |
| 4. check and record | relay on this Mac, as relay-gate | `relay hosts add ai.amidman.com --user relay-gate` again: login with `IdentitiesOnly`, program copied, `podman info` (rootless, cgroup v2, cpu, memory, pids), subuid range present, the image built from the default branch, then the first Linux watch of the default branch's head in the foreground; the record is written | `relay hosts remove ai.amidman.com` |
| 5. measure | the bring-up agent | 3 remote gates of commits the Mac also gated (the landed head from step 4, and two recent landed heads by `relay gate --watch-default <sha>`, not committed), compared exit by exit and step by step with the Mac logs; the time of each; whether a killed `relay gate` leaves a container after the session closes (2.2) | nothing |
| 6. retire the duplicate | the bring-up agent, a code change | after 3 green watches: remove the clean-image quick gate step from the paid run (lib/relay_ci_image.py and its caller and tests) | revert the commit |

The 3 root commands are steps 2 and 3 (`useradd`, `install -d`, the key file with its owner and mode). Nothing is installed on
the VPS, no service or setting changes. Times and results go into the queue item as fact notes the same turn they are read.

If the first watch (step 4) is red, the record is still written (1.6): the fix item lands, lanes keep gating on the Mac by 5.2's
"default branch red" row, and step 6 waits until 3 watches are green.

## 6. Critique

**Of the owner's picks, once.** I looked again with today's numbers. "a" (the VPS decides build-time gates) still rests on the
same arithmetic: landings 1.59 an hour (was 1.5), the VPS idle (load 0.01), nothing to install. Its four costs from rev 2
section 6 stand: Linux-only failures (now a fix item via the watch, not a red in every lane), a Mac-only break caught only at
landing, 23% of code landings losing their gate reuse (+0.23 Mac gates per landing, about 13 min each), and toolchain changes
gating on the Mac. The second "a" (relay creates the account itself) costs nothing new in exposure, and here is why it is worth
saying: **root ssh to ai.amidman.com already works from this Mac with no prompt** (this revision's read-only probe logged in as
root with `BatchMode=yes`). So any agent on this Mac can already run root commands on the server that holds mail, forgejo and
woodpecker; the gate account narrows what gates can do, but not what agents can do. That is outside this item; it is the one
question below.

**Of the brief's and rev 2's own picks.**
- Rev 2 5.4 "the quick gate's limit applied to the whole remote run" breaks with the 25-min limit (1.2); fixed here.
- Rev 2 5.7 "gate-hosts.toml" needs a TOML writer relay does not have; JSON instead (1.4).
- Rev 2 5.9 "relay hosts remove runs every undo" put a root command in code; removed (1.5).
- Rev 2 5.3.7 sent "its sha256" of the program without saying which copy; a worktree's copy would let a branch run its draft on
  the VPS outside the image rule. The copy beside the running `bin/relay` is sent (5.3.6).
- The brief's "3 gates on commits the Mac also gated" needs a way to run a remote gate of a chosen commit without committing a
  log; `relay gate --watch-default <sha>` gives it, no new command (5.6, 5.9 step 5). Its test: a watch file of an older commit
  written after the head's does not change the state `relay hosts status` prints.

## 7. Order of work and what each change needs first

| order | change | needs first | touches | agent minutes |
|---|---|---|---|---|
| 3 | hosts record and command, ssh transport, remote program, fallback, the 5.8 tests with fake ssh and podman | change 2 (landed); nothing from the owner; no VPS access (fakes only) | new lib/relay_hosts.py, lib/relay_gate_ssh.py, lib/relay_gate_remote.py, tests; bin/relay `cmd_gate` (build the `Remote`) and a thin `cmd_hosts`; reads `QUICK_LIMIT_SECONDS` | 165 (rev 2: 150; +15 for the running line, the backstop, the refusal that prints the root commands) |
| 4 | the Linux watch: `relay gate --watch-default`, its start from `relay land`, `default_red`/`holds_fix`, the fix item | change 3 | lib/relay_land.py and its 2 plugin copies, lib/relay_gate_ssh.py, bin/relay | 45 |
| 5 | bring-up (5.9), then retire the paid clean-image step | changes 3 and 4 landed; **the owner present to see 3 root commands** | the VPS (3 root commands, then the account only); lib/relay_ci_image.py and its caller | 50, plus gate wall time (one image build, about 4 gates) |

Lanes beside it: `speed-up-the-quick-gate` (in build; bin/ci, lib/relay_ci.py, tests/parallel_unittest.py) shares no file with
changes 3-4; it changes the limit constant change 3 reads, so whichever lands second runs against the other's value with no edit.
`tests-build-a-new-git-repo-for-every-case` (in build) shares none.

## 8. Recommendation

Build changes 3, 4, 5 in that order with the six decisions of section 1 (owner can reverse each). Rests on: the landed interface
read from the code (lib/relay_gate_logs.py:15-37, lib/relay_gate.py:389-423, bin/relay:633-661); the VPS re-read today (2.1:
idle, no account yet, cgroup limits delegated, nothing to install); the limit constant (1,800 s, lib/relay_ci.py:53) and the
owner's 25 min; a cold image build of 311 s measured on this Mac. Not measured, a guess: the VPS gate's time (about 5 min); change
5 measures it.

## Open for the owner

**Should agents on this Mac keep root access to ai.amidman.com?**

Found while measuring for this work, outside its scope. Your server ai.amidman.com runs mail, forgejo, woodpecker and a site. Today
any program on this Mac can log in to it as root with no prompt: this plan's own read-only check did (`ssh root@ai.amidman.com`
with no password, no question). The VPS gate design gives gates an account with no admin rights, but every agent session here
still has a root key a mistyped or confused command could use. relay's guard (the check that already refuses some commands to
agents) could refuse `ssh root@…` to agents, with a one-time allowance the front asks you for at bring-up (step 2-3 of 5.9).

| | what agents can do on your server | your work | cost |
|---|---|---|---|
| a. guard refuses root ssh to agents | only what the `relay-gate` account can (no admin, no docker) | say yes at bring-up for the 3 commands | one fix item, about 30 agent minutes (not measured); your own terminal is unaffected |
| b. leave as it is | anything root can | none | none now; one wrong command can touch mail or forgejo |

- a. The guard refuses it (recommended). Rests on: the root login measured working from this Mac today; the server's role (8
  live services).
- b. Leave it.

Not asked, decided inside the principles (owner can reverse): the limit counts from the run's start, not the queue (1.2); JSON
record (1.4); no root in relay's code (1.5); `add` proves the host and runs the first watch (1.6); the paid clean-image step is
retired after 3 green watches (1.1).

## What the brief could not answer

- The VPS gate's time and whether it is green there; whether the first image build on the VPS fits 15 min. Change 5 measures both.
- Whether a container survives its account's last session under `Linger=no`; checked at bring-up.
- Whether the paid run's clean-image step has run green on master since the fix closed (no paid run found in master's log since
  05:37Z); the first watch gives the same answer on the VPS.

## What changed after the review

This revision had no review of its own; it carries rev 2's ten findings, all held, into the code or into changes 3-5:

| finding (rev 2 review) | where it is now |
|---|---|
| F1 nothing gates the default branch on Linux | change 4 (5.6); `add` runs the first watch (1.6) |
| F2 the container checked out /src's HEAD | change 3, 5.3.5 and its test |
| F3 ssh's exit taken as the gate's | change 3, 5.5 (end line only); the new backstop row writes no log |
| F4 standard input both carries and signals | change 3, 5.3.2 |
| F5 slot count, start race, builds without a slot | change 3, 5.4 |
| F6 `relay verdict` refused a remote log | landed (change 2) |
| F7 the fix round after a red Mac landing gate | landed (change 2, `_last_mac_red`) |
| F8 image builds run branch code with network | change 3, 5.4 recipe rule; extended to the program itself (5.3.6) |
| F9 "never laundered" only for the same sha | landed (change 2, stretch rule) |
| F10 the cycle's recovery did not know the remote subject | landed (cycle.js:192 names both subjects) |
