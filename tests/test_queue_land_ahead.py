"""A queue landing must write only records the default branch's own code accepts (item a-queue-landing-writes-fields-master-s-code-reje).
Scratch repositories in a temp dir; the default branch carries a copy of lib/ whose schema does not know the `notes` key."""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

rq = tq.rq
git = tq.git
LIB = os.path.join(tq.ROOT, "lib")
NOTE = {"kind": "fact", "fact": ["Measured 27 Oct: 30 items."]}


class LandAhead(tq.Base):
    def master_with_old_schema(self):
        """Put a copy of lib/ on the default branch whose item keys lack `notes`: the code the lander's record must pass."""
        files = {}
        for name in sorted(os.listdir(LIB)):
            full = os.path.join(LIB, name)
            if name.endswith((".py", ".toml")) and os.path.isfile(full):
                with open(full, encoding="utf-8") as handle:
                    files["lib/" + name] = handle.read()
        old = files["lib/relay_queue.py"]
        # hand-made: the one place the keys are listed ends in `"dropped_why", "notes")`; removing "notes" is the older schema
        marker = '"dropped_at", "dropped_why", "notes")'
        self.assertEqual(old.count(marker), 1)
        files["lib/relay_queue.py"] = old.replace(marker, '"dropped_at", "dropped_why")')
        self.write_commit(self.main, files, "default branch code before notes")

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


if __name__ == "__main__":
    unittest.main()
