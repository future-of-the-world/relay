"""Queue time estimates: a change's real minutes come from agent transcripts, the estimate from the median of measured changes."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import relay_estimate as est  # noqa: E402

A = est.AgentRow


def write_agent(projects, session, agent_id, cwd, agent_type, start, end, prompt="go", proj="proj"):
    folder = os.path.join(projects, proj, session, "subagents")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"agent-{agent_id}.jsonl")
    lines = [{"type": "user", "cwd": cwd, "timestamp": start, "message": {"role": "user", "content": prompt}},
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
        lines = est.compare_lines([self.item()], {"s": est.Measured("c1", 15, 10, 2)})
        # wall: 10:00 to 11:30 is 90 minutes
        self.assertIn("30 est", lines[1])
        self.assertIn("15 agents (10 build)", lines[1])
        self.assertIn("90 wall", lines[1])

    def test_open_or_unmeasured_items_left_out(self):
        got = est.compare_lines([self.item(closed_at=None), self.item(slug="t", taken_by="wt/none")], {"s": est.Measured("c1", 1, 0, 1)})
        self.assertEqual(len(got), 1)


class Brief(unittest.TestCase):
    """F1: an agent run with git -C from the primary checkout is tied to its change by the brief."""
    def rows(self, **kw):
        with tempfile.TemporaryDirectory() as projects:
            write_agent(projects, "s1", "a1", "/r", "delegate:worker", "2026-10-01T10:00:00Z", "2026-10-01T10:07:00Z", **kw)
            return est.agent_rows(projects)

    def test_brief_names_worktree(self):
        self.assertEqual(self.rows(prompt="Worktree: /r/.worktrees/c1 build it"), [A("c1", "delegate:worker", 420.0)])

    def test_no_worktree_named_no_row(self):
        self.assertEqual(self.rows(prompt="just look at /r/lib"), [])

    def test_first_worktree_line_wins(self):
        self.assertEqual(self.rows(prompt="Train.\nWorktree: /r/.worktrees/train\nriders: /r/.worktrees/a /r/.worktrees/b"),
                         [A("train", "delegate:worker", 420.0)])


class Repo(unittest.TestCase):
    """F2: only this repo's worktrees count."""
    def test_same_name_in_other_repo_ignored(self):
        with tempfile.TemporaryDirectory() as projects:
            write_agent(projects, "s", "a", "/a/.worktrees/x", "delegate:worker", "2026-10-01T10:00:00Z", "2026-10-01T10:05:00Z", proj="-a--worktrees-x")
            write_agent(projects, "s", "b", "/b/.worktrees/x", "delegate:worker", "2026-10-01T10:00:00Z", "2026-10-01T10:30:00Z", proj="-b--worktrees-x")
            write_agent(projects, "s", "c", "/b", "delegate:worker", "2026-10-01T10:00:00Z", "2026-10-01T10:30:00Z",
                        prompt="Worktree: /b/.worktrees/x", proj="-b")
            self.assertEqual(est.agent_rows(projects, "/a"), [A("x", "delegate:worker", 300.0)])
            self.assertEqual(est.agent_rows(projects, "/nowhere"), [])


class Window(unittest.TestCase):
    """F4: one worktree name reused by two changes."""
    def item(self, taken, closed):
        return {"problems": [], "slug": "s", "time": 1, "taken_by": "wt/x", "taken_at": taken, "closed_at": closed}

    def test_agents_split_by_window(self):
        rows = [A("x", "delegate:worker", 600, "2026-10-01T10:10:00Z"), A("x", "delegate:worker", 1800, "2026-10-01T12:10:00Z"),
                A("x", "delegate:thinker", 60, "2026-10-01T09:00:00Z")]
        a = est.measure_item(rows, self.item("2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z"))
        b = est.measure_item(rows, self.item("2026-10-01T12:00:00Z", "2026-10-01T13:00:00Z"))
        # A: 10 min (the 09:00 design agent began before taken_at); B: 30 min
        self.assertEqual((a.agent_min, a.agents), (10.0, 1))
        self.assertEqual((b.agent_min, b.agents), (30.0, 1))
        both = est.measure_item(rows, self.item("2026-10-01T08:00:00Z", "2026-10-01T13:00:00Z"))
        self.assertEqual(both.agent_min, 41.0)


class View(unittest.TestCase):
    """F5: the view through bin/relay, with a temp config folder and queue."""
    def run_view(self, closed):
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.realpath(os.path.join(tmp, "repo"))
            os.makedirs(os.path.join(repo, ".relay", "queue"))
            subprocess.run(["git", "init", "-q", repo], check=True)
            cfg = os.path.join(tmp, "cfg")
            write_agent(os.path.join(cfg, "projects"), "s", "a", repo + "/.worktrees/c1", "delegate:worker",
                        "2026-10-01T10:05:00Z", "2026-10-01T10:15:00Z", proj=est.re.sub(r"[^A-Za-z0-9]", "-", repo) + "--worktrees-c1")
            item = {"slug": "it", "time": 30, "taken_by": "wt/c1", "taken_at": "2026-10-01T10:00:00Z",
                    "closed_at": "2026-10-01T11:00:00Z" if closed else None}
            import io
            from contextlib import redirect_stdout
            old = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = cfg
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("qe", os.path.join(root, "lib", "queue_ext", "estimate.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                out = io.StringIO()
                with redirect_stdout(out):
                    mod.run([dict(item, problems=[])], ["--root", repo])
            finally:
                if old is None:
                    del os.environ["CLAUDE_CONFIG_DIR"]
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old
            return out.getvalue()

    def test_closed_item_shows_actual(self):
        out = self.run_view(True)
        self.assertIn("30 est", out)
        self.assertIn("10 agents (10 build)", out)

    def test_open_item_no_line(self):
        out = self.run_view(False)
        self.assertNotIn("est ", out.split("\n", 1)[1])
        self.assertIn("no measured change yet", out)


if __name__ == "__main__":
    unittest.main()
