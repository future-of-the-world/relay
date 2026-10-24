"""The bench scenarios that grade `delegated-to-a-worker` run in a linked worktree and do not order a worker.

Cause found 2026-10-24: the workspace was a primary checkout, where core's guard blocks every write,
so files landed in a worktree the graders never look at. Owner's answer to review Q1: the prompts do
not say "hand it to a worker", so the grader keeps telling a delegating setup from a non-delegating one.
"""
import copy
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


class ScenarioPromptsLeaveDelegationToTheSetup(unittest.TestCase):
    def test_prompt_does_not_order_a_worker(self):
        for name in WORKER_SCENARIOS:
            scenario = relay_bench.load_scenario(name)
            prompt = scenario["_prompt"].lower()
            self.assertTrue(any(g["type"] == "agent_used" and g["agent_type"] == "worker" for g in scenario["graders"]), name)
            self.assertNotIn("worker", prompt, name)
            self.assertNotIn("another worktree", prompt, name)

    def test_docs_and_scaffolds_name_the_core_guard(self):
        texts = [open(os.path.join(ROOT, "docs", "benchmark.md"), encoding="utf-8").read()]
        texts += [open(os.path.join(ROOT, "evals", "scenarios", n, "scaffold.sh"), encoding="utf-8").read() for n in WORKER_SCENARIOS]
        for text in texts:
            self.assertNotIn("front's guard", text)
            self.assertIn("core plugin's main-checkout guard blocks every write", text)

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
        # derive_profile writes a tracked file under profiles/candidates; the test builds the dict itself
        derived = copy.deepcopy(base)
        derived["models"]["build"] = "haiku"
        derived["profile"] = {"name": "test-build-haiku"}
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

    def test_every_agent_of_a_copied_plugin_takes_its_own_tier(self):
        # An agent that is not one of delegate's: its own relay-tier decides, here judge -> sonnet.
        profile = copy.deepcopy(relay_bench.load_profile("active"))
        profile["models"]["judge"] = "sonnet"
        profile["profile"] = {"name": "test-judge-sonnet"}
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            os.makedirs(os.path.join(src, "agents"))
            with open(os.path.join(src, "agents", "foo.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: foo\nrelay-tier: judge\nmodel: opus\n---\nbody\n")
            copy_dir = relay_bench.plugin_for_run(profile, src, out)
            front, _ = relay_bench.split_frontmatter(open(os.path.join(copy_dir, "agents", "foo.md"), encoding="utf-8").read())
            self.assertEqual(front["model"], "sonnet")

    def test_plugin_without_agents_is_not_copied(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
            self.assertEqual(relay_bench.plugin_for_run(relay_bench.load_profile("active"), src, out), src)


if __name__ == "__main__":
    unittest.main()
