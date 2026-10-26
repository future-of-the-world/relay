"""tests/fake_tools.py: one cached file per text, a link per test, and a replaced tool is not shared."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_tools import install_fake  # noqa: E402


class FakeTools(unittest.TestCase):
    def test_same_text_shares_one_file_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            install_fake(a, "#!/bin/sh\necho hi\n")
            install_fake(b, "#!/bin/sh\necho hi\n")
            # same text -> same cached inode (a hardlink or a symlink to it)
            self.assertEqual(os.stat(a).st_ino, os.stat(b).st_ino)
            self.assertEqual(subprocess.run([a], capture_output=True, text=True).stdout, "hi\n")

    def test_replacing_a_tool_changes_only_that_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            install_fake(a, "#!/bin/sh\necho one\n")
            install_fake(b, "#!/bin/sh\necho one\n")
            install_fake(a, "#!/bin/sh\necho two\n")
            self.assertEqual(subprocess.run([a], capture_output=True, text=True).stdout, "two\n")
            self.assertEqual(subprocess.run([b], capture_output=True, text=True).stdout, "one\n")

    def test_an_installed_tool_cannot_be_written_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            install_fake(a, "#!/bin/sh\necho one\n")
            install_fake(b, "#!/bin/sh\necho one\n")
            if os.geteuid() != 0:    # root ignores file modes
                with self.assertRaises(PermissionError):
                    open(a, "w")
            self.assertEqual(subprocess.run([b], capture_output=True, text=True).stdout, "one\n")


if __name__ == "__main__":
    unittest.main()
