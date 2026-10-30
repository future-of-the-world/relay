"""The Linux watch of the default branch, the reason a lane stays on the Mac, the stop-sending rule and the watch's start after a landing
(plan gates-on-the-vps-hosts-transport-watch-bring-up 5.2, 5.6, 5.8), against the fake host."""
import fcntl
import os
import subprocess
import sys
import unittest
from unittest import mock

from test_gate import ROOT, git, read, write
from test_land import Land
from vps_base import HOST, VpsBase

import relay_gate_ssh
import relay_gate_watch
import relay_land
import relay_queue

NO_RESULT = "%s has not yet gated the default branch (run relay gate --watch-default)" % HOST


class Watching(VpsBase):
    def setUp(self):
        super().setUp()
        self.preinstall()
        self.folder = os.path.join(self.main, ".git", "relay-land", "linux")
        write(os.path.join(self.main, "lib", "more.py"), "more = 1\n")      # so master~1 is the recipe commit, which a watch can gate
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "more")

    def master(self):
        return git(self.main, "rev-parse", "master")

    def watch_file(self, sha, code):
        write(os.path.join(self.folder, sha + ".remote.gate.log"), "head %s\ncmd bin/ci --quick\nwait 0.0\nhost x\nstep two FAILED\n  boom\nexit %d\n" % (sha, code))

    def items(self):
        return {slug: item for slug, item in relay_queue.Reader(self.main, "refs/heads/master").items().items()}


class Reason(Watching):
    def test_no_watch_file_means_no_remote_and_the_not_yet_line(self):
        self.assertEqual(relay_gate_watch.build_remote(self.wt, self.home), (None, NO_RESULT))

    def test_no_record_means_no_remote_and_no_line(self):
        os.remove(os.path.join(self.home, "gate-hosts.json"))
        self.assertEqual(relay_gate_watch.build_remote(self.wt, self.home), (None, ""))

    def test_a_project_without_a_containerfile_gets_no_line_and_no_remote(self):
        """F2: another project (no container/Containerfile) stays on the Mac silently, as deciding_host does."""
        os.remove(os.path.join(self.wt, "container", "Containerfile"))
        self.assertEqual(relay_gate_watch.build_remote(self.wt, self.home), (None, ""))
        self.assertEqual(self.vps.ssh_calls(), [])

    def test_a_green_watch_gives_a_remote_with_no_default_red(self):
        self.watch_file(self.master(), 0)
        remote, reason = relay_gate_watch.build_remote(self.wt, self.home)
        self.assertEqual((remote.host, remote.default_red, remote.holds_fix, reason), (HOST, "", False, ""))

    def test_the_state_is_the_newest_file_on_the_first_parent_line_not_the_newest_by_time(self):
        """A file written later for an older commit never stands for the head (5.9 step 5): head green, master~1 red written after."""
        head = self.master()
        self.watch_file(head, 0)
        self.watch_file(git(self.main, "rev-parse", "master~1"), 1)
        remote, _ = relay_gate_watch.build_remote(self.wt, self.home)
        self.assertEqual(remote.default_red, "")

    def test_a_red_watch_gives_the_sentence_and_a_stop_at_the_limit_gives_none(self):
        """F11: exit 1 is red; exit 124 is a stop of the code at its limit, not red."""
        sha = self.master()
        self.watch_file(sha, 1)
        remote, _ = relay_gate_watch.build_remote(self.wt, self.home)
        self.assertEqual(remote.default_red, "since %s (step step two FAILED; fix item not filed yet)" % sha[:8])
        self.watch_file(sha, 124)
        self.assertEqual(relay_gate_watch.build_remote(self.wt, self.home)[0].default_red, "")
        self.watch_file(sha, 137)      # killed: not a verdict on the code either
        self.assertEqual(relay_gate_watch.build_remote(self.wt, self.home)[0].default_red, "")

    def test_a_lane_gates_on_the_mac_while_the_watch_is_red_and_the_fix_lane_does_not(self):
        sha = self.master()
        self.watch_file(sha, 1)
        remote, _ = relay_gate_watch.build_remote(self.wt, self.home)
        import relay_gate
        self.assertEqual(relay_gate.deciding_host(self.wt, remote, True)[0], "mac")
        held = relay_gate.Remote(HOST, remote.run, remote.default_red, True)
        self.assertEqual(relay_gate.deciding_host(self.wt, held, True)[0], "vps")


