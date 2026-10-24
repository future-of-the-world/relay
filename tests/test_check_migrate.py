"""`relay check migrate` (lib/relay_checks_migrate.py): the schema-1 checks of a scratch `.relay/checks` become check records.

Every test builds its own folder in a temp dir; nothing reads the repository's own `.relay/checks`.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_checks_migrate as mig  # noqa: E402
import relay_verdict as rv  # noqa: E402

HEAD_A, HEAD_B = "a" * 40, "b" * 40
SINCE_1, SINCE_2 = "1" * 40, "2" * 40
GATE_A = "/Users/x/relay/.worktrees/job-a/.relay/checks/%s.gate.log" % ("c" * 40)


def finding(fid, severity="MEDIUM", summary="it breaks"):
    return {"id": fid, "path": "lib/x.py", "line": 3, "severity": severity, "rank": rv.WORDS[severity], "kind": "inside",
            "summary": summary, "failing_case": ["x fails"]}


def review(file, reviewed, findings, scope=(), owner=None):
    out = {"base": "master", "file": file, "findings": findings, "notes": [], "reviewed": reviewed, "schema": 1,
           "scope": list(scope), "type": "review"}
    if owner:
        out["owner"] = owner
    return out


def review_set(reviewed, *reviews):
    return {"reviewed": reviewed, "reviews": list(reviews), "schema": 1, "type": "review-set"}


def old_check(head, sets, verdicts, new=(), scope=("Range x..HEAD.",), notes=(), gate=GATE_A):
    return {"findings": [dict(id=i, verdict=v, reason=["checked " + i]) for i, v in verdicts], "gate": gate, "head": head,
            "new": list(new), "notes": list(notes), "open": 0, "queued": 0, "review": list(sets), "reviewed": SINCE_1,
            "schema": 1, "scope": list(scope), "type": "check"}


def old_mark(head, gate="c" * 40 + ".gate.log"):
    return {"check": head + ".check.json", "commit": head, "gate": gate, "review": "s.review.json", "schema": 1,
            "time": "2026-10-24T09:18:01Z", "verdict": {"open": 0, "queued": 0, "reviewed": SINCE_1}}


class Folder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        self.folder = os.path.join(self.repo, ".relay", "checks")
        os.makedirs(self.folder)

    def put(self, name, data):
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)

    def get(self, name):
        with open(os.path.join(self.folder, name), encoding="utf-8") as handle:
            return json.load(handle)

    def snapshot(self):
        out = {}
        for name in sorted(os.listdir(self.folder)):
            with open(os.path.join(self.folder, name), "rb") as handle:
                out[name] = handle.read()
        return out

    def record(self, head):
        with open(os.path.join(self.folder, head + ".check.json"), encoding="utf-8") as handle:
            return rv.load_record(handle.read(), "the record", stored=True)


class TestConvert(Folder):
    def test_the_same_old_id_in_two_sets_of_one_check_is_refused(self):
        # Both sets hold F1, so the old check's verdict for F1 cannot be told apart: the migration refuses rather than guess.
        self.put("s1.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("F1")])))
        self.put("s2.review.json", review_set(SINCE_2, review("two.json", SINCE_2, [finding("F1", "LOW")])))
        self.put(HEAD_A + ".check.json", old_check(HEAD_A, ["s1.review.json", "s2.review.json"], [("F1", "MET")]))
        with self.assertRaises(mig.MigrateError):
            mig.migrate(self.repo)

    def test_one_check_over_two_sets(self):
        # Old ids are unique inside a check: set 1 has Q1, F1; set 2 has F2, F3. Result Q1, F1 (old F1), F2 (old F2), F3 (old F3).
        self.put("s1.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("Q1", "HIGH"), finding("F1")],
                                                              scope=["From queue item fix-the-thing: the fix is checked as finding Q1."])))
        self.put("s2.review.json", review_set(SINCE_2, review("two.json", SINCE_2, [finding("F2", "LOW"), finding("F3")])))
        self.put(HEAD_A + ".check.json", old_check(HEAD_A, ["s1.review.json", "s2.review.json"],
                                                   [("Q1", "MET"), ("F1", "MET"), ("F2", "DISPUTED"), ("F3", "MET")]))
        self.put(HEAD_A + ".json", old_mark(HEAD_A))
        self.assertEqual(mig.migrate(self.repo), (1, 1, 2))
        record = self.record(HEAD_A)
        self.assertEqual(record["item"], "fix-the-thing")
        self.assertEqual(record["branch"], "wt/job-a")
        self.assertEqual(record["gate"], "c" * 40 + ".gate.log")
        got = [(f["id"], f["source"], f.get("source_id"), f["since"], f["verdict"]) for f in record["findings"]]
        self.assertEqual(got, [("Q1", "queue", None, SINCE_1, "MET"), ("F1", "one.json", "F1", SINCE_1, "MET"),
                               ("F2", "two.json", "F2", SINCE_2, "DISPUTED"), ("F3", "two.json", "F3", SINCE_2, "MET")])
        self.assertEqual(record["findings"][2]["reason"], ["checked F2"])
        # The mark is schema 2: counts derived (the DISPUTED F2 is inside, rank low, so not open), `review` and `reviewed` gone.
        self.assertEqual(self.get(HEAD_A + ".json"), {"schema": 2, "commit": HEAD_A, "verdict": {"open": 0, "queued": 0},
                                                      "check": HEAD_A + ".check.json", "gate": "c" * 40 + ".gate.log",
                                                      "time": "2026-10-24T09:18:01Z"})

    def test_a_set_shared_by_two_checks_is_read_by_both_then_deleted_with_the_lone_set(self):
        self.put("s.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("F1")])))
        self.put("lone.review.json", review_set(SINCE_2, review("lone.json", SINCE_2, [finding("F1")])))
        for head in (HEAD_A, HEAD_B):
            self.put(head + ".check.json", old_check(head, ["s.review.json"], [("F1", "MET")]))
        self.assertEqual(mig.migrate(self.repo), (2, 0, 2))
        self.assertEqual(sorted(os.listdir(self.folder)), [HEAD_A + ".check.json", HEAD_B + ".check.json"])
        for head in (HEAD_A, HEAD_B):
            self.assertEqual([f["id"] for f in self.record(head)["findings"]], ["F1"])
            self.assertIsNone(self.record(head)["item"])

    def test_old_new_findings_become_n_with_the_old_id_in_the_reason(self):
        # The old check's own finding was called F3 and counted open 1. It becomes N1, NOT MET (still open), stated at the head.
        new = dict(finding("F3", "HIGH", "test_f6 fails"), details=["d"], evidence=[], pass_cases=["p"], fix_hint=["h"])
        self.put("s.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("F1")])))
        self.put(HEAD_A + ".check.json", old_check(HEAD_A, ["s.review.json"], [("F1", "MET")], new=[new]))
        self.put(HEAD_A + ".json", old_mark(HEAD_A))
        mig.migrate(self.repo)
        n1 = self.record(HEAD_A)["findings"][-1]
        self.assertEqual((n1["id"], n1["source"], n1["since"], n1["verdict"]), ("N1", "check", HEAD_A, "NOT MET"))
        self.assertIn("F3", n1["reason"][0])
        self.assertEqual(self.get(HEAD_A + ".json")["verdict"]["open"], 1)

    def test_a_note_saying_q1_is_met_becomes_a_q1_marked_migrated(self):
        note = "Q1 (queue item findings file) was not recorded. Q1 is MET: tests/test_x.py:34 passes at HEAD and fails before; gate green."
        self.put("s.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("F1")],
                                                             scope=["Range master...HEAD, closing queue item core-tests-not-in-gate (Q1)."])))
        self.put(HEAD_A + ".check.json", old_check(HEAD_A, ["s.review.json"], [("F1", "MET")], notes=["other", note]))
        mig.migrate(self.repo)
        findings = self.record(HEAD_A)["findings"]
        self.assertEqual([f["id"] for f in findings], ["Q1", "F1"])
        self.assertEqual((findings[0]["verdict"], findings[0]["source"], findings[0]["reason"]), ("MET", "queue", ["migrated", note]))
        self.assertEqual(self.record(HEAD_A)["item"], "core-tests-not-in-gate")

    def test_the_owner_words_of_a_review_stay_on_their_finding(self):
        owner = [{"id": "F1", "words": ["not wrong"], "date": "2026-10-20", "queue": "later-job"}]
        self.put("s.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("F1")], owner=owner)))
        self.put(HEAD_A + ".check.json", old_check(HEAD_A, ["s.review.json"], [("F1", "GAP")]))
        mig.migrate(self.repo)
        self.assertEqual(self.record(HEAD_A)["findings"][0]["owner"], [{"words": ["not wrong"], "date": "2026-10-20", "queue": "later-job"}])


class TestRun(Folder):
    def seed(self):
        self.put("s.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("F1")])))
        self.put(HEAD_A + ".check.json", old_check(HEAD_A, ["s.review.json"], [("F1", "MET")]))
        self.put(HEAD_A + ".json", old_mark(HEAD_A))
        with open(os.path.join(self.folder, "c" * 40 + ".gate.log"), "w", encoding="utf-8") as handle:
            handle.write("head %s\nexit 0\n" % ("c" * 40))

    def test_a_second_run_changes_nothing(self):
        self.seed()
        self.assertEqual(mig.migrate(self.repo), (1, 1, 1))
        after_first = self.snapshot()
        self.assertEqual(mig.migrate(self.repo), (0, 0, 0))
        self.assertEqual(self.snapshot(), after_first)
        self.assertIn("c" * 40 + ".gate.log", after_first)       # a gate log is never touched

    def test_a_check_missing_a_verdict_stops_the_run_with_nothing_written(self):
        # The set has F1 and F2 but the old check judged only F1: no verdict is invented.
        self.put("s.review.json", review_set(SINCE_1, review("one.json", SINCE_1, [finding("F1"), finding("F2")])))
        self.put(HEAD_A + ".check.json", old_check(HEAD_A, ["s.review.json"], [("F1", "MET")]))
        before = self.snapshot()
        with self.assertRaises(mig.MigrateError) as caught:
            mig.migrate(self.repo)
        self.assertIn("F2", str(caught.exception))
        self.assertEqual(self.snapshot(), before)

    def test_the_command_migrates_and_reports(self):
        self.seed()
        cmd = [sys.executable, os.path.join(ROOT, "bin", "relay"), "check", "migrate", "-C", self.repo]
        first = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual((first.returncode, first.stdout.strip()), (0, "migrated 1 checks and 1 marks; deleted 1 review sets"))
        second = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual((second.returncode, second.stdout.strip()), (0, "nothing to migrate"))
        self.record(HEAD_A)       # loads


if __name__ == "__main__":
    unittest.main()
