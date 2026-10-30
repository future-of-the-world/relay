"""The ssh transport and the program on the host (plan gates-on-the-vps-hosts-transport-watch-bring-up 5.3-5.5, 5.8), against a fake ssh and a
fake podman (tests/fake_vps.py) that run the REAL lib/relay_gate_remote.py: no network."""
import hashlib
import os
import shlex
import subprocess
import sys
import threading
import unittest
from unittest import mock

from test_gate import ROOT, RELAY, git, read, write
from vps_base import HOST, VpsBase, wait_until

import relay_gate_ssh


class Transport(VpsBase):
    def test_a_lane_gate_runs_the_exact_commit_on_the_host_and_logs_the_host_line(self):
        """The container's HEAD is the gated commit and its default branch exists (5.3.5); the log is the remote one with a host line."""
        sha = self.head()
        code, log, _ = self.gate()
        self.assertEqual(code, 0)
        self.assertTrue(log.endswith(sha + ".remote.gate.log"))
        lines = read(log).splitlines()
        tree = git(self.wt, "rev-parse", sha + "^{tree}")      # the gated commit; HEAD has moved on by the log commit
        self.assertEqual(lines[3], "host %s image relay-gate:%s tree %s" % (HOST, self.tag(), tree))
        self.assertEqual(lines[-1], "exit 0")
        seen = read(os.path.join(self.vps.root, "capture.txt"))
        self.assertIn("head=" + sha, seen)
        self.assertIn("master", seen.split("branches=")[1].split())      # "git branch <default> <tip>" (the lane branch is there too)
        self.assertTrue(any("on %s (slot 1 of 2, image relay-gate:%s" % (HOST, self.tag()) in line for line in self.captured))

    def test_a_red_exit_of_the_container_is_the_gates_exit(self):
        self.vps.mode({"ci_exit": 1})
        code, log, red = self.gate()
        self.assertEqual(code, 1)
        self.assertIn("step two FAILED", read(log))
        self.assertEqual(red[0], "step two FAILED")

    def test_only_an_end_line_makes_a_result(self):
        """A forged end line followed by podman exiting 1 is no result; podman failing to start (125) and a kill (137) are not either: each gives
        one line and the Mac runs the gate (5.5)."""
        cases = [({"forged": True}, "could not run the gate (podman exited 1"),
                 ({"create_exit": 125}, "could not run the gate (podman exited 125: Error: boom from podman)"),
                 ({"start_exit": 137}, "the container was killed, exit 137, memory peak unknown of 4 GiB")]
        for mode, text in cases:
            with self.subTest(mode=mode):
                self.vps.mode(mode)
                sha_log = os.path.join(self.wt, ".relay", "checks", self.head() + ".remote.gate.log")
                code, log, _ = self.gate(again=True)
                self.assertFalse(os.path.exists(sha_log))      # no remote log for a host that reached no end line
                self.assertTrue(log.endswith(".gate.log") and not log.endswith(".remote.gate.log"))      # the Mac ran it
                self.assertIn(text, read(log))      # the line is the first output line of the Mac log
                self.assertEqual(self.vps.containers(), [])      # the container is removed

    def test_an_unreachable_host_gives_one_line_and_a_mac_gate(self):
        self.vps.mode({"unreachable": True})
        code, log, err = self.go_err()
        self.assertEqual(code, 0)
        self.assertIn("gate: %s cannot be reached (connect to host ai.test port 22: Connection timed out); this gate runs on this Mac" % HOST, err)

    def go_err(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, log, _ = self.gate(again=True)      # again: a Mac log of the same commit from an earlier fallback would be reused
        return code, log, err.getvalue()

    def test_a_missing_or_different_program_is_installed_once_and_the_gate_runs_remote(self):
        """Exit 97 (missing) and 93 (another version): the Mac installs the default branch's bytes with the fixed line and retries (5.3.6)."""
        for broken in (None, self.program_text() + "# an older copy\n"):      # the older copy runs and answers 93
            with self.subTest(broken=broken):
                home_file = os.path.join(self.vps.root, "home", "relay-gate-remote.py")
                if os.path.exists(home_file):
                    os.remove(home_file)
                if broken:
                    write(home_file, broken)
                before = len(self.vps.ssh_calls())
                code, log, _ = self.gate(again=True)
                calls = self.vps.ssh_calls()[before:]
                self.assertEqual((code, len(calls)), (0, 3))      # run (97 or 93), install, run
                self.assertTrue(log.endswith(".remote.gate.log"))
                self.assertEqual(calls[1]["cmd"], relay_gate_ssh.INSTALL_LINE)
                self.assertEqual(read(home_file), read(self.program))

    def test_the_version_sent_is_the_default_branchs_blob_never_a_branch_draft(self):
        """F6: the worktree changes lib/relay_gate_remote.py; the version asked for is still the sha256 of master's file."""
        self.preinstall()
        write(os.path.join(self.wt, "lib", "relay_gate_remote.py"), "# a draft\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "draft")
        self.gate()
        sent = shlex.split(self.vps.ssh_calls()[-1]["cmd"].split("exec python3 ", 1)[1])[2]      # relay-gate-remote.py gate <version> ...
        self.assertEqual(sent, hashlib.sha256(read(self.program).encode()).hexdigest())

    def test_the_host_receives_exactly_the_arguments_the_mac_built(self):
        """F8: a branch named with shell characters round-trips through the login shell's second parse, and nothing runs."""
        name = "wt/a$(id);x'y"
        git(self.wt, "branch", "-m", name)
        self.preinstall()
        code, log, _ = self.gate()
        self.assertEqual(code, 0)
        self.assertTrue(log.endswith(".remote.gate.log"))
        words = shlex.split(self.vps.ssh_calls()[-1]["cmd"].split("exec python3 ", 1)[1])
        self.assertEqual(words[3], "refs/heads/" + name)

    def test_nothing_of_relay_home_goes_along(self):
        """5.8: ssh gets a cut environment, no agent or forwarding, and only the one key."""
        self.preinstall()
        with mock.patch.object(subprocess, "Popen", wraps=subprocess.Popen) as popen:
            self.gate()
        call = [c for c in popen.call_args_list if c.args[0][0] == "ssh"][0]
        kwargs, argv = call.kwargs, call.args[0]
        self.assertEqual(sorted(kwargs["env"]), sorted(set(kwargs["env"]) & {"PATH", "HOME", "LANG"}))
        for option in ("ForwardAgent=no", "ClearAllForwardings=yes", "IdentitiesOnly=yes", "BatchMode=yes"):
            self.assertIn(option, argv)
        self.assertEqual(argv[argv.index("-i") + 1], os.path.join(self.home, "keys", "gate-host"))
        self.assertEqual(argv[-2], "relay-gate@" + HOST)

    def test_a_busy_host_gives_the_busy_line(self):
        self.preinstall()
        self.use_host(slots=1, remote_wait_s=0)
        state = os.path.join(self.vps.root, "state", "containers")
        os.makedirs(state)
        write(os.path.join(state, "relay-gate-s1-9999.json"), "{}")
        write(os.path.join(state, "relay-gate-s1-9999.run"), "")      # a container of slot 1 is running
        code, log, err = self.go_err()
        self.assertIn("gate: %s was busy for 0 min (1 gates running); this gate runs on this Mac" % HOST, err)

    def test_a_build_runs_inside_its_slot_and_is_killed_at_its_bound(self):
        """F5: a build past build_limit_s ends with the 'still building' line; the slot is free after; a second gate that finds the build lock
        held falls back at once with 'is building'."""
        self.preinstall()
        self.use_host(build_limit_s=1)      # the record allows 300 at least; the transport takes any Host
        self.vps.mode({"build_hang": True})
        code, log, err = self.go_err()
        self.assertIn("was still building image relay-gate:%s after 0 min" % self.tag(), err)
        import fcntl
        slot = open(os.path.join(self.vps.root, "home", "slots", "1.lock"), "w")
        fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)      # raises if the program left the slot held
        slot.close()
        held = open(os.path.join(self.vps.root, "home", "slots", "build-%s.lock" % self.tag()), "w")
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)      # the killed build released its lock too
        code, log, err = self.go_err()
        held.close()
        self.assertIn("is building image relay-gate:%s now" % self.tag(), err)

    def test_the_slot_wait_and_the_build_do_not_count_against_the_gates_limit(self):
        """A missing image is built and the gate then runs: the remote log ends `exit 0` with no stop line, though the limit is 1 s."""
        self.preinstall()
        write(os.path.join(self.main, "lib", "relay_ci.py"), "QUICK_LIMIT_SECONDS = 1\n")
        git(self.main, "add", "-A"); git(self.main, "commit", "-q", "-m", "limit")
        git(self.wt, "merge", "-q", "--no-edit", "master")
        self.assertEqual(self.vps.images(), [])
        with mock.patch.object(relay_gate_ssh, "BACKSTOP_MARGIN_S", 30):
            code, log, _ = self.gate()
        self.assertEqual((code, self.vps.images()), (0, ["relay-gate:" + self.tag()]))
        self.assertEqual(read(log).splitlines()[-1], "exit 0")

    def test_a_hung_remote_run_is_the_backstop_not_a_stop_of_the_code(self):
        """After the running line, no end line within limit + margin: ssh is ended, no remote log, one line, a Mac log; stdin closing removes
        the container (no orphan keeps a slot)."""
        self.preinstall()
        write(os.path.join(self.main, "lib", "relay_ci.py"), "QUICK_LIMIT_SECONDS = 1\n")
        git(self.main, "add", "-A"); git(self.main, "commit", "-q", "-m", "limit")
        git(self.wt, "merge", "-q", "--no-edit", "master")
        self.vps.mode({"hang": True})
        with mock.patch.object(relay_gate_ssh, "BACKSTOP_MARGIN_S", 0):
            code, log, err = self.go_err()
        self.assertIn("gate: %s did not finish within 1 min of starting; this gate runs on this Mac" % HOST, err)
        self.assertFalse(log.endswith(".remote.gate.log"))
        self.assertTrue(wait_until(lambda: self.vps.containers() == []))

    def test_a_lost_connection_after_the_running_line_is_a_could_not_run(self):
        self.preinstall()
        self.vps.mode({"lose_after_running": True})
        code, log, err = self.go_err()
        self.assertIn("gate: the connection to %s was lost after 0.0 min; this gate runs on this Mac" % HOST, err)
        self.assertTrue(wait_until(lambda: self.vps.containers() == []))

    def test_a_cut_while_the_container_is_still_being_created_removes_it_once_created(self):
        """The running line comes before `podman create`: a cut that arrives while create runs (slow here by the fake) must not leave the container."""
        self.preinstall()
        self.vps.mode({"lose_after_running": True, "create_sleep": 2})
        code, log, err = self.go_err()
        self.assertIn("was lost after", err)
        # the create ends (marker) after the cut; the container it made must then be removed (an empty list before the marker proves nothing)
        self.assertTrue(wait_until(lambda: os.path.exists(os.path.join(self.vps.root, "created"))))
        self.assertTrue(wait_until(lambda: self.vps.containers() == []))

    def test_a_lane_gate_whose_branch_moved_exits_92_and_a_watch_gates_exactly_its_commit(self):
        """F2: a lane gate asked for an older commit than its branch tip is refused by the host; a pinned gate of master~1 runs that commit
        (the host's HEAD is it), leaves no refs/relay-gate/* and is unaffected by a commit added to master afterwards."""
        self.preinstall()
        write(os.path.join(self.wt, "more.txt"), "more\n")
        git(self.wt, "add", "-A"); git(self.wt, "commit", "-q", "-m", "more")
        older = git(self.wt, "rev-parse", "HEAD~1")      # the branch tip is one commit past it
        with self.assertRaises(relay_gate_ssh.Unavailable) as caught:
            relay_gate_ssh.gate(self.host, self.home, self.wt, older, relay_gate_ssh.QUICK_COMMAND)
        self.assertIn("not the one asked for", str(caught.exception))
        pinned = git(self.main, "rev-parse", "master")      # the recipe commit; master moves on below
        write(os.path.join(self.main, "later.txt"), "later\n")
        git(self.main, "add", "-A"); git(self.main, "commit", "-q", "-m", "later")
        result = relay_gate_ssh.gate(self.host, self.home, self.main, pinned, relay_gate_ssh.QUICK_COMMAND, pinned=True)
        self.assertEqual(result.code, 0)
        self.assertIn("head=" + pinned, read(os.path.join(self.vps.root, "capture.txt")))
        self.assertEqual(git(self.main, "for-each-ref", "refs/relay-gate"), "")

    def test_only_relay_goes_remote(self):
        """A command other than `bin/ci --quick` is not run on the host."""
        with self.assertRaises(relay_gate_ssh.Unavailable):
            relay_gate_ssh.gate(self.host, self.home, self.wt, self.head(), ["bin/ci"])
        self.assertEqual(self.vps.ssh_calls(), [])


