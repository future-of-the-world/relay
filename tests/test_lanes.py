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


if __name__ == "__main__":
    unittest.main()
