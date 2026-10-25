"""The wave paid run of e905742 (queue item the-wave-paid-run-of-e905742-is-red-in-9-eval-ca), finding Q1.

Every no-spec-step case failed its "no-openspec-command" grader because the pattern `\\bopenspec\\b`
matched a harmless `find .claude openspec docs` (a read of the project's docs folder), not only the
program `openspec`. These tests run each case's pattern over the JSON the grader sees for a Bash call
(`{"command": "..."}`) and need no paid run.
"""
import glob
import json
import os
import re
import subprocess
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CASES = ("no-spec-step", "no-spec-step-ru", "no-spec-step-typo")


def input_match(case: str) -> str:
    path = os.path.join(ROOT, "evals", "plugin", case, "graders", "no-openspec-command.md")
    with open(path, encoding="utf-8") as handle:
        head = handle.read().split("\n---\n")[0]
    line = next(x for x in head.split("\n") if x.startswith("input_match:"))
    return json.loads(line.partition(":")[2].strip())


def js_match(pattern: str, text: str) -> bool:
    """The eval tool applies input_match as a JavaScript RegExp: test it the same way (as tests/test_eval_record.py does)."""
    code = "const [p,t]=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(String(new RegExp(p).test(t)))"
    out = subprocess.run(["bun", "-e", code], input=json.dumps([pattern, text]), capture_output=True, text=True, check=True)
    return out.stdout == "true"


def hit(case: str, command: str) -> bool:
    return js_match(input_match(case), json.dumps({"command": command}, separators=(",", ":")))


class NoOpenspecCommand(unittest.TestCase):
    def test_reading_the_openspec_folder_is_not_a_command(self) -> None:
        # The run's own second command: `openspec` here is a folder name, so the grader must stay quiet.
        for case in CASES:
            for command in ("find .claude openspec docs -type f | head -40", "ls openspec/changes",
                            "cat openspec/config.yaml", "grep -rn sort openspec/specs"):
                self.assertFalse(hit(case, command), (case, command))

    def test_running_the_openspec_program_is_caught(self) -> None:
        # The program at the start, after && or ;, on a later line, or through npx; and a /opsx: command.
        for case in CASES:
            for command in ("openspec new change sort-by-name", "cd .worktrees/x && openspec validate x --strict",
                            "ls; openspec list", "ls\nopenspec list", "npx openspec init", "echo /opsx:propose x",
                            # F3: sessions really write VAR=value or env before the program.
                            "OPENSPEC_TELEMETRY=0 openspec validate x --strict", "env FOO=1 openspec list",
                            "A=1 B=2 npx openspec init"):
                self.assertTrue(hit(case, command), (case, command))

    def test_the_three_cases_share_one_pattern(self) -> None:
        self.assertEqual(len({input_match(case) for case in CASES}), 1)
        self.assertEqual(len(glob.glob(os.path.join(ROOT, "evals", "plugin", "no-spec-step*"))), len(CASES))


class NoWorkerBeforePlan(unittest.TestCase):
    """spec-step-on*: the grader was a meaning grader, which reads only the last message and cannot see the order of calls."""

    def test_it_is_a_tool_check_that_catches_a_worker_launch_only(self) -> None:
        for case in ("spec-step-on", "spec-step-on-en", "spec-step-on-ru", "spec-step-on-typo"):
            path = os.path.join(ROOT, "evals", "plugin", case, "graders", "no-worker-before-plan.md")
            with open(path, encoding="utf-8") as handle:
                head = handle.read().split("\n---\n")[0]
            meta = dict(x.split(": ", 1) for x in head.split("\n")[1:])
            self.assertEqual((meta["type"], meta["tool"], meta["max"]), ("tool_used", "Agent", "0"), case)
            pattern = json.loads(meta["input_match"])
            worker = json.dumps({"description": "build", "subagent_type": "delegate:worker", "prompt": "x"})
            scout = json.dumps({"description": "look", "subagent_type": "delegate:scout", "prompt": "x"})
            self.assertTrue(js_match(pattern, worker), case)
            self.assertFalse(js_match(pattern, scout), case)


