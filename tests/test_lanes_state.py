"""Lanes derived from git and the queue, the free-lane line, the Stop refusal, the close at landing and `relay queue start`.
Scratch repositories in a temp dir; time is a value passed in (epoch seconds); nothing touches the live queue."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402

sys.path.insert(0, os.path.join(tq.ROOT, "lib"))
import relay_lanes as rl  # noqa: E402

# the queue module relay_lanes itself holds: a test that dropped relay_* from sys.modules before this file was imported leaves
# tq.rq a different copy, and a mock or an exception class taken from it would miss the one relay_lanes uses
rq = rl.relay_queue
git = tq.git
NOW = 2_000_000_000.0
Q = ".relay/queue/"


def item(slug, kind="fix", ip=90, where=("lib/a.py",), **fields):
    """An item file as text; `fields` (taken_at, taken_by, notes ...) are set around the library."""
    new = rq.new_item(kind, ip, 10, "2026-10-01T00:00:00Z", "test", f"Title of {slug}", "what is wanted here", "it matters",
                      failing="the case fails" if kind == "fix" else "", pass_cases="the other case" if kind == "fix" else "",
                      where=list(where), failing_kind="claim" if kind == "fix" else "")
    return tq.raw_item(rq.serialize(slug, new), **fields)


def taken(by):
    return {"taken_at": tq.TAKEN_AT, "taken_by": by}


class LaneBase(tq.Base):
    def seed(self, files):
        if files:
            self.write_commit(self.main, files, "seed")

    def branch_with_commit(self, name, files, message="work"):
        """A worktree on wt/<name> with a commit changing `files`; returns its path."""
        path = self.worktree(name)
        self.write_commit(path, files, message)
        return path

    def state(self, limit=6, **kw):
        return rl.lanes_state(self.main, now=NOW, limit=limit, **kw)



class Lanes(LaneBase):
    def test_lane_running_without_commits(self):
        # wt/x was just taken: no own commit, tip == master. It runs; it is not "landed" (a fast-forward alone is not a landing).
        self.seed({Q + "x.json": item("x", **taken("wt/x"))})
        self.worktree("x")
        s = self.state()
        self.assertEqual([(l.branch, l.slug) for l in s.running], [("wt/x", "x")])
        self.assertEqual((s.landed_open, s.free), ([], 5))

    def test_lane_landed_still_open_fast_forward_and_both_train_forms(self):
        self.seed({Q + "a.json": item("a", "feature", **taken("wt/a")), Q + "b.json": item("b", "feature", **taken("wt/b")),
                   Q + "c.json": item("c", "feature", **taken("wt/c")), Q + "d.json": item("d", "feature", **taken("wt/d"))})
        for name in "abcd":
            self.branch_with_commit(name, {f"lib/{name}.py": "x\n"})
        git(self.main, "merge", "-q", "--ff-only", "wt/a")                        # a: fast-forward, ref kept
        git(self.main, "merge", "-q", "--no-ff", "-m", "Merge branch 'wt/b' into wt/train-3", "wt/b")     # b: first merge form, ref deleted below
        git(self.main, "merge", "-q", "--no-ff", "-m", "Merge wt/c into train-22b", "wt/c")               # c: second merge form
        git(self.main, "worktree", "remove", "--force", os.path.join(self.tmp, "b"))
        git(self.main, "worktree", "remove", "--force", os.path.join(self.tmp, "c"))
        git(self.main, "branch", "-D", "wt/b", "wt/c")
        s = self.state()
        # d has own commits and is not on master: running. a, b, c landed.
        self.assertEqual(sorted(x.slug for x in s.landed_open), ["a", "b", "c"])
        self.assertEqual([l.slug for l in s.running], ["d"])
        by = {x.slug: x for x in s.landed_open}
        self.assertEqual(by["b"].sha, git(self.main, "rev-parse", "HEAD~1"))    # the merge commit of b (c is the newest)

    def test_ref_gone_without_a_merge_is_not_running_and_not_landed(self):
        # a dropped branch: the item stays taken, no lane is running for it, nothing landed
        self.seed({Q + "g.json": item("g", "feature", **taken("wt/g"))})
        s = self.state()
        self.assertEqual((s.running, s.landed_open), ([], []))
        self.assertTrue(any("wt/g (gone" in q for q in s.quiet))

    def test_lane_no_item_worktree_by_recency(self):
        self.seed({})
        self.worktree("y")
        # reflog time of the creation is the real clock; NOW is far later than it: quiet. Put "now" at the real time: running.
        import time
        self.assertEqual([l.branch for l in rl.lanes_state(self.main, now=time.time(), limit=6).running], ["wt/y"])
        later = rl.lanes_state(self.main, now=time.time() + 4 * 3600, limit=6)          # 4 h > the 3 h setting
        self.assertEqual(later.running, [])
        self.assertIn("wt/y (quiet)", later.quiet)
        self.assertEqual(len(rl.lanes_state(self.main, quiet_hours=5, now=time.time() + 4 * 3600, limit=6).running), 1)

    def _train(self):
        """wt/a and wt/b with own commits, merged into the open wt/train-1; returns the train's worktree."""
        self.seed({Q + "a.json": item("a", **taken("wt/a")), Q + "b.json": item("b", **taken("wt/b")), Q + "c.json": item("c", **taken("wt/c"))})
        self.branch_with_commit("a", {"lib/a.py": "x\n"})
        self.branch_with_commit("b", {"lib/b.py": "x\n"})
        train = self.branch_with_commit("train-1", {"lib/t.py": "x\n"})
        git(train, "merge", "-q", "--no-ff", "-m", "Merge wt/a into wt/train-1", "wt/a")
        git(train, "merge", "-q", "--no-ff", "-m", "Merge wt/b into wt/train-1", "wt/b")
        return train

    def test_riders_of_an_open_train_are_one_lane(self):
        # a and b are merged into the open train-1: three branches, one lane (the train). Setting 2: 1 of 2 running, one item can start.
        self._train()
        s = self.state(limit=2)
        self.assertEqual([l.branch for l in s.running], ["wt/train-1"])
        self.assertEqual(s.free, 1)

    def test_rider_not_yet_in_the_train_is_its_own_lane(self):
        # c has own commits and is in no train: it counts besides the train. Setting 2: 2 of 2, nothing free.
        self._train()
        self.branch_with_commit("c", {"lib/c.py": "x\n"})
        s = self.state(limit=2)
        self.assertEqual(sorted(l.branch for l in s.running), ["wt/c", "wt/train-1"])
        self.assertEqual(s.free, 0)

    def test_trains_not_lanes(self):
        self.seed({})
        self.branch_with_commit("train-9", {"lib/t.py": "x\n"})
        s = rl.lanes_state(self.main, limit=6)
        self.assertEqual((s.running, s.quiet), ([], []))

    def test_free_zero_six_mixed(self):
        # setting 2: one taken lane without commits, one with commits, free 0: no line, no Stop refusal even with startable items
        self.seed({Q + "x.json": item("x", **taken("wt/x")), Q + "y.json": item("y", **taken("wt/y")), Q + "z.json": item("z")})
        self.worktree("x")
        self.branch_with_commit("y", {"lib/y.py": "1\n"})
        s = self.state(limit=2)
        self.assertEqual((len(s.running), s.free, s.picks), (2, 0, []))
        self.assertIsNone(rl.line(s))
        stamp = os.path.join(self.tmp, "stamps", "s1.json")
        self.assertIsNone(rl.stop_refusal(s, stamp, 1, "s1"))

    def test_line_skips_taken_and_follows_queue_order(self):
        # order: fixes before features, then ip. Free lanes 3 of 4 (one running): picks are the top three untaken items.
        self.seed({Q + "run.json": item("run", **taken("wt/run")), Q + "f1.json": item("f1", ip=80, where=("lib/q.py",)),
                   Q + "f2.json": item("f2", ip=95, where=("lib/r.py",)), Q + "ft.json": item("ft", "feature", ip=99, where=("lib/s.py",)),
                   Q + "f3.json": item("f3", ip=70, where=("lib/t.py",))})
        self.worktree("run")
        s = self.state(limit=4)
        # f2 (fix 95), f1 (fix 80), f3 (fix 70) fill the 3 free lanes; ft (feature, 99) comes after every fix
        self.assertEqual([(p.slug, p.mode) for p in s.picks], [("f2", "start"), ("f1", "start"), ("f3", "start")])
        text = rl.line(s, 2)
        self.assertEqual(text, "Lanes: 1 of 4 running; start: f2 (fix, ip 95), start: f1 (fix, ip 80)")

    def test_readiness_feature_is_design_and_unanswered_question_is_skipped(self):
        asked = {"asked_at": "2026-10-09T22:00:00Z", "question": ["**Keep it?**"], "options": ["a. Yes.", "b. No."]}
        self.seed({Q + "ft.json": item("ft", "feature", ip=50, where=("lib/s.py",)), Q + "fx.json": item("fx", ip=60, where=("lib/q.py",)),
                   Q + "ask.json": item("ask", ip=99, where=("lib/z.py",), notes=[asked]),
                   Q + "dz.json": item("dz", ip=40, where=("plugins/x design to redo",))})
        s = self.state(limit=6)
        self.assertEqual([(p.slug, p.mode) for p in s.picks], [("fx", "start"), ("dz", "design"), ("ft", "design")])
        self.assertIn("design: dz (fix, ip 40), design: ft (feature, ip 50)", rl.line(s))

    def test_overlap_skip(self):
        # wt/run changed lib/relay_setup.py (committed) and wrote lib/new.py (uncommitted). Items naming either wait, with the branch; a free file starts.
        self.seed({Q + "run.json": item("run", **taken("wt/run")), "lib/relay_setup.py": "0\n",
                   Q + "s.json": item("s", ip=95, where=("lib/relay_setup.py:10-20 the setup",)),
                   Q + "n.json": item("n", ip=94, where=("lib/new.py",)), Q + "free.json": item("free", ip=93, where=("lib/other.py",))})
        path = self.worktree("run")
        self.write_commit(path, {"lib/relay_setup.py": "1\n"}, "edit setup")
        with open(os.path.join(path, "lib", "new.py"), "w") as handle:
            handle.write("n\n")
        before = git(self.main, "status", "--porcelain"), git(self.main, "rev-parse", "master")
        s = self.state(limit=3)
        self.assertEqual([(w.slug, w.file, w.branch) for w in s.waits], [("s", "lib/relay_setup.py", "wt/run"), ("n", "lib/new.py", "wt/run")])
        self.assertEqual([p.slug for p in s.picks], ["free"])
        self.assertIn("waits: s (lib/relay_setup.py, wt/run), n (lib/new.py, wt/run)", rl.line(s))
        self.assertEqual((git(self.main, "status", "--porcelain"), git(self.main, "rev-parse", "master")), before)    # it reads git only

    def test_overlap_ignores_inert_files_and_a_file_the_branch_only_has_from_master(self):
        # the branch carries master's lib/a.py (merged in) but changed nothing: nothing waits
        self.seed({Q + "run.json": item("run", **taken("wt/run")), Q + "w.json": item("w", ip=95, where=("lib/a.py",)), "lib/a.py": "0\n"})
        self.worktree("run")
        self.write_commit(self.main, {"lib/a.py": "1\n"}, "master moves on")
        s = self.state()
        self.assertEqual(([w.slug for w in s.waits], [p.slug for p in s.picks]), ([], ["w"]))

    def test_lanes_setting_from_the_instruction_file(self):
        self.assertEqual(rl.lanes_setting(self.main), 4)
        with open(os.path.join(self.main, "CLAUDE.local.md"), "w") as handle:
            handle.write("# x\n\nChanges built at once: 6.\n")
        self.assertEqual(rl.lanes_setting(self.main), 6)

    def test_setting_bounds(self):
        self.assertEqual(rl.setting({"front": {"stop_nudge": 5}}, "stop_nudge"), 2)
        self.assertEqual(rl.setting({"front": {"stop_nudge": True}}, "stop_nudge"), 1)
        self.assertEqual(rl.setting({"front": {"lanes_line_items": 0}}, "lanes_line_items"), 1)
        self.assertEqual(rl.setting({}, "lane_quiet_hours"), 3)


