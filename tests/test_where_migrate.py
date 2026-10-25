"""The one-off rewrite of `where` from a string to a list of places (lib/relay_where_migrate.py), on a temporary queue."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import relay_queue as rq  # noqa: E402
import relay_where_migrate as wm  # noqa: E402


class SplitWhere(unittest.TestCase):
    def test_a_string_of_places_becomes_one_element_each(self):
        # "lib/relay_marks.py, plugins/core/hooks/guard-main.sh (writes), docs": three places; the comma inside the
        # parentheses of a note does not split; "docs" is a bare word that is the whole piece, so a place.
        text = "lib/relay_marks.py, plugins/core/hooks/guard-main.sh (writes, reads), docs"
        self.assertEqual(wm.split_where("s", text), (["lib/relay_marks.py", "plugins/core/hooks/guard-main.sh (writes, reads)", "docs"], True))

    def test_lines_and_notes_are_kept(self):
        self.assertEqual(wm.split_where("s", "lib/a.py:325-333 merge_settings, b.py:7"), (["lib/a.py:325-333 merge_settings", "b.py:7"], True))

    def test_a_piece_that_names_no_place_is_glued_to_the_note_before_it_and_not_clean(self):
        self.assertEqual(wm.split_where("s", "bin/ci, the eval runner and its graders"), (["bin/ci, the eval runner and its graders"], False))

    def test_a_first_word_with_a_bad_line_keeps_the_path_and_is_not_clean(self):
        self.assertEqual(wm.split_where("s", "lib/a.py:22,28-35, b.py"), (["lib/a.py :22,28-35", "b.py"], False))

    def test_a_string_with_no_place_gets_the_items_own_file(self):
        self.assertEqual(wm.split_where("job", "to be designed first"), ([".relay/queue/job.json to be designed first"], False))


class Migrate(unittest.TestCase):
    def test_every_record_open_and_done_is_rewritten_through_the_writer(self):
        with tempfile.TemporaryDirectory() as root:
            for sub, slug, closed, where in (("", "open-one", None, "lib/a.py, docs"), ("done", "done-one", "2026-10-03T00:00:00Z", "lib/b.py:5-9 note"),
                                             ("", "no-where", None, None)):
                item = rq.new_item("fix", 5, 10, "2026-10-01T00:00:00Z", "test", "Something is off", "what", "why", failing="fails")
                item["closed_at"], item["test"] = closed, ("tests/t.py::T::t" if closed else None)
                if closed:
                    item["fixed_by"] = "a" * 40
                text = rq.serialize(slug, item, "done" if closed else "open")
                data = json.loads(text)
                if where:
                    data["where"] = where                        # the old shape: one string
                folder = os.path.join(root, rq.QDIR, sub)
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, slug + ".json"), "w") as handle:
                    json.dump(data, handle)
            done, odd = wm.migrate(root)
            self.assertEqual(done, [".relay/queue/done/done-one.json", ".relay/queue/open-one.json"])
            self.assertEqual(odd, [])
            for sub, slug, want in (("", "open-one", ["lib/a.py", "docs"]), ("done", "done-one", ["lib/b.py:5-9 note"])):
                with open(os.path.join(root, rq.QDIR, sub, slug + ".json")) as handle:
                    item = rq.parse(slug, handle.read(), "done" if sub else "open")
                self.assertEqual((item["problems"], item["where"]), ([], want))
            self.assertEqual(wm.migrate(root), ([], []))          # run again: nothing left to rewrite


if __name__ == "__main__":
    unittest.main()
