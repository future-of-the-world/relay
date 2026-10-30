"""Tests of the principles rule and the auto-merge texts."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import ROOT, shipped_specs  # noqa: E402


class TestPrinciplesRule(unittest.TestCase):
    """The principles rule is carried by the targets that load it (relay, any opting-in project) and not by the global file."""

    def _targets(self):
        return shipped_specs()

    def test_rule_has_the_shape(self):
        import relay_rules
        self.assertEqual(relay_rules.rules()["principles"]["title"], "Principles")

    def test_global_file_does_not_list_principles_but_still_lists_the_others(self):
        # F2: a rule only relay loads stays out of the global read list; the rest of the list is unchanged
        import relay_rules, relay_config
        text = relay_rules.render_target("global", self._targets()["global"], relay_rules.rules(), relay_config.active_profile())
        self.assertNotIn("Principles", text)
        self.assertNotIn("**OpenSpec", text)   # a spec method's rule is carried by a project that turns the method on, never by the global file
        for title in ("Product work", "Quality gate", "Work queue", "Structured data"):
            self.assertIn(f"**{title}", text)

    def test_global_file_carries_the_long_job_exception(self):
        # `relay sync` writes the rendered global target to ~/.claude/CLAUDE.md; it must carry the delegation line
        import relay_rules, relay_config
        text = relay_rules.render_target("global", self._targets()["global"], relay_rules.rules(), relay_config.active_profile())
        text = " ".join(text.split())
        self.assertIn("a job over about 30 minutes, the paid `bin/ci`, is the front's: Bash `run_in_background`, never a runner", text)

    def test_a_new_rule_still_reaches_the_global_read_list(self):
        import relay_rules
        rules = {"a": {"title": "A", "gist": "g.", "body": "b", "path": "/x/a.md"},
                 "b": {"title": "B", "gist": "g.", "body": "b", "path": "/x/b.md"}}
        text = relay_rules.render_target("global", {"load": [], "skip": ["b"]}, rules, {})
        self.assertIn("**A**", text)
        self.assertNotIn("**B**", text)

    def test_global_target_writes_the_native_language_line_only_when_the_key_is_set(self):
        import relay_rules
        rules = {"a": {"title": "A", "gist": "g.", "body": "b", "path": "/x/a.md"}}
        with_key = relay_rules.render_target("global", {"load": [], "native_language": "Russian"}, rules, {})
        self.assertIn("My native language: Russian.\n", with_key)
        without = relay_rules.render_target("global", {"load": []}, rules, {})
        self.assertNotIn("native language", without)
        # a project target never carries it
        self.assertNotIn("native language", relay_rules.render_target("demo", {"load": [], "native_language": "Russian"}, rules, {}))

    def test_relay_loads_it_and_the_global_profile_does_not(self):
        # relay opts in by load; the global profile loads none of it (other projects opt in the same way)
        loaders = sorted(name for name, spec in self._targets().items() if "principles" in spec.get("load", []))
        self.assertIn("relay", loaders)
        import relay_config
        for profile in sorted(n for n in os.listdir(os.path.join(ROOT, "profiles")) if n.endswith(".toml")):
            data = relay_config.read_toml(os.path.join(ROOT, "profiles", profile))
            self.assertNotIn("principles", data.get("rules", {}).get("load", []), profile)

    def test_relay_target_renders_the_rule_in_full_and_nothing_else(self):
        import relay_rules
        spec = self._targets()["relay"]
        text = relay_rules.render_target("relay", spec, relay_rules.rules(), {})
        self.assertIn("## Principles", text)
        for n in range(1, 11):
            self.assertIn(f"## {n}. ", text)
        self.assertIn("waste that repeats on every run or every change is MEDIUM", text)
        self.assertNotIn("aste (experimental)", text)
        self.assertNotIn("Rules to read when they apply", text)


    def test_a_project_with_load_principles_carries_it(self):
        import relay_rules
        text = relay_rules.render_target("demo", {"load": ["principles"]}, relay_rules.rules(), {})
        self.assertIn("## 9. Decide inside the principles", text)
        self.assertIn("## 10. Works for a newcomer", text)

    def _section(self, n):
        import re
        with open(os.path.join(ROOT, "rules", "principles.md")) as f:
            text = f.read()
        m = re.search(rf"^### {n}\. .*?(?=^### |\Z)", text, re.S | re.M)
        return m.group(0)

    def test_principle_10_names_the_program_generally_and_relay_only_as_example(self):
        # a project loading the rule has its own program; relay appears only in "In relay ..." sentences
        import re
        body = self._section(10)
        general = " ".join(re.sub(r"In relay[^.]*\.", "", body).split())
        self.assertNotIn("relay", general.lower())
        self.assertIn("In relay the users are two", body)
        self.assertNotIn("non-obvious secrets", body)
        self.assertNotIn("stays minimal", body)

    def test_principle_headings_are_numbered_once_in_order(self):
        import re
        with open(os.path.join(ROOT, "rules", "principles.md")) as f:
            text = f.read()
        nums = [int(x) for x in re.findall(r"^### (\d+)\. ", text, re.M)]
        self.assertEqual(nums, list(range(1, len(nums) + 1)))


class AutoMergeTextsTest(unittest.TestCase):
    def _read(self, rel):
        with open(os.path.join(ROOT, rel)) as f:
            return " ".join(f.read().split())

    def test_git_rule_scopes_merge_without_asking_to_relay_projects(self):
        """F1: the rule merges without asking only where `.relay/` is; elsewhere and for Glonass the owner is asked."""
        text = self._read("rules/git.md")
        self.assertIn("Where the project has `.relay/`", text)
        self.assertIn("Elsewhere, and for merge requests on Glonass repositories, merge into the default branch only when I ask", text)

    def test_delegate_step_9_names_readiness_with_paid_run(self):
        """F3: step 9 merges on readiness (incl. the paid run), not on the verdict alone."""
        text = self._read("plugins/delegate/skills/delegate/SKILL.md")
        self.assertIn("When the change is ready", text)
        self.assertNotIn("the paid run green when agent, skill, role or rule texts changed", text)
        self.assertIn("default branch taken)", text)
        self.assertNotIn("When the verdict is `open 0` the front merges", text)

    def test_merged_line_has_paid_run_slot(self):
        """The merged line no longer carries a per-change paid-run part: the paid run is per wave."""
        self.assertNotIn("`; paid run green, $<cost>`", self._read("plugins/front/skills/front/SKILL.md"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
