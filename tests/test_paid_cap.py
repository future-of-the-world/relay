"""Free tests of the daily paid-run cap: it is read from projects.toml and the day's spend is summed from relay's own records.
No test calls a model."""
import datetime, json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_paidcap  # noqa: E402
import relay_bench  # noqa: E402

BIN = os.path.join(ROOT, "bin", "paid-cost")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        # run_bench lists the worktrees of ROOT; the live repo's would add their direct runs to the fixture's day
        self.addCleanup(setattr, relay_bench, "ROOT", relay_bench.ROOT)
        relay_bench.ROOT = self.home
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
        env = dict(os.environ, RELAY_HOME=self.home, RELAY_PROJECTS=self.projects, RELAY_ROOT=getattr(self, 'root', self.home))
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


class DirectRuns(Fixture):
    """A `claude plugin eval` run made by hand leaves evals/plugin/results/<stamp>/aggregate-result.json in the checkout it ran in."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.home, "repo-main")
        self.wt = os.path.join(self.home, "wt")
        git = lambda *a, cwd=self.root: subprocess.run(["git", "-C", cwd, *a], check=True, capture_output=True)
        os.makedirs(self.root)
        git("init", "-q"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        git("worktree", "add", "-q", "--detach", self.wt)

    def result(self, checkout, stamp, cost):
        folder = os.path.join(checkout, "evals", "plugin", "results", stamp.replace(":", "-").replace(".", "-"))
        os.makedirs(folder)
        with open(os.path.join(folder, "aggregate-result.json"), "w") as f:
            json.dump({"startedAt": stamp, "costUsd": cost}, f)

    def test_a_direct_run_in_a_worktree_counts_in_today(self):
        # failing case: a worker's direct run of one case cost 2.25 in a worktree; the ledger showed only the stored 7.00 (4 + 3) and 1.50 bench
        self.result(self.wt, "2026-10-24T05:00:00.000Z", 2.25)
        done = self.run_bin("today", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        # 4.00 + 3.00 + 1.50 + 2.25 = 10.75 over 4 runs
        self.assertEqual(done.stdout.strip(), "2026-10-24: spent $10.75 of the $10 cap, 4 runs")

    def test_a_direct_run_in_the_main_checkout_counts_and_another_day_does_not(self):
        self.result(self.root, "2026-10-24T05:00:00.000Z", 1.0)
        self.result(self.root, "2026-10-23T05:00:00.000Z", 5.0)   # yesterday
        done = self.run_bin("today", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.assertEqual(done.stdout.strip(), "2026-10-24: spent $9.50 of the $10 cap, 4 runs")   # 8.50 + 1.00

    def test_a_bin_ci_run_is_counted_once(self):
        # the stored record "a" (4.00) and the eval tool's own result have the same startedAt: one run
        self.result(self.wt, "2026-10-24T01:00:00.000Z", 4.0)
        done = self.run_bin("today", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.assertEqual(done.stdout.strip(), "2026-10-24: spent $8.50 of the $10 cap, 3 runs")

    def test_the_guard_sees_a_direct_run(self):
        # stored 7.00 + bench 1.50 = 8.50; largest stored batch 9.00 (23 Oct); cap raised to 18: 17.50 fits, but a direct 1.50 makes 10.00 + 9.00 = 19 > 18
        self.run_bin("cap", "18")
        args = ("guard", "eval", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.assertEqual(self.run_bin(*args).returncode, 0)
        self.result(self.wt, "2026-10-24T05:00:00.000Z", 1.5)
        done = self.run_bin(*args)
        self.assertEqual(done.returncode, 1)
        self.assertIn("$10.00 is spent", done.stdout)


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
        # run_bench stamps the day from the clock; the fixture's spend is dated 24 Oct, so the clock is fixed there (a run that
        # crossed UTC midnight, or any later day, made the cap look unspent and the bench start)
        real_dt = relay_bench.dt

        class FixedDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.datetime(2026, 10, 24, 12, 0, 0, tzinfo=tz)

        class FixedModule:
            def __getattr__(self, name):
                return FixedDatetime if name == "datetime" else getattr(real_dt, name)

        relay_bench.dt = FixedModule()
        self.addCleanup(setattr, relay_bench, "dt", real_dt)
        try:
            line = relay_paidcap.check("2026-10-24", relay_paidcap.bench_estimate(2, bench), "bench", self.projects, self.home, bench)
            self.assertIn("bench refused: the day's cap is $10, $8.50 is spent", line)
            with self.assertRaises(relay_bench.PaidCapReached):
                relay_bench.run_bench([{"profile": {}}] * 2, [{"name": "s", "runs": 1}], out_root=bench)
        finally:
            del os.environ["RELAY_HOME"], os.environ["RELAY_PROJECTS"]
        self.assertIsNone(relay_paidcap.check("2026-10-24", 1.0, "bench", self.projects, self.home, bench))  # 8.50 + 1.00 <= 10


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


class OutFolder(Fixture):
    """F1: the day's bench spend is summed over the default folder and every --out folder, whichever the run uses."""

    def setUp(self):
        super().setUp()
        self.day = utc_today()
        self.other = os.path.join(self.home, "elsewhere")
        os.makedirs(self.other)
        self._saved = {k: os.environ.get(k) for k in ("RELAY_HOME", "RELAY_PROJECTS")}
        os.environ["RELAY_HOME"], os.environ["RELAY_PROJECTS"] = self.home, self.projects

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def results(self, folder, cost):
        os.makedirs(os.path.join(folder, self.day + "T01-00-00Z"), exist_ok=True)
        with open(os.path.join(folder, self.day + "T01-00-00Z", "results.json"), "w") as f:
            json.dump({"started": self.day + "T01-00-00Z", "rows": [{"cost_usd": cost}]}, f)

    def test_spend_in_the_default_folder_counts_for_a_run_with_out(self):
        # failing case of F1: cap 10, 9.50 spent in home/bench, --out run estimated 1 session x 9.50 = 9.50: 19 > 10
        import shutil
        shutil.rmtree(os.path.join(self.home, "bench")); shutil.rmtree(os.path.join(self.home, "evals"))
        self.results(os.path.join(self.home, "bench"), 9.5)
        with self.assertRaises(relay_bench.PaidCapReached) as ctx:
            relay_bench.run_bench([{"profile": {}}], [{"name": "s", "runs": 1}], out_root=self.other)
        self.assertIn("$9.50 is spent", str(ctx.exception))

    def test_spend_in_an_out_folder_counts_for_the_default_folder_and_for_paid_cost_today(self):
        import shutil
        shutil.rmtree(os.path.join(self.home, "bench")); shutil.rmtree(os.path.join(self.home, "evals"))
        self.results(self.other, 9.5)
        relay_paidcap.link_out(os.path.join(self.other, self.day + "T01-00-00Z"), self.day + "T01-00-00Z")
        self.assertEqual(relay_paidcap.spend_today(self.day), (9.5, 1))
        done = self.run_bin("today", "--today", self.day)
        self.assertIn("spent $9.50 of the $10 cap, 1 run", done.stdout)
        with self.assertRaises(relay_bench.PaidCapReached):
            relay_bench.run_bench([{"profile": {}}], [{"name": "s", "runs": 1}], out_root=os.path.join(self.home, "bench"))

    def test_a_run_with_out_leaves_a_link_and_a_run_without_out_does_not(self):
        # no profiles: no session starts, the run only writes its folder (and the link when --out)
        relay_bench.run_bench([], [], out_root=self.other)
        self.assertEqual(len(os.listdir(relay_paidcap.link_dir())), 1)
        before = os.listdir(relay_paidcap.link_dir())
        relay_bench.run_bench([], [])
        self.assertEqual(os.listdir(relay_paidcap.link_dir()), before)

    def test_under_the_cap_without_out_still_runs(self):
        # pass case 4: spent 8.50 (fixture is 24 Oct; here one row 8.50 today), estimate 1.00, cap 10
        import shutil
        shutil.rmtree(os.path.join(self.home, "bench")); shutil.rmtree(os.path.join(self.home, "evals"))
        self.results(os.path.join(self.home, "bench"), 1.0)
        self.assertIsNone(relay_paidcap.check(self.day, relay_paidcap.bench_estimate(1), "bench"))  # 1.00 + 1.00 <= 10


GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
TOML = '[global]\ntitle = "t"\npaid_cap_usd_per_day = 200   # the owner cap; change it with bin/paid-cost cap <USD>\n'


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=dict(os.environ, **GIT_ENV), check=True).stdout


class LandedCap(unittest.TestCase):
    """F2: `bin/paid-cost cap <USD>` lands one commit on the default branch; the checkout it runs in is not edited."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(os.path.join(self.tmp.name, "repo"))
        os.makedirs(os.path.join(self.repo, ".relay"))
        git(self.repo, "init", "-q", "-b", "master")
        for name, text in (("projects.toml", TOML), (".relay/keep", "")):
            with open(os.path.join(self.repo, name), "w") as f:
                f.write(text)
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def cap(self, root, *args):
        env = dict(os.environ, RELAY_ROOT=root, **GIT_ENV)
        env.pop("RELAY_PROJECTS", None)
        return subprocess.run([sys.executable, BIN, "cap", *args], capture_output=True, text=True, env=env)

    def test_cap_from_the_main_checkout_commits_and_leaves_it_clean(self):
        done = self.cap(self.repo, "300")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "300"), done.stderr)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")           # clean: the ff merge brought the file
        landed = git(self.repo, "show", "master:projects.toml")
        self.assertIn("paid_cap_usd_per_day = 300   # the owner cap", landed)    # comment kept (F5)
        self.assertEqual(git(self.repo, "rev-list", "--count", "master"), "2\n")
        # pass case 2: a detached worktree of the default branch's head prints 300
        wt = os.path.join(self.tmp.name, "paid-wt")
        git(self.repo, "worktree", "add", "-q", "--detach", wt, "master")
        self.assertEqual(self.cap(wt).stdout.strip(), "300")

    def test_cap_from_a_task_worktree_changes_the_default_branch_not_the_worktree(self):
        wt = os.path.join(self.tmp.name, "task")
        git(self.repo, "worktree", "add", "-q", "-b", "wt/task", wt)
        done = self.cap(wt, "250")
        self.assertEqual(done.stdout.strip(), "250", done.stderr)
        self.assertIn("= 250", git(self.repo, "show", "master:projects.toml"))
        self.assertEqual(git(wt, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_cap_without_a_value_prints_and_changes_nothing(self):
        self.assertEqual(self.cap(self.repo).stdout.strip(), "200")
        self.assertEqual(git(self.repo, "rev-list", "--count", "master"), "1\n")


class CapText(unittest.TestCase):
    """F5: the value is replaced, the comment kept, no %g rounding."""

    def test_comment_kept(self):
        self.assertIn("= 250   # the owner cap", relay_paidcap.with_cap(TOML, 250.0))

    def test_big_and_fractional_values_are_exact(self):
        self.assertIn("= 1234567.5\n", relay_paidcap.with_cap('[global]\npaid_cap_usd_per_day = 5\n', 1234567.5))
        self.assertIn("= 12.345   #", relay_paidcap.with_cap(TOML, 12.345))

    def test_missing_key_is_added_under_global(self):
        out = relay_paidcap.with_cap('[global]\ntitle = "t"\n', 200.0)
        self.assertTrue(out.startswith("[global]\npaid_cap_usd_per_day = 200"))


class CiGuard(unittest.TestCase):
    """F3, F4: the gate (lib/relay_ci.py) refuses the paid step over the cap before claude is called; the ceiling is bounded by the day's room."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.home = os.path.join(t, "home")
        os.makedirs(os.path.join(self.home, "evals", "repo"))
        os.makedirs(os.path.join(t, "stub"))
        self.marker = os.path.join(t, "claude-called")
        with open(os.path.join(t, "stub", "claude"), "w") as f:
            f.write(f"#!/bin/sh\ntouch {self.marker}\n")
        os.chmod(os.path.join(t, "stub", "claude"), 0o755)
        self.projects = os.path.join(t, "projects.toml")

    def tearDown(self):
        self.tmp.cleanup()

    def spend(self, cost):
        with open(os.path.join(self.home, "evals", "repo", "a.json"), "w") as f:
            json.dump({"startedAt": utc_today() + "T01:00:00.000Z", "costUsd": cost}, f)

    def env(self, cap):
        with open(self.projects, "w") as f:
            f.write(f'[global]\npaid_cap_usd_per_day = {cap}\n')
        return dict(os.environ, RELAY_HOME=self.home, RELAY_PROJECTS=self.projects,
                    RELAY_ROOT=self.tmp.name,   # not a git checkout: no live worktree's direct eval runs count in this test
                    PATH=os.path.join(self.tmp.name, "stub") + os.pathsep + os.environ["PATH"],
                    PYTHONPATH=os.path.join(ROOT, "lib"))

    def run_section(self, cap):
        """The paid eval step of lib/relay_ci.py in a temporary tree (the real bin/ through a link, a stub `claude`)."""
        root = os.path.join(self.tmp.name, "tree")
        os.makedirs(os.path.join(root, "evals", "plugin"), exist_ok=True)
        if not os.path.exists(os.path.join(root, "bin")):
            os.symlink(os.path.join(ROOT, "bin"), os.path.join(root, "bin"))
        script = ("import sys, relay_ci\nci = relay_ci.Ci(sys.argv[1], False)\nci.prepare()\n"
                  "stop = ci.plugin_evals()\nif stop is not None:\n    sys.exit(stop)\nprint('SECTION-DONE')\n")
        return subprocess.run([sys.executable, "-c", script, root], cwd=ROOT, capture_output=True, text=True, env=self.env(cap))

    def test_over_the_cap_the_paid_step_is_refused_and_claude_is_never_called(self):
        self.spend(6.0)   # spent 6 + largest stored batch 6 = 12 > cap 10
        done = self.run_section(10)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("plugin evals refused", done.stdout)
        self.assertNotIn("SECTION-DONE", done.stdout)
        self.assertFalse(os.path.exists(self.marker))

    def test_under_the_cap_claude_is_called_once(self):
        self.spend(6.0)   # 12 <= cap 100
        done = self.run_section(100)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(os.path.exists(self.marker))

    def ceiling(self, cap, spent, max_cost):
        self.spend(spent)
        done = subprocess.run([sys.executable, BIN, "ceiling", "--within-day", "--cap", str(max_cost), "--jobs", "1"],
                               capture_output=True, text=True, env=self.env(cap))
        return done.stdout.strip()

    def test_ceiling_is_bounded_by_the_room_of_the_day(self):
        self.assertEqual(self.ceiling(200, 190, 15), "1 10")   # room 200 - 190 = 10 < 15

    def test_ceiling_keeps_the_tool_cap_when_the_room_is_larger(self):
        self.assertEqual(self.ceiling(200, 50, 15), "1 15")    # room 150 > 15


