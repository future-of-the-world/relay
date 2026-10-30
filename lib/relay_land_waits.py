"""What makes `relay land` wait instead of landing (design: the change-cycle script lands a ready change itself, 5.4 and 5.5).

Exit 5 (waits for the owner): the owner's hold on the branch (`relay land --hold`, `--release`; events in the land events file,
the newest of the two decides), or a question to the owner on a queue item the branch took that is not answered yet.
Exit 6 (waits for the paid run): the branch touches the paths the paid run checks and `relay_paid.state` says a run goes, ended
without a verdict, is green but not yet installed by `relay sync`, or is red (then only `--paid-fix` lands a branch).
`waiting` lists the branches that stopped on the paid run and still exist. Everything is read when asked; nothing is stored here.
Tests: tests/test_land_waits.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

import relay_git
import relay_land
import relay_paid
from relay_land import REFUSED, WAITS_OWNER, WAITS_PAID, Event, Stop

PAID_COST = os.path.join(relay_paid.ROOT, "bin", "paid-cost")


def hold(main: str, branch: str, words: str) -> None:
    relay_land.record(main, Event("hold", relay_land.now(), branch=branch, words=words))


def release(main: str, branch: str) -> None:
    relay_land.record(main, Event("release", relay_land.now(), branch=branch))


def held_words(main: str, branch: str) -> Optional[str]:
    """The owner's words of the newest hold of `branch` when no release came after it, else None."""
    words: Optional[str] = None
    for event in relay_land.read_events(main)[0]:
        if event.branch != branch:
            continue
        if event.kind == "hold":
            words = event.words or "no words given"
        elif event.kind == "release":
            words = None
    return words


def unanswered(main: str, branch: str) -> Optional[str]:
    """The title of a question to the owner, unanswered, on an item `branch` took (read on the default branch, where answers land)."""
    import relay_queue
    try:
        items = relay_queue.read_queue(main)
    except relay_queue.Refused as exc:
        raise Stop(REFUSED, [f"land: cannot read the queue to look for a question to the owner: {exc}"])
    for item in items:
        if item.get("problems") or item.get("taken_by") != branch:
            continue
        waiting = relay_queue.owner_waiting(relay_queue.notes_of(item))
        if waiting:
            return f"{item['slug']}: {relay_queue.question_title(waiting[0])}"
    return None


def touches_paid_paths(main: str, branch: str) -> bool:
    """True when `bin/paid-cost touches` lists files (exit 0), False when it lists none (exit 1); any other exit is an error and refuses."""
    done = subprocess.run([sys.executable, PAID_COST, "touches", branch, "--repo", main], capture_output=True, text=True)
    if done.returncode not in (0, 1):
        raise Stop(REFUSED, [f"land: cannot tell whether {branch} touches the paid paths: {(done.stderr or done.stdout).strip()}"])
    return done.returncode == 0


def check(main: str, default: str, branch: str, paid_fix: bool = False) -> None:
    """Raises Stop(WAITS_OWNER ...), Stop(WAITS_PAID ...) or Stop(REFUSED ...) when the branch must not land now."""
    words = held_words(main, branch)
    if words is not None:
        raise Stop(WAITS_OWNER, [f"land: {branch} is on hold (the owner: {words}): ask the owner; when they release it, "
                                 f"relay land --release {branch}, then relay land {branch}"])
    question = unanswered(main, branch)
    if question is not None:
        raise Stop(WAITS_OWNER, [f"land: {branch} waits for the owner's answer to a question on {question}: ask the owner; "
                                 f"once it is answered, relay land {branch}"])
    paid = relay_paid.state(main)
    if paid_fix:
        if paid.name != relay_paid.RED:
            raise Stop(REFUSED, [f"land: --paid-fix is not needed: {paid.line}; relay land {branch} without it"])
        return
    if paid.name == relay_paid.FREE or not touches_paid_paths(main, branch):
        return
    how = {relay_paid.RED: f"; the fix item lands with relay land {branch} --paid-fix, the others after the next green run",
           relay_paid.GOING: f"; relay land {branch} again when it ends",
           relay_paid.WAITS_SYNC: f"; then relay land {branch}",
           relay_paid.STOPPED: f"; then relay land {branch}",
           relay_paid.NOT_JUDGED: f"; then relay land {branch} (no fix item: --paid-fix does not apply)"}[paid.name]
    raise Stop(WAITS_PAID, [f"land: {branch} touches the paid run's paths and {paid.line}{how}"])


def waiting(main: str) -> list[str]:
    """The branches whose newest landing ended waiting for the paid run and that still exist, sorted."""
    newest: dict[str, str] = {}
    for event in relay_land.read_events(main)[0]:
        if event.kind == "done" and event.branch:
            newest[event.branch] = event.outcome
    return sorted(b for b, outcome in newest.items()
                  if outcome == WAITS_PAID and relay_git.git(main, "rev-parse", "--verify", "-q", "refs/heads/" + b)[0] == 0)


def after_sync(main: str) -> list[str]:
    """`relay sync` wrote its targets: note it (the paid run's settings are installed) and name the branches waiting for it."""
    rc, head = relay_git.git(main, "rev-parse", "--verify", "-q", "refs/heads/" + (relay_git.default_branch(main) or ""))
    relay_paid.record(main, relay_paid.PaidEvent("synced", relay_paid.now(), head=head if rc == 0 else ""))
    names = waiting(main)
    return [f"waiting for the paid run: {', '.join(names)}; land them in order with relay land <branch> (relay land --waiting lists them)"] if names else []
