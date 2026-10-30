"""Port of plugins/observe/tests/ledger.test.sh: the ledger hook's records."""
import glob
import json
import os
import re
import tempfile
import unittest
from typing import Dict, Optional

from hook_helpers import ROOT, run_hook, SoftCases

HOOK = os.path.join(ROOT, "plugins", "observe", "hooks", "ledger.py")
TRANSCRIPT_LINE = {"type": "assistant", "timestamp": "2026-10-19T10:00:00Z", "requestId": "r1",
                   "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 100, "cache_read_input_tokens": 50000,
                                                                       "cache_creation_input_tokens": 0, "output_tokens": 5}}}


class Ledger(SoftCases):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.extra_env: Dict[str, str] = {}
        os.makedirs(os.path.join(self.home, "s", "subagents"))
        self.t = os.path.join(self.home, "s.jsonl")
        self.write(self.t, json.dumps(TRANSCRIPT_LINE) + "\n")
        self.write(os.path.join(self.home, "s", "subagents", "agent-a1.jsonl"), json.dumps(TRANSCRIPT_LINE) + "\n")

    def write(self, path: str, text: str) -> None:
        with open(path, "w") as handle:
            handle.write(text)

    def send(self, event: object) -> None:
        text = event if isinstance(event, str) else json.dumps(event)
        run_hook(HOOK, text, dict({"RELAY_HOME": self.home}, **self.extra_env))

    def ledger(self) -> str:
        out = ""
        for path in sorted(glob.glob(os.path.join(self.home, "ledger", "*.jsonl"))):
            with open(path) as handle:
                out += handle.read()
        return out

    def has(self, pattern: str) -> None:
        self.assertTrue(re.search(pattern, self.ledger()), "no %r in the ledger" % pattern)

    def count(self, pattern: str) -> int:
        return sum(1 for ln in self.ledger().splitlines() if re.search(pattern, ln))

    def pre(self, tool_use_id: str, prompt: Optional[str], subagent: str = "delegate:worker", model: str = "opus") -> None:
        tool_input = {"subagent_type": subagent, "model": model}
        if prompt is not None:
            tool_input["prompt"] = prompt
        self.send({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": "/p", "tool_name": "Agent",
                   "tool_use_id": tool_use_id, "tool_input": tool_input})

    def prompt(self, text: str, prompt_id: str, **extra: object) -> None:
        self.send(dict({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "/p", "prompt": text, "prompt_id": prompt_id}, **extra))

    def test_session_start_with_model(self) -> None:
        self.send({"hook_event_name": "SessionStart", "session_id": "s", "cwd": "/p", "source": "startup", "model": "claude-opus-5"})
        self.has(r'"event": "session_start".*"model": "claude-opus-5"')

    def test_prompt_with_slash_and_no_text(self) -> None:
        self.prompt("/opsx:apply x", "p1")
        self.has(r'"slash": "/opsx:apply"')
        self.assertNotIn('"text"', self.ledger())

    def test_agent_start_stop_and_stop_context(self) -> None:
        self.send({"hook_event_name": "SubagentStart", "session_id": "s", "cwd": "/p", "agent_id": "a1", "agent_type": "delegate:scout",
                   "effort": {"level": "low"}, "agent_prompt": "abc"})
        self.has(r'"agent_type": "delegate:scout".*"effort": "low"')
        self.send({"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "a1", "agent_type": "delegate:scout",
                   "transcript_path": self.t, "last_assistant_message": "done"})
        self.has(r'"event": "agent_stop".*"requests": 1')  # reads the agent transcript by fallback
        self.send({"hook_event_name": "Stop", "session_id": "s", "cwd": "/p", "transcript_path": self.t, "last_assistant_message": "hello"})
        self.has(r'"event": "stop".*"context": 50100')  # 100 input + 50000 cache read

    def test_workflow_agent_without_a_start_hook_still_gets_a_start_event(self) -> None:
        # Claude Code sent no SubagentStart for this workflow agent: only the stop arrives. The ledger must still hold
        # one agent_start (stamped with the agent's first transcript line, 10:00:00Z) before the one agent_stop.
        folder = os.path.join(self.home, "sub", "workflows", "wf_abc")
        os.makedirs(folder)
        transcript = os.path.join(folder, "agent-w1.jsonl")
        self.write(transcript, json.dumps(TRANSCRIPT_LINE) + "\n")
        stop = {"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "w1", "agent_type": "delegate:runner",
                "agent_transcript_path": transcript}
        self.send(stop)
        self.assertEqual(self.count(r'"event": "agent_start".*"agent_id": "w1"'), 1)
        self.assertEqual(self.count(r'"event": "agent_stop".*"agent_id": "w1"'), 1)
        self.has(r'"ts": "2026-10-19T10:00:00Z", "event": "agent_start"')

    def test_stop_without_type_or_transcript_is_a_side_call_not_an_agent_stop(self) -> None:
        # The shape of 222 of 222 unmatched stops on 29 Oct: empty agent_type, no agent transcript anywhere.
        self.send({"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "zz9", "agent_type": "",
                   "transcript_path": os.path.join(self.home, "none.jsonl"), "last_assistant_message": "x" * 35})
        self.assertEqual(self.count(r'"event": "agent_stop"'), 0)  # no agent_stop left without an agent_start
        self.assertEqual(self.count(r'"event": "side_call".*"agent_id": "zz9".*"reply_chars": 35'), 1)

    def test_typed_agent_without_transcript_is_still_an_agent_stop(self) -> None:
        self.send({"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "r9", "agent_type": "delegate:runner",
                   "transcript_path": os.path.join(self.home, "none.jsonl"), "last_assistant_message": "hello"})
        self.assertEqual(self.count(r'"event": "agent_stop".*"agent_id": "r9".*"reply_chars": 5'), 1)

    def test_has_start_scans_each_day_file_once_and_finds_either_day(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ledger_hook", HOOK)
        mod = importlib.util.module_from_spec(spec)
        old = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = self.home
        self.addCleanup(lambda: os.environ.pop("RELAY_HOME") if old is None else os.environ.__setitem__("RELAY_HOME", old))
        spec.loader.exec_module(mod)
        # relay_ledger is cached per process and binds ledger_dir at its first import: a test that imported it under a patched
        # relay_config.ledger_dir (test_metrics) left it pointing elsewhere. Point it at this test's home, as the hook run sees it.
        real_dir = mod.relay_ledger.ledger_dir
        mod.relay_ledger.ledger_dir = lambda: os.path.join(self.home, "ledger")
        self.addCleanup(setattr, mod.relay_ledger, "ledger_dir", real_dir)
        opened = []
        real = open
        mod.open = lambda p, *a, **k: (opened.append(p), real(p, *a, **k))[1]
        self.assertFalse(mod.has_start("w1", "2026-10-19T10:00:00Z", "2026-10-19T11:00:00Z"))
        self.assertEqual(len(opened), 1)  # same day: one open
        os.makedirs(os.path.join(self.home, "ledger"), exist_ok=True)
        self.write(os.path.join(self.home, "ledger", "2026-10-20.jsonl"), '{"event": "agent_start", "agent_id": "w1"}\n')
        self.assertTrue(mod.has_start("w1", "2026-10-19T23:59:00Z", "2026-10-20T00:01:00Z"))

    def test_a_recorded_start_is_not_doubled_by_the_stop(self) -> None:
        # The start hook did fire: the stop must add no second start (the start is stamped now, the stop reads the same day file).
        self.send({"hook_event_name": "SubagentStart", "session_id": "s", "cwd": "/p", "agent_id": "a1", "agent_type": "delegate:scout"})
        self.send({"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "a1", "agent_type": "delegate:scout",
                   "transcript_path": self.t})
        self.assertEqual(self.count(r'"event": "agent_start"'), 1)

    def test_tool_pre_with_subagent_and_escalated_flag(self) -> None:
        self.send({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": "/p", "tool_name": "Agent", "tool_use_id": "t1",
                   "tool_input": {"subagent_type": "delegate:worker", "model": "sonnet"}})
        self.has(r'"subagent_type": "delegate:worker"')
        self.pre("t2", "line one\nEscalated: needs depth")
        self.has(r'"prompt_chars": 31, "escalated": true')
        self.pre("t3", "Not Escalated: here", "delegate:scout", "sonnet")
        self.has(r'"prompt_chars": 19, "escalated": false')
        self.assertNotIn("needs depth", self.ledger())  # the agent prompt text is not stored

    def test_escalation_is_read_as_the_route_guard_reads_it(self) -> None:
        self.pre("t4", "x\n  escalated: lower case counts")
        self.has(r'"tool_use_id": "t4".*"escalated": true')
        self.pre("t5", "x\nEscalated:")  # an empty reason is not an escalation
        self.has(r'"tool_use_id": "t5".*"escalated": false')

    def test_prompt_kinds(self) -> None:
        self.prompt("<task-notification>done</task-notification>", "p2")
        self.has(r'"kind": "notification"')
        self.prompt("owner words", "p0")
        self.has(r'"kind": "owner"')
        self.prompt("the hook still fires on <task-notification> prompts, fix it", "p3")
        self.has(r'"prompt_id": "p3".*"kind": "owner"')  # an owner quoting a marker is still the owner
        self.prompt("anything", "p4", origin={"kind": "task-notification"})
        self.has(r'"prompt_id": "p4".*"kind": "notification"')

    def test_reply_length_is_the_handback_message_or_null(self) -> None:
        handback = {"type": "assistant", "timestamp": "2026-10-19T10:00:00Z", "requestId": "r9",
                    "message": {"model": "claude-haiku-5", "content": [{"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": "DONE ok"}}],
                                "usage": {"input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 5}}}
        self.write(os.path.join(self.home, "s", "subagents", "agent-a2.jsonl"), json.dumps(handback) + "\n")
        self.send({"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "a2", "agent_type": "delegate:scout",
                   "transcript_path": self.t, "last_assistant_message": "text before the hand-back that the caller never sees"})
        self.has(r'"agent_id": "a2".*"reply_chars": 7')  # len("DONE ok") = 7
        self.send({"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "a3", "agent_type": "delegate:scout", "transcript_path": self.t})
        self.has(r'"agent_id": "a3".*"reply_chars": null')

    def claude_json(self, projects: dict) -> None:
        path = os.path.join(self.home, "claude.json")
        self.write(path, json.dumps({"projects": projects}))
        self.extra_env["RELAY_CLAUDE_JSON"] = path

    @staticmethod
    def usage(tokens: int) -> dict:
        return {"claude-opus-5-5": {"inputTokens": 1, "outputTokens": tokens, "costUSD": 0.1}}

    def test_session_start_copies_last_finished_totals_once(self) -> None:
        self.claude_json({"/p": {"lastSessionId": "old1", "lastModelUsage": self.usage(5683)}})
        self.send({"hook_event_name": "SessionStart", "session_id": "s", "cwd": "/p", "source": "startup"})
        self.has(r'"event": "session_usage".*"session_id": "old1".*"output_tokens": 5683')
        self.send({"hook_event_name": "SessionStart", "session_id": "s2", "cwd": "/p", "source": "startup"})
        self.assertEqual(self.count('"session_usage"'), 1)

    def test_new_session_does_not_copy_itself_but_a_resumed_one_does(self) -> None:
        self.claude_json({"/q": {"lastSessionId": "res1", "lastModelUsage": self.usage(777)}})
        self.send({"hook_event_name": "SessionStart", "session_id": "res1", "cwd": "/q", "source": "startup"})
        self.assertEqual(self.count('"session_usage".*"session_id": "res1"'), 0)
        self.send({"hook_event_name": "SessionStart", "session_id": "res1", "cwd": "/q", "source": "resume"})
        self.has(r'"event": "session_usage".*"session_id": "res1".*"output_tokens": 777')

    def test_session_end_copies_only_its_own_session(self) -> None:
        self.claude_json({"/r": {"lastSessionId": "end1", "lastModelUsage": self.usage(888)},
                          "/q": {"lastSessionId": "other", "lastModelUsage": self.usage(999)}})
        self.send({"hook_event_name": "SessionEnd", "session_id": "end1", "cwd": "/r", "reason": "other"})
        self.has(r'"event": "session_usage".*"session_id": "end1".*"output_tokens": 888')
        self.send({"hook_event_name": "SessionEnd", "session_id": "end2", "cwd": "/q", "reason": "other"})
        self.assertNotIn('"output_tokens": 999', self.ledger())

    def test_malformed_input_fails_open(self) -> None:
        self.send("garbage")  # must not raise; nothing to assert on beyond the hook returning


if __name__ == "__main__":
    unittest.main()
