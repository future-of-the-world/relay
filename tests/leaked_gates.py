"""After the library tests: any process still running from the run's temporary folder (its working folder is under it, or
its command names a path under it: a `relay gate`, a gate script, a sleeping child) is a leak. Find them, stop them, and
report them."""
import os
import signal
import subprocess
import time
from typing import Dict, List, Optional, Set, Tuple

STOP_GRACE = 10.0  # seconds a gate has to end its command after SIGTERM before it is killed


def _cwds() -> Optional[Dict[int, str]]:
    """pid -> resolved working folder of every process we can read: /proc where it exists, else one `lsof` call for all.
    None when lsof could not run or timed out: "nobody is there" and "could not look" differ."""
    found: Dict[int, str] = {}
    if os.path.isdir("/proc/self"):
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    found[int(name)] = os.path.realpath(os.readlink("/proc/%s/cwd" % name))
                except OSError:
                    pass
        return found
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = 0
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            found[pid] = os.path.realpath(line[1:])
    return found


def _ancestors() -> Set[int]:
    """This process and its parents: the runner that scans may itself carry the folder in its command line."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=30).stdout
    parent = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            parent[int(parts[0])] = int(parts[1])
    chain = {os.getpid()}
    pid = os.getpid()
    while parent.get(pid, 0) > 1 and parent[pid] not in chain:
        pid = parent[pid]
        chain.add(pid)
    return chain


CWD_SKIPPED = "the working-folder scan did not run (lsof failed or timed out): only processes naming the run folder in their command were looked for"


def find(folder: str, notes: Optional[List[str]] = None) -> List[Tuple[int, str]]:
    """(pid, command) of every running process other than this one and its parents that runs from `folder`: its working
    folder is `folder` or lies under it, or its command line names a path under it (a gate, or any script or sleep the
    test left behind). When the working-folder half could not run, CWD_SKIPPED is appended to `notes`."""
    root = os.path.realpath(folder)
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=30).stdout
    skip = _ancestors()
    scanned = _cwds()
    if scanned is None:
        if notes is not None:
            notes.append(CWD_SKIPPED)
        scanned = {}
    cwds = scanned
    found = []
    for line in out.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if not pid_text.isdigit() or int(pid_text) in skip:
            continue
        cwd = cwds.get(int(pid_text), "")
        if cwd == root or cwd.startswith(root + os.sep) or (root + os.sep) in command:
            found.append((int(pid_text), command.strip()))
    return found


def stop(folder: str, notes: Optional[List[str]] = None) -> List[Tuple[int, str]]:
    """Stop the leaked processes (a gate, its command, a script or sleep) under `folder`: SIGTERM (the gate ends its command's group and frees its slot), SIGKILL if
    it is still there after STOP_GRACE. Returns the ones found."""
    found = find(folder, notes)
    for pid, _ in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + STOP_GRACE
    pending = [pid for pid, _ in found]
    while pending and time.monotonic() < deadline:
        pending = [pid for pid in pending if _alive(pid)]
        if pending:
            time.sleep(0.1)
    for pid in pending:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie of ours is gone for this purpose
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(state) and not state.startswith("Z")
