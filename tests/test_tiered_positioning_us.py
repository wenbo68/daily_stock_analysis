# -*- coding: utf-8 -*-
"""Offline tests for the US positioning provider.

Pure-function coverage (short interest, ownership, insider window,
options ratios) plus the provider's explicit degradation contract:
FULL when all four blocks land, PARTIAL when some fail with warnings,
UNAVAILABLE (never a raise) when everything fails.
"""
from __future__ import annotations

import unittest
from datetime import date

from src.tiered_analysis.providers.base import Coverage, Market, SourceKind
from src.tiered_analysis.providers.positioning import (
    INSIDER_WINDOW_DAYS,
    PositioningUSProvider,
    insider_metrics,
    options_metrics,
    ownership_metrics,
    short_interest_metrics,
)

# 2026-07-01 as unix seconds (UTC midnight) for the as_of conversion.
_SHORT_INTEREST_EPOCH = 1782864000

_INFO = {
    "sharesShort": 50_000_000,
    "sharesShortPriorMonth": 40_000_000,
    "shortPercentOfFloat": 0.031,
    "shortRatio": 1.8,
    "floatShares": 1_600_000_000,
    "sharesOutstanding": 1_700_000_000,
    "heldPercentInstitutions": 0.6155,
    "heldPercentInsiders": 0.021,
    "dateShortInterest": _SHORT_INTEREST_EPOCH,
}

_HOLDERS = [{"pctHeld": 0.05}, {"pctHeld": 0.04}, {"pctHeld": 0.03}]

_TODAY = date(2026, 7, 24)

_INSIDER_ROWS = [
    {"date": "2026-07-01", "text": "Purchase at price 100.00 per share.",
     "shares": 1000, "value": 100_000},
    {"date": "2026-06-15", "text": "Sale at price 110.00 per share.",
     "shares": 400, "value": 44_000},
    # Not an open-market trade: must be ignored.
    {"date": "2026-06-20", "text": "Stock Award (Grant)", "shares": 9999,
     "value": None},
    # Outside the six-month window: must be ignored.
    {"date": "2025-12-01", "text": "Sale at price 90.00 per share.",
     "shares": 5000, "value": 450_000},
    # Unparseable date: must be skipped, not crash.
    {"date": None, "text": "Purchase at price 95.00 per share.",
     "shares": 10, "value": 950},
]

_CHAINS = [
    {"expiration": "2026-08-21", "call_oi": 1000.0, "put_oi": 800.0,
     "call_volume": 200.0, "put_volume": 300.0},
    {"expiration": "2026-09-18", "call_oi": 500.0, "put_oi": 580.0,
     "call_volume": 100.0, "put_volume": 60.0},
]


class ShortInterestMetricsTest(unittest.TestCase):
    def test_fractions_become_percentages_and_epochs_become_dates(self):
        metrics = short_interest_metrics(_INFO)
        self.assertAlmostEqual(metrics["short_pct_of_float"], 3.1)
        self.assertEqual(metrics["days_to_cover"], 1.8)
        self.assertEqual(metrics["shares_short"], 50_000_000)
        self.assertAlmostEqual(metrics["change_vs_prior_month_pct"], 25.0)
        self.assertEqual(metrics["as_of"], "2026-07-01")

    def test_short_pct_falls_back_to_shares_over_float(self):
        info = dict(_INFO)
        del info["shortPercentOfFloat"]
        metrics = short_interest_metrics(info)
        self.assertAlmostEqual(metrics["short_pct_of_float"], 3.125)

    def test_missing_prior_month_yields_no_change(self):
        info = {k: v for k, v in _INFO.items() if k != "sharesShortPriorMonth"}
        self.assertIsNone(short_interest_metrics(info)["change_vs_prior_month_pct"])

    def test_nan_values_are_treated_as_missing(self):
        metrics = short_interest_metrics({"shortRatio": float("nan")})
        self.assertIsNone(metrics["days_to_cover"])


class OwnershipMetricsTest(unittest.TestCase):
    def test_percentages_and_top10_concentration(self):
        metrics = ownership_metrics(_INFO, _HOLDERS)
        self.assertAlmostEqual(metrics["institutional_pct"], 61.55)
        self.assertAlmostEqual(metrics["insider_pct"], 2.1)
        self.assertAlmostEqual(metrics["top10_institutions_pct"], 12.0)
        self.assertEqual(metrics["float_shares"], 1_600_000_000)
        self.assertEqual(metrics["shares_outstanding"], 1_700_000_000)

    def test_only_the_ten_largest_holders_count(self):
        holders = [{"pctHeld": 0.01}] * 15
        metrics = ownership_metrics({}, holders)
        self.assertAlmostEqual(metrics["top10_institutions_pct"], 10.0)

    def test_older_yfinance_percent_out_key_is_accepted(self):
        metrics = ownership_metrics({}, [{"% Out": 0.07}])
        self.assertAlmostEqual(metrics["top10_institutions_pct"], 7.0)

    def test_no_holders_leaves_concentration_none(self):
        self.assertIsNone(ownership_metrics(_INFO, None)["top10_institutions_pct"])
        self.assertIsNone(ownership_metrics(_INFO, [])["top10_institutions_pct"])


