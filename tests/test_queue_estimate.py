"""Queue time estimates: a change's real minutes come from agent transcripts, the estimate from the median of measured changes."""
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import relay_estimate as est  # noqa: E402

A = est.AgentRow


def write_agent(projects, session, agent_id, cwd, agent_type, start, end, prompt="go", proj="proj", run=None):
    folder = os.path.join(projects, proj, session, "subagents", *(["workflows", run] if run else []))
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

    def test_worktree_folder_is_a_whole_path_part(self):
        # `my.worktrees` is not the `.worktrees` folder; a real one is still found
        self.assertIsNone(est.worktree_of("/x/relay/lib/my.worktrees/fx"))
        self.assertEqual(est.worktree_of("/x/relay/.worktrees/fx/lib"), "fx")

    def test_cwd_in_the_projects_own_folder_with_root(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_kit(root)
            self.assertEqual(est.change_of(f"{root}/.worktree/fx/lib", "", root=root), "fx")

    def test_agent_rows_with_cwd_in_the_projects_own_folder(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as projects:
            self.write_kit(root)
            proj = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(root))
            write_agent(projects, "s1", "a1", f"{root}/.worktree/fx", "delegate:worker", "2026-10-01T10:00:00Z", "2026-10-01T10:07:00Z", proj=proj)
            # 10:00 to 10:07 is 7 minutes, one row for change fx
            self.assertEqual(est.agent_rows(projects, root), [A("fx", "delegate:worker", 420.0)])

    def write_kit(self, root):
        os.makedirs(os.path.join(root, ".claude"))
        with open(os.path.join(root, ".claude", "kit.toml"), "w") as handle:
            handle.write('[project]\nworktrees = ".worktree"\n')

    def test_change_of_brief_line_in_the_projects_folder(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "kit.toml"), "w") as handle:
                handle.write('[project]\nworktrees = ".worktree"\n')
            line = f"Worktree: {root}/.worktree/fx (branch wt/fx)"
            self.assertEqual(est.change_of(root, line, root=root), "fx")

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
        self.assertNotIn("paid", est.next_estimate_text(hist))      # F3: the wave's paid run is not added to an item

    def test_no_history_no_guess(self):
        self.assertIsNone(est.estimate([]))


class PaidRun(unittest.TestCase):
    """F3: the paid run is per wave; it is a line of its own, never added to an item's estimate."""
    def batch(self, folder, name, seconds, cost, partial=False):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            json.dump({"durationSeconds": seconds, "costUsd": cost, "partial": partial}, handle)

    def test_median_of_full_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            self.batch(folder, "a.json", 1200, 4.0)
            self.batch(folder, "b.json", 2400, 6.0)
            self.batch(folder, "c.json", 3600, 10.0)
            self.batch(folder, "d.json", 60, 0.5, partial=True)     # a partial batch is not a run of the suite
            # minutes 20, 40, 60 -> median 40; costs 4, 6, 10 -> median 6
            self.assertIn("median 40m and $6.00 over 3 full runs", est.paid_run_text(folder))

    def test_none_measured_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn("not measured yet", est.paid_run_text(folder))
            self.assertIn("not measured yet", est.paid_run_text(os.path.join(folder, "missing")))


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


