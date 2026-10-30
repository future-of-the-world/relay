"""`relay digest`: the page from the queue difference between the stored head and the head now, when a digest or an alert is due, the Stop
hook that refuses once, the reversal line of `relay queue note`, and the texts. Scratch repositories in a temp dir; time is a value
passed in; nothing touches the live queue, the live events or the live evals."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

sys.path.insert(0, os.path.join(tq.ROOT, "lib"))
import relay_digest as rd  # noqa: E402

rq = rd.relay_queue
git = tq.git
Q = ".relay/queue/"
NOW = "2026-10-30T12:00:00Z"
OPTIONS = ["a. yes, no merge train", "b. a merge train"]
HOOK = os.path.join(tq.ROOT, "plugins", "front", "hooks", "digest_due.py")


def make(title, kind="feature", **fields):
    """(slug, file text) of an item found 1 Oct, with these fields set through the library."""
    slug = rq.slugify(title)
    new = rq.new_item(kind, 90, 10, "2026-10-01T00:00:00Z", "test", title, "what is wanted here", "it matters",
                      failing="the case fails" if kind == "fix" else "", pass_cases="the other case" if kind == "fix" else "",
                      where=["lib/a.py"], failing_kind="claim" if kind == "fix" else "")
    return slug, rq.serialize(slug, rq.changed(new, **fields))


def closed(title, kind="feature", **fields):
    proof = {"test": "tests/test_a.py::test_a"} if kind == "fix" else {"evidence": "abc1234"}      # a fix closes with a test, a feature with evidence
    return make(title, kind, taken_at="2026-10-02T00:00:00Z", taken_by="wt/z", closed_at="2026-10-03T00:00:00Z", **proof, **fields)


def decision(at, question, chosen="a", **extra):
    note = {"asked_at": at, "question": ["**%s**" % question], "options": OPTIONS, "decided_by": "front", "chosen": chosen, "because": ["principle 7"]}
    note.update(extra)
    return note


def with_notes(slug_text, notes):
    slug, text = slug_text
    return slug, tq.raw_item(text, notes=notes)


class DigestBase(tq.Base):
    def setUp(self):
        super().setUp()
        self.evals = os.path.join(self.tmp, "evals")
        os.makedirs(self.evals)
        patch = mock.patch.dict(os.environ, {"RELAY_HOME": os.path.join(self.tmp, "home")})
        patch.start()
        self.addCleanup(patch.stop)

    def commit(self, *items, extra=None, message="work"):
        files = {Q + slug + ".json": text for slug, text in items}
        files.update(extra or {})
        self.write_commit(self.main, files, message)

    def head(self):
        return git(self.main, "rev-parse", "refs/heads/master")

    def sent(self, at="2026-10-30T10:00:00Z", kind="sent"):
        rd.record_event(self.main, kind, at, self.head())

    def page(self, cfg=None, **kw):
        kw.setdefault("spend", lambda: (33.27, 200.0))
        kw.setdefault("evals", self.evals)
        return rd.page(self.main, "master", cfg or {}, now=NOW, **kw)

    def due(self, cfg=None, spend=None, now=NOW):
        return rd.due(self.main, "master", cfg or {}, now=now, spend=lambda: spend, evals=self.evals)

    def paid_run(self, name, ended):
        """A stored paid run that ended at `ended` (one hour long)."""
        start = rd.stamp_of(rd.epoch_of(ended) - 3600)
        rec = {"startedAt": start[:-1] + ".000Z", "durationSeconds": 3600, "partial": False, "aggregates": {"casesTotal": 31, "casesPassed": 31}}
        with open(os.path.join(self.evals, name + ".json"), "w") as handle:
            json.dump(rec, handle)

    def merged_lines(self, lines):
        return [x for x in lines if x.startswith("  - ")]


class Page(DigestBase):
    def test_closed_on_a_branch_before_the_event_and_merged_after_it_is_listed_once(self):
        # A is taken. The digest is sent. The change that closes A (closed_at 3 Oct, long before the event) reaches master only now:
        # the difference between the stored head and the head lists it, whatever time is written inside the record.
        self.commit(make("Alpha fix", "fix", taken_at="2026-10-02T00:00:00Z", taken_by="wt/z"))
        self.sent()
        self.assertEqual(self.merged_lines(self.page()), [])
        self.commit(closed("Alpha fix", "fix"))
        first = self.page()
        self.assertEqual(self.merged_lines(first), ["  - Alpha fix"])
        self.assertIn("Merged (fix 1, feature 0):", first)
        self.sent()                         # the page is sent: the same close is not listed again
        self.assertEqual(self.merged_lines(self.page()), [])

    def test_closed_and_merged_before_the_event_is_not_listed(self):
        self.commit(closed("Old change"))
        self.sent()
        # the closed item's file changes after the event (a fact note is added), yet it was already closed at the stored head
        self.commit(with_notes(closed("Old change"), [{"at": "2026-10-30T10:30:00Z", "fact": ["Measured 30 Oct: 3 files."]}]))
        lines = self.page()
        self.assertEqual(self.merged_lines(lines), [])
        self.assertTrue(lines[0].startswith("relay: nothing new since "), lines[0])

    def test_decision_dated_before_the_event_that_first_reaches_master_after_it_is_listed(self):
        self.sent("2026-10-30T10:00:00Z")
        # asked 20 Oct, long before the event at 30 Oct 10:00; it reaches master only now
        self.commit(with_notes(make("Cycle lands itself"), [decision("2026-10-20T00:00:00Z", "Does the cycle land a ready change itself?")]))
        lines = self.page()
        self.assertIn("1 decisions taken without you", lines[0])
        self.assertIn("  Cycle lands itself (not merged yet)", lines)
        self.assertIn("    **Does the cycle land a ready change itself?** chosen a. yes, no merge train (front: principle 7)", lines)

    def test_two_pages_with_nothing_merged_between_say_nothing_new(self):
        self.commit(closed("Beta change"))
        self.sent()
        self.commit(extra={"notes.txt": "x\n"})
        self.sent()
        self.commit(extra={"notes.txt": "y\n"})
        self.assertTrue(self.page()[0].startswith("relay: nothing new since "))

    def test_printing_records_nothing(self):
        self.sent()
        self.commit(closed("Gamma change"))
        before = self.page()
        self.assertEqual(self.page(), before)                         # printed twice: the same page
        self.assertEqual(len(rd.read_events(self.main)), 1)           # and no event was recorded by printing
        out: list = []
        self.assertEqual(rd.main(["-C", self.main, "--sent"], out.append), 0)
        self.assertEqual([e["kind"] for e in rd.read_events(self.main)], ["sent", "sent"])
        self.assertTrue(self.page()[0].startswith("relay: nothing new since "))      # after --sent: nothing new

    def test_a_stored_head_off_the_history_is_said_and_covers_24_hours(self):
        side = self.worktree("side")
        self.write_commit(side, {"side.txt": "s\n"}, "side work")
        rd.record_event(self.main, "sent", "2026-10-30T10:00:00Z", git(side, "rev-parse", "HEAD"))    # a commit master never had
        lines = rd.page(self.main, "master", {}, spend=lambda: None, evals=self.evals)
        self.assertTrue(lines[0].startswith("note: the head stored at the last digest ("), lines[0])
        self.assertIn("covering the last 24 h", lines[0])

    def test_waiting_question_recorded_twice_is_shown_once(self):
        ask = {"asked_at": "2026-10-30T05:10:00Z", "question": ["**Where does the comparison run?**"], "options": OPTIONS}
        self.sent()
        self.commit(with_notes(make("First place"), [ask]), with_notes(make("Second place"), [dict(ask, asked_at="2026-10-30T05:11:00Z")]))
        waiting = [x for x in self.page() if x.startswith("Waiting for you:")]
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0].count("Where does the comparison run?"), 1)
        self.assertIn("(asked 30 Oct 05:10 UTC)", waiting[0])            # the oldest of the two

    def test_line_limits_and_all(self):
        self.sent()
        self.commit(*[closed("Change number %02d" % n) for n in range(5)])
        lines = self.page({"front": {"digest_merged_lines": 3}})
        self.assertEqual(len(self.merged_lines(lines)), 3)
        self.assertIn("  ... and 2 more", lines)
        notes = [decision("2026-10-29T10:%02d:00Z" % n, "Decision number %02d?" % n) for n in range(12)]
        self.commit(with_notes(make("Many decisions"), notes))
        short = self.page({"front": {"digest_decision_lines": 10}})
        self.assertEqual(len([x for x in short if x.startswith("    **")]), 10)
        self.assertIn("  and 2 more decisions: relay digest --all", short)
        full = self.page({"front": {"digest_decision_lines": 10}}, show_all=True)
        self.assertEqual(len([x for x in full if x.startswith("    **")]), 12)
        self.assertFalse([x for x in full if "more decisions" in x])

    def test_an_answered_decision_leaves_the_next_page(self):
        self.sent()
        self.commit(with_notes(make("Cycle lands itself"), [decision("2026-10-29T10:00:00Z", "Does it land?")]))
        self.assertIn("1 decisions taken", self.page()[0])
        slug = "cycle-lands-itself"
        rq.note(self.main, slug, {"kind": "answer", "answer": ["a"], "to": ["2026-10-29T10:00:00Z"], "chosen": ["a"]}, now=NOW, **tq.QUIET)
        self.assertIn("0 decisions taken", self.page()[0])


class Due(DigestBase):
    def setUp(self):
        super().setUp()
        self.commit(extra={"f.txt": "0\n"})
        self.sent()

    def land(self, count):
        for n in range(count):
            self.commit(extra={"f.txt": "%d\n" % (n + 1)}, message="landing %d" % n)

    def test_fifteen_landings_without_a_paid_run_are_due_and_fourteen_are_not(self):
        self.land(14)
        self.assertEqual(self.due(), [])
        self.land(1)
        self.assertEqual(self.due(), ["digest due: 15 landings since the last digest (limit 15)"])

    def test_queue_commits_are_no_landing(self):
        for n in range(16):
            self.commit(make("Queue item %02d" % n), message="queue: item")
        self.assertEqual(self.due(), [])

    def test_a_paid_run_that_ended_after_the_digest_is_due_at_any_count(self):
        self.paid_run("late", "2026-10-30T11:00:00Z")          # ended 11:00, digest sent 10:00
        self.assertEqual(self.due(), ["digest due: a paid run ended 30 Oct 11:00 UTC"])

    def test_a_paid_run_that_ended_before_the_digest_is_not_due(self):
        self.paid_run("early", "2026-10-30T09:00:00Z")
        self.assertEqual(self.due(), [])

    def test_spend_alert_at_the_share_of_the_cap(self):
        self.assertEqual(self.due(spend=(79.0, 100.0)), [])      # 0.79 of the cap, share 0.8
        line = self.due(spend=(81.0, 100.0))
        self.assertEqual(len(line), 1)
        self.assertTrue(line[0].startswith("alert due: paid spend today $81.00 is at 81% of the $100 cap"), line)
        self.sent("2026-10-30T11:00:00Z", kind="alert")
        self.assertEqual(self.due(spend=(85.0, 100.0)), [])      # an alert was sent today: none again today
        self.assertEqual(len(self.due(spend=(85.0, 100.0), now="2026-10-31T01:00:00Z")), 1)       # the next UTC day

    def test_spend_share_setting_is_clamped(self):
        self.assertEqual(rd.setting({"front": {"spend_alert_share": 0.1}}, "spend_alert_share"), 0.5)
        self.assertEqual(rd.setting({"front": {"digest_max_landings": 500}}, "digest_max_landings"), 50)
        self.assertEqual(rd.setting({"front": {"digest_max_landings": "x"}}, "digest_max_landings"), 15)


class StopHook(DigestBase):
    def setUp(self):
        super().setUp()
        self.commit(extra={"f.txt": "0\n"})
        self.sent()
        self.env = dict(os.environ, RELAY_HOME=os.path.join(self.tmp, "home"))

    def run_hook(self, session="s1", **extra):
        event = {"hook_event_name": "Stop", "session_id": session, "cwd": self.main}
        event.update(extra)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def land(self, count):
        for n in range(count):
            self.commit(extra={"f.txt": "%d-%d\n" % (n, len(rd.read_events(self.main)))}, message="landing")

    def test_refuses_once_per_due_state_and_is_silent_after_sent(self):
        self.assertIsNone(self.run_hook())                    # nothing due
        self.land(15)
        first = self.run_hook()
        self.assertEqual(first["decision"], "block")
        self.assertIn("15 landings", first["reason"])
        self.assertIn("relay digest --sent", first["reason"])
        self.assertIsNone(self.run_hook())                    # the same state: refused once
        self.sent("2026-10-30T11:00:00Z")                     # the digest was sent: nothing due, the stamp is cleared
        self.assertIsNone(self.run_hook())
        self.land(15)
        self.assertEqual(self.run_hook()["decision"], "block")      # a new due state is refused again

    def test_silent_when_the_stop_is_already_a_hook_refusal_or_for_a_subagent(self):
        self.land(15)
        self.assertIsNone(self.run_hook(stop_hook_active=True))
        self.assertIsNone(self.run_hook(agent_id="a1"))

    def test_fails_open_with_one_line_when_git_cannot_answer(self):
        self.land(15)
        self.env["RELAY_DIGEST_HOOK_BUDGET_S"] = "0.000001"       # the deadline passes before the check ends
        out = self.run_hook()
        self.assertNotIn("decision", out or {})
        self.assertTrue((out or {}).get("systemMessage", "").startswith("digest hook: could not tell"), out)


class Reversal(DigestBase):
    def answer(self, slug, letter):
        return rq.note(self.main, slug, {"kind": "answer", "answer": ["по этому: " + letter], "to": ["2026-10-29T10:00:00Z"], "chosen": [letter]},
                       now=NOW, **tq.QUIET)

    def test_other_letter_on_a_merged_item_names_the_rework_item(self):
        self.commit(with_notes(closed("Merged cycle"), [decision("2026-10-29T10:00:00Z", "Land itself?", "a")]))
        text = self.answer("merged-cycle", "b")
        self.assertIn("This reverses 'Land itself?', whose change is already merged: add the rework item", text)

    def test_same_letter_is_a_confirmation_with_no_line(self):
        self.commit(with_notes(closed("Merged cycle"), [decision("2026-10-29T10:00:00Z", "Land itself?", "a")]))
        self.assertNotIn("rework", self.answer("merged-cycle", "a"))

    def test_other_letter_on_an_open_item_is_just_the_note(self):
        self.commit(with_notes(make("Open cycle"), [decision("2026-10-29T10:00:00Z", "Land itself?", "a")]))
        text = self.answer("open-cycle", "b")
        self.assertNotIn("rework", text)
        notes = rq.notes_of(self.item("open-cycle"))
        self.assertEqual((notes[0].answer_choice, notes[0].chosen), ("b", "a"))       # the answer is on the item for the lane to read


class FrontDecisionFact(DigestBase):
    def test_a_prose_front_decision_is_refused_and_the_decision_note_form_is_accepted(self):
        self.commit(make("Some change"))
        text = "Front decision (owner can reverse; principle 7): no merge train."
        with self.assertRaises(rq.Refused) as raised:
            rq.note(self.main, "some-change", {"kind": "fact", "fact": [text]}, now=NOW, **tq.QUIET)
        self.assertIn("decision note", str(raised.exception))
        self.assertIn("decided_by", str(raised.exception))
        rq.note(self.main, "some-change", {"kind": "question", "question": ["**" + text + "**"], "options": OPTIONS, "decided_by": "front",
                                          "chosen": "a", "because": ["principle 7"]}, now=NOW, **tq.QUIET)
        self.assertEqual(len(rq.notes_of(self.item("some-change"))), 1)
        rq.note(self.main, "some-change", {"kind": "fact", "fact": ["Measured 30 Oct: 3 files."]}, now=NOW, **tq.QUIET)    # other facts still go in


class Texts(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(tq.ROOT, rel), encoding="utf-8") as handle:
            return handle.read()

    def test_every_status_text_limits_the_line_to_owner_requests(self):
        for rel in ("rules/working-with-me.md", "rules/front.md", "plugins/front/skills/front/SKILL.md"):
            text = " ".join(self.read(rel).split())
            at = text.index("running and why")
            self.assertRegex(text[max(0, at - 60):at + 60], r"gives? (me )?a request", rel)

    def test_help_lists_digest(self):
        done = subprocess.run([sys.executable, os.path.join(tq.ROOT, "bin", "relay"), "--help"], capture_output=True, text=True, timeout=60)
        self.assertIn("relay digest", done.stdout)
        self.assertIn("--due", done.stdout)


if __name__ == "__main__":
    unittest.main()