class Stop(LaneBase):
    def free_state(self):
        self.seed({Q + "a.json": item("a")})
        return self.state(limit=2)

    def test_stop_nudge_once_per_state(self):
        s = self.free_state()
        stamp = os.path.join(self.tmp, "stamps", "s1.json")
        first = rl.stop_refusal(s, stamp, 1, "s1")
        self.assertIn("Lanes: 0 of 2 running; start: a (fix, ip 90)", first)
        self.assertIsNone(rl.stop_refusal(s, stamp, 1, "s1"))                     # the same state: once
        self.assertIsNotNone(rl.stop_refusal(s, os.path.join(self.tmp, "stamps", "s2.json"), 1, "s2"))     # another session has its own stamp
        self.worktree("w")                                                        # the state changed (a lane runs): refused again
        import time
        self.assertIsNotNone(rl.stop_refusal(rl.lanes_state(self.main, now=time.time(), limit=2), stamp, 1, "s1"))
        self.assertIsNone(rl.stop_refusal(s, os.path.join(self.tmp, "stamps", "s3.json"), 0, "s3"))         # nudge 0: the line only
        self.assertEqual(git(self.main, "status", "--porcelain"), "")             # the repository stays clean

    def run_hook(self, event, home, **more):
        hook = os.path.join(tq.ROOT, "plugins", "front", "hooks", "lanes.py")
        data = dict({"hook_event_name": event, "cwd": self.main, "session_id": "sess1"}, **more)
        env = dict(os.environ, RELAY_HOME=home, PYTHONPATH="")
        done = subprocess.run([sys.executable, hook], input=json.dumps(data), capture_output=True, text=True, env=env)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return done.stdout

    def test_stop_hook_script(self):
        self.seed({Q + "a.json": item("a")})
        home = os.path.join(self.tmp, "home")
        out = json.loads(self.run_hook("Stop", home))
        self.assertEqual(out["decision"], "block")
        self.assertIn("start: a (fix, ip 90)", out["reason"])
        self.assertEqual(self.run_hook("Stop", home), "")                                   # once per state
        self.assertEqual(self.run_hook("Stop", os.path.join(self.tmp, "home2"), stop_hook_active=True), "")
        self.assertEqual(self.run_hook("Stop", os.path.join(self.tmp, "home3"), agent_id="x"), "")
        self.assertTrue(os.path.isfile(os.path.join(home, "state", "lanes-stop", "sess1.json")))
        self.assertFalse(os.path.exists(os.path.join(self.main, "state")))

    def test_prompt_hook_prints_the_line_and_is_silent_when_full(self):
        self.seed({Q + "a.json": item("a")})
        out = json.loads(self.run_hook("UserPromptSubmit", os.path.join(self.tmp, "h")))
        self.assertIn("start: a (fix, ip 90)", out["hookSpecificOutput"]["additionalContext"])
        with open(os.path.join(self.main, "CLAUDE.local.md"), "w") as handle:
            handle.write("Changes built at once: 1.\n")
        self.worktree("busy")
        self.assertEqual(self.run_hook("UserPromptSubmit", os.path.join(self.tmp, "h")), "")


