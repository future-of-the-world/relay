"""Linux and Mac gate results compared on the same code (design each-change-is-gated-in-a-fresh-container, rev 2, section 8): the pairs, the
verdicts, the waves, the re-run of a red Linux result, the twin of a red landing. Against the fake host; temporary folders only."""
import hashlib
import os
import unittest
from unittest import mock

from test_gate import git, read, write
from test_gate_watch import Watching
from test_land import Land
from vps_base import HOST

import relay_gate
import relay_gate_compare
import relay_gate_ssh
import relay_gate_watch
import relay_hosts
import relay_land
import relay_paid
from relay_gate_logs import RemoteResult

T0 = "2026-10-30T10:00:00+00:00"
T1 = "2026-10-30T11:00:00+00:00"
T2 = "2026-10-30T12:00:00+00:00"
T3 = "2026-10-30T13:00:00+00:00"


def result(code):
    return RemoteResult(code, "step two FAILED\n  boom\n" if code else "ok\n", "host x", 0.0)


class Comparing(Watching):
    """master has code commits made by `code()`; events are written the way relay land writes them."""

    def code(self, name):
        write(os.path.join(self.main, "lib", name + ".py"), name + "\n")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", name)
        return git(self.main, "rev-parse", "HEAD")

    def inert(self, name="docs/handover.md", text="state\n"):
        write(os.path.join(self.main, name), text)
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "inert " + name)
        return git(self.main, "rev-parse", "HEAD")

    def landed(self, sha, ts=T0):
        relay_land.record(self.main, relay_land.Event("done", ts, branch="wt/x", outcome="landed", sha=sha))

    def red(self, judged, ts=T0):
        relay_land.record(self.main, relay_land.Event("done", ts, branch="wt/x", outcome="red", judged=judged))

    def twin_file(self, sha, code):
        write(os.path.join(self.folder, "twin", sha + ".remote.gate.log"), "branch wt/x\nhead %s\ncmd bin/ci --quick\nwait 0.0\nhost x\nok\nexit %d\n" % (sha, code))

    def rerun_file(self, sha, k, code):
        write(os.path.join(self.folder, "%s.rerun-%d.remote.gate.log" % (sha, k)), "head %s\ncmd bin/ci --quick\nwait 0.0\nhost x\nstep two FAILED\n  boom\nexit %d\n" % (sha, code))

    def lines(self, waves=3):
        return relay_gate_compare.compare_lines(self.main, waves, self.home)

    def text(self, waves=3):
        return "\n".join(self.lines(waves))

    def synced(self, ts):
        relay_paid.record(self.main, relay_paid.PaidEvent("synced", ts))