class OffbyoneScaffold(unittest.TestCase):
    """code-reviewer-offbyone: the hook hands the critic .claude/kit/critic.md from the tree the session stands on (master)."""

    def test_the_project_rule_is_on_master_not_only_on_the_branch(self) -> None:
        script = os.path.join(ROOT, "evals", "plugin", "code-reviewer-offbyone", "scaffold.sh")
        with tempfile.TemporaryDirectory() as work:
            subprocess.run(["bash", script], cwd=work, check=True, capture_output=True)

            def git(*args: str) -> str:
                return subprocess.run(["git", *args], cwd=work, check=True, capture_output=True, text=True).stdout

            self.assertEqual(git("branch", "--show-current").strip(), "master")
            # The session reads the checked-out tree: the rule file is there, with the label the grader looks for.
            with open(os.path.join(work, ".claude", "kit", "critic.md"), encoding="utf-8") as handle:
                self.assertIn("DOC-RULE", handle.read())
            # The branch changes only the code under review, not the rule (else the rule is on the branch only).
            self.assertEqual(sorted(git("diff", "--name-only", "master...wt/paging").split()),
                             ["src/shelf.test.ts", "src/shelf.ts"])


class ItTermsSetup(unittest.TestCase):
    """it-terms-es/-ru: the eval runner does not load the scaffold's CLAUDE.md into the session (measured: a probe
    case with CLAUDE.md, CLAUDE.local.md and .claude/CLAUDE.md, none of the three rules was followed), so the
    rule reaches the model only when the prompt sends it to read the file."""

    def test_the_prompt_sends_the_session_to_read_the_rule_file_and_allows_the_read(self) -> None:
        for case in ("it-terms-es", "it-terms-ru"):
            directory = os.path.join(ROOT, "evals", "plugin", case)
            with open(os.path.join(directory, "prompt.md"), encoding="utf-8") as handle:
                head, body = handle.read().split("\n---\n", 1)
            self.assertIn("CLAUDE.md", body, case)
            self.assertIn("allowed_tools: [Read]", head, case)
            # Read is one turn, the reply another: three turns left the model no room to answer.
            turns = int(next(x for x in head.split("\n") if x.startswith("max_turns:")).split(":")[1])
            self.assertGreaterEqual(turns, 4, case)
            with tempfile.TemporaryDirectory() as work:
                subprocess.run(["bash", os.path.join(directory, "scaffold.sh")], cwd=work, check=True, capture_output=True)
                with open(os.path.join(work, "CLAUDE.md"), encoding="utf-8") as handle:
                    self.assertIn("Standard IT terms stay in their English form", handle.read(), case)


class ItTermsPromptsDoNotGiveTheAnswer(unittest.TestCase):
    """F4/F5: a pass must show the rule at work, not the prompt or the rule text dictating the reply."""

    def test_ru_prompt_names_gate_without_defining_or_asking_for_it(self) -> None:
        with open(os.path.join(ROOT, "evals", "plugin", "it-terms-ru", "prompt.md"), encoding="utf-8") as handle:
            body = handle.read().split("\n---\n", 1)[1]
        self.assertIn("gate", body)
        self.assertIn("CLAUDE.md", body)
        for given in ("линтер", "проверка типов", "проверку типов", "что такое gate"):
            self.assertNotIn(given, body)

    def test_rule_does_not_prescribe_the_terms_of_a_merge_reply(self) -> None:
        with open(os.path.join(ROOT, "rules", "working-with-me.md"), encoding="utf-8") as handle:
            text = " ".join(handle.read().split())
        self.assertNotIn("A reply that explains a merge", text)
        self.assertNotIn("страховка", text)
        self.assertNotIn("gancho", text)
        self.assertIn("even when my own message uses the local word", text)
        self.assertIn("ветка", text)
        self.assertIn("rama", text)


if __name__ == "__main__":
    unittest.main()
