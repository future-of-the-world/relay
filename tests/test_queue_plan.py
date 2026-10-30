"""A task's plan is kept beside its queue item as .relay/queue/<slug>.plan.md, written only by `relay queue plan`
(design: reports-a-task-needs-are-kept-in-the-repository, revision 4, with the owner's answers: no review file).
Scratch repositories in a temp dir; expected values are worked out by hand in the comments."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402
from relay_testbase import ROOT, load_hook  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "plugins", "relay", "lib"))
import kit_guard  # noqa: E402
import relay_lanes  # noqa: E402

rq = tq.rq
git = tq.git
QUEUE = ".relay/queue/"
NO_ENV: dict = {}      # an empty environment: the size cap is its default (200 KB)
GUARD = os.path.join(ROOT, "plugins", "relay", "hooks", "guard-main.sh")
MERGE = os.path.join(ROOT, "plugins", "relay", "hooks", "merge.py")


class PlanBase(tq.Base):
    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {QUEUE + "zz.json": tq.feature_item("Zz", ip=20)}, "item zz")
        self.src = os.path.join(self.tmp, "p.md")
        self.put("# Plan\n\nfirst version\n")

    def put(self, text):
        with open(self.src, "w", encoding="utf-8") as handle:
            handle.write(text)

    def keep(self, slug="zz", **kw):
        return rq.keep_plan(self.main, slug, self.src, environ=kw.pop("environ", NO_ENV), **kw)

    def commits(self, path):
        return [c for c in git(self.main, "log", "--format=%H", "--", path).split("\n") if c]

    def last_files(self):
        return sorted(f for f in git(self.main, "diff", "--name-only", "HEAD~1", "HEAD").split("\n") if f)


class Readers(PlanBase):
    def test_readers_skip_plans_and_still_report_a_bad_item(self):
        # zz.plan.md beside zz.json: one item "zz" in the list, and check_files finds nothing, as without the plan.
        self.keep()
        self.assertEqual([i["slug"] for i in rq.read_queue(self.main, closed=True)], ["zz"])
        self.assertEqual(rq.check_files(self.main), [])
        # a malformed zz2.json beside the plan is still reported (by name), the plan is not
        with open(os.path.join(self.main, QUEUE + "zz2.json"), "w") as handle:
            handle.write("{}\n")
        self.assertEqual([p for p, _ in rq.check_files(self.main)], [QUEUE + "zz2.json"])

    def test_a_dotted_json_is_named_not_an_item(self):
        # a review as JSON beside an item would be read as a broken item by every reader; check names it as not an item
        with open(os.path.join(self.main, QUEUE + "zz.plan-review.json"), "w") as handle:
            handle.write("{}\n")
        (path, reasons), = rq.check_files(self.main)
        self.assertEqual(path, QUEUE + "zz.plan-review.json")
        self.assertIn("not an item", reasons[0])
        self.assertIn("<slug>.plan.md", reasons[0])

    def test_orphans_and_strangers_are_reported_but_machine_files_are_not(self):
        for name in ("yy.plan.md", "zz.notes.txt", ".DS_Store"):
            with open(os.path.join(self.main, QUEUE + name), "w") as handle:
                handle.write("x\n")
        got = dict(rq.check_files(self.main))
        # yy has no yy.json; the txt is no queue file; .DS_Store is the machine's
        self.assertEqual(sorted(got), [QUEUE + "yy.plan.md", QUEUE + "zz.notes.txt"])
        self.assertIn("no item", got[QUEUE + "yy.plan.md"][0])


class Keep(PlanBase):
    def test_only_changed_files_are_written_and_history_is_kept(self):
        out = self.keep()
        self.assertTrue(out.splitlines()[-1].startswith("plan zz: landed on master at "))
        self.assertEqual(self.last_files(), [QUEUE + "zz.plan.md"])
        # same bytes: no commit, "unchanged"
        before = git(self.main, "rev-parse", "HEAD")
        self.assertEqual(self.keep(), "plan zz: unchanged")
        self.assertEqual(git(self.main, "rev-parse", "HEAD"), before)
        # a different plan: a second commit on the plan's own history (2 versions)
        self.put("# Plan\n\nsecond version\n")
        self.keep()
        self.assertEqual(len(self.commits(QUEUE + "zz.plan.md")), 2)
        self.assertEqual(self.last_files(), [QUEUE + "zz.plan.md"])
        self.assertEqual(git(self.main, "show", "master:" + QUEUE + "zz.plan.md"), "# Plan\n\nsecond version")

    def test_the_item_is_not_touched(self):
        before = git(self.main, "rev-parse", "master:" + QUEUE + "zz.json")
        self.keep()
        self.assertEqual(git(self.main, "rev-parse", "master:" + QUEUE + "zz.json"), before)
        line = rq.plan_line(self.main, "zz")
        # the file is "# Plan\n\nfirst version\n" (22 bytes: under 1 KB, shown as 1 KB), one version
        self.assertTrue(line.startswith("Plan: " + os.path.join(self.main, QUEUE + "zz.plan.md") + " (1 KB, 1 version, last "), line)
        self.assertIsNone(rq.plan_line(self.main, "nope"))

    def test_a_dropped_or_closed_item_takes_a_plan_and_a_missing_one_names_add(self):
        dropped = tq.with_fields(tq.feature_item("Gone", ip=1), dropped_at="2026-10-04T00:00:00Z", dropped_why=["no"])
        closed = tq.with_fields(tq.fix_item("Shut"), **tq.taken_fields("wt/a"), closed_at=tq.CLOSED_AT, test="tests/t.py::test_job")
        self.write_commit(self.main, {QUEUE + "gone.json": dropped, QUEUE + "shut.json": closed}, "two finished items")
        self.assertIn("landed", self.keep("gone"))
        self.assertIn("landed", self.keep("shut"))
        with self.assertRaises(rq.Refused) as ctx:
            self.keep("nobody")
        self.assertIn("relay queue add", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(self.main, QUEUE + "nobody.plan.md")))

    def test_the_size_cap(self):
        # default cap 200 KB: 72 KB (the largest plan seen) passes, 201 KB is refused naming the cap and the setting
        self.put("a" * (72 * 1024))
        self.assertIn("landed", self.keep())
        self.put("a" * (201 * 1024))
        with self.assertRaises(rq.Refused) as ctx:
            self.keep()
        self.assertIn("200 KB", str(ctx.exception))
        self.assertIn("RELAY_PLAN_MAX_KB", str(ctx.exception))
        # the setting is clamped to 20-2000 and falls back to 200 when it is not a number
        self.assertEqual([rq.plan_cap_kb({"RELAY_PLAN_MAX_KB": v}) for v in ("5", "50", "9999", "x")], [20, 50, 2000, 200])

    def test_a_key_shape_and_the_home_folder_are_removed(self):
        key = "sk-ant-" + "a" * 40
        self.put(f"ok\nthe key {key} here\n/Users/dummy/relay/x.py\n")
        out = self.keep(home="/Users/dummy")
        # the key is on line 2 of the file; the home prefix becomes ~
        self.assertIn("line 2", out)
        self.assertIn("rotate the key", out)
        text = git(self.main, "show", "master:" + QUEUE + "zz.plan.md")
        self.assertEqual(text, "ok\nthe key <redacted> here\n~/relay/x.py")
        # 7 + 17 = 24 characters but the tail is under 20: not a key shape
        self.put("test string sk-ant-" + "x" * 17 + "\n")
        self.assertEqual(self.keep().count("line"), 0)
        self.assertIn("sk-ant-" + "x" * 17, git(self.main, "show", "master:" + QUEUE + "zz.plan.md"))

    def test_an_empty_or_missing_plan_file_is_refused(self):
        self.put("  \n")
        with self.assertRaises(rq.Refused):
            self.keep()
        os.remove(self.src)
        with self.assertRaises(rq.Refused):
            self.keep()


class Briefs(PlanBase):
    def test_the_plan_opens_from_a_worktree_made_before_it_landed(self):
        w = self.worktree("early")
        self.assertIsNone(rq.plan_path(w, "zz"))
        item = rq.read_queue(self.main)[0]
        design = relay_lanes.design_brief(item, w, self.tmp, "zz", rq.plan_path(w, "zz"))
        self.assertNotIn("Earlier plan", design)
        self.keep()
        path = rq.plan_path(w, "zz")
        # the main checkout's absolute path, not the worktree's: the worktree has no such file
        self.assertEqual(path, os.path.join(self.main, QUEUE + "zz.plan.md"))
        self.assertFalse(os.path.exists(os.path.join(w, QUEUE + "zz.plan.md")))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "# Plan\n\nfirst version\n")
        state = relay_lanes.State(setting=4, running=[], free=4, picks=[], waits=[], landed_open=[], quiet=[])
        build = relay_lanes.build_brief(item, w, "wt/early", self.tmp, "zz", state, "check", path)
        self.assertIn("Plan: " + path, build)
        self.assertNotIn("Plan:", relay_lanes.build_brief(item, w, "wt/early", self.tmp, "zz", state, "check", None))
        design = relay_lanes.design_brief(item, w, self.tmp, "zz", path)
        self.assertIn("Earlier plan: " + path, design)
        # the last step of every design brief is the keep command with this item and this output
        self.assertIn(f"relay queue plan zz --input {self.tmp}/reports/design-zz.md", design)


class Guarded(PlanBase):
    def hook(self, event):
        done = subprocess.run([GUARD], input=json.dumps(event), capture_output=True, text=True)
        return done.returncode, done.stderr

    def test_write_tool_and_shell_cannot_write_any_queue_file(self):
        w = self.worktree("g")
        target = os.path.join(w, QUEUE + "zz.plan.md")
        rc, err = self.hook({"tool_name": "Write", "cwd": w, "agent_id": "a1", "tool_input": {"file_path": target}})
        self.assertEqual(rc, 2)
        self.assertIn("relay queue plan", err)
        rc, _ = self.hook({"tool_name": "Write", "cwd": w, "agent_id": "a1", "tool_input": {"file_path": os.path.join(self.tmp, "scratch.md")}})
        self.assertEqual(rc, 0)   # a file outside the queue folder stays free
        rc, err = self.hook({"tool_name": "Bash", "cwd": w, "agent_id": "a1", "tool_input": {"command": f"cp {self.src} {target}"}})
        self.assertEqual(rc, 2)
        self.assertIn("relay queue plan", err)
        rc, _ = self.hook({"tool_name": "Bash", "cwd": w, "agent_id": "a1", "tool_input": {"command": f"cat {target}"}})
        self.assertEqual(rc, 0)   # reading is free

    def test_shell_rule_covers_every_file_of_the_folder(self):
        def kinds(cmd):
            return [row[0] for row in kit_guard.analyze(cmd, self.tmp, [])]
        self.assertIn("Y", kinds("cp f.md .relay/queue/zz.plan.md"))
        self.assertIn("Y", kinds("echo x > .relay/queue/zz.plan.md"))
        self.assertIn("Y", kinds("echo x > .relay/queue/zz.json"))
        self.assertNotIn("Y", kinds("cat .relay/queue/zz.plan.md"))


class MergeHook(PlanBase):
    def setUp(self):
        super().setUp()
        self.hook = load_hook("merge_hook_plan_test", MERGE)

    def test_a_branch_that_adds_a_plan_is_refused_but_one_that_took_master_is_not(self):
        w = self.worktree("p")
        # master gains a plan through the writer; the branch takes master by a merge: the plan is not in default...branch
        self.keep()
        git(w, "merge", "-q", "--no-edit", "master")
        self.hook.step_plan_files(self.main, "master", "refs/heads/wt/p")
        # the branch adds its own plan by hand: refused, naming the command
        self.write_commit(w, {QUEUE + "zz.plan.md": "by hand\n"}, "hand")
        with self.assertRaises(self.hook.Refused) as ctx:
            self.hook.step_plan_files(self.main, "master", "refs/heads/wt/p")
        self.assertIn("relay queue plan", str(ctx.exception))
        # the merge step that runs for every branch reaches it
        with self.assertRaises(self.hook.Refused) as ctx:
            self.hook.step_queue(self.main, "master", "wt/p")
        self.assertIn("plan zz.plan.md changed by hand", str(ctx.exception))


class Surface(unittest.TestCase):
    def test_help_lists_the_form(self):
        done = subprocess.run([os.path.join(ROOT, "bin", "relay"), "queue", "--help"], capture_output=True, text=True,
                              env={k: v for k, v in os.environ.items() if k != "RELAY_ROOT"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("relay queue plan <slug> --input <file.md>", done.stdout)


if __name__ == "__main__":
    mock.patch.stopall()
    unittest.main()
