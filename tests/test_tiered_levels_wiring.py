# -*- coding: utf-8 -*-
"""Offline tests: formula-only levels wired into the tiered run.

Outlook redesign (2026-07-20): the AI level adjuster is retired — levels
are formula bases everywhere. run_tiered_analysis must replace the DSA
sniper levels (LLM prose) with the deterministic bases, attach the
levels_detail audit trail (adjusted always None), and surface level
warnings on the report. Also covers the swing_low_20 payload key the
level formulas depend on.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.earnings import EarningsInfo
from src.tiered_analysis.integration import run_tiered_analysis
from src.tiered_analysis.providers.base import (
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.providers.technicals import (
    Bar,
    TechnicalsProvider,
    compute_swing_low,
)


class _StubProvider(DimensionProvider):
    kind = SourceKind.NUMERIC

    def __init__(self, result):
        self.dimension = result.dimension
        self._result = result

    def supports(self, market):
        return True

    def collect(self, symbol):
        return self._result


def _technicals_dim():
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
        payload={"close": 100.0, "sma_20": 96.0, "sma_60": 90.0,
                 "swing_low_20": 94.0, "atr_14": 3.0},
    )


def _fake_analysis_result():
    return {
        "decision_type": "buy",
        "confidence_level": "0.7",
        "sentiment_score": 72,
        "operation_advice": "buy the pullback",
        "dashboard": {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": 210.0,  # LLM prose level — must NOT survive
                    "secondary_buy": 205.0,
                    "stop_loss": 198.0,
                    "take_profit": 230.0,
                }
            }
        },
    }


def _run(providers=None):
    return run_tiered_analysis(
        "AAPL",
        market=Market.US,
        providers=providers or [_StubProvider(_technicals_dim())],
        analysis_runner=lambda symbol: _fake_analysis_result(),
        log_signal=False,
        earnings_lookup=lambda symbol, market: EarningsInfo(),
    )


class TestLevelsWiring(unittest.TestCase):
    def test_deterministic_bases_replace_dsa_sniper_levels(self):
        outcome = _run()
        levels = outcome.report.levels
        self.assertAlmostEqual(levels.entry, 96.0)  # not 210.0
        self.assertIsNone(levels.secondary_entry)  # backup entry retired
        self.assertAlmostEqual(levels.stop_loss, 90.0)
        self.assertAlmostEqual(levels.take_profit, 108.0)

    def test_detail_present_with_no_adjustments_ever(self):
        outcome = _run()
        detail = outcome.report.levels_detail["levels"]["entry"]
        self.assertAlmostEqual(detail["base"], 96.0)
        self.assertIsNone(detail["adjusted"])
        self.assertIn("support candidates", detail["formula"])

    def test_missing_technicals_leaves_levels_empty_with_warning(self):
        other = DimensionResult(
            dimension="macro_econ", kind=SourceKind.NUMERIC,
            coverage=Coverage.FULL, payload={"x": 1},
        )
        outcome = _run(providers=[_StubProvider(other)])
        self.assertIsNone(outcome.report.levels.entry)
        self.assertTrue(
            any("technicals unavailable" in w for w in outcome.report.warnings)
        )

    def test_downtrend_plan_still_issues_and_warns_in_the_report(self):
        downtrend = DimensionResult(
            dimension="technicals", kind=SourceKind.NUMERIC,
            coverage=Coverage.FULL,
            payload={"close": 89.0, "sma_20": 96.0, "sma_60": 90.0,
                     "swing_low_20": 94.0, "atr_14": 3.0},
        )
        outcome = _run(providers=[_StubProvider(downtrend)])
        self.assertIsNotNone(outcome.report.levels.entry)
        self.assertTrue(
            any("trend warning" in w for w in outcome.report.warnings)
        )


class TestSwingLowPayload(unittest.TestCase):
    def _bars(self, count=70):
        bars = []
        for i in range(count):
            close = 100.0 + i * 0.1
            bars.append(Bar(high=close + 1, low=close - 1, close=close,
                            open=close, volume=1000, date=f"d{i}"))
        return bars

    def test_compute_swing_low_uses_lookback_window(self):
        bars = self._bars(70)
        # last 20 bars: closes 105.0..106.9, lows are close-1 -> min = 104.0
        self.assertAlmostEqual(compute_swing_low(bars), 104.0)
        self.assertIsNone(compute_swing_low([]))

    def test_provider_payload_includes_swing_low(self):
        provider = TechnicalsProvider(bars_loader=lambda symbol: self._bars(70))
        result = provider.collect("AAPL")
        self.assertAlmostEqual(result.payload["swing_low_20"], 104.0)


if __name__ == "__main__":
    unittest.main()
