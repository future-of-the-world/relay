"""Port of plugins/front/tests/budget.test.sh: the budget and handover hooks."""
import json
import os
import tempfile
import unittest

from hook_helpers import ROOT, run_hook

HOOKS = os.path.join(ROOT, "plugins", "front", "hooks")


def line(cache_read: int) -> str:
    usage = {"input_tokens": 100, "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 0, "output_tokens": 5}
    return json.dumps({"type": "assistant", "timestamp": "2026-10-19T10:00:00Z", "message": {"usage": usage}}) + "\n"


class Budget(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.t = os.path.join(self.home, "s.jsonl")

    def send(self, hook: str, event: dict) -> str:
        return run_hook(os.path.join(HOOKS, hook), json.dumps(event), {"RELAY_HOME": self.home})

    def write(self, path: str, text: str) -> None:
        with open(path, "w") as handle:
            handle.write(text)

    def prompt(self) -> dict:
        return {"hook_event_name": "UserPromptSubmit", "session_id": "s", "transcript_path": self.t, "cwd": "/tmp"}

    def test_under_the_line_silent(self) -> None:
        self.write(self.t, line(100000))
        self.assertEqual(self.send("budget.py", self.prompt()), "")

    def test_over_the_line_handover_note_then_silent_by_marker(self) -> None:
        self.write(self.t, line(360000))
        self.assertIn("handover", self.send("budget.py", self.prompt()))
        # a second prompt over the line: the marker keeps it silent
        self.assertEqual(self.send("budget.py", self.prompt()), "")

    def test_big_agent_wrap_note_once_per_step(self) -> None:
        os.makedirs(os.path.join(self.home, "sess", "subagents"))
        a = os.path.join(self.home, "sess", "subagents", "agent-a1.jsonl")
        self.write(a, line(250000))
        event = {"hook_event_name": "PostToolUse", "session_id": "s", "agent_id": "a1",
                 "transcript_path": os.path.join(self.home, "sess.jsonl"), "agent_transcript_path": a, "tool_name": "Read"}
        self.assertIn("hand back", self.send("budget.py", event))
        self.assertEqual(self.send("budget.py", event), "")

    def project(self) -> str:
        proj = os.path.join(self.home, "proj")
        os.makedirs(os.path.join(proj, "docs"))
        self.write(os.path.join(proj, "docs", "handover.md"), "state\n")
        return proj

    def test_compact_names_the_handover_file(self) -> None:
        event = {"hook_event_name": "SessionStart", "source": "compact", "cwd": self.project()}
        self.assertIn("handover.md", self.send("handover.py", event))

    def test_no_handover_file_silent(self) -> None:
        event = {"hook_event_name": "SessionStart", "source": "compact", "cwd": "/tmp"}
        self.assertEqual(self.send("handover.py", event), "")

    def test_resume_warns_about_the_cache(self) -> None:
        event = {"hook_event_name": "SessionStart", "source": "resume", "cwd": self.project(), "prompt_cache_likely_expired": True,
                 "estimated_cache_write_usd": 1.2, "context_tokens": 180000}
        self.assertIn("cheaper", self.send("handover.py", event))


if __name__ == "__main__":
    unittest.main()
