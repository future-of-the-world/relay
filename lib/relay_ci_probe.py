"""Records of the gate's inert-probe worktrees and their clean-up (split from relay_ci).

A probe is a temporary worktree registered in the MAIN repository, so its record is kept twice: in the gated worktree
(<root>/.ci/inert-probe, the path of its temporary folder) and in the repository's shared git folder
(<common>/relay-inert-probes/<folder name>: the owner's root, then the folder). The first is cleaned by the next gate of
the same worktree; the second lets the next gate of ANY worktree remove a probe whose owner worktree is gone."""
from __future__ import annotations

import os
import shutil
import subprocess

from relay_ci_lines import _read_lines


def _run(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def shared_dir(root: str) -> str:
    """<shared git folder>/relay-inert-probes of the repository `root` belongs to."""
    common = _run(root, "rev-parse", "--git-common-dir").stdout.strip() or ".git"
    return os.path.join(os.path.realpath(os.path.join(root, common)), "relay-inert-probes")


def write_shared_record(root: str, tmpd: str) -> None:
    folder = shared_dir(root)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, os.path.basename(tmpd)), "w", encoding="utf-8") as handle:
        handle.write(root + "\n" + tmpd + "\n")


def drop_shared_record(root: str, tmpd: str) -> None:
    try:
        os.remove(os.path.join(shared_dir(root), os.path.basename(tmpd)))
    except FileNotFoundError:
        pass


def _remove_probe(root: str, tmpd: str) -> None:
    if tmpd and os.path.isdir(tmpd):
        _run(root, "worktree", "remove", "--force", os.path.join(tmpd, "wt"))
        shutil.rmtree(tmpd, ignore_errors=True)
    _run(root, "worktree", "prune")


def remove_leftover_probe(root: str) -> None:
    """Remove the probe worktree of an earlier run of THIS worktree that was killed before it could clean up, and the probes
    of worktrees that no longer exist. A probe of a live other worktree is never touched (it has its own record)."""
    record = os.path.join(root, ".ci", "inert-probe")
    lines = _read_lines(record)
    if lines:
        _remove_probe(root, lines[0].strip())
        drop_shared_record(root, lines[0].strip())
    if os.path.exists(record):
        os.remove(record)
    folder = shared_dir(root)
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        owner = _read_lines(os.path.join(folder, name))
        if len(owner) == 2 and not os.path.isdir(owner[0]):
            _remove_probe(root, owner[1])
            os.remove(os.path.join(folder, name))
