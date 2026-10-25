"""relay sync writes the profile's [session] model and effort into the user settings (Q1)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_rules  # noqa: E402
import relay_setup  # noqa: E402


ENV_KEYS = ("CLAUDE_CONFIG_DIR", "RELAY_SKIP_PAID_DUE")


class SessionProfile(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ENV_KEYS}
        self.tmp = tempfile.mkdtemp(prefix="relay-session-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp
        os.environ["RELAY_SKIP_PAID_DUE"] = "1"   # no paid-run record in a test
        self.path = os.path.join(self.tmp, "settings.json")
        self.profile = {"session": {"model": "opus", "effort": "medium"}}

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def put(self, data):
        with open(self.path, "w") as handle:
            json.dump(data, handle)

    def read(self):
        with open(self.path) as handle:
            return json.load(handle)

    def test_sync_writes_model_and_effort_and_leaves_other_keys(self):
        # The settings say effort high; the profile says medium: after sync it is medium, theme stays.
        self.put({"model": "sonnet", "effortLevel": "high", "theme": "auto"})
        results = relay_rules.sync(self.profile, only={"settings"})
        self.assertEqual(self.read(), {"model": "opus", "effortLevel": "medium", "theme": "auto"})
        self.assertEqual([r[0] for r in results], ["settings"])

    def test_dry_names_the_change_and_writes_nothing(self):
        self.put({"effortLevel": "high"})
        results = relay_rules.sync(self.profile, only={"settings"}, dry=True)
        self.assertEqual(self.read(), {"effortLevel": "high"})
        self.assertIn("effortLevel 'high' -> 'medium'", results[0][2])
        self.assertIn("model None -> 'opus'", results[0][2])

    def test_a_second_sync_is_unchanged(self):
        self.put({})
        relay_rules.sync(self.profile, only={"settings"})
        again = relay_rules.sync(self.profile, only={"settings"})
        self.assertEqual(again[0][2], "unchanged")

    def test_doctor_reports_a_mismatch_then_passes(self):
        self.put({"model": "opus", "effortLevel": "high"})
        bad = [n for n, good, _ in relay_setup.doctor(None, profile=self.profile) if not good and n.startswith("effortLevel")]
        self.assertEqual(len(bad), 1)
        relay_rules.sync(self.profile, only={"settings"})
        bad = [n for n, good, _ in relay_setup.doctor(None, profile=self.profile) if not good and n.startswith(("effortLevel", "model"))]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
