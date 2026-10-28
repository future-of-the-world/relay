"""Queue time estimates: a change's real minutes come from agent transcripts, the estimate from the median of measured changes."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import relay_estimate as est  # noqa: E402

A = est.AgentRow


def write_agent(projects, session, agent_id, cwd, agent_type, start, end):
    folder = os.path.join(projects, "proj", session, "subagents")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"agent-{agent_id}.jsonl")
    lines = [{"type": "user", "cwd": cwd, "timestamp": start, "message": {"role": "user", "content": "go"}},
             {"type": "assistant", "cwd": cwd, "timestamp": end, "requestId": "r1",
              "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "ok"}],
                          "usage": {"input_tokens": 1, "output_tokens": 1}}}]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(json.dumps(x) for x in lines))
    with open(path[:-len(".jsonl")] + ".meta.json", "w", encoding="utf-8") as handle:
        json.dump({"agentType": agent_type}, handle)


class Measure(unittest.TestCase):
    def test_worktree_name_from_cwd(self):
        self.assertEqual(est.worktree_of("/r/.worktrees/foo-bar/lib"), "foo-bar")
        self.assertIsNone(est.worktree_of("/r/lib"))

    def test_agent_minutes_sum_and_build_part(self):
        # change "c1": worker 10 min + checker 5 min = 15 agent min, 10 build; an agent outside any worktree is not counted
        rows = [A("c1", "delegate:worker", 600), A("c1", "delegate:checker", 300), A("c2", "ng-worker", 120)]
        got = est.by_change(rows)
        self.assertEqual((got["c1"].agent_min, got["c1"].build_min, got["c1"].agents), (15.0, 10.0, 2))
        self.assertEqual(got["c2"].build_min, 2.0)

    def test_rows_read_from_transcripts(self):
        with tempfile.TemporaryDirectory() as projects:
            write_agent(projects, "s1", "a1", "/r/.worktrees/c1", "delegate:worker", "2026-10-01T10:00:00Z", "2026-10-01T10:07:00Z")
            write_agent(projects, "s1", "a2", "/r", "delegate:scout", "2026-10-01T10:00:00Z", "2026-10-01T10:09:00Z")
            rows = est.agent_rows(projects)
        # 10:00 to 10:07 is 7 minutes; the scout ran outside a worktree and is dropped
        self.assertEqual(rows, [A("c1", "delegate:worker", 420.0)])


class Estimate(unittest.TestCase):
    def test_median_fixed_plus_median_build(self):
        # fixed (agents - build): 20, 30, 100 -> median 30; build: 5, 10, 8 -> median 8; estimate 38
        hist = [est.Measured("a", 25, 5, 3), est.Measured("b", 40, 10, 3), est.Measured("c", 108, 8, 3)]
        self.assertEqual(est.estimate(hist), 38)
        self.assertEqual(est.estimate(hist, paid_run_min=12), 50)

    def test_no_history_no_guess(self):
        self.assertIsNone(est.estimate([]))

    def test_text_places(self):
        self.assertTrue(est.edits_texts(["roles/judge.txt a note"]))
        self.assertTrue(est.edits_texts(["plugins/core/skills/x/SKILL.md:3"]))
        self.assertFalse(est.edits_texts(["lib/relay_queue.py:5", "tests/rules/x.py"]))


class Compare(unittest.TestCase):
    def item(self, **kw):
        base = {"problems": [], "slug": "s", "time": 30, "taken_by": "wt/c1", "taken_at": "2026-10-01T10:00:00Z",
                "closed_at": "2026-10-01T11:30:00Z"}
        base.update(kw)
        return base

    def test_actual_beside_estimate(self):
        lines = est.compare_lines([self.item()], {"c1": est.Measured("c1", 15, 10, 2)})
        # wall: 10:00 to 11:30 is 90 minutes
        self.assertIn("30 est", lines[1])
        self.assertIn("15 agents (10 build)", lines[1])
        self.assertIn("90 wall", lines[1])

    def test_open_or_unmeasured_items_left_out(self):
        got = est.compare_lines([self.item(closed_at=None), self.item(taken_by="wt/none")], {"c1": est.Measured("c1", 1, 0, 1)})
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()
