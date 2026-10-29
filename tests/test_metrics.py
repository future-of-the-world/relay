"""Change records (lib/relay_metrics.py), the label grammar, the routing guard's label rule, the ledger hook's label and the coverage
line of the gate. Every test builds a temporary repository or folder; nothing touches the live .relay/ or ~/.relay."""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

from test_gate import Fixture, git, write  # noqa: E402

import relay_config  # noqa: E402
import relay_coverage  # noqa: E402
import relay_queue  # noqa: E402
import relay_labels  # noqa: E402
import relay_land  # noqa: E402
import relay_metrics  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def agent(aid, unit, stage="build", start="2026-10-29T10:00:00Z", stop="2026-10-29T10:10:00Z", cost=1.0):
    return {"id": aid, "session": "s", "stage": stage, "n": 1, "model": "m", "start": start, "stop": stop, "requests": 3, "cost_usd": cost, "unit": unit}


class Parser(unittest.TestCase):
    def test_refuses_a_stored_duration(self):
        # principle 3: stage times are computed, never stored, so a record with `duration` is refused
        rec = {"schema": 1, "kind": "change", "unit": "a", "agents": [], "land": []}
        relay_metrics.parse(json.dumps(rec))
        with self.assertRaisesRegex(ValueError, "duration"):
            relay_metrics.parse(json.dumps({**rec, "duration": 5}))
        with self.assertRaisesRegex(ValueError, "gates"):
            relay_metrics.parse(json.dumps({**rec, "land": [{"kind": "done", "gates": 1}]}))


class Labels(unittest.TestCase):
    def test_free_words_are_dropped_and_two_stage_words_exist(self):
        self.assertEqual(relay_labels.label_of("other: docker-deps - short words for me"), "other: docker-deps")
        self.assertEqual(relay_labels.label_of("land: some-item"), "land: some-item")
        self.assertIsNone(relay_labels.label_of("look at the queue"))

    def test_f4_the_delegate_skill_states_the_label_form_with_an_example_that_matches_the_grammar(self):
        text = open(os.path.join(ROOT, "plugins", "delegate", "skills", "delegate", "SKILL.md"), encoding="utf-8").read()
        self.assertIn("`<stage>[ n]: <item id>`", text)
        self.assertIn("`land: <item id>`", text)
        self.assertIn("`other: <name>`", text)
        example = "other: docker-deps"
        self.assertIn(f"`{example} - read the lockfile`", text)
        self.assertEqual(relay_labels.label_of(example + " - read the lockfile"), example)

    def test_window_matching_old_forty_char_labels(self):
        # the 40-char slug is shared by items A and A-2; each owns the agents that started inside its own taken..closed window
        a, b = "refuse-folder-and-pattern-entries-in-where", "refuse-folder-and-pattern-entries-in-where-2"
        items = [{"slug": a, "taken_at": "2026-10-28T00:00:00Z", "closed_at": "2026-10-28T12:00:00Z"},
                 {"slug": b, "taken_at": "2026-10-28T10:00:00Z", "closed_at": "2026-10-29T00:00:00Z"}]
        notes = []
        unit = a[:40]
        self.assertEqual(relay_metrics.match_unit(agent("1", unit, start="2026-10-28T05:00:00Z"), items, notes), a)
        self.assertEqual(relay_metrics.match_unit(agent("2", unit, start="2026-10-28T20:00:00Z"), items, notes), b)
        self.assertEqual(notes, [])
        # inside both windows (10:00-12:00): neither, and one line naming the agent
        self.assertIsNone(relay_metrics.match_unit(agent("3", unit, start="2026-10-28T11:00:00Z"), items, notes), notes)
        self.assertEqual(len(notes), 1)
        self.assertIn("3", notes[0])
        # a full item id matches exactly, whatever the window
        self.assertEqual(relay_metrics.match_unit(agent("4", b, start="2026-10-28T11:00:00Z"), items, notes), b)


