"""relay metrics window (lib/relay_metrics.py): coverage and reversed windows. No repository is touched; git answers are stubbed."""
import os
import sys
import time
import unittest
from datetime import datetime
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import relay_metrics  # noqa: E402


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def fake_git(commits):
    """commits: {log file name: (commit time, coverage percent)}; answers the two git calls coverage_by_week makes."""
    def git(main, *args):
        if args[0] == "grep":
            return 0, "".join(f"rev:.relay/checks/{n}:ci: coverage {v}%\n" for n, (_, v) in commits.items())
        return 0, "".join(f"@{int(t)}\n\n.relay/checks/{n}\n" for n, (t, _) in commits.items())
    return git


class Window(unittest.TestCase):
    def run_summary(self, commits, **kw):
        with mock.patch.object(relay_metrics, "stored", return_value=[]), mock.patch.object(relay_metrics.relay_git, "git", fake_git(commits)):
            return relay_metrics.summary("m", "rev", now=utc("2026-10-29T13:00:00Z"), **kw)

    def test_coverage_outside_the_window_makes_no_block(self):
        # window 10:00-13:00: the 08:30 log is outside (no 08 block), the 10:20 log (85%) is inside the 10 block
        lines = self.run_summary({"a.gate.log": (utc("2026-10-29T08:30:00Z"), 70.0), "b.gate.log": (utc("2026-10-29T10:20:00Z"), 85.0)}, since="3h", by="hour")
        self.assertEqual(lines[1:], ["2026-10-29T10:", "  coverage: median 85.0% over 1 gates", "2026-10-29T11:", "  nothing recorded", "2026-10-29T12:", "  nothing recorded"])

    def test_coverage_at_until_is_not_counted(self):
        lines = self.run_summary({"a.gate.log": (utc("2026-10-29T11:30:00Z"), 80.0)}, since="2026-10-29T10:00:00Z", until="2026-10-29T11:00:00Z", by="hour")
        self.assertEqual(lines[1:], ["2026-10-29T10:", "  nothing recorded"])

    def test_no_window_keeps_coverage_by_week(self):
        lines = self.run_summary({"a.gate.log": (utc("2026-10-29T08:30:00Z"), 70.0)})
        self.assertEqual(lines[1:], ["2026-W44:", "  coverage: median 70.0% over 1 gates"])

    def test_reversed_or_empty_window_is_refused(self):
        # now 13:00: --since 1d = Oct 28 13:00, --until 2d = Oct 27 13:00, so since is after until
        for since, until in (("1d", "2d"), ("2026-10-29T10:00:00Z", "2026-10-29T10:00:00Z")):
            with self.assertRaises(ValueError) as caught:
                self.run_summary({}, since=since, until=until, by="day")
            self.assertIn("--since", str(caught.exception))
            self.assertIn("--until", str(caught.exception))

    def test_forward_window_gives_two_day_blocks(self):
        lines = self.run_summary({}, since="2d", until="1d", by="day")
        self.assertEqual(lines[1:], ["2026-10-27:", "  nothing recorded", "2026-10-28:", "  nothing recorded"])

    def test_long_hourly_window_is_fast_and_unique(self):
        # 2 years of hours = 17544 labels, each once; the old list scan took seconds
        began = time.process_time()
        labels = relay_metrics._bucket_labels(utc("2024-01-01T00:00:00Z"), utc("2026-01-01T00:00:00Z"), "hour")
        self.assertEqual((len(labels), len(set(labels))), (731 * 24, 731 * 24))
        self.assertLess(time.process_time() - began, 2.0)


if __name__ == "__main__":
    unittest.main()
