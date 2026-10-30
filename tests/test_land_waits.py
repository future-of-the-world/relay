"""What makes `relay land` wait: the owner's hold and an unanswered question (exit 5), the paid run (exit 6), `--paid-fix`,
`--waiting` (lib/relay_land_waits.py). Temporary repositories and a temporary RELAY_HOME; the gate is a script that counts its runs."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import relay_land  # noqa: E402
import relay_land_counters  # noqa: E402
import relay_paid  # noqa: E402
from relay_paid import PaidEvent  # noqa: E402
from test_gate import RELAY, git, write  # noqa: E402
from test_land import Land  # noqa: E402
import test_lanes_state as tls  # noqa: E402

START = "2026-10-30T10:00:00+00:00"
ASKED = {"asked_at": "2026-10-09T22:00:00Z", "question": ["**Keep it?**"], "options": ["a. Yes.", "b. No."]}


class Waits(Land):
    def hold_cmd(self, *args):
        return subprocess.run([sys.executable, RELAY, "land", *args, "-C", self.main], capture_output=True, text=True, env=self.env, cwd=self.main)

    def touch_paid(self):
        """the branch also changes a text the paid run checks (a skill); marked again for the new head"""
        write(os.path.join(self.wt, "plugins", "z", "skills", "s.md"), "text\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "skill")
        self.mark(self.wt)

    def started(self, pid, head="a" * 40):
        relay_paid.record(self.main, PaidEvent("started", START, head=head, pid=pid))

    def eval_record(self, partial, head="a" * 40):
        folder = relay_paid.evals_folder(self.main, self.env["RELAY_HOME"])
        write(os.path.join(folder, "r.json"), json.dumps({"startedAt": "2026-10-30T10:01:00.000Z", "durationSeconds": 60, "partial": partial,
                                                         "cases": [], "head": head, "branch": "master"}))

    def outcomes(self):
        return [e.outcome for e in self.done()]


class Hold(Waits):
    def test_held_branch_exits_5_and_master_stays(self):
        self.start()
        before = self.master()
        self.assertEqual(self.hold_cmd("--hold", "wt/x", "not yet").returncode, 0)
        run = self.land()
        self.assertEqual(run.returncode, 5, run.stdout + run.stderr)
        self.assertIn("not yet", run.stdout)
        self.assertIn("relay land --release wt/x", run.stdout)
        self.assertEqual((self.master(), self.runs(), self.outcomes()), (before, 0, ["waits_owner"]))        # no gate, no fast-forward; wt/x has no queue item

    def test_hold_then_release_lands(self):
        self.start()
        self.hold_cmd("--hold", "wt/x", "wait")
        self.hold_cmd("--release", "wt/x")
        run = self.land()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_a_hold_on_another_branch_does_not_stop_this_one(self):
        self.start()
        self.hold_cmd("--hold", "wt/other", "wait")
        self.assertEqual(self.land().returncode, 0)

    def test_hold_written_during_the_gate_stops_before_the_fast_forward(self):
        gate = 'echo run >> "%(counter)s"\n"%(py)s" "' + RELAY + '" land --hold wt/x "stop" -C "%(tmp)s/main"\nexit 0\n'
        self.start(gate=gate.replace("%(py)s", sys.executable))
        self.master_commit("lib/b.py", "b\n")        # a code take, so the gate runs
        before = self.master()
        run = self.land()
        self.assertEqual(run.returncode, 5, run.stdout + run.stderr)
        self.assertEqual((self.master(), self.runs()), (before, 1))

    def test_hold_events_are_read_and_counted(self):
        self.start()
        self.hold_cmd("--hold", "wt/x", "wait")
        self.land()
        self.assertEqual([e.kind for e in self.events()][:1], ["hold"])
        self.assertIn("outcomes: waits_owner 1", "\n".join(relay_land_counters.stats(self.main, None, None)))
        self.assertIsNone(relay_land.parse_event(json.dumps({"kind": "done", "ts": START, "outcome": "bogus"})))
        for line in ({"kind": "hold", "ts": START, "branch": "b", "words": "w"}, {"kind": "release", "ts": START, "branch": "b"},
                     {"kind": "done", "ts": START, "outcome": "waits_paid"}, {"kind": "done", "ts": START, "outcome": "waits_owner"}):
            self.assertIsNotNone(relay_land.parse_event(json.dumps(line)), line)


class Question(Waits):
    def item(self, **fields):
        # a feature item taken by wt/x, on master (where the owner's answers land); a feature, so the open-fix-item refusal does not apply
        write(os.path.join(self.main, ".relay", "queue", "job.json"), tls.item("job", "feature", **tls.taken("wt/x"), **fields))
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "queue")
        git(self.wt, "merge", "-q", "--no-edit", "master")
        self.mark(self.wt)

    def test_an_unanswered_question_exits_5_and_master_stays(self):
        self.start()
        self.item(notes=[ASKED])
        before = self.master()
        run = self.land()
        self.assertEqual(run.returncode, 5, run.stdout + run.stderr)
        self.assertIn("Keep it?", run.stdout)
        self.assertEqual((self.master(), self.runs()), (before, 0))

    def test_the_same_item_after_the_answer_lands(self):
        self.start()
        self.item(notes=[dict(ASKED, answered_at="2026-10-10T08:00:00Z", answer=["a"])])
        self.assertEqual(self.land().returncode, 0)

    def test_a_decision_an_agent_took_does_not_wait_for_the_owner(self):
        self.start()
        self.item(notes=[dict(ASKED, decided_by="front", chosen="a", because=["the rule says so"])])
        run = self.land()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class Paid(Waits):
    def test_a_going_run_does_not_hold_a_branch_that_touches_no_paid_path(self):
        self.start()
        self.started(os.getpid())
        self.assertEqual(self.land().returncode, 0)           # the branch changes lib/a.py only

    def test_going_run_exits_6_for_a_branch_touching_the_paid_paths(self):
        self.start()
        self.touch_paid()
        self.started(os.getpid())
        before = self.master()
        run = self.land()
        self.assertEqual(run.returncode, 6, run.stdout + run.stderr)
        self.assertIn("has been going since", run.stdout)
        self.assertEqual((self.master(), self.runs(), self.outcomes()), (before, 0, ["waits_paid"]))

    def test_free_state_lands_a_paid_path_branch(self):
        self.start()
        self.touch_paid()
        self.assertEqual(self.land().returncode, 0)

    def test_green_before_sync_waits_and_after_sync_lands(self):
        self.start()
        self.touch_paid()
        self.started(1, head=self.master())
        self.eval_record(False, head=self.master())
        run = self.land()
        self.assertEqual(run.returncode, 6, run.stdout + run.stderr)
        self.assertIn("run relay sync", run.stdout)
        relay_paid.record(self.main, PaidEvent("synced", "2099-01-01T00:00:00+00:00", head=self.master()))
        self.assertEqual(self.land().returncode, 0)

    def test_stopped_run_without_a_verdict_waits(self):
        self.start()
        self.touch_paid()
        self.started(2 ** 22 + 12345)          # a pid no process has
        run = self.land()
        self.assertEqual(run.returncode, 6, run.stdout + run.stderr)
        self.assertIn("start the paid run again", run.stdout)

    def test_red_run_holds_everything_but_the_paid_fix(self):
        self.start()
        self.touch_paid()
        self.started(1, head=self.master())
        self.eval_record(True, head=self.master())
        run = self.land()
        self.assertEqual(run.returncode, 6, run.stdout + run.stderr)
        self.assertIn("--paid-fix", run.stdout)
        run = self.land("wt/x", "--paid-fix")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_paid_fix_is_refused_when_no_run_is_red(self):
        self.start()
        run = self.land("wt/x", "--paid-fix")
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("not needed", run.stdout)

    def test_a_run_that_starts_during_the_landing_gate_stops_the_fast_forward(self):
        py = sys.executable
        hook = ('"%s" -c "import sys; sys.path.insert(0, \'%s\'); import relay_paid; relay_paid.record(sys.argv[1], '
                'relay_paid.PaidEvent(\'started\', relay_paid.now(), head=\'b\', pid=1))" "%%(tmp)s/main"' % (py, os.path.join(ROOT, "lib")))
        self.start(gate='echo run >> "%(counter)s"\n' + hook + '\nexit 0\n')
        self.touch_paid()
        self.master_commit("lib/b.py", "b\n")
        before = self.master()
        run = self.land()
        self.assertEqual(run.returncode, 6, run.stdout + run.stderr)
        self.assertEqual((self.master(), self.runs()), (before, 1))        # the gate ran, the second check refused the move

    def test_waiting_lists_a_branch_after_exit_6_and_drops_it_after_it_lands(self):
        self.start()
        self.touch_paid()
        self.started(os.getpid())
        self.assertEqual(self.land().returncode, 6)
        listed = self.hold_cmd("--waiting")
        self.assertEqual(listed.stdout.split(), ["wt/x"])
        relay_paid.record(self.main, PaidEvent("synced", "2099-01-01T00:00:00+00:00"))        # no start newer than the record: free
        os.remove(relay_paid.events_path(self.main))        # no start recorded: the state is free again
        self.assertEqual(self.land().returncode, 0)
        self.assertEqual(self.hold_cmd("--waiting").stdout.split(), [])


class Surface(Waits):
    def test_help_names_the_new_flags_and_exits_5_and_6(self):
        out = subprocess.run([sys.executable, RELAY, "land", "--help"], capture_output=True, text=True, env=self.env).stdout
        for words in ("--hold", "--release", "--waiting", "--paid-fix", "5 waits for the owner", "6 waits for the paid run"):
            self.assertIn(words, out)

    def test_sync_notes_the_install_and_names_the_waiting_branches(self):
        # relay sync is called with its writer stubbed (it would write the user's files): the note and the list come after a write that was not held
        import importlib.util
        from importlib.machinery import SourceFileLoader
        from unittest import mock
        loader = SourceFileLoader("relay_cmd", RELAY)
        spec = importlib.util.spec_from_loader("relay_cmd", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        self.start()
        self.touch_paid()
        self.started(os.getpid())
        self.assertEqual(self.land().returncode, 6)
        printed = []
        with mock.patch.object(module.relay_rules, "sync", return_value=[]), mock.patch.object(module.relay_config, "active_profile", return_value={}), \
                mock.patch.object(module.relay_config, "ROOT", self.main), mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            self.assertEqual(module.cmd_sync([]), 0)
            self.assertEqual(module.cmd_sync(["--dry"]), 0)
            self.assertEqual(module.cmd_sync(["agents"]), 0)        # named targets: not a full install
        self.assertEqual([e.kind for e in relay_paid.read_events(self.main)], ["started", "synced"])        # the dry run wrote none
        self.assertEqual(len([l for l in printed if l.startswith("waiting for the paid run: wt/x")]), 1)
