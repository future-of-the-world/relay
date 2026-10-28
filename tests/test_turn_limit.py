"""Q1: an agent that waits on a long job must not die silently at its turn limit.
Free: reads the role sources and the assembled agent files."""
import glob
import os
import re
import unittest

import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_gate import Fixture, git, read, write  # noqa: E402


def read_repo(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class TurnLimitWait(unittest.TestCase):
    def test_q1_builders_and_fixers_hand_back_still_running_before_the_limit(self) -> None:
        """Q1: the worker on wt/wave-red polled a test run and stopped at its 81st tool use with no hand-back.
        Every build and fix agent (maxTurns 80) must be told: one call per wait, and with 8 turns left write the
        report and hand back BLOCKED with `still running: <log>`."""
        seen = 0
        for path in sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "agents", "*.md"))):
            text = read_repo(os.path.relpath(path, ROOT))
            if not re.search(r"<!-- relay:base (build|fix) -->", text):  # the base that carries the budget part
                continue
            seen += 1
            self.assertIn("still running: <log>", text, path)
            self.assertIn("8 turns", text, path)
        self.assertGreaterEqual(seen, 2)  # worker and fixer; the checker has the judge base and writes early

    def test_q1_runner_replies_running_with_the_log_before_its_12_turns_end(self) -> None:
        """Q1: a runner waiting on a gate stopped at its 12th turn three times. It is told to reply RUNNING with the log
        path while 2 turns remain, so the step that started the job gets a result instead of a crash."""
        text = read_repo("plugins", "delegate", "agents", "runner.md")
        self.assertIn("12 turns", text)
        self.assertIn("2 turns", text)
        self.assertIn("RUNNING", text)

    def test_the_sources_carry_the_same_rule(self) -> None:
        self.assertIn("still running: <log>", read_repo("roles", "parts", "budget.md"))
        self.assertIn("{maxTurns}", read_repo("roles", "run.md"))


class RunningHandling(unittest.TestCase):
    def test_f2_delegate_skill_says_what_to_do_with_running_and_still_running(self) -> None:
        """F2: a runner reply RUNNING <log> and a hand-back BLOCKED ... still running: <log> leave the job running; a
        fresh runner waits on it; the gate is never started twice. The 30-minute rule stays."""
        text = " ".join(read_repo("plugins", "delegate", "skills", "delegate", "SKILL.md").split())
        self.assertIn("RUNNING with a log leaves the job running", text)
        self.assertIn("never start the gate again", text)
        self.assertIn("still running: <log>", text)
        self.assertIn("longer than about 30 minutes", text)


class TurnCountHook(unittest.TestCase):
    """F3: code, not the model, counts an agent's tool calls and says when few turns remain."""
    HOOK = os.path.join(ROOT, "plugins", "delegate", "hooks", "turn-limit.py")

    def run_hook(self, agent_type: str, prior_calls: int, agent_id: str = "a1") -> dict:
        """Run the hook as Claude Code does: JSON on stdin; the agent's transcript has `prior_calls` tool_use entries."""
        import json
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            session = os.path.join(tmp, "s1.jsonl")
            folder = os.path.join(tmp, "s1", "subagents")
            os.makedirs(folder)
            open(session, "w").close()
            with open(os.path.join(folder, "agent-%s.jsonl" % agent_id), "w", encoding="utf-8") as handle:
                for number in range(prior_calls):
                    handle.write(json.dumps({"type": "assistant", "message": {"content": [
                        {"type": "text", "text": "step"}, {"type": "tool_use", "id": "t%d" % number, "name": "Bash", "input": {}}]}}) + "\n")
                    handle.write(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t%d" % number}]}}) + "\n")
            data = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "transcript_path": session, "agent_id": agent_id, "agent_type": agent_type}
            done = subprocess.run([sys.executable, self.HOOK], input=json.dumps(data), capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0)
        return json.loads(done.stdout) if done.stdout.strip() else {}

    def context(self, out: dict) -> str:
        return out["hookSpecificOutput"]["additionalContext"]

    def test_f3_worker_at_its_72nd_call_is_told_to_hand_back(self) -> None:
        # worker maxTurns is 80; 71 calls are in the transcript, so the current one is the 72nd: 8 left.
        out = self.run_hook("delegate:worker", 71)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertIn("still running: <log>", self.context(out))
        self.assertIn("72 of 80", self.context(out))

    def test_f3_worker_at_its_40th_call_gets_nothing(self) -> None:
        self.assertEqual(self.run_hook("delegate:worker", 39), {})

    def test_f3_worker_at_its_71st_call_gets_nothing(self) -> None:
        # one before the line (80 - 8 = 72)
        self.assertEqual(self.run_hook("delegate:worker", 70), {})

    def test_f3_runner_is_told_at_its_10th_call(self) -> None:
        # runner maxTurns is 12: the line is 12 - 2 = 10; the 9th call gets nothing.
        self.assertIn("10 of 12", self.context(self.run_hook("delegate:runner", 9)))
        self.assertEqual(self.run_hook("delegate:runner", 8), {})

    def test_f3_the_main_session_gets_nothing(self) -> None:
        import json
        import subprocess
        data = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "transcript_path": "/nonexistent.jsonl"}
        done = subprocess.run([sys.executable, self.HOOK], input=json.dumps(data), capture_output=True, text=True, timeout=30)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_f3_an_agent_of_another_plugin_gets_nothing(self) -> None:
        self.assertEqual(self.run_hook("openspec:author", 79), {})

    def test_f3_the_hook_is_registered(self) -> None:
        self.assertIn("hooks/turn-limit.py", read_repo("plugins", "delegate", "hooks", "hooks.json"))


