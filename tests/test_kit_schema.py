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

    def test_gate_refuses_a_branch_with_a_settings_problem(self) -> None:
        import relay_gate
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "kit.toml"), "w") as handle:
                handle.write('[delegate]\nbuild_tier_opus = "denny"\n')
            with self.assertRaises(relay_gate.GateRefused) as ctx:
                relay_gate.refuse_bad_settings(root)
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
