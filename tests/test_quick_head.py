"""The quick check reads the same text the gate will (queue item the-quick-check-passes-before-a-commit-and-fails, finding Q1)."""
import os
import unittest

from test_queue import Base, committed_items, committed_text, fix_item, git


class TestQuickReadsTheWorkingTree(Base):
    def test_q1_an_uncommitted_edit_is_what_the_committed_text_helpers_read(self):
        # An edit not yet committed must be seen by a test that reads the item or the README, or `bin/ci --quick` is green
        # on the old commit and the gate on the new one is red.
        repo = self.repo("edit", items={"x": fix_item("Long one")})
        with open(os.path.join(repo, ".relay", "queue", "x.json"), "a", encoding="utf-8") as handle:
            handle.write("an uncommitted line\n")
        with open(os.path.join(repo, ".relay", "README.md"), "w", encoding="utf-8") as handle:
            handle.write("edited readme\n")
        self.assertTrue(committed_items(repo)["x.json"].endswith("an uncommitted line\n"))
        self.assertEqual(committed_text(repo, ".relay/README.md"), "edited readme\n")

    def test_q1_a_probe_commit_still_reads_the_commit_before_it(self):
        # the inert probe commits an appended line to every item: that line must stay invisible
        repo = self.repo("probe", items={"x": fix_item("Long one")})
        good = committed_items(repo)["x.json"]
        with open(os.path.join(repo, ".relay", "queue", "x.json"), "a", encoding="utf-8") as handle:
            handle.write("inert probe line\n")
        git(repo, "commit", "-aqm", "inert probe")
        self.assertEqual(committed_items(repo), {"x.json": good})
        self.assertEqual(committed_text(repo, ".relay/README.md"), "relay folder\n")


if __name__ == "__main__":
    unittest.main()
