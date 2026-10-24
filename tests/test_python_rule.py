"""The Python rule is loaded by relay's own CLAUDE.local.md and by no other target."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_config  # noqa: E402
import relay_rules  # noqa: E402

PROFILE = {"profile": {"name": "t", "description": "t"}, "models": {}, "rules": {"load": []}}


class PythonRule(unittest.TestCase):
    def setUp(self):
        self.specs = relay_config.read_toml(os.path.join(ROOT, "projects.toml"))
        self.rules = relay_rules.rules()

    def render(self, name):
        return relay_rules.render_target(name, self.specs[name], self.rules, PROFILE)

    def test_relay_loads_the_rule_in_full(self):
        text = self.render("relay")
        self.assertIn("## Python", text)
        self.assertIn(self.rules["python"]["body"], text)

    def test_the_global_target_neither_loads_nor_lists_it(self):
        text = self.render("global")
        self.assertNotIn("## Python", text)
        self.assertNotIn("rules/python.md", text)

    def test_only_relay_loads_it(self):
        loaders = sorted(n for n, s in self.specs.items() if "python" in s.get("load", []))
        self.assertEqual(loaders, ["relay"])


if __name__ == "__main__":
    unittest.main()
