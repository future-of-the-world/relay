# Design: build-time gates on the VPS ai.amidman.com, the landing gate on this Mac

Revision 2, 30 Oct 2026, thinker. Revises rev 1 (kept beside as design-vps-build-gates.rev1.md) against its design review (design-vps-build-gates-review.json, 10 findings: 1 HIGH, 7 MEDIUM, 2 LOW). All 10 hold; section 0 says what changed for each. Read-only: no code changed, nothing installed or changed on the VPS. Brief: scratchpad/briefs/design-vps-build-gates.md. Queue item: build-time-gates-on-the-vps-landing-gate-on-the.

Owner, 30 Oct, verbatim: answered "a" to "Should a gate on the VPS ai.amidman.com decide the gates run while a change is built, with the Mac running only the landing gate, or should the Mac keep deciding every gate?". Earlier the same day: "пока он не готов, можем ли мы начать утилизировать ai.amidman.com, это vps и процессор будет медленнее, однако я думаю что основные ограничения именно системные и связаны именно с запуском большого количества процессов, сделай замер".

Terms:
- **gate**: `relay gate`, which runs `bin/ci --quick` on a change's committed head and commits a log `.relay/checks/<sha>.gate.log` (first line `head <sha>`, second `cmd <command>`, third `wait <s>`, last `exit <n>`).
- **build-time gate**: any gate the change cycle runs while the change is built (the first gate, the gate after a fixer, the gate before the check). 3.8 of the 4.8 gates per change (design-remote-gate-host rev 2, 2.1).
- **landing gate**: the gate `relay land` runs after taking the default branch into the change; the merge hook decides on it.
- **merge hook**: plugins/relay/hooks/merge.py; its step 6 (`step_gate`, line 347) refuses a merge unless the newest gate log on unchanged code is green.
- **remote gate**: a gate whose command runs on the VPS; its log comes back to this Mac and is committed here.
- **inert files**: files whose change never changes a gate result (lib/relay_inert.py:16: `docs/handover.md`, `.relay/queue/**`, `.relay/checks/**`, `.relay/changes/**`); a gate log is reused across commits that changed only these.
- **stretch**: the commits a gate request may reuse a log from: walking back from the head while only inert files changed (for a green log) or only `.relay/checks/` changed (for a red one), as `reusable` and `finished_red` walk today (lib/relay_gate.py:354, :378).
- **deciding host**: the machine whose result a gate request takes (5.2).
- **bundle**: a `git bundle` file, a packed set of commits that `git clone` reads like a repository.
- **slot**: a permit to run one gate at a time on a machine.
- **Linux watch**: the new VPS gate of the default branch's head after each landing (5.6); its result is kept in the repository's git folder, never committed.

## 0. What changed from rev 1, finding by finding

| finding | verdict | what rev 2 does |
|---|---|---|
| F1 (HIGH) nothing gates the default branch on Linux | holds | new 5.6: after every landing, one VPS gate of the new default-branch head (no Mac slot); red files one fix item at the top of the queue; while the default branch is Linux-red, lanes' build-time gates run on the Mac, except the lane that holds that fix item |
| F2 the container checks out /src's HEAD, not the gated commit | holds (reproduced by the reviewer) | 5.3/5.4: the bundle carries the branch ref; no host clone; the container clones with `--no-checkout`, checks out the sha detached, creates the local default branch, drops the remote, and compares `HEAD` and `HEAD^{tree}` with the arguments before `bin/ci` |
| F3 ssh's exit status is taken as the gate's exit | holds | 5.5: the gate's exit comes only from an end line the container prints after `bin/ci` returned, matched with podman's exit; no end line means "could not run": fallback, no remote log. No host folder is mounted (`podman cp` instead), so the 0700 uid-mapping problem is gone |
| F4 standard input carries the bundle and also signals liveness | holds | 5.3: input is framed (`bundle <bytes>` then the bytes); after it the Mac keeps standard input open, and end of file there is the connection's end; a write error on the output is a second signal |
| F5 slot count and start race; image builds hold no slot | holds | 5.4: N slot lock files held by the kernel for the gate's life, plus the slot number in the container name; one build lock per image tag; a building gate holds its slot |
| F6 `relay verdict` refuses a check citing a remote log | holds | 5.1: `_gate` (lib/relay_verdict.py:754) compares with the regex group; all plugin copies listed |
| F7 the fix round after a red Mac landing gate is gated on the VPS | holds | 5.2: while the branch's newest Mac log is red, its build-time gates run on the Mac |
| F8 the consent question hid that image builds run branch code with network | holds | 5.4: images are built only from the default branch's recipe; a branch that changes the recipe gates on the Mac. The owner's question now states what runs with network |
| F9 "never laundered" held only for the same sha | holds | 5.2: the rule is stated over the stretch, and a Mac fallback is not started when the stretch holds a red remote log |
| F10 the cycle's recovery does not know the remote subject | holds | 5.1: cycle.js:166 names both subjects |

The reviewer's design remark (measure-vps-spawn put tests-build-a-new-git-repo-for-every-case first; rev 1 runs it beside) is answered in 7: kept beside, because the two share no files and the fix item ranks above this feature in the queue anyway.

