"""The gate program that runs on the VPS ai.amidman.com as the account relay-gate (plan gates-on-the-vps-hosts-transport-watch-bring-up 5.3-5.5).

Standard library only, imports nothing of relay, parses as Python 3.12: the Mac sends these exact bytes (the default branch's blob)
and installs them with a fixed shell line. Called as
    python3 relay-gate-remote.py gate <version> <ref> <sha> <tree> <default branch> <limit s> [name=value ...]
with `bundle <bytes>\\n` and the bundle on standard input; standard input then stays open until the end. End of file there, SIGHUP
or SIGTERM remove the container and the temporary folder. Lines it prints (the Mac reads them): relay-gate-running <slot> <image> <wait>,
the container's own output, relay-gate-exit <n> (printed by the container after bin/ci returned), relay-gate-result <n> (only when
podman's exit equals n), relay-gate-error <text>, relay-gate-busy <n>, relay-gate-building <image> held|gave-up,
relay-gate-killed <exit> <memory peak>. Exits: 0 result; 90 bad call; 91 could not run; 92 the commit sent is not the commit asked
for; 93 another program version; 94 the branch changes the image recipe; 95 busy or still building; 96 no end line (reserved).
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import IO, NoReturn

PINNED = "refs/relay-gate/"
RECIPE_FILES = ("container/Containerfile", "install.sh", "deps.toml")
IMAGE = "relay-gate"
BUNDLE_IN_CONTAINER = "/tmp/relay-gate.bundle"
SLOT_POLL_S = 1.0
# The container's script: a fresh repository from the bundle at the exact commit, then the gate, then the memory peak and the end line.
CONTAINER_SCRIPT = r"""
SRC=${RELAY_GATE_BUNDLE:-/tmp/relay-gate.bundle}; WORK=${RELAY_GATE_WORK:-/work}
sha=$1; tree=$2; def=$3; tip=$4
mkdir -p "$WORK/relay" && cd "$WORK/relay" || exit 92
git init -q . && git fetch -q --update-head-ok "$SRC" '+refs/*:refs/*' || exit 92
git checkout -q --detach "$sha" || exit 92
git branch -f "$def" "$tip" || exit 92
for r in $(git for-each-ref --format='%(refname)' refs/relay-gate); do git update-ref -d "$r"; done
[ "$(git rev-parse HEAD)" = "$sha" ] && [ "$(git rev-parse 'HEAD^{tree}')" = "$tree" ] || exit 92
bin/ci --quick
rc=$?
if [ -r /sys/fs/cgroup/memory.peak ]; then echo "memory peak $(( $(cat /sys/fs/cgroup/memory.peak) / 1048576 )) MB"; else echo "memory peak unknown"; fi
echo "relay-gate-exit $rc"
exit $rc
"""


class Run:
    """What must be undone when the run ends or is cut: the container, the temporary folder."""

    def __init__(self) -> None:
        self.container = ""
        self.tmp = ""
        self.done = False
        self.guard = threading.RLock()
        self.creating = False      # `podman create` is running: its container does not exist yet, so a cut must wait for it
        self.cut = 0               # the exit code of a cut that came while creating

    def cut_now(self, code: int) -> None:
        """Remove what exists and end, unless the container is being created: then run_container ends after the create returns."""
        with self.guard:
            if self.creating:
                self.cut = code
                return
        self.abort()
        os._exit(code)

    def abort(self) -> None:
        if self.container:
            subprocess.run(["podman", "rm", "-f", self.container], capture_output=True, timeout=60)
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


RUN = Run()


def say(text: str) -> None:
    print(text, flush=True)


def finish(code: int) -> NoReturn:
    """End the process at once: the thread that watches standard input may still be reading, and a normal exit would abort on it."""
    sys.stdout.flush()
    os._exit(code)


def fail(code: int, text: str) -> NoReturn:
    say("relay-gate-error " + text)
    RUN.abort()
    finish(code)


def git(bare: str, *args: str) -> tuple[int, str]:
    done = subprocess.run(["git", "--git-dir", bare, *args], capture_output=True, text=True, timeout=300)
    return done.returncode, done.stdout.strip()


def read_frame(stream: IO[bytes], path: str) -> int:
    """`bundle <n>` and n bytes from `stream` into `path`; returns n."""
    header = stream.readline().split()
    if len(header) != 2 or header[0] != b"bundle" or not header[1].isdigit():
        fail(90, "the bundle header is not understood")
    size = int(header[1])
    left = size
    with open(path, "wb") as out:
        while left:
            chunk = stream.read(min(left, 1 << 20))
            if not chunk:
                fail(91, "the bundle was cut short")
            out.write(chunk)
            left -= len(chunk)
    os.chmod(path, 0o644)      # the container's user must be able to read the copy
    return size


def free_slot(slots: int, wait_s: float, home: str) -> tuple[int, IO[str], float]:
    """(slot number, its open lock, seconds waited): a slot is free when its lock is ours and no `relay-gate-s<k>-*` container runs."""
    folder = os.path.join(home, "slots")
    os.makedirs(folder, exist_ok=True)
    start = time.monotonic()
    while True:
        running = subprocess.run(["podman", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=60).stdout.split()
        for k in range(1, slots + 1):
            handle = open(os.path.join(folder, "%d.lock" % k), "w")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                continue
            if any(name.startswith("relay-gate-s%d-" % k) for name in running):
                handle.close()
                continue
            return k, handle, time.monotonic() - start
        if time.monotonic() - start >= wait_s:
            say("relay-gate-busy %d" % len(running))
            fail(95, "busy")
        time.sleep(SLOT_POLL_S)


def build_image(bare: str, tip: str, tag: str, limit_s: float, home: str) -> None:
    """Build `relay-gate:<tag>` inside the caller's slot, bounded; a held build lock means someone else builds it."""
    image = "%s:%s" % (IMAGE, tag)
    lock = open(os.path.join(home, "slots", "build-%s.lock" % tag), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        say("relay-gate-building %s held" % image)
        fail(95, "building")
    with tempfile.TemporaryDirectory(prefix="relay-gate-ctx-", dir=RUN.tmp) as ctx:
        for name in RECIPE_FILES:
            rc, _ = git(bare, "cat-file", "-e", "%s:%s" % (tip, name))
            if rc != 0:
                continue
            target = os.path.join(ctx, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                out.write(subprocess.run(["git", "--git-dir", bare, "show", "%s:%s" % (tip, name)], capture_output=True, timeout=60).stdout)
        proc = subprocess.Popen(["podman", "build", "-f", "container/Containerfile", "-t", image, ctx], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            out_text = proc.communicate(timeout=limit_s)[0]
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            say("relay-gate-building %s gave-up" % image)
            fail(95, "building")
    if proc.returncode != 0:
        last = (out_text.strip().splitlines() or ["no output"])[-1]
        fail(91, "podman build exited %d: %s" % (proc.returncode, last))


def prune(keep: int) -> None:
    done = subprocess.run(["podman", "images", "--filter", "reference=" + IMAGE, "--format", "{{.Repository}}:{{.Tag}}"],
                          capture_output=True, text=True, timeout=60)
    for image in done.stdout.split()[keep:]:      # podman lists the newest first
        subprocess.run(["podman", "rmi", image], capture_output=True, timeout=120)


def watch_stdin() -> None:
    """End of file on standard input before the end: the Mac is gone or gave up."""
    while sys.stdin.buffer.read(4096):
        pass
    if not RUN.done:
        RUN.cut_now(98)


def on_signal(signum: int, frame: object) -> None:
    RUN.cut_now(128 + signum)


def run_container(name: str, image: str, sha: str, tree: str, default: str, tip: str, bundle: str, opts: dict[str, str]) -> tuple[int, int | None, list[str]]:
    """(podman's exit, the last end line's number or None, the last lines of output)."""
    create = ["podman", "create", "--name", name, "--network", "none", "--cpus", opts["cpus"], "--cpu-shares", opts["cpu_shares"],
              "--memory", opts["memory_gib"] + "g", "--pids-limit", "8192", "-e", "RELAY_GATE=" + sha, image,
              "sh", "-c", CONTAINER_SCRIPT, "sh", sha, tree, default, tip]
    with RUN.guard:
        RUN.creating = True
    try:
        done = subprocess.run(create, capture_output=True, text=True, timeout=120)
    finally:
        with RUN.guard:
            RUN.creating = False
            RUN.container = name      # rm -f of a name that was never created is harmless
            cut = RUN.cut
    if cut:
        RUN.cut_now(cut)
    if done.returncode != 0:
        fail(91, "podman exited %d: %s" % (done.returncode, (done.stderr.strip().splitlines() or ["no output"])[-1]))
    done = subprocess.run(["podman", "cp", bundle, "%s:%s" % (name, BUNDLE_IN_CONTAINER)], capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        fail(91, "podman exited %d: %s" % (done.returncode, (done.stderr.strip().splitlines() or ["no output"])[-1]))
    proc = subprocess.Popen(["podman", "start", "-a", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    assert proc.stdout is not None
    end: int | None = None
    tail: list[str] = []
    for line in proc.stdout:
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
        sys.stdout.flush()
        match = re.fullmatch(r"relay-gate-exit (\d+)", line.strip())
        end = int(match.group(1)) if match else end
        tail = (tail + [line.rstrip("\n")])[-5:]
    return proc.wait(), end, tail


def main(argv: list[str]) -> int:
    if len(argv) < 8 or argv[1] != "gate":
        fail(90, "usage: relay-gate-remote.py gate <version> <ref> <sha> <tree> <default branch> <limit s> [name=value ...]")
    version, ref, sha, tree, default = argv[2:7]
    with open(os.path.abspath(__file__), "rb") as handle:
        if hashlib.sha256(handle.read()).hexdigest() != version:
            fail(93, "this gate program is another version than the one asked for")
    opts = {"slots": "2", "cpus": "4", "memory_gib": "4", "cpu_shares": "256", "remote_wait_s": "900", "build_limit_s": "900", "images_kept": "3"}
    for word in argv[8:]:
        key, _eq, value = word.partition("=")
        opts[key] = value
    home = os.path.expanduser("~")
    RUN.tmp = tempfile.mkdtemp(prefix="relay-gate-")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    bundle = os.path.join(RUN.tmp, "in.bundle")
    read_frame(sys.stdin.buffer, bundle)
    threading.Thread(target=watch_stdin, daemon=True).start()
    bare = os.path.join(RUN.tmp, "bare.git")
    if subprocess.run(["git", "init", "-q", "--bare", bare], capture_output=True, timeout=60).returncode != 0:
        fail(91, "git init failed")
    fetched = subprocess.run(["git", "--git-dir", bare, "fetch", "-q", bundle, "+refs/*:refs/*"], capture_output=True, text=True, timeout=300)
    if fetched.returncode != 0:
        fail(91, "git fetch of the bundle failed: " + (fetched.stderr.strip().splitlines() or ["no output"])[-1])
    if git(bare, "rev-parse", "--verify", ref + "^{commit}")[1] != sha:
        fail(92, "%s is not at %s on the host (the branch moved after the gate began)" % (ref, sha[:12]))
    if git(bare, "rev-parse", sha + "^{tree}")[1] != tree:
        fail(92, "the tree of %s is not the tree asked for" % sha[:12])
    tip = sha if ref.startswith(PINNED) else git(bare, "rev-parse", "--verify", "refs/heads/%s^{commit}" % default)[1]
    if not tip:
        fail(92, "the default branch %s is not in the bundle" % default)
    blobs = {name: (git(bare, "rev-parse", "%s:%s" % (sha, name))[1], git(bare, "rev-parse", "%s:%s" % (tip, name))[1]) for name in RECIPE_FILES}
    changed = [name for name, (mine, theirs) in blobs.items() if mine != theirs]
    if changed:
        fail(94, "the branch changes the image recipe (%s)" % ", ".join(changed))
    tag = hashlib.sha256("".join("%s:%s\n" % (n, b[1]) for n, b in sorted(blobs.items())).encode()).hexdigest()[:12]
    image = "%s:%s" % (IMAGE, tag)
    slot, lock, waited = free_slot(int(opts["slots"]), float(opts["remote_wait_s"]), home)
    try:
        if subprocess.run(["podman", "image", "exists", image], capture_output=True, timeout=60).returncode != 0:
            build_image(bare, tip, tag, float(opts["build_limit_s"]), home)
            prune(int(opts["images_kept"]))
        say("relay-gate-running %d %s %.1f" % (slot, image, waited))
        code, end, tail = run_container("relay-gate-s%d-%d" % (slot, os.getpid()), image, sha, tree, default, tip, bundle, opts)
    finally:
        lock.close()
    RUN.done = True
    if end is not None and end == code:
        say("relay-gate-result %d" % code)
        RUN.abort()
        return 0
    if code in (137, 143):
        peak = next((line for line in reversed(tail) if line.startswith("memory peak")), "memory peak unknown")
        say("relay-gate-killed %d %s" % (code, peak))
    else:
        say("relay-gate-error podman exited %d: %s" % (code, tail[-1] if tail else "no output"))
    RUN.abort()
    return 91


if __name__ == "__main__":
    finish(main(sys.argv))
