"""The queue has no done/ folder: a close or a drop edits the item file in place, and the state is read from its dated fields.
Scratch repositories in a temp dir."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_queue as tq  # noqa: E402
from relay_testbase import load_hook as _load_hook  # noqa: E402

rq = tq.rq
git = tq.git
QUEUE = ".relay/queue/"


def closed(slug_title="Job"):
    """A fix item taken by wt/a and closed, as `relay queue done` leaves it."""
    return tq.with_fields(tq.fix_item(slug_title), **tq.taken_fields("wt/a"), closed_at=tq.CLOSED_AT, test="tests/t.py::test_job")


def taken():
    return tq.with_fields(tq.fix_item("Job"), **tq.taken_fields("wt/a"))


class ClosedOn(tq.Base):
    """`closed_on(main, base, tip, slug)`: closed_at empty at the branch's base and set at its tip (worked out by hand per case)."""

    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {QUEUE + "job.json": taken()}, "job is taken")
        self.base = git(self.main, "rev-parse", "HEAD")

    def tip(self, text, files=None):
        git(self.main, "checkout", "-q", "-b", "side", self.base)
        self.write_commit(self.main, {QUEUE + "job.json": text, **(files or {})}, "side")
        tip = git(self.main, "rev-parse", "HEAD")
        git(self.main, "checkout", "-q", "master")
        return tip

    def test_a_close_in_place_is_a_close_on_the_branch(self):
        # taken (no closed_at) at the base, closed_at set at the tip: closed on the branch
        self.assertTrue(rq.closed_on(self.main, self.base, self.tip(closed()), "job"))

    def test_an_item_not_closed_at_the_tip_is_not(self):
        self.assertFalse(rq.closed_on(self.main, self.base, self.tip(taken(), {"x.txt": "x\n"}), "job"))

    def test_an_item_already_closed_at_the_base_is_not_this_branchs(self):
        # an older branch closed it: closed_at is set at the base too, so the branch that only touches the file did not close it
        self.write_commit(self.main, {QUEUE + "job.json": closed()}, "an older branch closed it")
        base = git(self.main, "rev-parse", "HEAD")
        git(self.main, "checkout", "-q", "-b", "side", base)
        self.write_commit(self.main, {"x.txt": "x\n"}, "side")
        self.assertFalse(rq.closed_on(self.main, base, git(self.main, "rev-parse", "HEAD"), "job"))

    def test_an_item_absent_at_the_base_and_closed_at_the_tip_is_a_close(self):
        # the file did not exist at the base: no closed_at there
        git(self.main, "checkout", "-q", "-b", "side", self.base)
        self.write_commit(self.main, {QUEUE + "other.json": closed("Other")}, "side")
        self.assertTrue(rq.closed_on(self.main, self.base, git(self.main, "rev-parse", "HEAD"), "other"))

    def test_closing_tip_is_the_rider_whose_range_closes_the_item(self):
        # rider a closes job; rider b changes another file: only a's tip closes it; no rider closes "none"
        tip_a = self.tip(closed())
        git(self.main, "checkout", "-q", "-b", "other", self.base)
        self.write_commit(self.main, {"y.txt": "y\n"}, "b")
        tip_b = git(self.main, "rev-parse", "HEAD")
        git(self.main, "checkout", "-q", "master")
        riders = {"wt/a": tip_a, "wt/b": tip_b}
        self.assertEqual(rq.closing_tip(self.main, "master", riders, "job"), tip_a)
        self.assertIsNone(rq.closing_tip(self.main, "master", riders, "none"))


