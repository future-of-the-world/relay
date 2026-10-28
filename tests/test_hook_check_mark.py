"""Port of plugins/relay/tests/check-mark.test.sh: the check-mark hook (hooks/check-mark.py) and the guard's .relay/checks
rule (hooks/guard-main.sh): cases K1-K8, K10-K13 and G1-G7, Q1-Q4 of docs/plans/review-gate.md section 12.3, on throwaway
repositories under a temp dir (temp HOME). The reports are recorded by `relay check record review|check --input <file.toml>`
(the agents' only way to write the JSON the hook reads). K9 is the live run (paid): tests/live_k9.sh, never part of the gate."""
import calendar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from typing import List, Optional, Tuple

from hook_helpers import ROOT

CORE = os.path.join(ROOT, "plugins", "relay")
HOOK = os.path.join(CORE, "hooks", "check-mark.py")
GUARD = os.path.join(CORE, "hooks", "guard-main.sh")
RELAY = os.path.join(ROOT, "bin", "relay")
START = "2026-10-22T10:00:00.000Z"  # the agent's first timestamp; a report is new when its mtime is after it
NEW = calendar.timegm((2026, 10, 22, 11, 0, 0))
OLD = calendar.timegm((2026, 10, 22, 9, 0, 0))
MID = calendar.timegm((2026, 10, 22, 9, 30, 0))
HARNESS = "[Workflow harness — user request] run the change for me"


