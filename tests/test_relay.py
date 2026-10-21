"""Library tests: transcripts, analysis, ledger, bench pipeline (fake claude), rules sync."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, HERE)

import fixtures  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="relay-test-")
        self.claude = os.path.join(self.tmp, "claude")
        self.home = os.path.join(self.tmp, "relay-home")
        os.makedirs(self.claude)
        os.environ["CLAUDE_CONFIG_DIR"] = self.claude
        os.environ["RELAY_HOME"] = self.home
        os.environ["RELAY_ROOT"] = ROOT
        projects = os.path.join(self.tmp, "projects.toml")
        shutil.copy(os.path.join(ROOT, "projects.toml"), projects)
        os.environ["RELAY_PROJECTS"] = projects
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Transcripts(Base):
    def test_session_and_agents_are_read(self):
        import relay_transcripts as tr
        fixtures.populate(self.claude)
        path = tr.session_path_for(self.claude, "s-alix-1018")
        main = tr.read_trace(path)
        self.assertEqual(main.total.requests, 3)
        self.assertEqual(main.user_turns, 3)
        self.assertEqual(main.agents_started.get("alix-worker"), 1)
        self.assertEqual(main.max_context, 50 + 160_000 + 5_000)
        agents = tr.session_agents(path)
        self.assertEqual([a.agent_type for a in agents], ["alix-worker", "general-purpose", "Explore", "alix-reviewer"])
        worker = agents[0]
        self.assertEqual(worker.total.requests, 12)
        self.assertEqual(worker.first_read, 15_050)
        self.assertEqual(agents[3].gaps_over_5m, 1)
        self.assertEqual(tr.context_tokens_of(path), 50 + 160_000 + 5_000)

    def test_duplicate_request_ids_count_once(self):
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "t.jsonl")
        line = fixtures.assistant("2026-10-18T09:00:00Z", "claude-sonnet-5", 100, 0, 10, "same")
        with open(path, "w") as handle:
            handle.write(json.dumps(line) + "\n" + json.dumps(line) + "\n")
        self.assertEqual(tr.read_trace(path).total.requests, 1)


class Analysis(Base):
    def test_report_and_findings(self):
        import relay_analyze
        base = fixtures.populate(self.claude)
        data = relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        self.assertEqual(len(data["sessions"]), 2)
        text = relay_analyze.report(data)
        self.assertIn("By agent type", text)
        self.assertIn("alix-worker", text)
        ids = {f["id"] for f in relay_analyze.findings(data)}
        self.assertIn("F1", ids)   # opus build agent
        self.assertIn("F2", ids)   # general-purpose
        self.assertIn("F5", ids)   # the 7-minute gap
        f1 = next(f for f in relay_analyze.findings(data) if f["id"] == "F1")
        self.assertGreater(f1["saving_usd"], 0)

    def test_compare_two_periods(self):
        import relay_analyze
        base = fixtures.populate(self.claude)
        a = relay_analyze.collect(self.claude, base - dt.timedelta(hours=1), base + dt.timedelta(hours=1))
        b = relay_analyze.collect(self.claude, base + dt.timedelta(hours=2), base + dt.timedelta(hours=5))
        text = relay_analyze.compare(a, b, "old", "new")
        self.assertIn("cost per turn", text)
        self.assertIn("opus share", text)

    def test_classify(self):
        import relay_analyze as ra
        self.assertEqual(ra.classify("sdd:worker"), "build")
        self.assertEqual(ra.classify("delegate:scout"), "look")
        self.assertEqual(ra.classify("general-purpose"), "general")
        self.assertEqual(ra.classify("delegate:critic"), "think")


class Ledger(Base):
    def test_running_agents_and_durations(self):
        import relay_ledger as rl
        rl.append({"ts": "2026-10-18T09:00:00Z", "event": "agent_start", "session_id": "s", "agent_id": "a", "agent_type": "delegate:worker"})
        rl.append({"ts": "2026-10-18T09:00:01Z", "event": "tool_pre", "session_id": "s", "agent_id": "a", "tool": "Bash", "tool_use_id": "t1"})
        rl.append({"ts": "2026-10-18T09:00:31Z", "event": "tool_post", "session_id": "s", "agent_id": "a", "tool": "Bash", "tool_use_id": "t1"})
        events = rl.read()
        self.assertEqual(list(rl.running_agents(events)), ["s"])
        self.assertEqual(rl.tool_durations(events)[0][2], 30.0)
        rl.append({"ts": "2026-10-18T09:01:00Z", "event": "agent_stop", "session_id": "s", "agent_id": "a"})
        self.assertEqual(rl.running_agents(rl.read()), {})


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
        import relay_bench as rb
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
        again = rb.load_profile(b["_path"])
        self.assertEqual(again["models"]["build"], "haiku")
        self.assertEqual(again["rules"]["load"], base["rules"]["load"])

    def test_candidate_with_plugin_copy_drives_agents_and_plugin_dir(self):
        import relay_bench as rb
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
        self.assertTrue(any(copied[0] == c for c in cmd), cmd)
        self.assertNotIn(os.path.join(root, "plugins", "delegate"), cmd)

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


class Rules(Base):
    def test_sync_writes_global_and_agents(self):
        import relay_config
        import relay_rules
        profile = relay_config.active_profile()
        results = relay_rules.sync(profile, only={"global", "agents"})
        states = {n: s for n, _, s in results}
        self.assertEqual(states["global"], "written")
        text = open(os.path.join(self.claude, "CLAUDE.md")).read()
        self.assertIn("Generated by relay", text)
        self.assertIn("## Delegation", text)
        self.assertIn("Rules to read when they apply", text)
        self.assertEqual(relay_rules.check(profile), [])

    def test_hand_written_file_is_not_overwritten(self):
        import relay_config
        import relay_rules
        with open(os.path.join(self.claude, "CLAUDE.md"), "w") as handle:
            handle.write("mine\n")
        with self.assertRaises(relay_rules.Fail):
            relay_rules.sync(relay_config.active_profile(), only={"global"})
        relay_rules.sync(relay_config.active_profile(), only={"global"}, adopt="global")
        self.assertTrue(os.path.isfile(os.path.join(self.claude, "CLAUDE.md.before-relay")))

    def test_profile_rewrites_tiered_agents_in_a_copy(self):
        import relay_rules
        copy = os.path.join(self.tmp, "agents")
        shutil.copytree(os.path.join(ROOT, "plugins", "sdd", "agents"), copy)
        os.environ["RELAY_ROOT"] = os.path.join(self.tmp, "empty-root")   # no plugins/ there: only extra_dirs are touched
        os.makedirs(os.path.join(self.tmp, "empty-root", "plugins"))
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]
        import relay_rules
        changed = relay_rules.sync_agents({"models": {"build": "haiku", "judge": "sonnet"}, "effort": {"judge": "xhigh"}}, extra_dirs=[copy])
        worker = open(os.path.join(copy, "worker.md")).read()
        reviewer = open(os.path.join(copy, "reviewer.md")).read()
        self.assertIn("model: haiku", worker)
        self.assertIn("model: sonnet", reviewer)
        self.assertIn("effort: xhigh", reviewer)
        self.assertTrue(any(p.endswith("worker.md") for p in changed))
        self.assertIn("model: sonnet", open(os.path.join(ROOT, "plugins", "sdd", "agents", "worker.md")).read())  # source untouched

    def test_set_frontmatter(self):
        import relay_rules
        text = "---\nname: x\nmodel: opus\n---\nbody\n"
        new = relay_rules.set_frontmatter(text, {"model": "sonnet", "effort": "low"})
        self.assertIn("model: sonnet", new)
        self.assertIn("effort: low", new)
        self.assertTrue(new.endswith("body\n"))


class Setup(Base):
    def test_setup_then_doctor(self):
        import relay_setup
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "go.mod"), "w").write("module x\n")
        d, flow, product, done, todo = relay_setup.setup(proj, flow="none", product=False)
        self.assertEqual(d["stack"], "go")
        self.assertTrue(os.path.isfile(os.path.join(proj, ".claude", "kit.toml")))
        settings = json.load(open(os.path.join(proj, ".claude", "settings.json")))
        self.assertTrue(settings["enabledPlugins"]["delegate@relay"])
        checks = relay_setup.doctor(proj, profile={})
        names = {n: ok for n, ok, _ in checks}
        self.assertTrue(names["project has .claude/kit.toml"])
        self.assertTrue(names["gate.check exists and is executable"])
        # idempotent
        d2, *_ = relay_setup.setup(proj, flow="none", product=False)
        self.assertTrue(d2["has_bindings"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
