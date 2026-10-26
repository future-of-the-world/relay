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
        self.assertEqual(wm.split_where("s", "bin/ci, the eval runner and its graders"), (["bin/ci the eval runner and its graders"], False))

    def test_a_first_word_with_a_bad_line_keeps_the_path_and_is_not_clean(self):
        self.assertEqual(wm.split_where("s", "lib/a.py:22,28-35, b.py"), (["lib/a.py:22 28-35", "b.py"], False))

    def test_a_string_with_no_place_gets_the_items_own_file(self):
        self.assertEqual(wm.split_where("job", "to be designed first"), ([".relay/queue/job.json to be designed first"], False))


class SplitWhereFixes(unittest.TestCase):
    def test_a_glued_note_does_not_put_its_comma_into_the_place_word(self):
        # F1: "bin/paid-cost" is the path; the text after the comma is the note, so the path word has no comma
        elements, clean = wm.split_where("s", "bin/paid-cost, the eval runner's aggregate-result.json, whatever records a bin/ci run")
        self.assertEqual(rq.parse_place(elements[0]).path, "bin/paid-cost")
        self.assertFalse(clean)

    def test_a_place_with_a_line_and_glued_text_still_parses(self):
        # F1: before, "lib/a.py:5, notes about it" was written with the comma after the line number and refused
        elements, clean = wm.split_where("s", "lib/a.py:5, notes about it")
        self.assertEqual((len(elements), rq.parse_place(elements[0]), clean), (1, rq.Place("lib/a.py", 5, None, "notes about it"), False))

    def test_a_second_glued_piece_keeps_the_comma_between_notes(self):
        # the first glue gives "bin/ci one"; the note then exists, so the next piece is joined with ", "
        self.assertEqual(wm.split_where("s", "bin/ci, one two, three four"), (["bin/ci one two, three four"], False))

    def test_a_line_list_keeps_its_first_line_as_the_place(self):
        # F3: "lib/a.py:22,28-35": line 22 is the place, 28-35 goes to the note
        elements, clean = wm.split_where("s", "lib/a.py:22,28-35, b.py")
        self.assertEqual((rq.parse_place(elements[0]), elements[1], clean), (rq.Place("lib/a.py", 22, None, "28-35"), "b.py", False))
        elements, clean = wm.split_where("s", "docs/setup.md:11-24,42")
        self.assertEqual((rq.parse_place(elements[0]), clean), (rq.Place("docs/setup.md", 11, 24, "42"), False))

    def test_a_range_with_a_note_is_unchanged_and_clean(self):
        self.assertEqual(wm.split_where("s", "lib/a.py:325-333 merge_settings"), (["lib/a.py:325-333 merge_settings"], True))


class QueueMigrateWhere(unittest.TestCase):
    def convert(self, **extra):
        import relay_queue_migrate as qm
        data = {"state": "open", "kind": "fix", "title": "T", **extra}
        return qm.convert("slug", data, "2026-10-01T00:00:00Z", None, None)

    def test_an_old_shape_where_string_becomes_a_list(self):
        # F4
        self.assertEqual(self.convert(where="bin/ci:25")["where"], ["bin/ci:25"])

    def test_a_blank_where_is_dropped_and_a_missing_one_stays_missing(self):
        self.assertNotIn("where", self.convert(where="  "))
        self.assertNotIn("where", self.convert())


class AddInputWhere(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "in.toml")
            with open(path, "w") as handle:
                handle.write("title = 'T'\nwhy = 'w'\ntime = '5m'\n" + text)
            return rq.read_add_input(path, rq.ADD_KEYS, ("title", "why", "time"))

    def test_a_list_where_in_the_input_file_reaches_add_as_the_list(self):
        # F5
        self.assertEqual(self.read('where = ["lib/x.py:5-9 note", "docs/"]\n')["where"], ["lib/x.py:5-9 note", "docs/"])

    def test_a_string_where_in_the_input_file_is_refused_naming_where(self):
        with self.assertRaises(rq.Refused) as caught:
            self.read('where = "a, b"\n')
        self.assertIn("`where`", str(caught.exception))


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
