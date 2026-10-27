"""Notes on a queue item: what the owner says stays in it (schema, `relay queue note`, `show`, the session-file refusal, the waiting-question
hook). Scratch repositories in a temp dir; time is a value passed in."""
import datetime as dt
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq
git = tq.git
QUEUE = ".relay/queue/"
ROOT = tq.ROOT
FOUND = "2026-10-01T00:00:00Z"        # found_at of every helper item
T1, T2, T3 = "2026-10-05T10:00:00Z", "2026-10-05T11:00:00Z", "2026-10-06T09:00:00Z"
NOW = "2026-10-10T00:00:00Z"
OPTIONS = ["a. Keep it.", "b. Remove it."]


def raw(**changes):
    """A decoded item with these keys set, around the library, so a bad note reaches `check` as a file could carry it."""
    data = json.loads(tq.feature_item("Job"))
    data.update(changes)
    return data


def problems(**changes):
    return rq.check("job", raw(**changes))


def decision(**changes):
    out = {"asked_at": T1, "number": 1, "question": ["**1. Keep it?**"], "options": OPTIONS}
    out.update(changes)
    return out


class NotesShape(unittest.TestCase):
    """Each rule of the design (5.1) fails on the case that breaks it, worked out by hand."""

    def test_good_notes_are_accepted(self):
        notes = [{"at": T1, "said": ["words"]}, {"at": T2, "fact": ["Measured 5 Oct: 3 files."]},
                 decision(asked_at=T3, answered_at="2026-10-06T10:00:00Z", answer=["1. a", "because"], reading=["front: keep"])]
        self.assertEqual(problems(notes=notes), [])

    def test_empty_notes_refused(self):
        self.assertTrue(any("non-empty list" in p for p in problems(notes=[])))

    def test_note_has_one_kind(self):
        both = problems(notes=[{"at": T1, "said": ["a"], "fact": ["b"]}])
        none = problems(notes=[{"at": T1}])
        self.assertTrue(any("more than one of fact, said" in p for p in both), both)
        self.assertTrue(any("none of said, fact, question" in p for p in none), none)

    def test_note_times(self):
        self.assertTrue(any("at is not a UTC time" in p for p in problems(notes=[{"at": "yesterday", "said": ["a"]}])))
        # found_at is 1 Oct: a note dated 30 Sep cannot exist
        self.assertTrue(any("dated before found_at" in p for p in problems(notes=[{"at": "2026-09-30T00:00:00Z", "said": ["a"]}])))
        # answered one hour before it was asked
        early = decision(answered_at="2026-10-05T09:00:00Z", answer=["a"])
        self.assertTrue(any("answered_at is before asked_at" in p for p in problems(notes=[early])))

    def test_decision_needs_question_options_number(self):
        for bad, text in ((decision(question=[]), "question is not"), (decision(options=["a. only one"]), "options are not"),
                          (decision(options=["b. wrong", "a. order"]), "options are not"), (decision(number=0), "number is not")):
            self.assertTrue(any(text in p for p in problems(notes=[bad])), (bad, text))

    def test_answer_and_reading(self):
        no_answer = decision(answered_at=T2)                      # answered_at without answer
        no_stamp = decision(answer=["a"])                         # answer without answered_at
        reading_only = decision(reading=["front: yes"])           # a reading with no answer
        for bad, text in ((no_answer, "exactly when"), (no_stamp, "exactly when"), (reading_only, "reading needs an answer")):
            self.assertTrue(any(text in p for p in problems(notes=[bad])), (bad, text))

    def test_notes_in_date_order(self):
        late_first = [{"at": T2, "said": ["b"]}, {"at": T1, "said": ["a"]}]
        self.assertTrue(any("date order" in p for p in problems(notes=late_first)))

    def test_note_unknown_key(self):
        self.assertTrue(any("unknown key extra" in p for p in problems(notes=[{"at": T1, "said": ["a"], "extra": 1}])))

    def test_parse_gives_typed_notes_and_serialize_writes_them_back(self):
        notes = [{"at": T1, "said": ["words"]}, decision(asked_at=T2, answered_at=T3, answer=["1. a"])]
        text = json.dumps(raw(notes=notes))
        item = rq.parse("job", text)
        self.assertEqual([n.kind for n in item["notes"]], ["said", "decision"])
        self.assertEqual(item["notes"][1].answer, ["1. a"])
        self.assertEqual(json.loads(rq.serialize("job", item))["notes"], notes)


