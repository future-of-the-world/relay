"""Records of the gate's copy worktrees and their clean-up (split from relay_ci).

A gate copy is a temporary worktree registered in the MAIN repository, so its record is kept twice: in the gated worktree
(<root>/.ci/gate-copy, the path of its temporary folder) and in the repository's shared git folder
(<common>/relay-gate-copies/<folder name>: the owner's root, then the folder). The first is cleaned by the next gate of
the same worktree; the second lets the next gate of ANY worktree remove a copy whose owner worktree is gone."""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess

from relay_ci_lines import _read_lines


def _run(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def shared_dir(root: str) -> str:
    """<shared git folder>/relay-gate-copies of the repository `root` belongs to."""
    common = _run(root, "rev-parse", "--git-common-dir").stdout.strip() or ".git"
    return os.path.join(os.path.realpath(os.path.join(root, common)), "relay-gate-copies")


_held: dict[str, object] = {}   # record path -> the open record file whose exclusive lock says "this gate is alive"


def write_shared_record(root: str, tmpd: str, pid: int | None = None, hold: bool = True) -> None:
    """The record: the owner's root, the temporary folder, and the pid of the gate that made the copy (the pid only names the
    gate). `hold` keeps an exclusive flock on the record until `drop_shared_record`: the kernel frees it when the gate dies,
    whatever its pid namespace or a later reuse of its pid, so the lock, not the pid, tells a running gate from a killed one."""
    folder = shared_dir(root)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(tmpd))
    handle = open(path, "a", encoding="utf-8")   # not "w": truncating before the lock would show a half-written record
    if hold:
        fcntl.flock(handle, fcntl.LOCK_EX)
    handle.seek(0)
    handle.truncate()
    handle.write(f"{root}\n{tmpd}\n{os.getpid() if pid is None else pid}\n")
    handle.flush()
    if hold:
        _held[path] = handle
    else:
        handle.close()


def _held_by_a_gate(path: str) -> bool:
    """True when a running gate holds the record's lock; the lock is taken for the test and given back at once."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
    except FileNotFoundError:
        return True       # claimed by another pruner meanwhile
    return False


def prune_dead_copies(root: str) -> list[str]:
    """Remove every copy whose gate is gone (killed before it could clean up: nobody holds its record's lock) and return the
    folders removed. A record without a pid (written by an older gate) is left to `remove_leftover_copy`'s owner-folder rule."""
    folder = shared_dir(root)
    gone: list[str] = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        path = os.path.join(folder, name)
        lines = _read_lines(path)
        if len(lines) < 3 or not lines[2].strip().isdigit() or _held_by_a_gate(path):
            continue
        try:
            os.remove(path)   # claim the record: only the run that removed it cleans the copy
        except FileNotFoundError:
            continue
        _remove_copy(root, lines[1].strip())
        gone.append(lines[1].strip())
    return gone


def drop_shared_record(root: str, tmpd: str) -> None:
    path = os.path.join(shared_dir(root), os.path.basename(tmpd))
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    held = _held.pop(path, None)
    if held is not None:
        held.close()   # type: ignore[attr-defined]


def _remove_copy(root: str, tmpd: str) -> None:
    if tmpd and os.path.isdir(tmpd):
        _run(root, "worktree", "remove", "--force", os.path.join(tmpd, "wt"))
        shutil.rmtree(tmpd, ignore_errors=True)
    _run(root, "worktree", "prune")


def remove_leftover_copy(root: str) -> None:
    """Remove the copy worktree of an earlier run of THIS worktree that was killed before it could clean up, and the copies
    of worktrees that no longer exist. A copy of a live other worktree is never touched (it has its own record)."""
    record = os.path.join(root, ".ci", "gate-copy")
    lines = _read_lines(record)
    if lines:
        _remove_copy(root, lines[0].strip())
        drop_shared_record(root, lines[0].strip())
    if os.path.exists(record):
        os.remove(record)
    prune_dead_copies(root)
    folder = shared_dir(root)
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        owner = _read_lines(os.path.join(folder, name))
        if len(owner) >= 2 and not os.path.isdir(owner[0]):
            try:
                os.remove(os.path.join(folder, name))   # claim the record: only the gate that removed it cleans the copy
            except FileNotFoundError:
                continue   # another gate claimed it between our listing and now
            _remove_copy(root, owner[1])
