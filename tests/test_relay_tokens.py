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
import relay_tokens as rt  # noqa: E402


def st(home, slots=2, cpus=12):
    return rt.settings(home, slots, 4, cpus)


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
        self.assertEqual(s.per_gate, 8)          # 2 x RELAY_TEST_JOBS 4
        self.assertEqual(s.total, 48)            # 4 x 12 cpus

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
                "s=rt.settings(%r, 2, 4, 12); h=rt.take_base(%r, s, rt.GATE, 8)[0]; print('held', flush=True); time.sleep(60)"
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
        s = rt.settings(self.home, 1, 4, 12)
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

    def test_malformed_value_is_ignored(self):
        for bad in ("", "x@/tmp", "0@/tmp", "3", "-1@/tmp"):
            self.assertEqual(rt.passed_down({rt.ENV_HOLD: bad}, self.home), 0, bad)

    def test_jobs_from(self):
        self.assertEqual(rt.jobs_from({"RELAY_TEST_JOBS": "6"}), 6)
        self.assertEqual(rt.jobs_from({"RELAY_TEST_JOBS": "0"}), 4)
        self.assertEqual(rt.jobs_from({}), 4)


if __name__ == "__main__":
    unittest.main()