class Guard(unittest.TestCase):
    def setUp(self):
        self.guard = load("plugins/delegate/hooks/route-guard.py", "route_guard_metrics")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        patcher = mock.patch.object(self.guard, "running_now", return_value=0)
        patcher.start()
        self.addCleanup(patcher.stop)
        mock.patch.object(self.guard, "skill_evidence", return_value=(True, False)).start()
        self.addCleanup(mock.patch.stopall)

    def call(self, description):
        return self.guard.decide({"tool_name": "Agent", "cwd": self.tmp, "tool_input": {"subagent_type": "delegate:worker", "description": description, "prompt": "Brief: x"}})

    def test_unlabelled_hand_agent_is_refused_only_where_relay_is(self):
        self.assertIsNone(self.call("do a thing"))                      # no .relay/: the guard does not act
        os.mkdir(os.path.join(self.tmp, ".relay"))
        denied = self.call("do a thing")
        self.assertIn("deny", json.dumps(denied))
        self.assertIn("other: <name>", json.dumps(denied))
        self.assertIsNone(self.call("other: docker-deps - words for the person"))
        write(os.path.join(self.tmp, ".claude", "kit.toml"), "[metrics]\nenabled = false\n")
        self.assertIsNone(self.call("do a thing"))                      # metrics off: no guard


class Ledger(unittest.TestCase):
    def test_the_hook_keeps_the_label_and_never_the_free_words(self):
        ledger = load("plugins/observe/hooks/ledger.py", "ledger_metrics")
        with tempfile.TemporaryDirectory() as tmp:
            transcript = os.path.join(tmp, "agent-a1.jsonl")
            write(transcript[:-len(".jsonl")] + ".meta.json", json.dumps({"description": "other: docker-deps - secret words"}))
            self.assertEqual(ledger.hand_fields(transcript), {"label": "other: docker-deps"})
            write(transcript[:-len(".jsonl")] + ".meta.json", json.dumps({"description": "free text only"}))
            self.assertEqual(ledger.hand_fields(transcript), {})


