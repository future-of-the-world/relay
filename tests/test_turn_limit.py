"""Q1: an agent that waits on a long job must not die silently at its turn limit.
Free: reads the role sources and the assembled agent files."""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class TurnLimitWait(unittest.TestCase):
    def test_q1_builders_and_fixers_hand_back_still_running_before_the_limit(self) -> None:
        """Q1: the worker on wt/wave-red polled a test run and stopped at its 81st tool use with no hand-back.
        Every build and fix agent (maxTurns 80) must be told: one call per wait, and with 8 turns left write the
        report and hand back BLOCKED with `still running: <log>`."""
        seen = 0
        for path in sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "agents", "*.md"))):
            text = read(os.path.relpath(path, ROOT))
            if not re.search(r"<!-- relay:base (build|fix) -->", text):  # the base that carries the budget part
                continue
            seen += 1
            self.assertIn("still running: <log>", text, path)
            self.assertIn("8 turns", text, path)
        self.assertGreaterEqual(seen, 2)  # worker and fixer; the checker has the judge base and writes early

    def test_q1_runner_replies_running_with_the_log_before_its_12_turns_end(self) -> None:
        """Q1: a runner waiting on a gate stopped at its 12th turn three times. It is told to reply RUNNING with the log
        path while 2 turns remain, so the step that started the job gets a result instead of a crash."""
        text = read("plugins", "delegate", "agents", "runner.md")
        self.assertIn("12 turns", text)
        self.assertIn("2 turns", text)
        self.assertIn("RUNNING", text)

    def test_the_sources_carry_the_same_rule(self) -> None:
        self.assertIn("still running: <log>", read("roles", "parts", "budget.md"))
        self.assertIn("{maxTurns}", read("roles", "run.md"))


if __name__ == "__main__":
    unittest.main()
