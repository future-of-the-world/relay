"""Review fixes for the registry move: F2 (cap lands in the registry in RELAY_HOME) and F4 (move race)."""
import os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_config  # noqa: E402
import relay_paidcap  # noqa: E402
import relay_rules  # noqa: E402
import relay_setup  # noqa: E402

BIN = os.path.join(ROOT, "bin", "paid-cost")
TOML = '[global]\ntitle = "t"\npaid_cap_usd_per_day = 200   # the owner cap\n'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.root = os.path.join(self.tmp.name, "checkout")
        os.makedirs(self.home)
        os.makedirs(self.root)
        with open(os.path.join(self.home, "projects.toml"), "w") as f:
            f.write(TOML)

    def run_cap(self, *args, projects=None):
        env = dict(os.environ, RELAY_HOME=self.home, RELAY_ROOT=self.root)
        env.pop("RELAY_PROJECTS", None)
        if projects:
            env["RELAY_PROJECTS"] = projects
        return subprocess.run([sys.executable, BIN, "cap", *args], capture_output=True, text=True, env=env)


class CapInRegistry(Base):
    def test_cap_300_is_read_back_from_the_home_registry(self):
        # Failing case F2: before the fix the cap was committed to a tracked file nobody reads; the home copy stayed 200.
        done = self.run_cap("300")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "300"), done.stderr)
        self.assertEqual(self.run_cap().stdout.strip(), "300")
        with mock.patch.dict(os.environ, {"RELAY_HOME": self.home, "RELAY_ROOT": self.root}):
            os.environ.pop("RELAY_PROJECTS", None)
            self.assertEqual(relay_paidcap.cap(), 300.0)
        self.assertEqual(os.listdir(self.root), [])   # the checkout is not touched

    def test_cap_with_relay_projects_writes_that_file(self):
        p = os.path.join(self.tmp.name, "p.toml")
        with open(p, "w") as f:
            f.write(TOML)
        self.assertEqual(self.run_cap("250", projects=p).stdout.strip(), "250")
        self.assertIn("paid_cap_usd_per_day = 250", open(p).read())

    def test_cap_zero_is_refused(self):
        done = self.run_cap("0")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("the cap must be above 0", done.stderr + done.stdout)


class MoveRace(Base):
    def test_old_file_gone_between_check_and_move_returns_target(self):
        # Failing case F4: another process moved the file after our isfile checks; shutil.move raised FileNotFoundError.
        os.remove(os.path.join(self.home, "projects.toml"))
        old = os.path.join(self.root, "projects.toml")
        with open(old, "w") as f:
            f.write(TOML)
        with mock.patch.dict(os.environ, {"RELAY_HOME": self.home}), \
                mock.patch.object(relay_config, "LEGACY_PROJECTS", old), \
                mock.patch.object(relay_config.shutil, "move", side_effect=FileNotFoundError):
            os.environ.pop("RELAY_PROJECTS", None)
            self.assertEqual(relay_config.projects_file(), os.path.join(self.home, "projects.toml"))


class SplitRegistry(unittest.TestCase):
    """Owner answer a: owner settings and the project list in RELAY_HOME, a project's own settings in its git."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_first_command_in_a_git_checkout_leaves_it_clean(self) -> None:
        # F1 failing case: a fresh machine, relay in a real git checkout; the first command used to write projects.toml
        # (or fail on a missing one). Now the registry is made in RELAY_HOME from the shipped defaults.
        checkout, home = os.path.join(self.tmp.name, "relay"), os.path.join(self.tmp.name, "home")
        for sub in ("bin", "lib", "defaults"):
            shutil.copytree(os.path.join(ROOT, sub), os.path.join(checkout, sub), ignore=shutil.ignore_patterns("__pycache__"))
        git = lambda *a: subprocess.run(["git", "-C", checkout, *a], capture_output=True, text=True, check=True).stdout  # noqa: E731
        git("init", "-q")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
        env = {k: v for k, v in os.environ.items() if not k.startswith("RELAY_")}
        env.update(RELAY_HOME=home, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, os.path.join(checkout, "bin", "paid-cost"), "cap"], capture_output=True, text=True, env=env)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "200"), done.stderr)   # 200: the shipped default
        self.assertTrue(os.path.isfile(os.path.join(home, "projects.toml")))
        self.assertEqual(git("status", "--porcelain"), "")

    def test_a_project_s_lanes_and_load_come_from_its_own_kit_toml(self) -> None:
        # Q1 failing case: lanes and load for a registered project are read from <project>/.claude/kit.toml [rules]
        proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(os.path.join(proj, ".claude"))
        with open(os.path.join(proj, ".claude", "kit.toml"), "w") as f:
            f.write('[rules]\nlanes = 7\nload = ["principles"]\n')
        reg = os.path.join(self.tmp.name, "reg.toml")
        with open(reg, "w") as f:
            f.write(TOML.replace("[global]\n", '[global]\nfile = "/x/CLAUDE.md"\n') + f'[proj]\nfile = "{proj}/CLAUDE.local.md"\ntitle = "t"\n')
        with mock.patch.dict(os.environ, {"RELAY_PROJECTS": reg}):
            spec = relay_rules.targets()["proj"]
        self.assertEqual((spec["lanes"], spec["load"]), (7, ["principles"]))
        self.assertNotIn("lanes =", open(reg).read())

    def test_register_project_puts_the_rules_in_the_project(self) -> None:
        proj, home = os.path.join(self.tmp.name, "proj"), os.path.join(self.tmp.name, "home")
        os.makedirs(os.path.join(proj, ".claude"))
        open(os.path.join(proj, ".claude", "kit.toml"), "w").write("[gate]\n")
        with mock.patch.dict(os.environ, {"RELAY_HOME": home}):
            os.environ.pop("RELAY_PROJECTS", None)
            self.assertTrue(relay_setup.register_project("proj", proj, ui=True))
            reg = open(relay_config.projects_file()).read()
        self.assertIn("[proj]", reg)
        self.assertNotIn("product-work", reg)
        self.assertIn('load = ["product-work"]', open(os.path.join(proj, ".claude", "kit.toml")).read())

    def test_old_registry_in_the_checkout_moves_and_relay_s_part_goes_to_kit_toml(self) -> None:
        root, home = os.path.join(self.tmp.name, "checkout"), os.path.join(self.tmp.name, "home")
        os.makedirs(root)
        with open(os.path.join(root, "projects.toml"), "w") as f:
            f.write(TOML + f'[relay]\nfile = "{root}/CLAUDE.local.md"\ntitle = "t"\nlanes = 6\nload = ["principles"]\nread = []\n')
        with mock.patch.dict(os.environ, {"RELAY_HOME": home}), mock.patch.object(relay_config, "ROOT", root), \
                mock.patch.object(relay_config, "LEGACY_PROJECTS", os.path.join(root, "projects.toml")):
            os.environ.pop("RELAY_PROJECTS", None)
            target = relay_config.projects_file()
        self.assertIn("[global]", open(target).read())
        kit = relay_config.read_toml(os.path.join(root, ".claude", "kit.toml"))
        self.assertEqual(kit["rules"], {"lanes": 6, "load": ["principles"], "read": []})
        self.assertFalse(os.path.exists(os.path.join(root, "projects.toml")))


if __name__ == "__main__":
    unittest.main()
