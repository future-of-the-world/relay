"""lib/relay_tokens.py: the machine-wide pool of test tokens. Free. Every pool is a temporary RELAY_HOME."""
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.path.insert(0, HERE)
import relay_tokens as rt  # noqa: E402


def st(home, slots=2, cpus=12):
    return rt.settings(home, slots, cpus)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.makedirs(rt.pool_dir(self.home))
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        with open(os.path.join(rt.pool_dir(self.home), name), "w") as handle:
            handle.write(text)


class SettingsTest(Base):
    def test_defaults(self):
        # 12 cpus, 2 slots, 4 per gate: 8 gate tokens, shared 12-8 = 4
        s = st(self.home)
        self.assertEqual((s.total, s.per_gate, s.gate_tokens, s.notes), (12, 4, 8, ()))

    def test_the_default_share_shrinks_with_the_machine(self):
        # F5: agents' test runs keep at least 2 shared tokens. 4 cpus, 1 slot: share (4-2)//1 = 2, gate 2, shared 4-2 = 2
        # (without the fix: share 4, count raised to R+1 = 5, shared 1). 6 cpus, 2 slots: share (6-2)//2 = 2, gate 4, shared 2.
        # 6 cpus, 1 slot: (6-2)//1 = 4 stays the default 4, shared 2.
        for cpus, slots, per_gate in ((4, 1, 2), (6, 2, 2), (6, 1, 4)):
            s = st(self.home, slots, cpus)
            self.assertEqual((s.per_gate, s.total - s.gate_tokens), (per_gate, 2), (cpus, slots))
        self.write("per-gate", "3")        # the settings file still wins, inside its bounds
        self.assertEqual(st(self.home, 1, 4).per_gate, 3)

    def test_files_set_the_sizes(self):
        self.write("count", "20\n")
        self.write("per-gate", "3\n")
        s = st(self.home)
        self.assertEqual((s.total, s.per_gate, s.gate_tokens), (20, 3, 6))

    def test_out_of_bounds_brought_in_with_a_note(self):
        self.write("per-gate", "1")      # below 2
        self.write("count", "3")         # below R + 1 = 2 gates x 2 + 1 = 5
        s = st(self.home)
        self.assertEqual(s.per_gate, 2)
        self.assertEqual(s.total, 5)     # R + 1 = 2 gates x 2 + 1
        self.assertEqual(len(s.notes), 2)
        self.assertTrue(all(os.path.join("test-tokens", n) in note for n, note in zip(("per-gate", "count"), s.notes)))

    def test_upper_bounds(self):
        self.write("count", "1000")
        self.write("per-gate", "99")
        s = st(self.home)
        self.assertEqual(s.per_gate, 8)          # 2 x DEFAULT_JOBS 4
        self.assertEqual(s.total, 48)            # 4 x 12 cpus

    def test_the_split_does_not_depend_on_the_callers_jobs(self):
        # F1: the gate/shared split is one fact for the machine: a process with RELAY_TEST_JOBS=1 sees the same 8 gate tokens as one with 4
        for jobs in ("1", "4", "16"):
            self.assertEqual(rt.settings_for_run({"RELAY_TEST_JOBS": jobs}, self.home).gate_tokens, rt.settings_for_run({}, self.home).gate_tokens)
        self.write("per-gate", "99")
        self.assertEqual(rt.settings_for_run({"RELAY_TEST_JOBS": "1"}, self.home).per_gate, 8)      # clamped to 2 x 4, the same for everyone
        self.write("per-gate", "1")
        self.assertEqual(rt.settings_for_run({"RELAY_TEST_JOBS": "1"}, self.home).per_gate, 2)

    def test_a_run_with_one_job_waits_for_a_shared_token_and_leaves_gate_tokens(self):
        # F1: 12 cpus, 2 slots: gate 0..7, shared 8..11. All shared held, gate A holds 0..3: a RELAY_TEST_JOBS=1 run must wait, not take 4
        os.makedirs(os.path.join(self.home, "gate-slots"))
        with open(os.path.join(self.home, "gate-slots", "count"), "w") as handle:
            handle.write("2")
        self.write("count", "12")
        s = rt.settings(self.home, 2, 12)
        shared = [rt.take_base(self.home, s, rt.SHARED, 1)[0] for _ in range(4)]
        gate_a, _ = rt.take_base(self.home, s, rt.GATE, 4)
        out = {}
        thread = threading.Thread(target=lambda: out.update(r=rt.acquire_run_base({"RELAY_HOME": self.home, "RELAY_TEST_JOBS": "1"})), daemon=True)
        thread.start()
        waiting = os.path.join(rt.pool_dir(self.home), "waiting")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (os.path.isdir(waiting) and os.listdir(waiting)):
            time.sleep(0.05)
        self.assertTrue(os.listdir(waiting))      # a shared waiter file: it waits
        self.assertNotIn("r", out)
        gate_b, waited = rt.take_base(self.home, s, rt.GATE, 4)      # gate B gets 4..7 at once
        self.assertEqual(len(gate_b), 4)
        self.assertLess(waited, 1)
        shared[0].release()
        thread.join(20)
        self.assertEqual(len(out["r"].held), 1)
        out["r"].held.release()
        for held in shared[1:] + [gate_a, gate_b]:
            held.release()

    def test_not_a_number_uses_default_with_note(self):
        self.write("per-gate", "many")
        s = st(self.home)
        self.assertEqual(s.per_gate, 4)
        self.assertEqual(len(s.notes), 1)

    def test_cgroup_quota(self):
        # quota 200000 / period 100000 = 2 cpus, below the affinity 6; "max" leaves the affinity
        self.assertEqual(rt.cpus_from(6, "200000 100000"), 2)
        self.assertEqual(rt.cpus_from(6, "max 100000"), 6)


