"""relay_kit: the one checking parser of .claude/kit.toml, its env overrides, and what relay doctor and the gate say about them."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import ROOT  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_kit  # noqa: E402


class KitSchema(unittest.TestCase):
    def test_unknown_key_in_observe_is_named(self) -> None:
        kit = relay_kit.parse("[observe]\nenabld = true\nlog_prompts = false\n")
        self.assertEqual([p.where for p in kit.problems], [".claude/kit.toml [observe] enabld"])

    def test_observe_enabled_has_no_effect_and_is_reported(self) -> None:
        # [observe] enabled is read by no code (item, 27 Oct): the schema drops it, so the line is reported
        kit = relay_kit.parse("[observe]\nenabled = true\n")
        self.assertEqual(len(kit.problems), 1)
        self.assertIn("[observe] enabled", kit.problems[0].line())
        self.assertIn("has no effect", kit.problems[0].line())
        self.assertIn("remove the line", kit.problems[0].line())

    def test_unknown_section_is_reported(self) -> None:
        kit = relay_kit.parse('[delegat]\ntyped_only = false\n')
        self.assertEqual([p.where for p in kit.problems], [".claude/kit.toml [delegat]"])

    def test_wrong_type_names_key_and_uses_the_strict_default(self) -> None:
        kit = relay_kit.parse('[delegate]\ntyped_only = "false"\nbuild_tier_opus = "denny"\n')
        self.assertIs(kit.get("delegate", "typed_only"), True)   # a text "false" could be a typo of either word: the strict default
        self.assertEqual(kit.get("delegate", "build_tier_opus"), "escalate")
        self.assertEqual(sorted(p.where.split()[-1] for p in kit.problems), ["build_tier_opus", "typed_only"])

    def test_syntax_error_is_broken_and_defaults_apply(self) -> None:
        kit = relay_kit.parse('[delegate\nbuild_tier_opus = "deny"\n')
        self.assertIsNotNone(kit.broken)
        self.assertIn(".claude/kit.toml", kit.broken.line())
        self.assertEqual(kit.get("delegate", "build_tier_opus"), "escalate")

    def test_section_that_is_not_a_table_raises_nothing(self) -> None:
        for text in ('delegate = "x"\n', '[[delegate]]\ntyped_only = false\n'):
            kit = relay_kit.parse(text)
            self.assertIs(kit.get("delegate", "typed_only"), True, text)
            self.assertEqual(len(kit.problems), 1, text)
            self.assertIn("[delegate]", kit.problems[0].where)

    def test_out_of_range_numbers_clamp_or_default_per_key(self) -> None:
        kit = relay_kit.parse("[land]\nland_tries = 9\n[front]\nlanes_line_items = 99\nfeature_lanes = \"3\"\n")
        self.assertEqual(kit.get("land", "land_tries"), 3)           # clamped to the top of 1..3
        self.assertEqual(kit.get("front", "lanes_line_items"), 3)    # outside 0..10: the default
        self.assertEqual(kit.get("front", "feature_lanes"), 0)       # text: the default
        self.assertEqual(len(kit.problems), 3)

    def test_load_parses_once_per_file_and_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "kit.toml"), "w") as handle:
                handle.write("[observe]\nlog_prompts = true\n")
            self.assertIs(relay_kit.load(root), relay_kit.load(root))

    def test_missing_file_is_defaults_without_problems(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            kit = relay_kit.load(root)
            self.assertEqual((kit.problems, kit.broken), ((), None))

    def test_relay_own_kit_toml_has_no_problems(self) -> None:
        self.assertEqual([p.line() for p in relay_kit.load(ROOT).problems], [])

    def test_kartoteka_shaped_file_has_no_problems(self) -> None:
        with open(os.path.join(ROOT, "plugins", "relay", "tests", "profiles", "kartoteka.toml"), encoding="utf-8") as handle:
            self.assertEqual([p.line() for p in relay_kit.parse(handle.read()).problems], [])

    def test_env_booleans_accept_only_true_or_false(self) -> None:
        spec = relay_kit.SCHEMA["delegate"]["typed_only"]
        self.assertEqual(relay_kit.env_value("RELAY_DELEGATE_TYPED_ONLY", spec, {"RELAY_DELEGATE_TYPED_ONLY": "FALSE"}), (False, None))
        value, problem = relay_kit.env_value("RELAY_DELEGATE_TYPED_ONLY", spec, {"RELAY_DELEGATE_TYPED_ONLY": "1"})
        self.assertIs(value, True)   # "1" is not a word the guard knows: strict default, and a problem naming the variable
        self.assertIn("RELAY_DELEGATE_TYPED_ONLY", problem.line())

    def test_ctx_env_must_be_a_whole_number_of_at_least_1000(self) -> None:
        self.assertEqual(relay_kit.ctx_value("RELAY_CTX_STEP", {"RELAY_CTX_STEP": "5000"}), (5000, None))
        for bad in ("abc", "999", ""):
            value, problem = relay_kit.ctx_value("RELAY_CTX_STEP", {"RELAY_CTX_STEP": bad})
            self.assertEqual(value, 30000, bad)
            self.assertIn("RELAY_CTX_STEP", problem.line())

    def test_unknown_env_name_with_a_relay_prefix_is_a_problem(self) -> None:
        found = relay_kit.env_problems({"RELAY_DELEGATE_TYPED_ONLLY": "true", "RELAY_HOME": "/x"})
        self.assertEqual([p.where for p in found], ["env RELAY_DELEGATE_TYPED_ONLLY"])

    def test_setup_template_parses_clean(self) -> None:
        import relay_setup
        for ui in (True, False):
            text = relay_setup.bindings_text({"name": "p", "default_branch": "main", "ui": ui, "stack": "go"}, "none")
            self.assertEqual([p.line() for p in relay_kit.parse(text).problems], [], ui)

    def test_ask_reminder_keys_are_known_and_bounded(self) -> None:
        # documented in ask_waiting.py: days 1..30, lines 1..20, clamped
        self.assertEqual(relay_kit.parse("[front]\nask_reminder_days = 10\nask_reminder_lines = 3\n").problems, ())
        self.assertEqual(len(relay_kit.parse('[front]\nask_reminder_days = "x"\n').problems), 1)
        kit = relay_kit.parse("[front]\nask_reminder_days = 99\n")
        self.assertEqual(kit.get("front", "ask_reminder_days"), 30)

    def test_wave_min_above_six_is_a_problem(self) -> None:
        # relay_rules.wave_min_of refuses above 6
        kit = relay_kit.parse("[rules]\nwave_min = 9\n")
        self.assertEqual(len(kit.problems), 1)
        self.assertIn("[rules] wave_min", kit.problems[0].where)
        self.assertEqual(relay_kit.parse("[rules]\nwave_min = 6\n").problems, ())

    def test_feature_lanes_out_of_bounds_uses_zero(self) -> None:
        # relay_lane_features: out of bounds means 0, never clamped
        kit = relay_kit.parse("[front]\nfeature_lanes = 12\n")
        self.assertTrue(kit.problems[0].line().endswith("used 0"), kit.problems[0].line())
        self.assertEqual(relay_kit.parse("[front]\nfeature_lanes = 3\n").problems, ())

    def test_schema_matches_the_readers_own_tables(self) -> None:
        import relay_land
        import relay_lanes
        import relay_metrics
        import relay_rules
        hooks = os.path.join(ROOT, "plugins", "front", "hooks")
        sys.path.insert(0, hooks)
        try:
            import ask_waiting
        finally:
            sys.path.remove(hooks)
        tables = {"land": relay_land.SETTINGS, "front": dict(relay_lanes.SETTINGS), "metrics": relay_metrics.SETTINGS}
        tables["front"]["ask_reminder_days"] = ask_waiting.DAYS
        tables["front"]["ask_reminder_lines"] = ask_waiting.LINES
        for section, table in tables.items():
            for key, (default, low, high) in table.items():
                spec = relay_kit.SCHEMA[section][key]
                self.assertEqual((spec.default, spec.bounds), (default, (low, high)), f"{section}.{key}")
        self.assertEqual(relay_kit.SCHEMA["rules"]["lanes"].bounds, (1, relay_rules.LANES_MAX))
        self.assertEqual(relay_kit.SCHEMA["rules"]["wave_min"].bounds, (1, relay_rules.WAVE_MIN_MAX))

    def test_metrics_problem_reaches_the_route_guard_settings(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "kit.toml"), "w") as handle:
                handle.write('[metrics]\nenabled = "false"\n')
            _, problems = relay_kit.delegate_settings(root, {})
            self.assertTrue(any("[metrics] enabled" in p.line() for p in problems))

    def test_gate_refuses_a_branch_with_a_settings_problem(self) -> None:
        import subprocess
        import relay_gate
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "main")
            os.makedirs(os.path.join(root, ".relay"))

            def git(*args: str) -> None:
                subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)
            git("init", "-q", "-b", "main")
            git("config", "user.email", "t@t")
            git("config", "user.name", "t")
            with open(os.path.join(root, ".relay", "keep"), "w") as handle:
                handle.write("x")
            git("add", "-A")
            git("commit", "-q", "-m", "x")
            work = os.path.join(base, "task")
            git("worktree", "add", "-q", "-b", "task", work)
            os.makedirs(os.path.join(work, ".claude"))
            with open(os.path.join(work, ".claude", "kit.toml"), "w") as handle:
                handle.write('[delegate]\nbuild_tier_opus = "denny"\n')
            subprocess.run(["git", "-C", work, "add", "-A"], check=True, capture_output=True)
            subprocess.run(["git", "-C", work, "commit", "-q", "-m", "y"], check=True, capture_output=True)
            # through run(), so removing its call to refuse_bad_settings turns this red
            with self.assertRaises(relay_gate.GateRefused) as ctx:
                relay_gate.run(work)
            self.assertIn("build_tier_opus", str(ctx.exception))

    def test_doctor_reports_problems_and_bad_env_in_settings(self) -> None:
        import relay_setup
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as claude:
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "kit.toml"), "w") as handle:
                handle.write("[observe]\nenabld = true\n")
            with open(os.path.join(root, ".claude", "settings.local.json"), "w") as handle:
                handle.write('{"env": {"RELAY_CTX_STEP": "abc"}}')
            old = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = claude
            try:
                _, project = relay_setup.doctor_parts(root, profile={})
            finally:
                if old is None:
                    del os.environ["CLAUDE_CONFIG_DIR"]
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old
            red = [name for name, good, _ in project if not good]
            self.assertIn(".claude/kit.toml [observe] enabld", red)
            self.assertIn("env RELAY_CTX_STEP", red)


if __name__ == "__main__":
    unittest.main()
