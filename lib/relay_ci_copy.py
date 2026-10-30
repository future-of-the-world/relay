"""Records of the gate's copy worktrees and their clean-up (split from relay_ci).

A gate copy is a temporary worktree registered in the MAIN repository, so its record is kept twice: in the gated worktree
(<root>/.ci/gate-copy, the path of its temporary folder) and in the repository's shared git folder
(<common>/relay-gate-copies/<folder name>: the owner's root, then the folder). The first is cleaned by the next gate of
the same worktree; the second lets the next gate of ANY worktree remove a copy whose owner worktree is gone."""
from __future__ import annotations

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


def write_shared_record(root: str, tmpd: str, pid: int | None = None) -> None:
    """The record: the owner's root, the temporary folder, and the pid of the gate that made the copy."""
    folder = shared_dir(root)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, os.path.basename(tmpd)), "w", encoding="utf-8") as handle:
        handle.write(f"{root}\n{tmpd}\n{os.getpid() if pid is None else pid}\n")


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True      # another user's process: it exists
    return True


def prune_dead_copies(root: str) -> list[str]:
    """Remove every copy whose gate process is gone (killed before it could clean up) and return the folders removed. A record
    without a pid (written by an older gate) is left to `remove_leftover_copy`'s owner-folder rule."""
    folder = shared_dir(root)
    gone: list[str] = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        lines = _read_lines(os.path.join(folder, name))
        if len(lines) < 3 or not lines[2].strip().isdigit() or _running(int(lines[2])):
            continue
        try:
            os.remove(os.path.join(folder, name))   # claim the record: only the run that removed it cleans the copy
        except FileNotFoundError:
            continue
        _remove_copy(root, lines[1].strip())
        gone.append(lines[1].strip())
    return gone


def drop_shared_record(root: str, tmpd: str) -> None:
    try:
        os.remove(os.path.join(shared_dir(root), os.path.basename(tmpd)))
    except FileNotFoundError:
        pass


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
