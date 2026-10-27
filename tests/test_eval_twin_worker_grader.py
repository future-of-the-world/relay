"""Queue item the-twin-cases-no-spec-step-and-no-spec-step-ru.

The three cases no-spec-step, no-spec-step-ru and no-spec-step-typo share one prompt that stops at the first
agent's reply, so a correct run that sends a delegate:scout first has a scout as its only agent. Each case's
worker-started grader must accept a plain scout or worker and reject every other agent (principle 6: the rule,
not the one case the typo fix covered).
"""
import json
import os
import unittest

from test_wave_red import ROOT, js_match

CASES = ("no-spec-step", "no-spec-step-ru", "no-spec-step-typo")


def pattern(case: str) -> str:
    path = os.path.join(ROOT, "evals", "plugin", case, "graders", "worker-started.md")
    with open(path, encoding="utf-8") as handle:
        head = handle.read().split("\n---\n")[0]
    line = next(x for x in head.split("\n") if x.startswith("input_match:"))
    return json.loads(line.partition(":")[2].strip())


def agent(kind: str) -> str:
    return json.dumps({"description": "x", "subagent_type": kind, "prompt": "Find product list code"})


class TwinWorkerStarted(unittest.TestCase):
    def test_a_scout_or_a_worker_counts(self) -> None:
        for case in CASES:
            self.assertTrue(js_match(pattern(case), agent("delegate:scout")), case)
            self.assertTrue(js_match(pattern(case), agent("delegate:worker")), case)

    def test_other_agents_do_not_count(self) -> None:
        for case in CASES:
            for kind in ("openspec:plan", "openspec:author", "Explore", "general-purpose"):
                self.assertFalse(js_match(pattern(case), agent(kind)), f"{case} {kind}")

    def test_the_three_cases_carry_the_same_pattern(self) -> None:
        self.assertEqual(len({pattern(c) for c in CASES}), 1)


if __name__ == "__main__":
    unittest.main()
