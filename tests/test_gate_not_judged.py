"""A full gate is not green when eval runs were not judged or a meaning grader failed (bin/eval-record, bin/ci)."""
import io, json, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_eval_record import ROOT, fixture, load_record


class GateNotJudged(unittest.TestCase):
    def setUp(self):
        self.rec = load_record()
        self.tmp = tempfile.mkdtemp(prefix="gnj-")
        self.json = os.path.join(self.tmp, "evals.json")
        os.environ["RELAY_HOME"] = os.path.join(self.tmp, "home")

    def tearDown(self):
        os.environ.pop("RELAY_HOME", None); shutil.rmtree(self.tmp, ignore_errors=True)

    def step(self, data):
        json.dump(data, open(self.json, "w"))
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.rec.main(["--json", self.json, "--repo", "relay", "--branch", "wt/x"])
        return code, out.getvalue()

    def test_all_judged_and_passing_exits_0(self):
        code, out = self.step(fixture([[True] * 3] * 3))
        self.assertEqual(code, 0); self.assertNotIn("NOT A PASS", out)

    def test_a_failed_meaning_grader_exits_2_naming_the_case(self):
        code, out = self.step(fixture([[True] * 3, [False] * 3]))
        self.assertEqual(code, 2)
        self.assertEqual(out.strip().split("\n")[-1],
                         "ci: eval record: NOT A PASS: 1 meaning grader(s) failed, 0 not judged, in code-reviewer-offbyone")

    def test_an_errored_run_exits_2(self):
        d = fixture([[True] * 3] * 2); d["cases"][0]["arms"]["with"].append({"error": "max_turns 3", "graders": []})
        code, out = self.step(d)
        self.assertEqual(code, 2); self.assertIn("1 not judged, in code-reviewer-offbyone", out)

    def test_a_grader_without_votes_exits_2(self):
        code, _ = self.step(fixture([[True] * 3], no_votes=True))
        self.assertEqual(code, 2)

    def test_notes_alone_stay_green(self):
        # a split vote that passes and a rule-file read are notes, not a failure
        code, out = self.step(fixture([[True, False, True]] * 2, flagged_runs=(1,)))
        self.assertEqual(code, 0); self.assertIn("note:", out)

    def test_a_partial_batch_exits_2(self):
        # ceiling stop: 1 of 3 runs present, so 2 never ran
        d = fixture([[True] * 3], partial="cost ceiling reached"); d["cases"][0]["runsPerCase"] = 3
        code, out = self.step(d)
        self.assertEqual(code, 2)
        self.assertTrue(out.strip().split("\n")[-1].startswith("ci: eval record: NOT A PASS"))
        self.assertIn("code-reviewer-offbyone", out.strip().split("\n")[-1])

    def test_a_partial_batch_with_all_runs_exits_2(self):
        d = fixture([[True] * 3] * 3, partial="cost ceiling reached"); d["cases"][0]["runsPerCase"] = 3
        code, out = self.step(d)
        self.assertEqual(code, 2); self.assertIn("NOT A PASS", out)

    def test_fewer_runs_than_runs_per_case_exits_2(self):
        d = fixture([[True] * 3]); d["cases"][0]["runsPerCase"] = 3
        code, out = self.step(d)
        self.assertEqual(code, 2); self.assertIn("2 not judged", out)

    def test_a_case_with_no_runs_exits_2(self):
        d = fixture([]); d["cases"][0]["runsPerCase"] = 3
        code, out = self.step(d)
        self.assertEqual(code, 2); self.assertIn("3 not judged", out)

    def test_all_runs_present_exits_0(self):
        d = fixture([[True] * 3] * 3); d["cases"][0]["runsPerCase"] = 3
        self.assertEqual(self.step(d)[0], 0)

    def test_no_record_exits_2(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.rec.main(["--json", os.path.join(self.tmp, "missing.json")])
        self.assertEqual(code, 2); self.assertIn("NOT A PASS", out.getvalue()); self.assertIn("no record", out.getvalue())

    def test_an_unreadable_record_still_exits_1(self):
        open(self.json, "w").write("{not json")
        self.assertEqual(self.rec.main(["--json", self.json, "--repo", "relay", "--branch", "x"]), 1)

    def test_a_missing_meaning_grader_exits_2(self):
        d = fixture([[True] * 3] * 3)
        d["cases"][0]["arms"]["with"][1]["graders"] = [g for g in d["cases"][0]["arms"]["with"][1]["graders"] if g["name"] != "reports-off-by-one"]
        code, out = self.step(d)
        self.assertEqual(code, 2); self.assertTrue(out.strip().split("\n")[-1].endswith("1 not judged, in code-reviewer-offbyone"))

    def test_bin_ci_does_not_end_green_on_a_non_zero_record_step(self):
        ci = open(os.path.join(ROOT, "bin", "ci")).read()
        full = ci[ci.index("bin/eval-record"):ci.index('if [ "$status" -ne 0 ]')]
        self.assertIn("rec_rc=$?", full)
        self.assertIn("status=1", full)
        self.assertIn("not a pass", full)


if __name__ == "__main__":
    unittest.main()
