"""The "types and lint" step (bin/types-lint): it fails on a type error in a strict module and on an unused import,
and passes on the tree. The planted cases run in a temporary copy of the config and of one strict module."""
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

    def test_tree_passes(self):
        r = run(ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
