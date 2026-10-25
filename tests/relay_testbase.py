"""The base class and paths the library tests share: a temporary claude folder, relay home and projects file for each test."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)


def _drop_relay_modules() -> None:
    for m in list(sys.modules):
        if m.startswith("relay_"):
            del sys.modules[m]


class Base(unittest.TestCase):
    def setUp(self):
        self._saved_env = dict(os.environ)
        self.tmp = tempfile.mkdtemp(prefix="relay-test-")
        self.claude = os.path.join(self.tmp, "claude")
        self.home = os.path.join(self.tmp, "relay-home")
        os.makedirs(self.claude)
        os.environ["CLAUDE_CONFIG_DIR"] = self.claude
        os.environ["RELAY_HOME"] = self.home
        os.environ["RELAY_ROOT"] = ROOT
        projects = os.path.join(self.tmp, "projects.toml")
        self.project_file = os.path.join(self.tmp, "demo", "CLAUDE.local.md")   # never the owner's real project files
        with open(projects, "w") as handle:
            handle.write('[global]\nfile = "~/.claude/CLAUDE.md"\ntitle = "Defaults for all projects"\nintro = "Test."\nload = []\npaid_cap_usd_per_day = 1000\n\n'
                         '[demo]\nfile = "%s"\ntitle = "Principles this project loads"\nload = ["quality-gate"]\nread = []\n' % self.project_file)
        os.environ["RELAY_PROJECTS"] = projects
        _drop_relay_modules()

    def tearDown(self):
        # A test may point RELAY_ROOT at its own fixture (test_roles does); a class that sets nothing runs on what
        # is left behind, so put the environment and the imported relay modules back as they were before setUp.
        os.environ.clear()
        os.environ.update(self._saved_env)
        _drop_relay_modules()
        shutil.rmtree(self.tmp, ignore_errors=True)

