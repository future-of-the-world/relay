"""Sonnet cache reads cost 0.20 per million until 2026-10-09 and 0.10 after (prices.toml, [models.sonnet.before]).
`relay calibrate` had priced old sessions at the new rate and put three of them 3-21% under Claude Code's total;
it was not a long-context price (no Sonnet request in them passes 200k tokens). The numbers below are worked by hand."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import relay_analyze  # noqa: E402
import relay_prices  # noqa: E402
import relay_transcripts as tr  # noqa: E402

SONNET = "claude-sonnet-5-5"
READS = {"cache_read_input_tokens": 1_000_000}


class SonnetPriceHistory(unittest.TestCase):
    def test_cost_blends_the_earlier_cache_read_price(self):
        # 1M reads: all earlier = 1 x 0.20 = 0.20; half = 0.5 x 0.20 + 0.5 x 0.10 = 0.15; none = 0.10
        self.assertAlmostEqual(relay_prices.cost(SONNET, READS, early_share=1.0), 0.20)
        self.assertAlmostEqual(relay_prices.cost(SONNET, READS, early_share=0.5), 0.15)
        self.assertAlmostEqual(relay_prices.cost(SONNET, READS), 0.10)

    def test_other_models_have_no_earlier_price(self):
        self.assertAlmostEqual(relay_prices.cost("claude-opus-5-5", READS, early_share=1.0), 0.20)  # opus reads are 0.20 always
        self.assertAlmostEqual(relay_prices.cost("claude-haiku-5-5", READS, early_share=1.0), 0.01)

    def test_request_before_the_date_is_earlier(self):
        early, late = tr.Agg(), tr.Agg()
        early.add(SONNET, READS, when="2026-10-08T12:36:57.967Z")
        late.add(SONNET, READS, when="2026-10-12T10:37:43.416Z")
        self.assertEqual((early.early_reads, late.early_reads), (1_000_000, 0))
        self.assertAlmostEqual(early.cost, 0.20)
        self.assertAlmostEqual(late.cost, 0.10)

    def test_calibration_prices_an_early_session_at_the_earlier_rate(self):
        # Claude Code's total for a session with 1M Sonnet reads, all before the date: 1M x 0.20 = $0.20.
        agg = tr.Agg()
        agg.add(SONNET, READS, when="2026-10-06T11:51:46Z")
        main = tr.Trace(path="", kind="session")
        main.by_model[SONNET] = agg
        err, _basis = relay_analyze.price_error(SONNET, {"cost_usd": 0.20, **READS}, main, [])
        self.assertAlmostEqual(err, 0.0)

    def test_calibration_of_a_session_across_the_date(self):
        # 3M reads in all; the transcripts show 1M before the date and 1M after (hidden requests unseen), so half
        # the reads were earlier: 1.5M x 0.20 + 1.5M x 0.10 = 0.45.
        agg = tr.Agg()
        agg.add(SONNET, READS, when="2026-09-29T00:00:00Z")
        agg.add(SONNET, READS, when="2026-10-15T00:00:00Z")
        main = tr.Trace(path="", kind="session")
        main.by_model[SONNET] = agg
        numbers = {"cost_usd": 0.45, "cache_read_input_tokens": 3_000_000}
        err, _basis = relay_analyze.price_error(SONNET, numbers, main, [])
        self.assertAlmostEqual(err, 0.0)


if __name__ == "__main__":
    unittest.main()
