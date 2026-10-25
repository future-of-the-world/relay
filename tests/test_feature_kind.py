"""A NOT MET finding of any kind but outside is counted in open until the owner answers it (queue item
a-not-met-finding-of-kind-feature-is-counted-now, Q1)."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_checks_migrate as mig  # noqa: E402
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

    def test_design_and_question_are_open_too(self) -> None:
        # F3: a narrower predicate (inside + feature only) would give 0 for these. High design, medium question: 1 each.
        for kind, rank in (("feature", "high"), ("design", "high"), ("question", "medium")):
            with self.subTest(kind=kind):
                self.assertEqual(rv.open_of(record(finding(kind, rank=rank))), 1)

    def test_design_moved_to_the_queue_is_answered(self) -> None:
        # An owner entry carrying `queue` answers it: open 0, queued 1.
        data = record(finding("design", owner=True))
        data["findings"][0]["owner"] = [{"queue": "some-item", "date": "2026-10-25"}]
        self.assertEqual((rv.open_of(data), rv.queued_of(data)), (0, 1))


class TestMigrateKeepsOldRule(unittest.TestCase):
    def test_schema1_open_0_beside_not_met_feature_migrates(self) -> None:
        # F4: schema 1 counted inside findings only, so open 0 beside one NOT MET feature finding was consistent
        # (derived by the old rule: 0). It must migrate, not raise "old check says open 0 but its findings derive 1".
        since, head = "1" * 40, "a" * 40
        feature = {"id": "F1", "path": "x.py", "line": 1, "severity": "HIGH", "rank": "high", "kind": "feature",
                   "summary": "s", "failing_case": ["c"]}
        review = {"base": "master", "file": "one.json", "findings": [feature], "notes": [], "reviewed": since, "schema": 1,
                  "scope": [], "type": "review"}
        rset = {"reviewed": since, "reviews": [review], "schema": 1, "type": "review-set"}
        check = {"findings": [{"id": "F1", "verdict": "NOT MET", "reason": ["no"]}], "gate": "/Users/x/relay/.worktrees/job-a/.relay/checks/%s.gate.log" % ("c" * 40), "head": head, "new": [],
                 "notes": [], "open": 0, "queued": 0, "review": ["s.review.json"], "reviewed": since, "schema": 1,
                 "scope": ["Range x..HEAD."], "type": "check"}
        with tempfile.TemporaryDirectory() as repo:
            folder = os.path.join(repo, ".relay", "checks")
            os.makedirs(folder)
            for name, data in (("s.review.json", rset), (head + ".check.json", check)):
                with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
            self.assertEqual(mig.migrate(repo)[0], 1)


if __name__ == "__main__":
    unittest.main()
