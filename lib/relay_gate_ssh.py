"""The Mac side of a gate on a remote host: the ssh transport, what counts as a result, the lines for every other ending, and the event
file the stop-sending rule reads (plan gates-on-the-vps-hosts-transport-watch-bring-up 5.3-5.6). The program on the host is
lib/relay_gate_remote.py. ssh runs with a list of arguments (no local shell); the remote command is one string with every argument
through shlex.quote, because ssh joins the words and the account's login shell parses them again."""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Sequence

import relay_git
import relay_hosts
from relay_gate_logs import RemoteResult, RemoteUnavailable

PROGRAM = "lib/relay_gate_remote.py"
PROGRAM_ON_HOST = "relay-gate-remote.py"
INSTALL_LINE = "umask 077; cat > .relay-gate-remote.tmp.$$ && mv .relay-gate-remote.tmp.$$ relay-gate-remote.py"
QUICK_COMMAND = ["bin/ci", "--quick"]      # the only command the host runs
BACKSTOP_MARGIN_S = 120      # plan 5.7: covers the clone and checkout in the container and bin/ci's own stop
WATCH_BUILD_LIMIT_S = 3600      # a watch's image build bound: nobody waits on it (plan 5.4)
EVENTS_READ, EVENTS_KEEP = 200, 1000
COUNTED = ("result", "could-not-run")      # the outcomes that count toward the stop-sending rule (plan 5.5, last column)
PINNED = "refs/relay-gate/"
SUBUID_FILE = "/etc/subuid"      # the host's file of subordinate user ids (rootless podman needs a range for the account)


class Unavailable(RemoteUnavailable):
    """`outcome`: result | could-not-run | unreachable | busy | skipped (the last two and `unreachable` never count toward stop-sending)."""

    def __init__(self, text: str, outcome: str):
        super().__init__(text)
        self.outcome = outcome


class LoginRefused(Exception):
    """relay's key does not open the gate account."""


def linux_dir(repo: str) -> str:
    rc, out = relay_git.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not out:
        raise ValueError("%s is not in a git repository" % repo)
    return os.path.join(out, "relay-land", "linux")


# ---- the event file (plan 5.6): one dated line per remote attempt, the state is computed when read --------------------------------
def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_events(repo: str, host: str) -> list[dict[str, str]]:
    """The last EVENTS_READ events of `host`, oldest first; a line that is not an event is skipped."""
    try:
        with open(os.path.join(linux_dir(repo), "host-events.jsonl"), encoding="utf-8") as handle:
            lines = handle.read().splitlines()[-EVENTS_READ:]
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and all(isinstance(event.get(k), str) for k in ("at", "host", "outcome", "line")) and event["host"] == host:
            events.append(event)
    return events


def append_event(repo: str, host: str, outcome: str, line: str, now: Optional[str] = None) -> None:
    folder = linux_dir(repo)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "host-events.jsonl")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": now or _utc(), "host": host, "outcome": outcome, "line": line}) + "\n")
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    if len(lines) > EVENTS_KEEP:
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines[-EVENTS_KEEP:]) + "\n")
        os.replace(path + ".tmp", path)


def stopped(events: Sequence[dict[str, str]], stop_after: int) -> Optional[dict[str, str]]:
    """The newest counted event when the newest `stop_after` counted events are all could-not-run, else None."""
    counted = [e for e in events if e["outcome"] in COUNTED][-stop_after:]
    return counted[-1] if len(counted) == stop_after and all(e["outcome"] == "could-not-run" for e in counted) else None


# ---- ssh ---------------------------------------------------------------------------------------------------------------------------
def ssh_argv(host: relay_hosts.Host, home: Optional[str], remote: str) -> list[str]:
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % host.get("connect_timeout_s"),
            "-o", "ServerAliveInterval=%d" % host.get("keepalive_s"), "-o", "ServerAliveCountMax=%d" % host.get("keepalive_count"),
            "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes", "-o", "IdentitiesOnly=yes", "-i", relay_hosts.key_path(home),
            "%s@%s" % (host.user, host.name), remote]


def ssh_env() -> dict[str, str]:
    return {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}