class InPlace(tq.Base):
    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {QUEUE + "feat.json": tq.feature_item("Feat", ip=20), QUEUE + "gone.json": tq.feature_item("Gone", ip=10),
                                      QUEUE + "old.json": closed("Old")}, "seed")
        self.wa = self.worktree("a")

    def test_a_close_and_a_drop_each_change_the_one_item_file(self):
        rq.close_with_evidence(self.main, "feat", "19c02df", **tq.QUIET)
        rq.drop(self.main, "gone", "not wanted", **tq.QUIET)
        # worked out: each landing is one commit that touches only its own file, and no done/ folder appears
        for slug in ("feat", "gone"):
            self.assertEqual(git(self.main, "log", "-1", "--format=", "--name-only", "--grep=queue: " + slug), QUEUE + slug + ".json")
        self.assertEqual(git(self.main, "ls-tree", "-r", "--name-only", "master", "--", QUEUE + "done/"), "")

    def test_the_lander_refuses_a_kept_change_that_still_moves_to_done(self):
        # a wt/queue-feat branch made by the old code deletes feat.json and adds done/feat.json: two paths, refused
        base = git(self.main, "rev-parse", "master")
        git(self.main, "checkout", "-q", "-b", "wt/queue-feat", base)
        git(self.main, "rm", "-q", QUEUE + "feat.json")
        self.write_commit(self.main, {QUEUE + "done/feat.json": tq.feature_item("Feat")}, "queue: feat")
        git(self.main, "checkout", "-q", "master")
        with self.assertRaises(rq.Refused) as ctx:
            rq.land(self.main, "feat", **tq.QUIET)
        self.assertIn("changes more than the item", str(ctx.exception))

    def test_take_drop_ip_and_release_refuse_a_closed_item_by_its_state(self):
        head = git(self.main, "rev-parse", "master")
        for name, call in (("take", lambda: rq.take(self.wa, "old", **tq.QUIET)), ("drop", lambda: rq.drop(self.main, "old", "x", **tq.QUIET)),
                           ("ip", lambda: rq.set_ip(self.main, "old", 5, **tq.QUIET)), ("release", lambda: rq.release(self.main, "old", **tq.QUIET))):
            with self.assertRaises(rq.Refused, msg=name) as ctx:
                call()
            self.assertIn("queue item 'old' is done (closed 2026-10-03)", str(ctx.exception), name)
        self.assertEqual(git(self.main, "rev-parse", "master"), head)

    def test_the_list_has_open_and_taken_items_and_the_closed_ones_only_when_asked(self):
        rq.drop(self.main, "gone", "not wanted", **tq.QUIET)
        rq.take(self.wa, "feat", **tq.QUIET)
        # worked out: feat is taken, gone is dropped, old is done
        self.assertEqual(sorted((i["slug"], i["state"]) for i in rq.read_queue(self.main)), [("feat", "taken")])
        self.assertEqual(sorted((i["slug"], i["state"]) for i in rq.read_queue(self.main, closed=True)),
                         [("feat", "taken"), ("gone", "dropped"), ("old", "done")])

    def test_a_closed_slug_is_never_reused(self):
        rq.add(self.main, "feature", "Old", why="w", minutes=5, **tq.QUIET)       # the title's slug is "old", a closed item's name
        self.assertIsNotNone(self.item("old-2"))

    def test_show_finds_a_closed_and_a_dropped_item(self):
        rq.drop(self.main, "gone", "not wanted", **tq.QUIET)
        for slug in ("old", "gone"):
            done = subprocess.run([sys.executable, os.path.join(tq.ROOT, "bin", "relay"), "queue", "show", slug, "-C", self.main],
                                  capture_output=True, text=True, env=dict(os.environ, RELAY_ROOT=tq.ROOT))
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_check_needs_no_folder_for_a_state_and_reports_a_file_left_in_done(self):
        # a closed and a dropped item in the one folder are well formed
        rq.drop(self.main, "gone", "not wanted", **tq.QUIET)
        self.assertEqual(rq.check_files(self.main), [])
        os.makedirs(os.path.join(self.main, QUEUE, "done"))
        with open(os.path.join(self.main, QUEUE, "done", "late.json"), "w") as handle:
            handle.write(closed("Late"))
        self.assertEqual([path for path, _ in rq.check_files(self.main)], [QUEUE + "done/late.json"])

    def test_q1_since_is_the_commit_that_took_the_item_not_the_one_that_closed_it(self):
        rq.take(self.wa, "feat", **tq.QUIET)
        self.write_commit(self.main, {QUEUE + "job.json": tq.fix_item("Job", ip=60)}, "a fix")
        rq.take(self.wa, "job", **tq.QUIET)
        took = git(self.main, "rev-parse", "master")
        # the branch closes job in place: the file changes again, but Q1 is stated at the take
        self.write_commit(self.wa, {QUEUE + "job.json": closed()}, "close")
        slug, q1 = rq.record_item(self.wa)
        self.assertEqual((slug, q1["since"]), ("job", took))


