"""A queue landing must write only records the default branch's own code accepts (item a-queue-landing-writes-fields-master-s-code-reje).
Scratch repositories in a temp dir; the default branch carries a stub lib/relay_queue.py whose parse does not know the `notes` key."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq
git = tq.git
LIB = os.path.join(tq.ROOT, "lib")
NOTE = {"kind": "fact", "fact": ["Measured 27 Oct: 30 items."]}


class LandAhead(tq.Base):
    def master_with_code(self, code):
        """Put `code` as lib/relay_queue.py on the default branch: the code the lander's record must pass."""
        self.write_commit(self.main, {"lib/relay_queue.py": code}, "default branch queue code")

    def master_with_old_schema(self):
        """A stub of the older schema: parse reports the key `notes` as unknown and accepts everything else."""
        self.master_with_code(
            "import json\n"
            "def parse(slug, text):\n"
            "    return {'problems': ['unknown key notes'] if 'notes' in json.loads(text) else []}\n")

    def add_item(self):
        return rq.add(self.main, "feature", "A feature to note on", why="it matters", what="what is wanted here", minutes=10, **tq.QUIET)

    def test_a_landing_master_s_code_rejects_is_refused_with_the_next_step(self):
        slug_line = self.add_item()
        slug = slug_line.split()[1]
        self.master_with_old_schema()
        head = git(self.main, "rev-parse", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.note(self.main, slug, NOTE, now="2099-01-01T00:00:00Z", **tq.QUIET)
        text = str(ctx.exception)
        # the old schema reports the new key as unknown; the person is told the two ways out
        self.assertIn("unknown key notes", text)
        self.assertIn("merge the code first", text)
        self.assertEqual(git(self.main, "rev-parse", "master"), head)   # nothing landed
        self.assertEqual(self.branches(), [])

    def test_a_record_master_s_code_accepts_lands_at_once(self):
        slug = self.add_item().split()[1]
        self.master_with_old_schema()
        out = rq.set_ip(self.main, slug, 40, **tq.QUIET)   # no new key: the old schema accepts it
        self.assertIn("ip set", out)
        self.assertEqual(self.item(slug)["ip"], 40)

    def test_a_default_branch_without_the_code_lands_as_before(self):
        slug = self.add_item().split()[1]
        out = rq.note(self.main, slug, NOTE, now="2099-01-01T00:00:00Z", **tq.QUIET)
        self.assertIn("noted", out)

    def test_a_default_branch_whose_code_cannot_run_refuses(self):
        # fail closed: code that does not run (syntax error) or prints non-JSON must not be taken for "accepts"
        slug = self.add_item().split()[1]
        for code, word in (("def oops(:\n", "SyntaxError"), ("print('not json')\ndef parse(slug, text):\n    return {'problems': []}\n", "Expecting value")):
            self.master_with_code(code)
            head = git(self.main, "rev-parse", "master")
            with self.assertRaises(rq.Refused) as ctx:
                rq.set_ip(self.main, slug, 40, **tq.QUIET)
            self.assertIn("cannot run", str(ctx.exception))
            self.assertIn(word, str(ctx.exception))
            self.assertEqual(git(self.main, "rev-parse", "master"), head)


if __name__ == "__main__":
    unittest.main()