class Landing(LaneBase):
    def test_feature_closed_at_landing_fix_untouched_dropped_stays(self):
        self.seed({Q + "feat.json": item("feat", "feature", **taken("wt/feat")), Q + "fx.json": item("fx", **taken("wt/fx")),
                   Q + "rider.json": item("rider", "feature", **taken("wt/rider")), Q + "drop.json": item("drop", "feature", **taken("wt/drop"))})
        feat = self.branch_with_commit("feat", {"lib/feat.py": "x\n"}, "the change")
        self.write_commit(feat, {".relay/checks/c.check.json": "{}\n"}, "relay: check of abc")          # the tip is an inert check commit
        real = git(feat, "rev-parse", "HEAD~1")
        self.branch_with_commit("fx", {"lib/fx.py": "x\n"})
        self.branch_with_commit("rider", {"lib/rider.py": "x\n"})
        git(self.main, "merge", "-q", "--ff-only", "wt/feat")
        git(self.main, "merge", "-q", "--no-ff", "-m", "Merge wt/fx", "wt/fx")
        git(self.main, "merge", "-q", "--no-ff", "-m", "Merge wt/rider into train-1", "wt/rider")
        merge = git(self.main, "rev-parse", "HEAD")
        git(self.main, "worktree", "remove", "--force", os.path.join(self.tmp, "rider"))
        git(self.main, "branch", "-D", "wt/rider")
        lines = rl.close_landed(self.main)
        self.assertEqual(len(lines), 2, lines)
        self.assertEqual(self.item("feat")["evidence"], real)        # the newest non-inert commit, not the check tip
        self.assertEqual(self.item("rider")["evidence"], merge)      # a rider: its merge commit
        self.assertEqual(self.item("fx")["state"], "taken")          # a fix is closed by the cycle's --test, not here
        self.assertEqual(self.item("drop")["state"], "taken")        # a branch that never landed
        self.assertEqual(rl.close_landed(self.main), [])             # the second pass finds nothing more to close

    def test_landing_hook_closes_and_names_the_line(self):
        self.seed({Q + "feat.json": item("feat", "feature", **taken("wt/feat")), Q + "next.json": item("next", where=("lib/n.py",))})
        self.branch_with_commit("feat", {"lib/feat.py": "x\n"})
        git(self.main, "merge", "-q", "--ff-only", "wt/feat")
        hook = os.path.join(tq.ROOT, "plugins", "front", "hooks", "lanes.py")
        data = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": self.main, "tool_input": {"command": "git -C /x merge --ff-only wt/feat"}}
        done = subprocess.run([sys.executable, hook], input=json.dumps(data), capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=""))
        text = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("closed feat", text)
        self.assertIn("start: next (fix, ip 90)", text)
        self.assertEqual(self.item("feat")["state"], "done")
        other = dict(data, tool_input={"command": "ls wt/feat"})                     # not a landing: nothing
        done = subprocess.run([sys.executable, hook], input=json.dumps(other), capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=""))
        self.assertEqual(done.stdout, "")


