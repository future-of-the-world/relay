"""`relay precheck`: the gate's seconds-long steps, read-only, before the gate (speed approach A; queue item
a-fix-to-lib-leaves-the-plugins-copies-stale). Every repo here is a temporary one."""
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_precheck  # noqa: E402
import relay_tokens  # noqa: E402

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
        for rel in ("lib/relay_q.py", "plugins/relay/lib/relay_q.py", "plugins/front/lib/relay_q.py"):
            self.write(rel, "X = 1\n")
        self.write("prices.toml", "a = 1\n")
        self.write("plugins/relay/lib/prices.toml", "a = 1\n")
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
        self.assertIn("plugins/relay/lib/relay_q.py", found[1])
        self.assertIn("bin/sync-lib-copies", found[0])
        self.assertEqual(git(self.repo, "status", "--porcelain") + git(self.repo, "rev-parse", "HEAD"), before)
        with open(os.path.join(self.repo, "plugins/relay/lib/relay_q.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "X = 1\n")

    def test_copies_synced_but_not_committed_still_fail(self) -> None:
        # the gate gates HEAD: a refreshed working copy that is not committed is still red there
        self.write("lib/relay_q.py", "X = 2\n")
        self.commit()
        for rel in ("plugins/relay/lib/relay_q.py", "plugins/front/lib/relay_q.py"):
            self.write(rel, "X = 2\n")
        self.assertEqual(len(relay_precheck.check_lib_copies(self.repo)), 2)
        self.commit()
        self.assertEqual(relay_precheck.check_lib_copies(self.repo), [])

    def test_a_stale_prices_copy_fails(self) -> None:
        self.write("prices.toml", "a = 2\n")
        self.commit()
        found = relay_precheck.check_lib_copies(self.repo)
        self.assertEqual(len(found), 1)
        self.assertIn("plugins/relay/lib/prices.toml", found[0])


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
        self.write("plugins/relay/lib/relay_new.py", "def f(x):\n    match x:\n        case 1:\n            return 2\n")
        found = relay_precheck.check_python39(self.repo)
        self.assertIn("plugins/relay/lib/relay_new.py", found[0])

    def test_a_plain_module_is_clean(self) -> None:
        self.write("plugins/relay/lib/relay_ok.py", "X = 1\n")
        self.assertEqual(relay_precheck.check_python39(self.repo), [])


@unittest.skipUnless(relay_precheck.old_python(), "needs /usr/bin/python3 older than 3.11")
class TestPython39Hooks(Base):
    def test_a_hook_that_cannot_import_fails_naming_it(self) -> None:
        # tomllib is new in 3.11: the hook dies at import on every event. Rule: ImportError / ModuleNotFoundError at import fails;
        # a hook that exits non-zero later (a KeyError in main) is its own business and passes.
        self.write("plugins/relay/hooks/new-hook.py", "import tomllib\n")
        self.write("plugins/relay/hooks/typing-hook.py", "from typing import TypeGuard\n")
        self.write("plugins/relay/hooks/late-hook.py", "import sys\nsys.stdin.read()\n{}['k']\n")
        found = "\n".join(relay_precheck.check_python39(self.repo))
        self.assertIn("plugins/relay/hooks/new-hook.py", found)
        self.assertIn("plugins/relay/hooks/typing-hook.py", found)
        self.assertNotIn("late-hook", found)

    def test_a_hanging_hook_is_a_red_line_and_later_steps_still_run(self) -> None:
        self.write("plugins/relay/hooks/hang.py", "import time\ntime.sleep(60)\n")
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
        self.write("plugins/relay/lib/relay_q.py", "X = 0\n")
        self.write("tests/keep.txt", "x\n")
        self.commit()

    def test_from_a_subfolder_the_repository_is_checked(self) -> None:
        # F2: git ls-tree from tests/ lists paths relative to it, so the stale copy was never seen
        self.stale()
        code, lines = relay_precheck.run(os.path.join(self.repo, "tests"))
        self.assertEqual(code, 1)
        self.assertTrue(any("plugins/relay/lib/relay_q.py" in ln for ln in lines))

    def test_from_a_subfolder_identical_copies_are_green(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/relay/lib/relay_q.py", "X = 1\n")
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
        self.write("plugins/relay/lib/relay_q.py", "X = 1\n")
        self.commit()
        self.assertIn("ok   lib copies identical", relay_precheck.run(self.repo)[1])


class TestChangedTests(Base):
    """The gate runs every library test under plain python3 (tests/run_unittest.py) and the registry test; precheck runs the
    changed ones the same way (queue item precheck-misses-tests-the-gate-runs-differently)."""

    def setUp(self) -> None:
        super().setUp()
        git(self.repo, "branch", "-M", "master")
        os.makedirs(os.path.join(self.repo, "tests"), exist_ok=True)
        for name in ("run_unittest.py", "leaked_gates.py", "tmp_default.py"):
            shutil.copy(os.path.join(ROOT, "tests", name), os.path.join(self.repo, "tests", name))
        os.makedirs(os.path.join(self.repo, "lib"), exist_ok=True)
        for name in sorted(n for n in os.listdir(os.path.join(ROOT, "lib")) if n.endswith(".py")):   # run_unittest imports relay_tokens -> relay_gate -> a chain of lib modules: the whole lib
            shutil.copy(os.path.join(ROOT, "lib", name), os.path.join(self.repo, "lib", name))
        self.write("tests/__init__.py", "")
        # a stand-in for the registry test: red while rules/unlisted exists, as RuleTestsComplete is red for an unlisted reader
        self.write("tests/test_rules_gate.py", "import os, unittest\nROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
                   "class RuleTestsComplete(unittest.TestCase):\n    def test_x(self):\n"
                   "        self.assertFalse(os.path.exists(os.path.join(ROOT, 'unlisted')))\n")
        self.commit()
        git(self.repo, "checkout", "-q", "-b", "wt/task")

    def test_a_changed_test_importing_a_module_the_gate_lacks_is_red(self) -> None:
        # f8b4fee: tests imported pytest, which pytest has but plain python3 has not. Here the module is one nobody has.
        self.write("tests/test_new.py", "import not_installed_anywhere_xyz\n")
        self.commit()
        found = "\n".join(relay_precheck.check_changed_tests(self.repo))
        self.assertIn("FAIL changed tests", found)
        self.assertIn("not_installed_anywhere_xyz", found)

    def test_the_registry_test_runs_and_its_message_shows(self) -> None:
        # 4ba4199: a changed test is fine alone, but the registry test is red; precheck shows the registry's own message
        self.write("tests/test_new.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
        self.write("unlisted", "x")
        self.commit()
        found = "\n".join(relay_precheck.check_changed_tests(self.repo))
        self.assertIn("RuleTestsComplete", found)

    def test_a_passing_changed_test_is_clean(self) -> None:
        self.write("tests/test_new.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
        self.commit()
        self.assertEqual(relay_precheck.check_changed_tests(self.repo), [])

    def test_a_branch_without_test_changes_still_runs_only_the_registry_test(self) -> None:
        # no changed test: only the registry test runs (0.6 s measured), so a slow changed-test run costs nothing here
        self.write("unlisted", "x")
        self.commit()
        found = "\n".join(relay_precheck.check_changed_tests(self.repo))
        self.assertIn("RuleTestsComplete", found)
        self.assertNotIn("test_new", found)

    def test_a_branch_without_test_changes_and_a_green_registry_is_clean(self) -> None:
        self.write("README", "x")
        self.commit()
        self.assertEqual(relay_precheck.check_changed_tests(self.repo), [])

    def test_no_test_runner_says_skip(self) -> None:
        os.remove(os.path.join(self.repo, "tests", "run_unittest.py"))
        self.assertEqual(relay_precheck.check_changed_tests(self.repo), ["skipped: no tests/run_unittest.py here"])

    def test_an_uncommitted_edit_and_a_new_test_count_and_a_deleted_one_does_not(self) -> None:
        # F4: a tracked test edited but not committed is the worker's usual state while looping
        git(self.repo, "checkout", "-q", "master")
        self.write("tests/test_kept.py", "x = 1\n")
        self.write("tests/test_gone.py", "x = 1\n")
        self.commit()
        git(self.repo, "checkout", "-q", "wt/task")
        git(self.repo, "merge", "-q", "master")
        self.write("tests/test_kept.py", "x = 2\n")
        os.remove(os.path.join(self.repo, "tests", "test_gone.py"))
        self.write("tests/test_untracked.py", "x = 1\n")
        self.assertEqual(relay_precheck.changed_test_modules(self.repo), ["tests.test_kept", "tests.test_untracked"])

    SLEEPER = "import time, unittest\nclass T(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(%d)\n"

    def _set(self, name: str, value: int) -> None:
        self.addCleanup(setattr, relay_precheck, name, getattr(relay_precheck, name))
        setattr(relay_precheck, name, value)

    def test_a_changed_test_too_slow_for_the_step_is_a_red_line(self) -> None:
        self.write("tests/test_slow.py", self.SLEEPER % 60)
        self.commit()
        self._set("CHANGED_TESTS_TIMEOUT", 2)
        code, lines = relay_precheck.run(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("RED  changed tests", lines)
        self.assertIn("  FAIL changed tests took longer than 2 s", lines)   # the budget actually used

    def test_a_changed_test_slower_than_the_other_steps_budget_is_green(self) -> None:
        # F1: the changed-tests step has its own budget; a green test that takes 3 s passes although STEP_TIMEOUT is 1 s
        self.write("tests/test_slow.py", self.SLEEPER % 3)
        self.commit()
        self._set("STEP_TIMEOUT", 1)
        # the step keeps its own default budget (600 s): a 60 s one went red when the gate ran at load 50 and python took over a minute to start
        self.assertGreater(relay_precheck.CHANGED_TESTS_TIMEOUT, relay_precheck.STEP_TIMEOUT)
        real = subprocess.run

        def fake(cmd: list[str], *args: object, **kwargs: object) -> "subprocess.CompletedProcess[str]":
            # the registry test runs under STEP_TIMEOUT (1 s here) and takes longer than that on a busy machine: fake it green, so
            # only the slow changed test runs for real, under its own budget
            if cmd[0] == "python3" and cmd[-1] == relay_precheck.RULES_REGISTRY_TEST:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return real(cmd, *args, **kwargs)  # type: ignore[call-overload]

        with mock.patch.object(relay_precheck.subprocess, "run", fake):
            code, lines = relay_precheck.run(self.repo)
        self.assertIn("ok   changed tests", lines)

    def test_the_other_steps_keep_their_own_budget(self) -> None:
        # F1 pass 5: a slow bin/types-lint is still red at STEP_TIMEOUT
        self.write("bin/types-lint", "exec sleep 30\n")   # exec: the timeout kills sleep itself, not a bash that leaves it running

        self.commit()
        self._set("STEP_TIMEOUT", 1)
        code, lines = relay_precheck.run(self.repo)
        self.assertIn("  FAIL types and lint took longer than 1 s", lines)

    def test_a_slow_changed_test_does_not_hide_the_registry_message(self) -> None:
        # F2: a changed test is too slow (its group times out) and the registry test is red. The registry group must run first, so
        # both lines show. No wall clock: the test runs are faked (the registry run fails at once, the changed group raises
        # TimeoutExpired), so a busy machine cannot change the outcome. Run in the other order, the timeout would end the loop
        # before the registry test ran and its verdict would be lost.
        self.write("tests/test_rules_gate.py", "x = 1\n")
        self.write("tests/test_slow.py", "x = 1\n")
        self.commit()
        real = subprocess.run
        groups: list[list[str]] = []

        def fake(cmd: list[str], *args: object, **kwargs: object) -> "subprocess.CompletedProcess[str]":
            if cmd[0] != "python3" or not any(c.endswith("run_unittest.py") for c in cmd):
                return real(cmd, *args, **kwargs)  # type: ignore[call-overload]
            group = [c for c in cmd if c.startswith("tests.")]
            groups.append(group)
            if group == [relay_precheck.RULES_REGISTRY_TEST]:
                return subprocess.CompletedProcess(cmd, 1, "FAIL: RuleTestsComplete unlisted reader\n", "")
            raise subprocess.TimeoutExpired(cmd, relay_precheck.CHANGED_TESTS_TIMEOUT)

        with mock.patch.object(relay_precheck.subprocess, "run", fake):
            code, lines = relay_precheck.run(self.repo)
        text = "\n".join(lines)
        self.assertEqual(groups, [[relay_precheck.RULES_REGISTRY_TEST], ["tests.test_rules_gate", "tests.test_slow"]])   # registry alone first, then the changed files
        self.assertIn("RuleTestsComplete", text)
        self.assertIn("took longer than %d s" % relay_precheck.CHANGED_TESTS_TIMEOUT, text)

    def test_a_registry_test_cut_off_names_itself_and_its_own_allowance(self) -> None:
        # F1: STEP_TIMEOUT 1 s, the registry stand-in sleeps 3 s, the changed-tests budget stays 600 s: the line names the registry test and 1 s
        self.write("tests/test_rules_gate.py", "import time, unittest\nclass RuleTestsComplete(unittest.TestCase):\n    def test_x(self):\n"
                   "        time.sleep(3)\n")
        self.commit()
        self._set("STEP_TIMEOUT", 1)
        code, lines = relay_precheck.run(self.repo)
        text = "\n".join(lines)
        self.assertIn("FAIL rules registry test took longer than 1 s", text)
        self.assertNotIn("230", text)

    def test_no_default_branch_says_skip(self) -> None:
        git(self.repo, "branch", "-m", "wt/task", "feature")
        git(self.repo, "branch", "-m", "master", "trunk")
        self.assertEqual(relay_precheck.check_changed_tests(self.repo), ["skipped: no master or main branch to compare with"])

    # F3: the precheck holds one test token for its changed tests and passes it down; its test runs take no second one.
    ONE_SHARED = ("1", "2", "3")      # gate-slots/count 1, per-gate 2, count 3: gate tokens 0 and 1, one shared token (2)

    def pool(self) -> str:
        home = tempfile.mkdtemp(prefix="precheck-home-")
        self.addCleanup(shutil.rmtree, home, True)
        for rel, text in (("gate-slots/count", self.ONE_SHARED[0]), ("test-tokens/per-gate", self.ONE_SHARED[1]), ("test-tokens/count", self.ONE_SHARED[2])):
            os.makedirs(os.path.dirname(os.path.join(home, rel)), exist_ok=True)
            with open(os.path.join(home, rel), "w") as handle:
                handle.write(text)
        env = mock.patch.dict(os.environ, {"RELAY_HOME": home})
        env.start()
        self.addCleanup(env.stop)
        steps = mock.patch.object(relay_precheck, "STEPS", (("changed tests", relay_precheck.check_changed_tests),))
        steps.start()
        self.addCleanup(steps.stop)
        # a deadlock (the child waiting for a second token) ends as "FAIL changed tests took longer" after this budget, not after 600 s
        budget = mock.patch.object(relay_precheck, "CHANGED_TESTS_TIMEOUT", 30)
        budget.start()
        self.addCleanup(budget.stop)
        self.write("tests/test_new.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
        self.commit()
        return home

    def test_a_pool_with_one_shared_token_does_not_deadlock_the_changed_tests(self) -> None:
        self.pool()
        err = io.StringIO()
        with redirect_stderr(err):
            code, lines = relay_precheck.run(self.repo)
        self.assertEqual((code, lines[0]), (0, "ok   changed tests"), lines)      # the child took the passed-down base, not a second token
        self.assertNotIn("waiting", err.getvalue())

    def test_the_precheck_waits_for_the_one_token_and_says_so_once(self) -> None:
        home = self.pool()
        st = relay_tokens.settings(home, 1, 12)
        other, _ = relay_tokens.take_base(home, st, relay_tokens.SHARED, 1)
        err = io.StringIO()
        out = {}

        def go() -> None:
            with redirect_stderr(err):
                out["r"] = relay_precheck.run(self.repo)

        thread = threading.Thread(target=go, daemon=True)
        thread.start()
        waiting = os.path.join(relay_tokens.pool_dir(home), "waiting")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (os.path.isdir(waiting) and os.listdir(waiting)):
            time.sleep(0.05)
        self.assertTrue(os.listdir(waiting))      # the precheck is waiting
        other.release()
        thread.join(60)
        code, lines = out["r"]
        self.assertEqual((code, lines[0]), (0, "ok   changed tests"), lines)      # the wait did not count against the 30 s budget of the tests
        self.assertEqual(err.getvalue().count("precheck: waiting for a test token"), 1, err.getvalue())




class TestCommand(Base):
    def test_run_reports_every_step_and_exits_1_when_one_is_red(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/relay/lib/relay_q.py", "X = 1\n")
        self.commit()
        self.write("lib/relay_q.py", "X = 2\n")
        self.commit()
        code, lines = relay_precheck.run(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("RED  lib copies identical", lines)
        self.assertTrue(lines[-1].startswith("precheck: RED"))

    def test_the_relay_command_runs_it_and_passes_the_exit_code(self) -> None:
        self.write("lib/relay_q.py", "X = 1\n")
        self.write("plugins/relay/lib/relay_q.py", "X = 0\n")
        self.commit()
        done = subprocess.run([sys.executable, RELAY, "precheck", "-C", self.repo], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("plugins/relay/lib/relay_q.py", done.stdout)
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


class UsageNamesChangedTests(unittest.TestCase):
    def test_the_usage_and_the_cycle_comment_name_the_changed_tests_step(self) -> None:
        # F3: text only
        with open(RELAY, encoding="utf-8") as handle:
            usage = handle.read()
        start = usage.index("relay precheck [-C <worktree>]")
        self.assertIn("changed tests", usage[start:start + 400])
        with open(os.path.join(ROOT, "plugins", "delegate", "workflows", "cycle.js"), encoding="utf-8") as handle:
            js = handle.read()
        start = js.index("`relay precheck` (")
        self.assertIn("changed tests", js[start:start + 150])
