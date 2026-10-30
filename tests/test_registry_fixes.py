"""Review fixes for the registry move: F2 (cap lands in the registry in RELAY_HOME) and F4 (move race)."""
import os, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_config  # noqa: E402
import relay_paidcap  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
