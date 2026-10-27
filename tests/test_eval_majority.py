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

    def test_a_partial_record_is_left_out_of_the_baseline(self):
        # earlier: partial (c 0 of 3, ignored), 3 of 3, 3 of 3 -> baseline 6/6; now 2 of 3 is below it
        broken = batch(case([F, F, F])); broken["partial"] = True
        now = batch(case([P, P, F]))
        text = "\n".join(self.rec.report(now, "", [broken, batch(case([P, P, P])), batch(case([P, P, P]))]))
        self.assertIn("note: c: pass rate fell to 2 of 3 runs", text)

    def test_a_timed_out_run_is_a_failed_run_of_the_majority(self):
        # owner, 27 Oct, "7. a": PASS, PASS, timed out = 2 of 3 passed -> green, the summary names the timeout
        def timed(c, *idx):
            for i in idx:
                c["arms"]["with"][i] = {"error": "timed out after 600s", "graders": []}
            return c
        one = batch(timed(case([P, P, P]), 2))
        text = "\n".join(self.rec.report(one, ""))
        self.assertTrue(self.rec.is_green(one))
        self.assertIn("2 of 3 runs passed, 1 timed out", text)
        self.assertNotIn("not judged", text)
        # PASS, timed out, timed out = 1 of 3 -> red, and no run is called not judged
        two = batch(timed(case([P, P, P]), 1, 2))
        last = self.rec.report(two, "")[-1]
        self.assertFalse(self.rec.is_green(two))
        self.assertEqual(last, "ci: eval record: NOT A PASS: 0 meaning grader(s) failed, 2 run(s) timed out, 0 not judged, in c")
        # any other error stays not judged
        other = batch(case([P, P, P])); other["cases"][0]["arms"]["with"][2] = {"error": "max_turns", "graders": []}
        self.assertFalse(self.rec.is_green(other))

    def test_a_timed_out_run_counts_against_a_falling_pass_rate(self):
        # earlier 3 of 3; now PASS, PASS, timed out = 2 of 3, below it
        c = case([P, P, P]); c["arms"]["with"][2] = {"error": "timed out after 600s", "graders": []}
        text = "\n".join(self.rec.report(batch(c), "", [batch(case([P, P, P]))]))
        self.assertIn("note: c: pass rate fell to 2 of 3 runs", text)


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

    def test_earlier_records_skip_partial_and_take_the_newest_complete(self):
        folder = os.path.join(self.tmp, "f"); os.makedirs(folder)
        broken = batch(case([F, F, F])); broken["partial"] = True
        for name, d in (("01", broken), ("02", batch(case([P, P, P]))), ("03", batch(case([P, P, F])))):
            json.dump(d, open(os.path.join(folder, f"2026-10-{name}T00-00-00Z-master.json"), "w"))
        got = self.rec.earlier_records(folder)
        self.assertEqual([self.rec.case_rates(g)["c"] for g in got], [(3, 3), (2, 3)])  # 3 of 3 then 2 of 3, partial dropped
        # before the 03 record only 02 counts
        self.assertEqual(len(self.rec.earlier_records(folder, "2026-10-03T00-00-00Z-master.json")), 1)

    def test_verdict_compares_with_earlier_records_in_its_folder(self):
        folder = os.path.join(self.tmp, "evals"); os.makedirs(folder)
        json.dump(batch(case([P, P, P])), open(os.path.join(folder, "2026-10-01T00-00-00Z-master.json"), "w"))
        now = os.path.join(folder, "2026-10-02T00-00-00Z-master.json"); json.dump(batch(case([P, P, F])), open(now, "w"))
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.rec.main(["--verdict", now])
        self.assertEqual(code, 0); self.assertIn("pass rate fell to 2 of 3", out.getvalue())
        # alone in its folder: no fall note
        lone = os.path.join(self.tmp, "lone"); os.makedirs(lone)
        p2 = os.path.join(lone, "x.json"); json.dump(batch(case([P, P, F])), open(p2, "w"))
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.rec.main(["--verdict", p2])
        self.assertEqual(code, 0); self.assertNotIn("fell", out.getvalue())

    def test_a_red_store_prints_the_stored_path(self):
        home = os.path.join(self.tmp, "home"); os.environ["RELAY_HOME"] = home
        try:
            path = os.path.join(self.tmp, "new.json"); json.dump(batch(case([P, F, F])), open(path, "w"))
            out = io.StringIO()
            with redirect_stdout(out):
                code = self.rec.main(["--json", path, "--repo", "relay", "--branch", "master"])
            stored = os.path.join(home, "evals", "relay")
            self.assertEqual(code, 2)
            self.assertIn(f"--verdict {os.path.join(stored, os.listdir(stored)[0])} shows why", out.getvalue())
        finally:
            os.environ.pop("RELAY_HOME", None)


if __name__ == "__main__":
    unittest.main()
