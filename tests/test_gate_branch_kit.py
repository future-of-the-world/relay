"""The gate checks a branch's .claude/kit.toml with the branch's own lib/ (relay_kit and the modules it imports)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_gate  # noqa: E402


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


class BranchKit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wt = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _toml(self, body: str) -> None:
        _write(os.path.join(self.wt, ".claude", "kit.toml"), body)

    def _real_kit(self) -> str:
        dest = os.path.join(self.wt, "lib")
        os.makedirs(dest)
        for name in ("relay_kit.py", "relay_toml.py"):
            shutil.copy(os.path.join(ROOT, "lib", name), dest)
        return os.path.join(dest, "relay_kit.py")

    def test_branch_helper_module_is_used(self) -> None:
        # pass 1: relay_kit imports a helper only the branch has; no refusal
        _write(os.path.join(self.wt, "lib", "relay_kit_keys.py"), "KEYS = 1\n")
        _write(os.path.join(self.wt, "lib", "relay_kit.py"),
               "import relay_kit_keys\nclass _K:\n    problems = []\ndef load(root):\n    return _K()\n")
        self._toml("[delegate]\nnew_key = 1\n")
        relay_gate.refuse_bad_settings(self.wt)

    def test_real_kit_valid_toml_passes(self) -> None:
        # pass 2 base: the real module copied in loads (dataclasses need the module registered)
        self._real_kit()
        self._toml("[delegate]\n")
        relay_gate.refuse_bad_settings(self.wt)

    def test_real_kit_unknown_value_refused(self) -> None:
        # pass 3: a wrong value is named
        self._real_kit()
        self._toml('[delegate]\nopus_for_builders = "denny"\n')
        with self.assertRaises(relay_gate.GateRefused) as ctx:
            relay_gate.refuse_bad_settings(self.wt)
        self.assertIn("opus_for_builders", str(ctx.exception))

    def test_installed_schema_without_branch_kit(self) -> None:
        # pass 4
        self._toml("[delegate]\nrenamed_key = 1\n")
        with self.assertRaises(relay_gate.GateRefused) as ctx:
            relay_gate.refuse_bad_settings(self.wt)
        self.assertIn("renamed_key", str(ctx.exception))

    def test_branch_schema_decides(self) -> None:
        # the real copy edited to know new_key
        path = self._real_kit()
        with open(path) as handle:
            text = handle.read()
        self.assertIn('"opus_for_builders": Field(', text)
        # pass 2: the branch copy learns the key new_key; the installed schema does not know it
        _write(path, text.replace('"opus_for_builders": Field(', '"new_key": Field("int", "x"),\n        "opus_for_builders": Field(', 1))
        self._toml("[delegate]\nnew_key = 1\n")
        relay_gate.refuse_bad_settings(self.wt)
        self._toml("[delegate]\nnew_keyy = 1\n")
        with self.assertRaises(relay_gate.GateRefused):
            relay_gate.refuse_bad_settings(self.wt)

    def _refused(self, kit_source: str) -> str:
        _write(os.path.join(self.wt, "lib", "relay_kit.py"), kit_source)
        self._toml("[delegate]\n")
        with self.assertRaises(relay_gate.GateRefused) as ctx:
            relay_gate.refuse_bad_settings(self.wt)
        return str(ctx.exception)

    def test_syntax_error_refused(self) -> None:
        self.assertIn("relay_kit.py", self._refused("def (:\n"))

    def test_import_error_refused(self) -> None:
        self.assertIn("relay_kit.py", self._refused("raise ImportError('x')\n"))

    def test_load_without_problems_refused(self) -> None:
        # F2 pass 1: no traceback, a refusal naming the branch's module
        self.assertIn("lib/relay_kit.py", self._refused("def load(root):\n    return object()\n"))

    def test_problem_without_line_refused(self) -> None:
        # F2 pass 2
        src = "class _K:\n    problems = [object()]\ndef load(root):\n    return _K()\n"
        self.assertIn("lib/relay_kit.py", self._refused(src))

    def test_empty_problems_pass(self) -> None:
        # F2 pass 3
        _write(os.path.join(self.wt, "lib", "relay_kit.py"), "class _K:\n    problems = []\ndef load(root):\n    return _K()\n")
        self._toml("[delegate]\n")
        relay_gate.refuse_bad_settings(self.wt)


if __name__ == "__main__":
    unittest.main()
