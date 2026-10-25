"""Q1: a read-only agent (critic, checker, scout) must not run a relay command that writes, and `relay migrate --all`
must not write into a primary checkout unless asked. Free: temporary folders and HOME, no paid run."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "plugins", "delegate", "hooks", "read-only-guard.py")
RELAY = os.path.join(ROOT, "bin", "relay")
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def hook(agent_type: str, command: str, tool: str = "Bash") -> str:
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "agent_type": agent_type, "tool_input": {"command": command}}
    run = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)["hookSpecificOutput"].get("permissionDecision", "") if run.stdout else "allow"


class ReadOnlyHook(unittest.TestCase):
    def test_q1_critic_is_refused_relay_commands_that_write(self) -> None:
        """Q1: the critic of wt/projects-out ran `bin/relay migrate --all`. Each writer on the list is refused, also behind
        a path, `cd x &&`, a pipe and `bash -c`."""
        for command in ("bin/relay migrate --all", "relay setup /x", "cd w && python3 bin/relay migrate --all --apply",
                        "relay install", "relay queue add foo", "echo y | relay sync", 'bash -c "relay setup ."',
                        "relay check migrate", "relay queue take item"):
            for agent in ("delegate:critic", "delegate:checker", "delegate:scout"):
                self.assertEqual(hook(agent, command), "deny", (agent, command))

    def test_q1_reads_and_other_agents_are_let_through(self) -> None:
        """The same writers pass for the front's agents (worker: a deliberate setup); reads pass for the critic."""
        self.assertEqual(hook("delegate:worker", "bin/relay migrate --all"), "allow")
        self.assertEqual(hook("", "relay setup /x"), "allow")   # the main session has no agent type
        for command in ("relay sync --dry", "relay queue show a", "relay queue count", "relay doctor", "git log --oneline",
                        "grep migrate lib/relay_setup.py", "cat docs/relay-migrate.md"):
            self.assertEqual(hook("delegate:critic", command), "allow", command)
        self.assertEqual(hook("delegate:critic", "relay setup /x", tool="Read"), "allow")


class MigrateAllPrimary(unittest.TestCase):
    def test_q1_migrate_all_leaves_a_primary_checkout_alone_unless_asked(self) -> None:
        """Q1 failing case: from a worktree of project `proj`, `relay migrate --all` (projects.toml lists proj) put CLAUDE.md,
        bin/ and .claude/ into proj's primary checkout. Without --primary the checkout stays clean; with it the writer runs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            proj = os.path.join(tmp, "proj")
            os.makedirs(os.path.join(tmp, "home"))
            subprocess.run(["git", "init", "-q", "-b", "master", proj], check=True, timeout=20)
            subprocess.run([*GIT, "-C", proj, "commit", "-q", "--allow-empty", "-m", "i"], check=True, timeout=20)
            wt = os.path.join(proj, ".worktrees", "x")
            subprocess.run(["git", "-C", proj, "worktree", "add", "-q", wt, "-b", "wt/x"], check=True, timeout=20)
            with open(os.path.join(tmp, "projects.toml"), "w", encoding="utf-8") as handle:
                handle.write('[proj]\nfile = "%s/CLAUDE.local.md"\nload = []\n' % proj)
            env = {**os.environ, "HOME": os.path.join(tmp, "home"), "RELAY_HOME": os.path.join(tmp, "rh"),
                   "RELAY_PROJECTS": os.path.join(tmp, "projects.toml")}

            def status() -> str:
                return subprocess.run(["git", "-C", proj, "status", "--short", "--ignored"], capture_output=True, text=True, timeout=20).stdout

            def migrate(*args: str) -> subprocess.CompletedProcess:
                return subprocess.run([sys.executable, RELAY, "migrate", "--all", *args], capture_output=True, text=True, cwd=wt, env=env, timeout=120)

            before = status()   # only the untracked .worktrees/ folder
            run = migrate()
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("--primary", run.stdout)
            self.assertEqual(status(), before)
            run = migrate("--primary")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(os.path.isfile(os.path.join(proj, "CLAUDE.md")))


if __name__ == "__main__":
    unittest.main()
