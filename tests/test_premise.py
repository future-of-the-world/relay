"""A fix item records what its failing case is (finding Q1 of the premise item): a claim is reproduced before the build.
Scratch repositories in a temp dir."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestFailingKind(tq.Base):
    def test_q1_add_records_which_kind_the_failing_case_is_and_refuses_a_fix_that_does_not_say(self):
        repo = self.repo("premise")
        rq.add(repo, "fix", "Claimed fix", why="w", failing="a reviewer says so", failing_kind="claim", minutes=5, **tq.QUIET)
        rq.add(repo, "fix", "Tested fix", why="w", failing="it fails", failing_kind="test", minutes=5, **tq.QUIET)
        claimed = rq.parse("c", tq.git(repo, "show", "master:.relay/queue/claimed-fix.json"))
        tested = rq.parse("t", tq.git(repo, "show", "master:.relay/queue/tested-fix.json"))
        self.assertEqual((claimed["failing_kind"], claimed["problems"]), ("claim", []))
        self.assertEqual((tested["failing_kind"], tested["problems"]), ("test", []))
        self.assertIn("Failing case (claim):", rq.show_text(claimed))
        self.assertIn("Failing case (test):", rq.show_text(tested))
        with self.assertRaises(rq.Refused) as ctx:       # a fix that does not say what its failing case is
            rq.add(repo, "fix", "Silent fix", why="w", failing="it fails", minutes=5, **tq.QUIET)
        self.assertIn("failing_kind", str(ctx.exception))
        with self.assertRaises(rq.Refused):              # a word that is none of the three
            rq.add(repo, "fix", "Odd fix", why="w", failing="it fails", failing_kind="rumour", minutes=5, **tq.QUIET)
        with self.assertRaises(rq.Refused):              # a feature has no failing case
            rq.add(repo, "feature", "A feature", why="w", failing_kind="claim", minutes=5, **tq.QUIET)

    def test_q1_the_input_file_key_is_read_and_a_finding_is_queued_as_a_claim(self):
        path = os.path.join(self.tmp, "in.toml")
        with open(path, "w") as handle:
            handle.write("kind = 'fix'\ntitle = 'T'\nwhy = 'w'\ntime = '5m'\nfailing_case = 'x'\nfailing_kind = 'run'\n")
        self.assertEqual(rq.read_add_input(path, rq.ADD_KEYS, ("title", "why", "time"))["failing_kind"], "run")
        self.assertNotIn("failing_kind", rq.FROM_KEYS)     # --from takes it from the finding: always a claim

    def test_f4_add_from_queues_a_review_finding_and_a_checks_finding_as_a_claim(self):
        repo = self.repo("premise-from")
        finding = {"id": "F1", "path": "lib/q.py", "line": 4, "severity": "LOW", "rank": "low", "kind": "inside",
                   "summary": "review finding", "failing_case": ["x"]}
        report = os.path.join(self.tmp, "review.json")
        with open(report, "w") as handle:
            json.dump({"schema": 1, "type": "review", "reviewed": "a" * 40, "base": "master", "findings": [finding]}, handle)
        rq.add_from(repo, report, "F1", why="w", minutes=5, **tq.QUIET)
        check = {"schema": 2, "type": "check", "head": "b" * 40, "branch": "wt/x", "item": None, "gate": None, "worktree": "/w",
                 "findings": [dict(finding, id="N1", summary="check finding", source="check", since="a" * 40, verdict="NOT MET", reason=[])]}
        path = os.path.join(self.tmp, "chk.json")
        with open(path, "w") as handle:
            json.dump(check, handle)
        rq.add_from(repo, path, "N1", why="w", minutes=5, **tq.QUIET)
        for slug in ("review-finding", "check-finding"):
            item = rq.parse(slug, tq.git(repo, "show", "master:.relay/queue/%s.json" % slug))
            self.assertEqual(item["failing_kind"], "claim")

    def test_q1_the_skills_and_the_rule_name_the_reproduce_step(self):
        delegate, front, rule = (read("plugins", "delegate", "skills", "delegate", "SKILL.md"),
                                 read("plugins", "front", "skills", "front", "SKILL.md"), read("rules", "queue.md"))
        for text in (delegate, front):                       # both live cases are named where the step is
            self.assertIn("plugin-cache", text)
            self.assertIn("bench", text)
        self.assertIn("reproduce step", delegate)
        self.assertIn("`test` or `run`", delegate)          # an item with a failing test skips the step
        self.assertIn("one message", front)                  # non-reproduced claims reach the owner together
        self.assertIn("owner can", front)
        self.assertIn("failing_kind", rule)
        self.assertIn("no `failing_kind`", delegate)         # F1: an old item counts as a claim
        self.assertIn("counts as a claim", delegate)
        self.assertIn("counts as a claim", rule)
        self.assertIn("before `relay queue take`", delegate)  # F2: reproduced from the main checkout, nothing left taken
        self.assertIn('`failing_kind = "run"`', front)        # F3: the red-run fix item names its word


if __name__ == "__main__":
    unittest.main()
