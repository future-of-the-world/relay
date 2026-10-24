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

    def test_f1_a_probe_commit_reads_the_exact_bytes_the_tree_would(self):
        # A file ending "\n\n" must read the same in the probe path (git show) as in the tree path: git() strips, so a
        # stripped-plus-one-newline read would give "...\n" in the probe run and "...\n\n" in the outer run.
        repo = self.repo("bytes", items={"x": fix_item("Long one")})
        readme = os.path.join(repo, ".relay", "README.md")
        with open(readme, "w", encoding="utf-8") as handle:
            handle.write("two newlines\n\n")
        git(repo, "commit", "-aqm", "readme")
        tree = committed_text(repo, ".relay/README.md")
        with open(readme, "a", encoding="utf-8") as handle:
            handle.write("inert probe line\n")
        git(repo, "commit", "-aqm", "inert probe")
        self.assertEqual(tree, "two newlines\n\n")
        self.assertEqual(committed_text(repo, ".relay/README.md"), tree)


if __name__ == "__main__":
    unittest.main()
