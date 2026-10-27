"""The change-cycle workflow script (plugins/delegate/workflows/cycle.js), run against a fake Workflow runtime
(plugins/delegate/tests/fake-workflow.js, on Bun) with scripted agent answers: no model, no paid run.
Expected labels and stops are worked out by hand from the design (stage order of each kind), not printed from the script."""
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "plugins", "delegate", "workflows", "cycle.js")
FAKE = os.path.join(ROOT, "plugins", "delegate", "tests", "fake-workflow.js")
def _stage_label():
    spec = importlib.util.spec_from_file_location("ledger_hook", os.path.join(ROOT, "plugins", "observe", "hooks", "ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.STAGE_LABEL


LABEL = _stage_label()   # one grammar: the ledger's
STOPS = {"build", "gate", "fix red gate", "review", "fix", "check", "check item", "close queue item", "check show", "owner", "crash"}

DONE = {"status": "DONE", "summary": "ok"}
GREEN = {
    "stage:build": DONE, "stage:fix": DONE, "stage:fix red gate": DONE, "stage:close queue item": DONE, "stage:check show": DONE,
    "stage:design": DONE, "stage:design review": DONE, "stage:design revise": DONE,
    "stage:gate": {"ok": True, "gate_log": "gate.log"},
    "stage:review": {"inside": 0, "outside": 0, "design_or_question": False, "remaining": False, "main_point": "none"},
    "stage:check": {"open": 0, "fail_without_fix": "yes", "summary": "open 0", "q1_test": "tests/a.py::A::b"},
    "stage:check item": {"open": 0, "fail_without_fix": "yes", "summary": "open 0"},
}
RED = {"ok": False, "gate_log": "gate.log", "first_fail": "boom"}
INSIDE = {"inside": 1, "outside": 0, "design_or_question": False, "remaining": False, "main_point": "one"}


class Cycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("bun"):
            raise AssertionError("bun is a gate tool and must be on PATH")

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cycle-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.wt = os.path.join(self.tmp, "wt-x")
        self.scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(self.wt)

    def unit(self, **kw):
        base = {"name": "x", "wt": self.wt, "check": "pytest -q", "branch": "wt/x"}
        base.update(kw)
        return base

    def args(self, items, relay=True, **kw):
        a = {"base": "master", "relay": relay, "scratch": self.scratch, "items": items}
        if not relay:
            a["gate"] = "make test"
        a.update(kw)
        return a

    def run_cycle(self, args, **answers):
        table = dict(GREEN)
        table.update(answers)
        path = os.path.join(self.tmp, "scenario.json")
        with open(path, "w") as handle:
            json.dump({"args": args, "answers": table}, handle)
        done = subprocess.run(["bun", FAKE, "run", SCRIPT, path], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        out["labels"] = [e["label"] for e in out["events"] if e["event"] == "start"]
        out["prompts"] = {e["label"]: e["prompt"] for e in out["events"] if e["event"] == "start"}
        return out

    # 1
    def test_green_change_runs_one_checker_then_closes_the_item(self):
        """Stages of a change with an item, by the design: build, gate, review, ONE check, close, check show. Disabled
        rule (the old split): a second 'check queue item' agent would put a second checker in the list."""
        out = self.run_cycle(self.args([self.unit(item="the-item")]))
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "review: x", "check: x", "close queue item: x", "check show: x"])
        types = [e["agentType"] for e in out["events"] if e["event"] == "start"]
        self.assertEqual(types.count("delegate:checker"), 1)
        self.assertTrue(out["result"]["changes"][0]["ready"])
        self.assertIn("relay queue done the-item -C", out["prompts"]["close queue item: x"])
        self.assertIn("--test tests/a.py::A::b", out["prompts"]["close queue item: x"])

    def test_no_item_no_close_and_project_mode_has_no_queue_or_show(self):
        """Without an item: no close stage. Project mode (relay false): neither close nor check show."""
        out = self.run_cycle(self.args([self.unit()]))
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "review: x", "check: x", "check show: x"])
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False))
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "review: x", "check: x"])

    # 2
    def test_red_gate_fixed_once_then_stops(self):
        """gate_fixes defaults to 1: red, fix red gate 1, gate 2 green. Red twice: stops at gate after gate 2."""
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}})
        self.assertEqual(out["labels"][:5], ["build: x", "gate 1: x", "fix red gate 1: x", "gate 2: x", "review: x"])
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": RED})
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "fix red gate 1: x", "gate 2: x"])
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "gate")
        out = self.run_cycle(self.args([self.unit(), ], settings={"gate_fixes": 0}), **{"stage:gate": RED})
        self.assertEqual(out["labels"], ["build: x", "gate 1: x"])

    def test_red_gate_after_the_review_fix_numbers_go_on(self):
        """gate 1 red, fix red gate 1, gate 2 green, review (1 inside), fix, gate 3 red, fix red gate 2, gate 4 green."""
        gates = {"$seq": [RED, GREEN["stage:gate"], RED, GREEN["stage:gate"]]}
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": gates, "stage:review": INSIDE})
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "fix red gate 1: x", "gate 2: x", "review: x", "fix: x",
                                         "gate 3: x", "fix red gate 2: x", "gate 4: x", "check: x", "check show: x"])

    def test_still_running_stops_without_a_fixer(self):
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": {"ok": False, "gate_log": "l", "first_fail": "still running, pid 5, log l"}})
        self.assertEqual(out["labels"], ["build: x", "gate 1: x"])
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "gate")

    # 3
    def test_design_finding_stops_at_owner_and_open_check_stops_at_check(self):
        review = dict(GREEN["stage:review"], design_or_question=True, inside=2, main_point="design is wrong")
        out = self.run_cycle(self.args([self.unit()]), **{"stage:review": review})
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "owner")
        self.assertFalse([l for l in out["labels"] if l.startswith("fix")])
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:check": dict(GREEN["stage:check"], open=1)})
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "check")
        self.assertNotIn("close queue item: x", out["labels"])

    # 4
    def test_a_dead_agent_is_retried_once_under_the_same_label(self):
        throw = {"$throw": "subagent completed without calling StructuredOutput"}
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": {"$seq": [throw, GREEN["stage:gate"]]}})
        self.assertEqual(out["labels"].count("gate 1: x"), 2)
        self.assertTrue(out["result"]["changes"][0]["ready"])
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": throw})
        self.assertEqual(out["labels"].count("gate 1: x"), 2)
        change = out["result"]["changes"][0]
        self.assertEqual(change["stopped_at"], "gate")
        self.assertIn("StructuredOutput", change["detail"])
        out = self.run_cycle(self.args([self.unit()], settings={"retry_dead": 0}), **{"gate 1: x": throw})
        self.assertEqual(out["labels"].count("gate 1: x"), 1)

    def test_a_skipped_agent_stops_the_unit_at_once(self):
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": None})
        self.assertEqual(out["labels"].count("gate 1: x"), 1)
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "gate")

    # 5
    def test_fix_and_recheck_kinds(self):
        fix = self.unit(kind="fix", fix="Fix it.", fixes="fix.md", findings="review.json", item="i")
        out = self.run_cycle(self.args([fix]))
        self.assertEqual(out["labels"], ["fix: x", "gate 1: x", "check: x", "close queue item: x", "check show: x"])
        self.assertEqual(out["prompts"]["fix: x"], "Fix it.")
        rider = self.unit(kind="recheck", items=[{"slug": "a", "review": "ra.json"}, {"slug": "b", "review": "rb.json"}])
        out = self.run_cycle(self.args([rider]))
        self.assertEqual(out["labels"], ["gate 1: x", "check item 1: x", "check item 2: x", "check show: x"])
        self.assertIn("--item a --review ra.json", out["prompts"]["check item 1: x"])
        self.assertIn("--item b --review rb.json", out["prompts"]["check item 2: x"])
        order = [(e["event"], e["label"]) for e in out["events"] if e["label"].startswith("check item")]
        self.assertEqual(order, [("start", "check item 1: x"), ("end", "check item 1: x"), ("start", "check item 2: x"), ("end", "check item 2: x")])

    def test_recheck_stops_at_the_first_open_item_check(self):
        rider = self.unit(kind="recheck", items=[{"slug": "a", "review": "ra.json"}, {"slug": "b", "review": "rb.json"}])
        out = self.run_cycle(self.args([rider]), **{"check item 1: x": {"open": 1, "fail_without_fix": "no", "summary": "open 1"}})
        self.assertEqual(out["labels"], ["gate 1: x", "check item 1: x"])
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "check item")

    def test_recheck_one_item_names_it_and_no_items_gives_one_plain_check(self):
        out = self.run_cycle(self.args([self.unit(kind="recheck", items=[{"slug": "a", "review": "ra.json"}])]))
        self.assertEqual(out["labels"], ["gate 1: x", "check item 1: x", "check show: x"])
        self.assertIn("--item a", out["prompts"]["check item 1: x"])
        out = self.run_cycle(self.args([self.unit(kind="recheck", findings="relay check findings -C t")]))
        self.assertEqual(out["labels"], ["gate 1: x", "check: x", "check show: x"])

    def test_built_with_a_fix_prompt_is_refused_in_one_line(self):
        out = self.run_cycle(self.args([self.unit(kind="built", built="by hand", fix="Fix it.")]))
        self.assertEqual(out["labels"], [])
        self.assertIn("fix", out["result"]["refused"])
        self.assertNotIn("\n", out["result"]["refused"])

    # 6
    def test_empty_q1_test_stops_at_check_and_a_refused_close_stops_at_close(self):
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:check": dict(GREEN["stage:check"], q1_test="")})
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "check")
        self.assertNotIn("close queue item: x", out["labels"])
        blocked = {"status": "BLOCKED", "summary": "relay queue: test form wrong"}
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:check": dict(GREEN["stage:check"], q1_test="bad"), "stage:close queue item": blocked})
        change = out["result"]["changes"][0]
        self.assertEqual(change["stopped_at"], "close queue item")
        self.assertEqual(change["detail"], "relay queue: test form wrong")

    # 7
    def test_every_label_and_stop_is_in_the_stage_grammar(self):
        scenarios = [
            (self.args([self.unit(item="i")]), {"stage:review": INSIDE, "stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}}),
            (self.args([self.unit(kind="fix", fix="f", fixes="f.md", findings="r.json", item="i")]), {"stage:check": dict(GREEN["stage:check"], open=2)}),
            (self.args([self.unit(kind="recheck", items=[{"slug": "a", "review": "r"}])]), {}),
            (self.args([self.unit(kind="built", built="b")]), {"stage:review": dict(GREEN["stage:review"], remaining=True)}),
            (self.args([self.unit()], designs=[{"name": "d", "brief": "b.md", "out": "d.md"}]), {"stage:build": None}),
            (self.args([self.unit()]), {"stage:gate": None}),
        ]
        seen_labels, seen_stops = [], []
        for args, answers in scenarios:
            out = self.run_cycle(args, **answers)
            seen_labels += out["labels"]
            seen_stops += [c["stopped_at"] for c in out["result"]["changes"] if "stopped_at" in c]
        self.assertTrue(seen_labels and seen_stops)
        self.assertEqual([l for l in seen_labels if not LABEL.match(l)], [])
        self.assertEqual([s for s in seen_stops if s not in STOPS], [])
        self.assertGreaterEqual(len({l.split(":")[0] for l in seen_labels}), 8)   # the set above reaches most stage words

    # 8
    def test_meta_is_a_pure_literal_naming_every_phase_and_the_file_is_small(self):
        done = subprocess.run(["bun", FAKE, "meta", SCRIPT], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        meta = json.loads(done.stdout)
        self.assertEqual(meta["name"], "cycle")
        titles = {p["title"] for p in meta["phases"]}
        used = set()
        for args, answers in [(self.args([self.unit(item="i")], designs=[{"name": "d", "brief": "b", "out": "d.md"}]), {"stage:review": INSIDE})]:
            out = self.run_cycle(args, **answers)
            used |= {e["phase"] for e in out["events"] if e["event"] == "start"}
        self.assertEqual(used - titles, set())
        self.assertEqual(titles, {"Build", "Gate", "Review", "Fix", "Check", "Design"})
        self.assertLess(os.path.getsize(SCRIPT), 524288)
        with open(SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("Date.now", text)
        self.assertNotIn("Math.random", text)

    def test_the_fake_rejects_a_meta_that_is_not_a_literal(self):
        bad = os.path.join(self.tmp, "bad.js")
        with open(bad, "w") as handle:
            handle.write("export const meta = { name: 'x', phases: [{ title: PHASE }] }\n")
        done = subprocess.run(["bun", FAKE, "meta", bad], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 3)

    # 9
    def relay_commands(self, prompts):
        found = []
        for text in prompts:
            for span in re.findall(r"`(relay [^`]+)`", text):
                found.append(span)
        return found

    def bad_commands(self, commands):
        """The relay commands that do not parse, run with an empty temporary folder as the working folder."""
        home = tempfile.mkdtemp(prefix="cycle-home-")
        self.addCleanup(shutil.rmtree, home, True)
        env = dict(os.environ, RELAY_HOME=home, RELAY_ROOT=ROOT)
        bad = []
        for cmd in commands:
            words = shlex.split(cmd)[1:]
            done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay")] + words, cwd=self.wt, env=env,
                                  capture_output=True, text=True, timeout=60)
            text = done.stdout + done.stderr
            if done.returncode == 2 or "unknown option" in text or "unknown command" in text or "usage" in text.lower():
                bad.append(cmd)
        return bad

    def test_every_relay_command_the_prompts_name_still_parses(self):
        """Rendered from the script's own defaults (no gate_args). The two removed forms are the regression cases."""
        units = [self.unit(item="the-item"), self.unit(name="y", kind="fix", fix="f", fixes="f.md", findings="r.json", item="j"),
                 self.unit(name="z", kind="recheck", items=[{"slug": "a", "review": "ra.json"}])]
        out = self.run_cycle(self.args(units, designs=[{"name": "d", "brief": "b.md", "out": os.path.join(self.tmp, "d.md")}]),
                             **{"stage:review": INSIDE})
        commands = self.relay_commands(out["prompts"].values())
        self.assertTrue(any(c.startswith("relay gate -C") and c.endswith("-- --quick") for c in commands))
        self.assertTrue(any(c.startswith("relay queue done") for c in commands))
        self.assertTrue(any(c.startswith("relay check findings") for c in commands))
        self.assertTrue(any(c.startswith("relay check show") for c in commands))
        self.assertEqual(self.bad_commands(commands), [])
        removed = [f"relay queue done s -C {self.wt} --check x.json", f"relay gate -C {self.wt} --quick"]
        self.assertEqual(self.bad_commands(removed), removed)

    # 10
    def test_check_and_design_review_prompts_keep_the_report_label_the_hook_reads(self):
        spec = importlib.util.spec_from_file_location("check_mark", os.path.join(ROOT, "plugins", "core", "hooks", "check-mark.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        units = [self.unit(), self.unit(name="z", kind="recheck", items=[{"slug": "a", "review": "ra.json"}])]
        out = self.run_cycle(self.args(units, designs=[{"name": "d", "brief": "b.md", "out": "d.md"}]))
        for label in ("check: x", "check item 1: z", "design review: d"):
            found = mod.report_label(out["prompts"][label])
            self.assertTrue(found and found.endswith(".json"), f"{label}: {found}")

    # 11
    def test_no_fixed_path_in_any_prompt_and_no_relay_in_project_mode(self):
        banned = ("/Users/", "/private/", ".worktrees/", "scratchpad")
        with open(SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        for word in banned:
            self.assertNotIn(word, text)
        for relay in (True, False):
            units = [self.unit(**({"item": "i"} if relay else {})), self.unit(name="y", kind="fix", fix="f", fixes="f.md", findings="r.json"),
                      self.unit(name="z", kind="recheck", items=[{"slug": "a", "review": "ra.json"}]), self.unit(name="w", kind="built", built="b")]
            out = self.run_cycle(self.args(units, relay=relay, base="main", designs=[{"name": "d", "brief": "b.md", "out": "d.md"}]),
                                 **{"stage:review": INSIDE, "stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}})
            self.assertTrue(len(out["prompts"]) > 10)
            for label, prompt in out["prompts"].items():
                # the test's own temp dir is passed in as an argument (it may sit under /private/ when TMPDIR does);
                # only paths the script itself wrote may not appear
                prompt = prompt.replace(self.tmp, "<tmp>")
                for word in banned:
                    self.assertNotIn(word, prompt, label)
                self.assertNotIn("master", prompt, label)
                if not relay:
                    self.assertNotIn(".relay/", prompt, label)
                    self.assertNotIn("relay gate", prompt, label)
        self.assertIn("main...HEAD", out["prompts"]["review: x"])

    def test_project_gate_writes_the_head_and_exit_log(self):
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False))
        prompt = out["prompts"]["gate 1: x"]
        self.assertIn('echo "head $(git -C', prompt)
        self.assertIn("make test", prompt)
        self.assertIn('echo "exit $?"', prompt)

    # 12
    def test_missing_required_args_refuse_before_any_agent(self):
        full = self.args([self.unit()])
        for key in ("base", "relay", "scratch"):
            args = {k: v for k, v in full.items() if k != key}
            out = self.run_cycle(args)
            self.assertEqual(out["labels"], [], key)
            self.assertIn(key, out["result"]["refused"])
            self.assertNotIn("\n", out["result"]["refused"])
        args = self.args([self.unit(branch=None)], relay=False)
        del args["gate"]
        out = self.run_cycle(args)
        self.assertEqual(out["labels"], [])
        self.assertIn("gate", out["result"]["refused"])

    def test_base_names_the_review_range(self):
        out = self.run_cycle(self.args([self.unit()], base="main"))
        self.assertIn("`main...HEAD`", out["prompts"]["review: x"])
        out = self.run_cycle(self.args([self.unit()], base="master"))
        self.assertIn("`master...HEAD`", out["prompts"]["review: x"])

    def test_design_kind_reports_json_and_review_false_is_one_thinker(self):
        d = {"name": "d", "brief": "b.md", "out": os.path.join(self.tmp, "d.md")}
        out = self.run_cycle(self.args([], designs=[d]))
        self.assertEqual(out["labels"], ["design: d", "design review: d", "design revise: d"])
        self.assertIn(os.path.join(self.tmp, "d-review.json"), out["prompts"]["design revise: d"])
        out = self.run_cycle(self.args([], designs=[dict(d, review=False)]))
        self.assertEqual(out["labels"], ["design: d"])

    # review-fix round: F1 fixes line of the check, F2 project gate retry, F3 report names of a fix run
    def fixes_of(self, out, label="check: x"):
        return re.search(r"Fixes: `([^`]*)`", out["prompts"][label]).group(1)

    def test_f1_check_fixes_name_the_worker_report(self):
        w = os.path.join(self.scratch, "reports", "x.md")
        out = self.run_cycle(self.args([self.unit(item="the-item")]))
        self.assertEqual(self.fixes_of(out), w)                                        # case 1
        out = self.run_cycle(self.args([self.unit(item="the-item")]), **{"stage:review": INSIDE})
        self.assertEqual(self.fixes_of(out), f"{w} and {self.scratch}/reports/fix-x.md")   # case 2
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}})
        self.assertEqual(self.fixes_of(out), f"{w} and {self.scratch}/reports/fixgate-x-1.md")   # case 3
        out = self.run_cycle(self.args([self.unit(kind="fix", fix="f", fixes="F.md", findings="r.json")]))
        self.assertEqual(self.fixes_of(out), "F.md")                                   # case 4
        out = self.run_cycle(self.args([self.unit(kind="recheck", findings="r.json")]))
        self.assertEqual(self.fixes_of(out), "none")                                   # case 5
        out = self.run_cycle(self.args([self.unit(kind="built", built="b")]))
        self.assertEqual(self.fixes_of(out), "none")                                   # built: no worker report

    def test_f2_project_gate_prompt_waits_on_a_live_gate_instead_of_starting_another(self):
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False))
        prompt = out["prompts"]["gate 1: x"]
        self.assertIn("gate-x-1.log.pid", prompt)
        self.assertIn("do not start another", prompt)
        relay = self.run_cycle(self.args([self.unit()]))["prompts"]["gate 1: x"]
        self.assertNotIn(".pid", relay)                                                # relay mode unchanged

    def test_f3_fix_run_writes_no_name_the_change_run_wrote(self):
        gates = {"stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}}
        change = self.run_cycle(self.args([self.unit()]), **gates)
        fix = self.run_cycle(self.args([self.unit(kind="fix", fix="f", fixes="F.md", findings="r.json")]), **gates)
        names = lambda o: set(re.findall(r"(?:fixgate|gate|check)-[A-Za-z0-9.-]+?\.(?:md|log|json)", " ".join(o["prompts"].values())))
        self.assertTrue(names(change) and names(fix))
        self.assertEqual(names(change) & names(fix), set())
        self.assertIn("fixgate-x-1.md", names(change))                                 # change names as today
        self.assertIn("gate-x-1.log", names(change))
        self.assertIn(f"fixgate-fix-x-1.md", names(fix))


if __name__ == "__main__":
    unittest.main()