class MoveBack(tq.Base):
    def test_the_move_back_is_renames_only_and_keeps_each_files_history(self):
        # three commits on a.json (added, changed, moved to done/ with a change), then the move back as its own commit
        path = os.path.join(self.main, QUEUE)
        self.write_commit(self.main, {QUEUE + "a.json": tq.feature_item("Aaa")}, "added")
        self.write_commit(self.main, {QUEUE + "a.json": tq.with_fields(tq.feature_item("Aaa"), ip=7)}, "changed")
        os.makedirs(os.path.join(path, "done"))
        git(self.main, "mv", QUEUE + "a.json", QUEUE + "done/a.json")
        self.write_commit(self.main, {QUEUE + "done/a.json": tq.with_fields(tq.feature_item("Aaa"), ip=7, closed_at=tq.CLOSED_AT, taken_at=tq.TAKEN_AT,
                                                                           taken_by="wt/z", evidence="abc1234")}, "closed")
        import relay_queue_migrate
        self.assertEqual(relay_queue_migrate.move_done_back(self.main), [QUEUE + "a.json"])
        git(self.main, "commit", "-q", "-m", "move back")
        status = git(self.main, "diff", "-M", "--name-status", "HEAD~1", "HEAD")
        self.assertEqual(status, f"R100\t{QUEUE}done/a.json\t{QUEUE}a.json")
        # --follow: the file was added, changed, then closed in done/ ("start" does not touch it), so 3 commits before the move plus the move
        log = git(self.main, "log", "--follow", "--format=%s", "--", QUEUE + "a.json").split("\n")
        self.assertEqual(log, ["move back", "closed", "changed", "added"])

    def test_the_move_back_refuses_a_name_that_exists_in_both_places_and_moves_nothing(self):
        # a.json is free to move, b.json exists in both places: the whole move is refused before a.json goes
        self.write_commit(self.main, {QUEUE + "b.json": tq.feature_item("Bbb"), QUEUE + "done/a.json": closed("Aaa"), QUEUE + "done/b.json": closed("Bbb")}, "both")
        import relay_queue_migrate
        with self.assertRaises(relay_queue_migrate.rq.Refused):      # the module's own class: a full run can hold another copy of relay_queue
            relay_queue_migrate.move_done_back(self.main)
        self.assertTrue(os.path.exists(os.path.join(self.main, QUEUE, "done", "a.json")))
        self.assertFalse(os.path.exists(os.path.join(self.main, QUEUE, "a.json")))


OLD_RUNNER = (       # the default branch's hook before this change: it passes (slug, text, folder) to parse
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import relay_queue\n"
    "rows = json.load(sys.stdin)\n"
    "json.dump([relay_queue.parse(slug, text, where) for slug, text, where in rows], sys.stdout)\n"
)


_HOOK = []


def hook():
    """The merge hook module, loaded once (its Refused class must be the one the tests catch)."""
    if _HOOK:
        return _HOOK[0]
    module = _load_hook("merge_hook_in_place", os.path.join(tq.ROOT, "plugins", "core", "hooks", "merge.py"))
    _HOOK.append(module)
    return module


def taken_y():
    return tq.with_fields(tq.fix_item("Y"), **tq.taken_fields("wt/close"))


