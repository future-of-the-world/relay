"""After the library tests: any process still running from the run's temporary folder (its working folder is under it, or
its command names a path under it: a `relay gate`, a gate script, a sleeping child) is a leak. Find them, stop them, and
report them."""
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import relay_procs

STOP_GRACE = relay_procs.STOP_GRACE  # seconds a gate has to end its command after SIGTERM before it is killed (set in lib/relay_procs.py)
CWD_SKIPPED = "the working-folder scan did not run (lsof failed or timed out): only processes naming the run folder in their command were looked for"


def _cwds() -> Optional[Dict[int, str]]:
    """pid -> resolved working folder of every process we can read; None when lsof could not run ("nobody is there" and "could not look" differ)."""
    return relay_procs.working_folders()


def find(folder: str, notes: Optional[List[str]] = None) -> List[Tuple[int, str]]:
    """(pid, command) of every running process other than this one and its parents that runs from `folder`: its working
    folder is `folder` or lies under it, or its command line names a path under it (a gate, or any script or sleep the
    test left behind). When the working-folder half could not run, CWD_SKIPPED is appended to `notes`."""
    root = os.path.realpath(folder)
    procs = relay_procs.read_procs()
    skip = relay_procs.ancestors(procs, os.getpid())
    scanned = _cwds()
    if scanned is None:
        if notes is not None:
            notes.append(CWD_SKIPPED)
        scanned = {}
    found = []
    for proc in procs:
        if proc.pid in skip:
            continue
        cwd = scanned.get(proc.pid, "")
        if cwd == root or cwd.startswith(root + os.sep) or (root + os.sep) in proc.command:
            found.append((proc.pid, proc.command))
    return found


def stop(folder: str, notes: Optional[List[str]] = None) -> List[Tuple[int, str]]:
    """Stop the leaked processes (a gate, its command, a script or sleep) under `folder`: SIGTERM (the gate ends its command's group and frees its slot), SIGKILL if
    it is still there after STOP_GRACE. Returns the ones found."""
    found = find(folder, notes)
    relay_procs.stop([(pid, False) for pid, _ in found])
    return found


def _alive(pid: int) -> bool:
    return relay_procs.is_alive(pid)
