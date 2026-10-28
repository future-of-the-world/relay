"""A clean take of the default branch needs no new check; a hand-resolved one does (design relay-land 4.2). The Flow fixture is
tests/test_check_record.py's."""
import subprocess

from test_check_record import SPREAD, TEST_NAME, Flow, merge_hook, review_finding, rm, rq, rv


class MergeFindingsAfterTake(Flow):
    def start(self):
        """The fix changes lib/y.py; a review is of the take commit."""
        self.fix()
        self.commit({"lib/w.py": SPREAD.replace("one", "uno")}, message="a file only the fixer changes")
        return self.review("a.json", self.took, [review_finding(1)])

    def m_of(self, review):
        _, _, found = rv.build_findings(self.wa, self.head(), [review])
        return [(f["id"], f["path"], f["since"]) for f in found if f["id"].startswith("M")]

    def test_merge_findings_none_after_clean_take(self):
        # the fixer changed y.py's first line and the review is of that commit; master changes the last line; git merges
        # it by itself and the branch committed nothing since: nothing for the check
        self.start()
        review = self.review("b.json", self.head(), [review_finding(1)])
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END")})
        self.take_master()
        self.assertEqual(self.m_of(review), [])

    def test_a_hand_resolved_take_is_an_m_finding_for_the_resolved_file(self):
        # master and the fixer both changed y.py's first line: git stops, the author writes the result by hand
        review = self.start()
        self.master_changes({"lib/y.py": SPREAD.replace("one", "uno")})
        subprocess.run(["git", "-C", self.wa, "merge", "-q", "--no-edit", "master"], capture_output=True)
        self.write_commit(self.wa, {"lib/y.py": SPREAD.replace("one", "both")}, "resolved by hand")
        merge = self.head()
        self.assertEqual(self.m_of(review), [("M1", "lib/y.py", merge)])



class OneFunctionAfterTake(Flow):
    def after_check(self):
        self.flow_to_check()
        return self.head()

    def mark_commit(self):
        return next(c for c, _ in rm.marks(self.wa, "HEAD"))

    def test_fix_item_clean_overlap_take_lands(self):
        # the fix (checked, Q1 MET) changed y.py's first line; master changes its last line; git merges it by itself.
        # Red before the shared rule: check_refusal listed y.py as the branch's own file changed since the check.
        self.after_check()
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END")})
        self.take_master()
        self.assertIsNone(rq.close_refusal(self.wa, "HEAD", "job", TEST_NAME))
        self.assertEqual(merge_hook.step_mark(self.main, "master", "wt/a"), self.mark_commit())

    def test_fix_item_commit_after_check_refused(self):
        self.after_check()
        self.commit({"lib/y.py": SPREAD.replace("pad", "pod", 1)}, message="a commit after the check")
        self.assertIn("lib/y.py", rq.close_refusal(self.wa, "HEAD", "job", TEST_NAME))

    def test_show_no_change_line_after_clean_take(self):
        self.after_check()
        self.master_changes({"lib/y.py": SPREAD.replace("end", "END")})
        self.take_master()
        self.assertFalse([l for l in rm.show(self.main, "wt/a") if "changed after the mark" in l])
