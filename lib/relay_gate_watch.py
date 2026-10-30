"""The Linux watch of the default branch and the rules built on its files (plan gates-on-the-vps-hosts-transport-watch-bring-up 5.2, 5.6):
which Remote a lane gate gets (or the reason it stays on the Mac), the watch itself (`relay gate --watch-default`), the fix items a
red watch and a run of could-not-run endings file, and `relay hosts status`. A watch's result is a file in the git common dir
(`relay-land/linux/<sha>.remote.gate.log`), never committed; the state is found by walking git, nothing else is stored."""
from __future__ import annotations

import fcntl
import os
import shlex
import subprocess
import sys
import time
from typing import Callable, Optional, Sequence

import relay_git
import relay_hosts
import relay_inert
import relay_gate_ssh
from relay_gate_compare import run_files, run_name
from relay_gate_logs import LIMIT_EXIT, Remote, RemoteResult, _exit_code, first_failure

FOUND_IN = "the Linux gate of the default branch"
STOP_FOUND_IN = "the stop-sending rule of a gate host"
MAX_ROUNDS = 3      # a watch gates again when the default branch moved by non-inert files; this many gates in one call at most
LOCK, AGAIN, TWIN_LOCK = "watch.lock", "watch.again", "twin.lock"


def _tip(main: str, default: str) -> str:
    return relay_git.git(main, "rev-parse", "--verify", "refs/heads/%s^{commit}" % default)[1]


def _first_parent(main: str, default: str) -> list[str]:
    rc, out = relay_git.git(main, "rev-list", "--first-parent", "refs/heads/" + default)
    return out.split() if rc == 0 else []


def is_red(code: Optional[int]) -> bool:
    """A watch is red when its end line says 0 < n < 127 and n != 124 (124 is a stop of the code at its limit; the same rule as finished_red)."""
    return code is not None and 0 < code < 127 and code != LIMIT_EXIT


def newest_watch(worktree: str) -> Optional[tuple[str, Optional[int], str, int]]:
    """(sha, exit, log path, commits since) of the newest first-parent commit of the default branch that has a watch file, else None."""
    main, default = relay_git.main_checkout(worktree), relay_git.default_branch(worktree)
    if not main or not default:
        return None
    folder = relay_gate_ssh.linux_dir(worktree)
    for age, sha in enumerate(_first_parent(main, default)):
        files = run_files(folder, sha)      # the newest run of a commit with a verdict is its Linux state: a green re-run clears a red first run, a re-run stopped at its limit confirms nothing
        found: list[tuple[str, Optional[int]]] = []
        for path in files:
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    found.append((path, _exit_code(handle.read().splitlines())))
            except OSError:
                continue
        if not found:
            continue
        verdicts = [f for f in found if f[1] == 0 or is_red(f[1])]
        path, code = (verdicts or found)[-1]
        return sha, code, path, age
    return None


def open_item(main: str, default: str, found_in: str) -> Optional[str]:
    """The slug of an open or taken fix item found in `found_in` on the default branch, else None."""
    import relay_queue
    try:
        items = relay_queue.Reader(main, "refs/heads/" + default).items()
    except Exception:      # no queue in this project: nothing is open
        return None
    for slug, item in sorted(items.items()):
        if not item["problems"] and item["kind"] == "fix" and item["found_in"] == found_in and item["state"] in ("open", "taken"):
            return slug
    return None


def file_item(main: str, default: str, found_in: str, title: str, what: str, why: str, failing: str, pass_cases: str) -> str:
    """One fix item through relay's queue writer unless one with this `found_in` is open; the line to print."""
    import relay_queue
    slug = open_item(main, default, found_in)
    if slug:
        return "fix item %s is open already" % slug
    try:
        relay_queue.add(main, "fix", title, why=why, what=what, failing=failing, pass_cases=pass_cases, minutes=30, failing_kind="run", context=found_in)
    except relay_queue.Refused as exc:
        return "the fix item could not be filed (%s)" % exc
    return "filed a fix item: %s" % title


def maybe_file_stop(worktree: str, host: relay_hosts.Host) -> None:
    """The could-not-run event that trips the stop-sending rule files its fix item (plan 5.6)."""
    main, default = relay_git.main_checkout(worktree), relay_git.default_branch(worktree)
    events = relay_gate_ssh.read_events(worktree, host.name)
    n = host.get("stop_after")
    if not main or not default or not relay_gate_ssh.stopped(events, n) or relay_gate_ssh.stopped(events[:-1], n):
        return
    lines = "\n".join([e["line"] for e in events if e["outcome"] in relay_gate_ssh.COUNTED][-n:])
    line = file_item(main, default, STOP_FOUND_IN, "Gates on %s keep ending without a result" % host.name,
                     "The last %d remote gates on %s ended with could-not-run, so gates stay on this Mac until a Linux watch there finishes." % (n, host.name),
                     "Remote gates that cannot run cost every lane its remote time and then a full Mac gate.", lines,
                     "The next watch on the host reaches an end line.")
    print("gate: " + line, file=sys.stderr, flush=True)


