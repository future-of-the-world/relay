"""Python rule: tests never touch the live .relay/queue of the checkout (fix item python-rule-tests-never-touch-the-live-relay-que)."""
import os
import re
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
# A live read is a line that points a queue read at the checkout (ROOT) without naming a pinned commit. "Points a queue read at
# ROOT" means: it names ROOT and one of the queue's paths or readers. "Pinned" means it names QUEUE_COMMIT, `commit` (the
# parameter of pinned_items) or a hex sha of 7+ digits. A queue event (an item moving to done/) must not turn a test red.
ROOT_NAMED = re.compile(r"\bROOT\b")
QUEUE_READ = re.compile(r"\.relay/queue|[\"']\.relay[\"'],\s*[\"']queue|\bread_queue\b|\bcommitted_items\b|\bcheck_files\b")
PINNED = re.compile(r"\bQUEUE_COMMIT\b|\bcommit\b|\b[0-9a-f]{7,40}\b")


def is_live_read(line: str) -> bool:
    return bool(ROOT_NAMED.search(line) and QUEUE_READ.search(line) and not PINNED.search(line))


class TestNoLiveQueueReads(unittest.TestCase):
    def test_no_test_reads_the_checkouts_live_queue(self) -> None:
        found = []
        for name in sorted(os.listdir(TESTS)):
            if not name.endswith(".py") or name == os.path.basename(__file__):
                continue
            with open(os.path.join(TESTS, name), encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if is_live_read(line):
                        found.append("%s:%d" % (name, number))
        self.assertEqual(found, [])


class TestMatcher(unittest.TestCase):
    def test_a_read_of_the_live_queue_is_flagged(self) -> None:
        for line in ["rq.read_queue(ROOT)",
                     'show_raw(ROOT, "HEAD", ".relay/queue/x.json")',
                     'git(ROOT, "show", "HEAD:.relay/queue/x.json")',
                     "tq.committed_items(tq.ROOT)",
                     'open(os.path.join(ROOT, ".relay/queue/x.json"))',
                     'git(ROOT, "log", "--", ".relay/queue")',
                     'os.listdir(os.path.join(ROOT, ".relay", "queue"))']:
            with self.subTest(line=line):
                self.assertTrue(is_live_read(line))

    def test_a_pinned_read_or_a_read_outside_the_queue_is_not_flagged(self) -> None:
        for line in ['show_raw(ROOT, QUEUE_COMMIT, ".relay/queue/done/x.json")',
                     'committed_text(ROOT, ".relay/README.md")',
                     'git(ROOT, "show", "fba8e70:.relay/queue/x.json")']:
            with self.subTest(line=line):
                self.assertFalse(is_live_read(line))


if __name__ == "__main__":
    unittest.main()
