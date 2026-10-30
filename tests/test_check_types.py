"""Typed signatures of the functions the git-process change added or changed (rule: every new or changed function has types)."""

import importlib.util
import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_inert  # noqa: E402
import relay_verdict  # noqa: E402


def _bin_relay():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("relay_bin_for_types", os.path.join(ROOT, "bin", "relay"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Typed(unittest.TestCase):
    def assert_typed(self, function):
        signature = inspect.signature(function)
        for name, parameter in signature.parameters.items():
            self.assertIsNot(parameter.annotation, inspect.Parameter.empty, "%s: parameter %s has no type" % (function.__name__, name))
        self.assertIsNot(signature.return_annotation, inspect.Signature.empty, "%s: no return type" % function.__name__)

    def test_verdict_functions_have_types(self):
        for name in ("finding_list", "_finding_list", "record_check", "_record_check", "_merge_findings"):
            self.assert_typed(getattr(relay_verdict, name))

    def test_inert_git_has_types(self):
        self.assert_typed(relay_inert._git)

    def test_show_check_has_types(self):
        self.assert_typed(_bin_relay().show_check)

    def test_plugin_copies_are_identical(self):
        for name in ("relay_verdict.py", "relay_inert.py"):
            with open(os.path.join(ROOT, "lib", name), "rb") as handle:
                original = handle.read()
            for plugin in ("relay", "front"):
                with open(os.path.join(ROOT, "plugins", plugin, "lib", name), "rb") as handle:
                    self.assertEqual(handle.read(), original, "%s copy in plugins/%s differs" % (name, plugin))


if __name__ == "__main__":
    unittest.main()