class Program(unittest.TestCase):
    def test_the_program_parses_as_python_3_12_and_imports_only_the_standard_library(self):
        import ast
        source = read(os.path.join(ROOT, "lib", "relay_gate_remote.py"))
        tree = ast.parse(source, feature_version=(3, 12))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertTrue(names <= set(sys.stdlib_module_names), sorted(names - set(sys.stdlib_module_names)))


class ProgramRuns(VpsBase):
    """F1, F3 (review of e2e8c23b): the gate program run by hand against the fake podman, standard input an open pipe as under ssh."""

    def start(self, *options):
        tmp = os.path.join(self.tmp, "programtmp")
        os.makedirs(tmp, exist_ok=True)
        bundle = os.path.join(self.tmp, "x.bundle")
        git(self.main, "bundle", "create", bundle, "--all")
        sha = git(self.main, "rev-parse", "master")
        tree = git(self.main, "rev-parse", "master^{tree}")
        version = hashlib.sha256(read(self.program).encode()).hexdigest()
        env = dict(os.environ, HOME=os.path.join(self.vps.root, "home"), TMPDIR=tmp, LANG="C")
        proc = subprocess.Popen([sys.executable, self.program, "gate", version, "refs/heads/master", sha, tree, "master", "600", *options],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        with open(bundle, "rb") as handle:
            data = handle.read()
        proc.stdin.write(b"bundle %d\n" % len(data) + data)
        proc.stdin.flush()
        self.addCleanup(proc.kill)
        self.addCleanup(proc.stdin.close)
        return proc, tmp

    def test_a_normal_end_with_standard_input_still_open_exits_0(self):
        proc, tmp = self.start()
        self.assertEqual(proc.wait(timeout=120), 0)      # a bound against a hang only; Python 3.14 aborted (-6) here
        self.assertEqual(os.listdir(tmp), [])

    def test_an_exception_after_the_watcher_started_is_exit_91_with_an_error_line_and_nothing_left(self):
        """slots=x raises ValueError in int() after the bundle was read and the watcher started: an uncaught exception left by the normal
        interpreter exit, which aborted (-6) on Python 3.14 and skipped the clean-up."""
        proc, tmp = self.start("slots=x")
        self.assertEqual(proc.wait(timeout=120), 91)
        self.assertIn(b"relay-gate-error ValueError", proc.stdout.read())
        self.assertEqual(os.listdir(tmp), [])

    def test_a_cut_during_an_image_build_kills_the_build(self):
        """F3: stdin closes while `podman build` runs (it is in its own session): the build must be gone, not left running without a slot."""
        self.vps.mode({"build_hang": True})
        proc, tmp = self.start()
        pid_file = os.path.join(self.vps.root, "build.pid")
        self.assertTrue(wait_until(lambda: os.path.exists(pid_file) and read(pid_file).strip().isdigit()))
        pid = int(read(pid_file))
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=120), 98)

        def gone():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            return False
        self.assertTrue(wait_until(gone))
        self.assertEqual(os.listdir(tmp), [])


