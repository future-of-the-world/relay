"""A branch whose fix item is taken and open does not land, even when the take is on master only (a-landed-branch-can-leave-its-queue-item)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_gate import git, write  # noqa: E402
from test_land import Land  # noqa: E402
import test_lanes_state as tls  # noqa: E402


class OpenItemLanding(Land):
    def test_f2_a_take_on_master_that_the_branch_has_not_merged_refuses_the_landing(self):
        # fx is taken by wt/x on master only (not in wt/x's head): landing would leave it taken by a deleted branch
        self.start()
        self.master_commit(".relay/queue/fx.json", tls.item("fx", "fix", **tls.taken("wt/x")))
        before = self.master()
        run = self.land()
        out = run.stdout + run.stderr
        self.assertEqual(run.returncode, 2, out)
        self.assertIn("relay queue done fx -C " + self.wt + " --test", out)
        self.assertEqual(self.master(), before)
        self.assertEqual(self.runs(), 0)         # refused before the gate

    def test_f3_a_branch_whose_item_is_closed_on_it_lands(self):
        # the state filter: a fix taken by wt/x and closed on wt/x (test set) is not "open"; the refusal must not be the open-item one
        self.start()
        item = tls.item("job", "fix", **tls.taken("wt/x"))
        write(os.path.join(self.wt, ".relay", "queue", "job.json"), item)
        data = json.loads(item)
        data["closed_at"], data["test"] = "2026-10-29T10:00:00Z", "tests/test_a.py::test_a"
        write(os.path.join(self.wt, ".relay", "queue", "job.json"), json.dumps(data, indent=2) + "\n")
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "queue: done job")
        self.mark(self.wt)
        run = self.land()
        self.assertNotIn("still holds the open fix item", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