class Watch(Watching):
    def test_a_watch_gates_exactly_the_commit_it_names_and_writes_its_file_uncommitted(self):
        """F2: master~1 while master has moved on: the host's HEAD is master~1, the file is named for it, no ref is left, nothing committed."""
        older = git(self.main, "rev-parse", "master~1")
        before = git(self.main, "rev-parse", "HEAD")
        lines = relay_gate_watch.watch(self.main, older, self.home)
        self.assertIn("head=" + older, read(os.path.join(self.vps.root, "capture.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.folder, older + ".remote.gate.log")))
        self.assertEqual(read(os.path.join(self.folder, older + ".remote.gate.log")).splitlines()[-1], "exit 0")
        self.assertEqual(git(self.main, "for-each-ref", "refs/relay-gate"), "")
        self.assertEqual(git(self.main, "rev-parse", "HEAD"), before)      # never committed
        self.assertEqual(git(self.main, "status", "--porcelain"), "")
        self.assertIn("watch %s: exit 0 (on %s)" % (older[:12], HOST), lines[0])

    def test_a_commit_off_the_first_parent_line_is_refused(self):
        with self.assertRaises(ValueError):
            relay_gate_watch.watch(self.main, git(self.wt, "rev-parse", "HEAD"), self.home)      # the branch's commit is not on master

    def test_a_red_watch_files_one_fix_item_and_a_second_red_adds_none(self):
        self.vps.mode({"ci_exit": 1})
        first = relay_gate_watch.watch(self.main, None, self.home)
        self.assertTrue(any(line.startswith("filed a fix item") for line in first), first)
        fixes = {s: i for s, i in self.items().items() if i["found_in"] == relay_gate_watch.FOUND_IN}
        self.assertEqual(len(fixes), 1)
        item = next(iter(fixes.values()))
        self.assertEqual((item["kind"], item["failing_kind"], item["time"]), ("fix", "run", 30))
        self.assertIn("step two FAILED", item["failing_case"])
        older = git(self.main, "rev-parse", "master~1")
        second = relay_gate_watch.watch(self.main, older, self.home)
        self.assertTrue(any("is open already" in line for line in second), second)
        self.assertEqual(len([i for i in self.items().values() if i["found_in"] == relay_gate_watch.FOUND_IN]), 1)

    def test_a_watch_stopped_at_its_limit_writes_its_file_and_files_nothing(self):
        self.vps.mode({"ci_exit": 124})
        relay_gate_watch.watch(self.main, None, self.home)
        self.assertEqual(read(os.path.join(self.folder, self.master() + ".remote.gate.log")).splitlines()[-1], "exit 124")
        self.assertEqual([i for i in self.items().values() if i["found_in"] == relay_gate_watch.FOUND_IN], [])

    def test_a_watch_with_no_end_line_writes_no_file_and_counts_as_could_not_run(self):
        self.vps.mode({"start_exit": 137})
        lines = relay_gate_watch.watch(self.main, None, self.home)
        self.assertFalse(os.path.exists(os.path.join(self.folder, self.master() + ".remote.gate.log")))
        self.assertIn("no Linux result", lines[0])
        self.assertEqual([e["outcome"] for e in relay_gate_ssh.read_events(self.main, HOST)], ["could-not-run"])

    def test_a_second_watch_asks_the_running_one_to_gate_once_more(self):
        os.makedirs(self.folder)
        with open(os.path.join(self.folder, relay_gate_watch.LOCK), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lines = relay_gate_watch.watch(self.main, None, self.home)
        self.assertIn("already", lines[0])
        self.assertTrue(os.path.exists(os.path.join(self.folder, relay_gate_watch.AGAIN)))
        self.assertEqual(self.vps.ssh_calls(), [])

    def test_a_stale_again_request_does_not_make_a_later_watch_gate_twice(self):
        """F6: a request left by a watch that had ended is cleared when the next watch takes the lock; the tip does not move: one gate."""
        os.makedirs(self.folder)
        write(os.path.join(self.folder, relay_gate_watch.AGAIN), "")
        gated = []
        relay_gate_watch.watch(self.main, None, self.home, gate_one=lambda m, d, h, hm, sha: gated.append(sha) or [])
        self.assertEqual(gated, [self.master()])

    def test_the_running_watch_gates_again_when_the_default_branch_moved_by_code(self):
        """Marker set while it ran -> a second round on the new tip; no marker and no code change -> one round."""
        gated = []

        def one(main, default, host, home, sha):
            gated.append(sha)
            if len(gated) == 1:
                write(os.path.join(self.main, "lib", "new.py"), "x = 1\n")
                git(self.main, "add", "-A"); git(self.main, "commit", "-q", "-m", "code moves")
            return ["gated"]
        first = self.master()
        relay_gate_watch.watch(self.main, None, self.home, gate_one=one)
        self.assertEqual(gated, [first, self.master()])
        gated.clear()
        write(os.path.join(self.main, "notes.md"), "n\n")      # a doc: inert
        git(self.main, "add", "-A"); git(self.main, "commit", "-q", "-m", "inert")
        relay_gate_watch.watch(self.main, None, self.home, gate_one=lambda m, d, h, hm, sha: gated.append(sha) or [])
        self.assertEqual(len(gated), 1)


class StopSending(Watching):
    """F3: the newest `stop_after` counted events all could-not-run stop the lanes; the watch clears it."""

    def lane(self):
        """One lane gate through build_remote's Remote; returns what the caller sees."""
        remote, reason = relay_gate_watch.build_remote(self.wt, self.home)
        if remote is None:
            return reason
        try:
            return remote.run(self.wt, git(self.wt, "rev-parse", "HEAD"), relay_gate_ssh.QUICK_COMMAND).code
        except relay_gate_ssh.Unavailable as exc:
            return "unavailable: %s" % exc

    def test_three_could_not_runs_in_a_row_stop_the_fourth_and_file_one_item(self):
        self.watch_file(self.master(), 0)
        self.vps.mode({"start_exit": 137})
        for _ in range(3):
            self.assertTrue(self.lane().startswith("unavailable"))
        calls = len(self.vps.ssh_calls())
        reason = self.lane()
        self.assertEqual(len(self.vps.ssh_calls()), calls)      # the 4th made no ssh call
        self.assertIn("%s could not run the last 3 gates" % HOST, reason)
        self.assertIn("gates stay on this Mac until a Linux watch there finishes", reason)
        stops = [s for s, i in self.items().items() if i["found_in"] == relay_gate_watch.STOP_FOUND_IN]
        self.assertEqual(len(stops), 1)
        self.assertIn("fix item %s" % stops[0], reason)
        self.assertEqual((self.items()[stops[0]]["failing_kind"], self.items()[stops[0]]["time"]), ("run", 30))

    def test_a_result_between_the_failures_stops_nothing(self):
        self.watch_file(self.master(), 0)
        for mode in ({"start_exit": 137}, {"start_exit": 137}, {}, {"start_exit": 137}, {"start_exit": 137}):
            self.vps.mode(mode)
            self.lane()
        self.vps.mode({})
        self.assertEqual(self.lane(), 0)      # still sending
        self.assertEqual([s for s, i in self.items().items() if i["found_in"] == relay_gate_watch.STOP_FOUND_IN], [])

    def test_unreachable_and_busy_never_count(self):
        self.watch_file(self.master(), 0)
        self.vps.mode({"unreachable": True})
        for _ in range(4):
            self.assertTrue(self.lane().startswith("unavailable"))
        self.vps.mode({})
        self.assertEqual(self.lane(), 0)

    def test_a_watch_ending_137_counts_and_a_watch_that_reaches_an_end_line_clears_the_rule(self):
        self.watch_file(self.master(), 0)
        self.vps.mode({"start_exit": 137})
        for _ in range(3):
            relay_gate_watch.watch(self.main, None, self.home)
        self.assertIn("could not run the last 3 gates", self.lane())
        self.vps.mode({})
        relay_gate_watch.watch(self.main, None, self.home)      # reaches an end line
        self.assertEqual(self.lane(), 0)

    def test_stop_after_is_read_from_the_record(self):
        import relay_hosts
        relay_hosts.set_value(HOST, "stop_after", "1", self.home)
        self.watch_file(self.master(), 0)
        self.vps.mode({"start_exit": 137})
        self.lane()
        self.assertIn("could not run the last 1 gates", self.lane())


class AfterLanding(Land):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"RELAY_HOME": self.env["RELAY_HOME"]})      # the landing's gate takes its slot in the test's home, not the live one
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_landing_starts_the_watch_after_the_done_event(self):
        self.start()
        with mock.patch.object(relay_land, "_start_watch", return_value=["WATCH STARTED"]) as started:
            result = relay_land.land(self.main, "wt/x", lambda text: None)
        self.assertEqual(result.outcome, relay_land.LANDED)
        started.assert_called_once_with(self.main)
        self.assertIn("WATCH STARTED", result.lines)

    def test_a_landing_that_does_not_land_starts_no_watch(self):
        """A landing red at its gate starts the twin (tests/test_gate_compare.py), never the watch."""
        self.start(gate="exit 1\n")
        with mock.patch.object(relay_land, "_start_watch", return_value=["WATCH STARTED"]) as started:
            result = relay_land.land(self.main, "wt/x", lambda text: None)
        self.assertNotEqual(result.outcome, relay_land.LANDED)
        started.assert_not_called()

    def test_a_watch_that_cannot_start_is_a_line_not_a_changed_outcome(self):
        with mock.patch.object(relay_gate_watch, "start_after_landing", side_effect=RuntimeError("boom")):
            self.assertEqual(relay_land._start_watch("/x"), ["land: landed, but the Linux watch did not start: boom; next: relay gate --watch-default"])


class StartAfterLanding(VpsBase):
    def test_it_spawns_the_detached_watch_only_with_a_record_and_the_watch_on(self):
        spawned = []
        spawn = lambda argv, **kw: spawned.append((argv, kw))
        self.assertEqual(relay_gate_watch.start_after_landing(self.main, spawn, self.home, skip_temp=False), [])
        argv, kw = spawned[0]
        self.assertEqual(argv[1:], [os.path.join(ROOT, "bin", "relay"), "gate", "--watch-default", "-C", self.main])
        self.assertTrue(kw["start_new_session"])
        import relay_hosts
        relay_hosts.set_value(HOST, "watch_default", "off", self.home)
        spawned.clear()
        relay_gate_watch.start_after_landing(self.main, spawn, self.home, skip_temp=False)
        self.assertEqual(spawned, [])
        os.remove(os.path.join(self.home, "gate-hosts.json"))
        relay_gate_watch.start_after_landing(self.main, spawn, self.home, skip_temp=False)
        self.assertEqual(spawned, [])

    def test_a_project_without_a_containerfile_starts_no_watch(self):
        """F2: the record is global; a project that cannot go remote has no watch to start."""
        os.remove(os.path.join(self.main, "container", "Containerfile"))
        spawned = []
        relay_gate_watch.start_after_landing(self.main, lambda *a, **k: spawned.append(a), self.home, skip_temp=False)
        self.assertEqual(spawned, [])

    def test_status_calls_only_what_is_red_red(self):
        """F7: the wording follows is_red: exit 130 is not red, 1 is, 124 is a stop at the limit, 0 is green."""
        master = git(self.main, "rev-parse", "master")
        folder = os.path.join(self.main, ".git", "relay-land", "linux")
        for code, word in ((130, "ended 130"), (1, "red"), (124, "stopped at its limit"), (0, "green")):
            write(os.path.join(folder, master + ".remote.gate.log"), "head %s\ncmd bin/ci --quick\nwait 0.0\nhost x\nok\nexit %d\n" % (master, code))
            line = next(l for l in relay_gate_watch.status_lines(self.main, self.home) if "default branch:" in l)
            self.assertTrue(line.endswith(", " + word), line)

    def test_a_repository_in_a_temporary_folder_starts_no_watch(self):
        spawned = []
        relay_gate_watch.start_after_landing(self.main, lambda *a, **k: spawned.append(a), self.home)
        self.assertEqual(spawned, [])


class MergeHookStillLoads(unittest.TestCase):
    """F9: the plugin folders carry relay_land.py without the watch's modules; importing it must still work."""

    def test_relay_land_imports_with_only_a_plugin_lib_on_the_path(self):
        for plugin in ("relay", "front"):
            with self.subTest(plugin=plugin):
                folder = os.path.join(ROOT, "plugins", plugin, "lib")
                if not os.path.exists(os.path.join(folder, "relay_land.py")):
                    continue
                done = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); import relay_land" % folder], capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertNotIn("import relay_gate_watch", read(os.path.join(ROOT, "lib", "relay_land.py")).split("def land(")[0])      # not at the top


if __name__ == "__main__":
    unittest.main()
