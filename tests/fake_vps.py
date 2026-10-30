"""A fake gate host for tests (no network, no podman): `ssh` and `podman` scripts in <root>/bin that run the REAL lib/relay_gate_remote.py.
The fake ssh drops its options and runs the received string through `sh -c` in <root>/home with the fake podman first on PATH, as a real
sshd would for the account's login shell. The fake podman keeps its state in <root>/state, and runs the container's script for real
(in a folder, with the bundle read from a file) so the commit the container sees is the commit the program was asked to gate.
Behaviour comes from <root>/mode.json (keys below), read at each call."""
import json
import os
import sys

from fake_tools import install_fake

SSH = r'''#!%(py)s
import json, os, signal, subprocess, sys
vps = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
args = sys.argv[1:]
i, target, cmd = 0, None, ""
while i < len(args):
    if args[i] in ("-o", "-i"):
        i += 2
    elif args[i] == "-T":
        i += 1
    else:
        target, cmd = args[i], " ".join(args[i + 1:])
        break
mode = json.load(open(vps + "/mode.json")) if os.path.exists(vps + "/mode.json") else {}
with open(vps + "/ssh.jsonl", "a") as log:
    log.write(json.dumps({"target": target, "cmd": cmd, "argv": args}) + "\n")
if mode.get("unreachable"):
    sys.stderr.write("ssh: connect to host ai.test port 22: Connection timed out\n")
    sys.exit(255)
if mode.get("refuse") and "@" in target:
    sys.stderr.write("%%s: Permission denied (publickey).\n" %% target)
    sys.exit(255)
env = {"PATH": vps + "/bin:" + os.environ.get("PATH", ""), "HOME": vps + "/home", "LANG": "C"}
os.chdir(vps + "/home")
if mode.get("lose_after_running"):
    proc = subprocess.Popen(["sh", "-c", cmd], env=env, stdout=subprocess.PIPE)
    for line in proc.stdout:
        sys.stdout.write(line.decode()); sys.stdout.flush()
        if line.startswith(b"relay-gate-running"):
            proc.send_signal(signal.SIGHUP)      # what sshd does to the remote command when the connection drops (a kill would leave a created container)
            proc.wait()
            sys.exit(255)
    sys.exit(proc.wait())
os.execvpe("sh", ["sh", "-c", cmd], env)
'''

