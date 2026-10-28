"""Port of plugins/delegate/tests/route-guard.test.sh: the routing guard's decisions on the Agent tool."""
import json
import os
import tempfile
import unittest
from typing import Optional

from hook_helpers import ROOT, run_hook, SoftCases

GUARD = os.path.join(ROOT, "plugins", "delegate", "hooks", "route-guard.py")


class RouteGuard(SoftCases):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.cwd = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.home)
        os.makedirs(self.cwd)

    def agent(self, subagent: str, prompt: str = "x", model: Optional[str] = None, **extra: str) -> str:
        tool_input = {"subagent_type": subagent, "prompt": prompt}
        if model:
            tool_input["model"] = model
        event = {"tool_name": "Agent", "cwd": ".", "tool_input": tool_input}
        event.update(extra)
        return run_hook(GUARD, json.dumps(event), {"RELAY_HOME": self.home}, cwd=self.cwd)

    def test_general_purpose_denied(self) -> None:
        self.assertIn('"deny"', self.agent("general-purpose"))

    def test_typed_scout_allowed(self) -> None:
        self.assertEqual(self.agent("delegate:scout"), "")

    def test_worker_on_opus_denied(self) -> None:
        self.assertIn("Escalated", self.agent("delegate:worker", model="opus"))

    def test_worker_on_opus_with_lower_case_escalation_allowed(self) -> None:
        self.assertEqual(self.agent("delegate:worker", "x\n escalated: sonnet failed twice", "opus"), "")

    def test_worker_on_opus_with_an_empty_escalation_denied(self) -> None:
        self.assertIn("Escalated", self.agent("delegate:worker", "x\nEscalated:", "opus"))

    def test_worker_on_opus_with_escalation_allowed(self) -> None:
        self.assertEqual(self.agent("delegate:worker", "Brief: /b.md\nEscalated: sonnet failed twice", "opus"), "")

    def test_thinker_on_opus_allowed(self) -> None:
        self.assertEqual(self.agent("delegate:thinker", model="opus"), "")

    def test_long_prompt_without_brief_gets_a_note(self) -> None:
        self.assertIn("Brief", self.agent("delegate:worker", "a" * 3500))

    def test_non_agent_tool_ignored(self) -> None:
        event = {"tool_name": "Bash", "cwd": ".", "tool_input": {"command": "ls"}}
        self.assertEqual(run_hook(GUARD, json.dumps(event), {"RELAY_HOME": self.home}, cwd=self.cwd), "")

    def test_typed_only_false_allows_general_purpose(self) -> None:
        os.makedirs(os.path.join(self.cwd, ".claude"))
        with open(os.path.join(self.cwd, ".claude", "kit.toml"), "w") as handle:
            handle.write("[delegate]\ntyped_only = false\n")
        self.assertEqual(self.agent("general-purpose"), "")

    def test_fork_over_limit_denied(self) -> None:
        t = os.path.join(self.home, "t.jsonl")
        usage = {"input_tokens": 1000, "cache_read_input_tokens": 150000, "cache_creation_input_tokens": 0, "output_tokens": 5}
        with open(t, "w") as handle:
            handle.write(json.dumps({"type": "assistant", "message": {"usage": usage}}) + "\n")
        self.assertIn('"deny"', self.agent("fork", transcript_path=t))

    def test_malformed_input_fails_open(self) -> None:
        self.assertEqual(run_hook(GUARD, "not json", {"RELAY_HOME": self.home}, cwd=self.cwd), "")


if __name__ == "__main__":
    unittest.main()
