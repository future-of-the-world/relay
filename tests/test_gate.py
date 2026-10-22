"""`relay gate` (R1-R5) and the inert probe of bin/ci (A11) of docs/plans/review-gate.md sections 12.4 and 12.6.

Every repository is built in a temp directory; the gate commands are fixtures, never the real bin/ci of this repo
except as the file the A11 fixture copies.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RELAY = os.path.join(ROOT, "bin", "relay")
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_checkpage  # noqa: E402
import relay_verdict  # noqa: E402
import relay_marks  # noqa: E402
import relay_queue  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args, check=True):
    done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if check and done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


def read(path):
    with open(path) as handle:
        return handle.read()


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    if mode:
        os.chmod(path, mode)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = {**os.environ, **GIT_ENV, "RELAY_ROOT": ROOT}
        self.env.pop("RELAY_GATE", None)

    def repo(self, relay=True, gate=None, ignore=".ci/\n.worktrees/\n"):
        """main checkout on master with a worktree .worktrees/x on wt/x holding one commit; gate = the gate script's text"""
        main = os.path.join(self.tmp, "main")
        os.makedirs(main)
        git(main, "init", "-q", "-b", "master")
        write(os.path.join(main, ".gitignore"), ignore)
        if relay:
            write(os.path.join(main, ".relay", "README.md"), "x\n")
        if gate is not None:
            script = os.path.join(self.tmp, "gate.sh")
            write(script, "#!/bin/sh\n" + gate, stat.S_IRWXU)
            write(os.path.join(main, ".claude", "kit.toml"), '[gate]\nci = "%s"\n' % script)
            self.script = script
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "init")
        self.main = main
        self.wt = os.path.join(main, ".worktrees", "x")
        git(main, "worktree", "add", "-q", self.wt, "-b", "wt/x")
        write(os.path.join(self.wt, "lib", "a.py"), "a\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "work")

    def gate(self, cwd, *args):
        return subprocess.run([sys.executable, RELAY, "gate", *args], capture_output=True, text=True, cwd=cwd, env=self.env)


class Gate(Fixture):
    def test_r1_refuses_without_relay_folder(self):
        """R1: the default branch has no .relay/: refused, the message names relay setup, no log, no commit."""
        self.repo(relay=False, gate="exit 0\n")
        before = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        self.assertIn("relay setup", run.stderr)
        self.assertEqual(git(self.wt, "rev-parse", "HEAD"), before)
        self.assertFalse(os.path.exists(os.path.join(self.wt, ".relay")))

    def test_r2_refuses_a_dirty_worktree_and_accepts_an_ignored_file(self):
        """R2: a changed tracked file and an untracked one are refused (the log names a commit, so the code that ran must
        be that commit); an ignored file is fine."""
        self.repo(gate="exit 0\n")
        write(os.path.join(self.wt, "lib", "a.py"), "changed\n")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        self.assertIn("commit first", run.stderr)
        self.assertIn("lib/a.py", run.stderr)
        git(self.wt, "checkout", "--", "lib/a.py")
        write(os.path.join(self.wt, "new.txt"), "x\n")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        self.assertIn("new.txt", run.stderr)
        os.remove(os.path.join(self.wt, "new.txt"))
        write(os.path.join(self.wt, ".ci", "junk.log"), "x\n")      # ignored by .gitignore
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_r3_green_gate_writes_and_commits_its_log_alone(self):
        """R3: log = head <G>, cmd, the gate's output, exit 0; committed alone while a file the gate staged stays
        staged; the gate saw RELAY_GATE=<G>; the three printed lines."""
        self.repo(gate='echo "step one ok"\necho "seen=$RELAY_GATE" > .ci/seen\necho staged > extra.txt\ngit add extra.txt\nexit 0\n')
        head = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 0, run.stderr)
        log = os.path.join(self.wt, ".relay", "checks", head + ".gate.log")
        lines = read(log).splitlines()
        self.assertEqual(lines[0], "head " + head)
        self.assertEqual(lines[1], "cmd %s --quick" % self.script)
        self.assertEqual(lines[2:-1], ["step one ok"])
        self.assertEqual(lines[-1], "exit 0")
        self.assertEqual(read(os.path.join(self.wt, ".ci", "seen")).strip(), "seen=" + head)
        self.assertEqual([l for l in git(self.wt, "show", "--name-only", "--format=%s", "HEAD").splitlines() if l],
                         ["relay: gate of " + head, ".relay/checks/%s.gate.log" % head])
        self.assertEqual(git(self.wt, "diff", "--cached", "--name-only"), "extra.txt")
        out = run.stdout.splitlines()
        self.assertEqual(out, ["gate %s: exit 0" % head, log])

    def test_f11_a_project_that_does_not_ignore_ci_can_run_the_gate_twice(self):
        """F11: .gitignore lacks .ci/. The gate's own output file must not appear in the tree: two gates in a row both run
        (the second is on the first's log commit, an inert one), and the tree stays clean."""
        self.repo(gate="echo ok\nexit 0\n", ignore=".worktrees/\n")
        first = self.gate(self.wt)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.gate(self.wt)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")

    def test_r4_red_gate_exits_with_its_status_and_names_the_failure(self):
        """R4: a red fixture gate: exit status 1 (its own), the log ends exit 1, the failing step's lines are printed."""
        self.repo(gate='echo "ci: tests ok (1s)"\necho "ci: lint FAILED (1s, log: x)"\necho "    bad line"\nexit 1\n')
        head = git(self.wt, "rev-parse", "HEAD")
        run = self.gate(self.wt)
        self.assertEqual(run.returncode, 1)
        log = os.path.join(self.wt, ".relay", "checks", head + ".gate.log")
        self.assertEqual(read(log).splitlines()[-1], "exit 1")
        self.assertEqual(run.stdout.splitlines(), ["gate %s: exit 1" % head, log, "ci: lint FAILED (1s, log: x)", "    bad line"])
        # a different status passes through: 3 stays 3
        write(self.script, "#!/bin/sh\nexit 3\n", stat.S_IRWXU)    # the script lives outside the repo: the worktree is still clean
        self.assertEqual(self.gate(self.wt).returncode, 3)

    def test_r5_refused_in_the_main_checkout(self):
        """R5: the gate runs on a task branch, not in the main checkout."""
        self.repo(gate="exit 0\n")
        run = self.gate(self.main)
        self.assertEqual(run.returncode, 1)
        self.assertIn("task branch", run.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.main, ".relay", "checks")))


