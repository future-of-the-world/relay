"""The saved designs under docs/plans/ must read on another machine (review plans-save F1-F3)."""

import re
import unittest
from pathlib import Path

PLANS = Path(__file__).resolve().parent.parent / "docs" / "plans"


def plan(name: str) -> str:
    return (PLANS / name).read_text(encoding="utf-8")


class ChecksArtifactsHeader(unittest.TestCase):
    def test_header_says_times_cache_is_built_and_logs_are_not(self) -> None:
        # F1: line 2 is the status line; D (times cache) is on master since 7aef441.
        status = plan("checks-artifacts.md").splitlines()[1]
        self.assertIn("7aef441", status)
        self.assertIn("red-gate-and-probe-runs-keep-no-logs-to-find-a-c", status)
        self.assertIn("not built", status)
        self.assertNotIn("nothing in this file is in the code", status)

    def test_other_plans_stay_not_built(self) -> None:
        for name in ("dev-metrics.md", "cycle-scripts.md", "test-speed.md"):
            self.assertIn("Not built yet", "\n".join(plan(name).splitlines()[:4]), name)

    def test_gate_speed_design_is_said_once_to_be_not_kept(self) -> None:
        text = plan("checks-artifacts.md")
        self.assertRegex(text, r"gate-speed design[^\n]*not kept[^\n]*7aef441|not kept[^\n]*gate-speed design[^\n]*7aef441")


class CycleScriptsLinks(unittest.TestCase):
    def test_no_reference_to_unkept_dev_metrics_file(self) -> None:
        text = plan("cycle-scripts.md")
        self.assertNotIn("design-dev-metrics", text)
        self.assertIsNone(re.search(r"dev-metrics\.md:\d+", text))
        self.assertIn("docs/plans/dev-metrics.md", text)

    def test_revision_1_not_claimed_kept(self) -> None:
        text = plan("cycle-scripts.md")
        self.assertNotIn("kept beside this file", text)
        self.assertNotIn("design-cycle-scripts.r1.md", text)

    def test_measurement_scripts_line(self) -> None:
        text = plan("cycle-scripts.md")
        self.assertIn(
            "Measurement scripts (wfmeasure.py, wfagg.py, wfagg2.py, front.py) were in the session scratchpad (not kept)",
            text.replace("\n", " "),
        )


class ScratchNames(unittest.TestCase):
    def test_sim_clones_marked_not_kept(self) -> None:
        text = plan("checks-artifacts.md").replace("\n", " ")
        self.assertRegex(text, r"were in the session scratchpad \(not kept\)")

    def test_test_speed_sentence_ends_before_what_changed(self) -> None:
        text = plan("test-speed.md")
        self.assertNotIn("(not kept) What changed", text)
        self.assertIn("(not kept). What changed", text)


if __name__ == "__main__":
    unittest.main()