class Pairs(Comparing):
    def test_a_green_landed_head_with_a_green_watch_is_one_agreeing_pair(self):
        head = self.code("a")
        self.landed(head)
        self.watch_file(head, 0)
        text = self.text()
        # one landed head, green on both sides: 1 agree, a streak of 1, nothing unresolved
        self.assertIn("1 landed, 0 red landings; 1 agree", text)
        self.assertIn("agreeing pairs in a row: 1; 0 unresolved", text)

    def test_a_red_watch_on_a_queue_only_commit_after_the_head_pairs_through_the_inert_stretch_and_is_reproduced(self):
        head = self.code("a")
        self.landed(head)
        after = self.inert()      # only an inert file came after: the same code
        self.watch_file(after, 1)
        self.rerun_file(after, 1, 1)      # the re-run is red too: reproduced
        text = self.text()
        self.assertIn("Linux-only red, reproduced: %s step step two FAILED" % head[:12], text)
        self.assertIn("agreeing pairs in a row: 0", text)

    def test_a_red_watch_whose_rerun_is_green_is_flaky_and_neither_breaks_nor_extends_the_streak(self):
        old = self.code("old")
        self.landed(old, T0)
        self.watch_file(old, 0)
        head = self.code("a")
        self.landed(head, T1)
        self.watch_file(head, 1)
        self.rerun_file(head, 1, 0)
        text = self.text()
        self.assertIn("Linux-only red, flaky (green on re-run): %s" % head[:12], text)
        self.assertIn("agreeing pairs in a row: 1", text)      # only the old pair counts

    def test_a_missing_linux_result_never_counts_as_agreement(self):
        agreed = self.code("agreed")
        self.landed(agreed, T0)
        self.watch_file(agreed, 0)
        stopped, nofile, skipped, redlanding = (self.code(n) for n in ("stopped", "nofile", "skipped", "redlanding"))
        self.watch_file(stopped, 124)      # a stop at the time limit: no verdict
        # nofile: a could-not-run event and no file; skipped: the watch gated a later head, which changed code, so no run in its stretch
        self.landed(stopped, T1)
        self.landed(nofile, T1)
        self.landed(skipped, T2)
        self.red(redlanding, T2)      # a red landing with no twin
        text = self.text()
        self.assertIn("4 landed, 1 red landings; 1 agree; 4 unresolved", text)      # agreed + 3 gaps landed (4), 1 red landing; only `agreed` agrees
        self.assertEqual(text.count("no Linux result"), 4)
        self.assertIn("agreeing pairs in a row: 1; 4 unresolved", text)      # the one old pair; the four gaps neither break nor extend it

    def test_the_comparison_only_reads(self):
        head = self.code("a")
        self.landed(head)
        self.watch_file(head, 1)
        red = self.code("b")
        self.red(red)

        def snapshot():
            land = os.path.join(self.main, ".git", "relay-land")
            files = sorted((os.path.relpath(os.path.join(d, f), land), hashlib.sha256(read(os.path.join(d, f)).encode()).hexdigest())
                           for d, _, names in os.walk(land) for f in names)
            return (git(self.main, "status", "--porcelain"), git(self.main, "for-each-ref"), git(self.main, "rev-parse", "HEAD"), files)
        before = snapshot()
        self.lines()
        self.assertEqual(snapshot(), before)

    def test_landed_heads_come_only_from_done_events(self):
        first = self.code("a")
        self.inert(".relay/checks/%s.gate.log" % first, "log\n")      # a gate-log commit after the first landed head
        head1 = git(self.main, "rev-parse", "HEAD")
        take = self.code("take")      # a commit no event names (a take merge, a branch's own commit)
        second = self.code("b")
        self.inert(".relay/checks/%s.gate.log" % second, "log\n")
        head2 = git(self.main, "rev-parse", "HEAD")
        self.landed(head1, T0)
        self.landed(head2, T1)
        for sha in (first, second):
            self.watch_file(sha, 0)
        text = self.text()
        # two done events make two pairs; `take`, which has no event, and the first-parent commits between are not pairs
        self.assertIn("2 landed, 0 red landings; 2 agree", text)
        self.assertNotIn(take[:12], text)

    def test_a_linux_result_may_come_from_a_committed_build_time_log(self):
        head = self.code("a")
        self.landed(head)
        write(os.path.join(self.main, ".relay", "checks", head + ".remote.gate.log"), "head %s\ncmd bin/ci --quick\nwait 0.0\nhost x\nok\nexit 0\n" % head)
        self.assertIn("1 landed, 0 red landings; 1 agree", self.text())


class MacOnlyRed(Comparing):
    def setup_red(self):
        old = self.code("old")
        self.landed(old, T0)
        self.watch_file(old, 0)
        judged = self.code("judged")
        self.red(judged, T1)
        self.twin_file(judged, 0)      # the twin is green: the Mac alone said red
        return judged

    def later_mac_log(self, judged, code):
        c0 = self.inert()
        write(os.path.join(self.main, ".relay", "checks", c0 + ".gate.log"), "head %s\ncmd bin/ci --quick\nstep two FAILED\nexit %d\n" % (c0, code))
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "relay: gate of " + c0)

    def test_a_later_green_mac_gate_of_the_same_code_makes_it_flaky_on_the_mac(self):
        judged = self.setup_red()
        self.later_mac_log(judged, 0)
        text = self.text()
        self.assertIn("Mac-only red, flaky on the Mac: %s" % judged[:12], text)
        self.assertIn("agreeing pairs in a row: 1", text)

    def test_a_later_red_mac_gate_is_reproduced_and_breaks_the_streak(self):
        judged = self.setup_red()
        self.later_mac_log(judged, 1)
        text = self.text()
        self.assertIn("Mac-only red, reproduced on the Mac: %s" % judged[:12], text)
        self.assertIn("agreeing pairs in a row: 0", text)      # the older agreeing pair is behind the reproduced one

    def test_no_later_mac_gate_is_not_re_run_and_unresolved(self):
        judged = self.setup_red()
        text = self.text()
        self.assertIn("Mac-only red, not re-run on the Mac (Linux green): %s" % judged[:12], text)
        self.assertIn("agreeing pairs in a row: 1; 1 unresolved", text)

    def test_a_later_mac_gate_after_a_code_change_is_not_the_same_code(self):
        judged = self.setup_red()
        self.code("changed")      # code moved: a later Mac gate says nothing about `judged`
        self.later_mac_log(judged, 0)
        self.assertIn("not re-run on the Mac", self.text())

    def test_a_red_landing_and_a_red_twin_agree(self):
        judged = self.code("judged")
        self.red(judged)
        self.twin_file(judged, 1)
        self.assertIn("0 landed, 1 red landings; 1 agree", self.text())


