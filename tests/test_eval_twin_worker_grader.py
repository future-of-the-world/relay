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

    def test_twin_descriptions_name_the_scout_start(self) -> None:
        # F1: the grader accepts a scout, so the description must say so.
        for case in ("no-spec-step", "no-spec-step-ru"):
            with open(os.path.join(ROOT, "evals", "plugin", case, "case.yaml"), encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("a plain delegate agent (a worker, or a scout that finds the list first)", text, case)

    def test_twin_graders_name_the_typo_twin_as_the_measured_case(self) -> None:
        # F2: the 2-of-18 count was measured on the typo twin, not on these cases.
        for case in ("no-spec-step", "no-spec-step-ru"):
            path = os.path.join(ROOT, "evals", "plugin", case, "graders", "worker-started.md")
            with open(path, encoding="utf-8") as handle:
                self.assertIn("on the typo twin no-spec-step-typo", handle.read(), case)


if __name__ == "__main__":
    unittest.main()
