"""Port of plugins/relay/tests/kit.test.sh: `kit get`, `kit dump` and `kit path`."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import List, Tuple

from hook_helpers import ROOT, SoftCases

PLUGINS = os.path.join(ROOT, "plugins")
KIT = os.path.join(PLUGINS, "relay", "bin", "kit")
KIT_TOML = '[gate]\ncheck = "bin/check"\n[project]\nstack_skills = ["a","b"]\nok = true\n[x]\ny = 1\n'


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd, check=True, capture_output=True)


class KitBase(SoftCases):
    def setUp(self) -> None:
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        git(self.tmp, "init", "-q", "-b", "master", ".")
        git(self.tmp, "commit", "-q", "--allow-empty", "-m", "i")
        self.registry = os.path.join(self.tmp, "no-such-registry.json")

    def kit(self, args: List[str], cwd: str = "", kit: str = KIT, python: str = "") -> Tuple[int, str]:
        env = dict(os.environ, KIT_INSTALLED_PLUGINS=self.registry)
        cmd = ([python] if python else []) + [kit] + args
        done = subprocess.run(cmd, cwd=cwd or self.tmp, env=env, capture_output=True, text=True)
        return done.returncode, done.stdout.strip() if done.returncode == 0 else (done.stdout + done.stderr).strip()

    def write_toml(self, text: str = KIT_TOML) -> None:
        os.makedirs(os.path.join(self.tmp, ".claude"), exist_ok=True)
        with open(os.path.join(self.tmp, ".claude", "kit.toml"), "w") as handle:
            handle.write(text)


class NoFile(KitBase):
    def test_no_file_is_an_error_naming_the_next_step(self) -> None:
        want = "kit: no .claude/kit.toml in %s: this project has no bindings file (on a worktree branch, merge the default branch in first)" % self.tmp
        self.assertEqual(self.kit(["get", "gate.check"]), (1, want))
        # --default does not cover a missing file
        self.assertEqual(self.kit(["get", "--default", "x", "gate.check"]), (1, want))
        for args in (["dump"], ["packet", "--check", "demo"], ["spec-check", "--path", "."]):
            self.assertEqual(self.kit(args)[0], 1, args)


class WithFile(KitBase):
    def setUp(self) -> None:
        super().setUp()
        self.write_toml()

    def test_values(self) -> None:
        self.assertEqual(self.kit(["get", "gate.check"]), (0, "bin/check"))
        self.assertEqual(self.kit(["get", "project.stack_skills"]), (0, "a\nb"))
        self.assertEqual(self.kit(["get", "project.ok"]), (0, "true"))
        self.assertEqual(self.kit(["get", "x"]), (0, '{"y": 1}'))

    def test_missing_key_and_default(self) -> None:
        self.assertEqual(self.kit(["get", "gate.ci"]), (1, "kit: missing key 'gate.ci' (no such key in %s/.claude/kit.toml)" % self.tmp))
        self.assertEqual(self.kit(["get", "--default", "none", "gate.ci"]), (0, "none"))
        self.assertEqual(self.kit(["get", "--default", "none", "gate.check"]), (0, "bin/check"))
        self.assertEqual(self.kit(["get"])[0], 2)  # no key: usage

    def test_broken_file_exits_2_naming_kit(self) -> None:
        self.write_toml("[gate\n")
        rc, out = self.kit(["get", "gate.check"])
        self.assertEqual(rc, 2)
        self.assertTrue(out.startswith("kit:"))

    def test_worktree_uses_its_own_file_which_it_lacks(self) -> None:
        git(self.tmp, "worktree", "add", "-q", ".wt/a", "-b", "wt/a")  # a worktree of a commit without the (untracked) file
        sub = os.path.join(self.tmp, ".wt", "a", "sub")
        os.makedirs(sub)
        rc, out = self.kit(["get", "gate.check"], cwd=sub)
        self.assertEqual(rc, 1)
        self.assertIn(os.path.join(self.tmp, ".wt", "a"), out)

    def test_dump(self) -> None:
        rc, out = self.kit(["dump"])
        self.assertEqual((rc, json.loads(out)["gate"]), (0, {"check": "bin/check"}))

    @unittest.skipUnless(os.access("/usr/bin/python3", os.X_OK), "no system python")
    def test_system_python_without_tomllib(self) -> None:
        py = "/usr/bin/python3"
        self.assertEqual(self.kit(["get", "gate.check"], python=py), (0, "bin/check"))
        self.assertEqual(self.kit(["get", "project.stack_skills"], python=py), (0, "a\nb"))
        self.assertEqual(json.loads(self.kit(["dump"], python=py)[1])["gate"], {"check": "bin/check"})
        self.write_toml("[gate\n")
        self.assertEqual(self.kit(["get", "gate.check"], python=py)[0], 2)


class Path(KitBase):
    def setUp(self) -> None:
        super().setUp()
        self.write_toml()

    def test_source_layout(self) -> None:
        self.assertEqual(self.kit(["path", "openspec/flow.json"]), (0, os.path.join(PLUGINS, "openspec", "flow.json")))
        self.assertEqual(self.kit(["path", "relay/lib/kit_packet.py"]), (0, os.path.join(PLUGINS, "relay", "lib", "kit_packet.py")))
        rc, out = self.kit(["path", "openspec/nope"])
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("kit: no file 'opensp"))
        self.assertEqual(self.kit(["path", "openspec/../relay/bin/kit"])[0], 1)  # no escape

    def test_installed_layout_picks_the_version_for_this_project(self) -> None:
        inst = os.path.join(self.tmp, "market")
        for v in ("0.1.0", "0.2.0", "0.10.0"):
            skill = os.path.join(inst, "openspec", v, "skills", "x")
            os.makedirs(skill)
            with open(os.path.join(skill, "SKILL.md"), "w") as handle:
                handle.write(v + "\n")
        core = os.path.join(inst, "core", "0.1.0")
        os.makedirs(core)
        for sub in ("bin", "lib"):
            shutil.copytree(os.path.join(PLUGINS, "relay", sub), os.path.join(core, sub))
        ikit = os.path.join(core, "bin", "kit")
        want = lambda v: os.path.join(inst, "openspec", v, "skills", "x", "SKILL.md")  # noqa: E731
        ask = ["path", "openspec/skills/x/SKILL.md"]
        # no registry: the same version as the running core
        self.assertEqual(self.kit(ask, kit=ikit), (0, want("0.1.0")))
        self.registry = os.path.join(self.tmp, "installed_plugins.json")
        other = os.path.join(self.tmp, "other-project")

        def register(entries: list) -> None:
            with open(self.registry, "w") as handle:
                json.dump({"version": 2, "plugins": {"openspec@market": entries}}, handle)

        user02 = {"scope": "user", "installPath": os.path.join(inst, "openspec", "0.2.0"), "version": "0.2.0"}
        other010 = {"scope": "project", "projectPath": other, "installPath": os.path.join(inst, "openspec", "0.10.0"), "version": "0.10.0"}
        mine01 = {"scope": "project", "projectPath": self.tmp, "installPath": os.path.join(inst, "openspec", "0.1.0"), "version": "0.1.0"}
        register([user02, other010, mine01])  # this project's own install wins over newer ones
        self.assertEqual(self.kit(ask, kit=ikit), (0, want("0.1.0")))
        git(self.tmp, "worktree", "add", "-q", ".wt/a", "-b", "wt/a")
        self.assertEqual(self.kit(ask, cwd=os.path.join(self.tmp, ".wt", "a"), kit=ikit), (0, want("0.1.0")))
        register([other010, user02])  # another project's install is not used; the user-scope one is
        self.assertEqual(self.kit(ask, kit=ikit), (0, want("0.2.0")))
        with open(self.registry, "w") as handle:
            json.dump({"version": 2, "plugins": {}}, handle)  # empty registry: the core's own version
        self.assertEqual(self.kit(ask, kit=ikit), (0, want("0.1.0")))
        shutil.rmtree(os.path.join(inst, "openspec", "0.1.0"))  # nothing for this version: an error, not the newest
        rc, out = self.kit(ask, kit=ikit)
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith("kit: no file 'opensp"))


if __name__ == "__main__":
    unittest.main()
