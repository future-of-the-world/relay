"""Q1 of one-shared-test-file-makes-parallel-changes-conf: no test file is so large that every parallel change must append to it."""
import os
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
# tests/test_relay.py was 2008 lines with 17 classes and was the file all three conflicting merges of 24 Oct appended to.
# The largest file now is test_queue.py (1342 lines), so the cap leaves it room and refuses a return of one shared file.
MAX_LINES = 1500


class TestFilesStaySplit(unittest.TestCase):
    def test_no_test_file_is_longer_than_the_cap(self) -> None:
        too_long = []
        for name in sorted(os.listdir(TESTS)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(TESTS, name)) as handle:
                lines = len(handle.read().splitlines())
            if lines > MAX_LINES:
                too_long.append(f"{name}: {lines} lines")
        self.assertEqual(too_long, [])

    def test_the_old_shared_file_is_gone(self) -> None:
        self.assertFalse(os.path.exists(os.path.join(TESTS, "test_relay.py")))


if __name__ == "__main__":
    unittest.main()
