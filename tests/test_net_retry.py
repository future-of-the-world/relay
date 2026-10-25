"""relay sync puts CLAUDE_CODE_RETRY_WATCHDOG=1 into the user settings env (Q1)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import relay_rules  # noqa: E402
import relay_setup  # noqa: E402

KEY = "CLAUDE_CODE_RETRY_WATCHDOG"


class NetRetry(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "RELAY_SKIP_PAID_DUE")}
        self.tmp = tempfile.mkdtemp(prefix="relay-net-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp
        os.environ["RELAY_SKIP_PAID_DUE"] = "1"
        self.path = os.path.join(self.tmp, "settings.json")
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def put(self, data):
        with open(self.path, "w") as handle:
            json.dump(data, handle)

    def read(self):
        with open(self.path) as handle:
            return json.load(handle)

    def failing_doctor(self):
        return [n for n, good, _ in relay_setup.doctor(None, profile={}) if not good and KEY in n]

    def test_q1_sync_adds_the_watchdog_leaves_other_keys_and_is_idempotent(self):
        # Env holds the owner's FOO and the settings a theme: after sync both stay and the watchdog is "1".
        self.put({"theme": "auto", "env": {"FOO": "bar"}})
        relay_rules.sync({}, only={"settings"})
        self.assertEqual(self.read(), {"theme": "auto", "env": {"FOO": "bar", KEY: "1"}})
        again = relay_rules.sync({}, only={"settings"})
        self.assertEqual(again[0][2], "unchanged")

    def test_q1_a_key_the_owner_set_is_left_alone(self):
        self.put({"env": {KEY: "0"}})
        relay_rules.sync({}, only={"settings"})
        self.assertEqual(self.read(), {"env": {KEY: "0"}})
        self.assertEqual(self.failing_doctor(), [])

    def test_q1_doctor_flags_it_when_absent_then_passes(self):
        self.put({})
        self.assertEqual(len(self.failing_doctor()), 1)
        relay_rules.sync({}, only={"settings"})
        self.assertEqual(self.failing_doctor(), [])

    def test_q1_dry_writes_nothing(self):
        self.put({})
        relay_rules.sync({}, only={"settings"}, dry=True)
        self.assertEqual(self.read(), {})


if __name__ == "__main__":
    unittest.main()