if __name__ == "__main__":
    unittest.main()


class DirectRunsDurable(DirectRuns):
    """F1-F3 of the review: a direct run outlives its worktree; the bench guard sees direct runs; suite_roots is time-limited."""

    def remove_wt(self):
        subprocess.run(["git", "-C", self.root, "worktree", "remove", "--force", self.wt], check=True, capture_output=True)

    def test_a_direct_run_still_counts_after_its_worktree_is_removed(self):
        # F1: 4.00 + 3.00 + 1.50 + a direct 2.00 = 10.50 over 4 runs, before and after `git worktree remove` deletes the results
        self.result(self.wt, "2026-10-24T05:00:00.000Z", 2.0)
        args = ("today", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        want = "2026-10-24: spent $10.50 of the $10 cap, 4 runs"
        self.assertEqual(self.run_bin(*args).stdout.strip(), want)
        self.remove_wt()
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.run_bin(*args).stdout.strip(), want)

    def test_the_guard_counts_a_removed_direct_run(self):
        # F1 pass 2: cap 18; 8.50 + direct 1.50 = 10.00, + estimate 9.00 (largest stored batch) = 19 > 18, after the removal too
        self.run_bin("cap", "18")
        self.result(self.wt, "2026-10-24T05:00:00.000Z", 1.5)
        args = ("guard", "eval", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.assertEqual(self.run_bin(*args).returncode, 1)
        self.remove_wt()
        done = self.run_bin(*args)
        self.assertEqual(done.returncode, 1)
        self.assertIn("$10.00 is spent", done.stdout)

    def test_a_bin_ci_run_counts_once_after_removal(self):
        # F1 pass 3: same startedAt as stored record "a" (4.00): 8.50 over 3 runs, removal or not
        self.result(self.wt, "2026-10-24T01:00:00.000Z", 4.0)
        args = ("today", "--today", "2026-10-24", "--dir", os.path.join(self.home, "evals", "repo"))
        self.run_bin(*args)
        self.remove_wt()
        self.assertEqual(self.run_bin(*args).stdout.strip(), "2026-10-24: spent $8.50 of the $10 cap, 3 runs")

    def test_a_direct_run_stays_out_of_the_batch_estimate(self):
        # F1 pass 4: the largest stored batch is 9.00; a direct 50.00 run is not a batch
        self.result(self.wt, "2026-10-24T05:00:00.000Z", 50.0)
        self.run_bin("today", "--today", "2026-10-24")
        self.assertEqual(relay_paidcap.eval_estimate(self.home), 9.0)

    def test_bench_check_sees_a_direct_run(self):
        # F2: stored 7.00 + bench 1.50 + direct 1.50 = 10.00; bench estimate 0.50 -> refused naming $10.00
        self.result(self.wt, "2026-10-24T05:00:00.000Z", 1.5)
        saved = {k: os.environ.get(k) for k in ("RELAY_HOME", "RELAY_PROJECTS")}
        os.environ["RELAY_HOME"], os.environ["RELAY_PROJECTS"] = self.home, self.projects
        real_dt, real_root = relay_bench.dt, relay_bench.ROOT

        class FixedDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.datetime(2026, 10, 24, 12, 0, 0, tzinfo=tz)

        class FixedModule:
            def __getattr__(self, name):
                return FixedDatetime if name == "datetime" else getattr(real_dt, name)

        relay_bench.dt, relay_bench.ROOT = FixedModule(), self.root

        def restore():
            relay_bench.dt, relay_bench.ROOT = real_dt, real_root
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.addCleanup(restore)
        relay_paidcap.bench_estimate = (lambda orig: lambda s, b=None, home=None: 0.5)(relay_paidcap.bench_estimate)
        self.addCleanup(setattr, relay_paidcap, "bench_estimate", relay_paidcap.bench_estimate)
        with self.assertRaises(relay_bench.PaidCapReached) as cm:
            relay_bench.run_bench([{"profile": {}}], [{"name": "s", "runs": 1}], out_root=os.path.join(self.home, "bench"))
        self.assertIn("$10.00 is spent", str(cm.exception))

    def test_suite_roots_is_time_limited_and_lists_both_checkouts(self):
        # F3: two checkouts listed; a hung git (TimeoutExpired) gives []
        self.assertEqual(sorted(os.path.realpath(r) for r in relay_paidcap.suite_roots(self.root)),
                         sorted(os.path.realpath(r) for r in (self.root, self.wt)))
        real = relay_paidcap.subprocess.run

        def hang(*a, **k):
            self.assertIn("timeout", k)
            raise subprocess.TimeoutExpired(a[0], k["timeout"])
        relay_paidcap.subprocess.run = hang
        self.addCleanup(setattr, relay_paidcap.subprocess, "run", real)
        self.assertEqual(relay_paidcap.suite_roots(self.root), [])
