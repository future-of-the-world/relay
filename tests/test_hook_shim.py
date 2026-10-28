"""Port of plugins/relay/tests/shim.test.sh: templates/kit-shim lets a project script reach `kit` with no PATH help."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import List, Tuple

from hook_helpers import ROOT

CORE = os.path.join(ROOT, "plugins", "relay")
SHIM = os.path.join(CORE, "templates", "kit-shim")
INSTALL_HINT = "claude plugin install core@principles"


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd, check=True, capture_output=True)


class Shim(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = os.path.realpath(tempfile.mkdtemp())
        cls.project = os.path.join(cls.tmp, "project")
        os.makedirs(os.path.join(cls.project, "bin"))
        os.makedirs(os.path.join(cls.project, ".claude"))
        spec = os.path.join(cls.project, "openspec", "specs", "dial")
        os.makedirs(spec)
        shutil.copy(SHIM, os.path.join(cls.project, "bin", "kit"))
        os.chmod(os.path.join(cls.project, "bin", "kit"), 0o755)
        with open(os.path.join(cls.project, ".claude", "kit.toml"), "w") as handle:
            handle.write('[gate]\ncheck = "bin/check"\n')
        with open(os.path.join(spec, "spec.md"), "w") as handle:
            handle.write("## Purpose\nDial.\n\n## Requirements\n\n### Requirement: Spin\nThe dial SHALL spin.\n\n#### Scenario: Fast\n- **WHEN** asked\n- **THEN** it spins\n")
        git(cls.project, "init", "-q", "-b", "master", ".")
        git(cls.project, "add", "-A")
        git(cls.project, "commit", "-q", "-m", "init")
        git(cls.project, "worktree", "add", "-q", ".worktrees/w", "-b", "wt/w")
        os.makedirs(os.path.join(cls.tmp, "home"))
        cls.registry = os.path.join(cls.tmp, "installed_plugins.json")
        with open(cls.registry, "w") as handle:
            json.dump({"version": 2, "plugins": {"relay@amidman": [
                {"scope": "project", "projectPath": os.path.join(cls.tmp, "elsewhere"), "installPath": os.path.join(cls.tmp, "nowhere"), "version": "9.9.9"},
                {"scope": "project", "projectPath": cls.project, "installPath": CORE, "version": "0.1.0"}]}}, handle)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def kit(self, args: List[str], cwd: str = "", **env: str) -> Tuple[int, str]:
        """Run bin/kit with no kit anywhere on PATH: only the python3 that kit needs."""
        pybin = os.path.dirname(os.path.realpath(sys.executable))
        full = {"HOME": os.path.join(self.tmp, "home"), "PATH": "%s:/usr/bin:/bin" % pybin}
        full.update(env)
        exe = "../../bin/kit" if cwd else "bin/kit"
        done = subprocess.run([exe] + args, cwd=cwd or self.project, env=full, capture_output=True, text=True)
        return done.returncode, (done.stdout + done.stderr).strip()

    def test_kit_is_not_on_path(self) -> None:
        pybin = os.path.dirname(os.path.realpath(sys.executable))
        self.assertIsNone(shutil.which("kit", path="%s:/usr/bin:/bin" % pybin))

    def test_registry_get(self) -> None:
        self.assertEqual(self.kit(["get", "gate.check"], KIT_INSTALLED_PLUGINS=self.registry), (0, "bin/check"))

    def test_registry_spec_check_on_sound_and_broken_spec(self) -> None:
        self.assertEqual(self.kit(["spec-check", "--path", "openspec/specs"], KIT_INSTALLED_PLUGINS=self.registry)[0], 0)
        bad = os.path.join(self.project, "openspec", "specs", "bad")
        os.makedirs(bad)
        self.addCleanup(shutil.rmtree, bad, True)
        with open(os.path.join(bad, "spec.md"), "w") as handle:
            handle.write("## Requirements\n\n### Requirement: Broken\nIt does things.\n")
        rc, out = self.kit(["spec-check", "--path", "openspec/specs"], KIT_INSTALLED_PLUGINS=self.registry)
        self.assertEqual(rc, 1)
        self.assertIn("Broken", out)

    def test_registry_from_a_worktree_of_the_project(self) -> None:
        cwd = os.path.join(self.project, ".worktrees", "w")
        self.assertEqual(self.kit(["get", "gate.check"], cwd=cwd, KIT_INSTALLED_PLUGINS=self.registry), (0, "bin/check"))

    def test_source_checkout(self) -> None:
        env = {"KIT_INSTALLED_PLUGINS": os.path.join(self.tmp, "none.json"), "PRINCIPLES_DIR": os.path.join(CORE, "..", "..")}
        self.assertEqual(self.kit(["get", "gate.check"], **env), (0, "bin/check"))

    def test_kit_override(self) -> None:
        self.assertEqual(self.kit(["get", "gate.check"], KIT=os.path.join(CORE, "bin", "kit")), (0, "bin/check"))

    def test_nothing_found_exit_2_and_says_what_to_do(self) -> None:
        rc, out = self.kit(["get", "gate.check"], KIT_INSTALLED_PLUGINS=os.path.join(self.tmp, "none.json"), PRINCIPLES_DIR=os.path.join(self.tmp, "none"))
        self.assertEqual(rc, 2)
        self.assertIn(INSTALL_HINT, out)


if __name__ == "__main__":
    unittest.main()
