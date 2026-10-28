"""Port of plugins/relay/tests/inject-addition.test.sh: hooks/inject-addition.sh over a temporary repository with a worktree.
INJECT_RECORD=<file> python3 tests/test_hook_inject_addition.py re-records inject-addition.golden (only from a hook known good)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from hook_helpers import ROOT, SoftCases

CORE = os.path.join(ROOT, "plugins", "relay")
HOOK = os.path.join(CORE, "hooks", "inject-addition.sh")
GOLDEN = os.path.join(CORE, "tests", "inject-addition.golden")
NAMES = "apply-review archive author fixer parallel-apply plan reviewer spec-conformance spec-review spec-reviewer worker".split()


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd, check=True, capture_output=True)


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def fire(event: dict, hook: str = HOOK) -> str:
    done = subprocess.run([hook], input=json.dumps(event), capture_output=True, text=True, encoding="utf-8")
    return done.stdout


def agent(name: str, cwd: str, hook: str = HOOK) -> str:
    return fire({"hook_event_name": "SubagentStart", "agent_type": name, "cwd": cwd}, hook)


def skill(name: str, cwd: str) -> str:
    return fire({"hook_event_name": "PostToolUse", "tool_name": "Skill", "tool_input": {"skill": name}, "cwd": cwd})


def prompt(text: str, cwd: str) -> str:
    return fire({"hook_event_name": "UserPromptSubmit", "prompt": text, "cwd": cwd})


def ctx(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"].get("additionalContext", "") if out.strip() else ""


def event_name(out: str) -> str:
    return json.loads(out)["hookSpecificOutput"].get("hookEventName", "") if out.strip() else ""


def kartoteka(base: str) -> str:
    """12 per-agent files and no role file."""
    k = os.path.join(base, "kartoteka")
    os.makedirs(os.path.join(k, ".claude", "kit"))
    git(k, "init", "-q", "-b", "master")
    for n in NAMES:
        write(os.path.join(k, ".claude", "kit", n + ".md"), "%s-MARK\nline two of %s\n" % (n, n))
    return k


def golden_out(k: str) -> str:
    out = []
    for n in NAMES:
        out.append("== agent openspec:%s\n%s" % (n, agent("openspec:" + n, k)))
        out.append("== skill openspec:%s\n%s" % (n, skill("openspec:" + n, k)))
        out.append("== prompt /openspec:%s\n%s" % (n, prompt("/openspec:%s go" % n, k)))
    return "".join(o if o.endswith("\n") or not o else o for o in (s + ("" if s.endswith("\n") else "\n") for s in out))


class Inject(SoftCases):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = os.path.realpath(tempfile.mkdtemp())
        cls.R = os.path.join(cls.tmp, "repo")
        os.makedirs(os.path.join(cls.R, "sub", "dir"))
        write(os.path.join(cls.R, ".claude", "kit", "worker.md"), "WORKER-RULE ПСК\nsecond line\n")
        write(os.path.join(cls.R, ".claude", "kit", "plan.md"), "PLAN-RULE\n")
        git(cls.R, "init", "-q", "-b", "master", ".")
        git(cls.R, "add", "-A")
        git(cls.R, "commit", "-q", "-m", "init")
        git(cls.R, "worktree", "add", "-q", ".worktrees/wt1", "-b", "wt/wt1")
        git(cls.R, "worktree", "add", "-q", ".worktrees/wt2", "-b", "wt/wt2")
        os.remove(os.path.join(cls.R, ".worktrees", "wt2", ".claude", "kit", "worker.md"))  # a branch lacking the file
        cls.K = kartoteka(cls.tmp)
        cls.J = os.path.join(cls.tmp, "withrole")
        shutil.copytree(cls.K, cls.J)
        write(os.path.join(cls.J, ".claude", "kit", "judge.md"), "JUDGE-MARK\n")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_agent(self) -> None:
        out = agent("openspec:worker", self.R)
        self.assertIn("WORKER-RULE ПСК", ctx(out))
        self.assertIn("second line", ctx(out))  # the whole file
        self.assertEqual(event_name(out), "SubagentStart")
        self.assertIn("openspec:worker", ctx(out))
        self.assertIn("WORKER-RULE", ctx(agent("openspec:worker", os.path.join(self.R, "sub", "dir"))))
        self.assertIn("WORKER-RULE", ctx(agent("openspec:worker", os.path.join(self.R, ".worktrees", "wt1"))))
        self.assertIn("WORKER-RULE", ctx(agent("relay:worker", self.R)))  # a relay: name is served too

    def test_agent_gets_nothing(self) -> None:
        for name, cwd in (("openspec:worker", os.path.join(self.R, ".worktrees", "wt2")),  # a worktree without the file
                          ("openspec:fixer", self.R), ("worker", self.R), ("general-purpose", self.R),
                          ("openspec:../../etc/passwd", self.R),  # the role cannot leave the folder
                          ("pr-review-toolkit:worker", self.R), ("other:plan", self.R), ("product:ui-reviewer", self.R),
                          ("openspec:worker", self.tmp)):
            self.assertEqual(agent(name, cwd), "", (name, cwd))

    def test_prompt(self) -> None:
        out = prompt("/openspec:plan add a low-stock view", self.R)
        self.assertIn("PLAN-RULE", ctx(out))
        self.assertEqual(event_name(out), "UserPromptSubmit")
        for text in ("/openspec:plan", "  /openspec:plan x"):
            self.assertIn("PLAN-RULE", ctx(prompt(text, self.R)), text)
        self.assertIn("PLAN-RULE", ctx(prompt("/openspec:plan x", os.path.join(self.R, ".worktrees", "wt1"))))
        for text in ("/openspec:archive", "/pr-review-toolkit:plan x", "/plan x", "/opsx:propose x", "please /openspec:plan this", "/openspec:planner x"):
            self.assertEqual(prompt(text, self.R), "", text)

    def test_skill_and_other_events(self) -> None:
        out = skill("openspec:plan", self.R)
        self.assertIn("PLAN-RULE", ctx(out))
        self.assertEqual(event_name(out), "PostToolUse")
        self.assertEqual(skill("openspec:archive", self.R), "")
        self.assertEqual(skill("plan", self.R), "")
        self.assertEqual(fire({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": self.R}), "")
        self.assertEqual(fire({"hook_event_name": "Stop", "cwd": self.R}), "")

    def test_I4_no_role_file_output_equals_the_golden_file(self) -> None:
        with open(GOLDEN, encoding="utf-8") as handle:
            self.assertEqual(golden_out(self.K), handle.read())

    def test_I1_judge_file_first_then_own(self) -> None:
        out = ctx(agent("openspec:spec-reviewer", self.J))
        self.assertLess(out.index("JUDGE-MARK"), out.index("spec-reviewer-MARK"))
        self.assertIn("Project rules for the judge role (.claude/kit/judge.md of this project)", out)
        self.assertIn("Project rules for openspec:spec-reviewer (.claude/kit/spec-reviewer.md); where they differ from the role's rules, these win", out)
        self.assertEqual(event_name(agent("openspec:spec-reviewer", self.J)), "SubagentStart")

    def test_I2_I3_agents_without_a_file_of_their_own(self) -> None:
        out = ctx(agent("delegate:critic", self.J))
        self.assertIn("JUDGE-MARK", out)
        self.assertIn("Project rules for the judge role", out)
        self.assertNotIn("Project rules for delegate:critic", out)  # no second heading without an agent file
        self.assertIn("JUDGE-MARK", ctx(agent("delegate:checker", self.J)))

    def test_I5_I6_build_agent_and_skills_get_no_role_file(self) -> None:
        out = ctx(agent("delegate:worker", self.J))
        self.assertIn("worker-MARK", out)
        self.assertNotIn("JUDGE-MARK", out)
        self.assertIn("plan-MARK", ctx(skill("openspec:plan", self.J)))
        self.assertIn("plan-MARK", ctx(prompt("/openspec:plan go", self.J)))
        self.assertNotIn("JUDGE-MARK", skill("openspec:plan", self.J) + prompt("/openspec:plan go", self.J))

    def test_I8_judge_file_alone(self) -> None:
        jo = os.path.join(self.tmp, "judgeonly")
        write(os.path.join(jo, ".claude", "kit", "judge.md"), "JUDGE-MARK\n")
        git(jo, "init", "-q", "-b", "master")
        self.assertIn("JUDGE-MARK", ctx(agent("openspec:spec-conformance", jo)))
        self.assertEqual(agent("delegate:worker", jo), "")

    def test_I7_I9_a_map_of_our_own(self) -> None:
        h = os.path.join(self.tmp, "h")
        os.makedirs(os.path.join(h, "hooks"))
        os.makedirs(os.path.join(h, "lib"))
        hook = os.path.join(h, "hooks", "inject-addition.sh")
        shutil.copy(HOOK, hook)
        shutil.copy(HOOK[:-3] .replace('inject-addition', 'inject_addition') + '.py', os.path.join(h, 'hooks'))  # the wrapper execs the .py beside it
        tsv = os.path.join(h, "lib", "agent-roles.tsv")
        write(tsv, "openspec:author\tthink\n")
        out = agent("openspec:reviewer", self.J, hook)  # missing from the map: its own file only
        self.assertIn("reviewer-MARK", ctx(out))
        self.assertNotIn("JUDGE-MARK", out)
        os.remove(tsv)  # no map file: per-agent file only, and the hook still exits 0
        done = subprocess.run([hook], input=json.dumps({"hook_event_name": "SubagentStart", "agent_type": "openspec:reviewer", "cwd": self.J}),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0)
        self.assertIn("reviewer-MARK", ctx(done.stdout))
        self.assertNotIn("JUDGE-MARK", done.stdout)


if __name__ == "__main__":
    if os.environ.get("INJECT_RECORD"):
        tmp = os.path.realpath(tempfile.mkdtemp())
        try:
            write(os.environ["INJECT_RECORD"], golden_out(kartoteka(tmp)))
            print("recorded " + os.environ["INJECT_RECORD"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(0)
    unittest.main()
