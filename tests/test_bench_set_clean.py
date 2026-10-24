"""`relay bench --set` leaves the main checkout clean (queue item a-bench-with-set-leaves-the-main-checkout-dirty, Q1).

The derived profile used to be written into profiles/candidates/ of the checkout, untracked, and
guard-main refused to remove it. It is now written beside the bench report; `relay improve adopt`
takes it by that path.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_bench  # noqa: E402
import relay_paidcap  # noqa: E402

CANDIDATES = os.path.join(ROOT, "profiles", "candidates")


def candidates():
    return sorted(os.listdir(CANDIDATES)) if os.path.isdir(CANDIDATES) else []


class DerivedProfileLivesBesideTheReport(unittest.TestCase):
    def test_q1_set_writes_nothing_into_the_checkout_and_the_profile_sits_beside_the_report(self):
        base = relay_bench.load_profile("active")
        before = candidates()
        derived = relay_bench.derive_profile(base, ["models.build=haiku"])
        self.assertEqual(candidates(), before)   # deriving alone writes nothing in the repository
        scenario = {"name": "s", "runs": 1}
        with tempfile.TemporaryDirectory() as out_root:
            with mock.patch.object(relay_bench, "run_one", return_value={"cost_usd": 0.0}), \
                 mock.patch.object(relay_bench, "render", return_value="report"), \
                 mock.patch.object(relay_paidcap, "check", return_value=None), \
                 mock.patch.object(relay_paidcap, "link_out"):
                out_dir, doc, _ = relay_bench.run_bench([base, derived], [scenario], out_root=out_root)
            self.assertEqual(candidates(), before)
            beside = os.path.join(out_dir, "build-haiku.toml")
            self.assertTrue(os.path.isfile(beside))
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "report.md")))
            self.assertEqual(doc["profiles"][1]["path"], beside)
            # `relay improve adopt <path>` loads it with load_profile: the model change is there.
            adopted = relay_bench.load_profile(beside)
            self.assertEqual(adopted["models"]["build"], "haiku")


if __name__ == "__main__":
    unittest.main()
