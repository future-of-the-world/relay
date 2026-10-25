"""Library tests: the bench pipeline (fake claude)."""
import json
import os
import shutil
import sys

from relay_testbase import Base, ROOT


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


if __name__ == "__main__":
    unittest.main(verbosity=1)
