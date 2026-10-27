"""Lanes: the number of changes built at once is a setting (projects.toml `lanes`, 1-8, default 4) that the generated
file states; `bin/paid-cost paths` prints the paths the paid run checks; the front and rule texts carry the lane rules."""
import os
import subprocess
import sys
import unittest

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
        for needle in ("bin/paid-cost paths", "lanes keep building", "one train", "Changes built at once"):
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
        for needle in ("A wave is the train of checked-path", "end of a work stretch", "`relay sync` would stay refused",
                       "- Green:", "- Red:", "- Not judged", "bin/paid-cost touches"):
            self.assertIn(needle, text)
        self.assertNotIn("would change what the run is judging", text)
        self.assertNotIn("after the next wave", text)
        self.assertNotIn("after the last merge of a wave of 3-4", text)


if __name__ == "__main__":
    unittest.main()
