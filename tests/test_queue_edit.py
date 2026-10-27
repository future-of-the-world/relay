"""`relay queue edit` (one exact fragment, quoted text byte-equal, a dated why), `add` with `said`, the stale-check rule, `history`,
and the hand-edit fence of the merge hook. Scratch repositories in a temp dir; time is a value passed in."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402
import test_check_record as tcr  # noqa: E402

rq = tq.rq
git = tq.git
SLUG = "job-item"
QUEUE = ".relay/queue/"
FOUND = "2026-10-01T00:00:00Z"
NOW = "2026-10-10T00:00:00Z"
QUIET = tq.QUIET
merge_hook = tcr.merge_hook


def item_text(kind="feature", **fields):
    item = rq.new_item(kind, 0, 10, FOUND, "test", "Job item breaks", "what is wanted", "it matters",
                       **({"failing": "the case fails", "failing_kind": "claim"} if kind == "fix" else {}))
    item.update(fields)
    return rq.serialize(SLUG, item)


class Quoted(unittest.TestCase):
    """quoted_spans: the exact rule of which text is protected (design section 4)."""

    def test_double_guillemet_and_curly_spans(self):
        # three spans, each with its marks
        self.assertEqual(rq.quoted_spans(['a "b c" d «e» f “g”']), ['"b c"', "«e»", "“g”"])

    def test_single_quote_opens_after_space_and_closes_before_punctuation(self):
        # 'persist structured' opens after "(owner, 22 Oct: " (a space) and closes before ")"
        self.assertEqual(rq.quoted_spans(["(owner, 22 Oct: 'persist structured, operate with scripts')"]),
                         ["'persist structured, operate with scripts'"])

    def test_apostrophe_in_a_word_opens_nothing(self):
        self.assertEqual(rq.quoted_spans(["the owner's push and relay's rule"]), [])

    def test_a_quote_over_two_lines_is_one_span(self):
        self.assertEqual(rq.quoted_spans(['Owner: "first', "middle", 'last"']), ['"first\nmiddle\nlast"'])

    def test_unbalanced_double_quote_is_none(self):
        self.assertIsNone(rq.quoted_spans(['one " mark']))


class EditCommand(tq.Base):
    def seed(self, kind="feature", **fields):
        self.write_commit(self.main, {QUEUE + SLUG + ".json": item_text(kind, **fields)}, "seed")

    def edit(self, field, old, new, because="found wrong on 10 Oct", now=NOW):
        return rq.edit(self.main, SLUG, field, old, new, because, now=now, **QUIET)

    def current(self):
        return self.item(SLUG)

    def test_replaces_the_fragment_and_adds_a_dated_why_note(self):
        self.seed(why=['all others green, including the new check; "recall-decision never ran" said the log'])
        self.edit("why", "all others green, including the new check", "all others green except the new check")
        item = self.current()
        # only the fragment changed; the quoted span is byte-equal
        self.assertEqual(item["why"], ['all others green except the new check; "recall-decision never ran" said the log'])
        notes = rq.notes_of(item)
        self.assertEqual([(n.kind, n.at, n.text) for n in notes], [("fact", NOW, ["Edited why: found wrong on 10 Oct"])])

    def test_quoted_text_is_never_changed(self):
        self.seed(why=['He said "Как мы работаем с файлами очереди ?" and more'])
        with self.assertRaisesRegex(rq.Refused, "changes quoted text"):
            self.edit("why", "Как мы работаем", "Как работаем")
        self.assertEqual(self.current()["why"], ['He said "Как мы работаем с файлами очереди ?" and more'])
        self.assertIsNone(rq.notes_of(self.current()) or None)         # nothing was written

    def test_single_quoted_span_is_protected(self):
        self.seed(what=["(owner, 22 Oct: 'persist structured, operate with scripts')"])
        with self.assertRaisesRegex(rq.Refused, "quoted text"):
            self.edit("what", "persist structured", "persist")

    def test_apostrophe_in_a_word_is_editable(self):
        self.seed(why=["the owner's push was late"])
        self.edit("why", "push was late", "push came late")
        self.assertEqual(self.current()["why"], ["the owner's push came late"])

    def test_a_span_over_two_lines_is_protected(self):
        self.seed(why=['Owner: "first', "middle", 'last"'])
        with self.assertRaisesRegex(rq.Refused, "quoted text"):
            self.edit("why", "middle", "centre")

    def test_unbalanced_quotes_refuse_the_whole_field(self):
        self.seed(why=['one " mark', "other words"])
        with self.assertRaisesRegex(rq.Refused, "quotes do not balance"):
            self.edit("why", "other words", "more words")

    def test_old_must_be_found_exactly_once(self):
        self.seed(why=["same same"])
        with self.assertRaisesRegex(rq.Refused, "2 times"):
            self.edit("why", "same", "other")
        with self.assertRaisesRegex(rq.Refused, "0 times"):
            self.edit("why", "absent", "other")

    def test_a_note_is_not_an_editable_field(self):
        path = os.path.join(self.tmp, "e.toml")
        with open(path, "w") as handle:
            handle.write('field = "notes"\nold = "a"\nnew = "b"\nbecause = "c"\n')
        with self.assertRaisesRegex(rq.Refused, "only added"):
            rq.read_edit_input(path)

    def test_because_is_needed(self):
        self.seed()
        with self.assertRaisesRegex(rq.Refused, "say why"):
            self.edit("why", "it matters", "it matters more", because="  ")

    def test_a_taken_item_is_edited_and_the_reply_names_the_branch(self):
        self.seed("fix", taken_at="2026-10-02T00:00:00Z", taken_by="wt/z")
        out = self.edit("why", "it matters", "it matters a lot")
        self.assertIn("taken by wt/z", out)
        self.assertEqual(self.current()["why"], ["it matters a lot"])

    def test_test_is_edited_only_on_a_closed_item_to_an_existing_test(self):
        self.write_commit(self.main, {"tests/t.py": "def test_new():\n    pass\n"}, "tests")
        self.seed(taken_at="2026-10-02T00:00:00Z", taken_by="wt/z", closed_at="2026-10-03T00:00:00Z", test="tests/t.py::test_old")
        with self.assertRaisesRegex(rq.Refused, "does not hold a test named test_missing"):
            self.edit("test", "tests/t.py::test_old", "tests/t.py::test_missing")
        self.edit("test", "tests/t.py::test_old", "tests/t.py::test_new")
        self.assertEqual(self.current()["test"], "tests/t.py::test_new")

    def test_test_of_an_open_item_is_refused(self):
        self.seed(test=None)
        with self.assertRaisesRegex(rq.Refused, "only after it is closed"):
            self.edit("test", "x", "tests/t.py::test_new")

    def test_history_prints_the_earlier_text_from_git(self):
        self.seed(why=["old claim here"])
        self.edit("why", "old claim", "new claim")
        text = rq.history(self.main, SLUG)
        self.assertIn("why was:", text)
        self.assertIn("  old claim here", text)


class AddWithSaid(tq.Base):
    def test_the_owners_words_become_a_said_note_byte_equal(self):
        rq.add(self.main, "feature", "Make it faster please", why="it matters", minutes=10, said="Do it \"now\"\nplease", now=NOW, **QUIET)
        item = self.item("make-it-faster-please")
        notes = rq.notes_of(item)
        self.assertEqual([(n.kind, n.at, n.text) for n in notes], [("said", NOW, ['Do it "now"', "please"])])
        self.assertNotIn("now", " ".join(item["why"]))


class StaleCheck(tq.Base):
    """A fix's check counts only for the problem it judged: Q1 of the check against Q1 of the item at the default tip."""

    def test_an_edit_after_the_check_makes_it_stale(self):
        self.write_commit(self.main, {QUEUE + SLUG + ".json": item_text("fix", taken_at="2026-10-02T00:00:00Z", taken_by="wt/z")}, "seed")
        judged = rq._q1(self.item(SLUG))
        self.assertIsNone(rq.stale_check(self.main, "master", SLUG, judged, "a" * 12))
        rq.edit(self.main, SLUG, "failing_case", "the case fails", "the other case fails", "the problem was misstated", now=NOW, **QUIET)
        reason = rq.stale_check(self.main, "master", SLUG, judged, "a" * 12)
        self.assertIn("failing_case", reason)
        self.assertIn("check the fix again", reason)


