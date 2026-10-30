"""The routing guard's running count: an open agent silent for 10 minutes has ended and stops counting."""
import datetime as dt
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import ROOT  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_ledger  # noqa: E402

NOW = dt.datetime(2026, 10, 26, 20, 0, tzinfo=dt.timezone.utc)


def at(minutes_ago: float) -> str:
    return (NOW - dt.timedelta(minutes=minutes_ago)).isoformat()


def start(agent: str, minutes_ago: float) -> dict:
    return {"event": "agent_start", "session_id": "s", "agent_id": agent, "ts": at(minutes_ago)}


def stop(agent: str, minutes_ago: float) -> dict:
    return {"event": "agent_stop", "session_id": "s", "agent_id": agent, "ts": at(minutes_ago)}


def load_guard() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("route_guard_running", os.path.join(ROOT, "plugins", "delegate", "hooks", "route-guard.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunningNow(unittest.TestCase):
    def count(self, events: list) -> int:
        guard = load_guard()
        with mock.patch.object(relay_ledger, "read", return_value=events):
            return guard.running_now("s", NOW)

    def dead_workflow(self) -> list:
        # 7 starts an hour ago, last seen 50 minutes ago (over the 10-minute limit), no stops
        return [start("w%d" % i, 60) for i in range(7)] + [
            {"event": "tool_post", "session_id": "s", "agent_id": "w%d" % i, "ts": at(50)} for i in range(7)]

    def test_dead_agents_without_stop_do_not_count(self) -> None:
        events = self.dead_workflow() + [start("live", 3)]
        self.assertEqual(self.count(events), 1)   # 7 idle for 50 min dropped; the one started 3 min ago stays

    def test_stopped_agents_do_not_count(self) -> None:
        events = [start("w%d" % i, 5) for i in range(7)] + [stop("w%d" % i, 4) for i in range(7)] + [start("live", 3)]
        self.assertEqual(self.count(events), 1)

    def test_two_live_agents_count_two(self) -> None:
        self.assertEqual(self.count([start("a", 8), start("b", 1)]), 2)   # 8 min < 10 min limit

    def test_cap_still_fires_when_agents_really_run(self) -> None:
        events = [start("a%d" % i, 2) for i in range(6)]
        self.assertEqual(self.count(events), 6)   # six live agents: the guard's cap of 6 is reached

    def test_recent_tool_event_keeps_an_old_agent(self) -> None:
        events = [start("long", 90), {"event": "tool_pre", "session_id": "s", "agent_id": "long", "ts": at(4)}]
        self.assertEqual(self.count(events), 1)

    def test_start_alone_older_than_limit_does_not_count(self) -> None:
        self.assertEqual(self.count([start("x", 30)]), 0)   # started 30 min ago, never seen again: over the 10-minute limit

    def test_start_alone_within_limit_counts(self) -> None:
        self.assertEqual(self.count([start("x", 3)]), 1)   # started 3 min ago: still within the limit


if __name__ == "__main__":
    unittest.main()
