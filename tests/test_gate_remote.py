"""Build-time gates that run on a remote host (docs/plans/vps-build-gates.md 5.1, 5.2, 5.8): the remote log's name, the deciding host,
reuse over a stretch of commits, and the readers of the log. The remote runner is a function the test passes (no ssh, no podman)."""
import contextlib
import io
import os
import unittest

from test_gate import ROOT, Fixture, git, read, write
from relay_testbase import load_hook

import relay_gate
import relay_marks
import relay_verdict

HOST = "ai.test"
HOST_LINE = "host ai.test image relay-gate:0123456789ab tree 0000"


class Fake:
    """The remote runner: records its calls, answers with the codes in `codes` (a code that is an exception is raised)."""

    def __init__(self, *codes):
        self.codes = list(codes) or [0]
        self.calls = []

    def __call__(self, worktree, head, command):
        self.calls.append(head)
        code = self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]
        if isinstance(code, Exception):
            raise code
        return relay_gate.RemoteResult(code, "step FAILED\n  boom\n" if code else "ok\n", HOST_LINE, 0.0)

    def remote(self, **kw):
        return relay_gate.Remote(HOST, self, **kw)


class RemoteBase(Fixture):
    def setUp(self):
        super().setUp()
        self.counter = os.path.join(self.tmp, "runs")
        self.repo(gate='echo run >> "%s"\nexit ${GATE_EXIT:-0}\n' % self.counter)
        write(os.path.join(self.main, "container", "Containerfile"), "FROM x\n")      # on the default branch: a recipe the branch shares (a branch-only one gates on the Mac)
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "recipe")
        git(self.wt, "merge", "-q", "--no-edit", "master")

    def runs(self):
        return len(read(self.counter).splitlines()) if os.path.exists(self.counter) else 0

    def commit(self, msg, rel=None):
        if rel:
            write(os.path.join(self.wt, rel), msg + "\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", msg)
        return git(self.wt, "rev-parse", "HEAD")

    def go(self, remote=None, again=False, quick=True, exit_code=0):
        """relay_gate.run in this process; (code, log, stderr text)"""
        env = {**self.env, "GATE_EXIT": str(exit_code)}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, log, _ = relay_gate.run(self.wt, environ=env, quick=quick, again=again, remote=remote)
        return code, log, err.getvalue()

    def head(self):
        return git(self.wt, "rev-parse", "HEAD")

    def log_path(self, sha, remote):
        return os.path.join(self.wt, ".relay", "checks", sha + (".remote" if remote else "") + ".gate.log")


