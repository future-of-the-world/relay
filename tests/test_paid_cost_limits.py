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


def record(folder, name, cost, runs, partial=False, run_costs=None):
    arm = [{"costUsd": c, "judgeCostUsd": j} for c, j in run_costs] if run_costs else [{}] * runs
    d = {"costUsd": cost, "partial": partial, "cases": [{"name": "c", "arms": {"with": arm}}]}
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        json.dump(d, f)


class Ceiling(unittest.TestCase):
    RUNS = [(5.0, False, [0.30, 0.80, 0.20])]  # largest run 0.80, batch mean 0.43

    def test_cap_minus_the_largest_run_not_the_mean(self):
        # 3 other runs may be in flight: 4 - 3 x 0.80 = 1.60 (the mean 0.43 would give 2.7)
        self.assertEqual(load().ceiling(4, 4, self.RUNS), (4, 1.6))

    def test_less_than_one_run_left_drops_to_one_job(self):
        # 1 - 3 x 0.80 < 0.80: nothing is left for a run, so -j 1 and the cap itself
        self.assertEqual(load().ceiling(1, 4, self.RUNS), (1, 1))

    def test_one_job_passes_the_cap(self):
        self.assertEqual(load().ceiling(4, 1, self.RUNS), (1, 4))

    def test_nothing_measured_runs_one_job(self):
        self.assertEqual(load().ceiling(4, 4, []), (1, 4))

    def test_run_cost_adds_judge_cost_and_skips_runs_without_cost(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 1.0, 0, run_costs=[(0.70, 0.12), (0.10, 0.0)])
            # the single run is 0.70 + 0.12 = 0.82
            self.assertEqual(load().stored(d)[0][2], [0.82, 0.10])
            record(d, "b.json", 1.0, 2)  # runs with no costUsd
            self.assertEqual(load().stored(d)[1][2], [])

    def test_partial_batch_runs_count_for_the_ceiling(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 2.0, 0, partial=True, run_costs=[(0.80, 0.0)])
            self.assertEqual(load().ceiling(4, 4, load().stored(d)), (4, 1.6))

    def test_command_line_prints_jobs_and_ceiling(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 1.3, 0, run_costs=[(0.30, 0), (0.80, 0), (0.20, 0)])
            out = subprocess.run([BIN, "ceiling", "--cap", "4", "--jobs", "4", "--dir", d], capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "4 1.6")

    def test_empty_dir_prints_one_job_and_the_cap(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([BIN, "ceiling", "--cap", "10", "--jobs", "4", "--dir", d], capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "1 10")


class Estimate(unittest.TestCase):
    def test_mean_max_and_count(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 6.0, 3); record(d, "b.json", 8.0, 3); open(os.path.join(d, "x.json"), "w").write("not json")
            # mean (6 + 8) / 2 = 7.00, max 8.00, 2 readable records
            self.assertEqual(load().estimate(load().stored(d)), "mean $7.00, max $8.00 over 2 stored runs")

    def test_partial_batch_is_not_counted(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 9.0, 3); record(d, "p.json", 2.0, 3, partial=True)
            self.assertEqual(load().estimate(load().stored(d)), "not measured yet")
            record(d, "b.json", 8.0, 3)
            # full 9 and 8 only: mean 8.50, max 9.00
            self.assertEqual(load().estimate(load().stored(d)), "mean $8.50, max $9.00 over 2 stored runs")

    def test_one_record_is_not_measured_yet(self):
        with tempfile.TemporaryDirectory() as d:
            record(d, "a.json", 6.0, 3)
            self.assertEqual(load().estimate(load().stored(d)), "not measured yet")

    def test_no_folder_is_not_measured_yet(self):
        self.assertEqual(load().estimate(load().stored("/nonexistent-paid-cost-dir")), "not measured yet")


if __name__ == "__main__":
    unittest.main()
