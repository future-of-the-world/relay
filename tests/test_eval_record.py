"""Free tests of the eval record step (bin/eval-record), the rule-file flag patterns and bin/ci's eval lines.
No test calls a model."""
import importlib.util, io, json, os, shutil, subprocess, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "evals", "plugin")


def load_record():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("eval_record", os.path.join(ROOT, "bin", "eval-record"))
    spec = importlib.util.spec_from_loader("eval_record", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m)
    return m


def grader(path):
    meta = {}
    lines = open(path, encoding="utf-8").read().split("\n")
    for line in lines[1:lines.index("---", 1)]:
        k, _, v = line.partition(":"); v = v.strip()
        meta[k.strip()] = json.loads(v) if v.startswith('"') else v
    return meta


class FlagPatterns(unittest.TestCase):
    """T2: the input_match of the three rule-file flags, tested as the eval tool applies it (JavaScript RegExp over the input JSON)."""
    HEREDOC = "cat > .ci/code-review.md <<'EOF'\nReviewed: head of wt/paging\nThe rule (.claude/kit/code-reviewer.md) applies; grep -rn x . ok\nEOF"
    CASES = [
        ("Bash", "cat .claude/kit/code-reviewer.md; ls .claude", True),
        ("Bash", "cd .claude && cat kit/code-reviewer.md", True),
        ("Bash", "G=/x/git; cd /p; $G rev-parse a; cat .claude/kit/code-reviewer.md; ls", True),
        ("Bash", "grep -rn ROLE-RULE .", True),
        ("Bash", "rg -uu RULE", True),
        ("Bash", 'cd "$TMPDIR" && cat .claude/kit/judge.md', True),        # N2a: a quote before the verb
        ("Bash", 'cat ".claude/kit/judge.md"', True),
        ("Bash", 'echo "x" ; cat .claude/kit/judge.md', True),
        ("Bash", "sed -n 1,20p ./.claude/kit/judge.md", True),
        ("Bash", "ls -la", False),
        ("Bash", "git diff master...wt/paging -- src/shelf.ts", False),
        ("Bash", HEREDOC, False),
        ("Bash", "grep -rn slice src/", False),                            # N2b: a recursive grep of the source tree
        ("Bash", 'grep -R "x" src', False),
        ("Read", {"file_path": "/x/.claude/kit/judge.md"}, True),
        ("Read", {"file_path": "/x/src/shelf.ts"}, False),
        ("Grep", {"pattern": "ROLE-RULE", "path": "/x"}, True),
        ("Grep", {"pattern": "x", "path": "/x/.claude"}, True),
        ("Grep", {"pattern": "slice", "path": "/x/src"}, False),
    ]

    def js(self, rx, text):
        code = "const [p,t]=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(String(new RegExp(p).test(t)))"
        return subprocess.run(["bun", "-e", code], input=json.dumps([rx, text]), capture_output=True, text=True, check=True).stdout == "true"

    def test_every_case(self):
        tool = {"Bash": "bash", "Read": "read", "Grep": "grep"}
        for case in ("code-reviewer-offbyone", "critic-role-rule"):
            for name, arg, want in self.CASES:
                g = grader(os.path.join(PLUGIN, case, "graders", f"rule-file-read-by-{tool[name]}.md"))
                self.assertEqual(g["tool"], name); self.assertEqual(g["min"], "0"); self.assertEqual(g["weight"], "0.001")
                text = json.dumps({"command": arg} if name == "Bash" else arg, separators=(",", ":"))
                with self.subTest(case=case, tool=name, arg=str(arg)[:50]):
                    self.assertEqual(self.js(g["input_match"], text), want)

    def test_both_cases_carry_the_same_patterns(self):
        for t in ("read", "grep", "bash"):
            a, b = (grader(os.path.join(PLUGIN, c, "graders", f"rule-file-read-by-{t}.md")) for c in ("code-reviewer-offbyone", "critic-role-rule"))
            self.assertEqual(a, b)


