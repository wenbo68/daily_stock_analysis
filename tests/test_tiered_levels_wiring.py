# -*- coding: utf-8 -*-
"""Offline tests: anchor-and-adjust levels wired into the tiered run (v2 slice 3).

run_tiered_analysis must replace the DSA sniper levels (LLM prose) with the
deterministic bases + validated AI adjustments, attach the levels_detail
audit trail, and surface level warnings on the report. Also covers the new
swing_low_20 technicals payload key the level formulas depend on.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.integration import run_tiered_analysis
from src.tiered_analysis.levels import AdjustmentProposal
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


class _FakeAdjuster:
    def __init__(self, proposals=(), warnings=()):
        self._proposals = list(proposals)
        self._warnings = list(warnings)
        self.calls = []

    def propose(self, symbol, bases, dimensions):
        self.calls.append((symbol, bases))
        return self._proposals, self._warnings


def _run(adjuster):
    return run_tiered_analysis(
        "AAPL",
        market=Market.US,
        providers=[_StubProvider(_technicals_dim())],
        analysis_runner=lambda symbol: _fake_analysis_result(),
        log_signal=False,
        level_adjuster=adjuster,
    )


class TestLevelsWiring(unittest.TestCase):
    def test_deterministic_bases_replace_dsa_sniper_levels(self):
        outcome = _run(_FakeAdjuster())
        levels = outcome.report.levels
        self.assertAlmostEqual(levels.entry, 96.0)  # not 210.0
        self.assertAlmostEqual(levels.secondary_entry, 94.0)
        self.assertAlmostEqual(levels.stop_loss, 90.0)
        self.assertAlmostEqual(levels.take_profit, 108.0)

    def test_accepted_adjustment_lands_in_levels_and_detail(self):
        adjuster = _FakeAdjuster(proposals=[
            AdjustmentProposal(level="entry", value=94.5, reason="support",
                               evidence=("technicals.sma_20",)),
        ])
        outcome = _run(adjuster)
        self.assertAlmostEqual(outcome.report.levels.entry, 94.5)
        detail = outcome.report.levels_detail["levels"]["entry"]
        self.assertAlmostEqual(detail["base"], 96.0)
        self.assertAlmostEqual(detail["adjusted"], 94.5)
        self.assertEqual(detail["reason"], "support")

    def test_rejected_adjustment_keeps_base_and_warns(self):
        adjuster = _FakeAdjuster(proposals=[
            AdjustmentProposal(level="entry", value=80.0, reason="x",
                               evidence=("technicals.sma_20",)),  # out of band
        ])
        outcome = _run(adjuster)
        self.assertAlmostEqual(outcome.report.levels.entry, 96.0)
        self.assertTrue(
            any("rejected" in w for w in outcome.report.warnings)
        )
        self.assertTrue(
            outcome.report.levels_detail["levels"]["entry"]["rejection"]
        )

    def test_adjuster_warnings_reach_the_report(self):
        outcome = _run(_FakeAdjuster(warnings=["level adjuster unavailable: down"]))
        self.assertTrue(
            any("adjuster unavailable" in w for w in outcome.report.warnings)
        )

    def test_missing_technicals_leaves_levels_empty_with_warning(self):
        other = DimensionResult(
            dimension="macro_econ", kind=SourceKind.NUMERIC,
            coverage=Coverage.FULL, payload={"x": 1},
        )
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider(other)],
            analysis_runner=lambda symbol: _fake_analysis_result(),
            log_signal=False,
            level_adjuster=_FakeAdjuster(),
        )
        self.assertIsNone(outcome.report.levels.entry)
        self.assertTrue(
            any("technicals unavailable" in w for w in outcome.report.warnings)
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