class GateReuse(Fixture):
    """F1: a green gate on the same code (only inert files changed since) is reported, not run again.
    The gate script appends a line to a counter file outside the repo each time it runs."""

    def setUp(self) -> None:
        super().setUp()
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate='echo ran >> "%s"\nexit "${GATE_EXIT:-0}"\n' % self.counter)

    def runs(self) -> int:
        return len(read(self.counter).splitlines()) if os.path.exists(self.counter) else 0

    def test_f1_second_gate_on_the_gate_log_commit_runs_nothing(self) -> None:
        # pass case 1: gate on G, then HEAD = G + its log commit (inert): 1 run in all, same log printed, exit 0
        head = git(self.wt, "rev-parse", "HEAD")
        first = self.gate(self.wt)
        second = self.gate(self.wt)
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(self.runs(), 1)
        self.assertEqual(second.stdout.splitlines()[-1], os.path.join(self.wt, ".relay", "checks", head + ".gate.log"))

    def test_f1_a_non_inert_change_after_the_green_gate_runs_again(self) -> None:
        # pass case 2: lib/b.py is code, so a second gate runs and logs on the new HEAD
        self.gate(self.wt)
        write(os.path.join(self.wt, "lib", "b.py"), "b\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "more")
        head = git(self.wt, "rev-parse", "HEAD")
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 2)
        self.assertTrue(os.path.exists(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))

    def test_f1_a_red_gate_is_reused_only_across_record_commits(self) -> None:
        # a finished red gate stands for its record commit (queue item a-gate-re-run-on-its-record-commit-starts-over):
        # the second gate on the log commit prints exit 1 and runs nothing (1 run); a code change after it runs again (2)
        self.env["GATE_EXIT"] = "1"
        self.assertEqual(self.gate(self.wt).returncode, 1)
        self.assertEqual(self.gate(self.wt).returncode, 1)
        self.assertEqual(self.runs(), 1)
        write(os.path.join(self.wt, "lib", "c.py"), "c\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "code")
        self.assertEqual(self.gate(self.wt).returncode, 1)
        self.assertEqual(self.runs(), 2)

    def test_f1_a_green_gate_with_other_arguments_is_not_reused(self) -> None:
        # pass case 4: --quick is a different cmd line from none
        self.gate(self.wt)
        self.assertEqual(self.gate(self.wt, "--", "--quick").returncode, 0)
        self.assertEqual(self.runs(), 2)

    def test_f1_no_gate_log_runs(self) -> None:
        # pass case 5: a fresh branch has no log
        self.assertEqual(self.gate(self.wt).returncode, 0)
        self.assertEqual(self.runs(), 1)


if __name__ == "__main__":
    unittest.main()