class Records(Fixture):
    def mark(self, wt):
        """a check mark with open 0 for the head of `wt`, as `relay: check of` commits make them"""
        sha = git(wt, "rev-parse", "HEAD")
        data = {"schema": 2, "commit": sha, "check": sha + ".check.json", "verdict": {"open": 0, "queued": 0}}
        write(os.path.join(wt, ".relay", "checks", sha + ".json"), json.dumps(data))
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "relay: check of " + sha)

    def setUp(self):
        super().setUp()
        self.repo(gate="exit 0\n")
        self.mark(self.wt)
        self.ledger = os.path.join(self.tmp, "ledger")
        os.makedirs(self.ledger)
        rows = []
        for aid, unit in (("a1", "item-a"), ("b1", "item-b"), ("c1", "item-c")):
            rows.append({"ts": "2026-10-29T10:10:00.000Z", "event": "agent_stop", "agent_id": aid, "session_id": "s", "label": "build: " + unit,
                         "model": "m", "requests": 2, "cost_est": 0.5})
        write(os.path.join(self.ledger, "2026-10-29.jsonl"), "\n".join(json.dumps(r) for r in rows) + "\n")
        patcher = mock.patch("relay_config.ledger_dir", return_value=self.ledger)
        patcher.start()
        self.addCleanup(patcher.stop)
        # no front days by default (the front's transcripts are the owner's, outside the test); the front tests set them
        self.real_front_days = relay_metrics.front_days
        front = mock.patch.object(relay_metrics, "front_days", return_value=[])
        self.front_days = front.start()
        self.addCleanup(front.stop)

    def files(self):
        out = git(self.main, "ls-tree", "-r", "--name-only", "master", "--", ".relay/changes")
        return sorted(out.splitlines())

    def test_two_riders_get_two_records_and_each_agent_once(self):
        head = git(self.main, "rev-parse", "HEAD")
        lines = []
        relay_metrics.record_landing(self.main, [("item-a", "wt/a"), ("item-b", "wt/b")], head, head, [], 0, lines.append, now=1.8e9)
        a, b = f".relay/changes/item-a/land-{head[:12]}.json", f".relay/changes/item-b/land-{head[:12]}.json"
        # item-c is a finished unit with no landing: the sweep stores it (its agents stopped long before `now`); the train has no record
        self.assertEqual([f.split("/")[2] for f in self.files()], ["item-a", "item-b", "item-c"])
        recs = {f: json.loads(git(self.main, "show", "master:" + f)) for f in self.files()}
        self.assertEqual([x["id"] for x in recs[a]["agents"]], ["a1"])
        self.assertEqual([x["id"] for x in recs[b]["agents"]], ["b1"])
        self.assertEqual((recs[a]["before"], recs[a]["head"]), (head, head))
        # a second write at the same head adds nothing: every agent is already stored
        before = git(self.main, "rev-parse", "master")
        relay_metrics.record_landing(self.main, [("item-a", "wt/a")], head, head, [], 0, lines.append, now=1.8e9)
        self.assertEqual(git(self.main, "rev-parse", "master"), before)
        self.assertEqual(git(self.main, "status", "--porcelain"), "")

    def test_f8_front_days_without_a_record_get_one_with_the_reports_figure(self):
        claude = os.path.join(self.tmp, "claude")
        folder = os.path.join(claude, "projects", "p")
        os.makedirs(folder)
        stamps = ["2026-10-28T10:00:00Z", "2026-10-28T10:05:00Z"]
        lines = [{"type": "user", "timestamp": stamps[0], "message": {"role": "user", "content": "ask"}}]
        lines += [{"type": "assistant", "timestamp": t, "requestId": f"r{i}", "isSidechain": False, "message": {
                   "role": "assistant", "model": "claude-opus-5", "content": [], "usage": {
                       "input_tokens": 50, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0, "output_tokens": 10}}}
                  for i, t in enumerate(stamps)]
        write(os.path.join(folder, "s1.jsonl"), "".join(json.dumps({**x, "sessionId": "s1"}) + "\n" for x in lines))
        usage = {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0, "web_search_requests": 0}
        import relay_prices
        two = 2 * relay_prices.cost("claude-opus-5", usage)       # two identical requests on 28 Oct
        self.front_days.return_value = ["2026-10-28", "2026-10-29"]
        head = git(self.main, "rev-parse", "HEAD")
        with mock.patch("relay_config.claude_dir", return_value=claude):
            relay_metrics.record_landing(self.main, [], None, head, [], 0, print, now=1.8e9)
        got = {f.rsplit("/", 1)[1]: json.loads(git(self.main, "show", "master:" + f)) for f in self.files() if "/front/" in f}
        self.assertEqual(sorted(got), ["2026-10-28.json", "2026-10-29.json"])
        busy, empty = got["2026-10-28.json"], got["2026-10-29.json"]
        self.assertEqual((busy["kind"], busy["agents"]), ("front", []))
        self.assertAlmostEqual(busy["front"]["cost_usd"], round(two, 4), places=4)
        self.assertEqual((busy["front"]["day"], busy["front"]["sessions"], busy["front"]["basis"]), ("2026-10-28", 1, "estimate"))
        # a day with no front session is a stored zero, nothing to estimate
        self.assertEqual(empty["front"], {"day": "2026-10-29", "cost_usd": 0.0, "sessions": 0, "basis": "exact"})
        # written once: a second write adds nothing
        before = git(self.main, "rev-parse", "master")
        with mock.patch("relay_config.claude_dir", return_value=claude):
            relay_metrics.record_landing(self.main, [], None, head, [], 0, print, now=1.8e9)
        self.assertEqual(git(self.main, "rev-parse", "master"), before)

    def test_f8_front_days_are_the_complete_days_without_a_record(self):
        have = [{"front": {"day": "2026-10-28", "cost_usd": 1.0, "sessions": 1, "basis": "exact"}}]
        now = relay_metrics._epoch("2026-10-30T12:00:00Z")      # 30 Oct is not complete; 27 and 29 Oct have no record, 28 Oct has one
        with mock.patch.object(relay_metrics, "stored", return_value=have):
            self.assertEqual(self.real_front_days("m", "r", now), ["2026-10-27", "2026-10-29"])

    def test_a_sweep_waits_for_the_quiet_time(self):
        head = git(self.main, "rev-parse", "HEAD")
        stop = relay_metrics._epoch("2026-10-29T10:10:00Z")
        relay_metrics.record_landing(self.main, [], None, head, [], 0, print, now=stop + 59 * 60)       # 59 min after: still quiet time (60) to go
        self.assertEqual(self.files(), [])
        relay_metrics.record_landing(self.main, [], None, head, [], 0, print, now=stop + 61 * 60)
        self.assertEqual(len(self.files()), 3)

    def test_a_failing_writer_leaves_the_landing_landed(self):
        git(self.wt, "merge", "-q", "--no-edit", "master")
        self.mark(self.wt)
        notes = []
        with mock.patch.dict(os.environ, self.env), mock.patch("relay_metrics.record_landing", side_effect=RuntimeError("boom")):
            result = relay_land.land(self.main, "wt/x", notes.append)
        self.assertEqual(result.outcome, relay_land.LANDED)
        self.assertTrue(any("relay metrics backfill" in line and "boom" in line for line in result.lines), result.lines)

    def test_a_rider_with_no_queue_item_is_named_and_gets_no_record(self):
        before = git(self.main, "rev-parse", "HEAD")
        git(self.main, "checkout", "-q", "-b", "wt/c")
        write(os.path.join(self.main, "lib", "c.py"), "c\n")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "c")
        git(self.main, "checkout", "-q", "master")
        git(self.main, "merge", "-q", "--no-ff", "-m", "Merge wt/c into wt/train-1", "wt/c")
        head = git(self.main, "rev-parse", "HEAD")
        lines = []
        # the train brought in item-a (has an item) and wt/c (has none): one line names wt/c, and item-a still gets its record
        relay_metrics.record_landing(self.main, [("item-a", "wt/a")], before, head, [], 0, lines.append, now=1.8e9)
        self.assertEqual([x for x in lines if "wt/c" in x], [f"metrics: wt/c landed in {head[:12]} with no queue item; no record"])
        self.assertNotIn("wt/a", " ".join(lines))
        self.assertTrue(any(f.startswith(".relay/changes/item-a/land-") for f in self.files()))
        self.assertFalse(any("/c/" in f or "train" in f for f in self.files()))

    def test_a_queue_landing_and_a_records_landing_started_together_both_land(self):
        head = git(self.main, "rev-parse", "HEAD")
        write(os.path.join(self.main, "staged.txt"), "mine\n")
        git(self.main, "add", "staged.txt")
        item = relay_queue.new_item("feature", 50, 10, "2026-10-23T13:49:21Z", "test", "T", "w", "y")
        queue_path = ".relay/queue/zz-test-item.json"
        errors = []

        def queue_side():
            try:
                relay_queue.land_files(self.main, "zz-test-item", lambda rev: {queue_path: relay_queue.serialize("zz-test-item", item)}, "test item")
            except Exception as exc:       # the test names it below
                errors.append(exc)

        thread = threading.Thread(target=queue_side)
        thread.start()
        relay_metrics.record_landing(self.main, [("item-a", "wt/a")], head, head, [], 0, print, now=1.8e9)
        thread.join()
        self.assertEqual(errors, [])
        # both ended on the default branch, each with only its files; the staged file is still staged and in neither commit
        self.assertIn(queue_path, git(self.main, "ls-tree", "-r", "--name-only", "master").splitlines())
        self.assertTrue(any(f.startswith(".relay/changes/item-a/") for f in self.files()))
        self.assertEqual(git(self.main, "diff", "--cached", "--name-only"), "staged.txt")
        self.assertNotIn("staged.txt", git(self.main, "ls-tree", "-r", "--name-only", "master"))

    def test_relay_land_marks_its_gate_for_the_landing_coverage_mode(self):
        git(self.wt, "merge", "-q", "--no-edit", "master")
        self.mark(self.wt)
        seen = []
        import relay_gate
        real = relay_gate.run

        def spy(tree, **kwargs):
            seen.append((kwargs.get("environ") or {}).get("RELAY_LAND"))
            return real(tree, **kwargs)

        with mock.patch.dict(os.environ, self.env), mock.patch("relay_gate.run", spy):
            relay_land.land(self.main, "wt/x", lambda line: None)
        self.assertEqual(seen, ["1"])

    # ---- review findings F1, F5, F7, F10 ----

    def ev(self, kind, **kw):
        return relay_land.Event(kind, kw.pop("ts", "2026-10-29T11:00:00Z"), **kw)

    def changes(self, unit):
        return {f: json.loads(git(self.main, "show", "master:" + f)) for f in self.files() if f.split("/")[2] == unit}

    def test_f1_train_riders_each_hold_the_landings_events(self):
        """Train wt/train-25 lands riders item-a (wt/a) and item-b (wt/b); the events are on the train's branch, pid 77. By the
        design each rider's record holds the landing's asked, locked and done rows, shared (done: 1 gate, 358.8 s)."""
        head = git(self.main, "rev-parse", "HEAD")
        events = [self.ev("asked", branch="wt/train-25", pid=77), self.ev("locked", branch="wt/train-25", pid=77),
                  self.ev("done", branch="wt/train-25", pid=77, gates_run=1, gate_seconds=358.8, outcome="landed"),
                  self.ev("asked", branch="wt/train-25", pid=78),                  # another landing: never in a record
                  self.ev("held", slug="item-a", file="lib/x.py", holder="item-c")]
        relay_metrics.record_landing(self.main, [("item-a", "wt/a"), ("item-b", "wt/b")], head, head, events, 77, print, now=1.8e9, landed="wt/train-25")
        for unit, extra in (("item-a", ["held"]), ("item-b", [])):         # the held row belongs to item-a only
            (rec,) = [r for f, r in self.changes(unit).items() if "/land-" in f]
            self.assertEqual(sorted(r["kind"] for r in rec["land"]), sorted(["asked", "locked", "done"] + extra), unit)
            done = next(r for r in rec["land"] if r["kind"] == "done")
            self.assertEqual((done["gates_run"], done["gate_seconds"]), (1, 358.8))

    def test_f1_a_plain_landing_keeps_its_three_rows(self):
        head = git(self.main, "rev-parse", "HEAD")
        events = [self.ev("asked", branch="wt/a", pid=5), self.ev("locked", branch="wt/a", pid=5), self.ev("done", branch="wt/a", pid=5, gates_run=1, gate_seconds=2.0)]
        relay_metrics.record_landing(self.main, [("item-a", "wt/a")], head, head, events, 5, print, now=1.8e9, landed="wt/a")
        (rec,) = [r for f, r in self.changes("item-a").items() if "/land-" in f]
        self.assertEqual([r["kind"] for r in rec["land"]], ["asked", "locked", "done"])

    def queue_commit(self, items, message="queue"):
        for slug, item in items.items():
            write(os.path.join(self.main, ".relay", "queue", slug + ".json"), relay_queue.serialize(slug, item))
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", message)

    def test_f5_a_fix_closed_on_its_branch_is_a_landing_unit(self):
        """Fix item F is taken by wt/f on master; the cycle's --test close commits it as done on wt/f; wt/f then fast-forwards.
        At the new head F is `done`, yet it belongs to this landing (and a feature still taken, X on wt/fx, does too).
        An item taken by wt/old that landed in an earlier fast-forward (and is still open) does not."""
        taken = "2026-10-24T00:00:00Z"
        base = relay_queue.new_item("fix", 50, 10, "2026-10-23T13:49:21Z", "test", "T", "w", "y", failing="it fails", pass_cases="it passes")
        old_item = relay_queue.new_item("feature", 50, 10, "2026-10-23T13:49:21Z", "test", "T", "w", "y")
        self.queue_commit({"fix-f": relay_queue.changed(base, taken_at=taken, taken_by="wt/f"),
                           "feat-x": relay_queue.changed(old_item, taken_at=taken, taken_by="wt/fx"),
                           "feat-old": relay_queue.changed(old_item, taken_at=taken, taken_by="wt/old")})
        for branch in ("wt/old", "wt/fx"):
            git(self.main, "checkout", "-q", "-b", branch)
            write(os.path.join(self.main, "lib", branch[3:] + ".py"), "x\n")
            git(self.main, "add", "-A")
            git(self.main, "commit", "-q", "-m", branch)
            git(self.main, "checkout", "-q", "master")
            if branch == "wt/old":
                git(self.main, "merge", "-q", "--ff-only", branch)          # an earlier landing
        before = git(self.main, "rev-parse", "master")
        git(self.main, "checkout", "-q", "-b", "wt/f")
        self.queue_commit({"fix-f": relay_queue.changed(base, taken_at=taken, taken_by="wt/f", closed_at="2026-10-25T00:00:00Z", test="t.py::t", fixed_by="abc")}, "closed on its branch")
        git(self.main, "checkout", "-q", "master")
        git(self.main, "merge", "-q", "--no-ff", "-m", "Merge wt/f into wt/train-1", "wt/f")
        git(self.main, "merge", "-q", "--no-ff", "-m", "Merge wt/fx into wt/train-1", "wt/fx")
        head = git(self.main, "rev-parse", "master")
        units = relay_metrics.landed_units(self.main, before, head, "wt/train-1")
        self.assertEqual(sorted(units), [("feat-x", "wt/fx"), ("fix-f", "wt/f")])

    def test_f7_a_dropped_items_held_rows_are_swept_once(self):
        """A landing recorded held(slug=gone, lib/x.py, holder item-c) and `gone` was dropped: no landing has it as a unit, so the sweep
        stores the row under `gone`; a second sweep after the drop stores nothing more."""
        head = git(self.main, "rev-parse", "HEAD")
        item = relay_queue.new_item("feature", 50, 10, "2026-10-23T13:49:21Z", "test", "T", "w", "y")
        self.queue_commit({"gone": relay_queue.changed(item, dropped_at="2026-10-24T00:00:00Z", dropped_why=["no"])})
        events = [self.ev("held", slug="gone", file="lib/x.py", holder="item-c")]
        relay_metrics.record_landing(self.main, [], None, head, events, 0, print, now=1.8e9)
        first = self.changes("gone")
        self.assertEqual(len(first), 1)
        (rec,) = first.values()
        self.assertEqual([(r["kind"], r["file"], r["holder"]) for r in rec["land"]], [("held", "lib/x.py", "item-c")])
        self.assertIn("/sweep-", list(first)[0])
        relay_metrics.record_landing(self.main, [], None, head, events, 0, print, now=1.8e9 + 7200)
        self.assertEqual(list(self.changes("gone")), list(first))

    def test_f3_a_records_landing_that_fails_its_last_try_leaves_no_branch_and_names_no_queue_land(self):
        """land_files whose fast-forward is refused on every try: Refused, no wt/queue-* ref left (a record is not a queue item, so
        `relay queue land` would refuse it and the kept branch would block `relay metrics backfill`); landing again then works."""
        real = relay_queue._git

        def refuse_ff(main, *args, **kwargs):
            if args[:2] == ("merge", "--ff-only"):
                return 1, b"", "not possible to fast-forward"
            return real(main, *args, **kwargs)

        write_at = lambda rev: {".relay/changes/u/land-x.json": relay_metrics.dump(relay_metrics._record("change", "u", None, []))}
        with mock.patch.object(relay_queue, "_git", refuse_ff), mock.patch.object(relay_queue, "QUEUE_LAND_TRIES", 2), \
                mock.patch.object(relay_queue, "WAITS", (0,)):
            with self.assertRaises(relay_queue.Refused) as ctx:
                relay_queue.land_files(self.main, "metrics-abc", write_at, "change records")
        self.assertNotIn("relay queue land", str(ctx.exception))
        self.assertEqual(git(self.main, "for-each-ref", "refs/heads/wt/queue-*"), "")
        self.assertIsNotNone(relay_queue.land_files(self.main, "metrics-abc", write_at, "change records"))

    def test_f10_stored_reads_all_records_in_a_constant_number_of_git_processes(self):
        head = git(self.main, "rev-parse", "HEAD")
        for n in range(5):
            write(os.path.join(self.main, ".relay", "changes", f"u{n}", "land-x.json"), relay_metrics.dump(relay_metrics._record("change", f"u{n}", None, [])))
        write(os.path.join(self.main, ".relay", "changes", "bad", "land-x.json"), "{not json")      # skipped, not fatal
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "records")
        calls = []
        real_git, real_queue = relay_metrics.relay_git.git, relay_queue._git
        with mock.patch.object(relay_metrics.relay_git, "git", lambda *a, **k: calls.append(a[1:2]) or real_git(*a, **k)), \
                mock.patch.object(relay_queue, "_git", lambda *a, **k: calls.append(a[1:2]) or real_queue(*a, **k)):
            found = relay_metrics.stored(self.main, "master")
        self.assertEqual(sorted(r["unit"] for r in found), ["u0", "u1", "u2", "u3", "u4"])
        self.assertEqual(calls, [("ls-tree",), ("cat-file",)])         # one listing and one batch, however many records
        del head