## 1. Short answer: what this design decides (owner can reverse each)

1. **A remote gate writes its own file, `.relay/checks/<sha>.remote.gate.log`.** The merge hook (lib/relay_marks.py:227 `is_sha(name[:-9])`) and `relay land` ignore it with **no change to the merge hook**; the reviewer confirmed this. Build-time reuse, `relay verdict` and the cycle's recovery are taught the second name.
2. **Transport: one framed bundle per gate (the branch ref and the default branch, full history) on ssh's standard input; the container clones it, checks out the gated sha and checks commit and tree before `bin/ci`.** Measured: 6.2 MB, 1.2 s to make, 1.75 s to send. Nothing of relay stays on the VPS between gates except the gate images. No bare repository (owner, 28 Oct: no remote).
3. **Running: rootless podman under a new non-root account `relay-gate`, image from relay's `container/Containerfile` as landed on the default branch.** Run with no network, no host folder, CPU, memory and process caps. Measured: podman 4.9.3, newuidmap, pasta and cgroup v2 already there; **no package to install**.
4. **The default branch is gated on Linux after every landing** (the Linux watch), and a red result is one fix item at the top of the queue, not a red gate in every lane.
5. **Fallback: VPS unreachable in 3 s, busy over 15 min, or unable to run the gate → the gate runs on this Mac and says so in one line.** Paid gates and landing gates never go to the VPS.
6. **Setup: relay can do it through the root ssh login the owner already has, with the owner's yes** (3 root commands, 5.9; undone by `userdel -r relay-gate`).
7. **Order:** the clean-Linux fix first (a prerequisite); tests-build-a-new-git-repo-for-every-case beside; the build is 3 changes plus a bring-up, about 4 h 50 min of agent time (7).

## 2. Measurements (30 Oct, 06:00-06:20 local, master bc1c2009; landing rate re-read at 767db704)

### 2.1 The VPS now, read-only (one ssh session with a 60 s sample)

| what | value |
|---|---|
| machine | Ubuntu 24.04.4, kernel 6.8, 8 vCPUs, 16 GB RAM (14.3 GB available), no swap, up 16 weeks |
| disk | `/` 154 GB, 115 GB free (26% used) |
| load over 60 s | 0.03-0.07; CPU busy **0.4% of 8 cores** (242 of 48,760 jiffies) |
| top CPU users over 60 s | woodpecker-server 28 jiffies, gitea (forgejo) 28, dockerd 13, containerd 9, woodpecker-agent 6 (6,000 = one full core) |
| containers (docker) | caddy, woodpecker-server, 2 woodpecker agents (one for ALIX), athens, forgejo, tuda-lending, mailserver; together about 0.9 GB RAM, under 1.2% CPU |
| GitHub Actions runner | `/root/actions-runner`, last job log 22 May (idle 5 months) |
| podman | 4.9.3, runc, cgroup v2 with cpu, memory, pids controllers; `/usr/bin/newuidmap`, pasta and slirp4netns present |
| accounts | no account with uid 1000 or above; `/etc/subuid` empty (useradd fills it on Ubuntu) |
| tools on the host | git 2.43.0, Python 3.12.3, jq 1.7, procps 4.0.4, lsof, curl; **missing**: python3.14, uv, unzip, make, gcc |
| sshd | `PermitRootLogin yes`, `PasswordAuthentication no`, `ClientAliveInterval 0` |

**A silent ssh session is cut before 60 s.** A `sleep 60` with no output ended "Connection to 72.56.248.208 closed by remote host"; the same 60 s with `ServerAliveInterval=10` held. The server sends no keepalives, so something on the path drops an idle connection: **keepalives from the Mac are required.** (The leftover `/tmp/.relayprobe.*` files of the cut session were removed and checked gone.)

### 2.2 Transport

| | measured |
|---|---|
| `git bundle create` of HEAD and master, full history (3,321 commits) | 6,156,876 bytes, 1.17 s |
| sending it over ssh to `cat > /dev/null` | 1.75 s |
| ssh round trip | 0.57 s |
| secret-like strings in the whole history (`sk-ant-…`, private key headers, `ghp_…`, `AKIA…`) | 0 |

### 2.3 What this Mac's gates do today (git and the landing events)

- **Landings that reused a gate:** of 47 landings, 33 ran a gate and 14 reused one; **10 of 43 code landings (23%)** passed on a build-time gate with no gate of their own.
- **A landing gate that runs:** median 789 s, p90 1,629 s (39 landings).
- **Gates per hour** (gate commits on master, 3 days): 354 in 65 active hours; median 5, p90 8, max 11.
- **Landings per hour:** 48 landed between 28 Oct 17:40 and 30 Oct 01:54 UTC (`.git/relay-land/events.jsonl`), about **1.5 an hour**. This is the Linux watch's load before coalescing (5.6).
- **Toolchain changes:** 9 commits touched container/Containerfile, deps.toml or install.sh in 14 days: at most 4-5 changes a week gate on the Mac under 5.4's recipe rule.

### 2.4 Not measured