class Waves(Comparing):
    def test_waves_split_at_the_dated_synced_events_newest_first(self):
        a, b, c = self.code("a"), self.code("b"), self.code("c")
        self.landed(a, T0)      # before the first sync
        self.landed(b, T2)      # between the two
        self.landed(c, T3)      # after the last
        for sha in (a, b, c):
            self.watch_file(sha, 0)
        self.synced(T1)
        self.synced("2026-10-30T12:30:00+00:00")
        lines = [l for l in self.lines() if l.startswith("    wave")]
        # newest wave first: since 12:30 holds c, 11:00-12:30 holds b, the oldest holds a
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("    wave since 30 Oct 12:30Z: 1 landed"), lines[0])
        self.assertTrue(lines[1].startswith("    wave 30 Oct 11:00Z-30 Oct 12:30Z: 1 landed"), lines[1])
        self.assertTrue(lines[2].startswith("    wave before the first recorded wave (until 30 Oct 11:00Z): 1 landed"), lines[2])

    def test_the_count_of_waves_limits_the_history(self):
        self.synced(T1)
        self.synced(T2)
        self.assertEqual(len([l for l in self.lines(2) if l.startswith("    wave")]), 2)

    def test_with_no_synced_event_there_is_one_group(self):
        head = self.code("a")
        self.landed(head)
        lines = [l for l in self.lines() if l.startswith("    wave")]
        self.assertEqual(len(lines), 1)
        self.assertIn("before the first recorded wave", lines[0])


class Settings(Comparing):
    def test_settings_out_of_bound_are_refused_with_the_bound(self):
        with self.assertRaisesRegex(ValueError, "0 to 3"):
            relay_hosts.set_value(HOST, "rerun_disagreement", "4", self.home)
        with self.assertRaisesRegex(ValueError, "on or off"):
            relay_hosts.set_value(HOST, "twin_red_landings", "maybe", self.home)
        with self.assertRaisesRegex(ValueError, "1 to 20"):
            relay_hosts.main(["compare", "--waves", "21"])
        host = relay_hosts.set_value(HOST, "twin_red_landings", "off", self.home)
        self.assertEqual((host.twin_red_landings, host.watch_default, host.get("rerun_disagreement")), (False, True, 1))
        self.assertFalse(relay_hosts.load(self.home)[HOST].twin_red_landings)

    def test_compare_is_a_hosts_subcommand_and_status_carries_the_block(self):
        self.assertIn("Linux and Mac on the same code", "\n".join(relay_hosts.main(["compare", "-C", self.main])))
        self.assertIn("Linux and Mac on the same code", "\n".join(relay_gate_watch.status_lines(self.main, self.home)))


class Rerun(Comparing):
    def run_watch(self, codes):
        with mock.patch.object(relay_gate_ssh, "gate", side_effect=[result(c) for c in codes]) as gate:
            relay_gate_watch.watch(self.main, None, self.home)
        return gate

    def fix_items(self):
        return [s for s, i in self.items().items() if i["found_in"] == relay_gate_watch.FOUND_IN]

    def test_a_red_watch_then_a_green_rerun_files_nothing_and_sends_lanes_back_to_the_vps(self):
        gate = self.run_watch([1, 0])
        sha = self.master()
        self.assertEqual(gate.call_count, 2)
        self.assertEqual(sorted(os.listdir(self.folder)), sorted(["%s.remote.gate.log" % sha, "%s.rerun-1.remote.gate.log" % sha, "watch.lock"]))
        self.assertEqual(self.fix_items(), [])
        remote, _ = relay_gate_watch.build_remote(self.wt, self.home)
        self.assertEqual(remote.default_red, "")
        self.assertEqual(relay_gate.deciding_host(self.wt, remote, True)[0], "vps")
        self.landed(sha)
        self.assertIn("Linux-only red, flaky", self.text())

    def test_a_red_watch_then_a_red_rerun_files_one_fix_item_and_names_the_step(self):
        self.run_watch([1, 1])
        (slug,) = self.fix_items()
        remote, _ = relay_gate_watch.build_remote(self.wt, self.home)
        # the fix item's queue record moved master by one inert commit; the watch gated the commit before it
        self.assertEqual(remote.default_red, "since %s (step step two FAILED; fix item %s)" % (git(self.main, "rev-parse", "master~1")[:8], slug))

    def test_with_zero_reruns_a_red_watch_files_at_once_and_a_green_one_is_one_file(self):
        relay_hosts.set_value(HOST, "rerun_disagreement", "0", self.home)
        gate = self.run_watch([1])
        self.assertEqual(gate.call_count, 1)
        self.assertEqual(len(self.fix_items()), 1)
        self.assertNotEqual(relay_gate_watch.build_remote(self.wt, self.home)[0].default_red, "")
        relay_hosts.set_value(HOST, "rerun_disagreement", "1", self.home)
        gate = self.run_watch([0])
        self.assertEqual(gate.call_count, 1)      # green: no re-run

    def test_a_rerun_that_cannot_run_files_nothing_and_keeps_the_red_first_run_as_the_state(self):
        with mock.patch.object(relay_gate_ssh, "gate", side_effect=[result(1), relay_gate_ssh.Unavailable("gone", "unreachable")]):
            relay_gate_watch.watch(self.main, None, self.home)
        self.assertEqual(self.fix_items(), [])
        self.assertNotEqual(relay_gate_watch.build_remote(self.wt, self.home)[0].default_red, "")

    def test_a_new_gating_of_a_commit_removes_the_runs_of_its_earlier_gating(self):
        self.run_watch([1, 1])
        self.run_watch([0])
        sha = self.master()
        self.assertEqual([os.path.basename(p) for p in relay_gate_compare.run_files(self.folder, sha)], [sha + ".remote.gate.log"])


