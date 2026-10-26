"""Free tests of `bin/paid-cost due` (the merged changes no green paid run covers) and of the record's head/branch.
Each test builds its own git repository and record folder in a temporary directory; no model is called."""
import json, os, subprocess, tempfile, unittest
from importlib.machinery import SourceFileLoader
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAID = os.path.join(ROOT, "bin", "paid-cost")
RECORD = os.path.join(ROOT, "bin", "eval-record")


def load_record():
    loader = SourceFileLoader("eval_record_t", RECORD)
    spec = importlib.util.spec_from_loader("eval_record_t", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m)
    return m


def passing():
    return {"startedAt": "2026-10-24T10:00:00.000Z", "costUsd": 1.0, "cases": []}


class Due(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.repo = os.path.join(t.name, "repo"); self.rec = os.path.join(t.name, "records")
        os.makedirs(self.repo); os.makedirs(self.rec)
        self.git("init", "-q", "-b", "main")
        self.n = 0

    def git(self, *a):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return subprocess.run(["git", "-C", self.repo, *a], capture_output=True, text=True, check=True, env=env).stdout.strip()

    def commit(self, path, subject):
        self.n += 1
        full = os.path.join(self.repo, path); os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "a") as f:
            f.write(f"{self.n}\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", subject)
        return self.git("rev-parse", "HEAD")

    def record(self, name, head, branch="main", data=None):
        d = dict(data or passing())
        if head is not None:
            d["head"] = head
        d["branch"] = branch
        with open(os.path.join(self.rec, name), "w") as f:
            json.dump(d, f)

    def due(self):
        return subprocess.run(["python3", PAID, "due", "--repo", self.repo, "--dir", self.rec], capture_output=True, text=True)

    def test_lists_checked_path_commits_after_the_green_head(self):
        self.commit("rules/a.md", "before")
        green = self.commit("README.md", "the green head")
        self.commit("rules/b.md", "rule b")
        self.commit("docs/x.md", "docs only")          # not a checked path
        self.commit("plugins/front/skills/s/SKILL.md", "skill s")
        self.record("1.json", green)
        done = self.due()
        # only the two commits after the green head that touch checked paths, newest first; "before" is inside the green head
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([l.split(" ", 1)[1] for l in done.stdout.splitlines()], ["skill s", "rule b"])

    def test_nothing_due_prints_nothing(self):
        self.commit("rules/a.md", "a")
        self.record("1.json", self.git("rev-parse", "HEAD"))
        done = self.due()
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_checked_paths_each_count(self):
        green = self.commit("README.md", "start")
        subjects = []
        for p in ("roles/r.md", "plugins/x/agents/a.md", "plugins/x/hooks/h.sh", "evals/plugin/c.json", "bin/ci", "lib/l.py"):
            self.commit(p, p); subjects.append(p)
        self.record("1.json", green)
        got = sorted(l.split(" ", 1)[1] for l in self.due().stdout.splitlines())
        # bin/ and lib/ are not checked by the paid evals
        self.assertEqual(got, sorted(subjects[:4]))

    def test_a_plugin_rule_file_counts(self):
        # plugins/openspec/rules/openspec.md is what the spec-step evals put in front of the session: a commit that
        # changes it is due like a change under rules/
        green = self.commit("README.md", "start")
        self.commit("plugins/openspec/rules/openspec.md", "plugin rule")
        self.record("1.json", green)
        self.assertEqual([l.split(" ", 1)[1] for l in self.due().stdout.splitlines()], ["plugin rule"])

    def test_no_green_record_lists_all_and_says_so(self):
        self.commit("rules/a.md", "a"); self.commit("rules/b.md", "b")
        out = self.due().stdout.splitlines()
        self.assertEqual(out[0], "no green run recorded")
        self.assertEqual([l.split(" ", 1)[1] for l in out[1:]], ["b", "a"])

    def test_no_green_record_caps_at_fifty_with_a_count(self):
        for i in range(53):
            self.commit("rules/a.md", f"c{i}")
        out = self.due().stdout.splitlines()
        # 53 commits: the count line, then the newest 50 (c52 down to c3)
        self.assertEqual(out[1], "53 commits in all, the newest 50 listed")
        self.assertEqual(len(out), 2 + 50)
        self.assertTrue(out[2].endswith("c52")); self.assertTrue(out[-1].endswith("c3"))

    def test_record_without_head_is_ignored(self):
        self.commit("rules/a.md", "a")
        self.record("1.json", None)
        self.assertEqual(self.due().stdout.splitlines()[0], "no green run recorded")

    def test_record_of_another_branch_is_ignored(self):
        h = self.commit("rules/a.md", "a")
        self.record("1.json", h, branch="wt/other")
        self.assertEqual(self.due().stdout.splitlines()[0], "no green run recorded")

    def test_not_judged_run_is_not_green(self):
        h = self.commit("rules/a.md", "a")
        # a meaning grader without three votes was not judged (bin/eval-record's rule), so the record is not a pass
        bad = {"startedAt": "x", "costUsd": 1, "cases": [{"name": "c", "graders": [{"name": "g", "type": "llm"}],
               "arms": {"with": [{"graders": []}]}}]}
        self.record("1.json", h, data=bad)
        self.assertEqual(self.due().stdout.splitlines()[0], "no green run recorded")

    def test_partial_batch_is_not_green(self):
        h = self.commit("rules/a.md", "a")
        self.record("1.json", h, data=dict(passing(), partial=True))
        self.assertEqual(self.due().stdout.splitlines()[0], "no green run recorded")

    def test_git_error_exits_nonzero_with_the_message(self):
        done = subprocess.run(["python3", PAID, "due", "--repo", os.path.join(self.rec, "nope"), "--dir", self.rec], capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")
        self.assertIn("paid-cost:", done.stderr)


class CodeGrader(unittest.TestCase):
    def data(self, passed):
        return {"startedAt": "x", "costUsd": 1, "cases": [{"name": "c", "graders": [{"name": "rx", "type": "regex", "config": {"pattern": "p"}}],
                "arms": {"with": [{"graders": [{"name": "rx", "passed": passed}]}]}}]}

    def test_failed_regex_grader_is_not_green_and_exits_nonzero(self):
        # the only failure is a code grader with passed false: not a pass, in both is_green and the report's last line
        m = load_record()
        self.assertFalse(m.is_green(self.data(False)))
        self.assertIn("NOT A PASS", m.report(self.data(False), "")[-1])

    def test_passing_regex_grader_is_green(self):
        m = load_record()
        self.assertTrue(m.is_green(self.data(True)))


class RecordHead(unittest.TestCase):
    def test_store_writes_head_and_branch(self):
        m = load_record()
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "evals.json")
            json.dump(passing(), open(src, "w"))
            dest = m.store(src, passing(), t, "relay", "main", 30, "a" * 40)
            d = json.load(open(dest))
        self.assertEqual((d["head"], d["branch"]), ("a" * 40, "main"))
        self.assertTrue(dest.endswith("-main.json"))

    def test_is_green_matches_the_exit_verdict(self):
        m = load_record()
        self.assertTrue(m.is_green(passing()))
        self.assertFalse(m.is_green(dict(passing(), partial=True)))


