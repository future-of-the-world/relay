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
from relay_gate_logs import LIMIT_EXIT, REMOTE_SUFFIX, Remote, RemoteResult, _exit_code, first_failure

FOUND_IN = "the Linux gate of the default branch"
STOP_FOUND_IN = "the stop-sending rule of a gate host"
MAX_ROUNDS = 3      # a watch gates again when the default branch moved by non-inert files; this many gates in one call at most
LOCK, AGAIN = "watch.lock", "watch.again"


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
        path = os.path.join(folder, sha + REMOTE_SUFFIX)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        return sha, _exit_code(lines), path, age
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


def gate_commit(main: str, default: str, host: relay_hosts.Host, home: Optional[str], sha: str) -> list[str]:
    """One watch gate of `sha`: the file is written when an end line arrives (and only then); a red result files its fix item."""
    try:
        result = relay_gate_ssh.gate(host, home, main, sha, relay_gate_ssh.QUICK_COMMAND, pinned=True)
    except relay_gate_ssh.Unavailable as exc:
        maybe_file_stop(main, host)
        return ["gate: %s; no Linux result for %s" % (exc, sha[:12])]
    folder = relay_gate_ssh.linux_dir(main)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, sha + REMOTE_SUFFIX)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(log_text(sha, result))
    lines = ["watch %s: exit %d (on %s)" % (sha[:12], result.code, host.name), path]
    if is_red(result.code):
        failing = "\n".join(first_failure(result.output)) + "\nlog: " + os.path.relpath(path, main)      # relative: the queue refuses absolute temporary paths
        lines.append(file_item(main, default, FOUND_IN, "The default branch fails the quick gate on Linux (%s)" % host.name,
                               "The Linux watch of %s ended red (exit %d)." % (sha[:12], result.code),
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


def start_after_landing(main: str, spawn: Callable[..., object] = subprocess.Popen, home: Optional[str] = None, skip_temp: bool = True) -> list[str]:
    """After a landing: start `relay gate --watch-default` detached when a host is recorded with the watch on; returns lines to print.
    A repository under a temporary folder (a test's) starts none. Never changes the landing's outcome."""
    import relay_temp
    try:
        host = relay_hosts.first(home)
        if host is None or not host.watch_default or (skip_temp and relay_temp.under(main, relay_temp.temp_roots())):
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
            verdict = "green" if code == 0 else ("stopped at its limit" if code == LIMIT_EXIT else "red")
            out.append("  default branch: last gated on %s at %s, %d landings ago, %s" % (name, sha[:12], age, verdict))
        trip = relay_gate_ssh.stopped(events, host.get("stop_after"))
        out.append("  stop-sending rule: %s" % ("holds since %s" % trip["at"] if trip else "does not hold"))
        day = [e for e in events if e["at"] >= since]
        out.append("  last day: %d remote gates, %d fell back to the Mac" % (sum(e["outcome"] == "result" for e in day), sum(e["outcome"] != "result" for e in day)))
    return out