def with_notes(text, notes):
    return tq.raw_item(text, notes=notes)


class NoteCommand(tq.Base):
    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {QUEUE + "job.json": tq.feature_item("Job"),
                                      QUEUE + "old.json": tq.with_fields(tq.feature_item("Old"), taken_at=tq.TAKEN_AT, taken_by="wt/a",
                                                                         closed_at=tq.CLOSED_AT, evidence="abc1234")}, "seed")

    def note(self, slug="job", now=NOW, **fields):
        fields.setdefault("kind", next(k for k in ("said", "fact", "question", "answer") if k in fields))
        return rq.note(self.main, slug, fields, now=now, **tq.QUIET)

    def notes(self, slug="job"):
        return rq.notes_of(self.item(slug))

    def test_said_is_noted_verbatim_with_the_time_now(self):
        self.note(said=["Разве проблема была не в этом ?", "  второй  "])
        # default time is `now` (NOW), the lines are kept byte for byte
        self.assertEqual(self.notes(), [rq.Note("said", NOW, ["Разве проблема была не в этом ?", "  второй  "])])

    def test_note_lands_one_file_on_an_open_and_on_a_closed_item(self):
        for slug in ("job", "old"):
            self.note(slug, fact=["Measured 9 Oct: 4 files."])
            self.assertEqual(git(self.main, "show", "--name-only", "--format=", "HEAD").split(), [QUEUE + slug + ".json"])
        self.assertEqual(self.item("old")["state"], "done")       # a note changes nothing else

    def test_note_backdated_in_order(self):
        self.note(said=["late"], at=T3)
        self.note(said=["early"], at=T1)
        self.note(fact=["middle"], at=T2)
        # placed by date, not by the order of the calls
        self.assertEqual([n.text[0] for n in self.notes()], ["early", "middle", "late"])

    def test_note_appends_only(self):
        self.note(said=["first"], at=T1)
        before = git(self.main, "show", "HEAD:" + QUEUE + "job.json")
        self.note(fact=["second"], at=T2)
        after = json.loads(git(self.main, "show", "HEAD:" + QUEUE + "job.json"))
        self.assertEqual(after["notes"][0], json.loads(before)["notes"][0])
        self.assertEqual(len(after["notes"]), 2)

    def test_question_prints_the_block_and_the_answer_fills_it(self):
        out = self.note(question=["**1. Keep it?**", "Intro."], options=OPTIONS, number=1, at=T1)
        # the printed block is the question lines then the options, as the owner will see them
        self.assertTrue(out.endswith("**1. Keep it?**\nIntro.\na. Keep it.\nb. Remove it."), out)
        self.assertEqual([(n.kind, n.answered_at) for n in self.notes()], [("decision", None)])
        self.note(answer=["1. a", "keep, it is cheap"], reading=["Front: keep"], at=T2)
        n = self.notes()[0]
        self.assertEqual((n.answered_at, n.answer, n.reading, n.text), (T2, ["1. a", "keep, it is cheap"], ["Front: keep"], ["**1. Keep it?**", "Intro."]))

    def test_one_reply_answers_two_questions(self):
        self.note(question=["**1. First?**"], options=OPTIONS, number=1, at=T1)
        self.note(question=["**2. Second?**"], options=OPTIONS, number=2, at=T1)
        self.note(answer=["1. a", "2. a"], to=[1, 2], at=T2)
        self.assertEqual([n.answer for n in self.notes()], [["1. a", "2. a"]] * 2)

    def test_answer_with_several_waiting_and_no_to_names_the_next_step(self):
        self.note(question=["**1. First?**"], options=OPTIONS, number=1, at=T1)
        self.note(question=["**2. Second?**"], options=OPTIONS, number=2, at=T1)
        with self.assertRaises(rq.Refused) as ctx:
            self.note(answer=["1. a"], at=T2)
        message = str(ctx.exception)
        self.assertIn("waits on questions 1 ('First?') and 2 ('Second?')", message)
        self.assertIn("`to = [1]`", message)
        self.assertEqual([n.answered_at for n in self.notes()], [None, None])      # nothing noted

    def test_answer_with_none_waiting_names_the_next_step(self):
        with self.assertRaises(rq.Refused) as ctx:
            self.note(answer=["1. a"])
        self.assertIn("record the question first, or keep these words as `said`", str(ctx.exception))

    def test_unknown_slug_names_the_next_step(self):
        with self.assertRaises(rq.Refused) as ctx:
            self.note("nothing", said=["x"])
        self.assertIn("add the item first (`relay queue add`)", str(ctx.exception))

    def test_at_in_the_future_before_found_or_before_the_question_is_refused(self):
        for at, text in (("2026-10-11T00:00:00Z", "in the future"), ("2026-09-25T10:00:00Z", "before the item was found (" + FOUND + ")")):
            with self.assertRaises(rq.Refused) as ctx:
                self.note(said=["x"], at=at)
            self.assertIn(text, str(ctx.exception))
        self.note(question=["**1. Q?**"], options=OPTIONS, number=1, at=T2)
        with self.assertRaises(rq.Refused) as ctx:
            self.note(answer=["1. a"], at=T1)                      # one hour before it was asked
        self.assertIn("before question 1 was asked", str(ctx.exception))

    def test_note_refuses_session_path_in_fact(self):
        with self.assertRaises(rq.Refused) as ctx:
            self.note(fact=["See /private/tmp/claude-501/x/scratchpad/reports/design.md for the numbers."])
        self.assertIn("names a session file", str(ctx.exception))
        self.assertEqual(self.notes(), [])

    def test_note_keeps_owner_words_with_path(self):
        words = ["Look at /private/tmp/claude-501/x/scratchpad/reports/design.md"]
        self.note(said=words)
        self.note(question=["**1. Q?**"], options=OPTIONS, number=1, at=T1)
        self.note(answer=["a, see /tmp/foo/bar.md"], at=T2)
        notes = self.notes()
        self.assertEqual(notes[0].text if notes[0].kind == "said" else notes[1].text, words)
        self.assertEqual([n.answer for n in notes if n.kind == "decision"], [["a, see /tmp/foo/bar.md"]])

    def test_a_duplicate_waiting_number_is_refused(self):
        self.note(question=["**1. Q?**"], options=OPTIONS, number=1, at=T1)
        with self.assertRaises(rq.Refused) as ctx:
            self.note(question=["**1. Again?**"], options=OPTIONS, number=1, at=T2)
        self.assertIn("use the next number", str(ctx.exception))


