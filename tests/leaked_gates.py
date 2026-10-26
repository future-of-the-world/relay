"""After the library tests: a `relay gate` still running with its working folder under the run's temporary folder is a
leak (its runner died and left it holding a gate slot). Find them, stop them with their command, and report them."""
import os
import signal
import subprocess
import time
from typing import List, Tuple

STOP_GRACE = 10.0  # seconds a gate has to end its command after SIGTERM before it is killed


def _cwd(pid: int) -> str:
    """The working folder of a process, resolved; "" when it cannot be read (the process ended, or is not ours)."""
    try:
        return os.path.realpath(os.readlink("/proc/%d/cwd" % pid))
    except OSError:
        pass
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        if line.startswith("n"):
            return os.path.realpath(line[1:])
    return ""


def _is_relay_gate(command: str) -> bool:
    words = command.split()
    return any(os.path.basename(w) == "relay" and i + 1 < len(words) and words[i + 1] == "gate" for i, w in enumerate(words))


def find(folder: str) -> List[Tuple[int, str]]:
    """(pid, command) of every running `relay gate` whose working folder is `folder` or lies under it."""
    root = os.path.realpath(folder)
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=30).stdout
    found = []
    for line in out.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if not pid_text.isdigit() or int(pid_text) == os.getpid() or not _is_relay_gate(command):
            continue
        cwd = _cwd(int(pid_text))
        if cwd == root or cwd.startswith(root + os.sep):
            found.append((int(pid_text), command.strip()))
    return found


def stop(folder: str) -> List[Tuple[int, str]]:
    """Stop the leaked gates under `folder`: SIGTERM (the gate ends its command's group and frees its slot), SIGKILL if
    it is still there after STOP_GRACE. Returns the ones found."""
    found = find(folder)
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