class Fence(tq.Base):
    """The merge hook refuses a hand edit of an item's text and names the command; the library's own writes pass."""

    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {QUEUE + SLUG + ".json": item_text("feature", why=["it matters"], notes=[rq.Note("fact", NOW, ["measured"])])}, "seed")
        self.wt = self.worktree("t")

    def branch_with(self, files, message="work"):
        self.write_commit(self.wt, files, message)

    def judge(self):
        merge_hook.step_queue(self.main, "master", "wt/t")

    def test_a_hand_edit_of_why_is_refused_naming_the_command(self):
        self.branch_with({QUEUE + SLUG + ".json": item_text("feature", why=["changed by hand"], notes=[rq.Note("fact", NOW, ["measured"])])})
        with self.assertRaisesRegex(merge_hook.Refused, "why changed by hand; use relay queue edit"):
            self.judge()

    def test_events_and_appended_notes_pass(self):
        text = item_text("feature", why=["it matters"], taken_at="2026-10-11T00:00:00Z", taken_by="wt/t",
                         notes=[rq.Note("fact", NOW, ["measured"]), rq.Note("fact", "2026-10-11T00:00:00Z", ["more"])])
        self.branch_with({QUEUE + SLUG + ".json": text})
        self.judge()

    def test_an_earlier_note_rewritten_is_refused(self):
        self.branch_with({QUEUE + SLUG + ".json": item_text("feature", why=["it matters"], notes=[rq.Note("fact", NOW, ["measured differently"])])})
        with self.assertRaisesRegex(merge_hook.Refused, "an earlier note changed by hand"):
            self.judge()

    def test_test_changed_on_an_item_the_branch_did_not_close_is_refused(self):
        # written around the library, as a hand edit would be: a test with no closed_at is also malformed, but the fence names the cause first
        text = tq.raw_item(item_text("feature", why=["it matters"], notes=[rq.Note("fact", NOW, ["measured"])]), test="tests/t.py::test_x")
        self.branch_with({QUEUE + SLUG + ".json": text})
        with self.assertRaisesRegex(merge_hook.Refused, "test changed by hand"):
            self.judge()

    def test_a_close_by_the_branch_sets_test_and_passes(self):
        self.branch_with({"tests/t.py": "def test_x():\n    pass\n",
                          QUEUE + SLUG + ".json": item_text("feature", why=["it matters"], taken_at="2026-10-11T00:00:00Z", taken_by="wt/t",
                                                            closed_at="2026-10-12T00:00:00Z", test="tests/t.py::test_x",
                                                            notes=[rq.Note("fact", NOW, ["measured"])])})
        self.judge()

    def test_a_library_edit_taken_into_the_branch_passes(self):
        rq.edit(self.main, SLUG, "why", "it matters", "it matters more", "found on 10 Oct", now=NOW, **QUIET)
        git(self.wt, "merge", "-q", "--no-edit", "master")
        self.branch_with({"lib/x.py": "x = 1\n"})
        self.judge()

    def test_a_migrate_module_exempts_the_reshaping(self):
        self.branch_with({"lib/relay_thing_migrate.py": "x = 1\n",
                          QUEUE + SLUG + ".json": item_text("feature", why=["reshaped"], notes=[rq.Note("fact", NOW, ["measured"])])})
        self.judge()

    def test_a_reshaping_without_a_migrate_module_is_refused(self):
        self.branch_with({"lib/relay_queue.py": "ORDER = 1\n",
                          QUEUE + SLUG + ".json": item_text("feature", why=["reshaped"], notes=[rq.Note("fact", NOW, ["measured"])])})
        with self.assertRaisesRegex(merge_hook.Refused, "migrate module"):
            self.judge()


if __name__ == "__main__":
    unittest.main()
