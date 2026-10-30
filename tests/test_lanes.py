"""Lanes: the number of changes built at once is a setting (projects.toml `lanes`, 1-8, default 4) that the generated
file states; `bin/paid-cost paths` prints the paths the paid run checks; the front and rule texts carry the lane rules."""
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_rules  # noqa: E402
import relay_toml  # noqa: E402

PAID = os.path.join(ROOT, "bin", "paid-cost")
FRONT = os.path.join(ROOT, "plugins", "front", "skills", "front", "SKILL.md")


def render(spec: dict) -> str:
    return relay_rules.render_target("proj", dict({"load": [], "read": []}, **spec), {}, {})


class Lanes(unittest.TestCase):
    def test_default_is_four(self) -> None:
        # a project that sets nothing runs 4 changes at once (the delegation rule's old number)
        self.assertIn("Changes built at once: 4.", render({}))

    def test_setting_is_stated(self) -> None:
        self.assertIn("Changes built at once: 6.", render({"lanes": 6}))

    def test_bounds(self) -> None:
        for bad in (0, 9, "6", True, 2.5):
            with self.assertRaises(relay_rules.Fail, msg=repr(bad)):
                render({"lanes": bad})
        for good in (1, 8):
            self.assertIn("Changes built at once: %d." % good, render({"lanes": good}))

    def test_relay_project_runs_six(self) -> None:
        # the owner's answer of 27 Oct: 6 at once
        with open(os.path.join(ROOT, "projects.toml"), "rb") as handle:
            self.assertEqual(relay_toml.load(handle)["relay"]["lanes"], 6)

    def test_paid_paths_come_from_the_paid_run_source(self) -> None:
        out = subprocess.run([sys.executable, PAID, "paths"], capture_output=True, text=True, check=True).stdout.split()
        # CHECKED_PATHS in bin/paid-cost, shown without git's ":(glob)" prefix
        self.assertIn("rules/**", out)
        self.assertIn("plugins/*/skills/**", out)
        self.assertTrue(all(not p.startswith(":") for p in out))

    def test_front_text_names_the_lane_rules(self) -> None:
        text = open(FRONT, encoding="utf-8").read()
        for needle in ("bin/paid-cost paths", "lanes keep building", "one gate apart", "Changes built at once"):
            self.assertIn(needle, text)

    def test_delegation_rule_points_at_the_setting(self) -> None:
        text = open(os.path.join(ROOT, "rules", "delegation.md"), encoding="utf-8").read()
        self.assertIn("Changes built at once", text)


