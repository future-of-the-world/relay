"""relay setup run in a linked worktree writes nothing outside that worktree: the trailing rules sync does not rewrite
the main checkout's CLAUDE.local.md, and a sync held by a waiting paid run does not make setup exit 1."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import Base, ROOT  # noqa: E402

RELAY_BIN = os.path.join(ROOT, "bin", "relay")


def git(*args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


class WorktreeSetup(Base):
    def make(self) -> tuple[str, str]:
        """A temporary main checkout `proj` with a linked worktree; projects.toml has a [proj] target at the main checkout."""
        main = os.path.join(self.tmp, "proj")
        os.makedirs(main)
        git("init", "-q", main)
        git("-C", main, "commit", "-q", "--allow-empty", "-m", "init")
        wt = os.path.join(self.tmp, "proj-wt")
        git("-C", main, "worktree", "add", "-q", wt, "-b", "wt/x")
        target = os.path.join(main, "CLAUDE.local.md")
        with open(target, "w") as handle:
            handle.write("hand written, sync must not touch this\n")
        with open(os.environ["RELAY_PROJECTS"], "a") as handle:
            handle.write('\n[proj]\nfile = "%s"\ntitle = "t"\nload = ["quality-gate"]\nread = []\n' % target)
        return main, wt

    def run_setup(self, folder: str, **extra: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, RELAY_SKIP_PAID_DUE="1", **extra)
        return subprocess.run([sys.executable, RELAY_BIN, "setup", folder], env=env, capture_output=True, text=True)

    def test_main_checkout_file_is_untouched(self) -> None:
        main, wt = self.make()
        target = os.path.join(main, "CLAUDE.local.md")
        done = self.run_setup(wt)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(target) as handle:
            self.assertEqual(handle.read(), "hand written, sync must not touch this\n")   # byte-identical
        self.assertIn("Not synced from a worktree", done.stdout)
        # sync reads the main checkout's kit.toml, so it counts only once this branch is merged (finding F2)
        self.assertIn("after this branch is merged", done.stdout)
        self.assertNotIn("from " + main, done.stdout)

    def test_main_checkout_setup_still_syncs(self) -> None:
        main, _ = self.make()
        done = self.run_setup(main)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(main, "CLAUDE.local.md")) as handle:
            self.assertNotIn("hand written", handle.read())   # the unchanged behaviour outside a worktree

    def test_held_sync_exits_zero(self) -> None:
        main, _ = self.make()
        # a held sync is simulated through the sitecustomize-free route: a wrapper script that makes sync raise Held
        code = ("import sys, runpy; sys.path.insert(0, %r); import relay_rules\n"
                "def held(*a, **k): raise relay_rules.Held('abc123 something merged')\n"
                "relay_rules.sync = held\n"
                "sys.argv = [%r, 'setup', %r]\n"
                "runpy.run_path(%r, run_name='__main__')\n") % (os.path.join(ROOT, "lib"), RELAY_BIN, main, RELAY_BIN)
        done = subprocess.run([sys.executable, "-c", code], env=dict(os.environ, RELAY_SKIP_PAID_DUE="1"), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Not synced", done.stderr)


if __name__ == "__main__":
    unittest.main()
