# -*- coding: utf-8 -*-
"""Offline tests for the tier pipeline skeleton (slice 2).

Tier 1 delegates to the existing DSA analysis via an injected runner; these
tests fake that runner — no LLM, no network, no imports of the DSA decision
path.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.tiered_analysis.providers.base import Coverage, Market
from src.tiered_analysis.schema import (
    Direction,
    SizingSlots,
    SniperLevels,
    TierReport,
    coerce_price,
    extract_price,
)
from src.tiered_analysis.tiers import (
    Tier1Stage,
    Tier2Stage,
    TieredPipeline,
    TierState,
)


def _fake_dsa_result(**overrides):
    """Object shaped like src/analyzer.py AnalysisResult, minus the LLM."""
    base = dict(
        code="AAPL",
        name="Apple",
        sentiment_score=72,
        trend_prediction="看多",
        operation_advice="买入",
        decision_type="buy",
        confidence_level="高",
        dashboard={
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "180.5",
                    "secondary_buy": 178,
                    "stop_loss": 172.0,
                    "take_profit": "195",
                }
            }
        },
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestCoercePrice(unittest.TestCase):
    def test_numeric_passthrough(self):
        self.assertEqual(coerce_price(180.5), 180.5)
        self.assertEqual(coerce_price(178), 178.0)

    def test_numeric_string(self):
        self.assertEqual(coerce_price("195"), 195.0)

    def test_na_and_garbage_return_none(self):
        self.assertIsNone(coerce_price("N/A"))
        self.assertIsNone(coerce_price(""))
        self.assertIsNone(coerce_price(None))
        self.assertIsNone(coerce_price("about 180"))


class TestExtractPrice(unittest.TestCase):
    """Prose fallback — the live AAPL run returned sniper levels as full
    Chinese sentences; the price must be extracted deterministically."""

    def test_strict_values_still_work(self):
        self.assertEqual(extract_price("195"), 195.0)
        self.assertEqual(extract_price(178), 178.0)
        self.assertIsNone(extract_price("N/A"))
        self.assertIsNone(extract_price(None))

    def test_real_live_run_sentences(self):
        cases = [
            ("理想买入点：303.80元（缩量回踩MA5获得支撑，且MA10上穿MA20）", 303.80),
            ("次优买入点：294.70元（回踩MA10获得支撑，且MA10上穿MA20）", 294.70),
            ("止损位：290.00元（跌破MA20或当前价位下方约7%）", 290.00),
            ("目标位：325.00元（心理关口，需配合放量突破）", 325.00),
        ]
        for text, expected in cases:
            self.assertEqual(extract_price(text), expected, text)

    def test_indicator_names_are_not_prices(self):
        # digits glued to letters (MA20, RSI14) must never parse as prices
        self.assertIsNone(extract_price("跌破MA20后止损"))
        self.assertIsNone(extract_price("RSI14 oversold"))

    def test_percentages_are_not_prices(self):
        self.assertIsNone(extract_price("当前价位下方约7%"))

    def test_english_prose(self):
        self.assertEqual(extract_price("$210.50 support zone"), 210.50)


class TestSchema(unittest.TestCase):
    def test_sizing_slots_default_empty(self):
        slots = SizingSlots()
        self.assertIsNone(slots.capital)
        self.assertIsNone(slots.risk_fraction)
        self.assertIsNone(slots.shares)
        self.assertTrue(slots.is_empty)

    def test_direction_from_decision_type(self):
        self.assertEqual(Direction.from_decision_type("buy"), Direction.BUY)
        self.assertEqual(Direction.from_decision_type("hold"), Direction.HOLD)
        self.assertEqual(Direction.from_decision_type("sell"), Direction.SELL)
        self.assertEqual(Direction.from_decision_type("nonsense"), Direction.UNKNOWN)
        self.assertEqual(Direction.from_decision_type(None), Direction.UNKNOWN)

    def test_tier_report_sizing_always_present_and_empty_in_v1(self):
        report = TierReport(
            tier=1,
            symbol="AAPL",
            market=Market.US,
            coverage=Coverage.FULL,
            direction=Direction.BUY,
        )
        self.assertTrue(report.sizing.is_empty)


class TestTier1Stage(unittest.TestCase):
    def test_delegates_to_runner_and_adapts_result(self):
        stage = Tier1Stage(analysis_runner=lambda symbol: _fake_dsa_result())
        state = TierState(symbol="AAPL", market=Market.US)
        report = stage.run(state)

        self.assertEqual(report.tier, 1)
        self.assertEqual(report.direction, Direction.BUY)
        self.assertEqual(report.coverage, Coverage.FULL)
        self.assertEqual(report.score, 72)
        self.assertEqual(report.confidence, "高")
        self.assertEqual(
            report.levels,
            SniperLevels(entry=180.5, secondary_entry=178.0,
                         stop_loss=172.0, take_profit=195.0),
        )
        self.assertTrue(report.sizing.is_empty)

    def test_accepts_dict_results_too(self):
        payload = _fake_dsa_result().__dict__
        stage = Tier1Stage(analysis_runner=lambda symbol: payload)
        report = stage.run(TierState(symbol="AAPL", market=Market.US))
        self.assertEqual(report.direction, Direction.BUY)
        self.assertEqual(report.levels.stop_loss, 172.0)

    def test_missing_sniper_points_degrades_to_partial(self):
        stage = Tier1Stage(
            analysis_runner=lambda symbol: _fake_dsa_result(dashboard=None),
        )
        report = stage.run(TierState(symbol="AAPL", market=Market.US))
        self.assertEqual(report.coverage, Coverage.PARTIAL)
        self.assertEqual(report.direction, Direction.BUY)
        self.assertEqual(report.levels, SniperLevels())
        self.assertTrue(report.warnings)

    def test_unparseable_level_degrades_to_partial_with_warning(self):
        result = _fake_dsa_result()
        result.dashboard["battle_plan"]["sniper_points"]["stop_loss"] = "N/A"
        stage = Tier1Stage(analysis_runner=lambda symbol: result)
        report = stage.run(TierState(symbol="AAPL", market=Market.US))
        self.assertEqual(report.coverage, Coverage.PARTIAL)
        self.assertIsNone(report.levels.stop_loss)
        self.assertTrue(any("stop_loss" in w for w in report.warnings))

    def test_prose_sniper_levels_parse_without_warnings(self):
        # Live-run regression: DSA sometimes returns levels as sentences.
        result = _fake_dsa_result()
        result.dashboard["battle_plan"]["sniper_points"] = {
            "ideal_buy": "理想买入点：303.80元（缩量回踩MA5获得支撑）",
            "secondary_buy": "次优买入点：294.70元（回踩MA10获得支撑）",
            "stop_loss": "止损位：290.00元（跌破MA20或当前价位下方约7%）",
            "take_profit": "目标位：325.00元（心理关口，需配合放量突破）",
        }
        stage = Tier1Stage(analysis_runner=lambda symbol: result)
        report = stage.run(TierState(symbol="AAPL", market=Market.US))
        self.assertEqual(report.coverage, Coverage.FULL)
        self.assertEqual(report.levels.entry, 303.80)
        self.assertEqual(report.levels.secondary_entry, 294.70)
        self.assertEqual(report.levels.stop_loss, 290.00)
        self.assertEqual(report.levels.take_profit, 325.00)
        self.assertEqual(report.warnings, [])

    def test_runner_failure_is_unavailable_result_not_exception(self):
        def _boom(symbol):
            raise RuntimeError("LLM quota exhausted")

        stage = Tier1Stage(analysis_runner=_boom)
        report = stage.run(TierState(symbol="AAPL", market=Market.US))
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("LLM quota exhausted" in w for w in report.warnings))


class TestTier2Failures(unittest.TestCase):
    def test_tier2_without_foundation_report_is_unavailable(self):
        report = Tier2Stage().run(TierState(symbol="AAPL", market=Market.US))
        self.assertEqual(report.tier, 2)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("foundation" in w for w in report.warnings))

    def test_tier2_failure_never_falls_back_to_tier1_direction(self):
        # Outlook redesign: a failed vote is UNKNOWN, never the blob's call.
        state = TierState(symbol="AAPL", market=Market.US)
        state.reports[1] = TierReport(
            tier=1, symbol="AAPL", market=Market.US,
            coverage=Coverage.FULL, direction=Direction.BUY,
        )
        report = Tier2Stage().run(state)  # no dimensions -> failure
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("re-run" in w for w in report.warnings))


class TestTieredPipeline(unittest.TestCase):
    def _pipeline(self):
        return TieredPipeline(
            tier1=Tier1Stage(analysis_runner=lambda symbol: _fake_dsa_result()),
        )

    def test_runs_stages_up_to_requested_tier(self):
        state = self._pipeline().run("AAPL", market=Market.US, up_to_tier=2)
        self.assertEqual(sorted(state.reports), [1, 2])
        self.assertEqual(state.reports[1].coverage, Coverage.FULL)
        self.assertEqual(state.reports[2].coverage, Coverage.UNAVAILABLE)

    def test_default_runs_tier1_only(self):
        state = self._pipeline().run("AAPL", market=Market.US)
        self.assertEqual(sorted(state.reports), [1])

    def test_rejects_unsupported_tier(self):
        with self.assertRaises(ValueError):
            self._pipeline().run("AAPL", market=Market.US, up_to_tier=3)
        with self.assertRaises(ValueError):
            self._pipeline().run("AAPL", market=Market.US, up_to_tier=0)


if __name__ == "__main__":
    unittest.main()