class PoolTest(Base):
    def test_no_more_than_total_tokens_are_held(self):
        s = st(self.home)
        got = []
        while True:
            token = rt.try_extra(self.home, s)
            if token is None:
                break
            got.append(token)
        self.assertEqual(len(got), 12)           # gate tokens too: an extra may use a free gate token
        for token in got:
            token.release()

    def test_gate_base_not_blocked_by_shared_exhausted(self):
        s = st(self.home)
        shared = [rt.take_base(self.home, s, rt.SHARED, 1)[0] for _ in range(4)]   # all 4 shared tokens
        gate, waited = rt.take_base(self.home, s, rt.GATE, 4)
        self.assertEqual(len(gate), 4)
        self.assertLess(waited, 2)
        for held in shared + [gate]:
            held.release()

    def test_hand_run_waits_for_a_shared_token_and_says_so(self):
        s = st(self.home)
        shared = [rt.take_base(self.home, s, rt.SHARED, 1)[0] for _ in range(4)]
        lines = []
        out = {}
        thread = threading.Thread(target=lambda: out.update(r=rt.take_base(self.home, s, rt.SHARED, 1, lines.append)))
        thread.start()
        deadline = time.monotonic() + 20
        while not lines and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(lines and "test-tokens/count" in lines[0])
        self.assertNotIn("r", out)               # still waiting
        shared[0].release()
        thread.join(20)
        self.assertEqual(len(out["r"][0]), 1)
        out["r"][0].release()
        for held in shared[1:]:
            held.release()

    def test_waiter_check_blocks_extras_of_its_kind(self):
        s = st(self.home)
        os.makedirs(os.path.join(rt.pool_dir(self.home), "waiting"))
        marker = os.path.join(rt.pool_dir(self.home), "waiting", "shared-%d-0" % os.getpid())
        open(marker, "w").close()
        got = []
        while True:
            token = rt.try_extra(self.home, s, rt.SHARED)
            if token is None:
                break
            got.append(token)
        # the SHARED kind has a live waiter: the extras take only the 8 gate tokens
        self.assertEqual(len(got), 8)
        for token in got:
            token.release()
        os.unlink(marker)
        again = rt.try_extra(self.home, s, rt.SHARED)
        self.assertIsNotNone(again)              # the waiter is gone: SHARED is free again
        again.release()

    def test_a_released_token_reaches_a_base_waiter_not_an_extra_loop(self):
        # F2: 2 shared tokens (count = R + 2 with 1 slot x 2 = 4). A holds one as base and takes the other as an extra again and
        # again; B waits for a base while A holds the base and the extra. A's next extra must be refused as B waits, so B gets it.
        self.write("per-gate", "2")
        self.write("count", "4")
        s = rt.settings(self.home, 1, 12)
        gate_held, _ = rt.take_base(self.home, s, rt.GATE, 2)      # the gate tokens are busy, so an extra can only be a shared one
        base_a, _ = rt.take_base(self.home, s, rt.SHARED, 1)
        extra = rt.try_extra(self.home, s, rt.SHARED)
        self.assertIsNotNone(extra)
        out = {}
        thread = threading.Thread(target=lambda: out.update(r=rt.take_base(self.home, s, rt.SHARED, 1)))
        thread.start()
        waiting = os.path.join(rt.pool_dir(self.home), "waiting")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (os.path.isdir(waiting) and os.listdir(waiting)):
            time.sleep(0.05)
        names = os.listdir(waiting)
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("shared-%d-" % os.getpid()), names)      # take_base wrote its waiter file
        extra.release()
        self.assertIsNone(rt.try_extra(self.home, s, rt.SHARED))      # the waiter wins over the extra loop of A
        thread.join(20)
        self.assertEqual(len(out["r"][0]), 1)      # B got the released token while A still holds its base
        self.assertEqual(os.listdir(waiting), [])      # and its waiter file is gone
        out["r"][0].release()
        base_a.release()
        gate_held.release()

    def test_dead_waiter_file_is_ignored(self):
        s = st(self.home)
        os.makedirs(os.path.join(rt.pool_dir(self.home), "waiting"))
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        open(os.path.join(rt.pool_dir(self.home), "waiting", "shared-%d-0" % proc.pid), "w").close()
        token = rt.try_extra(self.home, s, rt.SHARED)
        self.assertIsNotNone(token)
        token.release()

    def test_a_run_grows_back_when_a_token_comes_free(self):
        s = st(self.home)
        everything = [rt.try_extra(self.home, s) for _ in range(12)]
        self.assertIsNone(rt.try_extra(self.home, s))
        everything[5].release()
        regained = rt.try_extra(self.home, s)
        self.assertIsNotNone(regained)
        regained.release()
        for held in everything:
            held.release()

    def test_a_killed_holder_frees_its_tokens(self):
        code = ("import sys,time; sys.path.insert(0, %r); import relay_tokens as rt; "
                "s=rt.settings(%r, 2, 12); h=rt.take_base(%r, s, rt.GATE, 8)[0]; print('held', flush=True); time.sleep(60)"
                % (os.path.join(os.path.dirname(HERE), "lib"), self.home, self.home))
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "held")
            s = st(self.home)
            gate_free = [rt.try_extra(self.home, s, rt.GATE) for _ in range(12)]
            self.assertEqual(sum(1 for t in gate_free if t is not None), 4)     # 12 - 8 held by the child
            for t in gate_free:
                if t is not None:
                    t.release()
            proc.send_signal(signal.SIGKILL)
            proc.wait()
            token, waited = rt.take_base(self.home, s, rt.GATE, 8)
            self.assertEqual(len(token), 8)
            self.assertLess(waited, 2)
            token.release()
        finally:
            proc.kill()
            proc.wait()
            proc.stdout.close()