class LandingTwin(Land):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"RELAY_HOME": self.env["RELAY_HOME"]})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_landing_red_at_its_gate_records_judged_and_starts_the_twin_once_after_the_done_event(self):
        self.start(gate="exit 1\n")
        with mock.patch.object(relay_land, "_start_twin", return_value=[]) as started:
            result = relay_land.land(self.main, "wt/x", lambda text: None)
        (event,) = self.done()
        # the red gate wrote its log, named for the commit it judged, and that commit is on the branch
        self.assertEqual((result.outcome, event.sha), ("red", None))
        self.assertTrue(os.path.exists(os.path.join(self.wt, ".relay", "checks", event.judged + ".gate.log")))
        started.assert_called_once_with(self.main, event.judged)

    def test_a_stop_at_the_limit_twice_records_no_judged_and_starts_nothing(self):
        self.start(gate="exit 124\n")
        with mock.patch.object(relay_land, "_start_twin", return_value=[]) as started, \
                mock.patch.object(relay_gate, "earlier_stop", return_value="earlier"):
            result = relay_land.land(self.main, "wt/x", lambda text: None)
        (event,) = self.done()
        self.assertEqual((result.outcome, event.judged), ("red", ""))
        started.assert_not_called()

    def test_a_first_stop_at_the_limit_and_a_green_landing_start_no_twin(self):
        self.start(gate="exit 124\n")
        with mock.patch.object(relay_land, "_start_twin", return_value=[]) as started:
            self.assertEqual(relay_land.land(self.main, "wt/x", lambda text: None).outcome, "handed_back")
        started.assert_not_called()

    def test_a_conflict_starts_no_twin(self):
        self.start()
        self.master_commit("lib/a.py", "different\n")      # the branch changed lib/a.py too
        with mock.patch.object(relay_land, "_start_twin", return_value=[]) as started:
            self.assertEqual(relay_land.land(self.main, "wt/x", lambda text: None).outcome, "conflict")
        started.assert_not_called()

    def test_a_twin_that_cannot_start_is_one_line_and_never_changes_the_outcome(self):
        self.start(gate="exit 1\n")
        with mock.patch("relay_gate_watch.start_twin_after_landing", side_effect=RuntimeError("boom")):
            result = relay_land.land(self.main, "wt/x", lambda text: None)
        self.assertEqual(result.outcome, "red")
        self.assertIn("land: the Linux twin of the red gate did not start: boom", result.lines)

    def test_a_done_event_with_judged_is_never_matched_by_the_sha_lookup(self):
        """relay_metrics matches done events by `sha`: a red event carries `judged`, never `sha`, so a re-landing of the same take is one landing."""
        self.start(gate="exit 1\n")
        with mock.patch.object(relay_land, "_start_twin", return_value=[]):
            relay_land.land(self.main, "wt/x", lambda text: None)
        (event,) = self.done()
        self.assertEqual([e for e in self.done() if e.sha == event.judged], [])
        self.assertNotEqual(event.judged, "")


