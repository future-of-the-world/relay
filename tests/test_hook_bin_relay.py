"""The front plugin's SessionStart hook names a main checkout whose bin/relay differs from HEAD (the 28 Oct eval stub), in its first line."""
import json
import os
import subprocess
import tempfile
import unittest

from hook_helpers import ROOT, SoftCases, run_hook

HOOK = os.path.join(ROOT, "plugins", "front", "hooks", "handover.py")
STUB = os.path.join(ROOT, "evals", "plugin", "relay-stub.py")


def git(repo: str, *args: str) -> None:
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


class BinRelayHook(SoftCases):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.tmp, "main")
        os.makedirs(os.path.join(self.repo, "bin"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.write("real relay\n")
        git(self.repo, "add", "bin/relay")
        git(self.repo, "commit", "-q", "-m", "init")

    def write(self, text: str, repo: str = "") -> None:
        with open(os.path.join(repo or self.repo, "bin", "relay"), "w") as handle:
            handle.write(text)

    def start(self, source: str = "startup") -> dict:
        home = os.path.join(self.tmp, "home")
        out = run_hook(HOOK, json.dumps({"source": source, "cwd": self.tmp}), {"RELAY_ROOT": self.repo, "RELAY_HOME": home})
        return json.loads(out) if out else {}

    def first_line(self) -> str:
        out = self.start()
        return out["hookSpecificOutput"]["additionalContext"].splitlines()[0] if out else ""

    def test_stub_bytes_in_bin_relay_are_named_in_the_first_line_with_the_restore_step(self):
        # pass case 1: bin/relay holds the bytes of the real eval stub, as on 28 Oct
        with open(STUB) as handle:
            self.write(handle.read())
        line = self.first_line()
        self.assertIn("bin/relay", line)
        self.assertIn("differs from HEAD", line)
        self.assertIn(f"git -C {self.repo} restore --source=HEAD --staged --worktree bin/relay", line)
        self.assertIn("differs from HEAD", self.start()["systemMessage"].splitlines()[0])

    def test_a_staged_stub_is_named_and_the_printed_command_restores_it(self):
        self.write("stub\n")
        git(self.repo, "add", "bin/relay")
        line = self.first_line()
        self.assertIn("differs from HEAD", line)
        cmd = line.split("terminal outside the session: ", 1)[1].split()
        subprocess.run(cmd, check=True)
        self.assertEqual(self.first_line(), "")
        self.assertEqual(subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout, "")

    def test_a_deleted_bin_relay_is_named(self):
        os.remove(os.path.join(self.repo, "bin", "relay"))
        self.assertIn("differs from HEAD", self.first_line())

    def test_bin_relay_equal_to_head_prints_nothing(self):
        # pass case 2
        self.assertEqual(self.start(), {})

    def test_a_task_worktree_editing_bin_relay_is_not_flagged(self):
        # pass case 3: RELAY_ROOT is a linked worktree whose branch edits bin/relay; the main checkout is clean
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", "-b", "task", wt)
        self.write("a branch editing bin/relay\n", wt)
        self.repo_env = wt
        out = run_hook(HOOK, json.dumps({"source": "startup", "cwd": self.tmp}), {"RELAY_ROOT": wt, "RELAY_HOME": self.tmp})
        self.assertEqual(out, "")
        # and from the worktree the main checkout is the one judged
        self.write("stub\n")
        out = run_hook(HOOK, json.dumps({"source": "startup", "cwd": self.tmp}), {"RELAY_ROOT": wt, "RELAY_HOME": self.tmp})
        self.assertIn(self.repo, json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_the_check_takes_no_index_lock_and_does_not_rewrite_the_index(self):
        # stale stat info (touch) is what makes `git status` rewrite the index
        self.write("real relay\n")
        os.utime(os.path.join(self.repo, "bin", "relay"), (1, 1))
        index = os.path.join(self.repo, ".git", "index")
        os.utime(index, (5, 5))
        self.start()
        self.assertEqual(os.stat(index).st_mtime, 5)
        # a held index.lock changes no answer
        open(index + ".lock", "w").close()
        self.assertEqual(self.start(), {})
        self.write("stub\n")
        self.assertIn("differs from HEAD", self.first_line())
        self.assertTrue(os.path.exists(index + ".lock"))


class WrapperLookup(SoftCases):
    """The plugin's bin/relay wrapper finds the repository through the amidman marketplace entry."""

    WRAPPER = os.path.join(ROOT, "plugins", "front", "bin", "relay")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude"))

    def repo(self, name: str) -> str:
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(path, "bin"))
        exe = os.path.join(path, "bin", "relay")
        with open(exe, "w") as handle:
            handle.write(f"#!/bin/sh\necho ran {name}\n")
        os.chmod(exe, 0o755)
        return path

    def settings(self, path: str) -> None:
        # the key setup writes: the marketplace's own name, so a rename that misses the wrapper turns these tests red
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as handle:
            name = json.load(handle)["name"]
        data = {"extraKnownMarketplaces": {name: {"source": {"source": "directory", "path": path}}}}
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as handle:
            json.dump(data, handle)

    def run_wrapper(self, **extra: str) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "HOME": self.home, **extra}
        return subprocess.run(["bash", self.WRAPPER], env=env, capture_output=True, text=True)

    def test_settings_marketplace_path(self) -> None:
        # failing case: relay lives elsewhere, only the amidman entry points at it, no ~/relay
        self.settings(self.repo("opt"))
        self.assertEqual(self.run_wrapper().stdout, "ran opt\n")

    def test_relay_root_wins(self) -> None:
        self.settings(self.repo("opt"))
        other = self.repo("other")
        self.assertEqual(self.run_wrapper(RELAY_ROOT=other).stdout, "ran other\n")

    def test_falls_back_to_home_relay(self) -> None:
        # no settings file: ~/relay is used
        os.makedirs(os.path.join(self.home, "relay", "bin"))
        exe = os.path.join(self.home, "relay", "bin", "relay")
        with open(exe, "w") as handle:
            handle.write("#!/bin/sh\necho ran home\n")
        os.chmod(exe, 0o755)
        self.assertEqual(self.run_wrapper().stdout, "ran home\n")


if __name__ == "__main__":
    unittest.main()
