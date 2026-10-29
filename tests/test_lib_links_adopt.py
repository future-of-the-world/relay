"""Plugin lib files are links to the one source in lib/ (queue item lib-modules-are-committed-in-three-copies).
Two code paths copy plugin folders and must treat a link right: the bench's plugin copy for `--plugin-dir`, and `relay improve adopt`,
which copies a candidate's files back onto plugins/<p>/. Every folder here is a temporary one."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_bench  # noqa: E402
import relay_precheck  # noqa: E402


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def git(repo: str, *args: str) -> None:
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@e.x", "-c", "user.name=t", *args], capture_output=True, check=True)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class Repo(unittest.TestCase):
    """A scratch 'repo': lib/relay_x.py, and plugins/delegate with a link plugins/delegate/lib/relay_x.py -> ../../../lib/relay_x.py."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        write(os.path.join(self.tmp, "lib", "relay_x.py"), "X = 1\n")
        self.plugin = os.path.join(self.tmp, "plugins", "delegate")
        write(os.path.join(self.plugin, "agents", "worker.md"), "---\nname: worker\nrelay-tier: build\nmodel: opus\n---\nb\n")
        write(os.path.join(self.plugin, "lib", "kit_only.py"), "K = 1\n")
        os.symlink("../../../lib/relay_x.py", os.path.join(self.plugin, "lib", "relay_x.py"))

    def candidate(self, shared: str) -> str:
        """What a candidate holds: real files (copytree's default), the shared module with the text `shared`."""
        folder = os.path.join(self.tmp, "cand", "delegate")
        write(os.path.join(folder, "lib", "relay_x.py"), shared)
        write(os.path.join(folder, "lib", "kit_only.py"), "K = 2\n")
        return folder


class TestBenchCopy(Repo):
    def test_the_plugin_copy_for_a_run_holds_real_files_not_dangling_links(self) -> None:
        # pass case 6: a relative link copied alone into a scratch folder points nowhere; the copy must hold the content
        profile = {"profile": {"name": "t"}, "models": {}, "effort": {}}
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        copy = relay_bench.plugin_for_run(profile, self.plugin, out)
        moved = os.path.join(copy, "lib", "relay_x.py")
        self.assertFalse(os.path.islink(moved))
        self.assertEqual(read(moved), "X = 1\n")


class TestAdoptLib(Repo):
    def test_a_candidate_equal_to_the_source_is_adopted_and_lib_is_untouched(self) -> None:
        cand = self.candidate("X = 1\n")
        self.assertEqual(relay_bench.lib_adoption_conflicts(cand, self.plugin), [])
        relay_bench.adopt_lib(os.path.join(cand, "lib"), os.path.join(self.plugin, "lib"))
        self.assertTrue(os.path.islink(os.path.join(self.plugin, "lib", "relay_x.py")))      # still a link
        self.assertEqual(read(os.path.join(self.tmp, "lib", "relay_x.py")), "X = 1\n")        # the source is unchanged
        self.assertEqual(read(os.path.join(self.plugin, "lib", "kit_only.py")), "K = 2\n")    # a plugin-only file is adopted

    def test_a_candidate_that_edited_a_shared_module_is_refused_by_name(self) -> None:
        cand = self.candidate("X = 99\n")
        found = relay_bench.lib_adoption_conflicts(cand, self.plugin)
        self.assertEqual(len(found), 1)
        self.assertIn("lib/relay_x.py", found[0])
        self.assertIn("port that edit to lib/", found[0])
        # nothing was written by asking
        self.assertEqual(read(os.path.join(self.tmp, "lib", "relay_x.py")), "X = 1\n")
        self.assertEqual(read(os.path.join(self.plugin, "lib", "kit_only.py")), "K = 1\n")

    def test_a_candidate_made_before_lib_moved_on_is_stale_not_edited(self) -> None:
        # F2 pass 1: candidate holds "X = 1" (committed once); lib then committed as "X = 2". The candidate is untouched, so no refusal.
        git(self.tmp, "init", "-q")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-q", "-m", "one")                      # lib/relay_x.py = "X = 1" is a committed version
        cand = self.candidate("X = 1\n")
        write(os.path.join(self.tmp, "lib", "relay_x.py"), "X = 2\n")
        git(self.tmp, "commit", "-q", "-am", "two")
        self.assertEqual(relay_bench.lib_adoption_conflicts(cand, self.plugin), [])
        relay_bench.adopt_lib(os.path.join(cand, "lib"), os.path.join(self.plugin, "lib"))
        self.assertEqual(read(os.path.join(self.tmp, "lib", "relay_x.py")), "X = 2\n")       # master's code kept
        self.assertTrue(os.path.islink(os.path.join(self.plugin, "lib", "relay_x.py")))

    def test_a_never_committed_edit_is_still_refused_in_a_repository(self) -> None:
        # F2 pass 2: "X = 99" was never committed in lib/, so it is an edit
        git(self.tmp, "init", "-q")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-q", "-m", "one")
        found = relay_bench.lib_adoption_conflicts(self.candidate("X = 99\n"), self.plugin)
        self.assertEqual(len(found), 1)
        self.assertIn("lib/relay_x.py", found[0])
        self.assertIn("port that edit to lib/", found[0])    # F2 pass 4: the refusal names the next step