def paid_touches(repo: str, branch: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([sys.executable, PAID, "touches", branch, "--repo", repo], capture_output=True, text=True)


class Touches(unittest.TestCase):
    """bin/paid-cost touches <branch>: the changed files that are on the paid run's checked paths."""

    def make_repo(self, tmp: str, files: "list[str]") -> str:
        def git(*a: str) -> None:
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True, capture_output=True)
        git("init", "-b", "main")
        git("commit", "--allow-empty", "-m", "base")
        git("checkout", "-b", "wt/x")
        for f in files:
            os.makedirs(os.path.dirname(os.path.join(tmp, f)), exist_ok=True)
            open(os.path.join(tmp, f), "w").write("x")
        git("add", ".")
        git("commit", "-m", "change")
        git("checkout", "main")
        return tmp

    def test_checked_path_is_printed_exit_0(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.make_repo(tmp, ["plugins/front/skills/front/SKILL.md", "lib/relay_gate.py", "plugins/relay/hooks/merge.py"])
            done = paid_touches(tmp, "wt/x")
            self.assertEqual(done.returncode, 0)
            # the skill and the hook are checked paths; lib/ is not
            self.assertEqual(sorted(done.stdout.split()), ["plugins/front/skills/front/SKILL.md", "plugins/relay/hooks/merge.py"])

    def test_unchecked_paths_print_nothing_exit_1(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # cycle.js is under plugins/delegate/workflows, which CHECKED_PATHS does not list
            self.make_repo(tmp, ["lib/relay_gate.py", "plugins/delegate/workflows/cycle.js"])
            done = paid_touches(tmp, "wt/x")
            self.assertEqual((done.returncode, done.stdout), (1, ""))


class Wave(unittest.TestCase):
    def test_wave_min_default_and_bounds(self) -> None:
        self.assertIn("lists at least: 3 changes", render({}))
        self.assertIn("lists at least: 5 changes", render({"wave_min": 5}))
        for bad in (0, 7, "3", True, 2.5):
            with self.assertRaises(relay_rules.Fail, msg=repr(bad)):
                render({"wave_min": bad})

    def test_front_defines_wave_and_the_three_endings(self) -> None:
        text = " ".join(open(FRONT, encoding="utf-8").read().split())   # one line: the file wraps its sentences
        for needle in ("A wave is the checked-path", "end of a work stretch", "`relay sync` would stay refused",
                       "- Green:", "- Red:", "- Not judged", "bin/paid-cost touches"):
            self.assertIn(needle, text)
        self.assertNotIn("would change what the run is judging", text)
        self.assertNotIn("after the next wave", text)
        self.assertNotIn("after the last merge of a wave of 3-4", text)


sys.path.insert(0, HERE)
import test_lanes_state as tls  # noqa: E402

HOOK = os.path.join(ROOT, "plugins", "front", "hooks", "lanes.py")


class LanesHookBounds(tls.LaneBase):
    """The UserPromptSubmit lanes hook never blocks the owner: a slow git gives one "not known" line; slow steps are logged."""

    def run_hook(self, home: str, budget: str = "", path: str = "") -> "subprocess.CompletedProcess[str]":
        env = dict(os.environ, RELAY_HOME=home, PYTHONPATH="")
        if budget:
            env["RELAY_LANES_HOOK_BUDGET_S"] = budget
        if path:
            env["PATH"] = path + os.pathsep + env["PATH"]
        data = {"hook_event_name": "UserPromptSubmit", "cwd": self.main, "session_id": "s"}
        # the timeout is only a safety net so a regression fails instead of hanging the suite
        return subprocess.run([sys.executable, HOOK], input=json.dumps(data), capture_output=True, text=True, env=env, timeout=60)

    def slow_git(self) -> str:
        """A folder with a `git` that never answers (exec, so the killed process is the sleeper itself)."""
        folder = os.path.join(self.tmp, "fakebin")
        os.makedirs(folder)
        with open(os.path.join(folder, "git"), "w") as handle:
            handle.write("#!/bin/sh\nexec sleep 60\n")
        os.chmod(os.path.join(folder, "git"), 0o755)
        return folder

    def test_blocked_git_gives_one_unknown_line(self) -> None:
        # the default budget (4 s) is what keeps the hook under the 10 s limit: without the deadline, main_checkout (5 s) and
        # project_root (5 s) alone run past 5 s, so the elapsed bound fails when the deadline is gone
        self.seed({tls.Q + "a.json": tls.item("a")})
        began = time.monotonic()
        out = self.run_hook(os.path.join(self.tmp, "h"), path=self.slow_git())
        # by hand: with the deadline the hook ends near its 4 s budget; without it the two 5 s sleeps give at least 10 s. 9 s
        # separates the two with room for a loaded machine (the clean image measured 5.04 s against the old 5.0)
        self.assertLess(time.monotonic() - began, 9.0)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        text = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(text, "Lanes: not known this time (the repository answered too slowly).")

    def hook_module(self):
        import importlib
        sys.path.insert(0, os.path.dirname(HOOK))
        try:
            return importlib.import_module("lanes")
        finally:
            sys.path.pop(0)

    def git_sleeping_on(self, word: str, seconds: int) -> str:
        """A folder with a `git` that sleeps `seconds` when an argument is `word`, else is the real git."""
        import shutil
        folder = os.path.join(self.tmp, "fakebin2")
        os.makedirs(folder)
        with open(os.path.join(folder, "git"), "w") as handle:
            handle.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = "%s" ] && sleep %d; done\nexec %s "$@"\n' % (word, seconds, shutil.which("git")))
        os.chmod(os.path.join(folder, "git"), 0o755)
        # the first run of a new script can stall for seconds on a busy machine (scan before exec): pay that here, not inside the hook's budget
        subprocess.run([os.path.join(folder, "git"), "--version"], capture_output=True, check=True)
        return folder

    def test_overrun_names_the_step_in_progress_not_a_git_call_that_returned(self) -> None:
        # git hangs only on cat-file, which the queue read runs outside the bounded git: show-ref etc. returned long before
        self.seed({tls.Q + "a.json": tls.item("a")})
        home = os.path.join(self.tmp, "h")
        self.run_hook(home, budget="3", path=self.git_sleeping_on("cat-file", 30))
        log = open(os.path.join(home, "state", "lanes-slow.log"), encoding="utf-8").read().splitlines()
        self.assertRegex(log[-1], r"overrun in (lanes|config) took 3\.0 s", log)

    def test_overrun_names_the_first_git_call_when_git_never_answers(self) -> None:
        self.seed({})
        home = os.path.join(self.tmp, "h")
        self.run_hook(home, budget="1", path=self.slow_git())
        log = open(os.path.join(home, "state", "lanes-slow.log"), encoding="utf-8").read().splitlines()
        self.assertRegex(log[-1], r"overrun in (git |config)")

    def test_nothing_is_printed_with_the_deadline_armed(self) -> None:
        hook = self.hook_module()
        events: "list[str]" = []
        with mock.patch.object(hook, "bound_git", lambda: None), mock.patch.object(hook, "arm", lambda s: events.append("arm")), \
                mock.patch.object(hook, "disarm", lambda: events.append("disarm")), \
                mock.patch.object(hook, "work", lambda *a: ("the line", None)), \
                mock.patch.object(hook, "context", lambda e, t: events.append("print " + t)), \
                mock.patch("sys.stdin", __import__("io").StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": self.main}))):
            hook.main()
        self.assertEqual(events, ["arm", "disarm", "print the line"])

    def landing(self, home: str, path: str, budget: str) -> "subprocess.CompletedProcess[str]":
        env = dict(os.environ, RELAY_HOME=home, PYTHONPATH="", RELAY_LANES_HOOK_BUDGET_S=budget)
        env["PATH"] = path + os.pathsep + env["PATH"]
        data = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": self.main,
                "tool_input": {"command": "git -C /x merge --ff-only wt/feat"}}
        return subprocess.run([sys.executable, HOOK], input=json.dumps(data), capture_output=True, text=True, env=env, timeout=60)

    def test_a_landing_close_finishes_its_writes_past_the_deadline(self) -> None:
        # the queue landing's `git merge --ff-only` takes 10 s, the deadline is 8 s (room for the read under load): the write must still finish whole
        self.seed({tls.Q + "feat.json": tls.item("feat", "feature", **tls.taken("wt/feat"))})
        self.branch_with_commit("feat", {"lib/feat.py": "x\n"})
        tls.git(self.main, "merge", "-q", "--ff-only", "wt/feat")
        home = os.path.join(self.tmp, "h")
        out = self.landing(home, self.git_sleeping_on("merge", 10), "8")
        slow = os.path.join(home, "state", "lanes-slow.log")
        self.assertIn("closed feat", json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"], open(slow).read() if os.path.exists(slow) else "")
        self.assertEqual(self.item("feat")["state"], "done")
        self.assertEqual(tls.git(self.main, "branch", "--list", "wt/queue-*"), "")
        self.assertFalse(os.path.exists(os.path.join(self.main, ".git", "index.lock")))

    def test_a_landing_with_blocked_git_writes_nothing_and_says_unknown(self) -> None:
        self.seed({tls.Q + "feat.json": tls.item("feat", "feature", **tls.taken("wt/feat"))})
        self.branch_with_commit("feat", {"lib/feat.py": "x\n"})
        tls.git(self.main, "merge", "-q", "--ff-only", "wt/feat")
        before = tls.git(self.main, "rev-parse", "HEAD")
        out = self.landing(os.path.join(self.tmp, "h"), self.slow_git(), "1")
        self.assertEqual(json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"], "Lanes: not known this time (the repository answered too slowly).")
        self.assertEqual(tls.git(self.main, "rev-parse", "HEAD"), before)

    def test_normal_run_prints_the_lanes_line(self) -> None:
        self.seed({tls.Q + "a.json": tls.item("a")})
        out = self.run_hook(os.path.join(self.tmp, "h"))
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        self.assertIn("start: a (fix, ip 90)", json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_overrun_is_logged_with_its_step(self) -> None:
        self.seed({})
        home = os.path.join(self.tmp, "h")
        self.run_hook(home, budget="1", path=self.slow_git())
        log = open(os.path.join(home, "state", "lanes-slow.log"), encoding="utf-8").read()
        # the first step to hang is the first git call, which the hook names
        self.assertIn("overrun in", log)

    def test_step_over_two_seconds_is_logged_and_a_fast_one_is_not(self) -> None:
        import importlib
        sys.path.insert(0, os.path.dirname(HOOK))
        try:
            hook = importlib.import_module("lanes")
        finally:
            sys.path.pop(0)
        home = os.path.join(self.tmp, "h")
        ticks = iter([0.0, 2.5, 10.0, 10.5])      # step "slow" takes 2.5 s (logged), step "fast" takes 0.5 s (not)
        with mock.patch.dict(os.environ, {"RELAY_HOME": home}), mock.patch.object(hook, "CLOCK", lambda: next(ticks)):
            hook.timed("slow", lambda: None)
            hook.timed("fast", lambda: None)
        lines = open(os.path.join(home, "state", "lanes-slow.log"), encoding="utf-8").read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("lanes hook: slow took 2.5 s"), lines[0])


if __name__ == "__main__":
    unittest.main()
