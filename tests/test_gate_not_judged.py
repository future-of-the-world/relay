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

    def test_bin_ci_does_not_end_green_on_a_non_zero_record_step(self):
        ci = open(os.path.join(ROOT, "bin", "ci")).read()
        full = ci[ci.index("bin/eval-record"):ci.index('if [ "$status" -ne 0 ]')]
        self.assertIn("rec_rc=$?", full)
        self.assertIn("status=1", full)
        self.assertIn("not a pass", full)


if __name__ == "__main__":
    unittest.main()
