"""Port of plugins/relay/tests/guard-diff.test.sh: every command in guard-diff.golden.jsonl must get the verdict
(block or allow) the old guard gave it ("was"), except where the golden file records a deliberate change.
Placeholders in cwd and cmd: @M@ the main checkout, @W@ its worktree .worktrees/any-change, @A@ .worktrees/a, @T@ a temp dir.
  python3 tests/test_hook_guard_diff.py --record <a plugins/relay directory of the old guard>   (rewrites "was")"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from hook_helpers import ROOT, SoftCases

CORE = os.path.join(ROOT, "plugins", "relay")
GOLDEN = os.path.join(CORE, "tests", "guard-diff.golden.jsonl")


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd, check=True, capture_output=True)


def build_repo(tmp: str) -> Dict[str, str]:
    main = os.path.join(tmp, "repo")
    os.makedirs(main)
    git(main, "init", "-q", "-b", "master", ".")
    git(main, "commit", "-q", "--allow-empty", "-m", "init")
    git(main, "worktree", "add", "-q", ".worktrees/any-change", "-b", "wt/any-change")
    git(main, "worktree", "add", "-q", ".worktrees/a", "-b", "wt/a")
    git(main, "worktree", "add", "-q", ".worktree/any-change", "-b", "wt/any-change2")
    with open(os.path.join(main, ".gitignore"), "w") as handle:
        handle.write(".ci/\n")
    with open(os.path.join(main, "README.md"), "w") as handle:
        handle.write("a\n")
    os.makedirs(os.path.join(main, ".claude"))
    shutil.copy(os.path.join(CORE, "tests", "profiles", "kartoteka.toml"), os.path.join(main, ".claude", "kit.toml"))
    return {"@W@": os.path.join(main, ".worktrees", "any-change"), "@A@": os.path.join(main, ".worktrees", "a"), "@M@": main, "@T@": tmp}


def verdict(hook: str, subs: Dict[str, str], case: Dict[str, str]) -> str:
    cwd, cmd = case["cwd"], case["cmd"]
    for key, val in subs.items():
        cwd, cmd = cwd.replace(key, val), cmd.replace(key, val)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    event = json.dumps({"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": cmd}})
    done = subprocess.run([hook], input=event, capture_output=True, text=True, env=env)
    return "block" if done.returncode == 2 else "allow"


def judge(hook: str, subs: Dict[str, str], cases: List[Dict[str, str]]) -> List[str]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda c: verdict(hook, subs, c), cases))


def load() -> List[Dict[str, str]]:
    with open(GOLDEN) as handle:
        return [json.loads(line) for line in handle if line.strip()]


class GuardDiff(SoftCases):
    hook = os.path.join(CORE, "hooks", "guard-main.sh")

    def test_every_golden_command_gets_its_recorded_verdict(self) -> None:
        tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        cases = load()
        got = judge(self.hook, build_repo(tmp), cases)
        bad = ["%s (old guard: %s)  %s  %s" % (v, c["was"], c["cwd"], c["cmd"]) for v, c in zip(got, cases) if v != c["was"]]
        self.assertEqual(bad, [])
        self.assertEqual(len(got), len(cases))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--record":
        old = os.path.realpath(sys.argv[2])
        tmp = os.path.realpath(tempfile.mkdtemp())
        try:
            cases = load()
            verdicts = judge(os.path.join(old, "hooks", "guard-main.sh"), build_repo(tmp), cases)
            with open(GOLDEN, "w") as handle:
                for case, v in zip(cases, verdicts):
                    case["was"] = v
                    handle.write(json.dumps(case, separators=(",", ":")) + "\n")
            print("recorded %d verdicts" % len(cases))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        unittest.main()