class SyncWaits(unittest.TestCase):
    def run_sync(self, *args):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        target = os.path.join(t.name, "a", "CLAUDE.local.md"); os.makedirs(os.path.dirname(target))
        projects = os.path.join(t.name, "projects.toml")
        open(projects, "w").write('[a]\nfile = "%s"\nload = ["quality-gate"]\nread = []\n' % target)
        env = {k: v for k, v in os.environ.items() if k != "RELAY_SKIP_PAID_DUE"}
        # an empty RELAY_HOME holds no green record, so every checked-path commit of this repository is due
        env.update(RELAY_PROJECTS=projects, RELAY_HOME=os.path.join(t.name, "home"), CLAUDE_CONFIG_DIR=os.path.join(t.name, "claude"), RELAY_ROOT=ROOT)
        done = subprocess.run(["python3", os.path.join(ROOT, "bin", "relay"), "sync", *args, "a"], env=env, capture_output=True, text=True)
        return done, os.path.exists(target)

    def test_sync_refuses_with_the_due_list_and_writes_nothing(self):
        done, written = self.run_sync()
        self.assertEqual(done.returncode, 1)
        self.assertIn("waits for a green paid run", done.stderr)
        self.assertIn("no green run recorded", done.stderr)
        self.assertFalse(written)

    def test_sync_agents_only_does_not_wait(self):
        # agents are assembled inside the checkout, so a due list does not hold them (the worker's step in a worktree);
        # --dry would skip the wait anyway, so run it for real into an empty copy of the machine state
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        env = {k: v for k, v in os.environ.items() if k != "RELAY_SKIP_PAID_DUE"}
        env.update(RELAY_HOME=os.path.join(t.name, "home"), CLAUDE_CONFIG_DIR=os.path.join(t.name, "claude"), RELAY_ROOT=ROOT)
        done = subprocess.run(["python3", os.path.join(ROOT, "bin", "relay"), "sync", "agents"], env=env, capture_output=True, text=True)
        self.assertNotIn("waits for a green paid run", done.stderr)

    def test_sync_dry_still_prints_its_plan(self):
        done, written = self.run_sync("--dry")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a: would write", done.stdout)
        self.assertFalse(written)


class OtherCallersWait(unittest.TestCase):
    def test_rules_sync_raises_held_for_global_but_not_for_agents(self):
        # relay_rules.sync is the one place every caller (setup, adopt, sync) passes; with a due list it refuses a
        # target outside the checkout; dry and wait=False (install) go through
        import sys
        lib = os.path.join(ROOT, "lib")
        sys.path.insert(0, lib); self.addCleanup(sys.path.remove, lib)
        import relay_rules
        saved = os.environ.pop("RELAY_SKIP_PAID_DUE", None)
        if saved is not None:
            self.addCleanup(os.environ.__setitem__, "RELAY_SKIP_PAID_DUE", saved)
        self.addCleanup(setattr, relay_rules, "paid_due", relay_rules.paid_due)
        relay_rules.paid_due = lambda: "abc1234 a rule"
        with self.assertRaises(relay_rules.Held):
            relay_rules.sync({}, only={"global"})
        with self.assertRaises(relay_rules.Held):
            relay_rules.sync({})
        relay_rules.sync({}, only={"global"}, dry=True)
        relay_rules.sync({}, only={"global"}, dry=True, wait=False)


if __name__ == "__main__":
    unittest.main(verbosity=1)
