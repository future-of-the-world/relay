"""A test repository with a recipe, the real gate program and a fake gate host (tests/fake_vps.py), for the tests of the transport, the
hosts record and the Linux watch."""
import hashlib
import os
import shutil
import time
from unittest import mock

from fake_vps import CI, FakeVps
from test_gate import ROOT, Fixture, git, write

import relay_gate
import relay_gate_ssh
import relay_hosts

HOST = "ai.test"
RECIPE = {"container/Containerfile": "FROM x\n", "install.sh": "echo install\n", "deps.toml": "[deps]\n"}


def wait_until(condition, timeout=30.0):
    """Poll `condition` until it is true (an event, not a sleep for its own sake); the test fails past `timeout`."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return bool(condition())


class VpsBase(Fixture):
    def setUp(self):
        super().setUp()
        self.vps = FakeVps(os.path.join(self.tmp, "vps"))
        self.home = os.path.join(self.tmp, "home")
        self.repo(gate="exit 0\n")
        write(os.path.join(self.main, ".claude", "kit.toml"), '[gate]\nci = "bin/ci"\nci_quick = "bin/ci --quick"\n')
        write(os.path.join(self.main, "bin", "ci"), CI, 0o755)
        for name, text in RECIPE.items():
            write(os.path.join(self.main, name), text)
        write(os.path.join(self.main, "lib", "relay_ci.py"), "QUICK_LIMIT_SECONDS = 1800\n")
        self.program = os.path.join(ROOT, "lib", "relay_gate_remote.py")
        write(os.path.join(self.main, "lib", "relay_gate_remote.py"), self.program_text())
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "recipe")
        git(self.wt, "merge", "-q", "--no-edit", "master")
        write(os.path.join(self.home, "keys", "gate-host"), "fake key\n")
        self.host = relay_hosts.Host(HOST, "relay-gate", {})
        relay_hosts.save({HOST: self.host}, self.home)
        patcher = mock.patch.dict(os.environ, {"PATH": self.vps.bin + os.pathsep + os.environ.get("PATH", ""), "RELAY_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env["PATH"] = os.environ["PATH"]
        self.captured = []

    def program_text(self):
        with open(self.program) as handle:
            return handle.read()

    def use_host(self, **values):
        self.host = relay_hosts.Host(HOST, "relay-gate", values)
        return self.host

    def preinstall(self):
        shutil.copy(self.program, os.path.join(self.vps.root, "home", "relay-gate-remote.py"))

    def head(self):
        return git(self.wt, "rev-parse", "HEAD")

    def remote(self, pinned=False):
        """A Remote whose runner is the real ssh transport against the fake host; stderr lines go to self.captured."""
        host = self.host
        return relay_gate.Remote(HOST, lambda worktree, head, command: relay_gate_ssh.gate(host, self.home, worktree, head, command, pinned, notify=self.captured.append))

    def gate(self, **kw):
        return relay_gate.run(self.wt, environ=self.env, quick=True, remote=self.remote(), **kw)

    def tag(self):
        """The image tag by hand: sha256 of "<file>:<blob id on master>" lines, files in name order, first 12 hex."""
        text = "".join("%s:%s\n" % (n, git(self.main, "rev-parse", "master:" + n)) for n in sorted(RECIPE))
        return hashlib.sha256(text.encode()).hexdigest()[:12]
