"""Queue item no-spec-step-typo-fails-one-run-in-three.

The request does not say where the list lives (typo or not), so in 2 of 18 kept-trace runs the coordinator
started a delegate:scout to find it; the prompt stops at the first agent's reply, so no worker followed and the
worker-started grader (pattern "delegate:worker") failed a correct run. The grader now accepts a plain delegate
scout or worker and still rejects an openspec agent and a run that started no agent.
"""
import json
import os
import unittest

from test_wave_red import ROOT, input_match, js_match


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


def command_input(command: str, description: str) -> str:
    return json.dumps({"command": command, "description": description}, separators=(",", ":"))


class NoOpenspecCommandReadsOnlyTheCommand(unittest.TestCase):
    """Review F1: the grader fired on a Bash description such as "(openspec folder too)"."""

    def test_a_description_naming_openspec_is_not_a_command(self) -> None:
        for case in ("no-spec-step", "no-spec-step-ru", "no-spec-step-typo"):
            text = command_input("ls -la", "List the project (openspec folder too)")
            self.assertFalse(js_match(input_match(case), text), case)

    def test_real_commands_still_match_and_folder_reads_do_not(self) -> None:
        for case in ("no-spec-step", "no-spec-step-ru", "no-spec-step-typo"):
            pat = input_match(case)
            self.assertTrue(js_match(pat, command_input("git log --oneline; openspec list", "x")), case)
            self.assertTrue(js_match(pat, command_input("(openspec list)", "x")), case)
            self.assertTrue(js_match(pat, command_input("openspec list", "x")), case)
            self.assertFalse(js_match(pat, command_input("ls openspec/changes", "List changes")), case)
