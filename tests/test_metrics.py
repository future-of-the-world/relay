"""Change records (lib/relay_metrics.py), the label grammar, the routing guard's label rule, the ledger hook's label and the coverage
line of the gate. Every test builds a temporary repository or folder; nothing touches the live .relay/ or ~/.relay."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

from test_gate import Fixture, git, write  # noqa: E402

import relay_coverage  # noqa: E402
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

    def test_the_tests_own_exit_code_passes_through(self):
        self.assertEqual(self.run_tests(1)[0][0], 1)

    def test_off_and_no_uv_leave_the_plain_run(self):
        self.assertEqual(self.run_tests(0, mode="off")[0], (None, None))
        self.assertEqual(self.run_tests(0, uv=False)[0], (None, None))


if __name__ == "__main__":
    unittest.main()