class Twin(Comparing):
    def setUp(self):
        super().setUp()
        self.judged = git(self.wt, "rev-parse", "HEAD")      # a branch commit: not on the first-parent line of master
        self.red(self.judged)

    def spawned(self, **kw):
        calls = []
        relay_gate_watch.start_twin_after_landing(self.main, self.judged, lambda argv, **k: calls.append(argv), self.home, skip_temp=False)
        return calls

    def test_the_twin_starts_detached_when_nothing_forbids_it(self):
        (argv,) = self.spawned()
        self.assertEqual(argv[1:], [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "relay"), "gate", "--twin", self.judged, "-C", self.main])

    def test_no_twin_when_the_setting_is_off_or_there_is_no_record(self):
        relay_hosts.set_value(HOST, "twin_red_landings", "off", self.home)
        self.assertEqual(self.spawned(), [])
        os.remove(os.path.join(self.home, "gate-hosts.json"))
        self.assertEqual(self.spawned(), [])

    def test_no_twin_while_sending_is_stopped_and_the_comparison_says_so(self):
        for _ in range(3):
            relay_gate_ssh.append_event(self.main, HOST, "could-not-run", "gate: x")
        self.assertEqual(self.spawned(), [])
        self.assertIn("no Linux result (sending stopped): %s" % self.judged[:12], self.text())

    def test_no_twin_when_the_stretch_has_a_remote_log_and_the_pair_comes_from_that_log(self):
        write(os.path.join(self.main, ".relay", "checks", self.judged + ".remote.gate.log"), "head %s\ncmd bin/ci --quick\nwait 0.0\nhost x\nok\nexit 1\n" % self.judged)
        self.assertEqual(self.spawned(), [])
        self.assertIn("0 landed, 1 red landings; 1 agree", self.text())

    def test_the_twin_writes_its_own_file_with_the_branch_and_leaves_no_ref_and_no_watch_request(self):
        folder = self.folder
        os.makedirs(folder, exist_ok=True)
        lines = relay_gate_watch.twin(self.main, self.judged, self.home)
        path = os.path.join(folder, "twin", self.judged + ".remote.gate.log")
        self.assertTrue(os.path.exists(path), lines)
        self.assertEqual(read(path).splitlines()[0], "branch wt/x")
        self.assertEqual(read(path).splitlines()[-1], "exit 0")
        self.assertFalse(os.path.exists(os.path.join(folder, "watch.again")))
        self.assertEqual(git(self.main, "for-each-ref", "refs/relay-twin"), "")
        self.assertIn("head=" + self.judged, read(os.path.join(self.vps.root, "capture.txt")))

    def test_a_twin_while_a_watch_runs_writes_no_watch_again(self):
        import fcntl
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, relay_gate_watch.LOCK), "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)      # a watch holds its lock
            relay_gate_watch.twin(self.main, self.judged, self.home)
        self.assertFalse(os.path.exists(os.path.join(self.folder, relay_gate_watch.AGAIN)))
        self.assertTrue(os.path.exists(os.path.join(self.folder, "twin", self.judged + ".remote.gate.log")))

    def test_a_watch_never_removes_a_twins_ref_and_both_files_appear(self):
        git(self.main, "update-ref", "refs/relay-twin/" + self.judged, self.judged)
        relay_gate_watch.watch(self.main, None, self.home)
        self.assertEqual(git(self.main, "rev-parse", "refs/relay-twin/" + self.judged), self.judged)
        self.assertTrue(os.path.exists(os.path.join(self.folder, self.master() + ".remote.gate.log")))

    def test_a_red_twin_files_no_fix_item_and_leaves_the_default_branch_green(self):
        self.watch_file(self.master(), 0)
        self.vps.mode({"ci_exit": 1})
        relay_gate_watch.twin(self.main, self.judged, self.home)
        self.assertEqual(read(os.path.join(self.folder, "twin", self.judged + ".remote.gate.log")).splitlines()[-1], "exit 1")
        self.assertEqual([s for s, i in self.items().items() if i["found_in"] == relay_gate_watch.FOUND_IN], [])
        remote, _ = relay_gate_watch.build_remote(self.wt, self.home)
        self.assertEqual(remote.default_red, "")

    def test_a_twin_never_decides_a_merge(self):
        """The merge path reads only Mac logs: a green twin file beside the red landing leaves .relay/checks and the Mac log reader alone."""
        self.twin_file(self.judged, 0)
        self.assertIsNone(relay_gate.reusable(self.wt, self.judged, relay_gate_ssh.QUICK_COMMAND))
        self.assertFalse(os.path.exists(os.path.join(self.main, ".relay", "checks", self.judged + ".gate.log")))


if __name__ == "__main__":
    unittest.main()
