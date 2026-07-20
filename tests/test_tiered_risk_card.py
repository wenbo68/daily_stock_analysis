# -*- coding: utf-8 -*-
"""Offline tests for the display-only 6-entry risk card.

Pure function, zero LLM. The card must always ship all 6 entries in
RISK_CARD_IDS order, with honest "na" statuses when inputs are missing,
and — by explicit owner decision — it affects nothing else in the run.
"""
from __future__ import annotations

import json
import unittest

from src.tiered_analysis.providers.base import (
    Coverage,
    DimensionResult,
    SourceKind,
)
from src.tiered_analysis.risk_card import (
    ADV_FLAG_FRACTION,
    RISK_CARD_IDS,
    VOLATILITY_FLAG_FRACTION,
    build_risk_card,
)
from src.tiered_analysis.schema import SniperLevels
from src.tiered_analysis.settings import SizingSettings


def _tech(payload=None):
    base = {
        "close": 100.0, "sma_20": 96.0, "sma_60": 90.0,
        "swing_low_20": 94.0, "atr_14": 3.0,
        "avg_volume_20": 1_000_000.0, "worst_day_1y": -0.03,
    }
    if payload:
        base.update(payload)
    return DimensionResult(
        dimension="technicals", kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL, payload=base,
    )


LEVELS = SniperLevels(entry=96.0, stop_loss=90.0, take_profit=108.0)

SIZING = {
    "shares": 166, "position_value": 15936.0, "risk_amount": 996.0,
    "loss_per_share": 6.0, "lot_size": 1, "cap_applied": False,
}

SETTINGS = SizingSettings(capital=100000.0, risk_fraction=0.01)


def _card(dimensions=None, levels=LEVELS, sizing=SIZING, settings=SETTINGS):
    return build_risk_card(
        dimensions=dimensions or [_tech()],
        levels=levels, sizing=sizing, settings=settings,
    )


def _by_id(card):
    return {entry["id"]: entry for entry in card}


class TestRiskCardShape(unittest.TestCase):
    def test_all_6_entries_in_frozen_order_and_json_ready(self):
        card = _card()
        self.assertEqual([e["id"] for e in card], list(RISK_CARD_IDS))
        json.dumps(card)  # must not raise

    def test_empty_run_degrades_to_na_never_crashes(self):
        card = build_risk_card(
            dimensions=[], levels=SniperLevels(), sizing=None,
            settings=SizingSettings(),
        )
        self.assertEqual(len(card), 6)
        self.assertTrue(all(e["status"] == "na" for e in card))


class TestRiskEntries(unittest.TestCase):
    def test_liquidity_flags_large_fraction_of_adv(self):
        entry = _by_id(_card())["liquidity"]
        self.assertEqual(entry["status"], "ok")
        thin = _by_id(_card(dimensions=[_tech({"avg_volume_20": 2000.0})]))
        self.assertEqual(thin["liquidity"]["status"], "flag")
        self.assertGreater(
            thin["liquidity"]["values"]["fraction_of_adv"], ADV_FLAG_FRACTION
        )

    def test_gap_stress_atr_scenario_numbers(self):
        entry = _by_id(_card())["gap_stress"]
        values = entry["values"]
        # ATR scenario: open = 90 - 3 = 87; loss = 166 * (96 - 87) = 1494;
        # 498 more than the planned 996.
        self.assertAlmostEqual(values["atr_open"], 87.0)
        self.assertAlmostEqual(values["atr_loss"], 166 * 9.0)
        self.assertAlmostEqual(values["atr_extra"], 1494.0 - 996.0)

    def test_gap_stress_mild_worst_day_does_not_gap_the_stop(self):
        entry = _by_id(_card())["gap_stress"]
        # Worst day -3% from entry 96 -> open 93.12, above the stop 90:
        # the stop is not gapped, the planned loss holds, no flag.
        self.assertEqual(entry["status"], "ok")
        values = entry["values"]
        self.assertAlmostEqual(values["worst_open"], 96.0 * 0.97)
        self.assertFalse(values["worst_gaps_stop"])
        self.assertNotIn("worst_loss", values)

    def test_gap_stress_big_worst_day_gaps_the_stop_and_flags(self):
        card = _by_id(_card(dimensions=[_tech({"worst_day_1y": -0.10})]))
        gap = card["gap_stress"]
        # Worst day -10% from entry 96 -> open 86.4 < stop 90: gapped.
        self.assertEqual(gap["status"], "flag")
        self.assertAlmostEqual(gap["values"]["worst_open"], 86.4)
        self.assertAlmostEqual(gap["values"]["worst_loss"], 166 * (96.0 - 86.4))
        self.assertAlmostEqual(
            gap["values"]["worst_extra"], 166 * (96.0 - 86.4) - 996.0
        )

    def test_gap_stress_survives_missing_worst_day(self):
        card = _by_id(_card(dimensions=[_tech({"worst_day_1y": None})]))
        gap = card["gap_stress"]
        self.assertEqual(gap["status"], "ok")  # ATR scenario still shown
        self.assertIn("atr_open", gap["values"])
        self.assertNotIn("worst_open", gap["values"])

    def test_volatility_flag_threshold(self):
        entry = _by_id(_card())["volatility"]
        self.assertEqual(entry["status"], "ok")  # 3% < 4%
        hot = _by_id(_card(dimensions=[_tech({"atr_14": 5.0})]))
        self.assertEqual(hot["volatility"]["status"], "flag")
        self.assertGreater(
            hot["volatility"]["values"]["atr_fraction"],
            VOLATILITY_FLAG_FRACTION,
        )

    def test_reward_risk_meets_the_default_goal(self):
        entry = _by_id(_card())["reward_risk"]
        self.assertEqual(entry["status"], "ok")
        self.assertAlmostEqual(entry["values"]["ratio"], 2.0)
        self.assertAlmostEqual(entry["values"]["goal"], 2.0)

    def test_reward_risk_flags_a_ratio_below_the_chosen_goal(self):
        picky = SizingSettings(capital=100000.0, risk_fraction=0.01,
                               reward_risk=3.0)
        entry = _by_id(_card(settings=picky))["reward_risk"]
        self.assertEqual(entry["status"], "flag")  # 2.0 < the 3x goal
        self.assertAlmostEqual(entry["values"]["goal"], 3.0)

    def test_stop_atr_multiple(self):
        entry = _by_id(_card())["stop_atr"]
        self.assertAlmostEqual(entry["values"]["atr_multiple"], 2.0)

    def test_stop_vs_swing_low_flags_stop_above_the_low(self):
        entry = _by_id(_card())["stop_vs_swing_low"]
        self.assertEqual(entry["status"], "ok")  # stop 90 < swing low 94
        shallow = _by_id(_card(levels=SniperLevels(
            entry=96.0, stop_loss=95.0, take_profit=108.0)))
        self.assertEqual(shallow["stop_vs_swing_low"]["status"], "flag")


if __name__ == "__main__":
    unittest.main()
