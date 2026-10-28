"""The check-mark hook reads a workflow checker's transcript: attachment entries after its prompt are not a failure."""
import json
import os
import tempfile
import unittest
from relay_testbase import load_hook as _load_hook  # noqa: E402

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "relay", "hooks", "check-mark.py")
check_mark = _load_hook("check_mark", HOOK)

PROMPT = "[Workflow harness] task text\n  Implement the brief.\n  Report: `r/x.md`."


def user(text, stamp="2026-10-24T05:09:00.000Z"):
    return {"type": "user", "message": {"role": "user", "content": text}, "timestamp": stamp}


def attachment(kind="environment"):
    # The shape of a real workflow transcript: no `message`, an `attachment` object.
    return {"type": "attachment", "attachment": {"type": kind}, "timestamp": "2026-10-24T05:09:01.000Z"}


def assistant(text="ok"):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


class MarkAttach(unittest.TestCase):
    def read(self, entries):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                for entry in entries:
                    handle.write(json.dumps(entry) + "\n")
            return check_mark.first_entry(path)

    def test_labelled_prompt_then_attachments(self):
        text, start = self.read([user(PROMPT), attachment(), attachment("model"), attachment("instructions"), assistant()])
        self.assertIn("Report:", text)
        self.assertIsNotNone(start)

    def test_unlabelled_prompt_then_attachments(self):
        text, _ = self.read([user("plain prompt"), attachment(), assistant()])
        self.assertEqual(text, "plain prompt")

    def test_no_prompt_still_fails(self):
        with self.assertRaises(check_mark.Fail) as ctx:
            self.read([attachment(), attachment(), assistant()])
        self.assertIn("does not start with a prompt", str(ctx.exception))

    def test_harness_relay_first_still_picks_labelled(self):
        text, _ = self.read([user("relay: Report: quoted"), user(PROMPT), attachment(), assistant()])
        self.assertIn("Implement the brief", text)


if __name__ == "__main__":
    unittest.main()