class TestAdoptCommand(Repo):
    def run_adopt(self, shared: str) -> "subprocess.CompletedProcess[str]":
        # a temp RELAY_ROOT: profiles/active.toml, a candidate profile c naming the candidate plugin folder, the plugin in plugins/
        write(os.path.join(self.plugin, ".claude-plugin", "plugin.json"), "{}\n")
        write(os.path.join(self.tmp, "profiles", "active.toml"), '[profile]\nname = "active"\n')
        write(os.path.join(self.tmp, "profiles", "candidates", "c.toml"), '[profile]\nname = "c"\n[plugins]\nenabled = ["./delegate"]\n')
        cand = os.path.join(self.tmp, "profiles", "candidates", "delegate")
        write(os.path.join(cand, ".claude-plugin", "plugin.json"), "{}\n")
        write(os.path.join(cand, "lib", "relay_x.py"), shared)
        env = dict(os.environ, RELAY_ROOT=self.tmp)
        return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "improve", "adopt", "c"],
                              capture_output=True, text=True, env=env, check=False)

    def test_adopt_of_an_edited_candidate_exits_1_and_writes_nothing(self) -> None:
        # F3 pass 1: the refusal in bin/relay runs before the history copy and active.toml
        done = self.run_adopt("X = 99\n")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("lib/relay_x.py", done.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "profiles", "history")))
        self.assertEqual(read(os.path.join(self.tmp, "profiles", "active.toml")), '[profile]\nname = "active"\n')
        self.assertEqual(read(os.path.join(self.tmp, "lib", "relay_x.py")), "X = 1\n")
        self.assertTrue(os.path.islink(os.path.join(self.plugin, "lib", "relay_x.py")))


class TestStrayMessage(unittest.TestCase):
    def test_a_new_plugin_only_file_is_told_how_to_be_kept(self) -> None:
        # F4 pass 1: the FAIL line names the file and the kit_* way to keep it, besides git rm for a merge leftover
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.realpath(tmp)
            write(os.path.join(repo, "plugins", "relay", "lib", "guard_rules.toml"), "a = 1\n")
            write(os.path.join(repo, "plugins", "relay", "lib", "kit_new.py"), "K = 1\n")     # F4 pass 3: no line
            git(repo, "init", "-q")
            git(repo, "add", "-A")
            git(repo, "-c", "user.email=t@e.x", "-c", "user.name=t", "commit", "-q", "-m", "x")
            found = relay_precheck.check_lib_links(repo)
        self.assertEqual(len(found), 1)
        self.assertIn("plugins/relay/lib/guard_rules.toml", found[0])
        self.assertIn("kit_*", found[0])
        self.assertIn("git rm", found[0])


if __name__ == "__main__":
    unittest.main()
