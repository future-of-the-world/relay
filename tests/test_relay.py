"""Library tests: transcripts, analysis, ledger, bench pipeline (fake claude), rules sync."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
        self.project_file = os.path.join(self.tmp, "demo", "CLAUDE.local.md")   # never the owner's real project files
        with open(projects, "w") as handle:
            handle.write('[global]\nfile = "~/.claude/CLAUDE.md"\ntitle = "Defaults for all projects"\nintro = "Test."\nload = []\n\n'
                         '[demo]\nfile = "%s"\ntitle = "Principles this project loads"\nload = ["quality-gate"]\nread = []\n' % self.project_file)
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

    def f1_ids(self, base):
        import relay_analyze
        window = (base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        return {f["id"] for f in relay_analyze.findings(relay_analyze.collect(self.claude, *window))}

    def test_escalated_build_agent_is_not_finding_f1(self):
        base = fixtures.populate(self.claude)
        self.assertIn("F1", self.f1_ids(base))
        shutil.rmtree(os.path.join(self.claude, "projects"))
        base = fixtures.populate(self.claude, prompts={0: "do it\nescalated: sonnet failed twice"})
        self.assertNotIn("F1", self.f1_ids(base))

    def test_refused_call_does_not_hand_its_flag_to_the_next_agent(self):
        """Today's shape: a refused Opus worker call (no agent), then the escalated retry. The ledger lists
        both calls and one agent start; the agent must get the retry's flag, whatever the ledger order."""
        import relay_ledger as rl
        base = fixtures.populate(self.claude, prompts={0: "do it\nEscalated: sonnet failed twice"})
        sid = "s-alix-" + base.strftime("%m%d")
        os.makedirs(rl.ledger_dir(), exist_ok=True)
        pre = {"event": "tool_pre", "session_id": sid, "tool": "Agent", "subagent_type": "alix-worker", "prompt_chars": 40}
        with open(os.path.join(rl.ledger_dir(), "2026-10-18.jsonl"), "w") as handle:
            for ts, extra in (("2026-10-18T09:11:00Z", {"escalated": False}), ("2026-10-18T09:11:01Z", {"escalated": True})):
                handle.write(json.dumps(dict(pre, ts=ts, **extra)) + "\n")
            handle.write(json.dumps({"ts": "2026-10-18T09:11:02Z", "event": "agent_start", "session_id": sid,
                                     "agent_id": "a0", "agent_type": "alix-worker"}) + "\n")
        self.assertNotIn("F1", self.f1_ids(base))

    def test_agent_calls_are_paired_to_agents_by_id(self):
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "m.jsonl")
        call = lambda i, prompt, kind="delegate:worker": fixtures.assistant(
            "2026-10-18T09:00:0%dZ" % i, "claude-opus-5", 1, 0, 1, "r%d" % i, tools=[("Agent", {"subagent_type": kind, "prompt": prompt})])
        lines = [call(1, "refused, no Escalated line"),                      # tu_r1_0: refused, never answered with an agent
                 fixtures.tool_result("2026-10-18T09:00:02Z", "tu_r1_0"),
                 call(3, "plain work\nEscalated:"),                          # tu_r3_0: reason missing, so not escalated
                 call(4, "x\n  escalated: failed twice"),                    # tu_r4_0: escalated
                 fixtures.tool_result("2026-10-18T09:00:05Z", "tu_r4_0", "second"),   # results arrive in the other order
                 fixtures.tool_result("2026-10-18T09:00:06Z", "tu_r3_0", "first")]
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        briefs = tr.read_trace(path).agent_briefs
        self.assertEqual(sorted(briefs), ["first", "second"])
        self.assertFalse(briefs["first"]["escalated"])
        self.assertTrue(briefs["second"]["escalated"])
        self.assertEqual(briefs["first"]["prompt_chars"], len("plain work\nEscalated:"))

    def test_notifications_are_not_owner_turns(self):
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "n.jsonl")
        notice = fixtures.user("2026-10-18T09:01:00Z", "<task-notification>agent done</task-notification>")
        notice["origin"] = {"kind": "task-notification"}
        peer = dict(fixtures.user("2026-10-18T09:02:00Z", "<agent-message from=a>hi</agent-message>"), isMeta=True, origin={"kind": "peer"})
        owner_quotes = "the hook still fires on <task-notification> prompts, fix it"
        lines = [fixtures.user("2026-10-18T09:00:00Z", "please do it"), notice, peer,
                 fixtures.user("2026-10-18T09:03:00Z", "[SYSTEM NOTIFICATION: background agent finished]"),
                 fixtures.user("2026-10-18T09:04:00Z", "<task-notification>no origin field</task-notification>"),
                 dict(fixtures.user("2026-10-18T09:05:00Z", "summary " * 100), isCompactSummary=True),
                 fixtures.user("2026-10-18T09:06:00Z", owner_quotes)]
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        trace = tr.read_trace(path)
        self.assertEqual(trace.user_turns, 2)
        self.assertEqual(trace.prompt_chars, len("please do it") + len(owner_quotes))

    def test_your_turns_count_only_what_the_owner_typed(self):
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "t.jsonl")
        typed = dict(fixtures.user("2026-10-18T09:00:00Z", "please do it"), origin={"kind": "human"}, promptSource="typed")
        accepted = dict(fixtures.user("2026-10-18T09:00:30Z", "yes"), origin={"kind": "human"}, promptSource="suggestion_accepted")
        lines = [typed, accepted,
                 fixtures.user("2026-10-18T09:01:00Z", "[Request interrupted by user]"),
                 fixtures.user("2026-10-18T09:01:30Z", "[Request interrupted by user for tool use]"),
                 # a real /clear: the command line, then a system line, then the next typed prompt; no output line, no reply
                 fixtures.user("2026-10-18T09:02:00Z", "<command-name>/clear</command-name>\n            <command-message>clear</command-message>\n            <command-args></command-args>"),
                 {"type": "system", "timestamp": "2026-10-18T09:02:05Z", "content": "cleared"},
                 dict(fixtures.user("2026-10-18T09:02:08Z", "now the next thing"), origin={"kind": "human"}, promptSource="typed"),
                 fixtures.user("2026-10-18T09:02:10Z", "<local-command-caveat>Caveat: the messages below were generated by the user while running local commands.</local-command-caveat>"),
                 fixtures.user("2026-10-18T09:02:20Z", "<local-command-stdout>Total cost: $1</local-command-stdout>"),
                 fixtures.user("2026-10-18T09:02:30Z", "<bash-input>ls</bash-input>"),
                 fixtures.user("2026-10-18T09:02:40Z", "<bash-stdout>a b</bash-stdout><bash-stderr></bash-stderr>"),
                 dict(fixtures.user("2026-10-18T09:03:00Z", "<task-notification>done</task-notification>"), origin={"kind": "task-notification"}),
                 dict(fixtures.user("2026-10-18T09:03:30Z", "something the system injected"), origin={"kind": "system"}),
                 fixtures.user("2026-10-18T09:04:00Z", "<command-message>opsx:apply</command-message>\n<command-name>/opsx:apply</command-name>\n<command-args>x</command-args>"),
                 fixtures.assistant("2026-10-18T09:04:30Z", "claude-opus-5-5", 10, 10, 5, "req9", text="ok")]
        # harness screens the old fixed list did not know: recognised by the output line that answers them
        for n, name in enumerate(("rate-limit-options", "usage-credits", "some-future-screen")):
            lines.append(fixtures.user("2026-10-18T09:05:%02dZ" % (n * 10), "<command-name>/%s</command-name>\n<command-message>%s</command-message>" % (name, name)))
            lines.append(fixtures.user("2026-10-18T09:05:%02dZ" % (n * 10 + 5), "<local-command-stdout>screen</local-command-stdout>"))
        # a program's prompt (headless run): promptSource "sdk", no origin
        lines.append(dict(fixtures.user("2026-10-18T09:06:00Z", "run the benchmark"), promptSource="sdk"))
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        self.assertEqual(tr.read_trace(path).user_turns, 4)      # the typed text, the accepted suggestion, the prompt after /clear, /opsx:apply (answered)

    def test_a_command_that_runs_a_prompt_is_a_turn_when_the_model_answers(self):
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "t.jsonl")
        lines = [fixtures.user("2026-10-18T09:00:00Z", "<command-name>/brand-new:thing</command-name>\n<command-args>x</command-args>"),
                 fixtures.assistant("2026-10-18T09:00:05Z", "claude-opus-5-5", 10, 10, 5, "req1", text="ok")]
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        self.assertEqual(tr.read_trace(path).user_turns, 1)

    def test_a_command_answered_after_a_background_notice_is_still_a_turn(self):
        # real shape: /list-agents, a task-notification (and a system line), then the model's reply
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "t.jsonl")
        lines = [fixtures.user("2026-10-18T09:00:00Z", "<command-name>/list-agents</command-name>\n<command-args></command-args>"),
                 dict(fixtures.user("2026-10-18T09:00:02Z", "<task-notification>agent done</task-notification>"), origin={"kind": "task-notification"}),
                 dict(fixtures.user("2026-10-18T09:00:03Z", "injected by the system"), origin={"kind": "system"}, promptSource="system"),
                 fixtures.assistant("2026-10-18T09:00:05Z", "claude-opus-5-5", 10, 10, 5, "req1", text="here are the agents"),
                 # a command cut off by the owner's next typed line stays not a turn
                 fixtures.user("2026-10-18T09:01:00Z", "<command-name>/clear</command-name>"),
                 dict(fixtures.user("2026-10-18T09:01:05Z", "<task-notification>x</task-notification>"), origin={"kind": "task-notification"}),
                 dict(fixtures.user("2026-10-18T09:01:10Z", "next thing"), origin={"kind": "human"}, promptSource="typed")]
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        self.assertEqual(tr.read_trace(path).user_turns, 2)    # /list-agents (answered) and "next thing"

    def test_scripted_sessions_are_counted_apart_from_your_turns(self):
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "t.jsonl")
        lines = [dict(fixtures.user("2026-10-18T09:00:00Z", "please do it " * 60), entrypoint="sdk-cli", promptSource="sdk"),
                 dict(fixtures.user("2026-10-18T09:01:00Z", "and then this"), entrypoint="sdk-cli")]
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        trace = tr.read_trace(path)
        self.assertEqual((trace.user_turns, trace.scripted_turns, trace.scripted, trace.prompt_chars), (0, 1, True, 0))

    def test_escalated_rule_is_one_rule(self):
        import relay_transcripts as tr
        self.assertTrue(tr.is_escalated("a\nEscalated: x"))
        self.assertTrue(tr.is_escalated("a\n  escalated: x"))
        self.assertFalse(tr.is_escalated("Escalated:"))
        self.assertFalse(tr.is_escalated("Not Escalated: here"))

    def test_handback_length_is_read_from_the_agent_transcript(self):
        import relay_transcripts as tr
        path = os.path.join(self.tmp, "a.jsonl")
        lines = [fixtures.assistant("2026-10-18T09:00:00Z", "claude-haiku-5", 1, 0, 1, "r1", text="plain text " * 100)]
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        self.assertIsNone(tr.read_trace(path).handback_chars)
        lines.append(fixtures.assistant("2026-10-18T09:00:01Z", "claude-haiku-5", 1, 0, 1, "r2",
                                        tools=[("SubagentHandback", {"message": "DONE: 3 files"})]))
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        self.assertEqual(tr.read_trace(path).handback_chars, len("DONE: 3 files"))

    def test_toml_fallback_reads_what_tomllib_reads(self):
        import glob
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11; the fallback is what runs there")
        import relay_toml
        for path in glob.glob(os.path.join(ROOT, "*.toml")) + glob.glob(os.path.join(ROOT, "profiles", "*.toml")):
            with open(path, "rb") as handle:
                text = handle.read().decode()
            self.assertEqual(relay_toml._loads(text), tomllib.loads(text), path)
        sample = 'a = 1\nb = [1, "x", [2.5]]\n[t.u]\nk = "v # not a comment" # comment\ni = {x = 1, y = true}\n[[arr]]\nn = 1\n[[arr]]\nn = 2\n'
        self.assertEqual(relay_toml._loads(sample), tomllib.loads(sample))

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


    def test_agent_stopped_twice_is_one_span(self):
        import relay_ledger as rl
        ev = [
            {"event": "agent_start", "session_id": "s", "agent_id": "a", "agent_type": "delegate:scout"},
            {"event": "agent_stop", "session_id": "s", "agent_id": "a", "agent_type": "delegate:scout", "requests": 5},
            {"event": "agent_stop", "session_id": "s", "agent_id": "a", "agent_type": "delegate:scout", "requests": 6},
        ]
        self.assertEqual(len(rl.agent_spans(ev)), 1)