class NestedTest(Base):
    def test_a_passed_base_is_not_taken_twice(self):
        # one shared token in the whole pool (count = R+1 with 1 slot x 2): the holder has it; its child must run without waiting
        self.write("per-gate", "2")
        self.write("count", "3")
        s = rt.settings(self.home, 1, 12)
        held, _ = rt.take_base(self.home, s, rt.SHARED, 1)
        env = {"RELAY_HOME": self.home, rt.ENV_HOLD: rt.hold_value(1, self.home)}
        base = rt.acquire_run_base(env)
        self.assertTrue(base.passed)
        self.assertEqual((base.workers, len(base.held)), (1, 0))
        held.release()

    def test_a_value_for_another_pool_is_ignored(self):
        with tempfile.TemporaryDirectory() as other:
            env = {"RELAY_HOME": self.home, rt.ENV_HOLD: rt.hold_value(3, other)}
            self.assertEqual(rt.passed_down(env, self.home), 0)
            base = rt.acquire_run_base(env)
            self.assertFalse(base.passed)
            self.assertEqual(len(base.held), 1)
            base.held.release()

    def test_the_slot_count_is_read_without_importing_relay_gate(self):
        # F7: a broken lib module (relay_gate imports a chain of them) must not stop a test run: make "import relay_gate" fail
        os.makedirs(os.path.join(self.home, "gate-slots"))
        with open(os.path.join(self.home, "gate-slots", "count"), "w") as handle:
            handle.write("3")
        code = ("import sys; sys.modules['relay_gate'] = None; sys.path.insert(0, %r); import relay_tokens as rt; "
                "print(rt.settings_for_run({}, %r).slots)" % (os.path.join(os.path.dirname(HERE), "lib"), self.home))
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout.strip()), (0, "3"), run.stderr)

    def test_a_bad_slot_count_gives_the_default(self):
        os.makedirs(os.path.join(self.home, "gate-slots"))
        for text in ("0", "x", "-2", ""):
            with open(os.path.join(self.home, "gate-slots", "count"), "w") as handle:
                handle.write(text)
            self.assertEqual(rt.read_slots(self.home), rt.default_slots(), text)

    def test_malformed_value_is_ignored(self):
        for bad in ("", "x@/tmp", "0@/tmp", "3", "-1@/tmp"):
            self.assertEqual(rt.passed_down({rt.ENV_HOLD: bad}, self.home), 0, bad)

    def test_jobs_from(self):
        self.assertEqual(rt.jobs_from({"RELAY_TEST_JOBS": "6"}), 6)
        self.assertEqual(rt.jobs_from({"RELAY_TEST_JOBS": "0"}), 4)
        self.assertEqual(rt.jobs_from({}), 4)