class NoteInput(tq.Base):
    def read(self, text):
        path = os.path.join(self.tmp, "in.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return rq.read_note_input(path)

    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib")
    def test_the_input_forms(self):
        got = self.read("question = '''**1. Q?**\nintro'''\noptions = ['a. x', 'b. y']\nnumber = 1\nat = '2026-10-05T10:00:00Z'\n")
        self.assertEqual((got["kind"], got["question"], got["number"]), ("question", ["**1. Q?**", "intro"], 1))
        self.assertEqual(self.read("answer = 'a'\nto = [1, 2]\nreading = 'r'\n")["to"], [1, 2])

    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib")
    def test_two_kinds_none_or_a_stray_key_are_refused_with_the_next_step(self):
        cases = (("said = 'a'\nfact = 'b'\n", "both `said` and `fact`; a note is one of"), ("at = '2026-10-05T10:00:00Z'\n", "none of `said`"),
                 ("said = 'a'\nto = [1]\n", "`to` does not go with `said`"), ("question = 'q'\n", "needs `options`"),
                 ("said = 'a'\nwhat = 'x'\n", "unknown key `what`"))
        for text, want in cases:
            with self.assertRaises(rq.Refused) as ctx:
                self.read(text)
            self.assertIn(want, str(ctx.exception))

    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib")
    def test_f1_options_in_another_shape_are_refused_as_input(self):
        # the front skill used to show `a (recommended) x`; each form is refused before anything lands, naming the form and the bad line
        for bad in ("a (recommended) x", "a) x"):
            with self.assertRaises(rq.Refused) as ctx:
                self.read(f"question = 'Q?'\nnumber = 1\noptions = ['{bad}', 'b. y']\n")
            text = str(ctx.exception)
            self.assertTrue(text.startswith("nothing noted:"), text)
            self.assertIn("`options`", text)
            self.assertIn("a. ", text)
            self.assertIn(bad, text)
        self.assertEqual(self.read("question = 'Q?'\nnumber = 1\noptions = ['a. x (recommended)', 'b. y']\n")["options"], ["a. x (recommended)", "b. y"])

    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib")
    def test_f1_the_front_skill_shows_the_stored_option_form(self):
        with open(os.path.join(ROOT, "plugins", "front", "skills", "front", "SKILL.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("a (recommended) <one line>", text)
        self.assertIn("a. <one line> (recommended)", text)

    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib")
    def test_f2_an_unquoted_toml_time_is_taken(self):
        # TOML reads 2026-10-27T01:20:00Z as a datetime; it is the same UTC time as the quoted string
        self.assertEqual(self.read("said = 'hi'\nat = 2026-10-27T01:20:00Z\n")["at"], "2026-10-27T01:20:00Z")
        self.assertEqual(self.read("said = 'hi'\nat = '2026-10-27T01:20:00Z'\n")["at"], "2026-10-27T01:20:00Z")
        with self.assertRaises(rq.Refused) as ctx:
            self.read("said = 'hi'\nat = '2026-10-27 01:20'\n")
        self.assertIn("`at` must be a UTC time", str(ctx.exception))
        with self.assertRaises(rq.Refused):
            self.read("said = 'hi'\nat = 2026-10-27T01:20:00+03:00\n")          # not UTC: refused


class SessionFiles(tq.Base):
    def add(self, **kw):
        args = dict(kind="fix", title="Something is wrong", why="it matters", what="what is wrong", failing="the case fails", failing_kind="claim", minutes=10)
        args.update(kw)
        kind, title = args.pop("kind"), args.pop("title")
        return rq.add(self.main, kind, title, **args, **tq.QUIET)

    def test_add_refuses_session_path(self):
        # the fix item's failing case: why line 2 names a scratchpad report
        with self.assertRaises(rq.Refused) as ctx:
            self.add(why="Because\nsee /private/tmp/claude-501/-Users-x/abc/scratchpad/reports/design-dev-metrics.md")
        self.assertIn("line 2 of `why` names a session file", str(ctx.exception))
        self.assertIn("Put the fact itself in", str(ctx.exception))
        with self.assertRaises(rq.Refused):
            self.add(why="the numbers are in scratchpad reports/design-dev-metrics.md")      # the word with a path in the same sentence
        self.assertEqual(self.branches(), [])

    def test_add_accepts_scratchpad_word(self):
        # the word alone, and a file name in another sentence, pass
        self.add(why="19 open items name a scratchpad path. The fix is in lib/x.py.")

    def test_done_evidence_refuses_session_path(self):
        self.add(kind="feature", title="A feature", failing="", failing_kind="")
        slug = "a-feature"
        with self.assertRaises(rq.Refused) as ctx:
            rq.close_with_evidence(self.main, slug, "/private/tmp/claude-501/x/report.md", **tq.QUIET)
        self.assertIn("names a session file", str(ctx.exception))
        rq.close_with_evidence(self.main, slug, tq.git(self.main, "rev-parse", "master"), **tq.QUIET)
        self.assertEqual(self.item(slug)["state"], "done")

    def test_f6_drop_keeps_the_owners_words_with_a_path(self):
        # drop's `why` is the owner's words (bin/relay usage): never altered, never path-checked
        self.add()
        rq.drop(self.main, "something-is-wrong", "дубль, см. /tmp/x/y.md", **tq.QUIET)
        self.assertEqual(self.item("something-is-wrong")["dropped_why"], ["дубль, см. /tmp/x/y.md"])

    def test_f3_add_from_names_a_step_the_front_can_take(self):
        report = os.path.join(self.tmp, "review.json")
        finding = {"id": "F1", "summary": "a thing is wrong", "path": "lib/x.py", "line": 3, "severity": "MEDIUM", "rank": "medium", "kind": "inside",
                   "failing_case": ["run it", "see /private/tmp/claude-501/x/scratchpad/trial/tally"], "pass_cases": ["ok"],
                   "details": ["d"], "evidence": ["e"], "fix_hint": ["h"]}
        with open(report, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "type": "review", "base": "master", "reviewed": "a" * 40, "scope": ["s"], "notes": [], "findings": [finding]}, handle)
        with self.assertRaises(rq.Refused) as ctx:
            rq.add_from(self.main, report, "F1", why="w", minutes=5, **tq.QUIET)
        text = str(ctx.exception)
        self.assertIn("names a session file", text)
        self.assertIn("relay queue add --input", text)          # the step that works: its own text, without the session file
        self.assertEqual(self.branches(), [])
        finding["failing_case"] = ["run it"]
        with open(report, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "type": "review", "base": "master", "reviewed": "a" * 40, "scope": ["s"], "notes": [], "findings": [finding]}, handle)
        rq.add_from(self.main, report, "F1", why="w", minutes=5, **tq.QUIET)          # no session path: queued as before
        with self.assertRaises(rq.Refused) as ctx:
            self.add(why="see /tmp/x/y.md")
        self.assertNotIn("relay queue add --input", str(ctx.exception))               # add --input keeps its own advice

    def test_check_keeps_old_links_valid(self):
        old = tq.with_fields(tq.feature_item("Job"), why=["see /private/tmp/claude-501/x/scratchpad/reports/a.md"])
        self.write_commit(self.main, {QUEUE + "job.json": old}, "an old item")
        self.assertEqual(rq.check_files(self.main), [])


class ShowAndSearch(tq.Base):
    def setUp(self):
        super().setUp()
        notes = [{"at": T1, "said": ["Я вижу ответы но не вопрос"]}, {"at": T2, "fact": ["Measured 5 Oct: 31.9%."]},
                 decision(asked_at=T3, answered_at="2026-10-06T10:00:00Z", answer=["1. a", "потому что дёшево"], reading=["Front: keep"]),
                 decision(asked_at="2026-10-06T11:00:00Z", number=2, question=["**2. Second?**"])]
        self.write_commit(self.main, {QUEUE + "job.json": with_notes(tq.feature_item("Job metrics"), notes),
                                      QUEUE + "other.json": tq.feature_item("Other thing")}, "seed")
        self.items = rq.read_queue(self.main, closed=True)

    def test_show_prints_notes_oldest_first_with_question_options_answer_and_reading(self):
        text = rq.show_text(next(i for i in self.items if i["slug"] == "job"), tz=dt.timezone.utc)
        lines = text[text.index("Notes:"):].split("\n")
        # worked out by hand: said 5 Oct 10:00, fact 11:00, question 1 asked 6 Oct 09:00 and answered 10:00, question 2 unanswered
        self.assertEqual(lines[:6], ["Notes:", "  5 Oct 10:00 the owner said:", "    “Я вижу ответы но не вопрос”",
                                     "  5 Oct 11:00 fact (front):", "    Measured 5 Oct: 31.9%.", "  6 Oct 09:00 question 1, asked:"])
        self.assertIn("    - a. Keep it.", lines)
        self.assertIn("  6 Oct 10:00 the owner answered question 1 (whole reply):", lines)
        self.assertIn("    “1. a", lines)
        self.assertIn("    потому что дёшево”", lines)
        self.assertIn("    front's reading (owner can reverse): Front: keep", lines)
        self.assertEqual(lines[-1], "    not answered yet")
        self.assertLess(text.index("Why:"), text.index("Notes:"))

    def test_words_find_items(self):
        found, how = rq.find_for_show(self.items, "дёшево")          # only in a note's answer
        self.assertEqual(([i["slug"] for i in found], how), (["job"], "words"))
        self.assertEqual([i["slug"] for i in rq.find_for_show(self.items, "other")[0]], ["other"])
        self.assertEqual(rq.find_for_show(self.items, "no such words")[0], [])
        self.assertEqual(rq.find_for_show(self.items, "job")[1], "slug")
        self.assertEqual(rq.match_lines(rq.search_items(self.items, "it matters")),
                         ["job: Job metrics (open, 2 decisions)", "other: Other thing (open, 0 decisions)"])


class Cli(tq.Base):
    """bin/relay: `note` is a write (never dispatched to a view), `show` takes words."""

    def run_relay(self, *args):
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "queue", *args, "-C", self.main], capture_output=True, text=True)
        return done.returncode, done.stdout, done.stderr

    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib")
    def test_queue_note_dispatch(self):
        self.write_commit(self.main, {QUEUE + "job.json": tq.feature_item("Job")}, "seed")
        path = os.path.join(self.tmp, "n.toml")
        with open(path, "w") as handle:
            handle.write("said = 'hello owner words'\n")
        self.assertEqual(self.run_relay("note", "job")[0], 2)               # a usage error naming --input, not "no queue view"
        self.assertIn("--input", self.run_relay("note", "job")[2])
        code, out, err = self.run_relay("note", "job", "--input", path)
        self.assertEqual(code, 0, err)
        code, out, err = self.run_relay("show", "owner words")               # found by the note's words, shown in full
        self.assertIn("hello owner words", out)
        self.assertEqual(self.run_relay("show", "nothing like it")[0], 2)

    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib")
    def test_f5_show_by_words_says_it_was_found_by_words(self):
        self.write_commit(self.main, {QUEUE + "job.json": tq.feature_item("Job")}, "seed")
        path = os.path.join(self.tmp, "n.toml")
        with open(path, "w") as handle:
            handle.write("said = 'hello owner words'\n")
        self.assertEqual(self.run_relay("note", "job", "--input", path)[0], 0)
        _, by_words, _ = self.run_relay("show", "owner words")
        self.assertTrue(by_words.startswith("found by words 'owner words':\n"), by_words)
        _, by_slug, _ = self.run_relay("show", "job")
        self.assertNotIn("found by words", by_slug)                          # the exact slug: no header