PODMAN = r'''#!%(py)s
import json, os, shutil, signal, subprocess, sys, time
vps = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
st = vps + "/state"
for d in ("images", "containers"):
    os.makedirs(st + "/" + d, exist_ok=True)
mode = json.load(open(vps + "/mode.json")) if os.path.exists(vps + "/mode.json") else {}
a = sys.argv[1:]
def log():
    with open(vps + "/podman.jsonl", "a") as f:
        f.write(json.dumps(a[:1] + [x for x in a[1:] if len(x) < 60]) + "\n")
log()
if a[:2] == ["image", "exists"]:
    sys.exit(0 if os.path.exists(st + "/images/" + a[2]) else 1)
if a[0] == "build":
    tag = a[a.index("-t") + 1]
    open(vps + "/build.pid", "w").write(str(os.getpid()) + "\n")      # the test waits on this and then checks that the build is gone
    if mode.get("build_hang"):
        time.sleep(600)
    time.sleep(mode.get("build_sleep", 0))
    if mode.get("build_exit"):
        sys.stderr.write("build broke\n"); sys.exit(mode["build_exit"])
    open(st + "/images/" + tag, "w").write("%%f" %% time.time())
    os.utime(st + "/images/" + tag, (time.time() + len(os.listdir(st + "/images")), time.time() + len(os.listdir(st + "/images"))))
    sys.exit(0)
if a[0] == "images":
    names = sorted(os.listdir(st + "/images"), key=lambda n: -os.path.getmtime(st + "/images/" + n))
    print("\n".join(names)); sys.exit(0)
if a[0] == "rmi":
    os.remove(st + "/images/" + a[1]); sys.exit(0)
if a[0] == "ps":
    print("\n".join(n[:-5] for n in os.listdir(st + "/containers") if n.endswith(".json") and os.path.exists(st + "/containers/" + n[:-5] + ".run")))
    sys.exit(0)
if a[0] == "info":
    print(mode.get("info", "true v2 [cpu io memory pids]")); sys.exit(0)
if a[0] == "create":
    if mode.get("create_exit"):
        sys.stderr.write("Error: boom from podman\n"); sys.exit(mode["create_exit"])
    name = a[a.index("--name") + 1]
    time.sleep(mode.get("create_sleep", 0))      # a create still running when the Mac's connection is cut
    rest = a[a.index("sh"):]
    json.dump({"argv": a, "script": rest[2], "args": rest[4:]}, open(st + "/containers/" + name + ".json", "w"))
    open(vps + "/created", "w").close()      # the test waits on this: a create has finished
    if mode.get("create_garbage"):
        sys.stdout.buffer.write(b"\xff\xfe\n")      # not text: the program that reads this output raises
        sys.stdout.flush()
    sys.exit(0)
if a[0] == "cp":
    name, _, _p = a[2].partition(":")
    shutil.copy(a[1], st + "/containers/" + name + ".bundle"); sys.exit(0)
if a[0] == "rm":
    name = a[-1]
    pid = st + "/containers/" + name + ".pid"
    if os.path.exists(pid):
        held = open(pid).read()
        try:
            if held.endswith("\n"): os.kill(int(held), signal.SIGKILL)   # a pid is whole only with its newline
        except OSError: pass
    for ext in (".json", ".bundle", ".pid", ".run"):
        if os.path.exists(st + "/containers/" + name + ext): os.remove(st + "/containers/" + name + ext)
    sys.exit(0)
if a[0] == "start":
    name = a[-1]
    spec = json.load(open(st + "/containers/" + name + ".json"))
    open(st + "/containers/" + name + ".run", "w").close()
    open(st + "/containers/" + name + ".pid", "w").write(str(os.getpid()) + "\n")
    if mode.get("start_exit"):
        sys.exit(mode["start_exit"])
    if mode.get("forged"):
        print("relay-gate-exit 0"); sys.stdout.flush(); sys.exit(1)
    if mode.get("hang"):
        time.sleep(600)
    work = st + "/work-" + name
    os.makedirs(work)
    env = dict(os.environ, RELAY_GATE_BUNDLE=st + "/containers/" + name + ".bundle", RELAY_GATE_WORK=work,
               FAKE_CI_EXIT=str(mode.get("ci_exit", 0)), FAKE_CI_SLEEP=str(mode.get("ci_sleep", 0)), FAKE_CAPTURE=vps + "/capture.txt",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull)
    done = subprocess.run(["sh", "-c", spec["script"], "sh"] + spec["args"], env=env)
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(done.returncode)
sys.exit(0)
'''

CI = '''#!/bin/sh
# the repository's bin/ci in tests: the exit and a pause come from the fake host's mode
echo "step one ok"
printf 'head=%s\\nbranches=%s\\n' "$(git rev-parse HEAD)" "$(git branch --format='%(refname:short)' | tr '\\n' ' ')" > "${FAKE_CAPTURE:-/dev/null}"
[ -n "$FAKE_CI_SLEEP" ] && [ "$FAKE_CI_SLEEP" != 0 ] && sleep "$FAKE_CI_SLEEP"
if [ "${FAKE_CI_EXIT:-0}" != 0 ]; then echo "step two FAILED"; echo "  boom"; fi
exit "${FAKE_CI_EXIT:-0}"
'''


class FakeVps:
    def __init__(self, root: str):
        self.root = root
        for folder in ("bin", "home", "state"):
            os.makedirs(os.path.join(root, folder), exist_ok=True)
        install_fake(os.path.join(root, "bin", "ssh"), SSH % {"py": sys.executable})
        install_fake(os.path.join(root, "bin", "podman"), PODMAN % {"py": sys.executable})
        self.mode({})

    @property
    def bin(self) -> str:
        return os.path.join(self.root, "bin")

    def mode(self, values: dict) -> None:
        with open(os.path.join(self.root, "mode.json"), "w") as handle:
            json.dump(values, handle)

    def lines(self, name: str) -> list:
        path = os.path.join(self.root, name)
        if not os.path.exists(path):
            return []
        with open(path) as handle:
            return [json.loads(line) for line in handle.read().splitlines()]

    def ssh_calls(self) -> list:
        return self.lines("ssh.jsonl")

    def podman_calls(self) -> list:
        return [c[0] for c in self.lines("podman.jsonl")]

    def containers(self) -> list:
        folder = os.path.join(self.root, "state", "containers")
        return sorted(n for n in os.listdir(folder) if n.endswith(".json")) if os.path.isdir(folder) else []

    def images(self) -> list:
        folder = os.path.join(self.root, "state", "images")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def capture(self) -> str:
        path = os.path.join(self.root, "capture.txt")
        with open(path) as handle:
            return handle.read()
