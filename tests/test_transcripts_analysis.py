"""Library tests: transcripts, analysis, ledger."""
import datetime as dt
import json
import os
import sys
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import Base, ROOT  # noqa: E402
import fixtures


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

    def write_front_session(self, requests: int, turns: int, name: str = "sf", scripted: bool = False) -> dt.datetime:
        """A main session of `turns` owner turns with `requests` front requests, each with one Bash call."""
        base = dt.datetime(2026, 10, 18, 9, 0, tzinfo=dt.timezone.utc)
        folder = os.path.join(self.claude, "projects", "p")
        os.makedirs(folder, exist_ok=True)
        lines = [fixtures.user(fixtures._ts(base, t), f"ask {t}") for t in range(turns)]
        lines += [fixtures.assistant(fixtures._ts(base, 1 + i * 0.01), "claude-opus-5", 1000, 0, 10, f"r{i}",
                                     tools=[("Bash", {"command": "ls"})]) for i in range(requests)]
        with open(os.path.join(folder, f"{name}.jsonl"), "w") as handle:
            for line in lines:
                line["sessionId"] = name
                if scripted:
                    line["entrypoint"] = "sdk-cli"
                handle.write(json.dumps(line) + "\n")
        return base

    def test_front_requests_per_turn_are_reported_and_flagged_over_the_target(self):
        import relay_analyze
        # 2 turns, 40 requests, 40 Bash calls: 20 requests and 20 tool calls per turn; 20 > the target of 15
        base = self.write_front_session(40, 2)
        window = (base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        data = relay_analyze.collect(self.claude, *window)
        text = relay_analyze.report(data)
        self.assertIn("20.0 requests, 20.0 tool calls", text)
        self.assertIn("ABOVE the target", text)
        f10 = [f for f in relay_analyze.findings(data) if f["id"] == "F10"]
        self.assertEqual(len(f10), 1)
        self.assertIn("20.0 front requests", f10[0]["evidence"])
        self.assertIn("front requests per turn", relay_analyze.compare(data, data))

    def test_front_within_the_target_is_not_flagged(self):
        import relay_analyze
        # 2 turns, 20 requests: 10 per turn, under 15
        base = self.write_front_session(20, 2)
        data = relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        text = relay_analyze.report(data)
        self.assertIn("10.0 requests", text)
        self.assertNotIn("ABOVE the target", text)
        self.assertNotIn("F10", {f["id"] for f in relay_analyze.findings(data)})

    def test_scripted_sessions_do_not_count_as_the_front(self):
        import relay_analyze
        # interactive: 10 turns, 100 requests = 10.0 per turn (under 15); a scripted run of 80 requests has its turns
        # zeroed, so counting its requests would give 180 / 10 = 18.0 per turn and a false flag
        base = self.write_front_session(100, 10)
        self.write_front_session(80, 3, name="bench", scripted=True)
        data = relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        text = relay_analyze.report(data)
        self.assertIn("10.0 requests", text)
        self.assertNotIn("ABOVE the target", text)
        self.assertNotIn("F10", {f["id"] for f in relay_analyze.findings(data)})
        self.assertEqual(relay_analyze.totals(data)["front_requests"], 100)

    def test_only_scripted_sessions_have_no_front_line(self):
        import relay_analyze
        base = self.write_front_session(80, 3, name="bench", scripted=True)
        data = relay_analyze.collect(self.claude, base - dt.timedelta(days=1), base + dt.timedelta(days=1))
        self.assertNotIn("Front (main session)", relay_analyze.report(data))
        self.assertNotIn("F10", {f["id"] for f in relay_analyze.findings(data)})

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
        self.assertEqual(ra.classify("delegate:worker"), "build")
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