def build_remote(worktree: str, home: Optional[str] = None) -> tuple[Optional[Remote], str]:
    """(Remote, "") for a quick lane gate that may go to the host; (None, reason) when it stays on the Mac for a reason to print (the line
    after `gate: ` without the closing "this gate runs on this Mac"); (None, "") when there is no record or no branch."""
    host = relay_hosts.first(home)
    if host is None or not relay_git.current_branch(worktree):
        return None, ""
    if not os.path.isfile(os.path.join(worktree, "container", "Containerfile")):      # a project that cannot go remote: deciding_host sends it to the Mac silently
        return None, ""
    last = relay_gate_ssh.stopped(relay_gate_ssh.read_events(worktree, host.name), host.get("stop_after"))
    if last is not None:
        main, default = relay_git.main_checkout(worktree), relay_git.default_branch(worktree)
        slug = open_item(main, default, STOP_FOUND_IN) if main and default else None
        return None, "%s could not run the last %d gates (%s; fix item %s); gates stay on this Mac until a Linux watch there finishes" % (
            host.name, host.get("stop_after"), last["line"].replace("gate: ", "", 1), slug or "not filed yet")
    watch = newest_watch(worktree)
    if watch is None:
        return None, "%s has not yet gated the default branch (run relay gate --watch-default)" % host.name
    sha, code, path, _age = watch
    red, held = "", False
    if is_red(code):
        with open(path, encoding="utf-8", errors="replace") as handle:
            body = handle.read().splitlines()[4:-1]
        main, default = relay_git.main_checkout(worktree), relay_git.default_branch(worktree)
        slug = open_item(main, default, FOUND_IN) if main and default else None
        red = "since %s (step %s; fix item %s)" % (sha[:8], first_failure("\n".join(body))[0].strip(), slug or "not filed yet")
        if slug:
            import relay_queue
            held = slug in relay_queue.held_fix_items(worktree)

    def run(tree: str, head: str, command: Sequence[str]) -> RemoteResult:
        try:
            return relay_gate_ssh.gate(host, home, tree, head, command)
        except relay_gate_ssh.Unavailable:
            maybe_file_stop(tree, host)
            raise
    return Remote(host.name, run, red, held), ""


def log_text(head: str, result: RemoteResult) -> str:
    out = result.output
    return "head %s\ncmd %s\nwait %.1f\n%s\n%s%sexit %d\n" % (head, " ".join(shlex.quote(c) for c in relay_gate_ssh.QUICK_COMMAND), result.wait, result.host_line,
                                                              out, "" if out.endswith("\n") or not out else "\n", result.code)


def gate_runs(main: str, host: relay_hosts.Host, home: Optional[str], sha: str, folder: str, prefix: str = relay_gate_ssh.PINNED,
              header: str = "") -> tuple[list[str], Optional[RemoteResult], str, bool]:
    """One gate of `sha` on the host and, while the newest run is red, up to `rerun_disagreement` more, each in a file of its own beside
    the first (written when an end line arrives, and only then; an earlier gating's files go when the first new one is written). Returns (lines, newest result, its file, whether the last run needed
    was made): False when a re-run could not run, so a red first run stands but has not been confirmed."""
    os.makedirs(folder, exist_ok=True)
    lines: list[str] = []
    last, path = None, ""
    for k in range(host.get("rerun_disagreement") + 1):
        try:
            result = relay_gate_ssh.gate(host, home, main, sha, relay_gate_ssh.QUICK_COMMAND, pinned=True, prefix=prefix)
        except relay_gate_ssh.Unavailable as exc:
            maybe_file_stop(main, host)
            lines.append("gate: %s; no Linux %s for %s" % (exc, "result" if k == 0 else "re-run result", sha[:12]))
            return lines, last, path, False
        if k == 0:
            for stale in run_files(folder, sha):      # runs of an earlier gating of this commit go only when a new run has an answer
                os.remove(stale)
        path = os.path.join(folder, run_name(sha, k))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(header + log_text(sha, result))
        lines += ["watch %s: exit %d (on %s)" % (sha[:12], result.code, host.name) if k == 0 else "re-run %d of %s: exit %d" % (k, sha[:12], result.code), path]
        last = result
        if not is_red(result.code):
            return lines, last, path, k == 0 or result.code == 0      # a re-run with no verdict confirms nothing
    return lines, last, path, True