def entry(text: str, ts: str = START) -> str:
    return json.dumps({"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}}, ensure_ascii=False)


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(cls.tmp, "home"))
        cls.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        cls.env.update(HOME=os.path.join(cls.tmp, "home"), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_AUTHOR_NAME="t",
                       GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", TZ="UTC")
        cls.n = 0

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cmd(self, cmd: List[str], cwd: str, stdin: Optional[str] = None, env: Optional[dict] = None) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, encoding="utf-8", env=env or self.env)

    def git(self, cwd: str, *args: str) -> str:
        return self.run_cmd(["git"] + list(args), cwd).stdout.strip()


class Mark(Base):
    # mkrepo: M = main on master (with .relay/ unless norelay); W = worktree on wt/t with one commit; INIT = master's commit (the
    # "reviewed" sha), HEAD0 = W's head (the "checked" sha), GATE = the green gate log committed after it
    def mkrepo(self, norelay: bool = False) -> None:
        type(self).n += 1
        self.M = os.path.join(self.tmp, "r%d" % self.n)
        self.S = os.path.join(self.tmp, "s%d" % self.n)
        os.makedirs(self.M)
        os.makedirs(self.S)
        self.git(self.M, "init", "-q", "-b", "master", ".")
        write(os.path.join(self.M, ".gitignore"), ".ci/\n")
        if not norelay:
            os.makedirs(os.path.join(self.M, ".relay"))
            write(os.path.join(self.M, ".relay", "README.md"), "x\n")
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "init")
        self.git(self.M, "worktree", "add", "-q", ".worktrees/t", "-b", "wt/t")
        self.W = os.path.join(self.M, ".worktrees", "t")
        write(os.path.join(self.W, "a.txt"), "a\n")
        self.git(self.W, "add", "a.txt")
        self.git(self.W, "commit", "-q", "-m", "work")
        self.INIT = self.git(self.M, "rev-parse", "master")
        self.HEAD0 = self.git(self.W, "rev-parse", "HEAD")
        self.GATE = self.HEAD0 + ".gate.log"
        os.makedirs(os.path.join(self.W, ".relay", "checks"), exist_ok=True)
        write(os.path.join(self.W, ".relay", "checks", self.GATE), "head %s\nexit 0\n" % self.HEAD0)
        self.git(self.W, "add", ".relay/checks")
        self.git(self.W, "commit", "-q", "-m", "gate")
        self.review(os.path.join(self.S, "f.json"), "F1", "note")
        self.report(0)

    def review(self, path: str, fid: str, summary: str, kind: str = "inside") -> None:
        write(os.path.join(self.S, "review.toml"), 'report = "%s"\nreviewed = "%s"\nbase = "master"\n[[finding]]\nid = "%s"\npath = "a.txt"\nline = 1\n'
              'severity = "HIGH"\nkind = "%s"\nsummary = "%s"\nfailing_case = "x gives 1, should give 2"\n' % (path, self.INIT, fid, kind, summary))
        done = self.run_cmd([RELAY, "check", "record", "review", "--input", os.path.join(self.S, "review.toml")], self.M)
        self.assertEqual(done.returncode, 0, "setup: review record failed: " + done.stderr)
        os.utime(path, (NEW, NEW))

    def report(self, open_: int, stamp: int = NEW, head: Optional[str] = None, reviews: Optional[List[str]] = None, ids: Tuple[str, ...] = ("F1",)) -> subprocess.CompletedProcess:
        """The checker's data at S/rep.json; open 1 gives F1 the verdict NOT MET, 0 gives every id MET."""
        revs = reviews or [os.path.join(self.S, "f.json")]
        text = 'report = "%s/rep.json"\nhead = "%s"\nworktree = "%s"\ngate = "%s"\nreview = [%s]\n' % (
            self.S, head or self.HEAD0, self.W, self.GATE, ", ".join('"%s"' % r for r in revs))
        for fid in ids:
            text += '[[status]]\nid = "%s"\nverdict = "%s"\n' % (fid, "NOT MET" if open_ == 1 and fid == "F1" else "MET")
        write(os.path.join(self.S, "check.toml"), text)
        done = self.run_cmd([RELAY, "check", "record", "check", "--input", os.path.join(self.S, "check.toml")], self.M)
        if os.path.exists(os.path.join(self.S, "rep.json")):
            os.utime(os.path.join(self.S, "rep.json"), (stamp, stamp))
        return done

    def prompt(self, files: Optional[str] = None) -> None:
        files = files or "`%s/f.json`" % self.S
        write(os.path.join(self.S, "agent.jsonl"), entry("Check: %s. Fixes: `none`. Worktree: `%s`. Check command: `bin/ci --quick`. Gate: `none`. Report: `%s/rep.json`." % (files, self.W, self.S)) + "\n")

    def stop(self, agent_type: str, active: bool = False) -> None:
        event = {"hook_event_name": "SubagentStop", "agent_type": agent_type, "agent_id": "a1", "cwd": self.M,
                 "agent_transcript_path": os.path.join(self.S, "agent.jsonl"), "stop_hook_active": active}
        done = self.run_cmd([sys.executable, "-I", HOOK], self.M, stdin=json.dumps(event))
        self.out, self.rc = done.stdout + done.stderr, done.returncode
        try:
            self.msg = json.loads(self.out).get("systemMessage", "")
        except ValueError:
            self.msg = ""

    def count(self) -> int:
        return int(self.git(self.W, "rev-list", "--count", "HEAD"))

    def stored(self, name: str) -> dict:
        return json.loads(self.git(self.W, "show", "HEAD:.relay/checks/" + name))

    def has_mark(self) -> bool:
        return self.run_cmd(["git", "cat-file", "-e", "HEAD:.relay/checks/%s.json" % self.HEAD0], self.W).returncode == 0

    def test_K1_valid_checker_stop_makes_one_commit_of_two_json_files(self) -> None:
        self.mkrepo()
        self.prompt()
        before = self.count()
        self.stop("delegate:checker")
        self.assertEqual(self.rc, 0)
        self.assertEqual(self.count(), before + 1)
        got = sorted(self.git(self.W, "show", "--name-only", "--format=", "HEAD").split())
        self.assertEqual(got, sorted([".relay/checks/%s.check.json" % self.HEAD0, ".relay/checks/%s.json" % self.HEAD0]))  # no .md
        j = self.stored(self.HEAD0 + ".json")
        self.assertEqual((j["commit"], j["schema"], j["verdict"], j["check"]), (self.HEAD0, 2, {"open": 0, "queued": 0}, self.HEAD0 + ".check.json"))
        self.assertNotIn("review", j)
        self.assertIsInstance(j["time"], str)
        self.assertRegex(j["commit"], "^[0-9a-f]{40}$")
        cj = self.stored(self.HEAD0 + ".check.json")
        self.assertEqual((cj["head"], cj["branch"], cj["item"], cj["gate"], cj["schema"], cj["type"]), (self.HEAD0, "wt/t", None, self.GATE, 2, "check"))
        self.assertNotIn("worktree", cj)
        self.assertNotIn("open", cj)  # no stored counts
        f = cj["findings"]
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["id"], f[0]["source"], f[0]["source_id"], f[0]["since"], f[0]["verdict"], f[0]["kind"]), ("F1", "f.json", "F1", self.INIT, "MET", "inside"))
        self.assertEqual(self.git(self.W, "log", "-1", "--format=%s"), "relay: check of " + self.HEAD0)

    def test_K2_critic_does_nothing_then_checker_marks(self) -> None:
        self.mkrepo()
        self.prompt()
        before = self.count()
        self.stop("delegate:critic")
        self.assertEqual((self.count(), self.out), (before, ""))
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before + 1)

    def test_K3_empty_agent_type(self) -> None:
        self.mkrepo()
        self.prompt()
        before = self.count()
        self.stop("")
        self.assertEqual((self.count(), self.out), (before, ""))

    def test_K4_no_check_data_keeps_the_earlier_mark(self) -> None:
        self.mkrepo()
        self.prompt()
        self.stop("delegate:checker")
        self.assertTrue(self.has_mark())
        before = self.count()
        os.remove(os.path.join(self.S, "rep.json"))
        write(os.path.join(self.S, "rep.md"), "# Check\nF1 MET\n## Verdict\nhead %s\nreviewed %s\nopen 0\nqueued 0\n" % (self.HEAD0, self.INIT))
        os.utime(os.path.join(self.S, "rep.md"), (NEW, NEW))
        self.stop("delegate:checker")
        self.assertEqual(self.rc, 2)  # kept going; the reason names the record command
        self.assertIn("relay check record check --input", self.out)
        self.stop("delegate:checker", active=True)
        self.assertEqual((self.rc, self.count()), (0, before))
        self.assertTrue(self.has_mark())
        self.assertIn("check mark not written for wt/t: no check record written during your run", self.msg)  # the old prose verdict is not read

    def test_K4b_bad_data_makes_no_mark(self) -> None:
        self.mkrepo()
        self.prompt()
        self.report(0)
        write(os.path.join(self.S, "rep.json"), "not json")
        os.utime(os.path.join(self.S, "rep.json"), (NEW, NEW))
        before = self.count()
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before)
        self.assertIn("is not JSON", self.msg)
        self.report(0)
        self.edit_report(gate="x")
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before)
        self.assertIn("gate must be null, a gate log file name", self.msg)

    def edit_report(self, **fields: str) -> None:
        path = os.path.join(self.S, "rep.json")
        with open(path) as handle:
            data = json.load(handle)
        data.update(fields)
        write(path, json.dumps(data))
        os.utime(path, (NEW, NEW))

    def test_K4c_counts_are_derived_never_typed(self) -> None:
        self.mkrepo()
        self.prompt()
        self.report(1)
        self.stop("delegate:checker")
        self.assertEqual(self.stored(self.HEAD0 + ".json")["verdict"]["open"], 1)
        self.mkrepo()
        self.prompt()
        self.report(0)
        self.edit_report(open=0)
        before = self.count()
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before)
        self.assertIn("unknown field open", self.msg)

    def test_K5_report_older_than_the_start(self) -> None:
        self.mkrepo()
        self.prompt()
        self.report(0, OLD)
        before = self.count()
        self.stop("delegate:checker")
        self.assertEqual((self.rc, self.count()), (2, before))
        self.stop("delegate:checker", active=True)
        self.assertEqual((self.rc, self.count()), (0, before))
        self.assertIn("no check record written during your run", self.msg)

    def test_K6_head_not_in_the_history(self) -> None:
        self.mkrepo()
        self.prompt()
        before = self.count()
        rec = self.report(0, NEW, self.HEAD0[:7])
        self.assertIn("is not a commit of this worktree", rec.stdout + rec.stderr)  # the record script refuses an abbreviated head
        self.report(0)
        self.edit_report(head="ab" * 20)
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before)
        self.assertIn("is not a commit of this worktree", self.msg)
        self.report(0)
        self.edit_report(head=self.HEAD0[:7])
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before)
        self.assertIn("head must be a full 40-character sha", self.msg)

    def test_K7_no_relay_dir_does_nothing_and_the_control_marks(self) -> None:
        self.mkrepo(norelay=True)
        self.prompt()
        before = self.count()
        self.stop("delegate:checker")
        self.assertEqual((self.count(), self.out), (before, ""))
        self.mkrepo()
        self.prompt()
        before = self.count()
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before + 1)

    def test_K8_index_locked_for_2s_lands_on_a_retry_and_commits_only_its_files(self) -> None:
        self.mkrepo()
        self.prompt()
        write(os.path.join(self.W, "other.txt"), "o\n")
        self.git(self.W, "add", "other.txt")
        before = self.count()
        lock = self.git(self.W, "rev-parse", "--path-format=absolute", "--git-path", "index.lock")
        open(lock, "w").close()
        timer = threading.Timer(2.0, lambda: os.path.exists(lock) and os.remove(lock))  # the hook waits 1 s between tries
        timer.start()
        self.addCleanup(timer.cancel)
        self.stop("delegate:checker")
        timer.join()
        self.assertEqual(self.count(), before + 1)
        self.assertTrue(self.has_mark())
        self.assertNotIn("other.txt", self.git(self.W, "show", "--name-only", "--format=", "HEAD"))
        self.assertEqual(self.git(self.W, "diff", "--cached", "--name-only"), "other.txt")

    def test_K10_two_reviews_in_one_record(self) -> None:
        self.mkrepo()
        a, b = os.path.join(self.S, "a.json"), os.path.join(self.S, "b.json")
        self.review(a, "F1", "from a")
        self.review(b, "F1", "question from b", "question")
        self.prompt("`%s`, `%s`" % (a, b))
        self.report(0, reviews=[a, b], ids=("F1", "F2"))
        self.stop("delegate:checker")
        got = [[x["id"], x["source"], x["source_id"], x["kind"], x["summary"]] for x in self.stored(self.HEAD0 + ".check.json")["findings"]]
        self.assertEqual(got, [["F1", "a.json", "F1", "inside", "from a"], ["F2", "b.json", "F1", "question", "question from b"]])

    def test_K11_recheck_after_the_review_changed(self) -> None:
        self.mkrepo()
        self.prompt()
        self.report(1)
        self.stop("delegate:checker")
        self.assertEqual(self.stored(self.HEAD0 + ".json")["verdict"]["open"], 1)
        self.review(os.path.join(self.S, "f.json"), "F1", "changed after the owner's word")
        self.report(0)
        self.stop("delegate:checker")
        self.assertEqual(self.stored(self.HEAD0 + ".check.json")["findings"][0]["summary"], "changed after the owner's word")
        self.assertEqual(self.stored(self.HEAD0 + ".json")["verdict"]["open"], 0)

    def test_K12_a_brief_prompt_names_the_missing_record_or_label(self) -> None:
        self.mkrepo()
        before = self.count()
        os.remove(os.path.join(self.S, "rep.json"))
        write(os.path.join(self.S, "agent.jsonl"), entry("Check the fix per the brief. Brief: %s/brief.md. Report: %s/rep.json." % (self.S, self.S)) + "\n")
        self.stop("delegate:checker", active=True)
        self.assertEqual(self.count(), before)
        self.assertIn("no check record written during your run", self.msg)
        self.assertIn("Report: %s/rep.json" % self.S, self.msg)
        write(os.path.join(self.S, "agent.jsonl"), entry("Check the fix per the brief. Brief: %s/brief.md." % self.S) + "\n")
        self.stop("delegate:checker", active=True)
        self.assertIn("no Report: line", self.msg)

    def prepend(self, *lines: str) -> None:
        path = os.path.join(self.S, "agent.jsonl")
        with open(path, encoding="utf-8") as handle:
            rest = handle.read()
        write(path, "".join(line + "\n" for line in lines) + rest)

    def test_K13_workflow_transcripts(self) -> None:
        self.mkrepo()
        self.prompt()
        before = self.count()
        self.prepend(entry(HARNESS))  # the harness's relayed request (no Report: label), then the check prompt
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before + 1)
        self.assertTrue(self.has_mark())

    def test_K13b_c_no_label_in_the_leading_entries(self) -> None:
        self.mkrepo()
        before = self.count()
        write(os.path.join(self.S, "agent.jsonl"), entry(HARNESS) + "\n" + entry("Check the fix per the brief.") + "\n")
        self.stop("delegate:checker", active=True)
        self.assertEqual(self.count(), before)
        self.assertIn("no Report: line", self.msg)
        # K13c: a Report: label after the first assistant entry is not the prompt
        write(os.path.join(self.S, "agent.jsonl"), entry(HARNESS) + "\n" + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "ok"}}) + "\n"
              + entry("Report: %s/rep.json." % self.S) + "\n")
        self.stop("delegate:checker", active=True)
        self.assertEqual(self.count(), before)
        self.assertIn("no Report: line", self.msg)

    def test_K13d_start_time_is_the_prompts_not_the_harness_lines(self) -> None:
        self.mkrepo()
        self.prompt()
        before = self.count()
        self.report(0, MID)  # harness 09:00, prompt 10:00 (START), report 09:30: older than the prompt
        self.prepend(entry(HARNESS, "2026-10-22T09:00:00.000Z"))
        self.stop("delegate:checker", active=True)
        self.assertEqual(self.count(), before)
        self.assertIn("no check record written during your run", self.msg)

    def test_K13e_the_last_report_label_wins(self) -> None:
        self.mkrepo()
        self.prompt()
        before = self.count()
        self.prepend(entry("[Workflow harness — user request] look at Report: %s/old-check.json" % self.S))
        self.stop("delegate:checker")
        self.assertEqual(self.count(), before + 1)
        self.assertTrue(self.has_mark())


