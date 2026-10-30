"""The change-cycle workflow script (plugins/delegate/workflows/cycle.js), run against a fake Workflow runtime
(plugins/delegate/tests/fake-workflow.js, on Bun) with scripted agent answers: no model, no paid run.
Expected labels and stops are worked out by hand from the design (stage order of each kind), not printed from the script."""
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
from relay_testbase import ROOT, load_hook  # noqa: E402

SCRIPT = os.path.join(ROOT, "plugins", "delegate", "workflows", "cycle.js")
FAKE = os.path.join(ROOT, "plugins", "delegate", "tests", "fake-workflow.js")
def _stage_label():
    return load_hook("ledger_hook", os.path.join(ROOT, "plugins", "observe", "hooks", "ledger.py")).STAGE_LABEL


LABEL = _stage_label()   # one grammar: the ledger's
STOPS = {"build", "gate", "fix red gate", "review", "fix", "check", "check item", "close queue item", "check show", "owner", "crash"}

DONE = {"status": "DONE", "summary": "ok"}
GREEN = {
    "stage:build": DONE, "stage:fix": DONE, "stage:fix red gate": DONE, "stage:close queue item": DONE, "stage:check show": DONE,
    "stage:other": DONE, "stage:design": DONE, "stage:design review": DONE, "stage:design revise": DONE,
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
        done = subprocess.run(["bun", FAKE, "run", SCRIPT, path], capture_output=True, text=True, timeout=600)
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
        self.assertEqual(out["labels"], ["build: the-item", "gate 1: the-item", "review: the-item", "check: the-item", "close queue item: the-item", "check show: the-item"])
        types = [e["agentType"] for e in out["events"] if e["event"] == "start"]
        self.assertEqual(types.count("delegate:checker"), 1)
        self.assertTrue(out["result"]["changes"][0]["ready"])
        self.assertIn("relay queue done the-item -C", out["prompts"]["close queue item: the-item"])
        self.assertIn("--test tests/a.py::A::b", out["prompts"]["close queue item: the-item"])

    def test_close_prompt_says_closing_is_the_cycles_rule_not_the_agents_call(self):
        """A run started in the turn of an owner question: the close runner must be told closing is the cycle's rule
        (the prompt carries it), so it cannot refuse on principle. Disabled (rule sentence removed): fails."""
        out = self.run_cycle(self.args([self.unit(item="the-item")]), **GREEN)
        p = out["prompts"]["close queue item: the-item"]
        self.assertIn("is the cycle's rule", p)
        self.assertIn("whatever message started this run", p)

    def test_gate_and_show_runners_carry_the_run_rule(self):
        """Every single-command runner is told the run's steps are the cycle's rules, whatever message started the run.
        Disabled (RUN_RULE removed): fails."""
        out = self.run_cycle(self.args([self.unit(item="the-item")]), **GREEN)
        for label in ("gate 1: the-item", "check show: the-item"):
            self.assertIn("steps of this run are the cycle's rules", out["prompts"][label])

    def test_no_item_no_close_and_project_mode_has_no_queue_or_show(self):
        """Without an item: no close stage. Project mode (relay false): neither close nor check show."""
        out = self.run_cycle(self.args([self.unit()]))
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "review: x", "check: x", "check show: x"])
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False))
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "review: x", "check: x"])

    def test_every_quiet_check_starts_with_the_precheck(self):
        """In relay mode the worker, the fixers and the checker all get `relay precheck -C <wt> && <check>`; project mode keeps
        the unit's check as it is. Disabled rule (quiet() returning it.check): the strings are missing from the prompts."""
        want = "relay precheck -C %s && (pytest -q)" % self.wt
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}, "stage:review": INSIDE})
        for label in ("build: x", "fix red gate 1: x", "fix: x", "check: x"):
            self.assertIn(want, out["prompts"][label], label)
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False))
        self.assertNotIn("precheck", out["prompts"]["check: x"])
        self.assertIn("pytest -q", out["prompts"]["check: x"])

    def test_every_quiet_check_says_to_run_detached(self):
        """The precheck may run past the 4-minute foreground limit: worker, fixers and checker are told to run it detached.
        Project mode (no precheck) gets no such note. Disabled note (quietNote() returning ''): the phrase is missing."""
        note = "run this check detached with a log"
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}, "stage:review": INSIDE})
        for label in ("build: x", "fix red gate 1: x", "fix: x", "check: x"):
            self.assertIn(note, out["prompts"][label], label)
        unit = self.unit(kind="fix", fix="Fix it.", fixes="f.md", findings="r.json", item="x")
        self.assertIn(note, self.run_cycle(self.args([unit]))["prompts"]["fix: x"])
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False))
        self.assertNotIn(note, out["prompts"]["check: x"])

    def test_a_fix_unit_fixer_gets_the_quiet_check_and_a_compound_check_is_grouped(self):
        """F1: the fix text alone left the precheck out of a fix-kind unit. F7: `a; b` must sit in a group so a red precheck's
        exit code is the command's. Project mode: no precheck, the front's fix text stays."""
        unit = self.unit(kind="fix", fix="Fix it.", fixes="f.md", findings="r.json", item="x", check="pytest a; pytest b")
        out = self.run_cycle(self.args([unit]))
        want = "relay precheck -C %s && (pytest a; pytest b)" % self.wt
        self.assertIn(want, out["prompts"]["fix: x"])
        self.assertIn(want, out["prompts"]["check: x"])
        out = self.run_cycle(self.args([dict(unit, item=None, branch=None)], relay=False))
        self.assertNotIn("precheck", out["prompts"]["fix: x"])
        self.assertIn("Fix it.", out["prompts"]["fix: x"])

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

    def test_t10_a_gate_stopped_at_its_limit_is_run_again_with_no_fixer(self):
        stopped = {"ok": False, "gate_log": "l", "first_fail": "gate: stopped at the 30-minute limit, step library tests was running"}
        # gate_reruns defaults to 1: stop, gate 2 green, no fixer anywhere
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": {"$seq": [stopped, GREEN["stage:gate"]]}})
        self.assertEqual(out["labels"][:4], ["build: x", "gate 1: x", "gate 2: x", "review: x"])
        self.assertFalse([lb for lb in out["labels"] if lb.startswith("fix red gate")])
        # stopped twice: the unit ends at gate with the line, still no fixer
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": stopped})
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "gate 2: x"])
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "gate")
        self.assertEqual(out["result"]["changes"][0]["detail"], stopped["first_fail"])
        # gate_reruns 0: the first stop ends the unit
        out = self.run_cycle(self.args([self.unit()], settings={"gate_reruns": 0}), **{"stage:gate": stopped})
        self.assertEqual(out["labels"], ["build: x", "gate 1: x"])
        # gate_reruns 3 is out of bounds (0 to 2)
        out = self.run_cycle(self.args([self.unit()], settings={"gate_reruns": 3}))
        self.assertIn("gate_reruns", out["result"]["refused"])

    def test_unknown_top_level_arg_is_refused_before_any_agent(self):
        """A setting at the top level (gate_fixes beside base) is refused in one line that says it goes under settings; any
        other unknown key is named. No agent starts in either case. Known keys and settings (cases above) run as before.
        Disabled check: the run goes on and the labels list is not empty."""
        out = self.run_cycle(self.args([self.unit()], gate_fixes=2))
        self.assertEqual(out["labels"], [])
        self.assertIn("gate_fixes goes under settings", out["result"]["refused"])
        self.assertNotIn("\n", out["result"]["refused"])
        out = self.run_cycle(self.args([self.unit()], bogus=1))
        self.assertEqual(out["labels"], [])
        self.assertIn("bogus", out["result"]["refused"])
        self.assertNotIn("\n", out["result"]["refused"])

    # 3
    def test_unknown_setting_and_unit_field_are_refused_before_any_agent(self):
        """A misspelt setting (gate_fix) and a misspelt unit field (itme) are refused naming the key; no agent starts.
        Pass cases: gate_fixes 2 and a unit with item run; gate_reruns 3 is still the bounds refusal.
        Disabled check: the run goes on and the labels list is not empty."""
        out = self.run_cycle(self.args([self.unit()], settings={"gate_fix": 2}))
        self.assertEqual(out["labels"], [])
        self.assertIn("gate_fix", out["result"]["refused"])
        self.assertIn("gate_fixes", out["result"]["refused"])  # the known settings are listed
        out = self.run_cycle(self.args([self.unit(itme="some-slug")]))
        self.assertEqual(out["labels"], [])
        self.assertIn("unit x has an unknown field itme", out["result"]["refused"])
        out = self.run_cycle(self.args([self.unit(item="some-slug")], settings={"gate_fixes": 2}))
        self.assertNotIn("refused", out["result"] or {})
        self.assertNotEqual(out["labels"], [])
        out = self.run_cycle(self.args([self.unit()], settings={"gate_reruns": 3}))
        self.assertIn("setting gate_reruns must be a whole number from 0 to 2", out["result"]["refused"])

    def test_design_finding_stops_at_owner_and_open_check_stops_at_check(self):
        review = dict(GREEN["stage:review"], design_or_question=True, inside=1, other_inside=0, main_point="design is wrong")
        out = self.run_cycle(self.args([self.unit()]), **{"stage:review": review})
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "owner")
        self.assertFalse([l for l in out["labels"] if l.startswith("fix")])
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:check": dict(GREEN["stage:check"], open=1)})
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "check")
        self.assertNotIn("close queue item: x", out["labels"])

    def test_a_question_does_not_hold_the_other_findings(self):
        """30 Oct failing case: F1 HIGH inside + F2 question. Hand count: other_inside is 1 (F1), so the fixer runs, its prompt
        says the question/Design finding is left alone, then gate 2, then the check, then the unit stops at owner with the
        item not closed. Disabled fix (stop before fixing): labels end at review, no fix or gate 2."""
        review = dict(GREEN["stage:review"], design_or_question=True, inside=2, other_inside=1, main_point="F2 asks the owner")
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:review": review, "stage:check": dict(GREEN["stage:check"], open=1)})
        self.assertEqual(out["labels"], ["build: i", "gate 1: i", "review: i", "fix: i", "gate 2: i", "check: i"])
        change = out["result"]["changes"][0]
        self.assertEqual(change["stopped_at"], "owner")
        self.assertEqual(change["open"], 1)
        self.assertIn("waits for the owner", out["prompts"]["fix: i"])
        self.assertNotIn("close queue item: i", out["labels"])

    def test_f1_a_review_without_other_inside_still_fixes_before_the_owner(self):
        """F1: question flagged, other_inside absent, inside 3. By design the fixer falls back to inside (3 > 0): fix, gate 2,
        check, then owner. Disabled fix (|| 0): labels end at review."""
        review = {k: v for k, v in GREEN["stage:review"].items()}
        review.update(design_or_question=True, inside=3, main_point="q")
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:review": review, "stage:check": dict(GREEN["stage:check"], open=1)})
        self.assertEqual(out["labels"], ["build: i", "gate 1: i", "review: i", "fix: i", "gate 2: i", "check: i"])
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "owner")

    def test_f2_the_fix_prompt_names_the_rule_for_every_waiting_finding(self):
        """F2: two waiting findings (question, Design): the prompt covers every finding of kind question or Design, not 'One
        finding'. No question: no waiting sentence."""
        review = dict(GREEN["stage:review"], design_or_question=True, inside=3, other_inside=1, main_point="q")
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:review": review, "stage:check": dict(GREEN["stage:check"], open=1)})
        prompt = out["prompts"]["fix: i"]
        self.assertIn("Every finding of kind question or Design", prompt)
        self.assertNotIn("One finding", prompt)
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:review": INSIDE})
        self.assertNotIn("kind question or Design", out["prompts"]["fix: i"])

    def test_f3_a_fix_unit_after_a_waits_stop_runs_fix_gate_check_and_closes_the_item(self):
        """F3: the unit the skill names for after the owner's answer: kind fix, findings = review JSON, fixes = two reports."""
        unit = self.unit(kind="fix", fix="Owner says keep it.", fixes="f1.md f2.md", findings="r.json", item="i")
        out = self.run_cycle(self.args([unit]))
        self.assertEqual(out["labels"], ["fix: i", "gate 1: i", "check: i", "close queue item: i", "check show: i"])
        self.assertTrue(out["result"]["changes"][0]["ready"])
        self.assertIn("f1.md", out["prompts"]["check: i"])
        self.assertIn("f2.md", out["prompts"]["check: i"])

    def test_f4_a_not_met_fix_on_the_waits_path_is_not_hidden(self):
        """F4: waits path, check open 2 with F1 NOT MET: the result carries the check summary and fail_without_fix; the check
        prompt no longer says to report the question as open."""
        review = dict(GREEN["stage:review"], design_or_question=True, inside=2, other_inside=1, main_point="q")
        ck = dict(GREEN["stage:check"], open=2, summary="F1 NOT MET", fail_without_fix="no")
        out = self.run_cycle(self.args([self.unit(item="i")]), **{"stage:review": review, "stage:check": ck})
        change = out["result"]["changes"][0]
        self.assertEqual(change["check"], "F1 NOT MET")
        self.assertEqual(change["fail_without_fix"], "no")
        self.assertEqual(change["gateLog"], "gate.log")
        self.assertNotIn("report it as open", out["prompts"]["check: i"])

    # 4
    def test_a_dead_agent_is_retried_once_under_the_same_label(self):
        throw = {"$throw": "subagent completed without calling StructuredOutput"}
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": {"$seq": [throw, GREEN["stage:gate"]]}})
        self.assertEqual(out["labels"].count("gate 1: x"), 2)
        self.assertTrue(out["result"]["changes"][0]["ready"])
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": throw, "gate 2: x": throw})
        self.assertEqual(out["labels"].count("gate 1: x"), 2)
        change = out["result"]["changes"][0]
        self.assertEqual(change["stopped_at"], "gate")                                 # the recovery gate died too: stop
        self.assertIn("StructuredOutput", change["detail"])
        out = self.run_cycle(self.args([self.unit()], settings={"retry_dead": 0}), **{"gate 1: x": throw})
        self.assertEqual(out["labels"].count("gate 1: x"), 1)

    def test_each_thrown_attempt_leaves_a_dead_note_before_the_retry_and_a_clean_run_leaves_none(self):
        # The script has no file access, so a runner agent (label "other: dead-...") writes the note. One throw -> one note,
        # attempt number 1, started after the dead attempt and before the retry (labels order: gate, note, gate).
        throw = {"$throw": "subagent completed without calling StructuredOutput"}
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": {"$seq": [throw, GREEN["stage:gate"]]}})
        self.assertEqual(out["labels"][1:4], ["gate 1: x", "other: x", "gate 1: x"])   # F1: the note joins the dead agent's unit
        note = out["prompts"]["other: x"]
        self.assertIn(os.path.join(self.scratch, "reports", "dead-gate-1-x-1.txt"), note)
        self.assertIn("subagent completed without calling StructuredOutput", note)
        self.assertIn("gate 1: x", note)
        self.assertIn("append", note)                                                 # F2: a second run never replaces an earlier note
        self.assertIn("date", note)                                                   # the time comes from the runner's clock
        self.assertTrue(out["result"]["changes"][0]["ready"])
        # two throws of the same agent: two notes, numbered 1 and 2
        out = self.run_cycle(self.args([self.unit()], settings={"retry_dead": 2}), **{"gate 1: x": {"$seq": [throw, throw, GREEN["stage:gate"]]}})
        self.assertEqual([l for l in out["labels"] if l.startswith("other:")], ["other: x", "other: x"])
        self.assertIn("dead-gate-1-x-2.txt", out["prompts"]["other: x"])
        # no throw, no note
        out = self.run_cycle(self.args([self.unit()]))
        self.assertEqual([l for l in out["labels"] if l.startswith("other:")], [])

    def test_a_note_agent_that_dies_too_never_stops_the_unit(self):
        # F3: the note's own death is swallowed; the stop detail is the dead agent's error, not the note's.
        throw = {"$throw": "subagent completed without calling StructuredOutput"}
        note_throw = {"$throw": "note agent died"}
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": {"$seq": [throw, GREEN["stage:gate"]]}, "other: x": note_throw})
        self.assertEqual(out["labels"][1:4], ["gate 1: x", "other: x", "gate 1: x"])
        self.assertTrue(out["result"]["changes"][0]["ready"])
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": throw, "gate 2: x": throw, "other: x": note_throw})
        change = out["result"]["changes"][0]
        self.assertEqual(change["stopped_at"], "gate")
        self.assertIn("StructuredOutput", change["detail"])
        self.assertNotIn("note agent died", change["detail"])

    def test_a_gate_agent_with_no_result_gets_one_recovery_gate_that_reads_the_head_log_first(self):
        """Failing case 29 Oct (wf_21bb938f-13f): both attempts of gate 1 died with no result and the cycle stopped at 'gate'.
        By the design: the unit goes on with one more gate agent (label gate 2), whose prompt says to read the head's gate log
        under .relay/checks/ first, to wait on a gate already running, and to run the gate only when neither exists.
        Disabled rule (stop on r.dead): labels end at gate 1 and the unit is not ready."""
        throw = {"$throw": "subagent completed without calling StructuredOutput"}
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": throw})
        self.assertEqual([l for l in out["labels"] if not l.startswith("other:")][:4], ["build: x", "gate 1: x", "gate 1: x", "gate 2: x"])
        self.assertTrue(out["result"]["changes"][0]["ready"])
        prompt = out["prompts"]["gate 2: x"]
        self.assertIn("%s/.relay/checks/<head>" % self.wt, prompt)
        self.assertIn(".gate.log", prompt)
        self.assertIn("already running", prompt)
        self.assertLess(prompt.index(".gate.log"), prompt.index("relay gate -C"))     # read the log before any gate is started
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False), **{"gate 1: x": throw})
        self.assertIn("gate-x-2.log", out["prompts"]["gate 2: x"])                     # project mode: its own log, same recovery

    def test_project_mode_recovery_reads_the_dead_attempts_log_and_pid_before_starting_a_gate(self):
        """F1: gate 1 (log gate-x-1.log, pid gate-x-1.log.pid) died; the gate 2 prompt must name those two to wait on / read
        before the instruction that starts the gate (which writes gate-x-2.log). Disabled fix: gate-x-1.log.pid is absent."""
        throw = {"$throw": "subagent completed without calling StructuredOutput"}
        out = self.run_cycle(self.args([self.unit(branch=None)], relay=False), **{"gate 1: x": throw})
        prompt = out["prompts"]["gate 2: x"]
        self.assertIn("gate-x-1.log.pid", prompt)
        self.assertLess(prompt.index("gate-x-1.log.pid"), prompt.index("gate-x-2.log"))
        self.assertTrue(out["result"]["changes"][0]["ready"])                          # pass case 2

    def test_relay_recovery_finds_the_log_one_commit_back_after_a_committed_gate(self):
        """F2: HEAD is the 'relay: gate of <sha>' commit, the log is named by <sha>; the prompt says so (before relay gate)."""
        throw = {"$throw": "died"}
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": throw})
        prompt = out["prompts"]["gate 2: x"]
        self.assertIn("relay: gate of <sha>", prompt)
        self.assertLess(prompt.index("relay: gate of <sha>"), prompt.index("relay gate -C"))

    def test_a_recovery_gate_is_one_only_per_gate_and_a_skip_is_not_recovered(self):
        throw = {"$throw": "died"}
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": throw, "gate 2: x": throw})
        self.assertEqual(out["labels"].count("gate 3: x"), 0)                          # one recovery, then stop

    def test_a_skipped_agent_stops_the_unit_at_once(self):
        out = self.run_cycle(self.args([self.unit()]), **{"gate 1: x": None})
        self.assertEqual(out["labels"].count("gate 1: x"), 1)
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "gate")

    # 5
    def test_fix_and_recheck_kinds(self):
        fix = self.unit(kind="fix", fix="Fix it.", fixes="fix.md", findings="review.json", item="x")
        out = self.run_cycle(self.args([fix]))
        self.assertEqual(out["labels"], ["fix: x", "gate 1: x", "check: x", "close queue item: x", "check show: x"])
        self.assertTrue(out["prompts"]["fix: x"].startswith("Fix it."))  # then the quiet check (F1)

    def test_recheck_with_findings_is_one_plain_check_in_project_mode(self):
        """Project mode (no .relay/, so no `relay land`) keeps the recheck kind: take, gate, one check."""
        out = self.run_cycle(self.args([self.unit(kind="recheck", findings="relay check findings -C t", branch=None)], relay=False))
        self.assertEqual(out["labels"], ["gate 1: x", "check: x"])

    def test_recheck_checker_prompt_names_the_fixes(self):
        """A recheck given `fixes` passes that report to the checker, not `Fixes: none` (the live 28 Oct case: fixed findings
        came back NOT MET). Disabled change (recheckUnit passing 'none'): the prompt says Fixes: `none`."""
        unit = self.unit(kind="recheck", findings="review.json", fixes="fix-x.md", branch=None)
        out = self.run_cycle(self.args([unit], relay=False))
        self.assertIn("Fixes: `fix-x.md`.", out["prompts"]["check: x"])
        self.assertNotIn("Fixes: `none`", out["prompts"]["check: x"])

    def test_recheck_without_fixes_names_the_scratch_check_records(self):
        """No `fixes`, with or without a branch: the checker is pointed at the check records in <scratch>/reports (readable with
        relay check show <file>), never `Fixes: none` and never `relay check show <branch>` (it prints no verdicts)."""
        for branch in ("wt/x", None):
            unit = self.unit(kind="recheck", findings="review.json", branch=branch)
            out = self.run_cycle(self.args([unit], relay=False))
            prompt = out["prompts"]["check: x"]
            self.assertNotIn("Fixes: `none`", prompt)
            self.assertNotIn("relay check show wt/x", prompt)
            self.assertIn("/reports/check-*.json whose worktree is %s (read each with relay check show <file>)" % self.wt, prompt)

    def test_cycle_recheck_refused_in_relay_mode(self):
        """Design relay-land 4.5: relay land takes the base and gates, so a recheck is refused with the exact shape of the
        fix unit a take conflict becomes (kind fix, findings = the branch's last review JSON, no item). Disabled rule: the
        old train path would start a gate agent."""
        out = self.run_cycle(self.args([self.unit(kind="recheck", findings="f")]))
        self.assertEqual(out["labels"], [])
        refused = out["result"]["refused"]
        for words in ("relay land", "kind fix", "findings = the branch's last review JSON", "no item"):
            self.assertIn(words, refused)
        self.assertNotIn("\n", refused)

    def test_cycle_never_prompts_land(self):
        """Only the front starts `relay land`: no prompt any kind of unit sends an agent names it."""
        units = [self.unit(item="i"), self.unit(name="b", kind="built", built="by hand"),
                 self.unit(name="f", kind="fix", fix="Fix it.", fixes="f.md", findings="r.json", item="j")]
        out = self.run_cycle(self.args(units, designs=[{"name": "d", "brief": "b.md", "out": "d.md"}]), **{"stage:review": INSIDE})
        self.assertGreater(len(out["prompts"]), 10)
        for label, prompt in out["prompts"].items():
            self.assertNotIn("relay land", prompt, label)

    def test_f6_labels_of_a_unit_with_an_item_carry_the_full_item_id_and_one_without_keeps_its_name(self):
        """Unit named x for item `x-and-a-very-long-queue-item-id`: every label ends with the item id (so the metrics match it exactly);
        a unit with no item keeps `<stage>: x`."""
        item = "x-and-a-very-long-queue-item-id"
        out = self.run_cycle(self.args([self.unit(item=item)]))
        self.assertEqual(out["labels"], [f"{s}: {item}" for s in ("build", "gate 1", "review", "check", "close queue item", "check show")])
        out = self.run_cycle(self.args([self.unit()]))
        self.assertEqual(out["labels"], ["build: x", "gate 1: x", "review: x", "check: x", "check show: x"])

    def test_recheck_gate_takes_the_base_first_and_a_conflict_stops_without_a_fix_round(self):
        """The queue item's pass cases: a recheck gate prompt starts with a merge of the base (relay and project mode); other
        kinds do not; a reported take conflict stops at gate with no fixer. Disabled rule (no takePrompt): no merge text."""
        merge = "git -C %s merge --no-edit master" % self.wt
        unit = self.unit(kind="recheck", findings="f", branch=None)
        out = self.run_cycle(self.args([unit], relay=False))
        self.assertTrue(out["prompts"]["gate 1: x"].startswith("First take the base"))
        self.assertIn(merge, out["prompts"]["gate 1: x"])
        out = self.run_cycle(self.args([self.unit(item="x")]))
        self.assertNotIn("merge --no-edit", out["prompts"]["gate 1: x"])
        conflict = {"ok": False, "gate_log": "", "first_fail": "take conflict: a.py"}
        out = self.run_cycle(self.args([self.unit(kind="recheck", findings="f", branch=None)], relay=False), **{"stage:gate": conflict})
        self.assertEqual(out["labels"], ["gate 1: x"])
        self.assertEqual(out["result"]["changes"][0]["stopped_at"], "gate")

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
            (self.args([self.unit(kind="recheck", findings="f", branch=None)], relay=False), {}),
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
        done = subprocess.run(["bun", FAKE, "meta", SCRIPT], capture_output=True, text=True, timeout=600)
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
        done = subprocess.run(["bun", FAKE, "meta", bad], capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 3)

    # 9
    def relay_commands(self, prompts):
        found = []
        for text in prompts:
            for span in re.findall(r"`(relay [^`]+)`", text):
                found.append(span.split(" && ")[0])   # `relay precheck -C <wt> && <check>`: the relay command is the first part
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
                                  capture_output=True, text=True, timeout=600)
            text = done.stdout + done.stderr
            if done.returncode == 2 or "unknown option" in text or "unknown command" in text or "usage" in text.lower():
                bad.append(cmd)
        return bad

    def test_every_relay_command_the_prompts_name_still_parses(self):
        """Rendered from the script's own defaults (no gate_args). The two removed forms are the regression cases."""
        units = [self.unit(item="the-item"), self.unit(name="y", kind="fix", fix="f", fixes="f.md", findings="r.json", item="j")]
        out = self.run_cycle(self.args(units, designs=[{"name": "d", "brief": "b.md", "out": os.path.join(self.tmp, "d.md")}]),
                             **{"stage:review": INSIDE})
        commands = self.relay_commands(out["prompts"].values())
        self.assertTrue(any(c.startswith("relay gate -C") and c.endswith("-- --quick") for c in commands))
        self.assertTrue(any(c.startswith("relay queue done") for c in commands))
        self.assertTrue(any(c.startswith("relay check show") for c in commands))
        self.assertEqual(self.bad_commands(commands), [])
        removed = [f"relay queue done s -C {self.wt} --check x.json", f"relay gate -C {self.wt} --quick"]
        self.assertEqual(self.bad_commands(removed), removed)

    def gate_command(self, **settings):
        out = self.run_cycle(self.args([self.unit(item="the-item")], settings=settings))
        found = [c for c in self.relay_commands(out["prompts"].values()) if c.startswith("relay gate -C")]
        self.assertEqual(len(found), 1, found)
        return found[0].replace(self.wt, "<wt>")

    def test_f3_gate_args_choose_the_quick_or_the_full_gate(self):
        self.assertEqual(self.gate_command(), "relay gate -C <wt> -- --quick")
        self.assertEqual(self.gate_command(gate_args="--paid"), "relay gate -C <wt> --paid")
        self.assertEqual(self.gate_command(gate_args=""), "relay gate -C <wt>")

    # 10
    def test_check_and_design_review_prompts_keep_the_report_label_the_hook_reads(self):
        mod = load_hook("check_mark", os.path.join(ROOT, "plugins", "relay", "hooks", "check-mark.py"))
        out = self.run_cycle(self.args([self.unit()], designs=[{"name": "d", "brief": "b.md", "out": "d.md"}]))
        for label in ("check: x", "design review: d"):
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
                      self.unit(name="w", kind="built", built="b")] + ([] if relay else [self.unit(name="z", kind="recheck", findings="f", branch=None)])
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
        out = self.run_cycle(self.args([self.unit(item="x")]))
        self.assertEqual(self.fixes_of(out), w)                                        # case 1
        out = self.run_cycle(self.args([self.unit(item="x")]), **{"stage:review": INSIDE})
        self.assertEqual(self.fixes_of(out), f"{w} and {self.scratch}/reports/fix-x.md")   # case 2
        out = self.run_cycle(self.args([self.unit()]), **{"stage:gate": {"$seq": [RED, GREEN["stage:gate"]]}})
        self.assertEqual(self.fixes_of(out), f"{w} and {self.scratch}/reports/fixgate-x-1.md")   # case 3
        out = self.run_cycle(self.args([self.unit(kind="fix", fix="f", fixes="F.md", findings="r.json")]))
        self.assertEqual(self.fixes_of(out), "F.md")                                   # case 4
        out = self.run_cycle(self.args([self.unit(kind="recheck", findings="r.json", branch=None)], relay=False))
        self.assertIn(f"{self.scratch}/reports/check-*.json", self.fixes_of(out))      # case 5: a recheck names the earlier records, not none
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
        self.assertIn("fixgate-fix-x-1.md", names(fix))


if __name__ == "__main__":
    unittest.main()
