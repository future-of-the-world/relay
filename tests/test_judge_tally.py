"""Free tests of tally.py: unreadable input exits 2, and the expected answer is a stored field, not a name.
No test calls a model."""
import glob, importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JM = os.path.join(ROOT, "evals", "judge-measure")
TALLY = os.path.join(JM, "tally.py")


def load_tally():
    spec = importlib.util.spec_from_file_location("tally", TALLY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def cli(path, here=TALLY):
    return subprocess.run([sys.executable, "-I", here, path, "--expect-model", "haiku"], capture_output=True, text=True)


def result(votes_by_grader, runs=5):
    """One case, graders named by the caller, every run judged with the given 3 votes."""
    gs = [{"name": n, "type": "llm", "weight": 1} for n in votes_by_grader]
    run = {"score": 1, "passed": True, "costUsd": 0.01, "judgeCostUsd": 0.002, "skippedPaidGraders": False,
           "graders": [{"name": n, "passed": sum(v) >= 2, "weight": 1, "judgeVotes": v} for n, v in votes_by_grader.items()]}
    return {"partial": False, "suite": {"judgeModel": "haiku"},
            "cases": [{"name": "measure-x", "runsPerCase": runs, "graders": gs, "arms": {"with": [run] * runs}}]}


T, F = True, False


class UnreadableInput(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="jt-")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, content, mode="w"):
        p = os.path.join(self.d, "r.json")
        with open(p, mode) as f:
            f.write(content)
        return p

    def assert_not_judged(self, r):
        # exit 2 = not judged; 1 would read as "a bar is exceeded"
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("NOT JUDGED", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(r.stderr.strip().split("\n")), 1)   # one plain line

    def test_an_empty_file(self):
        self.assert_not_judged(cli("/dev/null"))

    def test_a_missing_file(self):
        self.assert_not_judged(cli(os.path.join(self.d, "nope.json")))

    def test_bytes_that_are_not_text(self):
        self.assert_not_judged(cli(self.write(b"\xff\xfe\x00\x80", "wb")))

    def test_json_of_another_shape(self):
        # a list, a case that is a string and a suite that is a number: none is an eval result
        for text in ('[]', '{"suite": 3}', '{"suite": {"judgeModel": "haiku"}, "cases": ["x"]}', '{"suite": {"judgeModel": "haiku"}, "cases": [{"name": "measure-off-by-one", "arms": 5}]}'):
            with self.subTest(text):
                self.assert_not_judged(cli(self.write(text)))


class ExpectedAnswerIsAField(unittest.TestCase):
    def setUp(self):
        self.t = load_tally()

    def tally(self, data, answers):
        return self.t.tally(data, "haiku", answers=answers)

    def test_the_stored_field_decides_not_the_name(self):
        # grader "yes--01-a" is stored as FAIL: three FAIL votes are right, so the case passes.
        # Read from the name it would expect PASS and count 5 wrong verdicts.
        code, lines = self.tally(result({"yes--01-a": [F, F, F], "no--02-b": [F, F, F]}), {"measure-x": {"yes--01-a": False, "no--02-b": False}})
        self.assertEqual(code, 0, lines)
        self.assertIn("0 wrong verdicts", "\n".join(lines))

    def test_a_no_name_stored_as_pass(self):
        code, lines = self.tally(result({"no--01-a": [T, T, T]}), {"measure-x": {"no--01-a": True}})
        self.assertEqual(code, 0, lines)

    def test_a_wrong_vote_is_still_wrong_by_the_field(self):
        code, lines = self.tally(result({"yes--01-a": [F, F, F]}), {"measure-x": {"yes--01-a": True}})
        self.assertEqual(code, 1)
        self.assertIn("yes--01-a judged 5 of 5 runs the wrong way", "\n".join(lines))

    def test_a_grader_without_a_stored_answer_is_not_judged_and_named(self):
        with self.assertRaises(self.t.NotJudged) as e:
            self.tally(result({"yes--01-a": [T, T, T], "x": [T, T, T]}), {"measure-x": {"yes--01-a": True}})
        self.assertIn("x", str(e.exception))
        with self.assertRaises(self.t.NotJudged):
            self.tally(result({"yes--01-a": [T, T, T]}), None)

    def test_a_grader_missing_from_answers_json_is_not_judged_and_named(self):
        d = tempfile.mkdtemp(prefix="jt-")
        try:
            shutil.copytree(JM, os.path.join(d, "jm"), ignore=shutil.ignore_patterns("results", "__pycache__"))
            here = os.path.join(d, "jm")
            g = os.path.join(here, "measure-doc-rule", "answers.json")
            with open(g, encoding="utf-8") as f:
                stored = json.load(f)
            del stored["no--06-pagecount-already-documented"]
            with open(g, "w", encoding="utf-8") as f:
                json.dump(stored, f)
            answers = self.t.load_answers(here)
            data = result({k: [T, T, T] for k in stored} | {"no--06-pagecount-already-documented": [F, F, F]})
            data["cases"][0]["name"] = "measure-doc-rule"
            with self.assertRaises(self.t.NotJudged) as e:
                self.t.tally(data, "haiku", answers=answers)
            self.assertIn("no--06-pagecount-already-documented", str(e.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_broken_eval_folder_is_not_blamed_on_the_input_file(self):
        d = tempfile.mkdtemp(prefix="jt-")
        try:
            here = os.path.join(d, "jm")
            shutil.copytree(JM, here, ignore=shutil.ignore_patterns("results", "__pycache__"))
            os.remove(os.path.join(here, "measure-doc-rule", "answers.json"))
            r = cli("/dev/null", os.path.join(here, "tally.py"))
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("eval folder", r.stderr)
            self.assertIn("answers.json", r.stderr)
            self.assertNotIn("/dev/null", r.stderr)
            self.assertEqual(len(r.stderr.strip().split("\n")), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_every_committed_grader_has_the_field_matching_its_name(self):
        # today's runs must tally the same: yes-- graders expect PASS, no-- graders FAIL
        answers = self.t.load_answers()
        self.assertEqual(sorted(answers), sorted(self.t.load_expected()))
        for case, gs in answers.items():
            self.assertTrue(gs, case)
            for name, want in gs.items():
                self.assertEqual(want, name.startswith("yes--"), name)


class GraderFilesLoadInTheEvalTool(unittest.TestCase):
    # the eval tool (claude plugin eval) builds a grader from {name, ...front matter, criteria: body} and
    # checks it with a strict schema: type, name, criteria, focus, weight, arm. Any other key refuses the case.
    ALLOWED = {"type", "focus", "weight", "arm"}

    def test_every_front_matter_key_is_one_the_eval_tool_accepts(self):
        seen = 0
        for fn in sorted(glob.glob(os.path.join(JM, "measure-*", "graders", "*.md"))):
            with open(fn, encoding="utf-8") as f:
                lines = f.read().split("\n")
            front = lines[1:lines.index("---", 1)]
            keys = {l.partition(":")[0].strip() for l in front if l.strip()}
            self.assertLessEqual(keys, self.ALLOWED, os.path.relpath(fn, JM))
            seen += 1
        self.assertEqual(seen, 59)


if __name__ == "__main__":
    unittest.main()