class Inert(Fixture):
    """A11: bin/ci's last step `inert` runs only under `relay gate`, once, and is RED when a test reads an inert file."""

    TEST = (
        "import os, unittest\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_it(self):\n"
        "        marker = os.environ.get('INERT_MARKER')\n"
        "        if marker:\n"
        "            with open(marker, 'a') as handle:\n"
        "                handle.write('run\\n')\n"
        "%s"
    )

    def project(self, body="        pass\n"):
        """A project whose gate is a copy of the real bin/ci with one passing library test; a fake `claude` on PATH."""
        main = os.path.join(self.tmp, "main")
        os.makedirs(main)
        git(main, "init", "-q", "-b", "master")
        write(os.path.join(main, ".gitignore"), ".ci/\n.worktrees/\n")
        write(os.path.join(main, ".relay", "README.md"), "x\n")
        write(os.path.join(main, "docs", "handover.md"), "state\n")
        write(os.path.join(main, "tests", "test_x.py"), self.TEST % body)
        write(os.path.join(main, "evals", "plugin", "graders.test.sh"), "exit 0\n")
        os.makedirs(os.path.join(main, "bin"))
        shutil.copy(os.path.join(ROOT, "bin", "ci"), os.path.join(main, "bin", "ci"))
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "init")
        self.wt = os.path.join(main, ".worktrees", "x")
        git(main, "worktree", "add", "-q", self.wt, "-b", "wt/x")
        fake = os.path.join(self.tmp, "fakebin")
        write(os.path.join(fake, "claude"), "#!/bin/sh\nexit 0\n", stat.S_IRWXU)
        self.marker = os.path.join(self.tmp, "marker")
        self.env.update(PATH=fake + os.pathsep + self.env["PATH"], INERT_MARKER=self.marker)

    def runs(self):
        return len(read(self.marker).splitlines()) if os.path.exists(self.marker) else 0

    def test_without_relay_gate_the_step_is_skipped(self):
        """A11 (1): plain `bin/ci --quick` prints the skip line, is green, and runs the tests once."""
        self.project()
        run = subprocess.run(["bash", "bin/ci", "--quick"], capture_output=True, text=True, cwd=self.wt, env=self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("inert: skipped (runs under relay gate)", run.stdout)
        self.assertEqual(self.runs(), 1)

    def test_under_relay_gate_one_nested_run_and_green(self):
        """A11 (3) and (4): under `relay gate` with nothing reading an inert file: `inert` ok, and exactly one nested run
        (the marker file has the outer run's line and the nested run's: 2)."""
        self.project()
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.runs(), 2)
        head = git(self.wt, "rev-parse", "HEAD~1")
        self.assertIn("ci: inert ok", read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))

    def test_a_test_reading_an_inert_file_turns_inert_red(self):
        """A11 (2): a committed test asserts on docs/handover.md. The outer run passes ("state"); the nested run, where
        the file got a probe line, fails: the step results differ, so `inert` is RED and so is the gate."""
        self.project("        with open('docs/handover.md') as handle:\n"
                     "            self.assertEqual(handle.read(), 'state\\n')\n")
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        head = git(self.wt, "rev-parse", "HEAD~1")
        log = read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log"))
        self.assertIn("ci: inert FAILED", log)
        self.assertIn("ci: library tests ok", log)       # the outer run itself was green
        self.assertEqual(self.runs(), 2)

    def test_a_full_run_is_probed_with_its_hook_suites_in_full(self):
        """The hook case count must not depend on the mode: a suite that prints 2 ok lines in full mode and 1 under
        RELAY_QUICK=1 (as guard-main does) gives 2 in a full outer run; the nested probe run is quick for the paid steps
        only, so it must count 2 as well, else `inert` was red with 932 against 448 cases. The full outer run ends red
        here (the fixture has no eval-record); only the `inert` line is asserted."""
        self.project()
        main = os.path.dirname(os.path.dirname(self.wt))
        write(os.path.join(self.wt, "plugins", "x", "tests", "a.test.sh"),
              'echo "ok   one"\n[ "${RELAY_QUICK:-0}" = 1 ] || echo "ok   two"\n')
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "hook suite")
        self.gate(self.wt, "--")
        head = git(self.wt, "rev-parse", "HEAD~1")
        log = read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log"))
        self.assertIn("ci: inert ok", log)

    def test_f9_the_probe_plants_files_under_the_stored_json_names(self):
        """F9: a test that breaks on an unknown queue item or check JSON (as a reader listing the folders would) turns
        `inert` red: the probe planted .relay/queue/zz-probe.json, .relay/checks/zz.review.json and zz.check.json."""
        self.project("        for rel in ('.relay/queue/zz-probe.json', '.relay/checks/zz.review.json', '.relay/checks/zz.check.json'):\n"
                     "            self.assertFalse(os.path.exists(rel), rel)\n")
        run = self.gate(self.wt, "--", "--quick")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        head = git(self.wt, "rev-parse", "HEAD~1")
        self.assertIn("ci: inert FAILED", read(os.path.join(self.wt, ".relay", "checks", head + ".gate.log")))