class Reader(unittest.TestCase):
    def rec(self, unit, start, stop, cost):
        return {"schema": 1, "kind": "change", "unit": unit, "agents": [{"id": unit + start, "stage": "build", "start": start, "stop": stop, "cost_usd": cost}], "land": []}

    def test_summary_groups_by_week(self):
        # 2026-10-29 is a Thursday of ISO week 44, 2026-11-03 a Tuesday of week 45; build minutes 10 and 20 in week 44 (median 15), 30 in week 45
        recs = [self.rec("a", "2026-10-29T10:00:00Z", "2026-10-29T10:10:00Z", 1.0), self.rec("b", "2026-10-29T11:00:00Z", "2026-10-29T11:20:00Z", 3.0),
                self.rec("c", "2026-11-03T10:00:00Z", "2026-11-03T10:30:00Z", 2.0)]
        with mock.patch.object(relay_metrics, "stored", return_value=recs), mock.patch.object(relay_metrics, "coverage_by_week", return_value={"2026-W45": [80.0, 90.0]}):
            lines = relay_metrics.summary("main", "rev")
        self.assertEqual(lines[1:], ["2026-W44:", "  build: 2 agents, median 15.0 min, p90 20.0 min, total 30.0 min", "  cost per unit: median $2.00, total $4.00",
                                     "2026-W45:", "  build: 1 agents, median 30.0 min, p90 30.0 min, total 30.0 min", "  cost per unit: median $2.00, total $2.00",
                                     "  coverage: median 85.0% over 2 gates"])

    def test_owner_wait_is_asked_to_answered(self):
        # two answered questions: 30 min and 90 min = 120 min; a third is unanswered and counts for nothing
        notes = [relay_queue.Note("decision", "2026-10-29T10:00:00Z", ["q"], answered_at="2026-10-29T10:30:00Z", answer=["a"]),
                 relay_queue.Note("decision", "2026-10-29T11:00:00Z", ["q"], answered_at="2026-10-29T12:30:00Z", answer=["a"]),
                 relay_queue.Note("decision", "2026-10-29T13:00:00Z", ["q"]), relay_queue.Note("said", "2026-10-29T09:00:00Z", ["hi"])]
        rec = self.rec("a", "2026-10-29T10:00:00Z", "2026-10-29T10:10:00Z", 1.0)
        with mock.patch.object(relay_metrics, "stored", return_value=[rec]), mock.patch("relay_queue.read_queue", return_value=[{"slug": "a", "notes": notes}]):
            lines = relay_metrics.unit_lines("main", "rev", "a")
        self.assertIn("owner: 2 answers, 120.0 min waited", lines)

    def test_coverage_trend_places_a_log_in_the_week_of_its_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = os.path.join(tmp, "m")
            os.makedirs(main)
            git(main, "init", "-q", "-b", "master")
            for name, value, when in (("a", "80.0", "2026-10-29T12:00:00Z"), ("b", "90.0", "2026-10-29T13:00:00Z"), ("c", "50.0", "2026-11-03T12:00:00Z")):
                write(os.path.join(main, ".relay", "checks", name * 40 + ".gate.log"), f"head x\nci: coverage {value}% of lib, bin, plugins (1 of 2 lines)\n")
                git(main, "add", "-A")
                with mock.patch.dict(os.environ, {"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}):
                    git(main, "commit", "-q", "-m", name)
            weeks = relay_metrics.coverage_by_week(main, "refs/heads/master")
        self.assertEqual({k: sorted(v) for k, v in weeks.items()}, {"2026-W44": [80.0, 90.0], "2026-W45": [50.0]})


class Coverage(unittest.TestCase):
    def run_tests(self, tests_rc, mode="every", uv=True):
        calls = []

        def run(cmd, log, env=None):
            calls.append(cmd)
            if "json" in cmd:
                out = cmd[cmd.index("-o") + 1]
                write(out, json.dumps({"totals": {"percent_covered": 0.0, "covered_lines": 0, "num_statements": 10}}))
            return mock.Mock(returncode=tests_rc if "run" in cmd else 0)

        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, "deps.toml"), '[[dep]]\nname = "coverage"\nuv_tool = "coverage==7.17.0"\n')
            result = relay_coverage.run_tests(root, {}, run, mock.Mock(), lambda tool: "/bin/uv" if uv else None, mode)
            rc_text = ""
            if mode != "off" and uv:
                with open(os.path.join(root, ".ci", "coverage", "rc.toml")) as handle:
                    rc_text = handle.read()
            return result, calls, rc_text, root

    def test_zero_percent_is_a_line_not_a_failure(self):
        (rc, line), calls, rc_text, root = self.run_tests(0)
        self.assertEqual(rc, 0)
        self.assertEqual(line, "ci: coverage 0.0% of lib, bin, plugins (0 of 10 lines)")
        # data files sit under the ignored .ci/coverage/ (absolute), children included
        self.assertIn(f'data_file = "{root}/.ci/coverage/data"', rc_text)
        self.assertIn("coverage==7.17.0", calls[0])
        # `-W` is a python option: after `coverage run` coverage.py refuses it ("no such option: -W", seen on the first real gate run)
        self.assertLess(calls[0].index("-W"), calls[0].index("-m"))
        self.assertNotIn("-W", calls[0][calls[0].index("-m"):])

    def test_the_tests_own_exit_code_passes_through(self):
        self.assertEqual(self.run_tests(1)[0][0], 1)

    def test_landing_mode_measures_only_the_gate_relay_land_runs(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, ".claude", "kit.toml"), '[metrics]\ncoverage = "landing"\n')
            cfg = relay_config.load_bindings(root)
            self.assertEqual(relay_coverage.effective_mode(cfg, {"RELAY_LAND": "1"}), "every")
            self.assertEqual(relay_coverage.effective_mode(cfg, {}), "off")
            self.assertEqual(relay_coverage.effective_mode({}, {}), "every")

    def test_off_and_no_uv_leave_the_plain_run(self):
        self.assertEqual(self.run_tests(0, mode="off")[0], (None, None))
        self.assertEqual(self.run_tests(0, uv=False)[0], (None, None))


if __name__ == "__main__":
    unittest.main()