class RemoteLog(RemoteBase):
    def test_a_remote_gate_writes_its_own_log_and_runs_nothing_here(self):
        """Design 5.1: `<sha>.remote.gate.log` with the host line, committed as `relay: remote gate of <sha>`; no Mac log, no Mac run."""
        sha = self.head()
        fake = Fake(0)
        code, log, _ = self.go(fake.remote())
        self.assertEqual((code, fake.calls, self.runs()), (0, [sha], 0))
        self.assertEqual(log, self.log_path(sha, True))
        lines = read(log).splitlines()
        self.assertEqual((lines[0], lines[3], lines[-1]), ("head " + sha, HOST_LINE, "exit 0"))
        self.assertFalse(os.path.exists(self.log_path(sha, False)))
        self.assertEqual(git(self.wt, "log", "-1", "--format=%s"), "relay: remote gate of " + sha)

    def test_the_merge_hook_refuses_a_head_with_only_a_remote_log_and_takes_it_with_a_mac_log_beside(self):
        """5.8: a green remote log decides no merge (the hook reads `<sha>.gate.log` only); a green Mac log of the same head does."""
        hook = load_hook("merge_hook_for_remote_test", os.path.join(ROOT, "plugins", "relay", "hooks", "merge.py"))
        self.go(Fake(0).remote())
        with self.assertRaises(hook.Refused) as caught:
            hook.step_gate(self.main, "wt/x", "its worktree")
        self.assertIn("no gate has run on it yet", str(caught.exception))
        self.assertEqual(relay_marks.gate_logs(self.main, "refs/heads/wt/x"), [])
        now = self.head()      # the remote log's own commit: record commits only, but the Mac does not reuse a remote log
        code, log, _ = self.go(None)      # a landing passes no remote: the Mac runs, though a green remote log lies in the stretch
        self.assertEqual((code, self.runs(), log), (0, 1, self.log_path(now, False)))
        hook.step_gate(self.main, "wt/x", "its worktree")      # returns: green Mac gate, the remote log beside it

    def test_a_landing_or_a_paid_or_argument_gate_never_calls_the_remote(self):
        fake = Fake(0)
        self.go(fake.remote(), quick=False)
        self.go(None)
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.runs(), 1)      # the second call reused the first one's Mac log

    def test_the_cycle_recovery_names_both_subjects(self):
        text = read(os.path.join(ROOT, "plugins", "delegate", "workflows", "cycle.js"))
        self.assertIn('"relay: gate of <sha>" or "relay: remote gate of <sha>"', text)

    def test_the_printed_line_names_the_host_not_the_file_name(self):
        sha = self.head()
        _, log, _ = self.go(Fake(0).remote())
        self.assertEqual(relay_gate.log_sha_host(log), (sha, HOST))
        self.assertEqual(relay_gate.log_sha_host(self.log_path("a" * 40, False)), ("a" * 40, None))


class Stretch(RemoteBase):
    def test_the_newest_remote_log_decides_over_a_mac_green_on_the_record_commit_after_it(self):
        """5.2: remote red at C (log commit C2), Mac green at C2: relay gate reports the red one and runs nothing."""
        fake = Fake(1)
        code, log, _ = self.go(fake.remote())
        self.assertEqual(code, 1)
        self.go(None, again=True)      # a Mac gate at the record commit: green
        self.assertEqual(self.runs(), 1)
        code, again_log, err = self.go(fake.remote())
        self.assertEqual((code, again_log, len(fake.calls), self.runs()), (1, log, 1, 1))
        self.assertIn("reported, not run", err)

    def test_remote_red_and_mac_green_on_one_commit_report_the_red(self):
        """The Mac gates the head green; the remote then runs it again (--again) and is red: the remote one stands."""
        self.go(None)
        fake = Fake(1)
        self.assertEqual(self.go(fake.remote(), again=True)[0], 1)
        code, log, _ = self.go(fake.remote())
        self.assertEqual((code, log, len(fake.calls), self.runs()), (1, self.log_path(self.head_of_log(), True), 1, 1))

    def head_of_log(self):
        return git(self.wt, "log", "-1", "--format=%s").split()[-1]

    def test_no_mac_run_over_a_red_remote_log_when_the_host_cannot_be_reached(self):
        """5.2: --again with ssh down: the 'stands' line, the red exit, no Mac run."""
        self.go(Fake(1).remote())
        down = Fake(relay_gate.RemoteUnavailable("%s cannot be reached (ssh: connection timed out after 3 s)" % HOST))
        code, _, err = self.go(down.remote(), again=True)
        self.assertEqual((code, self.runs()), (1, 0))
        self.assertIn("gate: the red result of ai.test for %s stands; ai.test cannot be reached" % self.head_of_log()[:12], err)

    def test_an_unreachable_host_gives_one_line_and_a_mac_log(self):
        down = Fake(relay_gate.RemoteUnavailable("%s cannot be reached (ssh: connection timed out after 3 s)" % HOST))
        sha = self.head()
        code, log, err = self.go(down.remote())
        self.assertEqual((code, self.runs(), log), (0, 1, self.log_path(sha, False)))
        mine = [l for l in err.splitlines() if l.startswith("gate: ai.test cannot be reached")]
        self.assertEqual(len(mine), 1)
        self.assertIn(mine[0], read(log))      # also the first output line of the Mac log


