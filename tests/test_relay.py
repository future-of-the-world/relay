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
        owner_quotes = "tune-stage still fires on <task-notification> prompts, fix it"
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
                 fixtures.user("2026-10-18T09:02:00Z", "<command-name>/clear</command-name>\n            <command-message>clear</command-message>\n            <command-args></command-args>"),
                 fixtures.user("2026-10-18T09:02:10Z", "<local-command-caveat>Caveat: the messages below were generated by the user while running local commands.</local-command-caveat>"),
                 fixtures.user("2026-10-18T09:02:20Z", "<local-command-stdout>Total cost: $1</local-command-stdout>"),
                 fixtures.user("2026-10-18T09:02:30Z", "<bash-input>ls</bash-input>"),
                 fixtures.user("2026-10-18T09:02:40Z", "<bash-stdout>a b</bash-stdout><bash-stderr></bash-stderr>"),
                 dict(fixtures.user("2026-10-18T09:03:00Z", "<task-notification>done</task-notification>"), origin={"kind": "task-notification"}),
                 dict(fixtures.user("2026-10-18T09:03:30Z", "something the system injected"), origin={"kind": "system"}),
                 fixtures.user("2026-10-18T09:04:00Z", "<command-message>opsx:apply</command-message>\n<command-name>/opsx:apply</command-name>\n<command-args>x</command-args>")]
        with open(path, "w") as handle:
            handle.write("".join(json.dumps(l) + "\n" for l in lines))
        self.assertEqual(tr.read_trace(path).user_turns, 3)      # the typed text, the accepted suggestion, /opsx:apply

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
        env = dict(os.environ, RELAY_CLAUDE_JSON=os.path.join(self.claude, ".claude.json"))
        hook = os.path.join(ROOT, "plugins", "observe", "hooks", "ledger.py")
        payload = json.dumps({"hook_event_name": "SessionEnd", "session_id": "s-end", "cwd": "/Users/me/x", "reason": "other"})
        started = time.monotonic()
        subprocess.run([sys.executable, hook], input=payload.encode(), env=env, check=True)
        took = time.monotonic() - started
        self.assertLess(took, 0.5, "SessionEnd hook took %.2f s on a 300,000-line ledger" % took)
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


class Agents(unittest.TestCase):
    def test_judge_agents_have_room_and_write_their_file_early(self):
        """Two Opus agents once ran out of turns with no report: critic and thinker get 60 and must start the file early."""
        import re
        for name in ("critic", "thinker"):
            with open(os.path.join(ROOT, "plugins", "delegate", "agents", name + ".md"), encoding="utf-8") as handle:
                text = handle.read()
            self.assertEqual(re.search(r"(?m)^maxTurns: (\d+)$", text).group(1), "60", name)
            self.assertIn("within your first 10 tool calls", text, name)
            self.assertIn("append to it as you go", text, name)


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


if __name__ == "__main__":
    unittest.main(verbosity=1)