class Guard(Base):
    """The real guard-main.sh with CLAUDE_PROJECT_DIR = the worktree (as in a worktree session)."""
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.GM = os.path.join(cls.tmp, "gm")
        os.makedirs(os.path.join(cls.GM, ".relay"))
        cls.git0 = lambda *a, cwd=cls.GM: subprocess.run(["git"] + list(a), cwd=cwd, env=cls.env, check=True, capture_output=True)
        cls.git0("init", "-q", "-b", "master", ".")
        write(os.path.join(cls.GM, ".relay", "README.md"), "x\n")
        cls.git0("add", "-A")
        cls.git0("commit", "-q", "-m", "init")
        cls.git0("worktree", "add", "-q", ".worktrees/t", "-b", "wt/t")
        cls.GW = os.path.join(cls.GM, ".worktrees", "t")
        cls.scratch = os.path.join(cls.tmp, "scratch")
        cls.fx = os.path.join(cls.tmp, "fx")
        os.makedirs(cls.scratch)
        os.makedirs(cls.fx)
        # a repository without .relay/
        cls.NM = os.path.join(cls.tmp, "norelay")
        os.makedirs(cls.NM)
        cls.git0("init", "-q", "-b", "master", ".", cwd=cls.NM)
        write(os.path.join(cls.NM, "x"), "x\n")
        cls.git0("add", "-A", cwd=cls.NM)
        cls.git0("commit", "-q", "-m", "init", cwd=cls.NM)
        cls.git0("worktree", "add", "-q", ".worktrees/t", "-b", "wt/t", cwd=cls.NM)
        cls.NW = os.path.join(cls.NM, ".worktrees", "t")

    def g(self, expect: str, tool: str, cwd: str, key: str, val: str, anchor: Optional[str] = None) -> str:
        event = {"tool_name": tool, "cwd": cwd, "tool_input": {key: val}}
        env = dict(self.env, CLAUDE_PROJECT_DIR=anchor or self.GW)
        done = self.run_cmd([GUARD], cwd, stdin=json.dumps(event), env=env)
        self.assertEqual("block" if done.returncode == 2 else "allow", expect, "%s %s: %s" % (tool, val, done.stderr))
        return done.stderr

    def test_G1_write_tools_on_checks_are_blocked(self) -> None:
        err = self.g("block", "Write", self.GW, "file_path", self.GW + "/.relay/checks/x.json")
        self.assertIn("files in .relay/checks are written only by relay", err)
        self.g("block", "Edit", self.GM, "file_path", self.GM + "/.relay/checks/x.json")
        self.g("block", "MultiEdit", self.GW, "file_path", ".relay/checks/x.json")

    def test_G2_G3_shell_writes_are_blocked(self) -> None:
        for cmd, cwd in (("printf x > .relay/checks/a.json", self.GW), ("cp a.txt .relay/checks/", self.GW), ("git add .relay/checks", self.GW),
                         ("git checkout other -- .relay/checks", self.GW), ("git -C %s rm -r .relay/checks" % self.GW, self.scratch),
                         ("python3 -c \"open('.relay/checks/a.json','w').write('x')\"", self.GW),
                         ("node -e \"require('fs').writeFileSync('.relay/checks/a.json','x')\"", self.GW),
                         ("python3 -c \"import shutil; shutil.rmtree('.relay/checks')\"", self.GW)):
            self.g("block", "Bash", cwd, "command", cmd)

    def test_G4_G5_G6_reads_and_other_files_are_allowed(self) -> None:
        self.g("allow", "Write", self.GW, "file_path", self.scratch + "/check.md")
        self.g("allow", "Write", self.GW, "file_path", self.GW + "/.ci/check.md")
        for cmd in ("relay check show wt/x", "relay gate", "git log --oneline .relay/checks", 'grep -rn ".relay/checks" plugins/relay',
                    "cat .relay/checks/x.review.json", "jq .verdict .relay/checks/X.json",
                    "python3 -c \"import json;print(json.load(open('.relay/checks/X.json'))['verdict'])\"",
                    "python3 -c \"import json; print(json.load(open('.relay/checks/a.json'))['verdict']['open'] > 0)\"",
                    "python3 -c \"import sys; sys.stdout.write(open('.relay/checks/a.json').read())\"",
                    "cat >> %s/r.md <<'EOF'\nthe findings live in .relay/checks/x.review.md\nEOF" % self.scratch):
            self.g("allow", "Bash", self.GW, "command", cmd)

    def test_G7_outside_any_repository_with_relay_allowed_inside_refused(self) -> None:
        self.g("allow", "Bash", self.GW, "command", "mkdir -p %s/.relay/checks && printf '{}' > %s/.relay/checks/a.json" % (self.fx, self.fx))
        self.g("allow", "Write", self.GW, "file_path", self.fx + "/.relay/checks/a.json")
        self.g("block", "Bash", self.GW, "command", "printf '{}' > .worktrees/t/.relay/checks/a.json", self.GM)
        self.g("allow", "Bash", self.NW, "command", "printf '{}' > .relay/checks/a.json", self.NW)
        self.g("allow", "Write", self.NW, "file_path", self.NW + "/.relay/checks/a.json", self.NW)

    def test_Q1_Q4_queue_items_are_written_only_by_relay_queue(self) -> None:
        err = self.g("block", "Write", self.GW, "file_path", self.GW + "/.relay/queue/x.json")
        self.assertIn("relay queue edit", err)
        self.g("block", "Bash", self.GW, "command", "cat > .relay/queue/x.json <<'EOF'\n{}\nEOF")
        self.g("block", "Bash", self.GW, "command", "cp a.txt .relay/queue/x.json")
        self.g("block", "Bash", self.GW, "command", "python3 -c \"open('.relay/queue/x.json','w').write('x')\"")
        self.g("allow", "Bash", self.GW, "command", "relay queue note x --input %s/n.toml" % self.scratch)
        self.g("allow", "Bash", self.GW, "command", "git checkout --theirs -- .relay/queue/x.json")
        self.g("allow", "Bash", self.GW, "command", "cat .relay/queue/x.json")
        self.g("allow", "Write", self.GW, "file_path", self.fx + "/.relay/queue/x.json")


if __name__ == "__main__":
    unittest.main()
