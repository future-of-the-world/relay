"""Lanes derived from git and the queue, the free-lane line, the Stop refusal, the close at landing and `relay queue start`.
Scratch repositories in a temp dir; time is a value passed in (epoch seconds); nothing touches the live queue."""
import json
import os
import subprocess
import sys
import time
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
        s = rl.lanes_state(self.main, now=time.time(), limit=2)     # the train's reflog is real time: "now" is real too
        self.assertEqual([l.branch for l in s.running], ["wt/train-1"])
        self.assertEqual(s.free, 1)

    def test_rider_not_yet_in_the_train_is_its_own_lane(self):
        # c has own commits and is in no train: it counts besides the train. Setting 2: 2 of 2, nothing free.
        self._train()
        self.branch_with_commit("c", {"lib/c.py": "x\n"})
        s = rl.lanes_state(self.main, now=time.time(), limit=2)
        self.assertEqual(sorted(l.branch for l in s.running), ["wt/c", "wt/train-1"])
        self.assertEqual(s.free, 0)

    def test_f1_rider_uncommitted_edit_still_blocks_overlap(self):
        # a's worktree has an uncommitted edit to lib/z.py after a was merged into the train; item z (where lib/z.py) must wait on it.
        a = self._train()
        a = os.path.join(self.tmp, "a")
        with open(os.path.join(a, "lib", "z.py"), "w") as f:
            f.write("edit\n")
        git(self.main, "commit", "--allow-empty", "-q", "-m", "x")
        self.write_commit(self.main, {Q + "z.json": item("z", where=("lib/z.py",))}, "z")
        s = rl.lanes_state(self.main, now=time.time(), limit=3)
        self.assertEqual([w.slug for w in s.waits], ["z"])
        self.assertEqual(s.waits[0].file, "lib/z.py")
        self.assertNotIn("z", [p.slug for p in s.picks])

    def test_f1_committed_rider_file_blocks_while_train_open(self):
        self._train()
        self.write_commit(self.main, {Q + "q.json": item("q", where=("lib/a.py",))}, "q")
        s = rl.lanes_state(self.main, now=time.time(), limit=3)
        self.assertEqual([w.slug for w in s.waits], ["q"])

    def test_f2_dead_train_does_not_fold_riders(self):
        # the train's last activity is older than quiet hours: a and b are 2 lanes (setting 2: 0 free). Pass case: within hours, 1 lane.
        self._train()
        later = time.time() + 5 * 3600
        s = rl.lanes_state(self.main, now=later, quiet_hours=3, limit=2)
        self.assertEqual(sorted(l.branch for l in s.running), ["wt/a", "wt/b"])
        self.assertEqual(s.free, 0)

    def test_f2_train_waiting_110_minutes_is_still_one_lane(self):
        self._train()
        s = rl.lanes_state(self.main, now=time.time() + 110 * 60, quiet_hours=3, limit=2)
        self.assertEqual([l.branch for l in s.running], ["wt/train-1"])

    def test_f2_rider_counts_under_the_live_train_not_the_dead_one(self):
        self._train()
        git(self.main, "branch", "wt/train-0", "wt/train-1")        # a dead twin holding the same riders
        git(self.main, "reflog", "expire", "--expire=all", "refs/heads/wt/train-0")
        s = rl.lanes_state(self.main, now=time.time(), limit=3)
        self.assertEqual([l.branch for l in s.running], ["wt/train-1"])

    def test_f3_one_ref_scan_per_rider_candidate(self):
        # with 10 unrelated wt/* refs the rider scan runs one for-each-ref per lane with own commits, not one ancestry test per ref
        self._train()
        for n in range(10):
            git(self.main, "branch", f"wt/old-{n}", "master")
        calls = []
        real = rl._is_ancestor
        with mock.patch.object(rl, "_is_ancestor", side_effect=lambda *a: calls.append(a) or real(*a)):
            rl.lanes_state(self.main, now=time.time(), limit=3)
        # a, b: held by train-1 only (itself skipped; train-1 is not an ancestor of them): at most 1 ancestry test each, plus landing's own
        self.assertLessEqual(len([c for c in calls if c[1].startswith("refs/heads/wt/a") or c[1].startswith("refs/heads/wt/b")]), 2)

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
        # every pick is named (a pick is a lane to fill); the setting counts only the "next:" names
        self.assertEqual(text, "Lanes: 1 of 4 running; start: f2 (fix, ip 95), start: f1 (fix, ip 80), start: f3 (fix, ip 70); next: ft (feature, ip 99)")

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

    def test_picks_of_one_call_are_checked_against_each_other(self):
        # a and b both name lib/relay_setup.py, no lane running, 2 free lanes: a (ip 95) is picked, b waits naming a; c (other file) is picked
        self.seed({Q + "a.json": item("a", ip=95, where=("lib/relay_setup.py:1-5 x",)), Q + "b.json": item("b", ip=94, where=("lib/relay_setup.py:50-60 y",)),
                   Q + "c.json": item("c", ip=93, where=("lib/other.py",))})
        s = self.state(limit=2)
        self.assertEqual([p.slug for p in s.picks], ["a", "c"])
        self.assertEqual([(w.slug, w.file, w.pick) for w in s.waits], [("b", "lib/relay_setup.py", "a")])
        self.assertIn("waits: b (same file as a: lib/relay_setup.py)", rl.line(s))

    def test_f1_a_taken_item_holds_its_where_files_before_its_branch_changed_any(self):
        # a is taken by wt/a (worktree, no commit); b names the same file: b waits naming a (the second `start` in a row sees the first)
        self.seed({Q + "a.json": item("a", ip=95, where=("lib/relay_setup.py:1-5 x",), **taken("wt/a")),
                   Q + "b.json": item("b", ip=94, where=("lib/relay_setup.py:50-60 y",)), Q + "c.json": item("c", ip=93, where=("lib/y.py",))})
        path = self.worktree("a")
        s = self.state(limit=3)
        self.assertEqual([p.slug for p in s.picks], ["c"])                       # pass case 3: a different file is picked
        self.assertEqual([(w.slug, w.file, w.pick) for w in s.waits], [("b", "lib/relay_setup.py", "a")])
        # once wt/a has landed, b is picked again
        self.write_commit(path, {"lib/relay_setup.py": "1\n"}, "edit")
        git(self.main, "merge", "-q", "--ff-only", "wt/a")
        s = self.state(limit=3)
        self.assertEqual(([p.slug for p in s.picks], s.waits), (["b", "c"], []))

    def test_f1_a_committed_file_still_waits_naming_the_branch(self):
        self.seed({Q + "a.json": item("a", where=("lib/relay_setup.py",), **taken("wt/a")), "lib/relay_setup.py": "0\n",
                   Q + "b.json": item("b", ip=94, where=("lib/relay_setup.py",))})
        self.write_commit(self.worktree("a"), {"lib/relay_setup.py": "1\n"}, "edit")
        s = self.state()
        self.assertEqual([(w.slug, w.file, w.branch, w.pick) for w in s.waits], [("b", "lib/relay_setup.py", "wt/a", None)])

    def test_f3_a_lib_module_and_its_plugin_copy_are_one_file(self):
        self.seed({Q + "a.json": item("a", ip=95, where=("lib/relay_queue.py",)), Q + "b.json": item("b", ip=94, where=("plugins/front/lib/relay_queue.py",)),
                   Q + "c.json": item("c", ip=93, where=("plugins/front/lib/relay_lanes.py",)), Q + "d.json": item("d", ip=92, where=("plugins/front/bin/relay",)),
                   Q + "e.json": item("e", ip=91, where=("bin/relay",))})
        s = self.state(limit=5)
        self.assertEqual([p.slug for p in s.picks], ["a", "c", "d"])             # pass case 2: another module is picked
        self.assertEqual([(w.slug, w.file, w.pick) for w in s.waits], [("b", "lib/relay_queue.py", "a"), ("e", "bin/relay", "d")])

    def test_f3_a_running_branch_that_changed_the_lib_file_holds_its_plugin_copy_name(self):
        self.seed({Q + "r.json": item("r", where=("lib/z.py",), **taken("wt/r")), "lib/relay_queue.py": "0\n",
                   Q + "b.json": item("b", where=("plugins/front/lib/relay_queue.py",))})
        self.write_commit(self.worktree("r"), {"lib/relay_queue.py": "1\n"}, "edit")
        self.assertEqual([(w.slug, w.branch) for w in self.state().waits], [("b", "wt/r")])

    def test_disjoint_picks_both_start_and_a_folder_covers_its_files(self):
        self.seed({Q + "a.json": item("a", ip=95, where=("lib/a.py",)), Q + "b.json": item("b", ip=94, where=("lib/b.py",)),
                   Q + "d.json": item("d", ip=93, where=("lib",))})
        s = self.state(limit=3)
        self.assertEqual(([p.slug for p in s.picks], [w.slug for w in s.waits]), (["a", "b"], ["d"]))

    def test_overlap_ignores_inert_files_and_a_file_the_branch_only_has_from_master(self):
        # the branch carries master's lib/a.py (merged in) but changed nothing: nothing waits
        self.seed({Q + "run.json": item("run", where=("lib/z.py",), **taken("wt/run")), Q + "w.json": item("w", ip=95, where=("lib/a.py",)), "lib/a.py": "0\n"})
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
        self.assertEqual(rl.setting({"front": {"lanes_line_items": 0}}, "lanes_line_items"), 0)
        self.assertEqual(rl.setting({"front": {"lanes_line_items": 10}}, "lanes_line_items"), 10)
        # out of bounds: the default is used, and the note says so
        for bad in (11, -1, "5", True):
            cfg = {"front": {"lanes_line_items": bad}}
            self.assertEqual(rl.setting(cfg, "lanes_line_items"), 3)
            self.assertIn("lanes_line_items", rl.setting_note(cfg, "lanes_line_items") or "")
        self.assertIsNone(rl.setting_note({"front": {"lanes_line_items": 0}}, "lanes_line_items"))
        self.assertIsNone(rl.setting_note({}, "lanes_line_items"))

    def stuck_queue(self):
        # X is first by ip and carries a "not reproduced" fact; Y, Z, W follow; one lane is free
        fact = {"at": "2026-10-29T22:00:00Z", "fact": ["The front could not make this happen."], "reproduced": "no"}
        self.seed({Q + "x.json": item("x", ip=99, where=("lib/x.py",), notes=[fact]), Q + "y.json": item("y", ip=90, where=("lib/y.py",)),
                   Q + "z.json": item("z", ip=80, where=("lib/z.py",)), Q + "w.json": item("w", ip=70, where=("lib/w.py",))})
        return self.state(limit=1)

    def test_not_reproduced_item_is_not_a_pick_and_the_next_items_are_named(self):
        # one free lane: X (not reproduced) is skipped, so Y is the pick; Z and W are the next startable items
        s = self.stuck_queue()
        self.assertEqual(([p.slug for p in s.picks], [p.slug for p in s.upcoming]), (["y"], ["z", "w"]))
        self.assertEqual(rl.line(s), "Lanes: 0 of 1 running; start: y (fix, ip 90); next: z (fix, ip 80), w (fix, ip 70); skipped, not reproduced: x")
        self.assertEqual(rl.line(s, 1), "Lanes: 0 of 1 running; start: y (fix, ip 90); next: z (fix, ip 80); skipped, not reproduced: x")

    def test_line_items_zero_is_the_line_without_next(self):
        self.assertEqual(rl.line(self.stuck_queue(), 0), "Lanes: 0 of 1 running; start: y (fix, ip 90); skipped, not reproduced: x")

    def two_items(self, notes):
        self.seed({Q + "x.json": item("x", ip=99, where=("lib/x.py",), notes=notes), Q + "y.json": item("y", ip=90, where=("lib/y.py",))})
        return self.state(limit=1)

    def test_f1_the_newest_reproduction_fact_decides(self):
        no = {"at": "2026-10-29T10:00:00Z", "fact": ["No longer fails."], "reproduced": "no"}
        yes = {"at": "2026-10-29T12:00:00Z", "fact": ["bin/wt line 5 creates .worktree/."], "reproduced": "yes"}
        s = self.two_items([no, yes])        # the later positive note wins: X is the pick again
        self.assertEqual(([p.slug for p in s.picks], [p.slug for p in s.upcoming]), (["x"], ["y"]))
        self.assertEqual([p.slug for p in self.two_items([no]).picks], ["y"])      # only the negative note: skipped
        self.assertEqual([p.slug for p in self.two_items([yes]).picks], ["x"])     # only the positive note: a pick
        self.assertEqual([p.slug for p in self.two_items([yes, no]).picks], ["y"])    # the negative note is the newest
        self.assertEqual(rl.line(self.two_items([no]), 0), "Lanes: 0 of 1 running; start: y (fix, ip 90); skipped, not reproduced: x")

    def test_f2_prose_about_reproduction_is_no_result_only_the_field_is(self):
        # any wording ("did not reproduce", a Russian note, a quoted review line) without the field leaves X a pick
        for words in ("did not reproduce", "could not reproduce the failure", "не воспроизводится", "Review F2: PLAUSIBLE (traced, not reproduced)"):
            self.assertEqual([p.slug for p in self.two_items([{"at": "2026-10-29T10:00:00Z", "fact": [words]}]).picks], ["x"])

    def test_f2_the_field_is_validated_and_kept_by_the_note_writer(self):
        import datetime
        import relay_queue as rq
        note, why = rq.parse_note({"at": "2026-10-29T10:00:00Z", "fact": ["x"], "reproduced": "no"})
        self.assertEqual((note.reproduced, why, rq.note_dict(note)["reproduced"]), ("no", [], "no"))
        self.assertIn("reproduced is yes or no, on a fact note", rq.parse_note({"at": "2026-10-29T10:00:00Z", "fact": ["x"], "reproduced": "maybe"})[1])
        self.assertIn("reproduced is yes or no, on a fact note", rq.parse_note({"at": "2026-10-29T10:00:00Z", "said": ["x"], "reproduced": "no"})[1])
        self.assertIn("    reproduced: no", rq.notes_text({"notes": [note]}, datetime.timezone.utc))

    def test_f4_setting_note_names_the_cause_and_only_the_key_whose_rule_it_states(self):
        self.assertEqual(rl.setting_note({"front": {"lanes_line_items": "5"}}, "lanes_line_items"),
                         "lanes_line_items 5 is not a whole number: 3 is used")
        self.assertEqual(rl.setting_note({"front": {"lanes_line_items": 11}}, "lanes_line_items"),
                         "lanes_line_items 11 is out of bounds 0-10: 3 is used")
        self.assertIsNone(rl.setting_note({"front": {"stop_nudge": 5}}, "stop_nudge"))     # clamped to 2, not replaced by the default

    def test_next_skips_items_that_wait_or_ask_and_is_empty_when_lanes_are_full(self):
        asked = {"asked_at": "2026-10-09T22:00:00Z", "question": ["**Keep it?**"], "options": ["a. Yes.", "b. No."]}
        self.seed({Q + "run.json": item("run", where=("lib/r.py",), **taken("wt/run")), Q + "a.json": item("a", ip=95, where=("lib/a.py",)),
                   Q + "ask.json": item("ask", ip=94, where=("lib/q.py",), notes=[asked]),
                   Q + "hold.json": item("hold", ip=93, where=("lib/r.py",)), Q + "c.json": item("c", ip=92, where=("lib/c.py",))})
        self.write_commit(self.worktree("run"), {"lib/r.py": "1\n"}, "work")
        # one lane runs and has changed lib/r.py: "hold" waits for it, "ask" has an open question; a (pick) and c are startable
        s = self.state(limit=2)
        self.assertEqual(([p.slug for p in s.picks], [p.slug for p in s.upcoming]), (["a"], ["c"]))
        self.assertEqual(self.state(limit=1).upcoming, [])        # no free lane: nothing starts, nothing is named
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
        # the second reply is one short sentence of facts; it does not repeat the earlier answer
        self.assertIn("one short sentence", first)
        self.assertIn("facts only", first)
        self.assertNotIn("repeat", first)
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

    def test_prompt_hook_names_next_items_and_notes_an_out_of_bounds_setting(self):
        fact = {"at": "2026-10-29T22:00:00Z", "fact": ["Not reproduced."], "reproduced": "no"}
        self.seed({Q + "x.json": item("x", ip=99, where=("lib/x.py",), notes=[fact]), Q + "y.json": item("y", ip=90, where=("lib/y.py",)),
                   Q + "z.json": item("z", ip=80, where=("lib/z.py",))})
        with open(os.path.join(self.main, "CLAUDE.local.md"), "w") as handle:
            handle.write("Changes built at once: 1.\n")
        text = json.loads(self.run_hook("UserPromptSubmit", os.path.join(self.tmp, "h")))["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(text, "Lanes: 0 of 1 running; start: y (fix, ip 90); next: z (fix, ip 80); skipped, not reproduced: x")
        os.makedirs(os.path.join(self.main, ".claude"))
        with open(os.path.join(self.main, ".claude", "kit.toml"), "w") as handle:
            handle.write("[front]\nlanes_line_items = 11\n")
        text = json.loads(self.run_hook("UserPromptSubmit", os.path.join(self.tmp, "h")))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("next: z (fix, ip 80)", text)             # 11 is out of bounds: the default 3 is used
        self.assertIn("lanes_line_items 11 is out of bounds 0-10", text)

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

    def test_start_uses_the_projects_worktrees_folder_from_kit_toml(self):
        # kit.toml says project.worktrees = ".worktree" (ALIX): the worktree is <main>/.worktree/fx, not <main>/.worktrees/fx
        self.seed({Q + "fx.json": item("fx"), ".claude/kit.toml": '[project]\nworktrees = ".worktree"\n'})
        out = json.loads(rl.start(self.main, "fx", os.path.join(self.tmp, "scratch")))
        wt = os.path.join(self.main, ".worktree", "fx")
        self.assertEqual(out["worktree"], wt)
        self.assertTrue(os.path.isdir(wt))
        self.assertFalse(os.path.exists(os.path.join(self.main, ".worktrees")))

    def test_start_worktrees_folder_forms(self):
        # absolute stays absolute (F1); trailing slash and ../ forms (F2 pass cases 2-5)
        outside = os.path.join(self.tmp, "abs-wts")
        for n, (value, expect) in enumerate([
            (outside, os.path.join(outside, "fx")),
            (".worktree/", os.path.join(self.main, ".worktree", "fx")),
            ("", os.path.join(self.main, ".worktrees", "fx")),
            ("../wts-rel", os.path.normpath(os.path.join(self.main, "..", "wts-rel", "fx"))),
        ]):
            with self.subTest(value=value):
                self.seed({Q + "fx.json": item("fx"), ".claude/kit.toml": f'[project]\nworktrees = "{value}"\n'})
                out = json.loads(rl.start(self.main, "fx", os.path.join(self.tmp, f"scratch{n}")))
                self.assertEqual(out["worktree"], expect)
                self.assertFalse(os.path.exists(os.path.join(self.main, outside.lstrip("/"))))
                git(self.main, "worktree", "remove", "--force", expect)
                git(self.main, "branch", "-D", "wt/fx")

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

    def test_f2_f4_start_refuses_an_item_that_waits_and_names_it_and_the_flag_overrides(self):
        # a and b on one file, 2 free: start a; the line now says b waits for a; start b is refused naming a and the flag; with the flag it starts
        self.seed({Q + "a.json": item("a", ip=95, where=("lib/relay_setup.py:1-5",)), Q + "b.json": item("b", ip=94, where=("lib/relay_setup.py:50-60",)),
                   Q + "c.json": item("c", ip=93, where=("lib/c.py",))})
        scratch = os.path.join(self.tmp, "scratch")
        with mock.patch.object(rl, "lanes_setting", return_value=3):
            out = json.loads(rl.start(self.main, "a", scratch))
            self.assertEqual(out["other_waits"], ["b waits for lib/relay_setup.py (same file as a)"])      # no empty "()"
            with self.assertRaises(rq.Refused) as ctx:
                rl.start(self.main, "b", scratch)
            self.assertIn("b waits for lib/relay_setup.py (same file as a)", str(ctx.exception))
            self.assertIn("--despite-wait", str(ctx.exception))
            self.assertFalse(os.path.exists(os.path.join(self.main, ".worktrees", "b")))
            self.assertEqual(json.loads(rl.start(self.main, "c", scratch))["other_waits"], ["b waits for lib/relay_setup.py (same file as a)"])
            self.assertEqual(json.loads(rl.start(self.main, "b", scratch, despite_wait=True))["started"], "b")

    def test_f2_other_waits_names_the_running_branch(self):
        self.seed({Q + "r.json": item("r", where=("lib/z.py",), **taken("wt/r")), "lib/relay_setup.py": "0\n",
                   Q + "b.json": item("b", ip=94, where=("lib/relay_setup.py",)), Q + "c.json": item("c", ip=93, where=("lib/c.py",))})
        self.write_commit(self.worktree("r"), {"lib/relay_setup.py": "1\n"}, "edit")
        out = json.loads(rl.start(self.main, "c", os.path.join(self.tmp, "scratch")))
        self.assertEqual(out["other_waits"], ["b waits for lib/relay_setup.py (wt/r)"])

    def test_f4_flag_through_bin_relay(self):
        self.seed({Q + "a.json": item("a", ip=95), Q + "b.json": item("b", ip=94)})
        scratch = os.path.join(self.tmp, "scratch")
        def run(*extra):
            return subprocess.run([sys.executable, os.path.join(tq.ROOT, "bin", "relay"), "queue", "start", *extra, "--scratch", scratch, "-C", self.main],
                                  capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=tq.ROOT))
        self.assertEqual(run("a").returncode, 0)
        refused = run("b")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--despite-wait", refused.stderr + refused.stdout)
        done = run("b", "--despite-wait")
        self.assertEqual(done.returncode, 0, done.stderr)

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
