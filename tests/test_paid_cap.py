"""Free tests of the daily paid-run cap: it is read from projects.toml and the day's spend is summed from relay's own records.
No test calls a model."""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_paidcap  # noqa: E402
import relay_bench  # noqa: E402

BIN = os.path.join(ROOT, "bin", "paid-cost")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.projects = os.path.join(self.home, "projects.toml")
        with open(self.projects, "w") as f:
            f.write('[global]\ntitle = "t"\npaid_cap_usd_per_day = 10\n')
        os.makedirs(os.path.join(self.home, "evals", "repo"))
        os.makedirs(os.path.join(self.home, "bench", "2026-10-24T01-00-00Z"))
        # 24 Oct: eval batches 4.00 + 3.00, a bench session 1.50; 23 Oct batch 9.00 must not count.
        for name, day, cost in [("a", "2026-10-24T01:00:00.000Z", 4.0), ("b", "2026-10-24T20:00:00.000Z", 3.0), ("c", "2026-10-23T23:59:00.000Z", 9.0)]:
            with open(os.path.join(self.home, "evals", "repo", name + ".json"), "w") as f:
                json.dump({"startedAt": day, "costUsd": cost}, f)
        with open(os.path.join(self.home, "bench", "2026-10-24T01-00-00Z", "results.json"), "w") as f:
            json.dump({"started": "2026-10-24T01-00-00Z", "rows": [{"cost_usd": 1.5}, {"cost_usd": None}]}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def run_bin(self, *args):
        env = dict(os.environ, RELAY_HOME=self.home, RELAY_PROJECTS=self.projects)
        return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, env=env)


class Today(Fixture):
    def test_today_prints_spend_cap_and_run_count(self):
        # 4.00 + 3.00 + 1.50 = 8.50 over 3 runs; the 23 Oct batch is another day; the cap is the file's 10
        done = self.run_bin("today", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.assertEqual(done.stdout.strip(), "2026-10-24: spent $8.50 of the $10 cap, 3 runs")

    def test_cap_comes_from_projects_toml_and_one_command_changes_it(self):
        self.assertEqual(self.run_bin("cap").stdout.strip(), "10")
        self.assertEqual(self.run_bin("cap", "200").stdout.strip(), "200")
        self.assertEqual(relay_paidcap.cap(self.projects), 200.0)
        self.assertIn('title = "t"', open(self.projects).read())


class Refusal(Fixture):
    def test_eval_refused_when_spend_plus_estimate_passes_the_cap(self):
        # spent 8.50 (the bench dir is home/bench); largest stored batch 9.00 (23 Oct): 8.50 + 9.00 > 10
        done = self.run_bin("guard", "eval", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.assertEqual(done.returncode, 1)
        for part in ("cap is $10", "$8.50 is spent", "estimated at $9.00"):
            self.assertIn(part, done.stdout)

    def test_eval_runs_when_under_the_cap(self):
        # cap 100: 8.50 + 9.00 is under it
        self.run_bin("cap", "100")
        done = self.run_bin("guard", "eval", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_bench_refused_before_it_starts_and_runs_when_under(self):
        # bench estimate: 2 sessions x largest session 1.50 = 3.00; spent 8.50 + 3.00 > 10
        bench = os.path.join(self.home, "bench")
        os.environ["RELAY_HOME"], os.environ["RELAY_PROJECTS"] = self.home, self.projects
        try:
            line = relay_paidcap.check("2026-10-24", relay_paidcap.bench_estimate(2, bench), "bench", self.projects, self.home, bench)
            self.assertIn("bench refused: the day's cap is $10, $8.50 is spent", line)
            with self.assertRaises(relay_bench.PaidCapReached):
                relay_bench.run_bench([{"profile": {}}] * 2, [{"name": "s", "runs": 1}], out_root=bench)
        finally:
            del os.environ["RELAY_HOME"], os.environ["RELAY_PROJECTS"]
        self.assertIsNone(relay_paidcap.check("2026-10-24", 1.0, "bench", self.projects, self.home, bench))  # 8.50 + 1.00 <= 10


if __name__ == "__main__":
    unittest.main()
