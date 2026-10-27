"""tests/pidfile.py: a pid file is read only once it holds a whole line, and no test parses a file's text with int() any other way."""
import glob
import os
import re
import subprocess
import tempfile
import unittest

from pidfile import wait_pid

HERE = os.path.dirname(os.path.abspath(__file__))
# int() over the text of a file read in the same expression: int(read(p)), int(open(p).read()), int(p.read_text())
INT_OF_READ = re.compile(r"\bint\(.*(?:\bread\(|\.read_text\()")


class WaitPid(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "pid")

    def test_a_file_created_empty_and_written_later_gives_the_number(self) -> None:
        # the writer opens the file at once (empty) and writes "123\n" 0.3 s later; the old read-when-it-exists gave int('')
        writer = subprocess.Popen(["bash", "-c", 'exec 3>"$0"; sleep 0.3; echo 123 >&3', self.path])
        self.addCleanup(writer.wait)
        self.assertEqual(wait_pid(self.path), 123)

    def test_a_number_without_its_newline_is_not_yet_whole(self) -> None:
        with open(self.path, "w") as handle:
            handle.write("123")
        with self.assertRaises(AssertionError) as caught:
            wait_pid(self.path, timeout=1.0)
        self.assertIn("held no whole number within 1.0 s: '123'", str(caught.exception))

    def test_a_file_that_never_comes_fails_naming_it_missing(self) -> None:
        with self.assertRaises(AssertionError) as caught:
            wait_pid(self.path, timeout=1.0)
        self.assertIn("missing", str(caught.exception))

    def test_a_dead_writer_that_left_nothing_fails_at_once_naming_it(self) -> None:
        # timeout is 60 s but the writer is already gone: one read decides, so this returns at once, not after 60 s
        with self.assertRaises(AssertionError) as caught:
            wait_pid(self.path, timeout=60.0, writer_alive=lambda: False)
        self.assertIn("never wrote its pid", str(caught.exception))

    def test_a_dead_writer_that_wrote_before_dying_gives_the_number(self) -> None:
        with open(self.path, "w") as handle:
            handle.write("77\n")
        self.assertEqual(wait_pid(self.path, writer_alive=lambda: False), 77)

    def test_a_slow_live_writer_is_waited_for(self) -> None:
        writer = subprocess.Popen(["bash", "-c", 'sleep 0.3; echo 5 > "$0"', self.path])
        self.addCleanup(writer.wait)
        self.assertEqual(wait_pid(self.path, writer_alive=lambda: writer.poll() is None), 5)

    def test_a_timeout_outside_the_bounds_is_refused(self) -> None:
        for bad in (0.5, 901.0):
            with self.assertRaises(ValueError):
                wait_pid(self.path, timeout=bad)


class OnlyThroughTheHelper(unittest.TestCase):
    def test_no_test_parses_a_file_it_read_itself_with_int(self) -> None:
        found = []
        for name in sorted(glob.glob(os.path.join(HERE, "*.py"))):
            if os.path.basename(name) in ("pidfile.py", "test_pidfile.py"):
                continue
            with open(name) as handle:
                for number, line in enumerate(handle, 1):
                    if INT_OF_READ.search(line):
                        found.append("%s:%d" % (os.path.basename(name), number))
        self.assertEqual(found, [], "read a pid file with tests/pidfile.wait_pid, not int(read(...))")


if __name__ == "__main__":
    unittest.main()