class AskHook(tq.Base):
    def setUp(self):
        super().setUp()
        waiting = decision(asked_at="2026-10-09T22:00:00Z", question=["**1. Should work that never lands get its own record?**"])
        self.write_commit(self.main, {QUEUE + "job.json": with_notes(tq.feature_item("Job"), [waiting]),
                                      QUEUE + "plain.json": tq.feature_item("Plain")}, "seed")

    def test_hook_names_waiting_question(self):
        # asked 9 Oct 22:00, now 10 Oct 00:00: two hours ago
        lines = rq.waiting_lines(self.main, 7, 5, now=NOW)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("Waiting for the owner: job question 1 'Should work that never lands get its own record?', asked 2h ago;"), lines[0])

    def test_hook_skips_old_question(self):
        self.assertEqual(rq.waiting_lines(self.main, 7, 5, now="2026-10-17T00:00:01Z"), [])     # 7 days and one second
        self.assertEqual(len(rq.waiting_lines(self.main, 7, 5, now="2026-10-16T22:00:00Z")), 1)  # exactly 7 days

    def test_hook_limits_lines(self):
        notes = [decision(asked_at="2026-10-09T22:0%d:00Z" % n, number=n, question=["**%d. Q%d?**" % (n, n)]) for n in range(1, 4)]
        self.write_commit(self.main, {QUEUE + "job.json": with_notes(tq.feature_item("Job"), notes)}, "three")
        self.assertEqual(len(rq.waiting_lines(self.main, 7, 2, now=NOW)), 2)

    def test_hook_silent_without_questions(self):
        self.write_commit(self.main, {QUEUE + "job.json": tq.feature_item("Job")}, "none waiting")
        parsed = []
        real = rq.parse
        with mock.patch.object(rq, "parse", side_effect=lambda *a, **k: parsed.append(a) or real(*a, **k)):
            self.assertEqual(rq.waiting_lines(self.main, 7, 5, now=NOW), [])
        self.assertEqual(parsed, [])         # no file names a question: the one git grep finds nothing and nothing is parsed

    def hook_output(self):
        hook = os.path.join(ROOT, "plugins", "front", "hooks", "ask_waiting.py")
        data = json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": self.main})
        done = subprocess.run([sys.executable, hook], input=data, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=""))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        return done.stdout

    def test_f4_hook_script_prints_the_reminder_for_a_question_asked_an_hour_ago(self):
        # asked one real hour ago, so it is inside the 7 days whatever the clock says; the output is asserted unconditionally
        asked = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write_commit(self.main, {QUEUE + "job.json": with_notes(tq.feature_item("Job"), [decision(asked_at=asked)])}, "fresh question")
        out = self.hook_output()
        self.assertNotEqual(out, "")
        self.assertTrue(json.loads(out)["hookSpecificOutput"]["additionalContext"].startswith("Waiting for the owner: job question 1"), out)

    def test_f4_hook_script_is_silent_when_nothing_waits(self):
        self.write_commit(self.main, {QUEUE + "job.json": tq.feature_item("Job")}, "none waiting")
        self.assertEqual(self.hook_output(), "")

    def test_hook_script_clamps_settings_and_prints_json(self):
        hook = os.path.join(ROOT, "plugins", "front", "hooks", "ask_waiting.py")
        data = json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": self.main})
        done = subprocess.run([sys.executable, hook], input=data, capture_output=True, text=True,
                              env=dict(os.environ, PYTHONPATH=""))
        # the fixture question is old by the real clock, so only the no-error exit is asserted here; the output is asserted in test_f4_*
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        sys.path.insert(0, os.path.join(ROOT, "plugins", "front", "hooks"))
        try:
            import ask_waiting
        finally:
            sys.path.pop(0)
        self.assertEqual(ask_waiting.setting({"front": {"ask_reminder_days": 99}}, "ask_reminder_days", ask_waiting.DAYS), 30)
        self.assertEqual(ask_waiting.setting({"front": {"ask_reminder_lines": 0}}, "ask_reminder_lines", ask_waiting.LINES), 1)
        self.assertEqual(ask_waiting.setting({}, "ask_reminder_days", ask_waiting.DAYS), 7)
        self.assertEqual(ask_waiting.setting({"front": {"ask_reminder_days": "x"}}, "ask_reminder_days", ask_waiting.DAYS), 7)


if __name__ == "__main__":
    unittest.main()
