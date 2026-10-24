"""The Python rule is loaded by relay's own CLAUDE.local.md and by no other target."""
import ast
import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_config  # noqa: E402
import relay_rules  # noqa: E402

PROFILE = {"profile": {"name": "t", "description": "t"}, "models": {}, "rules": {"load": []}}


class PythonRule(unittest.TestCase):
    def setUp(self) -> None:
        self.specs = relay_config.read_toml(os.path.join(ROOT, "projects.toml"))
        self.rules = relay_rules.rules()

    def render(self, name: str) -> str:
        return relay_rules.render_target(name, self.specs[name], self.rules, PROFILE)

    def test_relay_loads_the_rule_in_full(self) -> None:
        text = self.render("relay")
        self.assertIn("## Python", text)
        self.assertIn(self.rules["python"]["body"], text)

    def test_the_global_target_neither_loads_nor_lists_it(self) -> None:
        text = self.render("global")
        self.assertNotIn("## Python", text)
        self.assertNotIn("rules/python.md", text)

    def test_only_relay_loads_it(self) -> None:
        loaders = sorted(n for n, s in self.specs.items() if "python" in s.get("load", []))
        self.assertEqual(loaders, ["relay"])

    def test_no_profile_loads_it(self) -> None:
        for path in sorted(glob.glob(os.path.join(ROOT, "profiles", "*.toml"))):
            load = relay_config.read_toml(path).get("rules", {}).get("load", [])
            self.assertNotIn("python", load, path)

    def test_the_rule_does_not_promise_a_gate_step_that_does_not_exist(self) -> None:
        body = self.rules["python"]["body"]
        self.assertNotIn("as the gate's step", body)
        self.assertIn("until that step exists, do not reformat files by hand", body)
        self.assertIn("to be pinned and installed", body)

    def test_the_rule_does_not_say_who_loads_it(self) -> None:
        # projects.toml holds that fact; prose repeating it goes stale
        self.assertNotIn("Only relay loads", self.rules["python"]["body"])

    def test_every_function_here_has_types(self) -> None:
        with open(os.path.abspath(__file__)) as f:
            tree = ast.parse(f.read())
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                self.assertIsNotNone(fn.returns, fn.name)
                for a in fn.args.args:
                    if a.arg != "self":
                        self.assertIsNotNone(a.annotation, fn.name + "." + a.arg)


if __name__ == "__main__":
    unittest.main()