- A full quick gate on the VPS (no tools there; nothing could be installed). The about-5-min figure is a guess from the 4.6-5.6x of three git-heavy test files (measure-vps-spawn, 3).
- How busy the woodpecker agents get when an ALIX pipeline runs.
- Whether rootless `podman --cpus` works on this VPS (cgroup delegation to the user's systemd); checked at bring-up.
- How often the default branch would be Linux-red after a landing. The one data point: on 30 Oct the clean Linux image gave 12 failing test batches on a commit the Mac passed.

## 3. How leading tools route jobs to remote runners

| tool | how a job finds a machine | what relay takes from it |
|---|---|---|
| Buildkite agents, GitLab runner tags, GitHub `runs-on` labels | each runner carries tags; a job names the tags it needs; a required check names one job, and a result from another job does not satisfy it | the landing requires the **Mac** result by name, as a protected branch requires the check named `macos` |
| Bazel remote execution | inputs content-addressed; the platform is part of the action's key, so a Linux result is never served for a Mac action; `--remote_local_fallback` runs locally when the remote fails | the host is part of the log's name; the commit pins the input; local fallback |
| distcc | host list with slots, `localhost/2 vps/4`; jobs pushed over ssh; a host that is down is skipped | push over ssh, slots per host, local fallback, no daemon besides sshd |
| GitLab/GitHub "main is red" (a pipeline on the default branch after each merge) | the default branch is built after merges; a red result alerts once, it is not pushed into every open merge request | the Linux watch: one gate of the default branch, one fix item |
| woodpecker (on the VPS itself) | agents pull from a server, a fresh container per step | the fresh container per job; not the server (the owner's manifesto: no external CI/CD) |

## 4. Approaches

| | A. Separate file, bundle, rootless podman (recommended) | B. Host line in the same file, bare repo, plain processes | 0. Do nothing |
|---|---|---|---|
| how a remote result is told apart | file name `<sha>.remote.gate.log`; no merge-path reader opens it | a `host vps` line in `<sha>.gate.log`; the hook learns to parse it | n/a |
| if the new code has a bug | **fails closed**: a remote log still decides no merge | **fails open**: a remote log without its host line reads as a Mac log | n/a |
| merge hook changes | none | `step_gate`, `gate_logs`, plus the plugin copy | none |
| one sha gated on both hosts | two files side by side | impossible: one path per sha | n/a |
| transport | 6.2 MB bundle per gate, nothing kept | push to a bare repository on the VPS: a full copy of relay on the server, which is a remote (owner, 28 Oct: no remote) | n/a |
| toolchain | the Containerfile image of the default branch | install.sh into the account's home: a second recipe that drifts | n/a |
| what runs with network on the server | only the default branch's installer, at an image build (about 4-5 a week) | every gate: branch code runs as a user with network and can read world-readable files on a mail server | n/a |
| packages to install on the VPS | none | unzip | none |
| Mac gate-minutes per change | about 74 → about 15-17, plus fallbacks and the Linux-red windows (5.6) | the same | about 74 |
| build-time gate wall per change | 3.8 × about 5 min ≈ 19 min (a guess, 2.4) | the same | 3.8 × 15.5 ≈ 59 min |
| agent build time | about 4 h 50 min (7) | about 4 h 30 min, plus its own hook design review | 0 |

Do nothing keeps the Mac at load 20-48 with 25% of gate time spent waiting for a slot, and leaves the VPS's measured 18x faster git starts unused.

## 5. Specification of approach A

### 5.1 The two logs and who reads which

Worked example, commit `b55c82b9…` built in lane `wt/x`:

| file | written when | lines |
|---|---|---|
| `.relay/checks/b55c82b9….remote.gate.log` | a build-time gate ran on the VPS and its end line came back (5.5) | `head <sha>`, `cmd bin/ci --quick`, `wait <s>` (VPS slot wait), `host ai.amidman.com image relay-gate:<12 hex> tree <tree id>`, output, `exit <n>` |
| `.relay/checks/b55c82b9….gate.log` | a gate ran on this Mac (landing, paid, or a build-time gate whose deciding host is the Mac or that fell back) | as today |

The remote log is committed with the subject `relay: remote gate of <sha>`, so the landing counters (lib/relay_land_counters.py:64) keep counting Mac gates; a second counter counts remote ones. Both files are under `.relay/checks/`, so both are inert.

| reader | Mac log | remote log | change |
|---|---|---|---|
| merge hook `step_gate` via `relay_marks.gate_logs` | yes | **no** | none (`is_sha(name[:-9])` already skips it; confirmed by the review) |
| `relay land` (`relay_gate.run`, lib/relay_land.py:356) | yes | **no** | passes `remote=False`; reuse stays Mac-only |
| `relay gate` at build time: `reusable`, `finished_red` | yes | yes | per stretch, by the rule of 5.2 |
| `relay_gate.earlier_stop` (land's "stopped twice") | yes | no | none |
| `relay verdict` `GATE_NAME` (lib/relay_verdict.py:54) | yes | yes | `^([0-9a-f]{40})(\.remote)?\.gate\.log\Z` |
| `relay verdict` `_gate` head check (lib/relay_verdict.py:754) | yes | yes | compares `logged` with the regex's group 1, not `base[:-len(".gate.log")]`; a remote log whose head line names another sha is still "not in the gate's form" |
| `relay gate`'s printed line (bin/relay:633) | yes | yes | prints `gate <sha>: exit 0 (on ai.amidman.com)`, not `gate <sha>.remote` |
| `relay check show` (lib/relay_marks.py:308) | yes | yes | the newest log's host, and a second line for the newest Mac log |
| cycle recovery (plugins/delegate/workflows/cycle.js:166) | yes | yes | names both subjects: "relay: gate of <sha>" or "relay: remote gate of <sha>"; its glob `<sha>*.gate.log` already matches both |
| metrics coverage (lib/relay_metrics.py:378) | yes | yes | label the host |

Copies to change together (the gate's "lib copies identical" step catches a miss): relay_verdict.py in plugins/front/lib and plugins/relay/lib; relay_land.py in plugins/front/lib and plugins/relay/lib; relay_marks.py in plugins/relay/lib; relay_queue.py in plugins/front/lib and plugins/relay/lib if 5.6 touches it.

### 5.2 Which host decides, and reuse across hosts ("a reused gate is the gate")

A request first picks its **deciding host**, in this order:

| request | deciding host | why |
|---|---|---|
| landing (`relay land`) | Mac | owner's "a" |
| paid (`--paid`) | Mac | paid runs stay here |
| no host record, or a worktree without `container/Containerfile` | Mac | only relay goes remote |
| the branch's newest Mac log on its own line since its base is red (F7) | Mac | the gate that failed is the gate that confirms the fix: a Mac-only break fixed and gated on the VPS would turn green there and red again at landing, with no bound on the loop |
| the default branch's newest Linux watch result is red (5.6), and this branch does not hold that fix item | Mac | a red default branch says nothing about this change; no lane is sent to fix code it did not touch |
| the branch changes container/Containerfile, deps.toml or install.sh against the default branch (5.4) | Mac | no branch recipe runs with network on the server |
| otherwise (build-time) | VPS | owner's "a" |

Reuse, over the stretch (F9):
- **Deciding host Mac:** only Mac logs count, green or red, exactly as today.
- **Deciding host VPS:** when the stretch holds any remote log, the **newest remote log decides**, whatever Mac logs lie in the same stretch. When it holds none, a Mac log (a fallback) serves as today. So a red remote result at `C` stands after its log commit `C2` and a Mac run at `C2`: the review's laundering path is closed.
- **No fallback over a red remote log:** when the stretch holds a red remote log and the VPS cannot be reached, `relay gate --again` does not start a Mac run whose green could not change the result. It prints `gate: the red result of ai.amidman.com for <sha12> stands; ai.amidman.com cannot be reached, so it cannot be run again now (relay gate --again once it is back)` and exits with the red code.
- **Cost of the owner's pick, measured:** the 10 of 43 code landings (23%) that reused a build-time Mac gate will run a Mac gate instead: +0.23 Mac gates per landing, each about 13 min (median 789 s).

### 5.3 Transport

1. `relay gate` on this Mac needs the head on a branch (a detached head gates on the Mac). It runs `ssh -o BatchMode=yes -o ConnectTimeout=3 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o ForwardAgent=no -o ClearAllForwardings=yes -i $RELAY_HOME/keys/gate-host relay-gate@ai.amidman.com python3 relay-gate-remote.py gate <version> <branch> <sha> <tree id> <default branch>` with a fixed environment (`PATH`, `HOME`, `LANG`), not the Mac's.
2. **Framed input (F4):** the first line on standard input is `bundle <bytes>`, then exactly that many bytes of `git bundle create - refs/heads/<branch> refs/heads/<default branch>` (full history). After the bundle the Mac writes nothing more and **keeps standard input open** until the run's end line arrives. On the VPS, end of file on standard input after the bundle means the connection or the Mac's gate ended: the program runs `podman rm -f` on its container and deletes its temp folder. A write error on its output (the Mac side gone, `EPIPE`) is the second signal and does the same; so does `SIGHUP`.
3. Full history and not the stripped commit: 6 tests read pinned old commits and 3 need a default branch (29 Oct); the inert probe needs the real inert files.
4. On the VPS the bundle goes to a file in a 0700 temp folder in the account's home. `git bundle list-heads` must show `refs/heads/<branch>` at `<sha>` and the default branch, else exit 92. A bare clone of the bundle in the same folder serves only to read the recipe blobs (5.4). No working checkout is made on the host.
5. **In the container (F2):** the bundle is put in with `podman cp` (no host folder mounted), then:
   `git clone -q --no-checkout ~/in.bundle ~/relay && cd ~/relay && git checkout -q --detach <sha> && git branch <default> origin/<default> && git remote remove origin`, then `git rev-parse HEAD` must equal `<sha>` and `git rev-parse HEAD^{tree}` must equal `<tree id>`, else exit 92 before `bin/ci` starts. Dropping the remote makes `lib/relay_git.default_branch` (lib/relay_git.py:434) find the local `master` as on the Mac, which has no remote; with `origin/HEAD` left in place it could name the wrong branch.
6. **What goes along:** the repository's commits and nothing else. No `$RELAY_HOME`, no `~/.claude`, no keys, no environment. The run gets `RELAY_PAID=off`, `RELAY_GATE=<sha>` and a `RELAY_HOME` inside the container. History holds no secret-like string (2.2).
7. **The remote program:** `lib/relay_gate_remote.py`, standard library, must run on the VPS's Python 3.12 while relay's gate type-checks for 3.14. A test parses it with `ast.parse(..., feature_version=(3, 12))`; anything else it gets wrong fails as "could not run" (5.5), never as a red result. Each gate sends its sha256 as `<version>`; a different copy on the VPS exits 93 and the Mac sends the new file over the same key, then retries once.

### 5.4 Running on the VPS

- **Account:** `relay-gate`, no sudo, not in the `docker` group (so it cannot reach dockerd and the 8 live containers). Its key line in `authorized_keys` carries `restrict`.
- **Image recipe from the default branch only (F8):** the tag is `relay-gate:<first 12 hex of sha256 over the blob ids of container/Containerfile, deps.toml and install.sh>`. The program computes it at `<sha>` and at the bundle's default branch; when they differ it exits 94 and the Mac runs the gate here: `gate: this branch changes relay's toolchain (deps.toml); its gates run on this Mac until it lands`. So an image build runs only the installer as landed on the default branch (reviewed and checked), with network, as `relay-gate`, about 4-5 times a week. The run itself has no network. A branch whose recipe equals an older default branch's (an old branch after a toolchain landing) differs from the current one and gates on the Mac until it takes the default branch.
- **Build:** a missing tag is built from those three files of the default branch (`git archive` into the temp folder, `podman build`; 311 s cold on the Mac, 27 Oct). Keep the 3 newest tags.
- **Run:** `podman create --name relay-gate-s<k>-<run id> --network none --cpus 4 --cpu-shares 256 --memory 4g --pids-limit 8192 <image> sh -c '<5.3.5 steps>; bin/ci --quick; rc=$?; echo "relay-gate-exit $rc"; exit $rc'`, then `podman cp` of the bundle, then `podman start -a`. `--cpu-shares 256` gives the VPS's own services the CPU whenever they want it.
- **Slots (F5):** `slots` lock files `~/slots/<k>.lock`, k = 0 .. slots-1. A gate takes slot k by a non-blocking `flock` on its file, and the slot counts as free only when no container named `relay-gate-s<k>-*` is running. The kernel releases the lock when the program dies, so nothing is stored that can drift (principle 3), and an orphan container still blocks its slot. The gate holds its slot from before the image check to after `podman rm`, so **a build counts as a slot**. No free slot: it retries every 10 s and prints a line each minute (which also keeps the connection alive).
- **One build per tag:** a blocking `flock` on `~/build-<tag>.lock` around "tag missing? build it"; a second gate needing the same tag waits there, then finds the tag present.
- **The Mac side while it runs:** `relay gate` holds the worktree's lock as today, takes **no** Mac gate slot and **no** Mac test tokens, and applies the quick gate's time limit to the whole remote run: at the limit it ends ssh (the VPS removes the container, 5.3.2) and writes the remote log with `exit 124` and the stop line, as today.

### 5.5 What counts as a result, fallback, and what the gate prints

**A remote log is written only when the run reached its end (F3):** the container's last output line is `relay-gate-exit <n>` and podman's exit status equals `n`; the program then prints its own last line `relay-gate-result <n>`, and the Mac takes the gate's exit from that line only. ssh's exit status is never read as the gate's exit. Anything else (podman's own errors 125/126/127, an out-of-memory kill 137, a git failure 128 before `bin/ci`, a Python traceback, exits 90-99) is "could not run": no remote log, one line, the gate runs here. The one exception is the Mac's own time limit (5.4), which writes `exit 124` as today.

| case | detected after | line on standard error (also the first output line of the Mac log) |
|---|---|---|
| start on the VPS | | `gate: on ai.amidman.com (slot 1 of 2, image relay-gate:3fa2c19e0b1d)` |
| cannot connect | `connect_timeout_s` (3 s) | `gate: ai.amidman.com cannot be reached (ssh: connection timed out after 3 s); this gate runs on this Mac` |
| busy | `remote_wait_s` (900 s) | `gate: ai.amidman.com was busy for 15 min (2 gates running); this gate runs on this Mac` |
| could not run (no end line) | when it happens | `gate: ai.amidman.com could not run the gate (podman exited 125: <its last error line>); this gate runs on this Mac` |
| connection lost mid-run | keepalive, 30 s | `gate: the connection to ai.amidman.com was lost after 6.9 min; this gate runs on this Mac` |
| deciding host is the Mac (5.2) | at once | the reason: `gate: the default branch is red on ai.amidman.com since 4f1a2b3c (step library; fix item <slug>); this gate runs on this Mac`, or the toolchain line of 5.4, or `gate: the last gate of this branch on this Mac is red; this gate runs on this Mac` |
| red or stopped on the VPS, end line present | | no fallback: it is the result (`exit 1`, or `exit 124`, handled as today) |
| red remote log in the stretch, VPS unreachable | at once | 5.2's "stands" line, no Mac run |

Worst case before a fallback starts: 3 s, 15 min, or the remote run time plus 30 s.

### 5.6 The Linux watch of the default branch (F1)

The gap: under "a", the Mac's landing gate is the only gate of the merged code, and Mac-green does not imply Linux-green (12 failing batches on 30 Oct). A landing whose build-time gates fell back to the Mac, or two changes each Linux-green whose merge is Linux-red, leave the default branch Linux-red, and every lane would then get a red VPS gate for code it did not touch.

- **When:** after `relay land` returns LANDED, it starts one detached `relay gate --watch-default` and returns at once. It takes no Mac slot and no Mac test tokens.
- **Coalescing:** one watch at a time (a lock in the git folder). A watch started while one runs exits; the running one, when done, gates again once if the default branch moved by non-inert files meanwhile. At the measured 1.5 landings an hour this adds at most 1.5 VPS gates an hour to the build-time peak of about 9.
- **What it gates:** the default branch's head, by the same transport and run (5.3, 5.4), with `<branch>` = the default branch.
- **Where the result lives:** `<git common dir>/relay-land/linux/<sha>.remote.gate.log`, beside `events.jsonl`; never committed (the default branch moves only by landings) and never read by the merge hook. The newest file is the default branch's Linux state; nothing else is stored.
- **Red:** one fix item through relay's queue writer (`relay queue add`, landed at once as queue items are): kind fix, `failing_kind` run, `found_in` "the Linux gate of the default branch", the failing lines and the log path as the failing case, pass case "the Linux watch of the head that lands the fix is green". A fix item ranks above the features (principle 1). While that item is open, a later red watch adds nothing and prints its sha.
- **Meanwhile:** lanes' build-time gates run on the Mac with the line of 5.5 (5.2's table), so no lane is sent to fix it and the cycle's checker never marks such a fix "NOT MET (scope)". The lane that holds the fix item (lib/relay_queue.py:1350, the items a branch holds) keeps gating on the VPS: its VPS gate is its proof.
- **Green again:** the next watch after the fix lands is green; lanes go back to the VPS by themselves.
- **VPS unreachable:** no item; the next landing tries again. `relay hosts status` prints `default branch: last gated on ai.amidman.com at <sha12>, 3 landings ago, green`.
- **What the window loses:** while the default branch is Linux-red, lanes are gated on the Mac only, so a Linux-only break they add is seen at the next watch after they land. Accepted: the alternative, lanes waiting for the fix, idles up to 6 lanes for the fix's 60-90 agent minutes.

### 5.7 Settings

In `$RELAY_HOME/gate-hosts.toml`, one record per host, written only by `relay hosts` (principle 4), checked by a schema. No record: no remote gate.

| setting | default | bound | at the bound |
|---|---|---|---|
| `slots` | 2 | 1-3 | at 1, a peak hour of 9 build-time gates plus 1.5 watches queues when a VPS gate takes over 5.7 min; at 3, 12 cores asked of 8: gates slow each other (services still win by weight) |
| `cpus` per gate | 4 | 2-8 | at 2, the library step's 4 workers share 2 cores (about 2x slower); at 8, one gate can take every core |
| `memory_gib` per gate | 4 | 2-12 | at 2, the 0.67 GB peak of 29 Oct fits with little room for a leak (an out-of-memory kill falls back to the Mac, 5.5); at 12, two gates can take the 14 GB the services leave |
| `cpu_shares` | 256 | 2-1024 | at 1024, a gate competes evenly with forgejo, mail and woodpecker; at 2, a busy CI build can nearly stop a gate |
| `connect_timeout_s` | 3 | 1-15 | at 1, a short hiccup sends the gate to the Mac; at 15, an unreachable VPS delays each gate 15 s |
| `keepalive_s` × count | 10 × 3 | 5-20 × 2-6 | above about 50 s per interval the path's idle cut (2.1) can drop a quiet session |
| `remote_wait_s` | 900 | 0-3,600 | at 0, any busy moment sends the gate to the Mac; at 3,600, a change waits up to an hour while the Mac is free |
| `images_kept` | 3 | 1-10 | at 1, a rollback of the toolchain rebuilds (5 min); at 10, about 10 GB of disk |
| `watch_default` | on | on/off | off: no Linux gate of the default branch; a Linux-red landing turns lanes red (F1's failing case) |

### 5.8 Each "never" and "only", with the test that fails when it is false

All with a fake `ssh` and a fake `podman` on PATH, in a temp repository.
- **The merge hook never accepts a remote log:** a head with only a green `<sha>.remote.gate.log` is refused "no green gate"; adding a green Mac log lets it through.
- **Landing never reuses a remote log:** `relay land` with a green remote log of its head and an inert-only take runs the Mac gate (`gates_run` 1); the fake `ssh` records no call.
- **Only quick gates go remote:** `relay gate --paid` with a host: no ssh call.
- **The remote log decides over the stretch:** remote red at `C`, its log commit `C2`, Mac green at `C2`: `relay gate` reports the red one and runs nothing. Remote red and Mac green on one commit: the same.
- **No fallback over a red remote log:** the same with ssh exiting 255: the "stands" line, no Mac run, red exit.
- **After a red Mac log the branch gates on the Mac:** a red Mac landing log at the newest code commit, then a fix commit: no ssh call. After a green Mac gate: the next gate calls ssh. No Mac log: ssh. Red remote log, no Mac log: ssh.
- **The container runs the gated commit:** a bundle of `<sha>` and master with the VPS's git default `master`, and again with `init.defaultBranch=main`: before `bin/ci`, `git rev-parse HEAD` is `<sha>`, `refs/heads/master` exists at the bundle's master, and `relay_git.default_branch` returns `master`. A tree argument that differs: exit 92, the Mac falls back, no remote log.
- **Only an end line makes a result:** fake podman exits 125 before the container starts: no remote log, one "could not run" line, a Mac log. A traceback with exit 1 and no end line: the same. `bin/ci` exits 1 and the end line says 1: a remote log `exit 1`, no fallback. An end line `relay-gate-exit 0` printed by a test followed by podman exit 1: not a result.
- **Nothing of $RELAY_HOME or secrets goes along:** the fake `ssh` records its arguments, environment and standard input; the test fails on any variable outside `PATH HOME LANG`, a missing `ForwardAgent=no`, or bundle refs other than the branch and the default branch.
- **No orphan keeps a slot:** 6.2 MB framed bundle sent and the connection held: the run starts and is not removed. Standard input closed 2 min into the run, or the Mac's `relay gate` killed with SIGTERM: within 5 s the fake podman got `rm -f relay-gate-s0-<id>`, the temp folder is gone, and the next gate takes slot 0 at once.
- **Slots hold under a race:** slots 2, one running; two gate programs started together: exactly one starts, the other waits. Two gates needing the same missing tag: one `podman build`. A build in progress and slots 1: a new gate waits. A leftover `relay-gate-s0-old` running with slots 1: a new gate waits.
- **No branch recipe is built:** a branch changing install.sh: exit 94, the toolchain line, a Mac log, and the fake podman records no `build`.
- **The remote program runs on Python 3.12:** `ast.parse(source, feature_version=(3, 12))` succeeds.
- **A remote log passes the check record:** `relay verdict` with gate `<sha>.remote.gate.log` starting `head <sha>`, ending `exit 0`: recorded, no gate problem, kept as the bare name; one whose head line names another sha: "not in the gate's form". The plugin copies stay identical.
- **The Linux watch files one item:** a landing followed by a red watch: exactly one fix item, with the failing lines; a second red watch while it is open: no second item; a green watch: no item and no Mac gate run. While the watch is red, a lane's gate makes no ssh call and prints the "default branch is red" line; the lane holding the fix item calls ssh.
- **Unreachable VPS gives one line:** ssh exiting 255: exactly one line starting `gate: ai.amidman.com cannot be reached`, and a Mac log.
- **Only relay goes remote:** a worktree without `container/Containerfile`: no ssh call.

### 5.9 Setup: what the owner does once, what relay does itself

The owner's step: say yes to the question below. Then relay runs from this Mac, through the owner's root ssh login (these steps only, never by a gate):

| step | command (on the VPS as root unless noted) | undo |
|---|---|---|
| 1. key | on this Mac: `ssh-keygen -t ed25519 -N '' -f $RELAY_HOME/keys/gate-host -C relay-gate` | delete the two files |
| 2. account | `useradd --create-home --shell /bin/bash relay-gate` (Ubuntu adds its `/etc/subuid`, `/etc/subgid` ranges; checked after) | `userdel -r relay-gate` (home, images, key line) |
| 3. key line | `install -d -m 700 -o relay-gate ~relay-gate/.ssh`; append `restrict <public key>` to `~relay-gate/.ssh/authorized_keys` (mode 600) | removed with step 2 |
| 4. program | as relay-gate: copy `relay-gate-remote.py` into its home | removed with step 2 |
| 5. check | as relay-gate: `podman info` (rootless, cgroup controllers), the first image build, one gate | nothing |
| record | on this Mac: `relay hosts add ai.amidman.com --user relay-gate` | `relay hosts remove ai.amidman.com` runs every undo above |

No package install, no change to sshd, docker, the 8 containers or any service. If step 5 finds the cpu or memory controller not delegated, the run uses `nice -n 19` and the slots as the cap, and a delegation drop-in for user@.service (a root change) comes to the owner first.

## 6. Critique

**Of the owner's pick ("a"), once.** I looked; it is sound on the numbers (Mac gate-minutes per change about 74 → about 15-17), with four costs:
1. **Linux-only failures stop the build while you still live on this Mac.** On 30 Oct the clean Linux image gave 12 failing test batches on a commit the Mac passed. Until the clean-Linux fix is green, "a" would turn every build-time gate red; hence that fix first. After it, the Linux watch (5.6) keeps the default branch green on Linux: a Linux-red landing becomes one fix item, and lanes gate on the Mac until it lands.
2. **A Mac-only break is caught only at landing,** after review and check: one more fix round plus a 13-min Mac gate. 5.2 keeps that fix round on the Mac, so it loops at most as today. How often: not measured (the Mac-only paths: the lsof reading, the slot reclaim, the installer's Darwin branches).
3. **Landings lose their reuse:** 23% of code landings will run a 13-min Mac gate they skip today (5.2).
4. **Toolchain changes keep their gates on the Mac** (5.4), at most 4-5 changes a week; their Linux result is first seen by the Linux watch after they land.

**Of the brief's own picks.**
- "Checked by tree id": with a full-history bundle the commit id already fixes the tree; the check is kept (one `rev-parse`, and right if the stripped commit replaces the bundle later). It now runs where `bin/ci` runs, inside the container.
- "The pinned toolchain installed in that account's home": done as a podman image stored there, not as install.sh run into it; a second recipe would drift from the Containerfile.
- The 29 Oct stripped-commit design strips three inert paths; lib/relay_inert.py has four (`.relay/changes/**`). A future stripped commit takes the list from relay_inert.

## 7. Order of work and the build

| order | change | depends on | agent minutes |
|---|---|---|---|
| 1 | **the-quick-gate-is-red-again-in-a-clean-linux-ima** (fix, ip 91, taken): `bin/ci --quick` green in the Containerfile image; `lsof` in the image; `RUN sh install.sh; true` must stop hiding a failed install | none | 60 (queue estimate) |
| beside | **tests-build-a-new-git-repo-for-every-case** (fix, ip 88): not a prerequisite; it helps this Mac most (27 ms per git start against 1.5 ms on the VPS), which still runs the landing gate and every `relay precheck`. measure-vps-spawn ranked it first because it cuts the cause on both machines; it ranks above this feature in the queue either way (principle 1), and the two share no files, so it runs in a lane beside change 2 rather than holding it | none | 90 (queue estimate) |
| 2 | **Remote log name and its readers** (5.1, 5.2): the deciding-host table, reuse over the stretch, `GATE_NAME` and `_gate`, the printed line, `relay check show`, cycle.js recovery, the subject and counter, all plugin copies; the 5.8 tests that need no transport. The remote runner is a function a test replaces | none | 55 |
| 3 | **Hosts, transport, remote program, fallback** (5.3-5.5, 5.7): `relay hosts add/remove/status` with schema and one writer; `lib/relay_gate_remote.py` (framing, end line, slot and build locks, recipe from the default branch, `podman cp`, container checkout); the Mac side with the fallback lines; the 5.8 tests with fake ssh and podman | 2 | 150 |
| 4 | **The Linux watch** (5.6): `relay gate --watch-default`, its start from `relay land`, the git-folder log, the fix item through the queue writer, the "default branch is red" row of the deciding-host table | 3 | 45 |
| 5 | **Bring-up on the VPS** (5.9), after the owner's yes and change 1 green: setup, first image build, 3 gates on commits the Mac also gated, one watch; times and results into the queue item | 1, 4 | 40, plus the gates' wall time |

Total about 4 h 50 min of agent time for changes 2-5 (rev 1: 3 h 45 min; the item says 4 h). Change 2 can start now; change 5 waits for change 1. Change 4 can be dropped (`watch_default` off) only by accepting F1's failing case.

## 8. Recommendation

Build approach A in the order of section 7. Rests on: the reader list read from the code and confirmed by the review (no merge-path reader opens `.remote.gate.log`); the transport measured (6.2 MB, 2.9 s to make and send) and the reviewer's reproduction of the checkout gap, now closed inside the container; the VPS measured idle (0.4% CPU, 14.3 GB free, podman and uid mapping present, no package needed); the landing rate (1.5 an hour) for the watch's load. Not measured, a guess: the about-5-min VPS gate (from the 4.6-5.6x of git-heavy tests) and how often the default branch goes Linux-red; change 5 measures the first, the watch's fix items will count the second.

## Open for the owner

**May relay set up the gate account on ai.amidman.com itself, using your root login?**

The VPS gates need an ordinary account on your server that relay's own key can log into. Your server runs mail, forgejo, woodpecker and a site, so this is your call. relay would create the account `relay-gate` (no admin rights, no access to docker), put relay's new key into it, copy one program into its home, and run one test gate; it installs no package and changes no service or setting. What then runs there: each gate runs relay's tests in a fresh container with no network and no access to your files, at most 2 at a time, with lower CPU priority than your services. With network: only an image build, which runs relay's installer as landed on relay's main line (not a branch's draft), about 4-5 times a week; it downloads relay's tools (uv, bun) from the internet. Everything is undone by deleting that account.

| | your work | what runs as root on your server | undo |
|---|---|---|---|
| a. relay does it | say yes once | 3 commands, once (create the account, its key folder, the key line), each shown before it runs | relay deletes the account |
| b. you do it | type 3 commands, paste one key | the same 3 commands, typed by you | you delete the account |

- a. relay does it (recommended). Rests on: the VPS read today (podman and uid mapping present, nothing to install) and the steps in 5.9.
- b. You run the commands yourself.

Decided inside the principles and reversible, not asked: images only from the main line's recipe (5.4); lanes gate on this Mac while the main line is red on Linux (5.6).

## What the brief could not answer

- A full quick gate on the VPS: its time and whether it is green there. Change 5 measures it.
- How loaded the VPS gets while an ALIX pipeline runs on woodpecker.
- Whether rootless `podman --cpus`, `--cpu-shares` and `--memory` work there (cgroup delegation; Ubuntu 24.04 delegates by default, not verified). Checked at bring-up.
- Why an idle ssh session is cut before 60 s (the path, not sshd); the keepalive works around it.
- How often the default branch goes Linux-red after a landing; the watch's fix items will show it.