class PassCases(VpsBase):
    """F4, F5 (review of e2e8c23b): plan 5.8 pass cases of the transport, through relay_gate_ssh.gate directly (deciding_host bypassed)."""

    def lane_commit(self, name, text):
        write(os.path.join(self.wt, name), text)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "lane " + name)

    def gate_direct(self, results, key):
        try:
            results[key] = relay_gate_ssh.gate(self.host, self.home, self.wt, self.head(), relay_gate_ssh.QUICK_COMMAND)
        except relay_gate_ssh.Unavailable as exc:
            results[key] = exc

    def test_a_branch_that_changes_the_recipe_is_refused_and_nothing_is_built(self):
        self.preinstall()
        self.lane_commit("container/Containerfile", "FROM y\n")
        with self.assertRaises(relay_gate_ssh.Unavailable) as caught:
            relay_gate_ssh.gate(self.host, self.home, self.wt, self.head(), relay_gate_ssh.QUICK_COMMAND)
        self.assertIn("changes relay's toolchain", str(caught.exception))
        self.assertIn("container/Containerfile", str(caught.exception))
        self.assertNotIn("build", self.vps.podman_calls())

    def test_a_recipe_file_absent_on_both_sides_is_unchanged_and_one_added_by_the_branch_is_refused(self):
        """F5: without deps.toml anywhere the gate runs (git rev-parse would echo `<sha>:deps.toml`, different for each commit)."""
        self.preinstall()
        git(self.main, "rm", "-q", "deps.toml")
        git(self.main, "commit", "-q", "-m", "no deps")
        self.lane_commit("lane.txt", "lane\n")
        git(self.wt, "merge", "-q", "--no-edit", "master")      # a merge commit: the gated sha is not the tip of master
        self.assertNotEqual(self.head(), git(self.main, "rev-parse", "master"))
        result = relay_gate_ssh.gate(self.host, self.home, self.wt, self.head(), relay_gate_ssh.QUICK_COMMAND)
        self.assertEqual(result.code, 0)
        self.lane_commit("deps.toml", "[deps]\n")
        with self.assertRaises(relay_gate_ssh.Unavailable) as caught:
            relay_gate_ssh.gate(self.host, self.home, self.wt, self.head(), relay_gate_ssh.QUICK_COMMAND)
        self.assertIn("deps.toml", str(caught.exception))

    def test_two_gates_started_together_on_one_slot_run_one_and_the_other_is_busy(self):
        self.preinstall()
        self.use_host(slots=1, remote_wait_s=0)
        os.makedirs(os.path.join(self.vps.root, "state", "images"))
        write(os.path.join(self.vps.root, "state", "images", "relay-gate:" + self.tag()), "")      # the image exists: no build in this test
        self.vps.mode({"ci_sleep": 3})      # the winner holds the slot far longer than the loser needs to ask
        results = {}
        threads = [threading.Thread(target=self.gate_direct, args=(results, k)) for k in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # exactly one result and one busy: two results would mean two containers on a one-slot host
        done = sorted(type(r).__name__ for r in results.values())
        self.assertEqual(done, ["RemoteResult", "Unavailable"], results)
        loser = next(r for r in results.values() if isinstance(r, relay_gate_ssh.Unavailable))
        self.assertEqual(loser.outcome, "busy")

    def test_two_gates_needing_one_missing_image_start_one_build(self):
        self.preinstall()
        self.vps.mode({"build_sleep": 3})
        results = {}
        first = threading.Thread(target=self.gate_direct, args=(results, "a"))
        first.start()
        self.assertTrue(wait_until(lambda: "build" in self.vps.podman_calls()))      # the first gate holds the build lock now
        self.gate_direct(results, "b")
        first.join()
        self.assertIn("is building image relay-gate:" + self.tag(), str(results["b"]))
        self.assertEqual(self.vps.podman_calls().count("build"), 1)

    def test_a_traceback_on_the_host_after_the_running_line_is_no_result(self):
        self.preinstall()
        self.vps.mode({"create_garbage": True})
        code, log, err = self.go_err()
        self.assertIn("could not run the gate", err)
        self.assertFalse(log.endswith(".remote.gate.log"))      # the Mac ran it
        self.assertNotIn("Traceback", err)
        self.assertEqual(relay_gate_ssh.read_events(self.wt, HOST)[-1]["outcome"], "could-not-run")
        self.assertTrue(wait_until(lambda: self.vps.containers() == []))

    go_err = Transport.go_err


class CycleForm(VpsBase):
    """F1: the cycle's `relay gate -C <wt> -- --quick` is a quick gate; `--paid` and other arguments are not."""

    def run_gate(self, *args):
        done = subprocess.run([sys.executable, RELAY, "gate", "-C", self.wt, *args], capture_output=True, text=True, env=self.env)
        return done.returncode, done.stdout, done.stderr

    def commit(self, name):
        write(os.path.join(self.wt, name), name + "\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", name)

    def test_both_quick_forms_make_one_ssh_call_and_the_others_none(self):
        self.preinstall()
        newest = git(self.main, "rev-parse", "HEAD")
        folder = os.path.join(self.main, ".git", "relay-land", "linux")
        write(os.path.join(folder, newest + ".remote.gate.log"), "head %s\ncmd bin/ci --quick\nwait 0.0\nhost x\nok\nexit 0\n" % newest)
        counts = []
        for i, args in enumerate([(), ("--", "--quick"), ("--paid",), ("--", "--other")]):
            self.commit("c%d" % i)
            before = len(self.vps.ssh_calls())
            code, out, err = self.run_gate(*args)
            counts.append(len(self.vps.ssh_calls()) - before)
            self.assertEqual(code, 0, err)
        self.assertEqual(counts, [1, 1, 0, 0])

    def test_without_a_linux_result_of_the_default_branch_a_lane_gates_on_the_mac(self):
        self.preinstall()
        self.commit("c")
        code, out, err = self.run_gate()
        self.assertEqual(self.vps.ssh_calls(), [])
        self.assertIn("gate: %s has not yet gated the default branch (run relay gate --watch-default); this gate runs on this Mac" % HOST, err)


if __name__ == "__main__":
    unittest.main()
