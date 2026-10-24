"""The bench scenarios that grade `delegated-to-a-worker` must ask for a worker, in this working copy.

Cause found 2026-10-24: the bench session follows the owner's rules (work in a worktree, write a
spec, review) and does small jobs itself, so no worker started and the files landed in a worktree
the graders never look at. The scenario prompts now say who builds and where.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_bench  # noqa: E402

WORKER_SCENARIOS = ("add-function", "small-script")


class ScenarioPromptsStartAWorker(unittest.TestCase):
    def test_prompt_asks_for_a_worker_in_this_working_copy(self):
        for name in WORKER_SCENARIOS:
            scenario = relay_bench.load_scenario(name)
            prompt = scenario["_prompt"]
            self.assertTrue(any(g["type"] == "agent_used" and g["agent_type"] == "worker" for g in scenario["graders"]), name)
            self.assertIn("worker agent", prompt, name)
            self.assertIn("this working copy", prompt, name)
            self.assertIn("not in another worktree", prompt, name)

    def test_workspace_is_a_linked_worktree_not_a_primary_checkout(self):
        # The guard refuses agent writes in a primary checkout; the graders read the workspace itself.
        for name in WORKER_SCENARIOS:
            with tempfile.TemporaryDirectory() as base:
                ws = relay_bench.make_workspace(relay_bench.load_scenario(name), base)
                self.assertTrue(os.path.isfile(os.path.join(ws, ".git")), name)   # a worktree has a .git file, a primary a folder
                self.assertTrue(os.path.isfile(os.path.join(ws, "src", "shelf.ts")), name)
                branch = subprocess.run(["git", "-C", ws, "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
                self.assertEqual(branch, "wt/bench")


class WorkerModelFollowsTheProfile(unittest.TestCase):
    def test_plugin_copy_carries_the_profile_models(self):
        # The session starts the plugin's own delegate:worker; its model line must be the profile's.
        base = relay_bench.load_profile("active")
        derived = relay_bench.derive_profile(base, ["models.build=haiku"])
        folder = os.path.join(ROOT, "plugins", "delegate")
        with tempfile.TemporaryDirectory() as out:
            def model_of(profile):
                copy = relay_bench.plugin_for_run(profile, folder, out)
                front, _ = relay_bench.split_frontmatter(open(os.path.join(copy, "agents", "worker.md"), encoding="utf-8").read())
                return front["model"]
            self.assertEqual(model_of(base), "sonnet")
            self.assertEqual(model_of(derived), "haiku")
        # the repository's own worker is not touched
        front, _ = relay_bench.split_frontmatter(open(os.path.join(folder, "agents", "worker.md"), encoding="utf-8").read())
        self.assertEqual(front["model"], "sonnet")


if __name__ == "__main__":
    unittest.main()