class InsiderMetricsTest(unittest.TestCase):
    def test_open_market_trades_inside_the_window_are_netted(self):
        metrics = insider_metrics(_INSIDER_ROWS, _TODAY)
        self.assertEqual(metrics["buy_count"], 1)
        self.assertEqual(metrics["sell_count"], 1)
        self.assertEqual(metrics["net_shares"], 600.0)
        self.assertEqual(metrics["net_value_usd"], 56_000.0)

    def test_the_window_edge_is_inclusive(self):
        edge = (_TODAY - date.resolution * INSIDER_WINDOW_DAYS).isoformat()
        rows = [{"date": edge, "text": "Purchase at price 1.00 per share.",
                 "shares": 5, "value": 5}]
        self.assertEqual(insider_metrics(rows, _TODAY)["buy_count"], 1)

    def test_no_trades_is_zeros_not_blanks(self):
        metrics = insider_metrics([], _TODAY)
        self.assertEqual(metrics["buy_count"], 0)
        self.assertEqual(metrics["sell_count"], 0)
        self.assertEqual(metrics["net_shares"], 0.0)


class OptionsMetricsTest(unittest.TestCase):
    def test_ratios_are_summed_over_all_fetched_expirations(self):
        metrics = options_metrics(_CHAINS)
        self.assertAlmostEqual(metrics["put_call_oi_ratio"], 1380.0 / 1500.0)
        self.assertAlmostEqual(metrics["put_call_volume_ratio"], 1.2)
        self.assertEqual(metrics["total_open_interest"], 2880.0)
        self.assertEqual(metrics["expirations_covered"], 2)

    def test_zero_call_side_yields_none_not_a_crash(self):
        chains = [{"call_oi": 0, "put_oi": 10, "call_volume": 0, "put_volume": 5}]
        metrics = options_metrics(chains)
        self.assertIsNone(metrics["put_call_oi_ratio"])
        self.assertIsNone(metrics["put_call_volume_ratio"])


def _provider(**overrides):
    loaders = {
        "info_loader": lambda symbol: _INFO,
        "holders_loader": lambda symbol: _HOLDERS,
        "insider_loader": lambda symbol: _INSIDER_ROWS,
        "options_loader": lambda symbol: _CHAINS,
        "today": lambda: _TODAY,
    }
    loaders.update(overrides)
    return PositioningUSProvider(**loaders)


def _boom(symbol):
    raise RuntimeError("boom")


class ProviderTest(unittest.TestCase):
    def test_supports_us_only(self):
        provider = _provider()
        self.assertTrue(provider.supports(Market.US))
        for market in (Market.CN, Market.HK, Market.JP, Market.UNKNOWN):
            self.assertFalse(provider.supports(market))

    def test_full_coverage_carries_all_four_blocks_and_citations(self):
        result = _provider().collect("AAPL")
        self.assertEqual(result.dimension, "positioning")
        self.assertEqual(result.kind, SourceKind.NUMERIC)
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertTrue(result.is_actionable)
        self.assertEqual(
            sorted(result.payload),
            ["insider_activity_6m", "options", "ownership", "short_interest"],
        )
        self.assertEqual(len(result.citations), 4)
        self.assertEqual(result.warnings, [])

    def test_one_failing_block_degrades_to_partial_with_a_warning(self):
        result = _provider(options_loader=_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertNotIn("options", result.payload)
        self.assertTrue(any("options chain failed" in w for w in result.warnings))

    def test_no_listed_options_is_an_explicit_warning(self):
        result = _provider(options_loader=lambda symbol: []).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertTrue(any("no listed options" in w for w in result.warnings))

    def test_info_failure_takes_out_both_summary_blocks(self):
        result = _provider(info_loader=_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertNotIn("short_interest", result.payload)
        self.assertNotIn("ownership", result.payload)
        # One warning for the shared fetch, not one per block.
        self.assertEqual(
            sum("Yahoo summary failed" in w for w in result.warnings), 1
        )

    def test_empty_info_is_surfaced_never_a_silent_blank(self):
        result = _provider(
            info_loader=lambda symbol: {},
            holders_loader=lambda symbol: [],
        ).collect("AAPL")
        self.assertTrue(
            any("no short-interest fields" in w for w in result.warnings)
        )
        self.assertTrue(any("no ownership fields" in w for w in result.warnings))

    def test_holders_failure_only_degrades_concentration(self):
        result = _provider(holders_loader=_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertIsNone(result.payload["ownership"]["top10_institutions_pct"])
        self.assertTrue(
            any("institutional holders failed" in w for w in result.warnings)
        )

    def test_everything_failing_is_unavailable_not_a_raise(self):
        result = _provider(
            info_loader=_boom, insider_loader=_boom, options_loader=_boom
        ).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertIsNone(result.payload)
        self.assertFalse(result.is_actionable)


if __name__ == "__main__":
    unittest.main()
