"""Queue item no-spec-step-typo-fails-one-run-in-three.

The typo prompt ("список товароф") does not say which list is meant, so in 2 of 18 kept-trace runs the coordinator
started a delegate:scout to find it; the prompt stops at the first agent's reply, so no worker followed and the
worker-started grader (pattern "delegate:worker") failed a correct run. The grader now accepts a plain delegate
scout or worker and still rejects an openspec agent and a run that started no agent.
"""
import json
import os
import unittest

from test_wave_red import ROOT, js_match


def pattern() -> str:
    path = os.path.join(ROOT, "evals", "plugin", "no-spec-step-typo", "graders", "worker-started.md")
    with open(path, encoding="utf-8") as handle:
        head = handle.read().split("\n---\n")[0]
    line = next(x for x in head.split("\n") if x.startswith("input_match:"))
    return json.loads(line.partition(":")[2].strip())


def agent(kind: str) -> str:
    return json.dumps({"description": "x", "subagent_type": kind, "prompt": "Implement the brief."})


class TypoWorkerStarted(unittest.TestCase):
    def test_a_worker_or_a_scout_first_start_counts(self) -> None:
        # Failing traces (e-W2XJtZ, e-KlOX6s): the only Agent call was subagent_type delegate:scout.
        self.assertTrue(js_match(pattern(), agent("delegate:worker")))
        self.assertTrue(js_match(pattern(), agent("delegate:scout")))

    def test_an_openspec_or_other_agent_does_not_count(self) -> None:
        for kind in ("openspec:plan", "openspec:author", "Explore", "general-purpose", "delegate:thinker"):
            self.assertFalse(js_match(pattern(), agent(kind)), kind)
