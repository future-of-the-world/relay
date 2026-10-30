"""The base class and paths the library tests share: a temporary claude folder, relay home and projects file for each test."""
import os
import shutil
import sys
import tempfile
import types
import unittest
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)


def _drop_relay_modules() -> None:
    for m in list(sys.modules):
        if m.startswith("relay_"):
            del sys.modules[m]


def load_hook(name: str, path: str) -> types.ModuleType:
    """Run a plugin hook file as a module without leaving its import side effects behind.

    A hook puts its plugin's lib copy first on sys.path and imports relay_* modules from there. Left in sys.modules,
    a copy such as plugins/delegate/lib/relay_config.py makes its ROOT the plugin folder, and a later test that imports
    lib/relay_license finds no data/licenses. So sys.path is put back and the modules the hook added are dropped."""
    saved_path = list(sys.path)
    before = set(sys.modules)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = saved_path
        plugins = os.path.join(ROOT, "plugins") + os.sep
        for added in set(sys.modules) - before:
            file = getattr(sys.modules[added], "__file__", None) or ""
            if added.startswith("relay_") or file.startswith(plugins):   # the hook's copies only; stdlib stays
                del sys.modules[added]


def shipped_specs() -> dict:
    """What the registry holds on a fresh machine (relay's shipped defaults) plus relay's own entry, whose settings
    are in this repository's .claude/kit.toml [rules]: the targets the tests of relay's own rules look at."""
    import relay_config
    data = relay_config.read_toml(os.path.join(ROOT, "defaults", "projects.toml"))
    own = relay_config.read_toml(os.path.join(ROOT, ".claude", "kit.toml"))["rules"]
    data["relay"] = dict(own, file=os.path.join(ROOT, "CLAUDE.local.md"), title="Principles this project loads")
    return data


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
        self._saved_modules = {m: sys.modules[m] for m in sys.modules if m.startswith("relay_")}
        _drop_relay_modules()

    def tearDown(self):
        # A test may point RELAY_ROOT at its own fixture (test_roles does); a class that sets nothing runs on what
        # is left behind, so put the environment and the imported relay modules back as they were before setUp.
        os.environ.clear()
        os.environ.update(self._saved_env)
        _drop_relay_modules()
        sys.modules.update(self._saved_modules)   # the very objects other test modules hold (tq.rq, rl), not fresh copies
        shutil.rmtree(self.tmp, ignore_errors=True)

