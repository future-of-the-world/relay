"""A': every test's temporary folder carries the test's name, so a leftover's path names its test and the gate's sweep finds it."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

import tmp_default


class Named(unittest.TestCase):
    def test_this_tests_temporary_folder_names_this_test(self):
        """The fact test: under any runner, mkdtemp lands in a `relay-home-<this method>-` folder (the name cut to 40 characters)."""
        folder = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, folder)
        expected = tmp_default.folder_prefix(self._testMethodName)
        self.assertIn(expected, os.path.realpath(folder) + os.sep, "a runner skipped tests/tmp_default.py: %s" % folder)
        self.assertEqual(expected, "relay-home-test_this_tests_temporary_folder_names_t-")

    def test_patching_twice_gives_one_folder_per_test_not_two_nested(self):
        tmp_default.patch_unittest()
        tmp_default.patch_unittest()
        parts = [part for part in os.path.realpath(tempfile.gettempdir()).split(os.sep) if part.startswith("relay-home-")]
        self.assertEqual(len(parts), 1, parts)

    def run_probe(self, argv):
        done = subprocess.run([sys.executable, *argv], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_plain_python_m_unittest_reaches_it(self):
        """`python3 -m unittest tests.test_tmp_folders_named.Named.test_this_tests_...` (no relay runner): tests/__init__.py patches."""
        self.run_probe(["-m", "unittest", "tests.test_tmp_folders_named.Named.test_this_tests_temporary_folder_names_this_test"])

    def test_the_gate_runners_reach_it(self):
        self.run_probe([os.path.join(HERE, "run_unittest.py"), "test_tmp_folders_named.Named.test_this_tests_temporary_folder_names_this_test"])

    def test_the_parallel_workers_reach_it(self):
        """tests/parallel_unittest.py --worker: given the fact test's name on stdin, it runs it with the folders named: one test ran, no problem."""
        name = "test_tmp_folders_named.Named.test_this_tests_temporary_folder_names_this_test"
        done = subprocess.run([sys.executable, os.path.join(HERE, "parallel_unittest.py"), "--worker", HERE], cwd=ROOT, input=name + "\n",
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        reply = json.loads(done.stdout.splitlines()[0])      # one reply per class name, then the leak scan's line
        self.assertEqual((reply["ran"], reply["problems"]), (1, []), done.stderr)


if __name__ == "__main__":
    unittest.main()