class Start(LaneBase):
    def test_start_takes_the_item_writes_the_brief_and_prints_the_unit(self):
        self.seed({Q + "fx.json": item("fx", where=("lib/relay_zeta.py",)), Q + "ft.json": item("ft", "feature", ip=99), "tests/test_zeta.py": "x\n"})
        scratch = os.path.join(self.tmp, "scratch")
        out = json.loads(rl.start(self.main, "fx", scratch))
        wt = os.path.join(self.main, ".worktrees", "fx")
        self.assertEqual((out["branch"], out["worktree"], out["mode"]), ("wt/fx", wt, "start"))
        unit = out["cycle_args"]["items"][0]
        self.assertEqual((unit["kind"], unit["item"], unit["branch"], unit["wt"]), ("change", "fx", "wt/fx", wt))
        self.assertEqual(unit["check"], f"pytest -q -x {wt}/tests/test_zeta.py")        # the test file named like the item's where file
        self.assertEqual(self.item("fx")["taken_by"], "wt/fx")                                 # taken on master
        brief = open(out["brief"]).read()
        self.assertIn("Queue item (fix, ip 90): `fx`", brief)
        self.assertIn("lib/relay_zeta.py", brief)
        # a feature starts as a design: the brief carries the item in full, the unit is a design
        design = json.loads(rl.start(self.main, "ft", scratch))
        self.assertEqual(design["mode"], "design")
        self.assertEqual(design["cycle_args"]["designs"][0]["out"], os.path.join(scratch, "reports", "design-ft.md"))
        self.assertIn("Title of ft", open(design["brief"]).read())

    def test_start_refused_without_a_free_lane_or_an_open_item_and_leaves_nothing(self):
        self.seed({Q + "a.json": item("a"), Q + "b.json": item("b", where=("lib/b.py",)), Q + "t.json": item("t", **taken("wt/t"))})
        self.worktree("t")
        scratch = os.path.join(self.tmp, "scratch")
        with mock.patch.object(rl, "lanes_setting", return_value=1):
            with self.assertRaises(rq.Refused) as ctx:
                rl.start(self.main, "a", scratch)
        self.assertIn("no free lane: 1 of 1 running", str(ctx.exception))
        with self.assertRaises(rq.Refused):
            rl.start(self.main, "t", scratch)                                      # already taken
        self.assertFalse(os.path.exists(os.path.join(self.main, ".worktrees", "a")))
        self.assertEqual(git(self.main, "branch", "--list", "wt/a"), "")

    def test_start_removes_the_worktree_when_the_take_fails(self):
        self.seed({Q + "a.json": item("a")})
        with mock.patch.object(rq, "take", side_effect=rq.Refused("boom")):
            with self.assertRaises(rq.Refused):
                rl.start(self.main, "a", os.path.join(self.tmp, "scratch"))
        self.assertFalse(os.path.exists(os.path.join(self.main, ".worktrees", "a")))
        self.assertEqual(git(self.main, "branch", "--list", "wt/a"), "")

    def test_start_command_through_bin_relay(self):
        self.seed({Q + "a.json": item("a")})
        scratch = os.path.join(self.tmp, "scratch")
        done = subprocess.run([sys.executable, os.path.join(tq.ROOT, "bin", "relay"), "queue", "start", "a", "--scratch", scratch, "-C", self.main],
                              capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=tq.ROOT))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["started"], "a")


