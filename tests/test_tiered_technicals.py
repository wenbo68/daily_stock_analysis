# -*- coding: utf-8 -*-
"""Offline deterministic tests for the tiered-analysis technicals provider.

No numpy/pandas/network: indicators are pure Python and bars are injected
fixtures, per the numeric-vs-textual rule in docs/tiered-analysis-design.md.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.providers.base import Coverage, SourceKind
from src.tiered_analysis.providers.technicals import (
    Bar,
    TechnicalsProvider,
    compute_atr,
    compute_bias,
    compute_ema,
    compute_macd,
    compute_score,
    compute_sma,
    compute_wilder_rsi,
)

# Classic 14-period RSI walkthrough dataset (Wilder's method, as popularized
# by the StockCharts RSI example): first RSI value is 70.46.
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
    45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
]


def _flat_bars(count: int, close: float = 100.0, spread: float = 2.0) -> list:
    """Bars with constant close and constant high-low range."""
    return [
        Bar(high=close + spread / 2, low=close - spread / 2, close=close)
        for _ in range(count)
    ]


def _trend_bars(closes: list) -> list:
    """Bars derived from a close series with a fixed 1% intraday range."""
    return [
        Bar(high=c * 1.005, low=c * 0.995, close=c)
        for c in closes
    ]


class TestSMA(unittest.TestCase):
    def test_sma_simple_average(self):
        self.assertEqual(compute_sma([1.0, 2.0, 3.0, 4.0], period=4), 2.5)

    def test_sma_uses_most_recent_window(self):
        self.assertEqual(compute_sma([10.0, 1.0, 2.0, 3.0], period=3), 2.0)

    def test_sma_insufficient_data_returns_none(self):
        self.assertIsNone(compute_sma([1.0, 2.0], period=3))


class TestEMA(unittest.TestCase):
    def test_ema_constant_series_equals_constant(self):
        self.assertAlmostEqual(compute_ema([5.0] * 30, period=12), 5.0)

    def test_ema_reacts_toward_recent_values(self):
        ema = compute_ema([1.0] * 20 + [2.0] * 5, period=10)
        self.assertGreater(ema, 1.0)
        self.assertLess(ema, 2.0)

    def test_ema_insufficient_data_returns_none(self):
        self.assertIsNone(compute_ema([1.0] * 5, period=10))


class TestWilderRSI(unittest.TestCase):
    def test_rsi_matches_wilder_textbook_value(self):
        rsi = compute_wilder_rsi(WILDER_CLOSES, period=14)
        self.assertAlmostEqual(rsi, 70.46, places=2)

    def test_rsi_all_gains_is_100(self):
        closes = [float(i) for i in range(1, 20)]
        self.assertEqual(compute_wilder_rsi(closes, period=14), 100.0)

    def test_rsi_all_losses_is_0(self):
        closes = [float(i) for i in range(20, 1, -1)]
        self.assertEqual(compute_wilder_rsi(closes, period=14), 0.0)

    def test_rsi_insufficient_data_returns_none(self):
        self.assertIsNone(compute_wilder_rsi([1.0, 2.0, 3.0], period=14))


class TestMACD(unittest.TestCase):
    def test_macd_constant_series_is_zero(self):
        macd = compute_macd([50.0] * 60)
        self.assertAlmostEqual(macd["macd"], 0.0)
        self.assertAlmostEqual(macd["signal"], 0.0)
        self.assertAlmostEqual(macd["histogram"], 0.0)

    def test_macd_positive_in_uptrend(self):
        closes = [100.0 * (1.01 ** i) for i in range(60)]
        macd = compute_macd(closes)
        self.assertGreater(macd["macd"], 0.0)

    def test_macd_insufficient_data_returns_none(self):
        self.assertIsNone(compute_macd([1.0] * 10))


class TestATR(unittest.TestCase):
    def test_atr_constant_range_equals_range(self):
        bars = _flat_bars(30, close=100.0, spread=2.0)
        self.assertAlmostEqual(compute_atr(bars, period=14), 2.0)

    def test_atr_includes_gap_in_true_range(self):
        # A gap up: true range must use previous close, not just high-low.
        bars = _flat_bars(20, close=100.0, spread=2.0)
        bars.append(Bar(high=111.0, low=110.0, close=110.5))
        atr_with_gap = compute_atr(bars, period=14)
        self.assertGreater(atr_with_gap, 2.0)

    def test_atr_insufficient_data_returns_none(self):
        self.assertIsNone(compute_atr(_flat_bars(5), period=14))


class TestBIAS(unittest.TestCase):
    def test_bias_above_sma_is_positive(self):
        closes = [100.0] * 19 + [110.0]
        bias = compute_bias(closes, period=20)
        self.assertGreater(bias, 0.0)

    def test_bias_at_sma_is_zero(self):
        self.assertAlmostEqual(compute_bias([100.0] * 20, period=20), 0.0)

    def test_bias_insufficient_data_returns_none(self):
        self.assertIsNone(compute_bias([100.0] * 5, period=20))


class TestCompositeScore(unittest.TestCase):
    def _score(self, closes: list) -> float:
        return compute_score(_trend_bars(closes))

    def test_score_bounded_0_100(self):
        for closes in (
            [100.0 * (1.03 ** i) for i in range(80)],   # parabolic rise
            [100.0 * (0.97 ** i) for i in range(80)],   # steady fall
            [100.0] * 80,                                # flat
        ):
            score = self._score(closes)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_score_ranks_pullback_over_overbought_over_downtrend(self):
        # Healthy uptrend that recently pulled back a little.
        pullback = [100.0 * (1.01 ** i) for i in range(70)]
        pullback += [pullback[-1] * (0.995 ** i) for i in range(1, 6)]
        # Overbought straight-line: relentless steep rise, RSI pinned high.
        overbought = [100.0 * (1.025 ** i) for i in range(75)]
        # Downtrend.
        downtrend = [100.0 * (0.985 ** i) for i in range(75)]

        s_pullback = self._score(pullback)
        s_overbought = self._score(overbought)
        s_downtrend = self._score(downtrend)

        self.assertGreater(s_pullback, s_overbought)
        self.assertGreater(s_overbought, s_downtrend)
        self.assertLess(s_downtrend, 50.0)


class TestTechnicalsProvider(unittest.TestCase):
    def test_provider_is_numeric(self):
        provider = TechnicalsProvider(bars_loader=lambda symbol: [])
        self.assertEqual(provider.kind, SourceKind.NUMERIC)
        self.assertEqual(provider.dimension, "technicals")

    def test_collect_full_coverage_payload(self):
        closes = [100.0 * (1.005 ** i) for i in range(80)]
        provider = TechnicalsProvider(
            bars_loader=lambda symbol: _trend_bars(closes),
        )
        result = provider.collect("AAPL")
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertTrue(result.is_actionable)
        payload = result.payload
        for key in ("sma_20", "ema_12", "rsi_14", "macd", "atr_14", "bias_20", "score"):
            self.assertIn(key, payload)
        self.assertIsNotNone(payload["atr_14"])
        self.assertEqual(len(result.citations), 1)  # cites the data source

    def test_collect_insufficient_bars_is_unavailable_not_silent(self):
        provider = TechnicalsProvider(bars_loader=lambda symbol: _flat_bars(3))
        result = provider.collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertFalse(result.is_actionable)
        self.assertTrue(result.warnings)

    def test_collect_loader_failure_is_unavailable_with_warning(self):
        def _boom(symbol):
            raise RuntimeError("source down")

        provider = TechnicalsProvider(bars_loader=_boom)
        result = provider.collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertFalse(result.is_actionable)
        self.assertTrue(any("source down" in w for w in result.warnings))

    def test_collect_short_history_is_partial(self):
        # Enough for RSI/ATR but not for SMA-60: partial, still actionable.
        closes = [100.0 * (1.005 ** i) for i in range(30)]
        provider = TechnicalsProvider(
            bars_loader=lambda symbol: _trend_bars(closes),
        )
        result = provider.collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertTrue(result.is_actionable)
        self.assertIsNone(result.payload["sma_60"])


if __name__ == "__main__":
    unittest.main()
