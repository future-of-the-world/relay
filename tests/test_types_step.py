"""The "types and lint" step (bin/types-lint): it fails on a type error in a strict module and on an unused import,
and passes on the tree. The tree itself is checked by the gate step, not here. The planted cases run in a temporary copy of the config and of one strict module."""
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEP = os.path.join(ROOT, "bin", "types-lint")


def run(directory):
    return subprocess.run(["bash", STEP, directory], capture_output=True, text=True)


class TypesStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        os.makedirs(os.path.join(self.tmp, "lib"))
        shutil.copy(os.path.join(ROOT, "pyproject.toml"), self.tmp)
        shutil.copy(os.path.join(ROOT, "lib", "relay_toml.py"), os.path.join(self.tmp, "lib"))

    def test_clean_copy_passes(self):
        r = run(self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_type_error_in_a_strict_module_fails(self):
        # relay_toml is listed as strict: a function declared to return int that returns a string is a type error,
        # and a function without annotations is an error only in strict mode
        with open(os.path.join(self.tmp, "lib", "relay_toml.py"), "a") as f:
            f.write("\n\ndef planted() -> int:\n    return \"x\"\n\n\ndef bare(x):\n    return x\n")
        r = run(self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL mypy", r.stdout)
        self.assertIn("relay_toml.py", r.stdout)
        self.assertIn("no-untyped-def", r.stdout)   # strict, not the default strictness
        self.assertNotIn("FAIL ruff", r.stdout)

    def test_unused_import_fails(self):
        with open(os.path.join(self.tmp, "lib", "other.py"), "w") as f:
            f.write("import os\n")
        r = run(self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL ruff", r.stdout)
        self.assertIn("F401", r.stdout)
        self.assertNotIn("FAIL mypy", r.stdout)

    def _plant_in_hook(self, hook):
        # mypy names a hook by its path from the root (plugins.front.hooks.handover): the override must match that
        shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(self.tmp, "lib"), dirs_exist_ok=True)
        d = os.path.join(self.tmp, os.path.dirname(hook))
        os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(ROOT, hook), d)
        with open(os.path.join(self.tmp, hook), "a") as f:
            f.write("\n\ndef bare(x):\n    return x\n")
        return run(self.tmp)

    def test_front_hooks_are_strict(self):
        for name in ("handover", "budget", "reply_language"):
            with self.subTest(hook=name):
                r = self._plant_in_hook("plugins/front/hooks/%s.py" % name)
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertIn("%s.py" % name, r.stdout)
                self.assertIn("no-untyped-def", r.stdout)

    def test_unannotated_hook_keeps_default_strictness(self):
        r = self._plant_in_hook("plugins/observe/hooks/ledger.py")
        self.assertNotIn("no-untyped-def", r.stdout)


if __name__ == "__main__":
    unittest.main()
