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
                 mock.patch.object(relay_paidcap, "bench_estimate", return_value=0.0), \
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


def _cheaper_doc(path_b, name_b):
    # active costs 2.0, the other 1.0, equal score: the other wins by $1.00.
    doc = {"profiles": [{"name": "active", "path": os.path.join(ROOT, "profiles", "active.toml")},
                        {"name": name_b, "path": path_b}], "scenarios": ["s"]}
    agg = {("active", "s"): {"score_min": 1, "cost_mean": 2.0, "duration_mean": 10},
           (name_b, "s"): {"score_min": 1, "cost_mean": 1.0, "duration_mean": 10}}
    return doc, agg


class VerdictNamesAWorkingAdoptArgument(unittest.TestCase):
    def test_f1_derived_profile_is_adopted_by_its_path(self):
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "build-haiku.toml")
            with open(path, "w") as h:
                h.write('[profile]\nname = "build-haiku"\n')
            doc, agg = _cheaper_doc(path, "build-haiku")
            self.assertIn(f"relay improve adopt {path}`", relay_bench.verdict(doc, agg))
            self.assertEqual(relay_bench.load_profile(path)["profile"]["name"], "build-haiku")

    def test_f1_named_candidate_keeps_its_short_name(self):
        path = os.path.join(CANDIDATES, "x.toml")
        doc, agg = _cheaper_doc(path, "x")
        self.assertIn("relay improve adopt x`", relay_bench.verdict(doc, agg))

    def test_f1_worse_quality_keeps_active(self):
        doc, agg = _cheaper_doc("/elsewhere/d.toml", "d")
        agg[("d", "s")]["score_min"] = 0
        self.assertTrue(relay_bench.verdict(doc, agg).startswith("Verdict: keep active"))


class DerivedProfileKeepsCopiedPlugins(unittest.TestCase):
    def test_f2_relative_plugin_entry_resolves_after_the_file_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = os.path.join(tmp, "profiles", "candidates")
            plug = os.path.join(cand, "x", "plugins", "delegate")
            os.makedirs(os.path.join(plug, ".claude-plugin"))
            os.makedirs(os.path.join(plug, "agents"))
            open(os.path.join(plug, ".claude-plugin", "plugin.json"), "w").write("{}")
            with open(os.path.join(cand, "x.toml"), "w") as h:
                h.write('[profile]\nname = "x"\n[plugins]\nenabled = ["core", "x/plugins/delegate"]\n')
            with mock.patch.object(relay_bench, "ROOT", tmp):
                base = relay_bench.load_profile("x")
                self.assertEqual(relay_bench.plugin_dir(base, "x/plugins/delegate"), os.path.realpath(plug))
                d = relay_bench.derive_profile(base, ["models.build=haiku"])
                d["_path"] = os.path.join(tmp, "bench", "ts", "build-haiku.toml")   # as run_bench does
                entries = d["plugins"]["enabled"]
                self.assertEqual(entries[0], "core")   # plain names stay names
                self.assertEqual(relay_bench.plugin_dir(d, entries[1]), os.path.realpath(plug))
                self.assertEqual(relay_bench.agent_definitions_dir(d), os.path.join(os.path.realpath(plug), "agents"))


if __name__ == "__main__":
    unittest.main()
