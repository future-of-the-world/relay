"""A case passes a wave run when most of its runs pass (2 of 3); owner, 25 Oct: "Сценарий проходит с большинством"."""
import io, json, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_eval_record import fixture, load_record


def case(votes_by_run, name="c"):
    d = fixture(votes_by_run)["cases"][0]
    d["name"] = name; d["runsPerCase"] = len(votes_by_run)
    return d


def batch(*cases):
    d = fixture([[True] * 3]); d["cases"] = list(cases)
    return d


P, F = [True] * 3, [False] * 3


class Majority(unittest.TestCase):
    def setUp(self):
        self.rec = load_record()

    def test_pass_pass_fail_is_green_and_the_rate_is_shown(self):
        # 2 of 3 runs pass: a majority, so the case passes; the failed run stays visible as a note
        lines = self.rec.report(batch(case([P, P, F])), "~/r.json")
        self.assertNotIn("NOT A PASS", lines[-1])
        text = "\n".join(lines)
        self.assertIn("2 of 3 runs passed, the case passes by majority", text)
        self.assertIn("run 3 reports-off-by-one", text)
        self.assertTrue(self.rec.is_green(batch(case([P, P, F]))))

    def test_pass_fail_fail_is_red(self):
        # 1 of 3 passes: no majority
        data = batch(case([P, F, F]))
        self.assertFalse(self.rec.is_green(data))
        self.assertIn("NOT A PASS: 2 meaning grader(s) failed, 0 not judged, in c", self.rec.report(data, "")[-1])

    def test_one_failing_case_among_passing_ones_is_named(self):
        data = batch(case([P, P, F], "a"), case([F, F, P], "b"))
        self.assertTrue(self.rec.report(data, "")[-1].endswith("in b"))

    def test_a_failed_code_grader_in_one_run_of_three_is_green(self):
        # the aa8cfd1 case: one run fails a code (regex) grader only
        c = case([P, P, P])
        c["arms"]["with"][0]["graders"].append({"name": "worker-started", "passed": False, "weight": 1})
        self.assertTrue(self.rec.is_green(batch(c)))
        c["arms"]["with"][1]["graders"].append({"name": "worker-started", "passed": False, "weight": 1})
        self.assertFalse(self.rec.is_green(batch(c)))

    def test_a_not_judged_run_still_makes_it_red(self):
        c = case([P, P, P]); c["arms"]["with"][2] = {"error": "max_turns", "graders": []}
        self.assertFalse(self.rec.is_green(batch(c)))

    def test_a_falling_rate_is_named(self):
        # earlier records: 3 of 3 passed; now 2 of 3, so the rate fell
        now = batch(case([P, P, F])); before = batch(case([P, P, P]))
        text = "\n".join(self.rec.report(now, "", [before]))
        self.assertIn("note: c: pass rate fell to 2 of 3 runs", text)
        self.assertNotIn("fell", "\n".join(self.rec.report(now, "", [batch(case([P, P, F]))])))
        self.assertNotIn("fell", "\n".join(self.rec.report(now, "")))


class VerdictCommand(unittest.TestCase):
    def setUp(self):
        self.rec = load_record()
        self.tmp = tempfile.mkdtemp(prefix="maj-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_verdict(self, data):
        path = os.path.join(self.tmp, "rec.json")
        json.dump(data, open(path, "w"))
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.rec.main(["--verdict", path])
        return code, out.getvalue(), path

    def test_verdict_recomputes_without_storing(self):
        os.environ["RELAY_HOME"] = os.path.join(self.tmp, "home")
        try:
            code, out, _ = self.run_verdict(batch(case([P, P, F])))
            self.assertEqual(code, 0); self.assertIn("ci: eval record: PASS", out)
            code, out, _ = self.run_verdict(batch(case([P, F, F])))
            self.assertEqual(code, 2); self.assertIn("ci: eval record: RED", out)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "home")))
        finally:
            os.environ.pop("RELAY_HOME", None)

    def test_an_unreadable_record_exits_1(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.rec.main(["--verdict", os.path.join(self.tmp, "none.json")]), 1)

    def test_main_names_a_fall_against_the_stored_records(self):
        home = os.path.join(self.tmp, "home"); os.environ["RELAY_HOME"] = home
        try:
            folder = os.path.join(home, "evals", "relay"); os.makedirs(folder)
            json.dump(batch(case([P, P, P])), open(os.path.join(folder, "2026-10-01T00-00-00Z-master.json"), "w"))
            path = os.path.join(self.tmp, "new.json"); json.dump(batch(case([P, P, F])), open(path, "w"))
            out = io.StringIO()
            with redirect_stdout(out):
                code = self.rec.main(["--json", path, "--repo", "relay", "--branch", "master"])
            self.assertEqual(code, 0); self.assertIn("pass rate fell to 2 of 3", out.getvalue())
        finally:
            os.environ.pop("RELAY_HOME", None)


if __name__ == "__main__":
    unittest.main()
