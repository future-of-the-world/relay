"""`relay precheck`: the gate's seconds-long steps, read-only, before the gate (speed approach A; queue item
a-fix-to-lib-leaves-the-plugins-copies-stale). Every repo here is a temporary one."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_precheck  # noqa: E402

RELAY = os.path.join(ROOT, "bin", "relay")


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = tempfile.mkdtemp(prefix="precheck-test-")
        self.addCleanup(shutil.rmtree, self.repo, True)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")

    def write(self, rel: str, text: str) -> None:
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def commit(self) -> None:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "x")


class TestLibCopies(Base):
    def setUp(self) -> None:
        super().setUp()
        for rel in ("lib/relay_q.py", "plugins/core/lib/relay_q.py", "plugins/front/lib/relay_q.py"):
            self.write(rel, "X = 1\n")
        self.write("prices.toml", "a = 1\n")
        self.write("plugins/core/lib/prices.toml", "a = 1\n")
        self.commit()

    def test_identical_copies_are_clean(self) -> None:
        self.assertEqual(relay_precheck.check_lib_copies(self.repo), [])

    def test_a_stale_copy_names_the_copy_and_the_sync_command_and_nothing_is_written(self) -> None:
        # lib/ edited and committed, copies left behind: the case of the queue item. The gate would go red on it.
        self.write("lib/relay_q.py", "X = 2\n")
        self.commit()
        before = git(self.repo, "status", "--porcelain") + git(self.repo, "rev-parse", "HEAD")
        found = relay_precheck.check_lib_copies(self.repo)
        # both copies differ from lib/, in the gate's plugin order (front before core)
        self.assertEqual(len(found), 2)
        self.assertIn("plugins/front/lib/relay_q.py", found[0])
        self.assertIn("plugins/core/lib/relay_q.py", found[1])
        self.assertIn("bin/sync-lib-copies", found[0])
        self.assertEqual(git(self.repo, "status", "--porcelain") + git(self.repo, "rev-parse", "HEAD"), before)
        with open(os.path.join(self.repo, "plugins/core/lib/relay_q.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "X = 1\n")

    def test_copies_synced_but_not_committed_still_fail(self) -> None:
        # the gate gates HEAD: a refreshed working copy that is not committed is still red there
        self.write("lib/relay_q.py", "X = 2\n")
        self.commit()
        for rel in ("plugins/core/lib/relay_q.py", "plugins/front/lib/relay_q.py"):
            self.write(rel, "X = 2\n")
        self.assertEqual(len(relay_precheck.check_lib_copies(self.repo)), 2)
        self.commit()
        self.assertEqual(relay_precheck.check_lib_copies(self.repo), [])

    def test_a_stale_prices_copy_fails(self) -> None:
        self.write("prices.toml", "a = 2\n")
        self.commit()
        found = relay_precheck.check_lib_copies(self.repo)
        self.assertEqual(len(found), 1)
        self.assertIn("plugins/core/lib/prices.toml", found[0])


class TestTypesStep(Base):
    def script(self, body: str) -> None:
        self.write("bin/types-lint", "#!/usr/bin/env bash\n" + body)
        path = os.path.join(self.repo, "bin", "types-lint")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def test_a_red_types_step_fails_precheck_with_its_output(self) -> None:
        self.script('echo "bin/relay:9: error: Too many arguments"; exit 1\n')
        found = relay_precheck.check_types(self.repo)
        self.assertEqual(found[0], "FAIL types and lint (bin/types-lint):")
        self.assertIn("bin/relay:9: error: Too many arguments", found[1])

    def test_a_clean_types_step_is_clean_and_a_missing_one_says_so(self) -> None:
        self.script("exit 0\n")
        self.assertEqual(relay_precheck.check_types(self.repo), [])
        os.remove(os.path.join(self.repo, "bin", "types-lint"))
        self.assertEqual(relay_precheck.check_types(self.repo), ["skipped: no bin/types-lint here"])


@unittest.skipUnless(relay_precheck.old_python(), "needs /usr/bin/python3 older than 3.11")
class TestPython39(Base):
    def test_a_module_that_needs_a_newer_python_fails(self) -> None:
        # `match` is a syntax error before 3.10, which mypy's python_version setting cannot see
        self.write("plugins/core/lib/relay_new.py", "def f(x):\n    match x:\n        case 1:\n            return 2\n")
        found = relay_precheck.check_python39(self.repo)
        self.assertIn("plugins/core/lib/relay_new.py", found[0])

    def test_a_plain_module_is_clean(self) -> None:
        self.write("plugins/core/lib/relay_ok.py", "X = 1\n")
        self.assertEqual(relay_precheck.check_python39(self.repo), [])


class TestCommand(Base):
    def test_run_reports_every_step_and_exits_1_when_one_is_red(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/core/lib/relay_q.py", "X = 1\n")
        self.commit()
        self.write("lib/relay_q.py", "X = 2\n")
        self.commit()
        code, lines = relay_precheck.run(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("RED  lib copies identical", lines)
        self.assertTrue(lines[-1].startswith("precheck: RED"))

    def test_the_relay_command_runs_it_and_passes_the_exit_code(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/core/lib/relay_q.py", "X = 0\n")
        self.commit()
        done = subprocess.run([sys.executable, RELAY, "precheck", "-C", self.repo], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("plugins/core/lib/relay_q.py", done.stdout)
        self.assertIn("bin/sync-lib-copies", done.stdout)


if __name__ == "__main__":
    unittest.main()
