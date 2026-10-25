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
        self.assertEqual(self.read(), {"model": "opus", "effortLevel": "medium", "theme": "auto", "env": {"CLAUDE_CODE_RETRY_WATCHDOG": "1"}})
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

    # F1: Claude Code reads modelSettings.<model>.effortLevel first; the top-level key is ignored for newer models.
    REAL = {"model": "opus", "theme": "auto", "modelSettings": {
        "claude-opus-5-5": {"effortLevel": "high"}, "claude-sonnet-5": {"autoCompactWindow": 5}}}

    def test_f1_effort_lands_in_the_models_modelsettings_entry(self):
        self.put(json.loads(json.dumps(self.REAL)))
        relay_rules.sync(self.profile, only={"settings"})
        got = self.read()
        self.assertEqual(got["modelSettings"]["claude-opus-5-5"]["effortLevel"], "medium")
        self.assertEqual(got["modelSettings"]["claude-sonnet-5"], {"autoCompactWindow": 5})
        self.assertEqual(got["theme"], "auto")
        self.assertEqual(relay_rules.sync(self.profile, only={"settings"})[0][2], "unchanged")

    def test_f1_dry_writes_nothing_and_names_the_entry(self):
        self.put(json.loads(json.dumps(self.REAL)))
        res = relay_rules.sync(self.profile, only={"settings"}, dry=True)
        self.assertEqual(self.read(), self.REAL)
        self.assertIn("modelSettings.claude-opus-5-5.effortLevel 'high' -> 'medium'", res[0][2])

    def test_f1_doctor_flags_the_modelsettings_entry_even_if_top_level_matches(self):
        data = json.loads(json.dumps(self.REAL))
        data["effortLevel"] = "medium"
        self.put(data)
        bad = [n for n, good, _ in relay_setup.doctor(None, profile=self.profile) if not good and "modelSettings" in n]
        self.assertEqual(len(bad), 1)

    def test_f1_no_modelsettings_still_sets_top_level(self):
        self.put({})
        relay_rules.sync(self.profile, only={"settings"})
        self.assertEqual(self.read(), {"model": "opus", "effortLevel": "medium", "env": {"CLAUDE_CODE_RETRY_WATCHDOG": "1"}})

    # F2: max is session-only.
    def test_f2_max_is_not_written_and_doctor_flags_it(self):
        profile = {"session": {"model": "opus", "effort": "max"}}
        self.put({"effortLevel": "high"})
        res = relay_rules.sync(profile, only={"settings"})
        self.assertIn("session-only", res[0][2])
        got = self.read()
        self.assertEqual(got["effortLevel"], "high")   # not overwritten with max
        self.assertEqual(got["model"], "opus")
        bad = [n for n, good, _ in relay_setup.doctor(None, profile=profile) if not good and n.startswith("effortLevel")]
        self.assertEqual(len(bad), 1)

    def test_f2_xhigh_is_written(self):
        self.put({})
        relay_rules.sync({"session": {"model": "opus", "effort": "xhigh"}}, only={"settings"})
        self.assertEqual(self.read()["effortLevel"], "xhigh")

    # F3: a malformed settings.json is refused, not rewritten.
    def test_f3_malformed_file_is_refused_untouched(self):
        bad = '{"enabledPlugins": {"core@relay": true}, "model": "sonnet",}'
        with open(self.path, "w") as handle:
            handle.write(bad)
        for dry, prefix in ((False, "refused: "), (True, "would refuse: ")):
            res = relay_rules.sync(self.profile, only={"settings"}, dry=dry)
            self.assertTrue(res[0][2].startswith(prefix), res[0][2])
            self.assertIn("not valid JSON", res[0][2])
        self.assertEqual(open(self.path).read(), bad)
        self.assertEqual(os.listdir(self.tmp), ["settings.json"])   # no .bak

    def test_f3_missing_file_is_created(self):
        relay_rules.sync(self.profile, only={"settings"})
        self.assertEqual(self.read(), {"model": "opus", "effortLevel": "medium", "env": {"CLAUDE_CODE_RETRY_WATCHDOG": "1"}})


if __name__ == "__main__":
    unittest.main()