class Deciding(RemoteBase):
    def test_after_a_red_mac_log_the_branch_gates_on_the_mac_until_a_green_one(self):
        """5.2 / F7: Mac red, then a fix commit: no remote call. After a green Mac gate the next gate calls the remote."""
        fake = Fake(0)
        self.assertEqual(self.go(None, exit_code=1)[0], 1)
        self.commit("fix", "lib/b.py")
        code, _, err = self.go(fake.remote())
        self.assertEqual((code, fake.calls, self.runs()), (0, [], 2))
        self.assertIn("gate: the last gate of this branch on this Mac is red; this gate runs on this Mac", err)
        self.commit("more", "lib/c.py")
        self.go(fake.remote())
        self.assertEqual(len(fake.calls), 1)      # the Mac log of the fix commit is green: back to the remote

    def test_no_mac_log_and_a_red_remote_log_both_go_to_the_remote(self):
        fake = Fake(1)
        self.go(fake.remote())      # no Mac log
        self.commit("next", "lib/b.py")
        self.go(fake.remote())      # a red remote log only
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(self.runs(), 0)

    def test_the_default_branch_red_sends_a_lane_to_the_mac_except_the_one_holding_the_fix(self):
        fake = Fake(0)
        note = "since 4f1a2b3c (step library; fix item x)"
        code, _, err = self.go(fake.remote(default_red=note))
        self.assertEqual((code, fake.calls, self.runs()), (0, [], 1))
        self.assertIn("gate: the default branch is red on ai.test %s; this gate runs on this Mac" % note, err)
        self.commit("next", "lib/b.py")
        self.go(fake.remote(default_red=note, holds_fix=True))
        self.assertEqual(len(fake.calls), 1)

    def test_a_branch_that_changes_the_toolchain_gates_on_the_mac(self):
        fake = Fake(0)
        self.commit("recipe", "install.sh")
        code, _, err = self.go(fake.remote())
        self.assertEqual((code, fake.calls, self.runs()), (0, [], 1))
        self.assertIn("this branch changes relay's toolchain (install.sh)", err)

    def test_a_worktree_without_a_containerfile_never_goes_remote(self):
        git(self.wt, "rm", "-q", "-r", "container")
        self.commit("drop the recipe")
        fake = Fake(0)
        self.go(fake.remote())
        self.assertEqual((fake.calls, self.runs()), ([], 1))


class Readers(RemoteBase):
    def test_relay_verdict_takes_a_remote_log_as_a_gate_and_keeps_its_bare_name(self):
        sha = self.head()
        _, log, _ = self.go(Fake(0).remote())
        kept, problems = relay_verdict._gate(self.wt, sha, os.path.basename(log))
        self.assertEqual((kept, problems), (sha + ".remote.gate.log", []))

    def test_a_remote_log_whose_head_line_names_another_sha_is_not_in_the_gates_form(self):
        sha = self.head()
        other = "b" * 40
        path = self.log_path(sha, True)
        write(path, "head %s\ncmd x\nwait 0.0\nexit 0\n" % other)
        kept, problems = relay_verdict._gate(self.wt, sha, os.path.basename(path))
        self.assertIsNone(kept)
        self.assertEqual(problems[0][1], "the gate log is not in the gate's form")

    def test_check_show_names_the_host_and_the_newest_mac_log(self):
        self.go(None)
        mac = self.head_of_commit_subject("relay: gate of")
        self.commit("next", "lib/b.py")
        self.go(Fake(0).remote())
        lines = relay_marks.show(self.main, "wt/x", sleep=lambda s: None)
        self.assertEqual(lines[0], "gate %s: exit 0 (on ai.test)" % self.head_of_commit_subject("relay: remote gate of"))
        self.assertEqual(lines[1], "landing gate (this Mac): %s exit 0" % mac)

    def head_of_commit_subject(self, prefix):
        return git(self.wt, "log", "-1", "--format=%s", "--grep=^" + prefix).split()[-1]


if __name__ == "__main__":
    unittest.main()
