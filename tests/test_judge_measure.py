"""Free tests of the meaning-judge measurement: make.py --check (T3) and tally.py (T4).
No test calls a model."""
import copy, importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS = os.path.join(ROOT, "evals")
MAKE = os.path.join(EVALS, "judge-measure", "make.py")
TALLY = os.path.join(EVALS, "judge-measure", "tally.py")


def load_tally():
    spec = importlib.util.spec_from_file_location("tally", TALLY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def check(root):
    return subprocess.run([sys.executable, "-I", MAKE, "--check", "--root", root], capture_output=True, text=True)


class MakeCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jm-")
        self.root = os.path.join(self.tmp, "evals")
        shutil.copytree(EVALS, self.root, ignore=shutil.ignore_patterns("fixture", "results", "scenarios", "baseline", "__pycache__"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, rel, fn):
        p = os.path.join(self.root, rel)
        t = open(p, encoding="utf-8").read(); open(p, "w", encoding="utf-8").write(fn(t))

    def test_committed_files_pass(self):
        r = check(EVALS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_grader_body_that_differs_from_the_production_rubric_fails(self):
        self.edit("judge-measure/measure-doc-rule/graders/yes--01-e-NnQ3lv.md", lambda t: t.replace("PASS if it does.", "PASS if it does, mostly."))
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("graders/yes--01-e-NnQ3lv.md differs", r.stdout)

    def test_a_production_rubric_change_makes_every_measurement_grader_stale(self):
        self.edit("plugin/code-reviewer-offbyone/graders/reports-off-by-one.md", lambda t: t + "Extra sentence.\n")
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("measure-off-by-one/graders/", r.stdout)

    def test_a_template_that_mentions_the_finding_outside_its_slot_fails(self):
        # N1: a "no" item built on it would still report the contradiction in a second place
        self.edit("judge-measure/measure-contradiction/templates/review.txt",
                  lambda t: t.replace("**Questions for the owner**", "**Questions for the owner** (the corrupt file: moved aside by D2)"))
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("mentions the finding outside its slot", r.stdout)

    def test_an_item_under_1000_characters_fails(self):
        self.edit("judge-measure/measure-role-rule/templates/a.txt", lambda t: "Short review.\n{{FINDING}}\n")
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("under 1000", r.stdout)

    def test_a_no_item_that_fails_the_code_check_fails(self):
        # the judge must decide every item: a "no" item the code already refuses measures nothing
        self.edit("judge-measure/measure-role-rule/written/wrong-passes.txt", lambda t: "- takeItem(amount) passes.\n")
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("does not pass", r.stdout)

    def test_a_recorded_wrong_reply_in_no_items_txt_fails(self):
        self.edit("judge-measure/measure-off-by-one/items.txt",
                  lambda t: "\n".join(l for l in t.split("\n") if "the-end-is-correct" not in l))
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("is in no items.txt", r.stdout)

    def test_a_no_item_without_a_template_fails(self):
        self.edit("judge-measure/measure-doc-rule/items.txt", lambda t: t.replace("no judge-measure/measure-doc-rule/written/checked-pagecount-ok.txt into templates/review.txt", "no judge-measure/measure-doc-rule/written/checked-pagecount-ok.txt"))
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("needs a template", r.stdout)


def llm_run(*grader_votes, **extra):
    gs = []
    for name, votes in grader_votes:
        g = {"name": name, "passed": bool(votes) and sum(votes) >= 2, "weight": 1, "explanation": "x"}
        if votes is not None: g["judgeVotes"] = votes
        gs.append(g)
    run = {"score": 1, "passed": True, "costUsd": 0.01, "judgeCostUsd": 0.002, "skippedPaidGraders": False, "graders": gs}
    run.update(extra)
    return run


def result(runs, model="haiku", **top):
    d = {"partial": False, "suite": {"judgeModel": model}, "cases": [{"name": "measure-x", "arms": {"with": runs}}]}
    d.update(top)
    return d


Y, N = "yes--01-a", "no--02-b"
T, F = True, False


class Tally(unittest.TestCase):
    def setUp(self):
        self.t = load_tally()

    def run_tally(self, data, **kw):
        return self.t.tally(copy.deepcopy(data), kw.pop("model", "haiku"), **kw)

    def test_a_clean_run_passes(self):
        code, lines = self.run_tally(result([llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(5)]))
        self.assertEqual(code, 0, lines); self.assertIn("PASS measure-x: 0 wrong verdicts of 10", "\n".join(lines))

    def test_a_no_item_that_got_pass_is_a_wrong_verdict(self):
        runs = [llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(4)] + [llm_run((Y, [T, T, T]), (N, [T, T, F]))]
        code, lines = self.run_tally(result(runs))
        self.assertEqual(code, 1); self.assertIn("1 wrong verdicts", "\n".join(lines)); self.assertIn("no--02-b judged 1 of 5 runs the wrong way", "\n".join(lines))

    def test_the_bar_can_be_raised_within_its_bound(self):
        runs = [llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(4)] + [llm_run((Y, [T, T, T]), (N, [T, T, T]))]
        self.assertEqual(self.run_tally(result(runs), max_wrong=1, max_split=1)[0], 0)

    def test_split_votes_count_as_a_split_item_and_fail_above_the_bar(self):
        runs = [llm_run((Y, [T, T, F]), (N, [F, F, T])) for _ in range(5)]
        code, lines = self.run_tally(result(runs))
        self.assertEqual(code, 1); self.assertIn("2 split items of 2", "\n".join(lines))
        self.assertEqual(self.run_tally(result(runs), max_split=2)[0], 0)

    def test_exit_2_cases_print_no_verdict(self):
        base = [llm_run((Y, [T, T, T]), (N, [F, F, F]))]
        cases = {
            "a skipped grader (passed false, no votes)": result(base + [llm_run((Y, [T, T, T]), (N, None))]),
            "a grader with 2 votes": result(base + [llm_run((Y, [T, T]), (N, [F, F, F]))]),
            "partial": result(base, partial=True, partialReason="cost ceiling reached"),
            "skippedPaidGraders": result([llm_run((Y, [T, T, T]), (N, [F, F, F]), skippedPaidGraders=True)]),
            "another judge model": result(base, model="sonnet"),
        }
        for what, data in cases.items():
            with self.subTest(what):
                with self.assertRaises(self.t.NotJudged):
                    self.run_tally(data)

    def test_cli_exit_codes(self):
        d = tempfile.mkdtemp(prefix="jm-")
        try:
            p = os.path.join(d, "r.json")
            json.dump(result([llm_run((Y, [T, T, T]), (N, None))]), open(p, "w"))
            r = subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2); self.assertEqual(r.stdout, ""); self.assertIn("not judged", r.stderr)
            json.dump(result([llm_run((Y, [T, T, T]), (N, [F, F, F]))]), open(p, "w"))
            self.assertEqual(subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True).returncode, 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