def fixture(votes_by_run, partial=None, flagged_runs=(), no_votes=False, evidence="intro\nF1 HIGH src/shelf.ts:27: slice end\nmore"):
    runs = []
    for n, votes in enumerate(votes_by_run, 1):
        gs = [{"name": "reports-off-by-one", "passed": sum(votes) >= 2, "weight": 1, "explanation": "judge votes", "evidence": evidence}]
        if not no_votes:
            gs[0]["judgeVotes"] = votes
        gs.append({"name": "rule-file-read-by-bash", "passed": True, "weight": 0.001,
                   "explanation": f"Bash called {1 if n in flagged_runs else 0}x (expected 0..∞)"})
        runs.append({"graders": gs})
    d = {"startedAt": "2026-10-22T14:48:17.123Z", "partial": bool(partial), "suite": {"judgeModel": "haiku"},
         "cases": [{"name": "code-reviewer-offbyone",
                    "graders": [{"name": "reports-off-by-one", "type": "llm"},
                                {"name": "names-file-and-line", "type": "regex", "config": {"pattern": r"(?:^|\n)[^\n]*shelf\.ts:\s?2[5-8]\b", "flags": "i"}},
                                {"name": "rule-file-read-by-bash", "type": "tool_used"}],
                    "arms": {"with": runs}}]}
    if partial: d["partialReason"] = partial
    return d


EVIDENCE = ("- **F2 HIGH, DOC-RULE** `src/shelf.ts:30`: the exported function `pageCount` has no doc comment.\n"
            "- src/shelf.ts:27: the end is correct\nmore")


def real_case(runs):
    """code-reviewer-offbyone as the eval tool lists it: the case's graders in file order (regex checks
    first, follows-project-rule before names-file-and-line), the patterns read from the committed graders."""
    def regex(n):
        g = grader(os.path.join(PLUGIN, "code-reviewer-offbyone", "graders", n + ".md"))
        return {"name": n, "type": "regex", "config": {"pattern": g["pattern"], "flags": g.get("flags", "")}}
    return {"name": "code-reviewer-offbyone", "runsPerCase": len(runs),
            "graders": [{"name": "agent-used", "type": "tool_used"}, regex("follows-project-rule"), regex("names-file-and-line"),
                        {"name": "reports-doc-rule-breach", "type": "llm"}, {"name": "reports-off-by-one", "type": "llm"}],
            "arms": {"with": runs}}


def real_run(**failed):
    gs = [{"name": n, "passed": not failed.get(n), "weight": 1, "judgeVotes": [False] * 3 if failed.get(n) else [True] * 3,
           "explanation": "judge votes", "evidence": EVIDENCE} for n in ("reports-doc-rule-breach", "reports-off-by-one")]
    return {"error": None, "graders": gs}


class RecordRealShapes(unittest.TestCase):
    """The tool's own shapes: both code checks of one case in file order, a run that threw (graders: [])."""
    def setUp(self):
        self.rec = load_record()

    def report(self, runs):
        return "\n".join(self.rec.report({"cases": [real_case(runs)]}, "~/rec.json"))

    def test_each_failed_meaning_grader_shows_its_own_code_checks_line(self):
        out = self.report([real_run(**{"reports-off-by-one": True})])
        self.assertIn('judged: "- src/shelf.ts:27: the end is correct"', out); self.assertNotIn("pageCount", out)
        out = self.report([real_run(**{"reports-doc-rule-breach": True})])
        self.assertIn("judged: \"- **F2 HIGH, DOC-RULE** `src/shelf.ts:30`: the exported function `pageCount`", out); self.assertNotIn("the end is correct", out)

    def test_a_run_that_threw_is_counted_not_judged_and_never_silent(self):
        crashed = {"error": "scaffold_script failed", "graders": []}
        out = self.report([real_run(), crashed, real_run()])
        self.assertIn("1 not judged", out.split("\n")[0]); self.assertIn("run 2: the run errored (scaffold_script failed)", out)

    def test_a_meaning_grader_missing_from_a_run_is_not_judged(self):
        short = real_run(); short["graders"] = short["graders"][:1]
        out = self.report([real_run(), short])
        self.assertIn("1 not judged", out.split("\n")[0]); self.assertIn("run 2 reports-off-by-one: not judged", out)


