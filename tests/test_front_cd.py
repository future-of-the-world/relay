"""The front's `cd` into a linked worktree moves Claude Code's session folder there. guard-main refuses it for the main
session (no agent_id in the hook input) and lets a subagent, which has its own folder, do it. Free: temporary repo."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "plugins", "core", "hooks", "guard-main.sh")
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


class FrontCd(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.main = os.path.realpath(self.tmp.name)
        subprocess.run(GIT + ["init", "-q", "-b", "master", self.main], check=True)
        subprocess.run(GIT + ["-C", self.main, "commit", "-q", "--allow-empty", "-m", "i"], check=True)
        self.wt = os.path.join(self.main, ".worktrees", "x")
        subprocess.run(GIT + ["-C", self.main, "worktree", "add", "-q", self.wt, "-b", "wt/x"], check=True)

    def run_hook(self, command: str, agent: bool = False, cwd: str = "") -> int:
        event = {"tool_name": "Bash", "cwd": cwd or self.main, "tool_input": {"command": command}}
        if agent:
            event["agent_id"] = "a1"
            event["agent_type"] = "delegate:worker"
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        run = subprocess.run([HOOK], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
        self.last = run.stderr
        return run.returncode

    def test_main_session_cd_into_worktree_is_refused(self) -> None:
        for command in (f"cd {self.wt}; ls", f"cd {self.wt} && ls", f"cd {self.wt}", f"cd {self.wt}/sub/.."):
            self.assertEqual(self.run_hook(command), 2, command)
            self.assertIn("git -C", self.last)

    def test_other_commands_run(self) -> None:
        for command in (f"git -C {self.wt} status", f"ls {self.wt}", f"(cd {self.wt} && ls)", "cd /tmp && ls"):
            self.assertEqual(self.run_hook(command), 0, command)

    def test_subagent_in_its_worktree_is_not_refused(self) -> None:
        self.assertEqual(self.run_hook(f"cd {self.wt} && ls", agent=True, cwd=self.wt), 0)


if __name__ == "__main__":
    unittest.main()
