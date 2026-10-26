"""The merge hook (plugins/core/hooks/merge.py) as a module: what the shell tests cannot make happen (an unexpected exception)."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(os.path.dirname(HERE), "plugins", "core", "hooks", "merge.py")
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def load_hook():
    spec = importlib.util.spec_from_file_location("merge_hook_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FailsClosed(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.tmp]))
        self.repo = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(self.repo, ".relay"))
        env = {**os.environ, **GIT_ENV}
        for args in (["init", "-q", "-b", "master"], ["add", "-A"]):
            if args[0] == "add":
                with open(os.path.join(self.repo, ".relay", "README.md"), "w") as handle:
                    handle.write("x\n")
            subprocess.run(["git", "-C", self.repo, *args], check=True, env=env)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "init"], check=True, env=env)
        subprocess.run(["git", "-C", self.repo, "branch", "wt/x"], check=True, env=env)
        self.hook = {"hook_event_name": "PreToolUse", "cwd": self.repo, "tool_input": {"command": "git merge --ff-only wt/x"}}

    def run_pre(self, judge, module=None):
        module = module or load_hook()
        err = io.StringIO()
        with mock.patch.object(module, "judge", side_effect=judge), contextlib.redirect_stderr(err):
            rc = module.pre(self.hook)
        return rc, err.getvalue()

    def test_an_unexpected_exception_refuses_the_merge_with_exit_2(self):
        # exit 1 of a PreToolUse hook is non-blocking: the merge would run unjudged
        rc, err = self.run_pre(KeyError("schema"))
        self.assertEqual(rc, 2)
        self.assertIn("merge refused: the gate for wt/x could not be judged", err)

    def test_a_refusal_keeps_its_own_line_and_exit_2(self):
        module = load_hook()
        rc, err = self.run_pre(module.Refused("no green gate"), module)
        self.assertEqual((rc, err.strip()), (2, "merge refused: no green gate"))

    def test_a_branch_tip_git_cannot_count_is_a_refusal_not_a_value_error(self):
        # the diff names the path as added, then `rev-list --count` of a tip that does not exist fails (exit 128, no output)
        module = load_hook()
        real = module.relay_git.git

        def git(repo, *args, **kwargs):
            if args[0] == "diff":
                return 0, "queue/x.json"
            return real(repo, *args, **kwargs)

        with mock.patch.object(module.relay_git, "git", side_effect=git):
            with self.assertRaises(module.Refused) as caught:
                module.closing_ref(self.repo, "master", {"wt/gone": "0" * 40}, "queue/x.json")
        self.assertIn("wt/gone", str(caught.exception))

    def test_a_command_with_no_merge_is_silent(self):
        self.hook["tool_input"]["command"] = "git status"
        rc, err = self.run_pre(KeyError("never called"))
        self.assertEqual((rc, err), (0, ""))


class GuardMainSync(unittest.TestCase):
    """guard-main in a main checkout on its default branch lets it catch up with its remote, and nothing else of that kind."""

    GUARD = os.path.join(os.path.dirname(HERE), "plugins", "core", "hooks", "guard-main.sh")

    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.repo]))
        self.env = {**os.environ, **GIT_ENV}
        self.env.pop("CLAUDE_PROJECT_DIR", None)
        subprocess.run(["git", "init", "-q", "-b", "master", self.repo], check=True, env=self.env)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "--allow-empty", "-m", "init"], check=True, env=self.env)

    def verdict(self, command: str) -> int:
        payload = json.dumps({"tool_name": "Bash", "cwd": self.repo, "tool_input": {"command": command}})
        return subprocess.run([self.GUARD], input=payload, text=True, capture_output=True, env=self.env).returncode

    def test_q1_a_main_checkout_on_its_default_branch_may_ff_only_to_origin_default_only(self):
        # Failing case: it was refused (exit 2); now exit 0. Everything else of the kind stays refused (exit 2).
        self.assertEqual(self.verdict("git merge --ff-only origin/master"), 0)
        self.assertEqual(self.verdict("git merge origin/master"), 2)            # not fast-forward only
        self.assertEqual(self.verdict("git merge --ff-only some-branch"), 2)
        self.assertEqual(self.verdict("git merge --ff-only upstream/master"), 2)   # origin is the only remote
        self.assertEqual(self.verdict("git merge --ff-only origin/other"), 2)       # not the default branch
        subprocess.run(["git", "-C", self.repo, "switch", "-q", "-c", "side"], check=True, env=self.env)
        self.assertEqual(self.verdict("git merge --ff-only origin/master"), 2)      # the default branch is not checked out

    def test_f1_fetch_head_is_not_a_sync(self):
        # FETCH_HEAD is whatever the last fetch wrote (any remote, URL or local branch): a bypass of "origin only" and of the gate.
        self.assertEqual(self.verdict("git merge --ff-only FETCH_HEAD"), 2)
        self.assertEqual(self.verdict("git fetch . side && git merge --ff-only FETCH_HEAD"), 2)
        self.assertEqual(self.verdict("git fetch https://example.invalid/x.git topic && git merge --ff-only FETCH_HEAD"), 2)
        self.assertEqual(self.verdict("git merge --ff-only origin/master"), 0)

    def test_f4_ff_only_beside_no_ff_is_refused(self):
        # git takes the last of --ff/--no-ff/--ff-only: --ff-only --no-ff makes a merge commit on the default branch.
        for flag in ("--no-ff", "--ff", "--squash"):
            self.assertEqual(self.verdict(f"git merge --ff-only {flag} --no-edit origin/master"), 2, flag)
            self.assertEqual(self.verdict(f"git merge --ff-only {flag} wt/x"), 2, flag)
        self.assertEqual(self.verdict("git merge --ff-only origin/master"), 0)
        self.assertEqual(self.verdict("git merge --ff-only wt/x"), 0)
        self.assertEqual(self.verdict("git merge --ff-only wt/x 2>&1 | tail -3"), 0)

    def test_f5_header_names_the_sync_exception(self):
        with open(self.GUARD) as handle:
            header = handle.read()[:1500]
        self.assertIn("--ff-only origin/<default>", header)


if __name__ == "__main__":
    unittest.main()