class Numbers(Base):
    """Trustworthy numbers: prices, agent snapshots, Claude Code's own totals."""

    # Claude Code's own per-model totals for one session (what /cost showed), as numbers only.
    SESSION_8_43 = {
        "claude-opus-5-5": dict(input_tokens=56_500, output_tokens=118_400, cache_read_input_tokens=11_200_000,
                                cache_creation_input_tokens=383_100, one_hour=80_000, cost=6.99),
        "claude-sonnet-5-5": dict(input_tokens=32_700, output_tokens=48_700, cache_read_input_tokens=4_300_000,
                                  cache_creation_input_tokens=180_700, one_hour=0, cost=1.43),
        "claude-haiku-5-5": dict(input_tokens=1_200, output_tokens=1_900, cache_read_input_tokens=32_700,
                                 cache_creation_input_tokens=13_900, one_hour=0, cost=0.00313),
    }

    def test_prices_reproduce_cost_within_one_percent(self):
        import relay_prices
        total = 0.0
        for model, row in self.SESSION_8_43.items():
            usage = {k: row[k] for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
            usage["cache_creation"] = {"ephemeral_1h_input_tokens": row["one_hour"]}
            got = relay_prices.cost(model, usage)
            self.assertAlmostEqual(got / row["cost"], 1.0, delta=0.01, msg=model)
            total += got
        self.assertAlmostEqual(total / 8.43, 1.0, delta=0.01)

    def test_main_only_opus_sessions_price_within_a_tenth_of_a_percent(self):
        import relay_prices
        # (input, output, cache read, cache write, costUSD): Claude Code's totals; the main thread writes for 1 hour
        sessions = [
            (34, 5683, 1_053_863, 46_711, 0.6982566), (126, 7406, 973_181, 46_161, 0.7125482),
            (4, 2031, 69_960, 19_252, 0.208644), (102, 41_505, 5_020_358, 141_392, 2.9657156),
            (728, 11_061, 873_270, 42_492, 0.738722), (96, 147_804, 8_365_862, 214_728, 6.3474604),
        ]
        for i, o, cr, cw, want in sessions:
            usage = {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw,
                     "cache_creation": {"ephemeral_1h_input_tokens": cw}}
            self.assertAlmostEqual(relay_prices.cost("claude-opus-5-5", usage) / want, 1.0, delta=0.001)

    def test_one_hour_writes_cost_eight_not_five(self):
        import relay_prices
        hour = {"cache_creation_input_tokens": 1_000_000, "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}}
        five = {"cache_creation_input_tokens": 1_000_000, "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 0}}
        self.assertAlmostEqual(relay_prices.cost("claude-opus-5-5", hour), 8.0)
        self.assertAlmostEqual(relay_prices.cost("claude-opus-5-5", five), 5.0)
        self.assertAlmostEqual(relay_prices.cost("claude-opus-5-5", {"cache_creation_input_tokens": 1_000_000}), 5.0)
        # reads differ 20x between models, ratios inside a model do not
        self.assertAlmostEqual(relay_prices.cost("claude-haiku-5-5", {"cache_read_input_tokens": 1_000_000}), 0.01)
        self.assertAlmostEqual(relay_prices.cost("claude-haiku-4-5", {"cache_read_input_tokens": 1_000_000}), 0.10)
        self.assertEqual(relay_prices.tier("claude-haiku-4-5-20251001"), "haiku-4-5")

    def _agent_session(self, final_output):
        """A main session plus one Sonnet agent whose only request was written in two mid-stream lines."""
        import fixtures
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        fixtures.write_session(self.claude, "-Users-me-x", "s-snap", base, [("delegate:worker", "claude-sonnet-5-5", 1, 1)])
        path = os.path.join(self.claude, "projects", "-Users-me-x", "s-snap", "subagents", "agent-a0.jsonl")
        first = fixtures.assistant("2026-10-21T09:12:00.000Z", "claude-sonnet-5-5", 0, 15_000, 16, "req-1",
                                   tools=[("Bash", {"command": "x" * 400})], sidechain=True)
        second = fixtures.assistant("2026-10-21T09:12:01.000Z", "claude-sonnet-5-5", 0, 15_000, 40, "req-1",
                                    text="y" * 100, sidechain=True)
        with open(path, "w") as handle:
            for line in (first, second):
                handle.write(json.dumps(line) + "\n")
        return os.path.join(self.claude, "projects", "-Users-me-x", "s-snap.jsonl")

    def test_agent_output_is_not_the_mid_answer_snapshot(self):
        import relay_transcripts as tr
        self._agent_session(None)
        agent = tr.session_agents(os.path.join(self.claude, "projects", "-Users-me-x", "s-snap.jsonl"))[0]
        # visible: json of the tool input 13 + 400 + 2 = 415 characters, plus 100 of text = 515; x 0.62 = 319.3
        self.assertEqual(agent.total.usage["output_tokens"], 319)
        self.assertTrue(agent.total.estimated)
        self.assertEqual(agent.total.requests, 1)

    def test_recorded_count_wins_when_larger_than_the_guess(self):
        import relay_transcripts as tr
        self._agent_session(None)
        path = os.path.join(self.claude, "projects", "-Users-me-x", "s-snap", "subagents", "agent-a0.jsonl")
        with open(path, "a") as handle:
            import fixtures
            handle.write(json.dumps(fixtures.assistant("2026-10-21T09:12:02.000Z", "claude-sonnet-5-5", 0, 15_000, 5000, "req-1", sidechain=True)) + "\n")
        agent = tr.session_agents(os.path.join(self.claude, "projects", "-Users-me-x", "s-snap.jsonl"))[0]
        self.assertEqual(agent.total.usage["output_tokens"], 5000)

    def _claude_json(self, session_id):
        models = {}
        for model, row in self.SESSION_8_43.items():
            models[model] = {"inputTokens": row["input_tokens"], "outputTokens": row["output_tokens"], "thinkingTokens": 0,
                             "cacheReadInputTokens": row["cache_read_input_tokens"],
                             "cacheCreationInputTokens": row["cache_creation_input_tokens"], "webSearchRequests": 0,
                             "costUSD": row["cost"]}
        with open(os.path.join(self.claude, ".claude.json"), "w") as handle:
            json.dump({"projects": {"/Users/me/x": {"lastSessionId": session_id, "lastModelUsage": models}}}, handle)
        stamp = dt.datetime(2026, 10, 22, tzinfo=dt.timezone.utc).timestamp()      # written after the session ended
        os.utime(os.path.join(self.claude, ".claude.json"), (stamp, stamp))

    def test_report_uses_claude_codes_totals_when_present(self):
        import relay_analyze
        import relay_ledger
        self._agent_session(None)
        self._claude_json("s-snap")
        relay_ledger.capture("2026-10-21T10:00:00Z")        # seen after the session's last activity (09:12)
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        text = relay_analyze.report(relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1)))
        sonnet = next(line for line in text.splitlines() if line.startswith("claude-sonnet-5-5"))
        self.assertIn("49k", sonnet)            # 48,700 exact output tokens, not the snapshot's few hundred
        self.assertIn("$1.43", sonnet)
        self.assertIn("exact", sonnet)
        self.assertIn("exact for 100% of usage", text)
        self.assertIn("$8.42", text)            # 6.99 + 1.43 + 0.00313 = 8.42313; /cost rounds its unrounded sums to 8.43
        self.assertIn("Claude Code helpers (no transcript)", text)

    def test_capture_does_not_write_a_total_smaller_than_the_recorded_one(self):
        """If Claude Code restarts its counter on resume, the new total covers only the resumed part: it must
        not replace the bigger one already recorded (it would be labelled exact for the whole session)."""
        import relay_ledger
        self.SESSION_8_43["claude-opus-5-5"]["cost"] = 9.0
        try:
            self._claude_json("s-r")
        finally:
            self.SESSION_8_43["claude-opus-5-5"]["cost"] = 6.99
        self.assertEqual(relay_ledger.capture("2026-10-21T09:00:00Z"), ["s-r"])
        self._claude_json("s-r")                                   # now 6.99: smaller than the 9.00 recorded
        self.assertEqual(relay_ledger.capture("2026-10-21T10:00:00Z"), [])
        self.assertEqual(relay_ledger.usage_sessions()["s-r"]["claude-opus-5-5"]["cost_usd"], 9.0)
        os.remove(os.path.join(self.home, "ledger", "usage-index.json"))     # the index is a shortcut, not the truth
        self.assertEqual(relay_ledger.capture("2026-10-21T10:01:00Z"), [])

    def test_a_restarted_counter_that_grows_past_the_old_total_stays_an_estimate(self):
        """First part 9.00; the resumed part restarts at 0, is seen at 4.00 (smaller: not written, session marked),
        then grows to 12.00. A plain 'grew' rule would write 12.00 and label a 21.00 session exact; it must not."""
        import relay_ledger
        for cost, when in ((9.0, "09:00"), (4.0, "10:00"), (12.0, "11:00")):
            self.SESSION_8_43["claude-opus-5-5"]["cost"] = cost
            try:
                self._claude_json("s-g")
            finally:
                self.SESSION_8_43["claude-opus-5-5"]["cost"] = 6.99
            written = relay_ledger.capture("2026-10-21T%s:00Z" % when)
            self.assertEqual(written, ["s-g"] if cost == 9.0 else [])
        self.assertEqual(relay_ledger.usage_sessions()["s-g"]["claude-opus-5-5"]["cost_usd"], 9.0)
        self.assertNotIn("s-g", relay_ledger.exact_sessions())          # never exact again, not even the 12.00 in the file
        os.remove(os.path.join(self.home, "ledger", "usage-index.json"))
        self.assertEqual(relay_ledger.capture("2026-10-21T12:00:00Z"), [])

    def test_the_usage_index_keeps_every_entry_under_concurrent_writers(self):
        """30 SessionEnd hooks at once used to keep 12 to 26 of 30 index entries (read-modify-write, shared temp)."""
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import relay_ledger as l; "
                "l.record_usage(sys.argv[1], '/p', {'m': {'output_tokens': 1}}, '2026-10-21T09:00:00Z')" % os.path.join(ROOT, "lib"))
        env = dict(os.environ, RELAY_HOME=self.home)
        procs = [subprocess.Popen([sys.executable, "-c", code, "s%02d" % n], env=env) for n in range(30)]
        for proc in procs:
            self.assertEqual(proc.wait(), 0)
        import relay_ledger
        with open(os.path.join(self.home, "ledger", "usage-index.json")) as handle:
            index = json.load(handle)
        self.assertEqual(len(index.get("sessions", index)), 30)
        self.assertEqual(len(relay_ledger.usage_sessions()), 30)

    def test_capture_never_reads_the_whole_ledger(self):
        import relay_ledger
        self._claude_json("s-n4")
        real = relay_ledger.read

        def bounded(since=None, until=None):
            if since is None:
                raise AssertionError("capture read the whole ledger")
            return real(since=since, until=until)
        relay_ledger.read = bounded
        try:
            self.assertEqual(relay_ledger.capture("2026-10-21T10:00:00Z"), ["s-n4"])
            self.assertEqual(relay_ledger.capture("2026-10-21T10:01:00Z"), [])
        finally:
            relay_ledger.read = real

    def test_capture_with_a_readable_index_never_reads_the_ledger(self):
        """The index is trusted when it can be read: not in "sessions" = not recorded, not in "restarted" = not
        restarted. The ledger is read only when the index is missing (the day files of the last 3 days)."""
        import relay_ledger
        self._claude_json("s-trust")
        real = relay_ledger.read
        index_file = os.path.join(self.home, "ledger", "usage-index.json")

        def guarded(since=None, until=None):
            if os.path.exists(index_file):
                raise AssertionError("capture read the ledger although the index exists")
            return real(since=since, until=until)
        relay_ledger.read = guarded
        try:
            self.assertEqual(relay_ledger.capture("2026-10-21T10:00:00Z"), ["s-trust"])   # new session
            self.assertEqual(relay_ledger.capture("2026-10-21T10:01:00Z"), [])            # recorded session
            with open(index_file, "w") as handle:
                handle.write("{not json")                                                  # corrupt: ledger fallback
            relay_ledger.read = real
            self.assertEqual(relay_ledger.capture("2026-10-21T10:02:00Z"), [])
        finally:
            relay_ledger.read = real

    def test_session_end_hook_is_fast_on_a_large_ledger(self):
        """SessionEnd has a 1 s timeout; the ledger grows without limit. 300,000 old lines must cost nothing."""
        import subprocess
        self._claude_json("s-end")
        ledger = os.path.join(self.home, "ledger")
        os.makedirs(ledger)
        line = json.dumps({"ts": "2026-06-01T10:00:00.000Z", "event": "tool_post", "session_id": "old", "cwd": "/p",
                           "tool": "Bash", "tool_use_id": "x" * 40}) + "\n"
        for day in range(1, 31):
            with open(os.path.join(ledger, "2026-06-%02d.jsonl" % day), "w") as handle:
                handle.write(line * 10000)
        # the days the old code did read (today and the 3 before), 100,000 lines each, and an index
        recent = line.replace("2026-06-01", "2026-10-21")
        for back in range(4):
            day = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=back)).strftime("%Y-%m-%d")
            with open(os.path.join(ledger, day + ".jsonl"), "a") as handle:
                handle.write(recent * 100000)
        with open(os.path.join(ledger, "usage-index.json"), "w") as handle:
            json.dump({"sessions": {}, "restarted": []}, handle)
        env = dict(os.environ, RELAY_CLAUDE_JSON=os.path.join(self.claude, ".claude.json"))
        hook = os.path.join(ROOT, "plugins", "observe", "hooks", "ledger.py")
        payload = json.dumps({"hook_event_name": "SessionEnd", "session_id": "s-end", "cwd": "/Users/me/x", "reason": "other"})
        started = time.monotonic()
        subprocess.run([sys.executable, hook], input=payload.encode(), env=env, check=True)
        took = time.monotonic() - started
        self.assertLess(took, 0.3, "SessionEnd hook took %.2f s on a 700,000-line ledger" % took)
        text = "".join(open(os.path.join(ledger, f)).read() for f in os.listdir(ledger) if not f.startswith("2026-06") and f.endswith(".jsonl"))
        self.assertIn('"event": "session_end"', text)
        self.assertIn('"event": "session_usage"', text)

    def test_report_without_totals_says_estimate_with_its_error(self):
        import relay_analyze
        self._agent_session(None)
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        text = relay_analyze.report(relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1)))
        self.assertIn("exact for 0% of usage", text)
        self.assertIn("estimate", text)
        self.assertIn("Known error", text)

    def test_capture_copies_totals_once_and_skips_the_running_session(self):
        import relay_ledger
        self._claude_json("s-old")
        self.assertEqual(relay_ledger.capture("2026-10-21T10:00:00Z", folder="/Users/me/x", skip_session="s-old"), [])
        self.assertEqual(relay_ledger.capture("2026-10-21T10:00:00Z", folder="/Users/me/other"), [])
        self.assertEqual(relay_ledger.capture("2026-10-21T10:00:00Z", folder="/Users/me/x", skip_session="s-new"), ["s-old"])
        self.assertEqual(relay_ledger.capture("2026-10-21T10:05:00Z", folder="/Users/me/x", skip_session="s-new"), [])
        lines = [e for e in relay_ledger.read() if e["event"] == "session_usage"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["models"]["claude-opus-5-5"]["output_tokens"], 118_400)
        self.assertEqual(lines[0]["models"]["claude-opus-5-5"]["cost_usd"], 6.99)
        self.assertEqual(sorted(lines[0]["models"]["claude-haiku-5-5"]), sorted(
            ["input_tokens", "output_tokens", "thinking_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
             "web_search_requests", "cost_usd"]))

    def test_report_known_error_comes_from_the_last_calibrate_run(self):
        import relay_analyze
        self._agent_session(None)
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        window = (self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        text = relay_analyze.report(relay_analyze.collect(*window))
        self.assertIn("not measured yet; run relay calibrate", text)
        self.assertNotIn("36%", text)
        relay_analyze._save_calibration({"measured": "2026-10-21", "estimate": {
            "with_agents": {"n": 7, "median": 0.05, "worst": 0.31, "worst_signed": -0.31, "over_10": 2}}})
        text = relay_analyze.report(relay_analyze.collect(*window))
        self.assertNotIn("not measured yet", text)
        self.assertIn("sessions with agents: median 5%, worst 31% low, 2 of 7 over 10% off", text)

    def _opus_session(self, n, miss=1.0):
        """A transcript-only Opus session `n` and Claude Code's total for it: the cost the prices give, divided by `miss`."""
        import fixtures
        import relay_prices
        base = dt.datetime(2026, 10, 21, 8, 0, tzinfo=dt.timezone.utc)
        fixtures.write_session(self.claude, f"-Users-me-p{n}", f"s-cal{n}", base, [])
        usage = {"input_tokens": 150, "cache_read_input_tokens": 420_000, "cache_creation_input_tokens": 15_000, "output_tokens": 1200}
        return {"inputTokens": 150, "outputTokens": 1200, "thinkingTokens": 0, "cacheReadInputTokens": 420_000,
                "cacheCreationInputTokens": 15_000, "webSearchRequests": 0,
                "costUSD": relay_prices.cost("claude-opus-5", usage) / miss}

    def test_calibrate_reports_median_and_worst_and_stores_them(self):
        import relay_analyze
        projects = {}
        for n in range(5):
            projects[f"/Users/me/p{n}"] = {"lastSessionId": f"s-cal{n}", "lastModelUsage": {"claude-opus-5": self._opus_session(n)}}
        projects["/Users/me/p5"] = {"lastSessionId": "s-cal5", "lastModelUsage": {"claude-opus-5": self._opus_session(5, miss=1.5)}}
        # inside the 5-minute..1-hour range (a band check sees no error) yet 13% below what the transcript's own split prices
        projects["/Users/me/p6"] = {"lastSessionId": "s-cal6", "lastModelUsage": {"claude-opus-5": self._opus_session(6, miss=1 / 1.15)}}
        # a session with no transcript on this machine: priced against the 5-minute..1-hour range
        projects["/Users/me/gone"] = {"lastSessionId": "s-gone", "lastModelUsage": {"claude-opus-5": {
            "inputTokens": 100, "outputTokens": 1000, "thinkingTokens": 0, "cacheReadInputTokens": 100_000,
            "cacheCreationInputTokens": 10_000, "webSearchRequests": 0, "costUSD": 0.10}}}
        with open(os.path.join(self.claude, ".claude.json"), "w") as handle:
            json.dump({"projects": projects}, handle)
        text = relay_analyze.calibrate(self.claude, "2026-10-21T12:00:00Z")
        line = next(l for l in text.splitlines() if l.startswith("  opus:"))
        self.assertIn("median 0.00%", line)
        self.assertIn("worst +50.0%", line)         # the one large miss must show, not hide behind the median
        self.assertIn("2 of 8 over 10% off", line)
        self.assertIn("7 transcript", line)
        self.assertIn("1 band", line)
        self.assertIn("WARNING", line)
        stored = relay_analyze.load_calibration()
        self.assertEqual(stored["prices"]["opus"]["over_10"], 2)
        self.assertAlmostEqual(stored["prices"]["opus"]["worst"], 0.5)
        self.assertIn("estimate", stored)
        self.assertEqual(len([e for e in __import__('relay_ledger').read() if e["event"] == "session_usage"]), 8)

    def test_resumed_session_keeps_the_newest_total_and_is_an_estimate_until_then(self):
        import relay_analyze
        import relay_ledger
        self._agent_session(None)
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        window = (self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        self._claude_json("s-snap")
        self.assertEqual(relay_ledger.capture("2026-10-21T09:05:00Z"), ["s-snap"])     # copied before the session ended
        self.assertEqual(relay_ledger.capture("2026-10-21T09:06:00Z"), [])             # same total: nothing new
        text = relay_analyze.report(relay_analyze.collect(*window))     # claude.json stays, with a fresh mtime
        self.assertIn("exact for 0% of usage", text)                   # the transcript runs past the copied total
        # the owner resumed the session: Claude Code writes the bigger total again
        self.SESSION_8_43["claude-opus-5-5"]["cost"] = 9.0
        try:
            self._claude_json("s-snap")
        finally:
            self.SESSION_8_43["claude-opus-5-5"]["cost"] = 6.99
        self.assertEqual(relay_ledger.capture("2026-10-21T10:00:00Z"), ["s-snap"])
        self.assertEqual(relay_ledger.usage_sessions()["s-snap"]["claude-opus-5-5"]["cost_usd"], 9.0)
        text = relay_analyze.report(relay_analyze.collect(*window))
        self.assertIn("exact for 100% of usage", text)
        self.assertIn("$10.43", text)       # 9.00 + 1.43 + 0.00313: the newest line, not the first

    def test_claude_json_alone_never_makes_a_total_exact(self):
        """Claude Code rewrites ~/.claude.json all the time, so its mtime is no proof; a total only in that file
        (a resumed session's stale one, or a closed one not yet copied) is an estimate until the ledger holds it."""
        import relay_analyze
        import relay_ledger
        self._agent_session(None)
        self._claude_json("s-snap")
        p = os.path.join(self.claude, ".claude.json")
        stamp = dt.datetime(2026, 10, 21, 9, 21, 30, tzinfo=dt.timezone.utc).timestamp()     # 18 s after the last activity
        os.utime(p, (stamp, stamp))
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        window = (self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        text = relay_analyze.report(relay_analyze.collect(*window))
        self.assertIn("exact for 0% of usage", text)
        self.assertNotIn("$8.42", text)
        # the session ended (09:12 was its last line) and its hook copied the total: now it is exact
        self.assertEqual(relay_ledger.capture("2026-10-21T09:30:00Z", only_session="s-snap"), ["s-snap"])
        text = relay_analyze.report(relay_analyze.collect(*window))
        self.assertIn("exact for 100% of usage", text)
        self.assertIn("$8.42", text)

    def test_resume_start_copies_the_old_total_so_the_resumed_work_makes_it_an_estimate(self):
        import relay_analyze
        import relay_ledger
        self._agent_session(None)
        self._claude_json("s-snap")                                  # A closed earlier with this total
        # the owner resumes A at 09:30: the hook copies the stale total (not skipping the resumed session)
        self.assertEqual(relay_ledger.capture("2026-10-21T09:30:00Z", folder="/Users/me/x"), ["s-snap"])
        # A works on until 09:40, claude.json is rewritten meanwhile by other sessions
        import fixtures
        path = os.path.join(self.claude, "projects", "-Users-me-x", "s-snap.jsonl")
        with open(path, "a") as handle:
            handle.write(json.dumps(fixtures.assistant("2026-10-21T09:40:00.000Z", "claude-opus-5-5", 10, 1000, 200, "req-late")) + "\n")
        self._claude_json("s-snap")
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        text = relay_analyze.report(relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1)))
        self.assertIn("exact for 0% of usage", text)

    def _late_turn(self, ts, out):
        import fixtures
        path = os.path.join(self.claude, "projects", "-Users-me-x", "s-snap.jsonl")
        with open(path, "a") as handle:
            handle.write(json.dumps(fixtures.assistant(ts, "claude-opus-5-5", 10, 1000, out, "req-late")) + "\n")

    def test_resume_then_work_seconds_later_is_still_an_estimate(self):
        import relay_analyze
        import relay_ledger
        self._agent_session(None)
        self._claude_json("s-snap")
        relay_ledger.capture("2026-10-21T09:30:00Z", folder="/Users/me/x")      # resume copies the stale total
        self._late_turn("2026-10-21T09:30:45.000Z", 60000)                       # 45 s later: no tolerance window
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        text = relay_analyze.report(relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1)))
        self.assertIn("exact for 0% of usage", text)
        self.assertNotIn("$8.42", text)

    def test_calibrate_leaves_out_sessions_that_went_on_after_their_total(self):
        import relay_analyze
        import relay_ledger
        self._agent_session(None)
        self._claude_json("s-snap")
        relay_ledger.capture("2026-10-21T09:30:00Z", folder="/Users/me/x")
        self._late_turn("2026-10-21T09:40:00.000Z", 200000)
        text = relay_analyze.calibrate(self.claude, "2026-10-21T09:41:00Z")
        self.assertEqual(relay_analyze.load_calibration()["estimate"], {})
        self.assertIn("1 skipped (not covered", text)

    def test_calibration_file_of_another_shape_does_not_crash_the_report(self):
        import relay_analyze
        self._agent_session(None)
        base = dt.datetime(2026, 10, 21, 9, 0, tzinfo=dt.timezone.utc)
        window = (self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        for data in ({"estimate": {"with_agents": {"median": 0.05}}}, {"estimate": {"with_agents": 1}}, [], {"estimate": []},
                     {"estimate": {"with_agents": {"median": "0.05", "worst_signed": -0.1, "over_10": 0, "n": 1}}}):
            relay_analyze._save_calibration(data)
            text = relay_analyze.report(relay_analyze.collect(*window))
            self.assertIn("not measured yet; run relay calibrate", text, msg=json.dumps(data))
        relay_analyze._save_calibration({"measured": "2026-10-21", "estimate": {}})
        text = relay_analyze.report(relay_analyze.collect(*window))
        self.assertIn("no session had both a transcript and a total", text)

    def test_calibrate_stores_the_errors_the_report_prints_beside_an_estimate(self):
        import relay_analyze
        import relay_ledger
        self._agent_session(None)
        # Claude Code's total for the session with an agent: the transcripts-only estimate is far below it
        self._claude_json("s-snap")
        text = relay_analyze.calibrate(self.claude, "2026-10-21T12:00:00Z")
        stored = relay_analyze.load_calibration()["estimate"]
        self.assertEqual(list(stored), ["with_agents"])             # the session has an agent: it is not filed as without
        mains = relay_analyze.collect(self.claude, dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc), dt.datetime(2026, 10, 22, tzinfo=dt.timezone.utc))
        guess = relay_analyze.session_figures(mains["sessions"][0], {})["cost"]
        total = sum(m["cost_usd"] for m in relay_ledger.usage_sessions()["s-snap"].values())
        want = (guess - total) / total                              # estimate against Claude Code's total, signed
        self.assertLess(want, -0.1)
        self.assertAlmostEqual(stored["with_agents"]["worst_signed"], want, places=6)
        self.assertAlmostEqual(stored["with_agents"]["median"], abs(want), places=6)
        self.assertEqual(stored["with_agents"]["n"], 1)
        self.assertEqual(stored["with_agents"]["over_10"], 1)
        # drop the ledger copy and the file's total so the report has an estimate to print
        os.remove(os.path.join(self.claude, ".claude.json"))
        shutil.rmtree(os.path.join(self.home, "ledger"), ignore_errors=True)
        report = relay_analyze.report(relay_analyze.collect(self.claude, dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc), dt.datetime(2026, 10, 22, tzinfo=dt.timezone.utc)))
        self.assertIn(f"sessions with agents: median {abs(want) * 100:.0f}%, worst {abs(want) * 100:.0f}% low, 1 of 1 over 10% off", report)


