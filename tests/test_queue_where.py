"""`where` entries that name a folder or a pattern are refused by `add` and `edit` (not by `check`); a file, also a new one, is accepted.
Scratch repositories in a temp dir; time is a value passed in."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq
SLUG = "job-item"
FOUND = "2026-10-01T00:00:00Z"
NOW = "2026-10-10T00:00:00Z"
QUIET = tq.QUIET
SEED = {"lib/relay_other.py": "x = 1\n", "docs/handover.md": "h\n", "plans/a.md": "q\n"}


class WhereFiles(tq.Base):
    def setUp(self):
        super().setUp()
        self.write_commit(self.main, SEED, "seed")

    def add(self, where):
        return rq.add(self.main, "feature", "Make it faster please", why="it matters", minutes=10, where=where, now=NOW, **QUIET)

    def seed_item(self, where):
        item = rq.new_item("feature", 0, 10, FOUND, "test", "Job item breaks", "what is wanted", "it matters", where=where)
        self.write_commit(self.main, {f".relay/queue/{SLUG}.json": rq.serialize(SLUG, item)}, "item")

    def edit(self, old, new):
        return rq.edit(self.main, SLUG, "where", old, new, "found wrong on 10 Oct", now=NOW, **QUIET)

    def test_add_refuses_a_slash_folder_a_bare_directory_and_a_pattern(self):
        # lib/ ends in a slash; docs exists as a directory; plans/*.md has a star
        for entry, word in (("lib/", "a folder"), ("docs", "a folder"), ("plans/*.md", "a pattern")):
            with self.assertRaisesRegex(rq.Refused, f"where element 2 `{entry.replace('*', '.')}` is {word}: name the file you will change"):
                self.add(["lib/relay_other.py", entry])

    def test_add_accepts_files_also_a_new_one_and_a_line(self):
        for where in (["lib/relay_cmd/digest.py"], ["lib/relay_other.py:103"],
                      ["lib/relay_setup.py:325-333 merge_settings", "docs/handover.md"]):
            self.add(where)

    def test_the_refusal_names_the_next_step(self):
        with self.assertRaises(rq.Refused) as ctx:
            self.add(["docs/"])
        self.assertIn("name the file you will change (a new file is fine, e.g. lib/relay_cmd/digest.py)", str(ctx.exception))

    def test_edit_gives_the_same_verdicts(self):
        self.seed_item(["lib/relay_other.py"])
        for new in ("lib/", "docs", "plans/*.md"):
            with self.assertRaisesRegex(rq.Refused, "nothing edited: where element 1 .* is a (folder|pattern)"):
                self.edit("lib/relay_other.py", new)
        self.assertEqual(self.item(SLUG)["where"], ["lib/relay_other.py"])
        self.edit("lib/relay_other.py", "lib/relay_cmd/digest.py")
        self.assertEqual(self.item(SLUG)["where"], ["lib/relay_cmd/digest.py"])
        self.edit("lib/relay_cmd/digest.py", "lib/relay_other.py:103")
        self.assertEqual(self.item(SLUG)["where"], ["lib/relay_other.py:103"])

    def test_check_stays_green_on_a_stored_item_with_a_folder(self):
        # check has no tree to look at: a folder entry written before this rule is not a malformed item
        self.seed_item(["lib/", "plans/*.md"])
        self.assertEqual(self.item(SLUG)["problems"], [])
        self.assertEqual(rq.check_files(self.main), [])


if __name__ == "__main__":
    unittest.main()
