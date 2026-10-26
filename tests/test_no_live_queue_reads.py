"""Python rule: tests never touch the live .relay/queue of the checkout (fix item python-rule-tests-never-touch-the-live-relay-que)."""
import os
import re
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
# A live read is any of: the helpers that list or read the queue folder pointed at the checkout (ROOT), a read of a queue path
# at ROOT, or a git log of the checkout's queue history. A queue event (an item moving to done/) must not turn a test red.
LIVE = [re.compile(r"committed_items\(ROOT"),
        re.compile(r"committed_text\(ROOT,\s*[\"']\.relay/queue"),
        re.compile(r"git\(ROOT,\s*[\"']log[\"'].*\.relay/queue"),
        re.compile(r"os\.listdir\(os\.path\.join\(ROOT,\s*[\"']\.relay[\"'],\s*[\"']queue")]


class TestNoLiveQueueReads(unittest.TestCase):
    def test_no_test_reads_the_checkouts_live_queue(self) -> None:
        found = []
        for name in sorted(os.listdir(TESTS)):
            if not name.endswith(".py") or name == os.path.basename(__file__):
                continue
            with open(os.path.join(TESTS, name), encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if any(pattern.search(line) for pattern in LIVE):
                        found.append("%s:%d" % (name, number))
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
