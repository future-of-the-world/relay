"""A NOT MET finding of any kind but outside is counted in open until the owner answers it (queue item
a-not-met-finding-of-kind-feature-is-counted-now, Q1)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_verdict as rv  # noqa: E402

SHA = "a" * 40


def finding(kind: str, rank: str = "high", verdict: str = "NOT MET", owner: bool = False) -> dict:
    out = {"id": "F1", "path": "x.py", "line": 1, "severity": "HIGH", "rank": rank, "kind": kind, "summary": "s",
           "failing_case": ["case"], "source": "review.json", "since": SHA, "verdict": verdict, "reason": ["r"]}
    if owner:
        out["owner"] = [{"words": ["ok"], "date": "2026-10-25"}]
    return out


def record(*findings: dict) -> dict:
    return {"schema": 2, "type": "check", "head": SHA, "branch": "b", "item": None, "gate": None, "worktree": "/w",
            "findings": list(findings)}


class TestFeatureKind(unittest.TestCase):
    def test_feature_not_met_finding_is_open(self) -> None:
        # Q1: one high NOT MET finding of kind feature, no owner entry: open 1 (it was 0).
        data = record(finding("feature"))
        rv.load_record(__import__("json").dumps(data))        # the record is valid as it stands
        self.assertEqual(rv.open_of(data), 1)

    def test_met_and_answered_and_outside_are_not_open(self) -> None:
        # All MET: 0. Owner answered the feature: 0. Outside is counted by outside_of, not open. Low rank: 0.
        self.assertEqual(rv.open_of(record(finding("feature", verdict="MET"))), 0)
        self.assertEqual(rv.open_of(record(finding("feature", owner=True))), 0)
        self.assertEqual(rv.open_of(record(finding("feature", rank="low"))), 0)
        outside = record(finding("outside"))
        self.assertEqual((rv.open_of(outside), rv.outside_of(outside)), (0, 1))


if __name__ == "__main__":
    unittest.main()