class Roles(Base):
    """Assembly of the role bases (lib/relay_roles.py) on fixture trees; the real agent files are checked at the end."""

    JUDGE = "---\nrole: judge\nneeds-tools: Read, Bash\nnever-tools: Edit\n---\nJudge body.\nTurns: {maxTurns}.\n"
    LIMITS = "## Limits\n- No long commands.\n"
    TESTS = "## Tests\n- Expected values by hand.\n"

    def fixture(self, agent_tools="Read, Bash", markers=None, max_turns=60):
        """A tree with roles/ and one agent plugins/x/agents/a.md; returns its root."""
        root = os.path.join(self.tmp, "fx")
        for sub in ("roles/parts", "plugins/x/agents", "rules"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        files = {"roles/judge.md": self.JUDGE, "roles/parts/limits.md": self.LIMITS, "roles/parts/tests.md": self.TESTS,
                 "roles/build.md": "---\nrole: build\n---\nBuild.\n\n<!-- relay:include tests -->\n\nEnd.\n"}
        for name, text in files.items():
            with open(os.path.join(root, name), "w") as handle:
                handle.write(text)
        markers = markers if markers is not None else (
            "<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n\nFlow text.\n\n"
            "<!-- relay:part limits -->\n<!-- relay:end limits -->\n")
        with open(os.path.join(root, "plugins/x/agents/a.md"), "w") as handle:
            handle.write("---\nname: a\ntools: %s\nmaxTurns: %d\n---\n\n%s" % (agent_tools, max_turns, markers))
        return root

    def agent(self, root):
        return os.path.join(root, "plugins/x/agents/a.md")

    def lib(self):
        import relay_roles
        return relay_roles

    def test_assembled_agents_are_current(self):
        """A1: assembly fills the regions (maxTurns of the agent, the include expanded, the frontmatter of the base
        stripped); a hand edit inside a region is reported with the file and the base; the real tree is current."""
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n\nFlow text.\n")
        self.assertEqual(rr.check(root), [(self.agent(root), "judge", "base")])
        rr.assemble(root)
        text = open(self.agent(root)).read()
        # worked out by hand: the base body, its {maxTurns} = 60 from this agent's frontmatter, between the markers
        want = "<!-- relay:base judge -->\nJudge body.\nTurns: 60.\n<!-- relay:end judge -->\n\nFlow text.\n"
        self.assertTrue(text.endswith(want), text)
        self.assertEqual(rr.check(root), [])
        with open(self.agent(root), "w") as handle:
            handle.write(text.replace("Judge body.", "Judge body, edited."))
        self.assertEqual(rr.check(root), [(self.agent(root), "judge", "base")])
        self.assertEqual(rr.describe(self.agent(root), "judge", root),
                         "plugins/x/agents/a.md: text in relay:base judge differs from roles/judge.md: "
                         "edit roles/judge.md, then run bin/relay sync agents from this checkout")
        # F5: an edit inside a part names the part and its file, and sync says which region of which file it rewrote
        root = self.fixture()   # an agent with a base and the limits part
        rr.assemble(root)
        with open(self.agent(root)) as handle:
            text = handle.read()
        with open(self.agent(root), "w") as handle:
            handle.write(text.replace("No long commands.", "Long commands are fine."))
        (found,) = rr.check(root)
        self.assertEqual(found, (self.agent(root), "limits", "part"))
        self.assertEqual(rr.describe(*found[:2], root, found[2]),
                         "plugins/x/agents/a.md: text in relay:part limits differs from roles/parts/limits.md: "
                         "edit roles/parts/limits.md, then run bin/relay sync agents from this checkout")
        self.assertEqual(rr.assemble_detail(root, dry=True), [(self.agent(root), [("part", "limits")])])
        self.assertEqual(rr.assemble_detail(root), [(self.agent(root), [("part", "limits")])])
        self.assertEqual(rr.check(root), [])
        # on the real tree a stale region fails with the describe() message, not a tuple
        self.assertEqual([rr.describe(p, n, ROOT, k) for p, n, k in rr.check(ROOT)], [])   # the real agent files are what their bases say
        with open(os.path.join(ROOT, rr.MAP_FILE), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), rr.role_map(ROOT))   # and the role map is what their markers say

    def test_assembly_writes_the_role_map(self):
        """F2: assembly writes plugins/core/lib/agent-roles.tsv (one line per marked agent, sorted), leaves it alone
        when current, leaves a stale one alone on a dry run, and writes none when the checkout has no core plugin."""
        rr = self.lib()
        root = self.fixture()
        self.assertFalse(os.path.exists(os.path.join(root, rr.MAP_FILE)))
        rr.assemble(root)
        self.assertFalse(os.path.exists(os.path.join(root, rr.MAP_FILE)))   # no plugins/core/lib: no map
        os.makedirs(os.path.join(root, "plugins/core/lib"))
        with open(os.path.join(root, "plugins/x/agents/b.md"), "w") as handle:
            handle.write("---\nname: b\nmaxTurns: 80\n---\n\n<!-- relay:base build -->\n<!-- relay:end build -->\n")
        mapfile = os.path.join(root, rr.MAP_FILE)
        rr.assemble(root, dry=True)
        self.assertFalse(os.path.exists(mapfile))   # dry: nothing written
        rr.assemble(root)
        with open(mapfile) as handle:
            self.assertEqual(handle.read(), "x:a\tjudge\nx:b\tbuild\n")
        before = (open(mapfile).read(), os.stat(mapfile).st_mtime_ns)
        rr.assemble(root)
        self.assertEqual((open(mapfile).read(), os.stat(mapfile).st_mtime_ns), before)   # current: untouched
        with open(mapfile, "w") as handle:
            handle.write("stale\n")
        rr.assemble(root, dry=True)
        with open(mapfile) as handle:
            self.assertEqual(handle.read(), "stale\n")
        rr.assemble(root)
        with open(mapfile) as handle:
            self.assertEqual(handle.read(), "x:a\tjudge\nx:b\tbuild\n")

    def test_include_is_expanded_one_level(self):
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base build -->\n<!-- relay:end build -->\n")
        rr.assemble(root)
        self.assertIn("Build.\n\n## Tests\n- Expected values by hand.\n\nEnd.\n", open(self.agent(root)).read())
        with open(os.path.join(root, "roles/parts/tests.md"), "a") as handle:
            handle.write("<!-- relay:include limits -->\n")
        with self.assertRaises(rr.RolesError) as caught:
            rr.assemble(root)
        self.assertIn("includes are one level", str(caught.exception))

    def test_every_agent_has_one_base(self):
        """A2 on fixtures: no base, two bases, an unknown base or part, unbalanced, nested and wrongly closed markers."""
        rr = self.lib()
        cases = {
            "none": ("<!-- relay:part limits -->\n<!-- relay:end limits -->\n", "0 relay:base regions"),
            "two": ("<!-- relay:base judge -->\n<!-- relay:end judge -->\n<!-- relay:base build -->\n<!-- relay:end build -->\n", "2 relay:base regions"),
            "unknown base": ("<!-- relay:base nope -->\n<!-- relay:end nope -->\n", "roles/nope.md missing"),
            "unknown part": ("<!-- relay:base judge -->\n<!-- relay:end judge -->\n<!-- relay:part nope -->\n<!-- relay:end nope -->\n", "roles/parts/nope.md missing"),
            "unclosed": ("<!-- relay:base judge -->\ntext\n", "never closed"),
            "stray end": ("<!-- relay:end judge -->\n", "no open marker"),
            "nested": ("<!-- relay:base judge -->\n<!-- relay:part limits -->\n<!-- relay:end limits -->\n<!-- relay:end judge -->\n", "no nesting"),
            "wrong end": ("<!-- relay:base judge -->\n<!-- relay:end build -->\n", "closes region 'judge'"),
        }
        for label, (markers, message) in cases.items():
            root = self.fixture(markers=markers)
            found = " | ".join(rr.problems(root))
            self.assertIn(message, found, label)
        root = self.fixture(markers="<!-- relay:base judge -->\n<!-- relay:end judge -->\n")
        self.assertEqual(rr.problems(root), [])
        self.assertEqual(rr.problems(self.fixture(markers="no markers at all\n")), [])
        self.assertIn("no relay:base region", " ".join(rr.problems(self.fixture(markers="no markers at all\n"), require_base=True)))

    def test_base_tools(self):
        """A3: a judge whose tools lack Bash, or hold Edit, is reported."""
        rr = self.lib()
        marker = "<!-- relay:base judge -->\n<!-- relay:end judge -->\n"
        self.assertEqual(rr.problems(self.fixture(agent_tools="Read, Bash, Grep", markers=marker)), [])
        self.assertIn("tools lack Bash", " ".join(rr.problems(self.fixture(agent_tools="Read, Grep", markers=marker))))
        self.assertIn("tools hold Edit", " ".join(rr.problems(self.fixture(agent_tools="Read, Bash, Edit", markers=marker))))

    def test_base_placeholders(self):
        """A4: only {maxTurns} is a placeholder, in bases, parts and (after assembly) never in an agent file."""
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\n<!-- relay:end judge -->\n")
        self.assertEqual(rr.problems(root), [])
        with open(os.path.join(root, "roles/parts/limits.md"), "a") as handle:
            handle.write("Wait {seconds} seconds.\n")
        self.assertIn("placeholder {seconds}", " ".join(rr.problems(root)))
        rr.assemble(root)
        self.assertNotIn("{maxTurns}", open(self.agent(root)).read())
        with open(self.agent(root), "a") as handle:
            handle.write("\nleft {maxTurns} outside a region\n")
        self.assertIn("holds {maxTurns} after assembly", " ".join(rr.problems(root)))
        # the real bases and parts hold no other placeholder
        self.assertEqual([p for p in rr.problems(ROOT) if "placeholder" in p], [])

    def test_assembly_touches_only_source(self):
        """A5: a fake installed copy (registered in the config dir) and a bench candidate's copy stay as they are."""
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        copies = [os.path.join(self.claude, "plugins", "cache", "x"), os.path.join(root, "profiles", "candidates", "c", "plugins", "x")]
        for copy in copies:
            os.makedirs(os.path.join(copy, "agents"))
            with open(os.path.join(copy, "agents", "a.md"), "w") as handle:
                handle.write("---\nname: a\nmaxTurns: 60\n---\n<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        with open(os.path.join(self.claude, "plugins", "installed_plugins.json"), "w") as handle:
            json.dump({"plugins": {"x@relay": [{"installPath": copies[0]}]}}, handle)
        before = [open(os.path.join(c, "agents", "a.md")).read() for c in copies]
        self.assertEqual(rr.assemble(root), [self.agent(root)])
        self.assertEqual([open(os.path.join(c, "agents", "a.md")).read() for c in copies], before)

    def test_sync_agents_writes_only_this_checkout(self):
        """A7: with RELAY_ROOT a fixture copy, sync(only={"agents"}) writes inside its plugins/*/agents and nowhere else
        (no CLAUDE.md in the config dir, nothing else in the fixture)."""
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        os.environ["RELAY_ROOT"] = root
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]
        import relay_rules

        def snapshot(folder, skip):
            seen = {}
            for here, _, names in os.walk(folder):
                for name in names:
                    path = os.path.join(here, name)
                    if not path.startswith(skip):
                        seen[path] = open(path, "rb").read()
            return seen
        skip = os.path.join(root, "plugins", "x", "agents")
        before_root, before_claude = snapshot(root, skip), snapshot(self.claude, "")
        results = relay_rules.sync({}, only={"agents"})
        self.assertEqual(snapshot(root, skip), before_root)
        self.assertEqual(snapshot(self.claude, ""), before_claude)
        self.assertFalse(os.path.exists(os.path.join(self.claude, "CLAUDE.md")))
        self.assertIn("Judge body.", open(self.agent(root)).read())
        self.assertEqual(results[-1][2], "assembled 1, set model/effort in 0")

    def test_dry_sync_counts_agents(self):
        """A8: --dry says how many agent files it would assemble and how many get model/effort, and writes nothing."""
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        with open(self.agent(root), "a") as handle:
            handle.write("")
        text = open(self.agent(root)).read().replace("maxTurns: 60\n", "maxTurns: 60\nrelay-tier: fix\nmodel: opus\n")
        with open(self.agent(root), "w") as handle:
            handle.write(text)
        with open(os.path.join(root, "plugins/x/agents/b.md"), "w") as handle:    # no markers, a tier whose model differs
            handle.write("---\nname: b\nrelay-tier: fix\nmodel: opus\n---\nPlain.\n")
        os.environ["RELAY_ROOT"] = root
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]
        import relay_rules
        before = open(self.agent(root)).read()
        profile = {"models": {"fix": "sonnet"}}
        # worked out by hand: a.md has a stale region (1 to assemble); a.md and b.md both have tier fix on opus, profile says sonnet (2 to set)
        self.assertEqual(relay_rules.sync(profile, only={"agents"}, dry=True)[-1][2], "would assemble 1, would set model/effort in 2")
        self.assertEqual(open(self.agent(root)).read(), before)

    def test_assembly_is_idempotent(self):
        """A9: a second run changes nothing; one run restores an edited region."""
        rr = self.lib()
        root = self.fixture()
        rr.assemble(root)
        once = open(self.agent(root)).read()
        self.assertEqual(rr.assemble(root), [])
        self.assertEqual(open(self.agent(root)).read(), once)
        with open(self.agent(root), "w") as handle:
            handle.write(once.replace("No long commands.", "Edited."))
        self.assertEqual(rr.assemble(root), [self.agent(root)])
        self.assertEqual(open(self.agent(root)).read(), once)

    def test_every_real_agent_has_one_base(self):
        """A2 on the real tree: every agent file of every plugin has exactly one relay:base region, known parts and the tools
        its base needs; the bases of the 15 agents are the ones the design names (the checker is a judge)."""
        rr = self.lib()
        self.assertEqual(rr.problems(ROOT, require_base=True), [])
        by_base = {}
        for path in rr.agent_files(ROOT):
            text = open(path).read()
            base = [r["name"] for r in rr.parse_regions(text) if isinstance(r, dict) and r["kind"] == "base"][0]
            by_base.setdefault(base, []).append(os.path.relpath(path, ROOT))
        self.assertEqual(by_base, {
            "lookup": ["plugins/delegate/agents/scout.md"],
            "run": ["plugins/delegate/agents/runner.md"],
            "build": ["plugins/delegate/agents/worker.md", "plugins/sdd/agents/worker.md"],
            "fix": ["plugins/delegate/agents/fixer.md", "plugins/sdd/agents/fixer.md"],
            "think": ["plugins/delegate/agents/thinker.md", "plugins/sdd/agents/author.md"],
            "judge": ["plugins/delegate/agents/checker.md", "plugins/delegate/agents/critic.md", "plugins/product/agents/ui-reviewer.md",
                      "plugins/sdd/agents/code-reviewer.md", "plugins/sdd/agents/reviewer.md", "plugins/sdd/agents/spec-conformance.md",
                      "plugins/sdd/agents/spec-reviewer.md"]})

    def test_judges_cannot_edit_and_check_mode_does_not_need_part_two(self):
        """The judge base forbids Edit tools (A3) and names no part-2 thing as a given: marks, merge refusal and queue
        items appear only as 'when the project has' them. A judge that gained Edit, or a base that states a queue as fact, fails."""
        rr = self.lib()
        for path in rr.agent_files(ROOT):
            text = open(path).read()
            meta, _ = rr.split_frontmatter(text)
            if "relay:base judge" in text:
                for tool in ("Edit", "MultiEdit", "NotebookEdit"):
                    self.assertNotIn(tool, [x.strip() for x in meta["tools"].split(",")], path)
        judge = open(os.path.join(ROOT, "roles", "judge.md")).read()
        flat = " ".join(judge.split())
        self.assertIn("When the project has a work queue, a finding from a findings file", flat)
        # review F8: the owner's move is data (an owner entry with `queue`), not a `Owner: <id> moved to queue item` prompt line
        self.assertIn("a finding the owner moved to a queue item is data: an `owner` entry with `queue`", flat)
        self.assertNotIn("Owner: <id> moved to queue item", flat)
        self.assertIn("relay changed -C <path> <sha>` lists no file", flat)
        checker = open(os.path.join(ROOT, "plugins", "delegate", "agents", "checker.md")).read()
        self.assertIn("where the project has check marks", " ".join(checker.split()))

    def test_judge_base_part2(self):
        """A15: the judge base names `relay changed --own` in check step 1 and the linter line in "Each finding"; the
        checker's flow part and the delegate skill name `relay gate`."""
        judge = " ".join(open(os.path.join(ROOT, "roles", "judge.md")).read().split())
        self.assertIn("List its files with `relay changed --own -C <path> <Reviewed sha>`", judge)
        each = judge[judge.index("## Each finding"):judge.index("## The rating is yours")]
        self.assertIn("<path>:<line>: <SEVERITY>: F<n> <what goes wrong>", each)
        self.assertIn("relay changed -C <path> <sha>` lists no file", judge)     # the gate rule has no --own
        self.assertIn("F2 MET tests/test_inert.py:88", judge)
        # F5: agents without Write get a quoted heredoc, never an unquoted one, in the base and in every synced copy
        self.assertIn("with a quoted heredoc `cat > <file> <<'EOF'` when you have no Write tool", judge)
        rr = self.lib()
        for path in rr.agent_files(ROOT):
            text = " ".join(open(path).read().split())
            if "relay:base judge" in text:
                self.assertIn("with a quoted heredoc `cat > <file> <<'EOF'` when you have no Write tool", text, path)
        checker = " ".join(open(os.path.join(ROOT, "plugins", "delegate", "agents", "checker.md")).read().split())
        self.assertIn("written by `relay gate`", checker)
        self.assertIn("never `Brief: <file>`", checker)
        skill = " ".join(open(os.path.join(ROOT, "plugins", "delegate", "skills", "delegate", "SKILL.md")).read().split())
        self.assertIn("runs `relay gate`", skill)
        self.assertIn("never `git rebase`", skill)
        self.assertIn("`relay check show <branch>`", skill)
        front = " ".join(open(os.path.join(ROOT, "plugins", "front", "skills", "front", "SKILL.md")).read().split())
        self.assertIn("## A change ready to merge", front)
        self.assertIn("Publish the page yourself with your Artifact tool", front)
        self.assertIn("gives the page's file path instead", front)

    def test_missing_base_names_the_checkout_rule(self):
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\n<!-- relay:end judge -->\n")
        os.remove(os.path.join(root, "roles", "judge.md"))
        with self.assertRaises(rr.RolesError) as caught:
            rr.assemble(root)
        self.assertEqual(str(caught.exception), "roles/judge.md missing (run from the checkout that has roles/)")