def gate_commit(main: str, default: str, host: relay_hosts.Host, home: Optional[str], sha: str) -> list[str]:
    """One watch gate of `sha` (with its re-runs); the fix item is filed only when the last run is red too."""
    lines, last, path, complete = gate_runs(main, host, home, sha, relay_gate_ssh.linux_dir(main))
    if complete and last is not None and is_red(last.code):
        failing = "\n".join(first_failure(last.output)) + "\nlog: " + os.path.relpath(path, main)      # relative: the queue refuses absolute temporary paths
        lines.append(file_item(main, default, FOUND_IN, "The default branch fails the quick gate on Linux (%s)" % host.name,
                               "The Linux watch of %s ended red (exit %d)." % (sha[:12], last.code),
                               "A red default branch on Linux sends every lane to the Mac until it is fixed.", failing,
                               "The Linux watch of the head that lands the fix is green."))
    return lines


def watch(repo: str, sha: Optional[str] = None, home: Optional[str] = None, gate_one: Callable[..., list[str]] = gate_commit) -> list[str]:
    """`relay gate --watch-default [<sha>]`: gate a first-parent commit of the default branch (default: its tip) on the host; one watch at
    a time (a second call asks the running one to gate once more). With no sha, it gates again when the default branch moved by non-inert files."""
    main, default = relay_git.main_checkout(repo), relay_git.default_branch(repo)
    if not main or not default:
        raise ValueError("%s is not in a repository with a default branch" % repo)
    host = relay_hosts.first(home)
    if host is None:
        raise ValueError("there is no gate host in the record: relay hosts add <host>")
    line = _first_parent(main, default)
    if sha is not None:
        full = relay_git.git(main, "rev-parse", "--verify", sha + "^{commit}")[1]
        if full not in line:
            raise ValueError("%s is not on the first-parent line of %s" % (sha, default))
        sha = full
    folder = relay_gate_ssh.linux_dir(main)
    os.makedirs(folder, exist_ok=True)
    handle = open(os.path.join(folder, LOCK), "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        open(os.path.join(folder, AGAIN), "w").close()
        handle.close()
        return ["a watch is running already; it gates once more when it ends"]
    try:
        if os.path.exists(os.path.join(folder, AGAIN)):      # a request left by a watch that ended: it asked for a gate that this one is about to make
            os.remove(os.path.join(folder, AGAIN))
        _rc, refs = relay_git.git(main, "for-each-ref", "--format=%(refname)", "refs/relay-gate")      # leftovers of a killed watch
        for ref in refs.split():
            relay_git.git(main, "update-ref", "-d", ref)
        out: list[str] = []
        target = sha or _tip(main, default)
        for _round in range(MAX_ROUNDS):
            out += gate_one(main, default, host, home, target)
            again = os.path.exists(os.path.join(folder, AGAIN))
            if again:
                os.remove(os.path.join(folder, AGAIN))
            tip = _tip(main, default)
            if sha is not None or not (again or (tip != target and relay_inert.changed(main, target, tip))):
                break
            target = tip
        return out
    finally:
        handle.close()


def _twin_reason(main: str, host: Optional[relay_hosts.Host], sha: str) -> str:
    """"" when a twin of `sha` should run, else the reason it should not."""
    import relay_gate_compare
    if host is None:
        return "there is no gate host in the record"
    if not host.twin_red_landings:
        return "twin_red_landings is off"
    if not os.path.isfile(os.path.join(main, "container", "Containerfile")):
        return "this project cannot go remote"
    if relay_gate_ssh.stopped(relay_gate_ssh.read_events(main, host.name), host.get("stop_after")) is not None:
        return "sending to %s is stopped" % host.name
    import relay_land
    branch = next((e.branch for e in reversed(relay_land.read_events(main)[0]) if e.kind == "done" and e.judged == sha), "")
    refs = ("refs/heads/" + (relay_git.default_branch(main) or ""), *(("refs/heads/" + branch,) if branch else ()))      # a red landing's logs are committed on its branch only
    if relay_gate_compare.linux_result(main, sha, refs) is not None:
        return "the code of %s has a Linux result already" % sha[:12]
    return ""


def twin(repo: str, sha: str, home: Optional[str] = None, gate_run: Callable[..., tuple[list[str], Optional[RemoteResult], str, bool]] = gate_runs) -> list[str]:
    """`relay gate --twin <sha>`: the Linux gate of a commit a red landing judged. Its own lock (twins run one at a time, in order), its own ref
    prefix, its own folder; never writes `watch.again`, files no fix item and is never read by the default branch's rules."""
    main = relay_git.main_checkout(repo)
    host = relay_hosts.first(home)
    if not main:
        raise ValueError("%s is not in a git repository" % repo)
    if host is None:
        raise ValueError("there is no gate host in the record: relay hosts add <host>")
    full = relay_git.git(main, "rev-parse", "--verify", sha + "^{commit}")[1]
    if not full:
        raise ValueError("%s is not a commit" % sha)
    folder = relay_gate_ssh.linux_dir(main)
    os.makedirs(folder, exist_ok=True)
    handle = open(os.path.join(folder, TWIN_LOCK), "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)      # blocking: the next twin waits its turn
        reason = _twin_reason(main, host, full)
        if reason:
            return ["no twin: " + reason]
        _rc, refs = relay_git.git(main, "for-each-ref", "--format=%(refname)", relay_gate_ssh.TWIN_PINNED.rstrip("/"))      # leftovers of a killed twin
        for ref in refs.split():
            relay_git.git(main, "update-ref", "-d", ref)
        import relay_land
        branch = next((e.branch for e in reversed(relay_land.read_events(main)[0]) if e.kind == "done" and e.judged == full), "")
        lines, _last, _path, _complete = gate_run(main, host, home, full, os.path.join(folder, "twin"), relay_gate_ssh.TWIN_PINNED, "branch %s\n" % branch)
        return lines
    finally:
        handle.close()


def start_twin_after_landing(main: str, sha: str, spawn: Callable[..., object] = subprocess.Popen, home: Optional[str] = None, skip_temp: bool = True) -> list[str]:
    """After a landing that ended red at its gate: start `relay gate --twin <sha>` detached when it should run (a host is recorded, the
    twin setting is on, sending is not stopped, no Linux result of that code exists yet). Returns lines to print; never changes the outcome."""
    import relay_temp
    try:
        host = relay_hosts.first(home)
        if skip_temp and relay_temp.under(main, relay_temp.temp_roots()):
            return []
        if _twin_reason(main, host, sha):
            return []
        relay = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "relay")
        folder = relay_gate_ssh.linux_dir(main)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "twin.log"), "ab") as log:
            spawn([sys.executable, relay, "gate", "--twin", sha, "-C", main], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        return []
    except Exception as exc:
        return ["land: the Linux twin of the red gate did not start: %s; next: relay gate --twin %s" % (exc, sha)]


def start_after_landing(main: str, spawn: Callable[..., object] = subprocess.Popen, home: Optional[str] = None, skip_temp: bool = True) -> list[str]:
    """After a landing: start `relay gate --watch-default` detached when a host is recorded with the watch on; returns lines to print.
    A repository under a temporary folder (a test's) starts none. Never changes the landing's outcome."""
    import relay_temp
    try:
        host = relay_hosts.first(home)
        if host is None or not host.watch_default or (skip_temp and relay_temp.under(main, relay_temp.temp_roots())):
            return []
        if not os.path.isfile(os.path.join(main, "container", "Containerfile")):      # a project that cannot go remote has nothing to watch
            return []
        relay = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "relay")
        folder = relay_gate_ssh.linux_dir(main)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "watch.log"), "ab") as log:
            spawn([sys.executable, relay, "gate", "--watch-default", "-C", main], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        return []
    except Exception as exc:      # the landing already happened (the rule of _change_records)
        return ["land: landed, but the Linux watch did not start: %s; next: relay gate --watch-default" % exc]


def status_lines(repo: str, home: Optional[str] = None, now: Optional[float] = None) -> list[str]:
    """`relay hosts status`: one block per host (plan 5.7)."""
    hosts = relay_hosts.load(home)
    if not hosts:
        return ["no gate host is recorded: relay hosts add <host>"]
    out = []
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime((time.time() if now is None else now) - 86400))
    for name, host in hosts.items():
        events = relay_gate_ssh.read_events(repo, name)
        out.append("%s (%s): %s" % (name, host.user, relay_hosts.settings_text(host)))
        watch_state = newest_watch(repo)
        if not host.watch_default:
            out.append("  default branch: the Linux watch is off")
        elif watch_state is None:
            out.append("  default branch: not gated on %s yet" % name)
        else:
            sha, code, _path, age = watch_state
            verdict = "green" if code == 0 else "stopped at its limit" if code == LIMIT_EXIT else "red" if is_red(code) else "ended %s" % code
            out.append("  default branch: last gated on %s at %s, %d landings ago, %s" % (name, sha[:12], age, verdict))
        import relay_gate_compare
        out += relay_gate_compare.compare_lines(repo, relay_gate_compare.DEFAULT_WAVES, home)
        trip = relay_gate_ssh.stopped(events, host.get("stop_after"))
        out.append("  stop-sending rule: %s" % ("holds since %s" % trip["at"] if trip else "does not hold"))
        day = [e for e in events if e["at"] >= since]
        out.append("  last day: %d remote gates, %d fell back to the Mac" % (sum(e["outcome"] == "result" for e in day), sum(e["outcome"] != "result" for e in day)))
    return out
