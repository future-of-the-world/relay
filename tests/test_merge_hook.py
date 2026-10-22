"""The merge hook (plugins/core/hooks/merge.py) as a module: what the shell tests cannot make happen (an unexpected exception)."""
import contextlib
import importlib.util
import io
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

    def test_a_command_with_no_merge_is_silent(self):
        self.hook["tool_input"]["command"] = "git status"
        rc, err = self.run_pre(KeyError("never called"))
        self.assertEqual((rc, err), (0, ""))


if __name__ == "__main__":
    unittest.main()
