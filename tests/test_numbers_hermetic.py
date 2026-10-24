"""capture's fallback window (no usable index) is counted from the time capture is given, not from the machine's
clock, and nothing is read from the real HOME. The moment used is years before any real run, so a window taken
from the real clock would miss the day's lines."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))


class NumbersHermetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="relay-hermetic-")
        self.saved = {k: os.environ.get(k) for k in ("HOME", "RELAY_HOME", "CLAUDE_CONFIG_DIR")}
        os.makedirs(os.path.join(self.tmp, "empty-home"))
        os.environ["HOME"] = os.path.join(self.tmp, "empty-home")
        os.environ["RELAY_HOME"] = os.path.join(self.tmp, "relay-home")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, "claude")
        os.makedirs(os.environ["CLAUDE_CONFIG_DIR"])
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]

    def tearDown(self):
        import shutil
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fallback_window_follows_the_given_time_not_the_clock(self):
        import relay_ledger
        models = {"claude-opus-5-5": {"inputTokens": 1, "outputTokens": 5, "costUSD": 1.0}}
        with open(os.path.join(os.environ["CLAUDE_CONFIG_DIR"], ".claude.json"), "w") as handle:
            json.dump({"projects": {"/p": {"lastSessionId": "s1", "lastModelUsage": models}}}, handle)
        # 2020-03-04: far from the real date. First write, then lose the index: the ledger line of 09:00 is the
        # only proof the total was recorded, and it is 3 h old at 12:00, well inside the 3-day window.
        self.assertEqual(relay_ledger.capture("2020-03-04T09:00:00Z"), ["s1"])
        os.remove(os.path.join(os.environ["RELAY_HOME"], "ledger", "usage-index.json"))
        self.assertEqual(relay_ledger.capture("2020-03-04T12:00:00Z"), [])


if __name__ == "__main__":
    unittest.main()
