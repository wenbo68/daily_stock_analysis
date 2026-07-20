# -*- coding: utf-8 -*-
"""Offline tests for the display-only 13-entry risk card.

Pure function, zero LLM. The card must always ship all 13 entries in
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
        "avg_volume_20": 1_000_000.0, "worst_day_5pct": -0.03,
    }
    if payload:
        base.update(payload)
    return DimensionResult(
        dimension="technicals", kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL, payload=base,
    )


LEVELS = SniperLevels(entry=96.0, secondary_entry=94.0,
                      stop_loss=90.0, take_profit=108.0)

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
    def test_all_13_entries_in_frozen_order_and_json_ready(self):
        card = _card()
        self.assertEqual([e["id"] for e in card], list(RISK_CARD_IDS))
        json.dumps(card)  # must not raise

    def test_empty_run_degrades_to_na_never_crashes(self):
        card = build_risk_card(
            dimensions=[], levels=SniperLevels(), sizing=None,
            settings=SizingSettings(),
        )
        self.assertEqual(len(card), 13)
        self.assertTrue(all(e["status"] == "na" for e in card))


class TestRiskSideEntries(unittest.TestCase):
    def test_concentration_ok_and_flag(self):
        entry = _by_id(_card())["concentration"]
        self.assertEqual(entry["status"], "ok")
        self.assertAlmostEqual(entry["values"]["fraction"], 0.15936)
        capped = _by_id(_card(sizing={**SIZING, "cap_applied": True}))
        self.assertEqual(capped["concentration"]["status"], "flag")

    def test_cash_left(self):
        entry = _by_id(_card())["cash"]
        self.assertAlmostEqual(entry["values"]["cash_left"], 84064.0)

    def test_max_loss_flags_lot_rounding_drift(self):
        entry = _by_id(_card())["max_loss"]
        self.assertEqual(entry["status"], "ok")
        drifted = _by_id(_card(sizing={**SIZING, "risk_amount": 1200.0}))
        self.assertEqual(drifted["max_loss"]["status"], "flag")

    def test_liquidity_flags_large_fraction_of_adv(self):
        entry = _by_id(_card())["liquidity"]
        self.assertEqual(entry["status"], "ok")
        thin = _by_id(_card(dimensions=[_tech({"avg_volume_20": 2000.0})]))
        self.assertEqual(thin["liquidity"]["status"], "flag")
        self.assertGreater(
            thin["liquidity"]["values"]["fraction_of_adv"], ADV_FLAG_FRACTION
        )

    def test_var_flags_when_bad_day_exceeds_planned_risk(self):
        entry = _by_id(_card())["var"]
        # 3% of 15936 = 478 < planned 996 -> ok
        self.assertEqual(entry["status"], "ok")
        wild = _by_id(_card(dimensions=[_tech({"worst_day_5pct": -0.10})]))
        self.assertEqual(wild["var"]["status"], "flag")

    def test_gap_stress_scenario_numbers(self):
        entry = _by_id(_card())["gap_stress"]
        self.assertAlmostEqual(entry["values"]["gap_price"], 87.0)  # 90 - 3
        self.assertAlmostEqual(entry["values"]["loss_if_gap"], 166 * 9.0)

    def test_volatility_flag_threshold(self):
        entry = _by_id(_card())["volatility"]
        self.assertEqual(entry["status"], "ok")  # 3% < 4%
        hot = _by_id(_card(dimensions=[_tech({"atr_14": 5.0})]))
        self.assertEqual(hot["volatility"]["status"], "flag")
        self.assertGreater(
            hot["volatility"]["values"]["atr_fraction"],
            VOLATILITY_FLAG_FRACTION,
        )


class TestTraderSideEntries(unittest.TestCase):
    def test_reward_risk_ratio(self):
        entry = _by_id(_card())["reward_risk"]
        self.assertAlmostEqual(entry["values"]["ratio"], 2.0)

    def test_stop_atr_multiple(self):
        entry = _by_id(_card())["stop_atr"]
        self.assertAlmostEqual(entry["values"]["atr_multiple"], 2.0)

    def test_stop_vs_swing_low_flags_stop_above_the_low(self):
        entry = _by_id(_card())["stop_vs_swing_low"]
        self.assertEqual(entry["status"], "ok")  # stop 90 < swing low 94
        shallow = _by_id(_card(levels=SniperLevels(
            entry=96.0, secondary_entry=94.0, stop_loss=95.0,
            take_profit=108.0)))
        self.assertEqual(shallow["stop_vs_swing_low"]["status"], "flag")

    def test_staleness_snapshot_is_fresh_by_construction(self):
        entry = _by_id(_card())["staleness"]
        self.assertFalse(entry["values"]["close_below_stop"])

    def test_both_entries_flags_busted_risk_budget(self):
        entry = _by_id(_card())["both_entries"]
        # 166 * (6 + 4) = 1660 > 1000 budget -> the double fill busts it.
        self.assertEqual(entry["status"], "flag")
        self.assertAlmostEqual(entry["values"]["combined_risk"], 1660.0)
        self.assertAlmostEqual(entry["values"]["risk_budget"], 1000.0)

    def test_ownership_context_na_when_nothing_held(self):
        entry = _by_id(_card())["ownership_context"]
        self.assertEqual(entry["status"], "na")

    def test_ownership_context_combines_held_and_new(self):
        settings = SizingSettings(capital=100000.0, risk_fraction=0.01,
                                  ownership=300)
        entry = _by_id(_card(settings=settings))["ownership_context"]
        self.assertEqual(entry["status"], "flag")  # 30000+15936 > 25% cap
        self.assertAlmostEqual(entry["values"]["combined_value"], 45936.0)
        self.assertAlmostEqual(entry["values"]["combined_shares"], 466.0)


if __name__ == "__main__":
    unittest.main()