def finding(fid, path, line, severity, summary, case, kind="inside"):
    return {"id": fid, "path": path, "line": line, "severity": severity, "rank": {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}[severity], "kind": kind, "summary": summary, "failing_case": [case]}


class Page(Fixture):
    """P1 and P2 (design 12.4): `relay check page` writes one HTML file from the stored checks."""

    def stored(self, findings, source_lines=100, opened=1, queue_line=None, new=(), code_after=False, queue_state=None):
        """A branch with src/a.py (line 10 holds `if a < b and c & d:`), a green gate log, a review set made of `findings`
        (finding dicts), a check with F1 MET tests/t.py:5 / F2 NOT MET no test, and the mark; returns the reviewed sha."""
        self.repo()
        code = ["line %d" % n for n in range(1, source_lines + 1)]
        code[9] = "if a < b and c & d:"
        write(os.path.join(self.wt, "src", "a.py"), "\n".join(code) + "\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "code")
        reviewed = git(self.wt, "rev-parse", "HEAD")
        log = os.path.join(self.wt, ".relay", "checks", reviewed + ".gate.log")
        write(log, "head %s\ncmd fixture\nci: tests ok (1s)\nexit 0\n" % reviewed)
        relay_marks.commit_file(self.wt, log, "relay: gate of " + reviewed)
        review = {"schema": 1, "type": "review", "reviewed": reviewed, "base": "master", "findings": findings, "file": "findings.json"}
        check = {"schema": 1, "type": "check", "head": reviewed, "reviewed": reviewed, "gate": None, "review": [reviewed + ".review.json"],
                 "findings": [{"id": "F1", "verdict": "MET", "reason": ["tests/t.py:5"]}, {"id": "F2", "verdict": "NOT MET", "reason": ["no test"]}],
                 "new": list(new), "open": opened, "queued": 0}
        mark = {"schema": 1, "commit": reviewed, "verdict": {"open": opened, "queued": 0, "reviewed": reviewed},
                "review": reviewed + ".review.json", "check": reviewed + ".check.json", "gate": None, "time": "2026-10-22T10:00:00Z"}
        relay_marks.put(self.wt, reviewed, mark, {
            reviewed + ".review.json": json.dumps(relay_verdict.stored_set([review], reviewed)),
            reviewed + ".check.json": json.dumps(check)})
        if queue_line:
            # an item as relay_queue writes it: the finding's linter line is the first line of its `what`
            item = relay_queue.new_item("fix", 1, 10, "2026-10-22", "test", "an outside thing", queue_line, "it matters", failing="z")
            where = os.path.join(self.main, ".relay", "queue", "foo.json")
            if queue_state:                 # the item was closed or dropped: it lives in done/
                item = relay_queue.changed(item, state=queue_state, closed_by="wt/y" if queue_state == "done" else "",
                                           test="t.py::t" if queue_state == "done" else "", dropped_why=["no"] if queue_state == "dropped" else None)
                where = os.path.join(self.main, ".relay", "queue", "done", "foo.json")
            write(where, relay_queue.serialize("foo", item))
            git(self.main, "add", "-A")
            git(self.main, "commit", "-q", "-m", "queue foo")
        if code_after:                      # a code commit after the gate and the mark, with no new gate
            write(os.path.join(self.wt, "lib", "later.py"), "later\n")
            git(self.wt, "add", "-A")
            git(self.wt, "commit", "-q", "-m", "code after the gate")
        return reviewed

    def page(self, *extra):
        run = subprocess.run([sys.executable, RELAY, "check", "page", "-C", self.main, "wt/x", *extra],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 0, run.stderr)
        return run.stdout.strip(), read(run.stdout.strip())

    def test_p1_page_holds_each_finding_status_and_code_escaped(self):
        """P1: each linter line, its status line and the five code lines around it at the reviewed commit; no script, no
        link; `<` and `&` of a code line shown as &lt; and &amp;; the outside finding shows its queue item's slug."""
        outside = "src/a.py:30: LOW: F3 an outside thing"
        review = [finding("F1", "src/a.py", 10, "HIGH", "comparison a < b & c drops rows", "a=1 gives 0 rows, should give 1."),
                  finding("F2", "src/a.py", 20, "MEDIUM", "second thing", "input y."),
                  finding("F3", "src/a.py", 30, "LOW", "an outside thing", "z.", kind="outside")]
        self.stored(review, queue_line=outside)
        path, page = self.page()
        self.assertEqual(path, os.path.join(self.main, ".ci", "page-x.html"))
        # hand-worked: html.escape of `a < b & c` is `a &lt; b &amp; c`; the excerpt of line 10 is lines 8..12
        self.assertIn("src/a.py:10: HIGH: F1 comparison a &lt; b &amp; c drops rows", page)
        self.assertIn("src/a.py:20: MEDIUM: F2 second thing", page)
        self.assertIn("MET tests/t.py:5", page)
        self.assertIn("NOT MET no test", page)
        self.assertIn("   8  line 8\n   9  line 9\n  10  if a &lt; b and c &amp; d:\n  11  line 11\n  12  line 12", page)
        self.assertNotIn("if a < b", page)
        self.assertIn("a=1 gives 0 rows, should give 1.", page)
        self.assertIn("queued as <b>foo</b>", page)
        # verdict line: gate green, 2 inside, 1 fixed and checked (F1 MET, F2 NOT MET), 1 outside queued, open 1
        self.assertIn("2 found inside the change, 1 fixed and checked; 1 outside, 1 queued. Open: 1.", page)
        self.assertIn("Free checks: green (gate of ", page)
        self.assertIn("ci: tests ok (1s)", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("http", page)
        self.assertNotIn("<link", page)
        # -o writes where asked
        target = os.path.join(self.tmp, "out", "p.html")
        written, _ = self.page("-o", target)
        self.assertEqual(written, target)
        self.assertTrue(os.path.exists(target))

    def closed_item_page(self, state):
        outside = "src/a.py:30: LOW: F3 an outside thing"
        review = [finding("F1", "src/a.py", 10, "HIGH", "first", "x."), finding("F3", "src/a.py", 30, "LOW", "an outside thing", "z.", kind="outside")]
        self.stored(review, queue_line=outside, queue_state=state)
        return self.page()[1]

    def test_f6_an_outside_finding_whose_item_was_closed_still_counts_as_queued(self):
        """Review F6: foo moved to done/ as closed: the page says "queued as foo (closed)" and the verdict counts it."""
        page = self.closed_item_page("done")
        self.assertIn("queued as <b>foo</b> (closed)", page)
        self.assertIn("1 outside, 1 queued.", page)
        self.assertNotIn("not queued", page)

    def test_f6_an_outside_finding_whose_item_was_dropped_still_counts_as_queued(self):
        page = self.closed_item_page("dropped")
        self.assertIn("queued as <b>foo</b> (dropped)", page)
        self.assertIn("1 outside, 1 queued.", page)

    def test_f6_an_outside_finding_no_item_carries_is_not_queued(self):
        review = [finding("F1", "src/a.py", 10, "HIGH", "first", "x."), finding("F3", "src/a.py", 30, "LOW", "an outside thing", "z.", kind="outside")]
        self.stored(review)
        page = self.page()[1]
        self.assertIn("not queued", page)
        self.assertIn("1 outside, none queued.", page)

    def test_f3_page_shows_the_checks_new_findings_and_the_questions(self):
        """F3: a mark with open 1 whose check has a new inside HIGH F9 and every review finding MET, and a question finding:
        the page shows F9's linter line and case, the question under its heading, and never says 'all fixed' next to it."""
        review = [finding("F1", "src/a.py", 10, "HIGH", "first", "x."), finding("F2", "src/a.py", 20, "MEDIUM", "second", "y."),
                  finding("F3", "src/a.py", 30, "LOW", "which way", "z.", kind="question")]
        new = [finding("F9", "src/a.py", 40, "HIGH", "a break the fix caused", "w gives 0.")]
        self.stored(review, new=new)
        _, page = self.page()
        self.assertIn("<h2>New in the check</h2>", page)
        self.assertIn("src/a.py:40: HIGH: F9 a break the fix caused", page)
        self.assertIn("w gives 0.", page)
        self.assertIn("<h2>Questions for the owner</h2>", page)
        self.assertIn("src/a.py:30: LOW: F3 which way", page)
        self.assertIn("1 new in the check", page)
        self.assertNotIn("all fixed and checked", page)

    def test_f3_a_clean_check_still_says_all_fixed_and_checked(self):
        # one inside finding F1, MET in the fixture check, open 0, no new: the verdict as before
        self.stored([finding("F1", "src/a.py", 10, "HIGH", "first", "x.")], opened=0)
        _, page = self.page()
        self.assertIn("1 found inside the change, all fixed and checked; 0 outside, none queued. Open: 0.", page)
        self.assertNotIn("New in the check", page)

    def test_f10_the_page_does_not_say_plain_green_when_code_changed_after_the_gate(self):
        self.stored([finding("F1", "src/a.py", 10, "HIGH", "first", "x.")], opened=0, code_after=True)
        _, page = self.page()
        self.assertIn("Free checks: green, but code changed since (gate of ", page)
        self.assertIn('class="verdict bad"', page)

    def test_f10_an_inert_commit_after_the_gate_is_still_plain_green(self):
        self.stored([finding("F1", "src/a.py", 10, "HIGH", "first", "x.")], opened=0)
        write(os.path.join(self.wt, "docs", "handover.md"), "state\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "handover")
        _, page = self.page()
        self.assertIn("Free checks: green (gate of ", page)

    def test_p2_page_is_cut_at_page_max_lines(self):
        """P2: 75 findings of 8 content lines each (linter, status, five code lines, failing case) = 600 lines. By hand:
        400 / 8 = 50 fit, so F1..F50 are shown and 25 are cut with the 'more' line naming the review file."""
        self.assertEqual(relay_checkpage.PAGE_MAX_LINES, 400)
        review = [finding("F%d" % n, "src/a.py", n + 2, "MEDIUM", "thing %d" % n, "case %d." % n) for n in range(1, 76)]
        reviewed = self.stored(review, opened=0)
        _, page = self.page()
        self.assertEqual(page.count('class="finding"'), 50)
        self.assertIn("src/a.py:52: MEDIUM: F50 thing 50", page)
        self.assertNotIn("F51 thing 51", page)
        self.assertIn("25 more findings in .relay/checks/%s.review.json" % reviewed, page)

    def test_page_refuses_a_mark_whose_review_data_is_missing_or_invalid(self):
        """The page reads only the stored JSON: a mark from the prose-only days (no data files) or with a broken review
        set gives no page and a message, never a guess from the markdown."""
        reviewed = self.stored([finding("F1", "src/a.py", 10, "HIGH", "x", "y")])
        folder = os.path.join(self.wt, ".relay", "checks")
        write(os.path.join(folder, reviewed + ".review.json"), "{not json")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "break the review data")
        run = subprocess.run([sys.executable, RELAY, "check", "page", "-C", self.main, "wt/x"], capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 1)
        self.assertIn("the review data %s.review.json is not JSON" % reviewed, run.stderr)
        git(self.wt, "rm", "-q", "-f", ".relay/checks/%s.review.json" % reviewed)
        git(self.wt, "commit", "-q", "-m", "remove the review data")
        run = subprocess.run([sys.executable, RELAY, "check", "page", "-C", self.main, "wt/x"], capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 1)
        self.assertIn("is not stored for wt/x", run.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.main, ".ci", "page-x.html")))

    def test_page_refuses_without_a_mark(self):
        """No check mark yet: no page is built, no file written, the message says what to run."""
        self.repo()
        run = subprocess.run([sys.executable, RELAY, "check", "page", "-C", self.main, "wt/x"], capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 1)
        self.assertIn("no check mark for wt/x yet", run.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.main, ".ci", "page-x.html")))


if __name__ == "__main__":
    unittest.main()
