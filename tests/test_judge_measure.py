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

    def test_the_off_by_one_fail_clause_has_no_words_a_right_answer_also_says(self):
        # Haiku failed right answers yes-03 (5 of 5 runs) and yes-05 (2 of 5) because a right reply says
        # "a page must hold at most 2" / cites the doc comment, and the FAIL clause named "stays within size"
        # and "as the doc says". The rubric must not carry those phrases again.
        t = open(os.path.join(EVALS, "plugin", "code-reviewer-offbyone", "graders", "reports-off-by-one.md"), encoding="utf-8").read()
        fail = " ".join(t[t.index("PASS if it does."):].split())
        for phrase in ("stays within size", "as the doc says"):
            self.assertNotIn(phrase, fail)

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

    def test_a_commented_out_items_line_does_not_count_as_listed(self):
        self.edit("judge-measure/measure-off-by-one/items.txt",
                  lambda t: t.replace("no plugin/code-reviewer-offbyone/recorded/bad/reports-off-by-one__the-end-is-correct.txt", "# no plugin/code-reviewer-offbyone/recorded/bad/reports-off-by-one__the-end-is-correct.txt"))
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("is in no items.txt", r.stdout)

    def test_a_known_wrong_answer_that_no_no_item_says_fails(self):
        self.edit("judge-measure/measure-off-by-one/items.txt",
                  lambda t: "\n".join(l for l in t.split("\n") if "one-parameter-too-many" not in l))
        r = check(self.root)
        self.assertEqual(r.returncode, 1); self.assertIn("known wrong answer", r.stdout); self.assertIn("one parameter too many", r.stdout)

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


def case_of(runs, name="measure-x", graders=(Y := "yes--01-a", N := "no--02-b")):
    """A case in the eval tool's shape: graders[] with name/type/weight, runsPerCase, arms of runs."""
    return {"name": name, "runsPerCase": 5, "maxTurns": 1,
            "graders": [{"name": g, "type": "llm", "weight": 1, "config": {}} for g in graders], "arms": {"with": runs}}


def errored_run():
    """What the tool returns for a run that threw (binary: graders: [], error set; partial stays false)."""
    return {"score": 0, "passed": False, "costUsd": 0.0, "judgeCostUsd": 0, "error": "scaffold_script failed",
            "skippedPaidGraders": False, "graders": []}


def result(runs, model="haiku", **top):
    d = {"partial": False, "suite": {"judgeModel": model}, "cases": [case_of(runs)]}
    d.update(top)
    return d


T, F = True, False


class Tally(unittest.TestCase):
    def setUp(self):
        self.t = load_tally()

    def run_tally(self, data, **kw):
        # the synthetic graders are named yes--/no-- by this test only; the answers are handed in as the stored field
        ans = {c["name"]: {g["name"]: g["name"].startswith("yes--") for g in c["graders"]} for c in data["cases"]}
        return self.t.tally(copy.deepcopy(data), kw.pop("model", "haiku"), answers=kw.pop("answers", ans), **kw)

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
        # base alone is 1 run of runsPerCase 5: a short sample is not a verdict either
        full = [llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(5)]
        cases.update({
            "a short sample (1 run of 5)": result(base),
            "every run errored (graders: [])": result([errored_run() for _ in range(5)]),
            "one run errored, four complete": result(full[:4] + [errored_run()]),
            "an item absent from one run": result(full[:4] + [llm_run((Y, [T, T, T]))]),
            "no cases": result(full, cases=[]),
            "a case without runs": result(full, cases=[case_of([])]),
        })
        for what, data in cases.items():
            with self.subTest(what):
                with self.assertRaises(self.t.NotJudged):
                    self.run_tally(data)

    def test_a_20_run_file_that_keeps_runsPerCase_5_tallies(self):
        # `--runs 20` writes 20 runs per arm but the case still says runsPerCase 5; 2 items x 20 runs = 40 verdicts
        runs = [llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(20)]
        code, lines = self.run_tally(result(runs))
        self.assertEqual(code, 0, lines); self.assertIn("PASS measure-x: 0 wrong verdicts of 40", "\n".join(lines))

    def test_a_case_missing_from_the_file_is_not_judged(self):
        full = [llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(5)]
        with self.assertRaises(self.t.NotJudged) as e:
            self.run_tally(result(full), expected={"measure-x": 2, "measure-y": 2})
        self.assertIn("measure-y", str(e.exception))

    def test_fewer_items_than_items_txt_is_not_judged(self):
        full = [llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(5)]
        with self.assertRaises(self.t.NotJudged) as e:
            self.run_tally(result(full), expected={"measure-x": 3})
        self.assertIn("items.txt", str(e.exception))
        self.assertEqual(self.run_tally(result(full), expected={"measure-x": 2})[0], 0)

    def test_the_committed_item_counts_are_what_main_expects(self):
        exp = self.t.load_expected()
        self.assertEqual(sorted(exp), ["measure-contradiction", "measure-doc-rule", "measure-off-by-one", "measure-role-rule", "measure-ru-style"])
        for name, n in exp.items():
            self.assertEqual(n, len([f for f in os.listdir(os.path.join(EVALS, "judge-measure", name, "graders")) if f.startswith(("yes--", "no--"))]))

    def test_cli_exit_codes(self):
        d = tempfile.mkdtemp(prefix="jm-")
        try:
            p = os.path.join(d, "r.json")
            json.dump(result([llm_run((Y, [T, T, T]), (N, None))]), open(p, "w"))
            r = subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2); self.assertEqual(r.stdout, ""); self.assertIn("NOT JUDGED", r.stderr)
            # the crashed run of the eval tool: four cases, every run graders: [] with error; the gate must not say PASS
            names = load_tally().load_expected()
            real = load_tally().load_answers()   # the committed graders and their stored expected answers
            gnames = lambda k: sorted(real[k])
            json.dump(result([], cases=[case_of([errored_run() for _ in range(5)], name=k, graders=gnames(k)) for k, n in names.items()]), open(p, "w"))
            r = subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2); self.assertEqual(r.stdout, ""); self.assertIn("errored", r.stderr)
            json.dump(result([], cases=[]), open(p, "w"))
            self.assertEqual(subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True).returncode, 2)
            full = [llm_run((Y, [T, T, T]), (N, [F, F, F])) for _ in range(5)]
            json.dump(result(full, cases=[case_of(full, name="measure-doc-rule")]), open(p, "w"))
            r = subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2); self.assertIn("missing case", r.stderr)
            # a complete run: the four real cases, every item of items.txt, 5 runs of 3 votes
            def complete(k):
                return [llm_run(*[(g, [real[k][g]] * 3) for g in gnames(k)]) for _ in range(5)]
            cases = [case_of(complete(name), name=name, graders=gnames(name)) for name in names]
            json.dump(result([], cases=cases), open(p, "w"))
            r = subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("PASS measure-off-by-one", r.stdout)
            cases[1]["graders"].pop()   # the result lists one item fewer than items.txt
            json.dump(result([], cases=cases), open(p, "w"))
            r = subprocess.run([sys.executable, "-I", TALLY, p, "--expect-model", "haiku"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2); self.assertIn("items.txt", r.stderr)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
