"""Review fixes of the kit.toml rename: duplicate new name, single-quoted values, setup() wiring, lane branches that inherit an old name."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import ROOT  # noqa: E402
from test_setup_off import Fixture  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_gate  # noqa: E402
import relay_kit  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, env={**os.environ, **GIT_ENV})


class RenameEdges(unittest.TestCase):
    def test_f2_new_name_already_present_drops_the_old_line(self) -> None:
        # the new name's value (4) wins; the file stays valid TOML
        new, did = relay_kit.rename_old_delegate_keys("[delegate]\nmax_parallel = 6\nmax_agents_per_change = 4\n")
        kit = relay_kit.parse(new)
        self.assertIsNone(kit.broken)
        self.assertEqual(kit.values["delegate"]["max_agents_per_change"], 4)
        self.assertEqual(did, ["[delegate] max_parallel removed (max_agents_per_change is already set)"])

    def test_f2_plain_rename_still_one_done_line(self) -> None:
        new, did = relay_kit.rename_old_delegate_keys("[delegate]\nmax_parallel = 6\n")
        self.assertEqual(new, "[delegate]\nmax_agents_per_change = 6\n")
        self.assertEqual(len(did), 1)

    def test_f4_single_quoted_old_value_is_mapped(self) -> None:
        new, _ = relay_kit.rename_old_delegate_keys("[delegate]\nbuild_tier_opus = 'allow'\n")
        self.assertEqual(new, "[delegate]\nopus_for_builders = 'always'\n")
        self.assertEqual(relay_kit.parse(new).problems, ())


class SetupWiring(Fixture):
    def test_f3_setup_itself_migrates_and_a_second_run_is_quiet(self) -> None:
        root = self.relay_tree()
        self.write(root, ".claude/kit.toml", '[delegate]\nmax_parallel = 6\nbuild_tier_opus = "allow"\n')
        first = self.run_setup(root)
        text = self.read(root, ".claude/kit.toml")
        self.assertIn("max_agents_per_change = 6", text)
        self.assertIn('opus_for_builders = "always"', text)
        self.assertIn("kit.toml: [delegate] max_parallel -> max_agents_per_change", str(first))
        self.assertNotIn("max_parallel -> ", str(self.run_setup(root)))


class LaneBranch(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        self.main = os.path.join(self.tmp, "main")
        os.makedirs(os.path.join(self.main, ".claude"))
        os.makedirs(os.path.join(self.main, ".relay"))
        self.kit = os.path.join(self.main, ".claude", "kit.toml")
        git(self.main, "init", "-q", "-b", "master")
        self.put(self.kit, "[delegate]\nmax_parallel = 6\n")
        self.put(os.path.join(self.main, ".relay", "README.md"), "x\n")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "init")
        self.wt = os.path.join(self.tmp, "wt")
        git(self.main, "worktree", "add", "-q", self.wt, "-b", "wt/task")
        self.put(self.kit, "[delegate]\nmax_agents_per_change = 6\n")   # master renames after the fork
        git(self.main, "commit", "-qam", "rename")

    @staticmethod
    def put(path: str, text: str) -> None:
        with open(path, "w") as handle:
            handle.write(text)

    def refusal(self) -> str:
        try:
            relay_gate.refuse_bad_settings(self.wt)
        except relay_gate.GateRefused as exc:
            return str(exc)
        return ""

    def test_f1_inherited_old_name_says_take_the_default_branch(self) -> None:
        self.assertIn("take the default branch", self.refusal())
        self.assertNotIn("relay setup", self.refusal())

    def test_f1_after_taking_master_the_gate_passes_the_settings_step(self) -> None:
        git(self.wt, "merge", "-q", "--no-edit", "master")
        self.assertEqual(self.refusal(), "")

    def test_f1_a_branch_that_writes_an_old_name_is_still_refused_with_setup(self) -> None:
        self.put(os.path.join(self.wt, ".claude", "kit.toml"), "[delegate]\ntyped_only = false\n")
        git(self.wt, "commit", "-qam", "mine")
        msg = self.refusal()
        self.assertIn("typed_agents_only", msg)
        self.assertIn("relay setup", msg)

    def test_f1_parse_still_names_the_new_key(self) -> None:
        self.assertIn("max_agents_per_change", relay_kit.parse("[delegate]\nmax_parallel = 4\n").problems[0].line())


if __name__ == "__main__":
    unittest.main()
