"""Free tests of bin/paid-cost: the money ceiling passed to a paid run and the estimate from stored records.
No test calls a model."""
import json, os, subprocess, tempfile, unittest
from importlib.machinery import SourceFileLoader
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "paid-cost")


def load():
    loader = SourceFileLoader("paid_cost", BIN)
    spec = importlib.util.spec_from_loader("paid_cost", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m)
    return m


def record(folder, name, cost, runs):
    d = {"costUsd": cost, "cases": [{"name": "c", "arms": {"with": [{}] * runs}}]}
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        json.dump(d, f)


class Ceiling(unittest.TestCase):
    def test_cap_minus_the_batch_in_flight(self):
        # 3 other runs may be in flight when the tool trips: 4 - 3 x 0.80 = 1.60
        self.assertEqual(load().ceiling(4, 4, [(2.4, 3), (4.0, 5)]), (4, 1.6))

    def test_less_than_one_run_left_drops_to_one_job(self):
        # 1 - 3 x 0.80 < 0: nothing is left for even one run, so -j 1 and the cap itself
        self.assertEqual(load().ceiling(1, 4, [(4.0, 5)]), (1, 1))

    def test_one_job_passes_the_cap(self):
        self.assertEqual(load().ceiling(4, 1, [(4.0, 5)]), (1, 4))

    def test_nothing_measured_runs_one_job(self):
        self.assertEqual(load().ceiling(4, 4, []), (1, 4))

    def test_command_line_prints_jobs_and_ceiling(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 4.0, 5)  # 0.80 a run
            out = subprocess.run([BIN, "ceiling", "--cap", "4", "--jobs", "4", "--dir", d], capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "4 1.6")


class Estimate(unittest.TestCase):
    def test_mean_max_and_count(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 6.0, 3); record(d, "b.json", 8.0, 3); open(os.path.join(d, "x.json"), "w").write("not json")
            # mean (6 + 8) / 2 = 7.00, max 8.00, 2 readable records
            self.assertEqual(load().estimate(load().stored(d)), "mean $7.00, max $8.00 over 2 stored runs")

    def test_one_record_is_not_measured_yet(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 6.0, 3)
            self.assertEqual(load().estimate(load().stored(d)), "not measured yet")

    def test_no_folder_is_not_measured_yet(self):
        self.assertEqual(load().estimate(load().stored("/nonexistent-paid-cost-dir")), "not measured yet")


class CiWiring(unittest.TestCase):
    def test_ci_passes_the_computed_ceiling_and_jobs(self):
        ci = open(os.path.join(ROOT, "bin", "ci"), encoding="utf-8").read()
        self.assertIn("bin/paid-cost ceiling", ci)
        self.assertNotIn('--max-cost-usd "${EVALS_MAX_COST:-15}"', ci)


if __name__ == "__main__":
    unittest.main()