def ssh_run(host: relay_hosts.Host, home: Optional[str], remote: str, data: bytes = b"", timeout: float = 120) -> tuple[int, str, str]:
    """(exit, stdout, stderr) of one short remote command."""
    try:
        done = subprocess.run(ssh_argv(host, home, remote), input=data, capture_output=True, env=ssh_env(), timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 255, "", "ssh: %s" % exc
    return done.returncode, done.stdout.decode(errors="replace"), done.stderr.decode(errors="replace")


def last_line(text: str, default: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else default


# ---- what is sent ----------------------------------------------------------------------------------------------------------------
def _git_bytes(repo: str, *args: str) -> bytes:
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, timeout=300)
    if done.returncode != 0:
        raise ValueError(done.stderr.decode(errors="replace").strip() or "git %s failed" % args[0])
    return done.stdout


def program_source(repo: str) -> tuple[bytes, str]:
    """(bytes, sha256) of the gate program as the default branch has it (plan 5.3.6): never a branch's draft."""
    main = relay_git.main_checkout(repo)
    default = relay_git.default_branch(repo)
    if not main or not default:
        raise Unavailable("the default branch cannot be told, so the gate program cannot be sent", "skipped")
    try:
        data = _git_bytes(main, "show", "refs/heads/%s:%s" % (default, PROGRAM))
    except ValueError:
        raise Unavailable("the gate program is not on %s yet" % default, "skipped")
    return data, hashlib.sha256(data).hexdigest()


def quick_limit(repo: str, sha: str) -> int:
    """QUICK_LIMIT_SECONDS as the gated commit's lib/relay_ci.py sets it, read as text."""
    try:
        text = _git_bytes(repo, "show", "%s:lib/relay_ci.py" % sha).decode(errors="replace")
    except ValueError:
        raise Unavailable("the quick gate's time limit cannot be read from lib/relay_ci.py", "skipped")
    match = re.search(r"^QUICK_LIMIT_SECONDS\s*=\s*(\d+)", text, re.MULTILINE)
    if not match:
        raise Unavailable("the quick gate's time limit cannot be read from lib/relay_ci.py", "skipped")
    return int(match.group(1))


def remote_command(version: str, ref: str, sha: str, tree: str, default: str, limit: int, options: Sequence[str]) -> str:
    words = ["gate", version, ref, sha, tree, default, str(limit), *options]
    return "[ -r %s ] || exit 97; exec python3 %s %s" % (PROGRAM_ON_HOST, PROGRAM_ON_HOST, " ".join(shlex.quote(w) for w in words))


def install(host: relay_hosts.Host, home: Optional[str], data: bytes) -> None:
    rc, _out, err = ssh_run(host, home, INSTALL_LINE, data)
    if rc != 0:
        raise Unavailable("%s could not install its gate program (%s)" % (host.name, last_line(err, "ssh exited %d" % rc)), "could-not-run")


# ---- one remote gate -------------------------------------------------------------------------------------------------------------
class Attempt:
    """What one ssh session printed and how it ended."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.running: Optional[int] = None      # index in `lines` of the running line
        self.started = 0.0
        self.rc = 0
        self.stderr = ""
        self.backstop = False


def _session(argv: list[str], frame: bytes, limit: int, clock: Callable[[], float], on_running: Callable[[str], None]) -> Attempt:
    attempt = Attempt()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ssh_env())
    except OSError as exc:
        attempt.rc, attempt.stderr = 255, "ssh: %s" % exc
        return attempt
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    errors: list[str] = []

    def write() -> None:
        try:
            proc.stdin.write(frame)      # type: ignore[union-attr]
            proc.stdin.flush()      # type: ignore[union-attr]
        except OSError:
            pass      # the host ended early: its ending says why

    def read_out() -> None:
        for raw in proc.stdout:      # type: ignore[union-attr]
            lines.put(raw.decode(errors="replace").rstrip("\n"))
        lines.put(None)

    def read_err() -> None:
        errors.append(proc.stderr.read().decode(errors="replace"))      # type: ignore[union-attr]

    threads = [threading.Thread(target=f, daemon=True) for f in (write, read_out, read_err)]
    for thread in threads:
        thread.start()
    deadline: Optional[float] = None
    while True:
        try:
            line = lines.get(timeout=None if deadline is None else max(0.0, deadline - clock()))
        except queue.Empty:
            attempt.backstop = True      # ssh ends (SIGTERM, as for any ssh client), the host removes the container
            proc.terminate()
            break
        if line is None:
            break
        attempt.lines.append(line)
        if attempt.running is None and line.startswith("relay-gate-running "):
            attempt.running, attempt.started = len(attempt.lines) - 1, clock()
            deadline = attempt.started + limit + BACKSTOP_MARGIN_S
            on_running(line)
    try:
        proc.stdin.close()
    except OSError:
        pass
    try:
        attempt.rc = proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        attempt.rc = proc.wait()
    for thread in threads[1:]:
        thread.join(5)
    for stream in (proc.stdout, proc.stderr):
        stream.close()
    attempt.stderr = "".join(errors)
    return attempt


def _unavailable(host: relay_hosts.Host, attempt: Attempt, limit: int, clock: Callable[[], float], watch: bool) -> Unavailable:
    """The line and the outcome for an attempt that reached no result (plan 5.5)."""
    name = host.name
    errors = [line.split(" ", 1)[1] if " " in line else "" for line in attempt.lines if line.startswith("relay-gate-error")]
    if attempt.backstop:
        return Unavailable("%s did not finish within %d min of starting" % (name, math.ceil((limit + BACKSTOP_MARGIN_S) / 60)), "could-not-run")
    if attempt.running is not None and attempt.rc == 255 and not errors:
        return Unavailable("the connection to %s was lost after %.1f min" % (name, (clock() - attempt.started) / 60), "could-not-run")
    if attempt.running is None and attempt.rc == 255:
        return Unavailable("%s cannot be reached (%s)" % (name, last_line(attempt.stderr, "ssh: no answer").replace("ssh: ", "", 1)), "unreachable")
    if attempt.rc == 95:
        for line in attempt.lines:
            words = line.split()
            if words[:1] == ["relay-gate-busy"] and len(words) == 2:
                return Unavailable("%s was busy for %d min (%s gates running)" % (name, host.get("remote_wait_s") // 60, words[1]), "busy")
            if words[:1] == ["relay-gate-building"] and len(words) == 3:
                if words[2] == "held":
                    return Unavailable("%s is building image %s now" % (name, words[1]), "busy")
                bound = WATCH_BUILD_LIMIT_S if watch else host.get("build_limit_s")
                return Unavailable("%s was still building image %s after %d min" % (name, words[1], bound // 60), "could-not-run")
    if attempt.rc == 94:
        return Unavailable("this branch changes relay's toolchain (%s)" % (errors[-1] if errors else "the image recipe"), "skipped")
    if attempt.rc == 92:
        return Unavailable("%s was sent a commit that is not the one asked for (%s)" % (name, errors[-1] if errors else "the branch moved"), "skipped")
    for line in attempt.lines:
        words = line.split(maxsplit=2)
        if words[:1] == ["relay-gate-killed"] and len(words) == 3:
            return Unavailable("%s could not run the gate (the container was killed, exit %s, %s of %d GiB)" % (name, words[1], words[2], host.get("memory_gib")), "could-not-run")
    detail = errors[-1] if errors else (last_line(attempt.stderr, "") or "ssh exited %d with no end line" % attempt.rc)
    return Unavailable("%s could not run the gate (%s)" % (name, detail), "could-not-run")


def _result(host: relay_hosts.Host, attempt: Attempt) -> Optional[RemoteResult]:
    """A result only from the end line followed by the program's result line with the same number (plan 5.5)."""
    if attempt.running is None or len(attempt.lines) < attempt.running + 3 or attempt.rc != 0:
        return None
    exit_line, result_line = attempt.lines[-2].split(), attempt.lines[-1].split()
    if not (len(exit_line) == 2 and exit_line[0] == "relay-gate-exit" and len(result_line) == 2 and result_line[0] == "relay-gate-result"
            and exit_line[1] == result_line[1] and exit_line[1].isdigit()):
        return None
    running = attempt.lines[attempt.running].split()
    wait = float(running[3]) if len(running) > 3 else 0.0
    return RemoteResult(int(exit_line[1]), "\n".join(attempt.lines[attempt.running + 1:-2]) + "\n", "", wait)


def gate(host: relay_hosts.Host, home: Optional[str], worktree: str, head: str, command: Sequence[str], pinned: bool = False,
         clock: Callable[[], float] = time.monotonic, notify: Callable[[str], None] = lambda text: print(text, file=sys.stderr, flush=True)) -> RemoteResult:
    """Run the quick gate of `head` on `host`; RemoteResult, or raises Unavailable. `pinned`: a watch of a first-parent commit of the
    default branch (a temporary ref carries that exact commit); otherwise a lane gate of the worktree's branch. Records one event."""
    try:
        result = _gate(host, home, worktree, head, command, pinned, clock, notify)
    except Unavailable as exc:
        append_event(worktree, host.name, exc.outcome, "gate: %s" % exc)
        raise
    append_event(worktree, host.name, "result", "exit %d" % result.code)
    return result


def _gate(host: relay_hosts.Host, home: Optional[str], worktree: str, head: str, command: Sequence[str], pinned: bool,
          clock: Callable[[], float], notify: Callable[[str], None]) -> RemoteResult:
    if list(command) != QUICK_COMMAND:
        raise Unavailable("%s runs only `bin/ci --quick`" % host.name, "skipped")
    main, default = relay_git.main_checkout(worktree), relay_git.default_branch(worktree)
    branch = relay_git.current_branch(worktree)
    if not main or not default or (not branch and not pinned):
        raise Unavailable("the branch to send cannot be told", "skipped")
    source, version = program_source(worktree)
    limit = quick_limit(worktree, head)
    tree = relay_git.git(worktree, "rev-parse", head + "^{tree}")[1]
    ref = PINNED + head if pinned else "refs/heads/%s" % branch
    options = ["%s=%d" % (k, host.get(k)) for k in ("slots", "cpus", "memory_gib", "cpu_shares", "remote_wait_s", "images_kept")]
    options.append("build_limit_s=%d" % (WATCH_BUILD_LIMIT_S if pinned else host.get("build_limit_s")))
    if pinned:
        relay_git.git(worktree, "update-ref", ref, head)      # git refuses to bundle a bare commit id: the ref carries it
    try:
        try:
            body = _git_bytes(worktree, "bundle", "create", "-", ref, *([] if pinned else ["refs/heads/" + default]))
        except ValueError as exc:
            raise Unavailable("the bundle could not be made (%s)" % last_line(str(exc), "git failed"), "skipped")
    finally:
        if pinned:
            relay_git.git(worktree, "update-ref", "-d", ref)
    frame = b"bundle %d\n" % len(body) + body

    def on_running(line: str) -> None:
        words = line.split()
        notify("gate: on %s (slot %s of %d, image %s, %.1f MB sent)" % (host.name, words[1], host.get("slots"), words[2], len(body) / 1e6))

    installed = False
    while True:
        argv = ssh_argv(host, home, remote_command(version, ref, head, tree, default, limit, options))
        attempt = _session(argv, frame, limit, clock, on_running)
        result = _result(host, attempt)
        if result is not None:
            return RemoteResult(result.code, result.output, "host %s image %s tree %s" % (host.name, attempt.lines[attempt.running or 0].split()[2], tree), result.wait)
        if attempt.rc in (93, 97) and attempt.running is None and not installed:      # another version, or none: install the default branch's, once
            install(host, home, source)
            installed = True
            continue
        raise _unavailable(host, attempt, limit, clock, pinned)


# ---- add: prove the host (plan 5.9 step 4a) -------------------------------------------------------------------------------------
def prove(host: relay_hosts.Host, repo: str, home: Optional[str]) -> list[str]:
    """Log in as the gate account, install the program, read podman's limits and the subuid range. Builds nothing, gates nothing."""
    rc, _out, err = ssh_run(host, home, "true", timeout=60)
    if rc != 0:
        if "denied" in err.lower():
            raise LoginRefused(err)
        raise ValueError("%s cannot be reached (%s)" % (host.name, last_line(err, "ssh exited %d" % rc)))
    try:
        data, _version = program_source(repo)
        install(host, home, data)
    except Unavailable as exc:
        raise ValueError(str(exc))
    rc, out, err = ssh_run(host, home, "podman info --format '{{.Host.Security.Rootless}} {{.Host.CgroupsVersion}} {{.Host.CgroupControllers}}'", timeout=120)
    words = out.replace("[", " ").replace("]", " ").split()
    if rc != 0 or len(words) < 2:
        raise ValueError("podman info failed on %s (%s): install rootless podman for %s" % (host.name, last_line(err, "no answer"), host.user))
    if words[0] != "true" or words[1] != "v2":
        raise ValueError("podman on %s must be rootless on cgroup v2 (it says %s %s)" % (host.name, words[0], words[1]))
    missing = [c for c in ("cpu", "memory", "pids") if c not in words[2:]]
    if missing:
        raise ValueError("the cgroup controller %s is not delegated to %s on %s: gate limits would not hold" % (", ".join(missing), host.user, host.name))
    rc, _out, _err = ssh_run(host, home, 'grep -q "^$(id -un):" %s' % shlex.quote(SUBUID_FILE), timeout=60)
    if rc != 0:
        raise ValueError("%s has no subuid range on %s: rootless podman cannot run" % (host.user, host.name))
    return ["%s: logged in as %s, gate program installed, podman rootless on cgroup v2 with cpu memory pids" % (host.name, host.user)]
