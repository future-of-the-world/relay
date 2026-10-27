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


@unittest.skipUnless(relay_precheck.old_python(), "needs /usr/bin/python3 older than 3.11")
class TestPython39Hooks(Base):
    def test_a_hook_that_cannot_import_fails_naming_it(self) -> None:
        # tomllib is new in 3.11: the hook dies at import on every event. Rule: ImportError / ModuleNotFoundError at import fails;
        # a hook that exits non-zero later (a KeyError in main) is its own business and passes.
        self.write("plugins/core/hooks/new-hook.py", "import tomllib\n")
        self.write("plugins/core/hooks/typing-hook.py", "from typing import TypeGuard\n")
        self.write("plugins/core/hooks/late-hook.py", "import sys\nsys.stdin.read()\n{}['k']\n")
        found = "\n".join(relay_precheck.check_python39(self.repo))
        self.assertIn("plugins/core/hooks/new-hook.py", found)
        self.assertIn("plugins/core/hooks/typing-hook.py", found)
        self.assertNotIn("late-hook", found)

    def test_a_hanging_hook_is_a_red_line_and_later_steps_still_run(self) -> None:
        self.write("plugins/core/hooks/hang.py", "import time\ntime.sleep(60)\n")
        self.commit()
        old = relay_precheck.STEP_TIMEOUT
        relay_precheck.STEP_TIMEOUT = 1
        self.addCleanup(setattr, relay_precheck, "STEP_TIMEOUT", old)
        code, lines = relay_precheck.run(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("RED  python 3.9", lines)
        self.assertIn("  FAIL python 3.9 took longer than 1 s", lines)
        self.assertTrue(any(ln.endswith("lib copies identical") or "lib copies identical" in ln for ln in lines))


class TestRootAndSkips(Base):
    def stale(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/core/lib/relay_q.py", "X = 0\n")
        self.write("tests/keep.txt", "x\n")
        self.commit()

    def test_from_a_subfolder_the_repository_is_checked(self) -> None:
        # F2: git ls-tree from tests/ lists paths relative to it, so the stale copy was never seen
        self.stale()
        code, lines = relay_precheck.run(os.path.join(self.repo, "tests"))
        self.assertEqual(code, 1)
        self.assertTrue(any("plugins/core/lib/relay_q.py" in ln for ln in lines))

    def test_from_a_subfolder_identical_copies_are_green(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/core/lib/relay_q.py", "X = 1\n")
        self.write("tests/keep.txt", "x\n")
        self.commit()
        code, lines = relay_precheck.run(os.path.join(self.repo, "tests"))
        self.assertEqual(code, 0, lines)
        self.assertIn("ok   lib copies identical", lines)

    def test_outside_a_repository_head_cannot_be_read(self) -> None:
        plain = tempfile.mkdtemp(prefix="precheck-plain-")
        self.addCleanup(shutil.rmtree, plain, True)
        code, lines = relay_precheck.run(plain)
        self.assertEqual(code, 1)
        self.assertTrue(any("cannot read HEAD" in ln for ln in lines))

    def test_a_step_with_nothing_to_check_says_skip_not_ok(self) -> None:
        # F9
        self.write("README", "x\n")
        self.commit()
        code, lines = relay_precheck.run(self.repo)
        self.assertEqual(code, 0, lines)
        self.assertFalse([ln for ln in lines if ln.startswith("ok   python") or ln.startswith("ok   lib copies")], lines)
        self.assertTrue(any(ln.startswith("skip lib copies identical") for ln in lines), lines)
        if relay_precheck.old_python():
            self.assertTrue(any(ln.startswith("skip python 3.9") for ln in lines), lines)

    def test_a_checked_copy_is_still_ok(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/core/lib/relay_q.py", "X = 1\n")
        self.commit()
        self.assertIn("ok   lib copies identical", relay_precheck.run(self.repo)[1])


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


class BriefTemplateNamesPrecheck(unittest.TestCase):
    def test_the_delegate_check_line_names_precheck_for_projects_with_relay_only(self) -> None:
        # F4: the template line a worker brief takes its quiet check from names `relay precheck -C` first, and only where
        # the project has `.relay/` (a project without it is not told to run it)
        with open(os.path.join(ROOT, "plugins", "delegate", "skills", "delegate", "SKILL.md"), encoding="utf-8") as handle:
            lines = [ln for ln in handle if ln.startswith("Check: ")]
        self.assertEqual(len(lines), 1)
        self.assertIn("relay precheck -C <worktree> && (<command>)", lines[0])
        self.assertIn("project with `.relay/`", lines[0])
