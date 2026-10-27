"""The hooks run under whatever python3 is on the hook's PATH, on macOS /usr/bin/python3 (3.9): every plugin lib module
and hook must import there, and a hook must survive an empty event. mypy's python_version cannot see this class."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = "/usr/bin/python3"
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_precheck  # noqa: E402


def old_python():
    if not os.path.exists(PY):
        return False
    v = subprocess.run([PY, "-c", "import sys; print(sys.version_info[1])"], capture_output=True, text=True).stdout
    return v.strip().isdigit() and int(v) < 11


@unittest.skipUnless(old_python(), "needs /usr/bin/python3 older than 3.11")
class Python39(unittest.TestCase):
    def test_lib_modules_import_and_hooks_survive_an_empty_event(self):
        # One judge for the gate and `relay precheck`: relay_precheck.check_python39, so the two cannot drift.
        self.assertEqual(relay_precheck.check_python39(ROOT), [])


if __name__ == "__main__":
    unittest.main()
