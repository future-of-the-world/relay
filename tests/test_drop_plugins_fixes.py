"""Review fixes F1-F4 of the change that drops the issues and product plugins."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_setup_off import Fixture, ROOT  # noqa: E402


class DropPluginsFixes(Fixture):
    def doctor(self, root, name):
        return [(ok, detail) for n, ok, detail in self.rs.doctor(root, profile={}) if n == name]

    def test_f1_a_screen_project_gets_product_binding_and_rule(self):
        root = self.git_folder("scr")
        self.write(root, "go.mod", "module x\n")
        self.write(root, "index.html", "<html>")
        self.run_setup(root)
        kit = self.read(root, ".claude/kit.toml")
        self.assertIn("[product]", kit)
        self.assertIn('run_skill = "scr-run"', kit)
        self.assertNotIn("product@amidman", self.plugins(root))
        from relay_config import projects_file
        self.assertIn('"product-work"', open(projects_file()).read())

    def test_f1_no_screen_no_product(self):
        root = self.git_folder("nos")
        self.write(root, "go.mod", "module x\n")
        self.run_setup(root)
        self.assertNotIn("[product]", self.read(root, ".claude/kit.toml"))
        from relay_config import projects_file
        self.assertNotIn("product-work", open(projects_file()).read())

    def test_f1_existing_product_section_kept(self):
        root = self.git_folder("keep")
        self.write(root, "index.html", "<html>")
        text = '[product]\nmedium = "mine"\nrun_skill = "r"\n'
        self.write(root, ".claude/kit.toml", text)
        self.run_setup(root)
        self.assertIn(text, self.read(root, ".claude/kit.toml"))

    def test_f2_retired_flow_kind_names_the_cause(self):
        root = self.relay_tree()
        self.write(root, ".claude/kit.toml", '[flow]\nkind = "issues"\n')
        found = self.doctor(root, "no retired flow in kit.toml")
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0][0])
        self.assertIn("relay no longer ships that flow", found[0][1])
        self.assertEqual(self.doctor(root, "flow plugin for 'issues' found"), [])

    def test_f2_none_and_unknown_flow(self):
        root = self.relay_tree()
        self.write(root, ".claude/kit.toml", '[flow]\nkind = "none"\n')
        self.assertEqual(self.doctor(root, "no retired flow in kit.toml"), [])
        self.write(root, ".claude/kit.toml", '[flow]\nkind = "other"\n')
        self.assertEqual(self.doctor(root, "no retired flow in kit.toml"), [])
        self.assertFalse(self.doctor(root, "flow plugin for 'other' found")[0][0])

    def test_f3_retired_key_in_local_settings_is_reported(self):
        root = self.relay_tree()
        self.write(root, ".claude/settings.local.json", json.dumps({"enabledPlugins": {"product@amidman": True}}))
        name = "no retired relay plugin in .claude/settings.json"
        found = self.doctor(root, name)
        self.assertFalse(found[0][0])
        self.assertIn("product@amidman", found[0][1])

    def test_f3_clean_passes(self):
        root = self.relay_tree()
        self.assertTrue(self.doctor(root, "no retired relay plugin in .claude/settings.json")[0][0])

    def test_f4_docs_drop_removed_plugin_lines(self):
        flows = open(os.path.join(ROOT, "docs", "flows.md")).read()
        self.assertNotIn("/issue 42", flows)
        self.assertNotIn("look_review", open(os.path.join(ROOT, "docs", "variants", "archive.md")).read())


if __name__ == "__main__":
    unittest.main()
