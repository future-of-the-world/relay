"""Library tests: the bench pipeline (fake claude)."""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import Base, ROOT  # noqa: E402


class Bench(Base):
    def fake_claude(self, cost, turns, text, make_file=None):
        """A `claude` that prints a result document; records its argv; optionally writes a file."""
        path = os.path.join(self.tmp, "claude-fake")
        with open(path, "w") as handle:
            handle.write("#!/usr/bin/env bash\n")
            handle.write(f"printf '%s\\n' \"$@\" > \"{self.tmp}/argv-$$.txt\"\n")
            if make_file:
                handle.write(f"echo made > {make_file}\n")
            handle.write("cat <<'EOF'\n")
            handle.write(json.dumps({"type": "result", "subtype": "success", "duration_ms": 4200, "duration_api_ms": 3100,
                                     "num_turns": turns, "result": text, "session_id": "fake", "total_cost_usd": cost,
                                     "usage": {"input_tokens": 10, "output_tokens": 20},
                                     "modelUsage": {"claude-sonnet-5": {"costUSD": cost * 0.7}, "claude-haiku-5": {"costUSD": cost * 0.3}}}))
            handle.write("\nEOF\n")
        os.chmod(path, 0o755)
        os.environ["RELAY_CLAUDE_BIN"] = path
        return path

    def scenario(self):
        folder = os.path.join(self.tmp, "scen")
        os.makedirs(os.path.join(folder, "fixture"))
        with open(os.path.join(folder, "fixture", "README.md"), "w") as handle:
            handle.write("fixture\n")
        with open(os.path.join(folder, "prompt.md"), "w") as handle:
            handle.write("Add a file called out.txt containing 'made' and reply DONE.")
        with open(os.path.join(folder, "scenario.toml"), "w") as handle:
            handle.write('name = "make-file"\nfixture = "fixture"\nmax_turns = 5\nallowed_tools = ["Write"]\n'
                         '[[graders]]\nname = "said-done"\ntype = "regex"\npattern = "DONE"\n'
                         '[[graders]]\nname = "file"\ntype = "file_exists"\npath = "out.txt"\n'
                         '[[graders]]\nname = "cmd"\ntype = "command"\ncommand = "grep -q made out.txt"\n')
        return folder

    def test_two_profiles_side_by_side(self):
        import relay_bench as rb
        self.fake_claude(0.42, 3, "DONE", make_file="out.txt")
        a = rb.load_profile("active")
        b = rb.load_profile("sonnet-front")
        s = rb.load_scenario(self.scenario())
        out_dir, doc, text = rb.run_bench([a, b], [s], runs=1, out_root=os.path.join(self.tmp, "bench"))
        self.assertEqual(len(doc["rows"]), 2)
        self.assertEqual(doc["rows"][0]["score"], 1.0)
        self.assertEqual(doc["rows"][0]["cost_usd"], 0.42)
        self.assertIn("delta (B-A)", text)
        self.assertIn("Verdict", text)
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "results.json")))
        # the profile reached the command line: model, agents json with tiers, rules
        argv = open(next(os.path.join(self.tmp, f) for f in os.listdir(self.tmp) if f.startswith("argv-"))).read()
        self.assertIn("--model", argv)
        self.assertIn("--agents", argv)
        self.assertIn('"scout"', argv)
        self.assertIn("--append-system-prompt", argv)

    def test_failed_grader_lowers_score_and_verdict_keeps_a(self):
        import relay_bench as rb
        self.fake_claude(0.10, 2, "not finished")       # no file, no DONE
        a = rb.load_profile("active")
        b = rb.load_profile("lean-rules")
        s = rb.load_scenario(self.scenario())
        _, doc, text = rb.run_bench([a, b], [s], runs=1, out_root=os.path.join(self.tmp, "bench"))
        self.assertEqual(doc["rows"][0]["score"], 0.0)
        self.assertIn("failed graders", text)

    def test_agent_definitions_follow_profile(self):
        import relay_bench as rb
        p = rb.load_profile("sonnet-judge")
        agents = rb.agent_definitions(p)
        self.assertEqual(agents["critic"]["model"], "sonnet")
        self.assertEqual(agents["critic"]["effort"], "xhigh")
        self.assertEqual(agents["scout"]["model"], "haiku")
        self.assertIn("Read", agents["scout"]["tools"])

    def test_derive_profile_with_set(self):
        os.environ["RELAY_ROOT"] = self.tmp   # candidates are written under the root
        os.makedirs(os.path.join(self.tmp, "profiles", "candidates"))
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]
        import relay_bench as rb
        base = rb.load_profile(os.path.join(ROOT, "profiles", "active.toml"))
        b = rb.derive_profile(base, ["models.build=haiku", "effort.build=low", "delegate.max_parallel=2"])
        self.assertEqual(b["models"]["build"], "haiku")
        self.assertEqual(b["effort"]["build"], "low")
        self.assertEqual(b["delegate"]["max_parallel"], 2)
        self.assertEqual(base["models"]["build"], "sonnet")
        # deriving writes nothing; run_bench writes the file beside the report (tests/test_bench_set_clean.py)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "profiles", "candidates")), [])
        written = os.path.join(self.tmp, "derived.toml")
        with open(written, "w", encoding="utf-8") as handle:
            handle.write(rb.to_toml(b))
        again = rb.load_profile(written)
        self.assertEqual(again["models"]["build"], "haiku")
        self.assertEqual(again["rules"]["load"], base["rules"]["load"])

    def test_candidate_with_plugin_copy_drives_agents_and_plugin_dir(self):
        root = os.path.join(self.tmp, "root")
        shutil.copytree(os.path.join(ROOT, "plugins", "delegate"), os.path.join(root, "plugins", "delegate"))
        shutil.copytree(os.path.join(ROOT, "profiles"), os.path.join(root, "profiles"))
        shutil.copytree(os.path.join(ROOT, "rules"), os.path.join(root, "rules"))
        os.environ["RELAY_ROOT"] = root
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]
        import relay_bench as rb
        out, copied = rb.new_candidate("plan-first", "active", ["delegate"], ["effort.build=low"])
        worker = os.path.join(copied[0], "agents", "worker.md")
        with open(worker, "a") as handle:
            handle.write("\n## 0. Plan\nList the steps first.\n")
        again = rb.load_profile("plan-first")
        agents = rb.agent_definitions(again)
        self.assertIn("## 0. Plan", agents["worker"]["prompt"])
        self.assertEqual(agents["worker"]["effort"], "low")
        cmd = rb.claude_command(again, {"max_turns": 3}, "p", None, None)
        self.assertTrue(any(os.path.realpath(copied[0]) == c for c in cmd), cmd)
        self.assertNotIn(os.path.join(os.path.realpath(root), "plugins", "delegate"), cmd)

    def test_parse_result_from_stream(self):
        import relay_bench as rb
        out = '{"type":"system"}\n{"type":"result","total_cost_usd":0.5,"result":"ok"}\n'
        self.assertEqual(rb.parse_result(out)["total_cost_usd"], 0.5)
        self.assertEqual(rb.parse_result("")["total_cost_usd"] if rb.parse_result("") else None, None)

    def test_cost_ceiling_marks_partial(self):
        import relay_bench as rb
        self.fake_claude(5.0, 3, "DONE", make_file="out.txt")
        a = rb.load_profile("active")
        s = rb.load_scenario(self.scenario())
        _, doc, _ = rb.run_bench([a], [s], runs=3, out_root=os.path.join(self.tmp, "bench"), max_cost_usd=6.0)
        self.assertTrue(doc["partial"])
        self.assertEqual(len(doc["rows"]), 2)

    def transcript(self, session_id, calls, subagent_calls=()):
        """A config folder holding a session transcript (and a subagent's) with the given Bash commands."""
        config = os.path.join(self.tmp, "cfg")
        proj = os.path.join(config, "projects", "-some-folder")
        os.makedirs(os.path.join(proj, session_id, "subagents"))

        def lines(commands):
            return "".join(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "ran it"},
                {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": c}}]}}) + "\n" for c in commands) + "{torn"
        with open(os.path.join(proj, session_id + ".jsonl"), "w") as handle:
            handle.write(lines(calls))
        with open(os.path.join(proj, session_id, "subagents", "agent-1.jsonl"), "w") as handle:
            handle.write(lines(subagent_calls))
        return config

    def test_tool_called_sees_a_real_command_not_a_word(self):
        import relay_bench as rb
        g = {"tool": "^Bash$", "input": r"\bpython3?\b.*scratch"}
        # the checker's subagent ran python on a scratch file: 1 hit of 3 calls
        cfg = self.transcript("s1", ["ls"], ["python3 /tmp/scratch/check.py", "echo hi"])
        self.assertTrue(rb.tool_called(g, "s1", rb.tool_calls("s1", cfg))[0])
        # a session that only wrote "I ran a script" in its reply made no such call
        cfg2 = self.transcript("s2", ["ls", "cat notes.md"])
        self.assertFalse(rb.tool_called(g, "s2", rb.tool_calls("s2", cfg2))[0])
        # exists = false inverts
        self.assertTrue(rb.tool_called({**g, "exists": False}, "s2", rb.tool_calls("s2", cfg2))[0])
        self.assertEqual(rb.tool_calls("nope", cfg), [])

    def test_scenario_file_may_name_the_tool_called_grader(self):
        import relay_bench as rb
        folder = os.path.join(self.tmp, "scen-tc")
        os.makedirs(folder)
        with open(os.path.join(folder, "prompt.md"), "w") as handle:
            handle.write("run a script")
        with open(os.path.join(folder, "scenario.toml"), "w") as handle:
            handle.write('name = "tc"\nmax_turns = 5\n[[graders]]\nname = "ran-python"\ntype = "tool_called"\ninput = "python3"\n')
        # loads (was refused as 'unknown type'), then grades a stored session by its calls, not the reply text
        scen = rb.load_scenario(folder)
        cfg = self.transcript("s8", ["python3 sketch.py"])
        self.assertTrue(rb.grade(scen, self.tmp, "ok", "claude", "haiku", session_id="s8", config_dir=cfg)[-1]["passed"])
        cfg2 = self.transcript("s9", ["ls"])
        self.assertFalse(rb.grade(scen, self.tmp, "I ran python3", "claude", "haiku", session_id="s9", config_dir=cfg2)[-1]["passed"])

    def test_no_secret_from_the_environment_reaches_a_grader(self):
        import relay_bench as rb
        fake = "sk-fake-0123456789abcdef"
        os.environ["FAKE_BENCH_API_KEY"] = fake
        self.addCleanup(os.environ.pop, "FAKE_BENCH_API_KEY", None)
        cfg = self.transcript("s3", [f"curl -H 'x-api-key: {fake}' https://example.test"])
        calls = rb.tool_calls("s3", cfg)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(fake, calls[0][1])
        passed, note = rb.tool_called({"input": "curl"}, "s3", calls)
        self.assertTrue(passed)
        self.assertNotIn(fake, note)
        self.assertFalse(rb.tool_called({"input": fake}, "s3", calls)[0])   # a grader cannot match the secret either

    def test_grade_runs_a_tool_called_grader_from_the_runs_config_folder(self):
        import relay_bench as rb
        cfg = self.transcript("s4", ["python3 scratch.py"])
        scen = {"graders": [{"name": "ran", "type": "tool_called", "input": "python3"}]}
        out = rb.grade(scen, self.tmp, "I ran a script", "claude", "haiku", session_id="s4", config_dir=cfg)
        self.assertTrue(out[0]["passed"])
        out = rb.grade(scen, self.tmp, "python3 scratch.py", "claude", "haiku", session_id="s5", config_dir=cfg)
        self.assertFalse(out[0]["passed"])


class GradersFindTaskBranch(Base):
    """A worker builds on its own task branch and leaves the merge to the owner (relay's rules), so a grader that reads
    files looks at the workspace first and then at the task branches (bench 2026-10-30, judge-fable add-function)."""

    def workspace(self, scenario: str) -> str:
        ws = os.path.join(self.tmp, "ws")
        shutil.copytree(os.path.join(ROOT, "evals", "plugin", "fixture"), ws)
        subprocess.run(["bash", os.path.join(ROOT, "evals", "scenarios", scenario, "scaffold.sh")], cwd=ws, check=True,
                       capture_output=True)
        return ws

    def on_branch(self, ws: str, files: dict[str, str]) -> None:
        """Commit `files` on wt/remove-item, a worktree beside the workspace, and leave the workspace untouched."""
        wt = os.path.join(self.tmp, "remove-item")
        subprocess.run(["git", "-C", ws, "worktree", "add", "-q", "-b", "wt/remove-item", wt], check=True)
        for name, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(wt, name)), exist_ok=True)
            with open(os.path.join(wt, name), "w") as handle:
                handle.write(text)
        os.chmod(os.path.join(wt, "bin", "count"), 0o755) if "bin/count" in files else None
        subprocess.run(["git", "-C", wt, "add", "-A"], check=True)
        subprocess.run(["git", "-C", wt, "-c", "user.name=f", "-c", "user.email=f@x", "commit", "-qm", "work"], check=True)

    def grades(self, scenario: str, ws: str) -> dict[str, bool]:
        import relay_bench as rb
        scen = rb.load_scenario(scenario)
        scen["graders"] = [g for g in scen["graders"] if g["type"] == "command" and g["name"] != "tests-pass"]
        return {r["name"]: r["passed"] for r in rb.grade(scen, ws, "", "claude", "haiku")}

    def test_add_function_found_only_on_a_task_branch(self):
        ws = self.workspace("add-function")
        self.on_branch(ws, {"src/shelf.ts": "export function removeItem() {}\n", "src/shelf.test.ts": "test('removeItem', () => {})\n"})
        self.assertEqual(self.grades("add-function", ws), {"function-exists": True, "test-written": True})

    def test_add_function_absent_everywhere_fails(self):
        ws = self.workspace("add-function")
        self.on_branch(ws, {"README.txt": "nothing\n"})
        self.assertEqual(self.grades("add-function", ws), {"function-exists": False, "test-written": False})

    def test_small_script_found_only_on_a_task_branch(self):
        ws = self.workspace("small-script")
        self.on_branch(ws, {"bin/count": "#!/usr/bin/env bash\ngrep -c 'test(' \"$1\"\n"})
        self.assertEqual(self.grades("small-script", ws), {"script-runs": True})

    def test_small_script_absent_everywhere_fails(self):
        ws = self.workspace("small-script")
        self.on_branch(ws, {"README.txt": "nothing\n"})
        self.assertEqual(self.grades("small-script", ws), {"script-runs": False})


class ModulesPutBack(unittest.TestCase):
    def test_a_base_test_leaves_the_relay_modules_it_found(self):
        """Another test module holds the relay_* modules it imported (test_lanes_state: tq.rq and rl); a Base test that left
        fresh copies behind made a later lazy import see a second relay_queue, so `Refused` never matched (gate, 28 Oct)."""
        import relay_config  # noqa: F401  (puts the module in sys.modules for the snapshot)
        before = sys.modules["relay_config"]

        class Inner(Base):
            def test_it(self):
                import relay_config as fresh
                self.assertIsNot(fresh, before)   # the test itself runs on fresh modules

        result = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(unittest.defaultTestLoader.loadTestsFromTestCase(Inner))
        self.assertTrue(result.wasSuccessful())
        self.assertIs(sys.modules["relay_config"], before)


if __name__ == "__main__":
    unittest.main(verbosity=1)