class TheMoveBranch(tq.Base):
    """A branch whose range moves closed items out of done/ closes nothing; step_queue judges only the items the range changed."""

    def setUp(self):
        super().setUp()
        self.write_commit(self.main, {QUEUE + "done/x.json": closed("X")}, "x closed at the base, under done/")
        self.base = git(self.main, "rev-parse", "HEAD")

    def move_branch(self):
        git(self.main, "checkout", "-q", "-b", "wt/move", self.base)
        git(self.main, "mv", QUEUE + "done/x.json", QUEUE + "x.json")
        git(self.main, "commit", "-q", "-m", "move")
        git(self.main, "checkout", "-q", "master")

    def test_moving_a_closed_item_out_of_done_is_not_a_close_and_is_not_refused(self):
        # worked out: x is closed at the base (under done/) and at the tip (moved): the branch closed nothing
        self.move_branch()
        self.assertFalse(rq.closed_on(self.main, self.base, "wt/move", "x"))
        hook().step_queue(self.main, "master", "wt/move")       # does not raise

    def moved_on_master(self):
        git(self.main, "mv", QUEUE + "done/x.json", QUEUE + "x.json")       # done/ is gone on the default branch, as after the migrate
        git(self.main, "commit", "-q", "-m", "move")

    def test_a_close_in_place_without_a_test_is_still_refused(self):
        self.moved_on_master()
        self.write_commit(self.main, {QUEUE + "y.json": taken_y()}, "y taken")
        git(self.main, "checkout", "-q", "-b", "wt/close")
        self.write_commit(self.main, {QUEUE + "y.json": tq.with_fields(tq.fix_item("Y"), **tq.taken_fields("wt/close"), closed_at=tq.CLOSED_AT,
                                                                       test="tests/none.py::test_none")}, "close y")
        git(self.main, "checkout", "-q", "master")
        with self.assertRaises(hook().Refused) as ctx:
            hook().step_queue(self.main, "master", "wt/close")
        self.assertIn("closed without a test or a check", str(ctx.exception))

    def test_a_new_item_added_already_closed_is_refused(self):
        self.moved_on_master()
        git(self.main, "checkout", "-q", "-b", "wt/new")
        self.write_commit(self.main, {QUEUE + "z.json": closed("Z")}, "z added closed")
        git(self.main, "checkout", "-q", "master")
        with self.assertRaises(hook().Refused) as ctx:
            hook().step_queue(self.main, "master", "wt/new")
        self.assertIn("closed without a test or a check", str(ctx.exception))

    def test_held_fix_items_does_not_list_a_renamed_item(self):
        git(self.main, "checkout", "-q", "-b", "wt/move", self.base)
        git(self.main, "mv", QUEUE + "done/x.json", QUEUE + "x.json")
        git(self.main, "commit", "-q", "-m", "move")
        # worked out: the move closes nothing, so the branch holds no fix item
        self.assertEqual(rq.held_fix_items(self.main, riders=True), {})

    def test_step_queue_asks_closed_on_only_for_the_items_the_range_changed(self):
        self.move_branch()
        git(self.main, "merge", "-q", "wt/move")
        git(self.main, "checkout", "-q", "-b", "wt/other")
        self.write_commit(self.main, {"a.txt": "a\n"}, "unrelated")
        git(self.main, "checkout", "-q", "master")
        # worked out: wt/other changed only a.txt; x (closed, in the tip) is not in its range, so closed_on is never called
        with mock.patch.object(rq, "closed_on", side_effect=AssertionError("called")) as spy:
            hook().step_queue(self.main, "master", "wt/other")
        spy.assert_not_called()


class OldHookNewLib(unittest.TestCase):
    """The default branch's hook runs the branch's lib with three-element rows."""

    def run_runner(self, runner, rows):
        lib = os.path.join(tq.ROOT, "lib")
        done = subprocess.run([sys.executable, "-I", "-c", runner, lib], input=json.dumps(rows), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_old_runner_with_three_element_rows_parses_open_and_done(self):
        text = tq.feature_item("Feat")
        for folder in ("open", "done"):
            out = self.run_runner(OLD_RUNNER, [["x", text, folder]])
            self.assertEqual(out[0]["problems"], [], folder)       # no folder rule any more

    def test_the_new_runner_with_two_element_rows_works(self):
        out = self.run_runner(hook().RULES_RUNNER, [["x", tq.feature_item("Feat")]])
        self.assertEqual(out[0]["problems"], [])


if __name__ == "__main__":
    unittest.main()
