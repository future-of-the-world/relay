"""The hooks run under whatever python3 is on the hook's PATH, on macOS /usr/bin/python3 (3.9): every plugin lib module
and hook must import there, and a hook must survive an empty event. mypy's python_version cannot see this class."""
import glob
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = "/usr/bin/python3"


def old_python():
    if not os.path.exists(PY):
        return False
    v = subprocess.run([PY, "-c", "import sys; print(sys.version_info[1])"], capture_output=True, text=True).stdout
    return v.strip().isdigit() and int(v) < 11


@unittest.skipUnless(old_python(), "needs /usr/bin/python3 older than 3.11")
class Python39(unittest.TestCase):
    def test_lib_modules_import(self):
        for path in sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "lib", "*.py"))):
            with self.subTest(module=os.path.relpath(path, ROOT)):
                code = "import sys, importlib; sys.path.insert(0, %r); importlib.import_module(%r)" % (
                    os.path.dirname(path), os.path.basename(path)[:-3])
                r = subprocess.run([PY, "-c", code], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_hooks_survive_an_empty_event(self):
        for path in sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "hooks", "*.py"))):
            with self.subTest(hook=os.path.relpath(path, ROOT)):
                r = subprocess.run([PY, path], input="{}", capture_output=True, text=True)
                self.assertNotIn("TypeError", r.stderr)
                self.assertNotIn("SyntaxError", r.stderr)


if __name__ == "__main__":
    unittest.main()