class Agents(unittest.TestCase):
    def test_every_agent_has_a_turn_limit_and_judges_write_their_file_early(self):
        """Two Opus agents once ran out of turns with no report. Every agent file in every plugin carries maxTurns
        (a new agent without one fails here): Opus judges and thinkers 60 and must start the file early, Sonnet
        builders and fixers 80, the small lookup agents keep their own."""
        import glob
        import re
        files = sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "agents", "*.md")))
        self.assertGreaterEqual(len(files), 14)
        for path in files:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            name = os.path.relpath(path, ROOT)
            front = text.split("---", 2)[1]
            turns = re.search(r"(?m)^maxTurns: (\d+)$", front)
            self.assertIsNotNone(turns, name + " has no maxTurns")
            model = re.search(r"(?m)^model: (\w+)$", front).group(1)
            if model == "opus":
                self.assertEqual(turns.group(1), "60", name)
                self.assertIn("within your first 10 tool calls", text, name)
                # a run cut short still leaves what was found: a thinker appends to its file, a judge records its input early and again
                self.assertTrue("append to it as you go" in text or "record again as you add findings" in text, name)
            elif model == "sonnet":
                self.assertEqual(turns.group(1), "80", name)

    def test_no_place_restates_the_old_loop(self):
        """A6 (part 1): the review is one review and a checked fix. No rule, base, skill or agent says the old loop
        (two passes, a third pass, debt), and each of the five review places names roles/judge.md."""
        import glob
        import re
        banned = ["over the fix range", "at most twice", "no third pass", "second pass", "tech debt", "technical debt",
                  "follow-up with an id", "follow-up id"]
        files = []
        for pattern in ("rules/*.md", "roles/*.md", "roles/parts/*.md", "plugins/*/skills/*/SKILL.md", "plugins/*/agents/*.md"):
            files += glob.glob(os.path.join(ROOT, pattern))
        self.assertGreater(len(files), 40)
        for path in sorted(files):
            with open(path, encoding="utf-8") as handle:
                text = handle.read().lower()
            for phrase in banned:
                self.assertNotIn(phrase, text, "%s still says %r" % (os.path.relpath(path, ROOT), phrase))
        places = ["rules/delegation.md", "plugins/delegate/skills/delegate/SKILL.md", "plugins/issues/skills/implement/SKILL.md",
                  "plugins/sdd/skills/apply-review/SKILL.md", "plugins/sdd/skills/spec-review/SKILL.md"]
        for place in places:
            with open(os.path.join(ROOT, place), encoding="utf-8") as handle:
                self.assertIn("roles/judge.md", handle.read(), place + " does not name roles/judge.md")

    def test_project_rule_rating_belongs_to_the_judge(self):
        """A project rule reaches every agent that rates under it: in every judge-base agent the rating is the agent's
        own (a skill's severities are input), style is a finding when a project rule makes it one, and a finding a
        project rule raises gets its own reply line with the rule's label; the two judges that run a skill say so."""
        import glob
        import re
        def read(rel):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                return " ".join(handle.read().split())
        agents = [p for p in sorted(glob.glob(os.path.join(ROOT, "plugins/*/agents/*.md")))
                  if "<!-- relay:base judge -->" in open(p, encoding="utf-8").read()]
        self.assertGreaterEqual(len(agents), 7)
        own_list_flows = ("plugins/sdd/agents/spec-reviewer.md", "plugins/sdd/agents/spec-conformance.md",
                          "plugins/product/agents/ui-reviewer.md")
        for path in agents:
            text = read(os.path.relpath(path, ROOT))
            name = os.path.relpath(path, ROOT)
            self.assertIn("unless a project rule makes it one", text, name)
            self.assertIn("## The rating is yours", text, name)
            self.assertIn("carries the rule's label", text, name)
            self.assertIn("Every finding a project rule raises gets one line too (where, what, the rule's label)", text, name)
            # the reply section the agent actually emits: the shared one says the lines beyond the 10 belong to every
            # reply, and a flow that gives its own reply list names the project-rule line in that list
            reply = text[text.index("## Reply "):]
            self.assertIn("belong to every reply, a flow's own list included", reply, name)
            if "## Reply, in addition" in text:
                own = text[text.index("## Reply, in addition"):]
                own = re.split(r" ## (?!Reply, in addition)", own)[0]
                has_own_list = re.search(r"replaces the shared reply list|reply with at most 10|In the reply give", own)
                if name in own_list_flows:   # a rewording that hides the list must fail here, not skip
                    self.assertTrue(has_own_list, name + ": the flow's own reply list cannot be found")
                if has_own_list:
                    self.assertRegex(own, r"project rule\s+raises \(where, what, the rule's label\)", name + " own reply list")
        for flow in ("plugins/sdd/agents/spec-reviewer.md", "plugins/sdd/agents/spec-conformance.md",
                     "plugins/product/agents/ui-reviewer.md"):
            self.assertIn("## Reply, in addition", read(flow), flow)
        code = read("plugins/sdd/agents/code-reviewer.md")
        self.assertIn("The skill runs without the project's rules", code)
        self.assertIn("in its own reply line even when the skill rated it low", code)
        self.assertIn("The skill does not see the project's rules", read("plugins/sdd/agents/spec-conformance.md"))
        conf = " ".join(read("plugins/sdd/agents/spec-conformance.md").split())
        self.assertIn("that cap counts only these CRITICAL and MISSING lines", conf)
        self.assertIn("beyond that and never inside the cap", conf)
        self.assertIn("is given once, as its labelled line beyond the cap", conf)

    def test_gate_runs_before_the_check_in_every_flow(self):
        """F3/F4/F6/F7: in each flow the order is fix, full gate (a log that starts with `head <sha>`), check; a flow
        with no gate says so; the global texts name relay's path for the judge base; an open finding inside the change
        is not deferred."""
        def read(rel):   # line breaks do not matter to the wording
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                return " ".join(handle.read().split())
        writer = 'echo "head $(git -C <wt> rev-parse HEAD)"'
        implement = read("plugins/issues/skills/implement/SKILL.md")
        self.assertIn(writer, implement)
        self.assertLess(implement.index("delegate:fixer"), implement.index("runs `gate.ci`"))
        self.assertLess(implement.index("runs `gate.ci`"), implement.index("`delegate:checker` with `Gate: <log>`"))
        review = read("plugins/sdd/skills/apply-review/SKILL.md")
        self.assertIn(writer, review)
        self.assertLess(review.index("## 4. Close: the final gate"), review.index("## 5. Check of the fixes"))
        self.assertIn("pipeline #<n> on <full sha> passed", review)
        delegate = read("plugins/delegate/skills/delegate/SKILL.md")
        self.assertIn(writer, delegate)
        self.assertLess(delegate.index("6. **Gate again.**"), delegate.index("7. **Check.**"))
        self.assertLess(delegate.index("3. **Gate before the review.**"), delegate.index("4. **One whole-change review.**"))
        # the checker side: the log form, the remote form and the no-gate form are all named, and agree with spec-review
        judge = read("roles/judge.md")
        self.assertIn("`head <full sha>`", judge)
        self.assertIn("pipeline #<n> on <full sha> passed", judge)
        self.assertIn("`Gate: none (artifacts only)`", judge)
        self.assertIn("outside `openspec/`", judge)   # a code fix with no gate is still open +1
        checker = read("plugins/delegate/agents/checker.md")
        spec = read("plugins/sdd/skills/spec-review/SKILL.md")
        self.assertIn("Gate: none (artifacts only)", spec)
        self.assertIn("writes no verdict", spec)
        self.assertIn("writes no verdict", checker)
        # review F9: the artifacts-only check writes plain text, so the skill names a .md report and reads it directly
        self.assertIn("spec-check.md", spec)
        self.assertNotIn("spec-check.json", spec)
        self.assertNotIn("relay check show <scratchpad>/review/spec-check", spec)
        self.assertIn("plain text file", checker)
        # F6: the global rule and the skills that run in other projects give relay's path, never a bare roles/judge.md
        for rel in ("rules/delegation.md", "plugins/delegate/skills/delegate/SKILL.md",
                    "plugins/issues/skills/implement/SKILL.md", "plugins/sdd/skills/spec-review/SKILL.md"):
            text = read(rel)
            self.assertIn("~/relay/roles/judge.md", text, rel)
            self.assertEqual(text.count("roles/judge.md"), text.count("~/relay/roles/judge.md"), rel)
        # F7: no deferral of an open HIGH or MEDIUM inside the change
        self.assertNotIn("follow-up with an id", review)
        self.assertIn("never a follow-up", review)

    def test_relay_changed(self):
        """A12: `relay changed -C <repo> <sha>` lists the changed files that are not inert, and follows the matcher:
        `*` stays inside one path part, `**` crosses parts."""
        tmp = tempfile.mkdtemp(prefix="relay-changed-")
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)

        def git(*args):
            return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                  capture_output=True, text=True, check=True).stdout.strip()

        def write(rel, text):
            path = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(text)

        git("init", "-q")
        write("lib/a.py", "1\n")
        write("docs/handover.md", "1\n")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD")
        write("lib/a.py", "2\n")
        write("docs/handover.md", "2\n")
        write("docs/handover.md.bak", "x\n")
        write(".relay/queue/x.md", "x\n")
        write(".relay/queue/deep/y.md", "y\n")
        write(".relay/checks/%s.json" % base, "{}\n")
        write(".relay/other.md", "z\n")
        git("add", "-A")
        git("commit", "-q", "-m", "change")
        env = dict(os.environ, RELAY_ROOT=ROOT)
        run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", repo, base],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        # not inert: the code, a sibling of the handover with another name, an unlisted .relay file
        self.assertEqual(sorted(run.stdout.split()), [".relay/other.md", "docs/handover.md.bak", "lib/a.py"])
        # nothing changed since HEAD: nothing listed
        run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", repo, "HEAD"],
                             capture_output=True, text=True, env=env)
        self.assertEqual((run.returncode, run.stdout), (0, ""))
        # the matcher itself
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import relay_inert
        self.assertTrue(relay_inert.matches(".relay/queue/a/b/c.md"))
        self.assertTrue(relay_inert.matches(".relay/checks/abc.json"))
        self.assertFalse(relay_inert.matches(".relay/queuex/a.md"))
        self.assertFalse(relay_inert.matches("sub/docs/handover.md"))
        # F1: a rename counts as delete + add, so code moved into an inert folder (or out of one) is listed
        write("lib/foo.py", "1\n")
        write("lib/\u00fc.py", "1\n")
        git("add", "-A")
        git("commit", "-q", "-m", "more")
        start = git("rev-parse", "HEAD")
        git("mv", "lib/foo.py", ".relay/queue/foo.py")
        git("mv", "docs/handover.md", "lib/h.py")
        write("lib/\u00fc.py", "2\n")
        write("docs/handover.md", "again\n")   # a new inert file, ignored
        write(".relay/checks/x.json", "{}\n")
        git("add", "-A")
        git("commit", "-q", "-m", "moves")
        self.assertEqual(relay_inert.changed(repo, start), ["lib/foo.py", "lib/h.py", "lib/\u00fc.py"])
        git("commit", "-q", "--allow-empty", "-m", "nothing")
        write("docs/handover.md", "3\n")
        write(".relay/checks/y.json", "{}\n")
        git("add", "-A")
        git("commit", "-q", "-m", "inert only")
        self.assertEqual(relay_inert.changed(repo, "HEAD~1"), [])
        self.assertTrue(relay_inert._regex("a/*/c").match("a/b/c"))
        self.assertFalse(relay_inert._regex("a/*/c").match("a/b/d/c"))
        self.assertTrue(relay_inert._regex("a/**/c").match("a/b/d/c"))
        self.assertTrue(relay_inert._regex("a/**/c").match("a/c"))

    def test_relay_changed_own(self):
        """A14: `relay changed --own` leaves out what only the default branch changed (design 7.2, the six rows of the
        worked values), and plain `changed` lists master's file for the same pair.

        Worked by hand. master M0 holds queue.py v1, inert.py v1, bin.txt (six lines), no foo item. The branch adds
        marks.py and merge.py (a) and fixes inert.py and the first line of bin.txt, and is checked there: X.
        Master then gains queue.py v2, the item foo.md and a change of bin.txt's last line. The branch edits merge.py
        (b), reverts inert.py to v1, and merges master: Y. For the pair X..Y:
          queue.py     v1 v1 v2 v2   only master changed it                   not own
          foo.md       inert                                                  not listed at all
          marks.py     not in the X..Y diff                                   not listed at all
          merge.py     none a none b  edited after X                          own
          inert.py     v1 fix v1 v1   at X the branch had touched it          own (a reverted checked fix)
          bin.txt      both sides changed, git combined them                  own"""
        tmp = tempfile.mkdtemp(prefix="relay-own-")
        self.addCleanup(shutil.rmtree, tmp, True)
        main = os.path.join(tmp, "main")
        wt = os.path.join(main, ".worktrees", "x")
        os.makedirs(main)

        def git(cwd, *args):
            return subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                  capture_output=True, text=True, check=True).stdout.strip()

        def write(cwd, rel, text):
            path = os.path.join(cwd, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(text)

        git(main, "init", "-q", "-b", "master")
        write(main, ".gitignore", ".worktrees/\n")
        write(main, "lib/relay_queue.py", "v1\n")
        write(main, "lib/relay_inert.py", "v1\n")
        write(main, "bin/relay", "1\n2\n3\n4\n5\n6\n")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "M0")
        m0 = git(main, "rev-parse", "HEAD")
        git(main, "worktree", "add", "-q", wt, "-b", "wt/x")
        write(wt, "lib/relay_marks.py", "a\n")
        write(wt, "plugins/core/hooks/merge.py", "a\n")
        write(wt, "lib/relay_inert.py", "v1 fixed\n")
        write(wt, "bin/relay", "1a\n2\n3\n4\n5\n6\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "checked work")
        x = git(wt, "rev-parse", "HEAD")
        write(main, "lib/relay_queue.py", "v2\n")
        write(main, ".relay/queue/foo.md", "item\n")
        write(main, "bin/relay", "1\n2\n3\n4\n5\n6a\n")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "master moves")
        write(wt, "plugins/core/hooks/merge.py", "b\n")
        write(wt, "lib/relay_inert.py", "v1\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "after the check")
        git(wt, "merge", "-q", "--no-edit", "master")
        env = dict(os.environ, RELAY_ROOT=ROOT)

        def listed(*args):
            run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", wt, *args],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            return sorted(run.stdout.split())

        self.assertEqual(listed("--own", x, "HEAD"), ["bin/relay", "lib/relay_inert.py", "plugins/core/hooks/merge.py"])
        self.assertEqual(listed("--own", x), ["bin/relay", "lib/relay_inert.py", "plugins/core/hooks/merge.py"])   # until defaults to HEAD
        self.assertEqual(listed(x), ["bin/relay", "lib/relay_inert.py", "lib/relay_queue.py", "plugins/core/hooks/merge.py"])
        # without a merge from master B_U = B_S: --own lists what plain changed lists
        self.assertEqual(listed("--own", m0, x), listed(m0, x))
        self.assertEqual(listed(m0, x), ["bin/relay", "lib/relay_inert.py", "lib/relay_marks.py", "plugins/core/hooks/merge.py"])
        # no default branch: --own cannot tell and says so
        git(main, "branch", "-m", "master", "trunk2")
        git(main, "branch", "-m", "trunk2", "other")
        run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", wt, "--own", x],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 1)
        self.assertIn("cannot tell the default branch", run.stderr)

    def test_role_names_are_not_agent_or_skill_names(self):
        """A13: a role file `.claude/kit/<role>.md` must not also be the per-agent or per-skill file of a served plugin
        (one file would serve both); the map plugins/core/lib/agent-roles.tsv is what the agents' base markers say."""
        import glob
        import re
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import relay_roles
        roles = {os.path.basename(f)[:-3] for f in glob.glob(os.path.join(ROOT, "roles", "*.md"))}
        self.assertEqual(roles, {"lookup", "run", "build", "fix", "think", "judge"})
        served = {"core", "sdd", "product", "delegate", "issues", "front"}
        names = {}
        for kind, pattern in (("agent", "plugins/*/agents/*.md"), ("skill", "plugins/*/skills/*/SKILL.md")):
            for path in glob.glob(os.path.join(ROOT, pattern)):
                plugin = os.path.relpath(path, ROOT).split(os.sep)[1]
                if plugin in served:
                    stem = os.path.basename(path)[:-3] if kind == "agent" else os.path.basename(os.path.dirname(path))
                    names[stem] = kind + " " + plugin
        self.assertGreater(len(names), 15)
        for role in sorted(roles):
            self.assertNotIn(role, names, "role %s is also the name of %s" % (role, names.get(role)))
        with open(os.path.join(ROOT, relay_roles.MAP_FILE), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(len(lines), len(glob.glob(os.path.join(ROOT, "plugins", "*", "agents", "*.md"))))
        for line in lines:
            self.assertRegex(line, r"^[a-z]+:[a-z-]+\t(lookup|run|build|fix|think|judge)$")
        self.assertEqual("".join(l + "\n" for l in lines), relay_roles.role_map(ROOT))


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


class Rules(Base):
    def test_sync_writes_global_and_project_files(self):
        import relay_config
        import relay_rules
        profile = relay_config.active_profile()
        # not "agents": that rewrites the repository's own agent files (test_profile_rewrites_tiered_agents_in_a_copy covers it)
        results = relay_rules.sync(profile, only={"global", "demo"})
        states = {n: s for n, _, s in results}
        self.assertEqual(states["global"], "written")
        self.assertEqual(states["demo"], "written")
        self.assertIn("## Quality gate", open(self.project_file).read())
        text = open(os.path.join(self.claude, "CLAUDE.md")).read()
        self.assertIn("Generated by relay", text)
        self.assertIn("## Delegation", text)
        self.assertIn("Rules to read when they apply", text)
        self.assertEqual(relay_rules.check(profile), [])
        with open(self.project_file, "a") as handle:
            handle.write("edited\n")
        self.assertEqual([c[0] for c in relay_rules.check(profile)], ["demo"])

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


class RelayFolder(Base):
    """S1-S3 (design 12.7): `relay setup --relay-folder` writes `.relay/README.md` and nothing else."""

    def _repo(self):
        repo = os.path.join(self.tmp, "fixture-repo")
        os.makedirs(repo)
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        with open(os.path.join(repo, "go.mod"), "w") as handle:
            handle.write("module x\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True)
        return repo

    def _env(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
        settings = os.path.join(home, ".claude", "settings.json")
        with open(settings, "w") as handle:
            handle.write('{"enabledPlugins": {"x@y": true}}\n')
        return dict(os.environ, HOME=home, CLAUDE_CONFIG_DIR=os.path.join(home, ".claude")), settings

    def _run(self, env, *args, cwd=None):
        return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "setup", *args],
                              env=env, cwd=cwd, capture_output=True, text=True, timeout=60)

    def _status(self, repo):
        return subprocess.run(["git", "-C", repo, "status", "--porcelain", "-uall"], capture_output=True, text=True, check=True).stdout.splitlines()

    def test_s1_relay_folder_writes_only_the_readme(self):
        repo = self._repo()
        env, settings = self._env()
        projects = os.environ["RELAY_PROJECTS"]
        before = (open(settings, "rb").read(), open(projects, "rb").read())
        out = self._run(env, "--relay-folder", repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        # only the one file is new: every other piece of plain setup (kit.toml, bin/*, settings, project entry) is absent
        self.assertEqual(self._status(repo), ["?? .relay/README.md"])
        self.assertEqual((open(settings, "rb").read(), open(projects, "rb").read()), before)
        for rel in ("bin/check", "bin/wt", ".claude/kit.toml"):
            self.assertFalse(os.path.exists(os.path.join(repo, rel)), rel)

    def test_s1_default_folder_is_the_current_one(self):
        repo = self._repo()
        env, _ = self._env()
        out = self._run(env, "--relay-folder", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self._status(repo), ["?? .relay/README.md"])

    def test_s2_existing_readme_is_left_alone(self):
        repo = self._repo()
        env, settings = self._env()
        os.makedirs(os.path.join(repo, ".relay"))
        with open(os.path.join(repo, ".relay", "README.md"), "w") as handle:
            handle.write("mine\n")
        before = open(settings, "rb").read()
        out = self._run(env, "--relay-folder", repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(open(os.path.join(repo, ".relay", "README.md")).read(), "mine\n")
        self.assertEqual(self._status(repo), ["?? .relay/README.md"])   # still just the pre-existing file, nothing added
        self.assertEqual(open(settings, "rb").read(), before)

    def test_relay_folder_refuses_other_flags_and_a_missing_folder(self):
        env, _ = self._env()
        out = self._run(env, "--relay-folder", "--flow", "none", self._repo())
        self.assertEqual(out.returncode, 2)
        out = self._run(env, "--relay-folder", os.path.join(self.tmp, "nope"))
        self.assertEqual(out.returncode, 2)

    def test_s3_plain_setup_still_writes_kit_toml_settings_and_readme(self):
        import relay_setup
        repo = self._repo()
        d, flow, product, done, todo = relay_setup.setup(repo, flow="none", product=False)
        self.assertTrue(os.path.isfile(os.path.join(repo, ".claude", "kit.toml")))
        self.assertTrue(os.path.isfile(os.path.join(repo, ".claude", "settings.json")))
        self.assertTrue(os.path.isfile(os.path.join(repo, ".relay", "README.md")))


    def test_f10_migrate_plan_and_apply_leave_the_relay_folder_out(self):
        """Review F10: `relay migrate` (a plan, and --apply) does the plain setup but writes no .relay/ (not Kartoteka's)."""
        import relay_setup
        for apply in (False, True):
            repo = self._repo() if not apply else os.path.join(self.tmp, "second")
            if apply:
                os.makedirs(repo)
                subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
            relay_setup.migrate(repo, apply=apply, flow="none", product=False)
            self.assertTrue(os.path.isfile(os.path.join(repo, ".claude", "kit.toml")), apply)       # the rest of setup ran
            self.assertFalse(os.path.exists(os.path.join(repo, ".relay")), apply)
        relay_setup.setup(repo, flow="none", product=False)                                      # relay setup of that one project does
        self.assertTrue(os.path.isfile(os.path.join(repo, ".relay", "README.md")))


class DefaultBranch(unittest.TestCase):
    """T18: relay_git.default_branch is never the current branch (design fact 2.8)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-git-test-"))
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_AUTHOR_NAME="t",
                        GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        sys.modules.pop("relay_git", None)
        import relay_git
        self.relay_git = relay_git

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, repo, *args):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=self.env)

    def repo(self, name, *branches):
        """A repository whose first commit is on branches[0]; the others are local branches at the same commit."""
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        subprocess.run(["git", "init", "-q", "-b", branches[0], d], check=True, env=self.env)
        self.git(d, "commit", "-q", "--allow-empty", "-m", "init")
        for b in branches[1:]:
            self.git(d, "branch", b)
        return d

    def kit(self, repo, branch):
        os.makedirs(os.path.join(repo, ".claude"))
        with open(os.path.join(repo, ".claude", "kit.toml"), "w") as handle:
            handle.write('[project]\ndefault_branch = "%s"\n' % branch)

    def test_only_develop_with_binding(self):
        d = self.repo("a", "develop")
        self.assertIsNone(self.relay_git.default_branch(d))   # no binding, no master/main: none, not the current branch
        self.kit(d, "develop")
        self.assertEqual(self.relay_git.default_branch(d), "develop")

    def test_worktree_on_task_branch_gets_master(self):
        d = self.repo("relay-like", "master")
        self.git(d, "worktree", "add", "-q", os.path.join(d, ".worktrees", "review-gate"), "-b", "wt/review-gate")
        wt = os.path.join(d, ".worktrees", "review-gate")
        self.assertEqual(self.relay_git.default_branch(wt), "master")   # setup's default_branch answers wt/review-gate here
        self.assertEqual(self.relay_git.main_checkout(wt), d)

    def test_master_and_main_prefers_master(self):
        self.assertEqual(self.relay_git.default_branch(self.repo("b", "main", "master")), "master")

    def test_main_alone(self):
        self.assertEqual(self.relay_git.default_branch(self.repo("m", "main")), "main")

    def test_binding_naming_a_task_branch_is_ignored(self):
        d = self.repo("c", "master")
        self.kit(d, "wt/x")
        self.assertEqual(self.relay_git.default_branch(d), "master")

    def test_origin_head_wins_over_binding(self):
        d = self.repo("o", "master")
        self.kit(d, "develop")
        self.git(d, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.git(d, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.assertEqual(self.relay_git.default_branch(d), "trunk")

    def test_unreadable_kit_toml_is_ignored(self):
        d = self.repo("u", "develop")
        os.makedirs(os.path.join(d, ".claude"))
        with open(os.path.join(d, ".claude", "kit.toml"), "w") as handle:
            handle.write("[project\n")
        self.assertIsNone(self.relay_git.default_branch(d))

    def test_outside_a_repository(self):
        self.assertIsNone(self.relay_git.default_branch(self.tmp))
        self.assertIsNone(self.relay_git.main_checkout(self.tmp))


class TestTasteRule(unittest.TestCase):
    """The experimental taste rule is loaded by the relay project's CLAUDE.local.md and by no other target."""

    def _targets(self):
        import relay_config
        return relay_config.read_toml(os.path.join(ROOT, "projects.toml"))

    def test_rule_has_the_shape(self):
        import relay_rules
        self.assertEqual(relay_rules.rules()["taste"]["title"], "Taste (experimental)")

    def test_global_file_does_not_list_taste_but_still_lists_the_others(self):
        # F2: a rule only relay loads stays out of the global read list; the rest of the list is unchanged
        import relay_rules, relay_config
        text = relay_rules.render_target("global", self._targets()["global"], relay_rules.rules(), relay_config.active_profile())
        self.assertNotIn("Taste", text)
        for title in ("OpenSpec", "Product work", "Quality gate", "Work queue", "Structured data"):
            self.assertIn(f"**{title}", text)

    def test_a_new_rule_still_reaches_the_global_read_list(self):
        import relay_rules
        rules = {"a": {"title": "A", "gist": "g.", "body": "b", "path": "/x/a.md"},
                 "b": {"title": "B", "gist": "g.", "body": "b", "path": "/x/b.md"}}
        text = relay_rules.render_target("global", {"load": [], "skip": ["b"]}, rules, {})
        self.assertIn("**A**", text)
        self.assertNotIn("**B**", text)

    def test_global_target_writes_the_native_language_line_only_when_the_key_is_set(self):
        import relay_rules
        rules = {"a": {"title": "A", "gist": "g.", "body": "b", "path": "/x/a.md"}}
        with_key = relay_rules.render_target("global", {"load": [], "native_language": "Russian"}, rules, {})
        self.assertIn("My native language: Russian.\n", with_key)
        without = relay_rules.render_target("global", {"load": []}, rules, {})
        self.assertNotIn("native language", without)
        # a project target never carries it, and relay's own projects.toml sets it for the real global target
        self.assertNotIn("native language", relay_rules.render_target("demo", {"load": [], "native_language": "Russian"}, rules, {}))
        self.assertEqual(self._targets()["global"]["native_language"], "Russian")

    def test_only_the_relay_target_loads_it(self):
        # relay is the one project target whose load names taste; the global profile loads none of it
        loaders = sorted(name for name, spec in self._targets().items() if "taste" in spec.get("load", []))
        self.assertEqual(loaders, ["relay"])
        import relay_config
        for profile in sorted(n for n in os.listdir(os.path.join(ROOT, "profiles")) if n.endswith(".toml")):
            data = relay_config.read_toml(os.path.join(ROOT, "profiles", profile))
            self.assertNotIn("taste", data.get("rules", {}).get("load", []), profile)

    def test_relay_target_renders_the_rule_in_full_and_nothing_else(self):
        import relay_rules
        spec = self._targets()["relay"]
        text = relay_rules.render_target("relay", spec, relay_rules.rules(), {})
        self.assertIn("## Taste (experimental)", text)
        self.assertIn("You have taste for waste.", text)
        self.assertNotIn("Rules to read when they apply", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