class Record(unittest.TestCase):
    def setUp(self):
        self.rec = load_record()
        self.tmp = tempfile.mkdtemp(prefix="rec-")
        self.home = os.path.join(self.tmp, "home"); self.json = os.path.join(self.tmp, "evals.json")
        os.environ["RELAY_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("RELAY_HOME", None)
        for root, dirs, _ in os.walk(self.tmp):   # the fixtures mimic the tool's read-only folders
            for d in dirs: os.chmod(os.path.join(root, d), 0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_step(self, data, **kw):
        if data is not None: json.dump(data, open(self.json, "w"))
        argv = ["--json", self.json, "--repo", "relay", "--branch", "wt/role-bases"]
        for k, v in kw.items(): argv += [f"--{k}", str(v)]
        out = io.StringIO()
        with redirect_stdout(out): code = self.rec.main(argv)
        return code, out.getvalue()

    def test_a_fresh_file_is_copied_and_old_ones_pruned_to_the_newest_30(self):
        folder = os.path.join(self.home, "evals", "relay"); os.makedirs(folder)
        for i in range(30): open(os.path.join(folder, f"2026-01-{i + 1:02d}T00-00-00Z-old.json"), "w").write("{}")
        code, out = self.run_step(fixture([[True] * 3] * 3))
        self.assertEqual(code, 0)
        names = sorted(os.listdir(folder))
        self.assertEqual(len(names), 30)
        self.assertNotIn("2026-01-01T00-00-00Z-old.json", names)
        self.assertIn("2026-10-22T14-48-17Z-wt-role-bases.json", names)

    def test_the_summary_line_ends_with_the_run_cost(self):
        d = fixture([[True] * 3]); d["costUsd"] = 9.3149  # rounds to cents: $9.31
        _, out = self.run_step(d)
        self.assertIn("0 meaning grader(s) failed, 0 split votes, cost $9.31", out.split("\n")[0])
        d.pop("costUsd")
        _, out = self.run_step(d)
        self.assertNotIn("cost $", out)

    def test_a_failed_grader_prints_votes_and_the_judged_line_matching_the_code_check(self):
        _, out = self.run_step(fixture([[True] * 3, [False, False, True]]))   # 1 of 2 runs pass: no majority, so the failure counts
        self.assertIn("1 meaning grader(s) failed, 1 split vote", out)
        self.assertIn("FAIL code-reviewer-offbyone run 2 reports-off-by-one: votes FAIL FAIL PASS", out)
        self.assertIn('judged: "F1 HIGH src/shelf.ts:27: slice end"', out)
        self.assertIn("record: ", out)

    def test_the_judged_line_is_the_first_200_characters_when_no_line_matches(self):
        _, out = self.run_step(fixture([[False] * 3], evidence="x" * 300))
        self.assertIn('judged: "' + "x" * 200 + '"', out); self.assertNotIn("x" * 201, out)

    def test_a_passing_split_vote_is_a_note_and_counted_unanimous_votes_print_nothing(self):
        _, out = self.run_step(fixture([[True, False, True]]))
        self.assertIn("0 meaning grader(s) failed, 1 split vote", out)
        self.assertIn("note: code-reviewer-offbyone run 1 reports-off-by-one passed on a split vote (PASS FAIL PASS)", out)
        _, quiet = self.run_step(fixture([[True] * 3, [False] * 3]))
        self.assertNotIn("split vote (", quiet); self.assertIn("0 split votes", quiet)

    def test_a_rule_file_read_is_a_note_naming_the_run(self):
        _, out = self.run_step(fixture([[True] * 3] * 3, flagged_runs=(2,)))
        self.assertIn("a session in the run read the rule file in 1 of 3 runs (run 2, Bash), so those runs do not prove the hook delivered it", out)

    def batch_with_traces(self, passes):
        """A batch whose runs have scaffold folders <tmp>/e-x/out/trace.jsonl, as the tool leaves them under --keep-temp."""
        data = fixture([[True] * 3 if ok else [False] * 3 for ok in passes])
        folders = []
        for n, run in enumerate(data["cases"][0]["arms"]["with"], 1):
            top = os.path.join(self.tmp, f"e-run{n}"); os.makedirs(os.path.join(top, "out"))
            with open(os.path.join(top, "out", "trace.jsonl"), "w") as handle:
                handle.write(f"trace {n}\n")
            run["tracePath"] = os.path.join(top, "out", "trace.jsonl"); folders.append(top)
            # the real layout: sealed/ mode 000, the top folder r-x (measured on /private/tmp/e-*)
            os.makedirs(os.path.join(top, "sealed")); os.chmod(os.path.join(top, "sealed"), 0)
            os.chmod(top, 0o500)
        return data, folders

    def test_a_red_batch_keeps_the_failing_runs_traces_where_the_record_names_them(self):
        # runs 1 and 2 fail (0 of 3 votes), run 3 passes: 1 of 3 runs pass, so the case is red (majority rule); the failing runs' traces are copied, run 3's is not
        data, folders = self.batch_with_traces([False, False, True])
        code, out = self.run_step(data)
        self.assertEqual(code, 2)
        stored = json.load(open(os.path.join(self.home, "evals", "relay", os.listdir(os.path.join(self.home, "evals", "relay"))[0])))
        runs = stored["cases"][0]["arms"]["with"]
        self.assertEqual([("keptTracePath" in r) for r in runs], [True, True, False])
        self.assertEqual(open(runs[1]["keptTracePath"]).read(), "trace 2\n")
        for r in runs[:2]:
            self.assertIn("trace: " + r["keptTracePath"], out)
        self.assertEqual([os.path.exists(f) for f in folders], [False] * 3)   # the tool's temp folders are gone

    def test_a_green_batch_keeps_no_trace_and_removes_the_temp_folders(self):
        data, folders = self.batch_with_traces([True, True, True])
        code, _ = self.run_step(data)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.home, "eval-traces")))
        self.assertEqual([os.path.exists(f) for f in folders], [False] * 3)

    def test_a_folder_that_is_not_the_tools_scaffold_is_never_removed(self):
        data, _ = self.batch_with_traces([True, True, True])
        other = os.path.join(self.tmp, "mine"); os.makedirs(os.path.join(other, "out"))
        open(os.path.join(other, "out", "trace.jsonl"), "w").close()
        data["cases"][0]["arms"]["with"][0]["tracePath"] = os.path.join(other, "out", "trace.jsonl")
        self.run_step(data)
        self.assertTrue(os.path.exists(other))

    def test_an_errored_run_and_a_failed_code_grader_print_their_kept_trace(self):
        # F3: run 1 errored, run 2 fails the code grader only (meaning grader passes): both copies are named in the output
        data, _ = self.batch_with_traces([True, True, True])
        runs = data["cases"][0]["arms"]["with"]
        runs[0] = dict(tracePath=runs[0]["tracePath"], error="boom")
        runs[1]["graders"].append({"name": "names-file-and-line", "passed": False})
        code, out = self.run_step(data)
        self.assertEqual(code, 2)
        stored = json.load(open(os.path.join(self.home, "evals", "relay", os.listdir(os.path.join(self.home, "evals", "relay"))[0])))
        kept = [r["keptTracePath"] for r in stored["cases"][0]["arms"]["with"][:2]]
        for path in kept:
            self.assertIn("trace: " + path, out)

    def test_trace_copies_are_pruned_with_their_record(self):
        old = os.path.join(self.home, "eval-traces", "relay", "2026-01-01T00-00-00Z-old", "c-with-run1"); os.makedirs(old)
        os.makedirs(os.path.join(self.home, "evals", "relay"))
        open(os.path.join(self.home, "evals", "relay", "2026-01-02T00-00-00Z-old.json"), "w").write("{}")
        self.run_step(fixture([[True] * 3]))
        self.assertFalse(os.path.exists(os.path.dirname(old)))

    def test_no_file_prints_no_record_and_exits_2(self):
        code, out = self.run_step(None)
        self.assertEqual(code, 2); self.assertIn("plugin evals wrote no record", out); self.assertFalse(os.path.exists(self.home))

    def test_partial_prints_the_reason_once(self):
        _, out = self.run_step(fixture([[True] * 3] * 2, partial="cost ceiling reached"))
        self.assertEqual(out.count("cost ceiling reached"), 1)

    def test_a_grader_without_votes_is_not_judged_never_votes(self):
        _, out = self.run_step(fixture([[True] * 3], no_votes=True))
        self.assertIn("not judged (cost ceiling)", out); self.assertNotIn("votes ", out.replace("split votes", "")); self.assertNotIn("FAIL code-reviewer", out)

    def test_a_copy_that_cannot_be_made_exits_1(self):
        os.makedirs(self.home); open(os.path.join(self.home, "evals"), "w").write("a file where the folder should be")
        code, out = self.run_step(fixture([[True] * 3]))
        self.assertEqual(code, 1); self.assertIn("could not store the eval record", out)


if __name__ == "__main__":
    unittest.main()
