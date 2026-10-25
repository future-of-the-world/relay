"""Library tests: the numbers the reports and the ledger give."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

from relay_testbase import Base, ROOT
import fixtures


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

    @staticmethod
    def _recent(clock):
        """A time on yesterday's date: the ledger fallback reads only the last 3 days of the real clock, so a
        literal date would stop being found 3 days after it (these tests failed from 2026-10-24 10:00 on)."""
        day = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        return "%sT%sZ" % (day.strftime("%Y-%m-%d"), clock)

    def test_capture_does_not_write_a_total_smaller_than_the_recorded_one(self):
        """If Claude Code restarts its counter on resume, the new total covers only the resumed part: it must
        not replace the bigger one already recorded (it would be labelled exact for the whole session)."""
        import relay_ledger
        self.SESSION_8_43["claude-opus-5-5"]["cost"] = 9.0
        try:
            self._claude_json("s-r")
        finally:
            self.SESSION_8_43["claude-opus-5-5"]["cost"] = 6.99
        self.assertEqual(relay_ledger.capture(self._recent("09:00:00")), ["s-r"])
        self._claude_json("s-r")                                   # now 6.99: smaller than the 9.00 recorded
        self.assertEqual(relay_ledger.capture(self._recent("10:00:00")), [])
        self.assertEqual(relay_ledger.usage_sessions()["s-r"]["claude-opus-5-5"]["cost_usd"], 9.0)
        os.remove(os.path.join(self.home, "ledger", "usage-index.json"))     # the index is a shortcut, not the truth
        self.assertEqual(relay_ledger.capture(self._recent("10:01:00")), [])

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
            written = relay_ledger.capture(self._recent("%s:00" % when))
            self.assertEqual(written, ["s-g"] if cost == 9.0 else [])
        self.assertEqual(relay_ledger.usage_sessions()["s-g"]["claude-opus-5-5"]["cost_usd"], 9.0)
        self.assertNotIn("s-g", relay_ledger.exact_sessions())          # never exact again, not even the 12.00 in the file
        os.remove(os.path.join(self.home, "ledger", "usage-index.json"))
        self.assertEqual(relay_ledger.capture(self._recent("12:00:00")), [])

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
            self.assertEqual(relay_ledger.capture(self._recent("10:00:00")), ["s-trust"])   # new session
            self.assertEqual(relay_ledger.capture(self._recent("10:01:00")), [])            # recorded session
            with open(index_file, "w") as handle:
                handle.write("{not json")                                                  # corrupt: ledger fallback
            relay_ledger.read = real
            self.assertEqual(relay_ledger.capture(self._recent("10:02:00")), [])
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
        relay_analyze.calibrate(self.claude, "2026-10-21T12:00:00Z")
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