if __name__ == "__main__":
    unittest.main()


class Review(LaneBase):
    """Fixes of the review of the first build (F1-F5, F7)."""

    def test_f1_a_branch_holding_two_items_is_one_lane(self):
        # a (feature) and b (fix) are both taken by wt/a: one branch is one lane. Limit 2, c open: running 1, free 1, picks [c].
        self.seed({Q + "a.json": item("a", "feature", **taken("wt/a")), Q + "b.json": item("b", **taken("wt/a")),
                   Q + "c.json": item("c", where=("lib/c.py",))})
        self.branch_with_commit("a", {"lib/a.py": "x\n"})
        s = self.state(limit=2)
        self.assertEqual([l.branch for l in s.running], ["wt/a"])
        self.assertEqual((s.free, [p.slug for p in s.picks]), (1, ["c"]))
        self.assertTrue(rl.line(s).startswith("Lanes: 1 of 2 running"))
        # two branches: two lanes, free 0
        self.seed({Q + "d.json": item("d", **taken("wt/d"))})
        self.worktree("d")
        self.assertEqual((len(self.state(limit=2).running), self.state(limit=2).free), (2, 0))

    def test_f1_two_items_on_one_landed_branch_both_listed(self):
        self.seed({Q + "a.json": item("a", "feature", **taken("wt/a")), Q + "b.json": item("b", **taken("wt/a"))})
        self.branch_with_commit("a", {"lib/a.py": "x\n"})
        git(self.main, "merge", "-q", "--ff-only", "wt/a")
        s = self.state(limit=2)
        self.assertEqual((sorted(x.slug for x in s.landed_open), s.running), (["a", "b"], []))

    def take_master_then_land(self, delete):
        self.seed({Q + "feat.json": item("feat", "feature", **taken("wt/feat"))})
        feat = self.branch_with_commit("feat", {"lib/feat.py": "x\n"}, "own")
        own = git(feat, "rev-parse", "HEAD")
        with mock.patch.dict(os.environ, {"GIT_COMMITTER_DATE": "2030-01-01T00:00:00Z"}):       # the newest commit by date
            self.write_commit(self.main, {"lib/other.py": "y\n"}, "another change")
        git(feat, "merge", "-q", "--no-ff", "-m", "Merge master into wt/feat", "master")
        git(self.main, "merge", "-q", "--ff-only", "wt/feat")
        if delete:
            git(self.main, "worktree", "remove", "--force", feat)
            git(self.main, "branch", "-d", "wt/feat")
        return own

    def test_f2_evidence_is_the_branchs_own_commit_after_taking_master(self):
        # own commit A, master gets Y, the branch merges master (M), fast-forward landing: evidence is A, not Y or M
        own = self.take_master_then_land(delete=False)
        rl.close_landed(self.main)
        self.assertEqual(self.item("feat")["evidence"], own)

    def test_f2_f3_ref_gone_after_a_fast_forward_and_a_master_merge(self):
        own = self.take_master_then_land(delete=True)
        rl.close_landed(self.main)
        self.assertEqual(self.item("feat")["state"], "done")
        self.assertEqual(self.item("feat")["evidence"], own)

    def test_f3_fast_forward_landing_ref_gone_without_a_master_merge(self):
        self.seed({Q + "feat.json": item("feat", "feature", **taken("wt/feat"))})
        feat = self.branch_with_commit("feat", {"lib/feat.py": "x\n"})
        own = git(feat, "rev-parse", "HEAD")
        git(self.main, "merge", "-q", "--ff-only", "wt/feat")
        git(self.main, "worktree", "remove", "--force", feat)
        git(self.main, "branch", "-d", "wt/feat")
        rl.close_landed(self.main)
        self.assertEqual((self.item("feat")["state"], self.item("feat")["evidence"]), ("done", own))

    def test_f2_merge_into_the_branch_is_not_its_landing(self):
        # "Merge master into wt/x" and "Merge branch 'master' into wt/x" name wt/x but do not land it (its ref is gone)
        self.seed({Q + "x.json": item("x", "feature", **taken("wt/x"))})
        for n, message in enumerate(("Merge master into wt/x", "Merge branch 'master' into wt/x")):
            git(self.main, "checkout", "-q", "-b", f"tmp{n}")
            self.write_commit(self.main, {f"lib/t{n}.py": "t\n"}, "t")
            git(self.main, "checkout", "-q", "master")
            self.write_commit(self.main, {f"lib/u{n}.py": "u\n"}, "u")
            git(self.main, "merge", "-q", "--no-ff", "-m", message, f"tmp{n}")
            git(self.main, "branch", "-q", "-D", f"tmp{n}")
            self.assertEqual(rl.landing(self.main, "master", "wt/x", None), (False, None), message)

    def test_f4_a_new_worktree_from_an_old_commit_is_running_at_its_creation(self):
        import time
        env = dict(os.environ, GIT_COMMITTER_DATE="2026-10-01T00:00:00Z", GIT_AUTHOR_DATE="2026-10-01T00:00:00Z")
        with mock.patch.dict(os.environ, env):
            self.seed({"lib/old.py": "x\n"})                 # a head commit dated 27 days before the real clock
        self.worktree("y")
        now = time.time()
        self.assertEqual([l.branch for l in rl.lanes_state(self.main, now=now, limit=6).running], ["wt/y"])
        later = rl.lanes_state(self.main, now=now + 4 * 3600, limit=6)       # 4 h > the 3 h setting
        self.assertEqual(later.running, [])
        self.assertIn("wt/y (quiet)", later.quiet)

    def test_f5_design_in_a_path_is_not_the_design_mode(self):
        fx = rq.parse("f", item("f", where=("docs/design.md:127-129",)))
        self.assertEqual(rl.mode_of(fx), "start")
        self.assertEqual(rl.mode_of(rq.parse("g", item("g", where=("lib/x.py redo the design",)))), "design")
        self.assertEqual(rl.mode_of(rq.parse("h", item("h", "feature", where=("lib/x.py",)))), "design")

    def test_f7_merge_base_is_not_a_landing(self):
        self.seed({})
        hook = os.path.join(tq.ROOT, "plugins", "front", "hooks", "lanes.py")
        sys.path.insert(0, os.path.dirname(hook))
        try:
            import importlib
            lanes_hook = importlib.import_module("lanes")
        finally:
            sys.path.pop(0)
        self.assertIsNone(lanes_hook.LANDING.search("git merge-base --is-ancestor wt/x master"))
        self.assertIsNotNone(lanes_hook.LANDING.search("git merge --ff-only wt/feat"))
        self.assertIsNone(lanes_hook.LANDING.search("ls wt/feat"))