class RunnerPoolTest(unittest.TestCase):
    """tests/run_unittest.py leaves nothing outside its temporary folder."""
    RUNNER = os.path.join(HERE, "run_unittest.py")
    ONE = "tests.test_relay_tokens.SettingsTest.test_defaults"

    def run_runner(self, env_extra):
        outer = tempfile.TemporaryDirectory()
        self.addCleanup(outer.cleanup)
        home = os.path.join(outer.name, "home")
        os.makedirs(home)
        env = {k: v for k, v in os.environ.items() if k not in ("RELAY_HOME", rt.ENV_HOLD)}
        env["HOME"] = home
        env.update(env_extra(outer.name))
        done = subprocess.run([sys.executable, self.RUNNER, self.ONE], cwd=os.path.dirname(HERE), env=env,
                              capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr)
        return outer.name, home

    def test_no_pool_left_in_home(self):
        # No gate above: the pool is a temporary folder, so an empty HOME (default RELAY_HOME is ~/.relay) stays empty.
        _, home = self.run_runner(lambda outer: {})
        self.assertEqual(os.listdir(home), [])

    def test_no_pool_left_in_relay_home(self):
        # RELAY_HOME pointing at an empty folder stays empty too.
        def extra(outer):
            os.makedirs(os.path.join(outer, "rh"))
            return {"RELAY_HOME": os.path.join(outer, "rh")}
        outer, home = self.run_runner(extra)
        self.assertEqual(os.listdir(os.path.join(outer, "rh")), [])
        self.assertEqual(os.listdir(home), [])

    def test_a_gates_pool_is_shared(self):
        # A holder passed RELAY_TEST_TOKENS for the pool at RELAY_HOME: the runner keeps that pool (takes no token of its own,
        # so the pool folder holds only what the holder made) and does not swap in a temporary one.
        def extra(outer):
            rh = os.path.join(outer, "rh")
            os.makedirs(rt.pool_dir(rh))
            return {"RELAY_HOME": rh, rt.ENV_HOLD: rt.hold_value(1, rh)}
        outer, _ = self.run_runner(extra)
        self.assertEqual(os.listdir(rt.pool_dir(os.path.join(outer, "rh"))), [])

    def test_own_pool_environ(self):
        import run_unittest
        with tempfile.TemporaryDirectory() as tmp:
            held = {"RELAY_HOME": tmp, rt.ENV_HOLD: rt.hold_value(2, tmp)}
            self.assertEqual(run_unittest.own_pool_home(held), tmp)
            other = run_unittest.own_pool_home({"RELAY_HOME": tmp})
            self.assertNotEqual(os.path.realpath(other), os.path.realpath(tmp))
            self.assertTrue(os.path.realpath(other).startswith(os.path.realpath(tempfile.gettempdir())))


if __name__ == "__main__":
    unittest.main()