class BriefFile(unittest.TestCase):
    """F1: the prompt only names a brief file; the worktree is in the file the agent read first (kept in its transcript)."""
    def write(self, projects, tool_text, prompt="Read and follow the brief /s/briefs/b.md"):
        write_agent(projects, "s1", "a1", "/r", "delegate:worker", "2026-10-01T10:00:00Z", "2026-10-01T10:07:00Z", prompt=prompt)
        path = os.path.join(projects, "proj", "s1", "subagents", "agent-a1.jsonl")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n" + json.dumps({"type": "user", "cwd": "/r", "timestamp": "2026-10-01T10:00:01Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": [{"type": "text", "text": tool_text}]}]}}))

    def test_worktree_from_brief_read(self):
        with tempfile.TemporaryDirectory() as projects:
            self.write(projects, "Fix it in /r/.worktrees/c9 (branch wt/c9)")
            self.assertEqual(est.agent_rows(projects), [A("c9", "delegate:worker", 420.0)])

    def test_branch_from_brief_read(self):
        with tempfile.TemporaryDirectory() as projects:
            self.write(projects, "work on branch wt/c9 only")
            self.assertEqual(est.agent_rows(projects), [A("c9", "delegate:worker", 420.0)])

    def test_nothing_named_no_row(self):
        with tempfile.TemporaryDirectory() as projects:
            self.write(projects, "just edit lib/x.py")
            self.assertEqual(est.agent_rows(projects), [])


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
        ia, ib = self.item("2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z"), self.item("2026-10-01T12:00:00Z", "2026-10-01T13:00:00Z")
        a = est.measure_item(rows, ia, [ia, ib])
        b = est.measure_item(rows, ib, [ia, ib])
        # A: 10 min (the 09:00 design agent began before taken_at); B: 30 min
        self.assertEqual((a.agent_min, a.agents), (10.0, 1))
        self.assertEqual((b.agent_min, b.agents), (30.0, 1))
        # an agent still running after the item's closed_at (the last checks) counts to it: 11:30 belongs to A, not lost
        late = rows + [A("x", "delegate:fixer", 120, "2026-10-01T11:30:00Z")]
        self.assertEqual(est.measure_item(late, ia, [ia, ib]).agent_min, 12.0)
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
            old_home = os.environ.get("RELAY_HOME")
            os.environ["RELAY_HOME"] = os.path.join(tmp, "home")
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("qe", os.path.join(root, "lib", "queue_ext", "estimate.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                out = io.StringIO()
                with redirect_stdout(out):
                    mod.run([dict(item, problems=[])], ["--root", repo])
            finally:
                if old_home is None:
                    del os.environ["RELAY_HOME"]
                else:
                    os.environ["RELAY_HOME"] = old_home
                if old is None:
                    del os.environ["CLAUDE_CONFIG_DIR"]
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = old
            return out.getvalue()

    def test_closed_item_shows_actual(self):
        out = self.run_view(True)
        self.assertIn("30 est", out)
        self.assertIn("10 agents (10 build)", out)

    def test_view_prints_paid_run_and_coverage(self):
        out = self.run_view(True)
        self.assertIn("paid run of a wave (not part of an item's estimate)", out)
        self.assertIn("coverage: 1 of 1 closed items", out)

    def test_open_item_no_line(self):
        out = self.run_view(False)
        self.assertNotIn("est ", out.split("\n", 1)[1])
        self.assertIn("no measured change yet", out)


if __name__ == "__main__":
    unittest.main()


class Workflow(unittest.TestCase):
    """Agents of a workflow run live in subagents/workflows/<run>/ and start in the folder the workflow was launched from."""
    def test_workflow_agents_are_read(self):
        with tempfile.TemporaryDirectory() as projects:
            write_agent(projects, "s1", "g1", "/r/.worktrees/c1", "delegate:checker", "2026-10-01T10:00:00Z", "2026-10-01T10:04:00Z", run="wf_1")
            # 4 minutes in a workflow folder: counted (the glob used to stop at subagents/agent-*.jsonl)
            self.assertEqual(est.agent_rows(projects), [A("c1", "delegate:checker", 240.0)])

    def test_brief_outranks_launch_folder_in_a_workflow(self):
        with tempfile.TemporaryDirectory() as projects:
            write_agent(projects, "s1", "g1", "/r/.worktrees/old", "delegate:fixer", "2026-10-01T10:00:00Z", "2026-10-01T10:03:00Z",
                        prompt="Worktree: /r/.worktrees/new", run="wf_1")
            write_agent(projects, "s1", "g2", "/r/.worktrees/old", "delegate:fixer", "2026-10-01T10:00:00Z", "2026-10-01T10:03:00Z",
                        prompt="Worktree: /r/.worktrees/new")
            rows = est.agent_rows(projects)
        # workflow agent: its brief names "new"; a plain subagent keeps its own working folder "old"
        self.assertEqual(sorted(r.change for r in rows), ["new", "old"])


class ViewRoot(unittest.TestCase):
    def test_root_inside_worktree_is_the_repo(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "queue_ext"))
        import estimate as view
        self.assertEqual(view.repo_top("/r/.worktrees/c1"), "/r")
        self.assertEqual(view.repo_top("/r"), "/r")

    def test_repo_top_of_a_project_with_its_own_worktrees_folder(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "queue_ext"))
        import estimate as view
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".claude"))
            with open(os.path.join(root, ".claude", "kit.toml"), "w") as handle:
                handle.write('[project]\nworktrees = ".worktree"\n')
            self.assertEqual(view.repo_top(os.path.join(root, ".worktree", "fx")), root)
