"""Q1: a read-only agent (critic, checker, scout) must not run a relay command that writes, and `relay migrate --all`
must not write into a primary checkout unless asked. Free: temporary folders and HOME, no paid run."""
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from relay_testbase import load_hook as _load_hook  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "plugins", "delegate", "hooks", "read-only-guard.py")
RELAY = os.path.join(ROOT, "bin", "relay")
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def load_guard():
    return _load_hook("read_only_guard", HOOK)


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
                        "relay check migrate", "relay queue take item", "relay queue note x --input a.toml", "FOO=1 relay setup .", "env X=1 relay install",
                        "bash -c 'cd x; relay setup .'", "eval relay setup", "sh -c 'relay sync'",
                        "relay check owner review.json F2 --input o.toml", "relay improve adopt cand", "relay candidate x",
                        "relay calibrate", "relay gate", "relay bench a b", "relay land wt/x"):
            for agent in ("delegate:critic", "delegate:checker", "delegate:scout"):
                self.assertEqual(hook(agent, command), "deny", (agent, command))

    def test_q1_reads_and_other_agents_are_let_through(self) -> None:
        """The same writers pass for the front's agents (worker: a deliberate setup); reads pass for the critic."""
        self.assertEqual(hook("delegate:worker", "bin/relay migrate --all"), "allow")
        self.assertEqual(hook("", "relay setup /x"), "allow")   # the main session has no agent type
        for command in ("relay sync --dry", "relay queue show a", "relay queue count", "relay doctor", "git log --oneline",
                        "grep migrate lib/relay_setup.py", "cat docs/relay-migrate.md",
                        "git grep -n 'relay setup'", 'grep -rn "relay queue add" docs', "rg 'relay install' README.md",
                        'echo "see relay setup docs"', "sh -c 'relay sync --dry'", "relay bench list", "relay improve suggest",
                        "relay improve log", "relay check show r.json", "relay check findings --review r.json",
                        "relay check record check --input c.toml"):
            self.assertEqual(hook("delegate:critic", command), "allow", command)
        self.assertEqual(hook("delegate:critic", "relay setup /x", tool="Read"), "allow")

    def test_q1_every_relay_subcommand_is_classified_as_read_or_write(self) -> None:
        """A subcommand bin/relay gains must be put on the guard's list (WRITERS) or its READS: none is left unclassified."""
        guard = load_guard()
        with open(RELAY, encoding="utf-8") as handle:
            source = handle.read()
        table = source[source.index("COMMANDS = {"):source.index("\n}\n", source.index("COMMANDS = {"))]
        commands = set(re.findall(r'"(\w+)":', table))
        self.assertGreater(len(commands), 10)
        self.assertEqual(commands - set(guard.WRITERS) - guard.READS, set())
        queue_words = set(re.search(r"relay queue \[([a-z|]+)\]", source).group(1).split("|"))
        self.assertEqual(queue_words - guard.WRITERS["queue"] - guard.READ_WORDS["queue"], set())

    def test_q1_every_queue_writing_word_of_bin_relay_is_on_the_guard_list(self) -> None:
        """Failing case: `start` (makes a worktree, takes an item) is in bin/relay QUEUE_WRITES but was not on the guard's
        list, so a critic could run `relay queue start x --scratch y`. The usage line does not list it; QUEUE_WRITES does."""
        loader = importlib.machinery.SourceFileLoader("relay_bin_for_guard_test", RELAY)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        self.assertIn("start", module.QUEUE_WRITES)
        self.assertEqual(set(module.QUEUE_WRITES) - load_guard().WRITERS["queue"], set())
        self.assertEqual(hook("delegate:critic", "relay queue start x --scratch y"), "deny")


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
                   "RELAY_PROJECTS": os.path.join(tmp, "projects.toml"),
                   "RELAY_CLAUDE_BIN": "false"}   # a stub: the plugin install must not run the real claude

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
