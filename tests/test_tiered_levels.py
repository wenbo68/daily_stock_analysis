# -*- coding: utf-8 -*-
"""Offline tests for deterministic base levels + adjustment validation.

Formulas under test are documented in docs/tiered-analysis-formulas.md:
ideal entry = min(close, max(support candidates)); stop = ideal - 2*ATR;
target = min(ideal + R*(ideal - stop), nearest overhead resistance) with
R the user's chosen reward-to-risk ratio (default 2). The trend gate
(close must sit above sma_60) voids the plan; a resistance-capped ratio
below R only warns — the old 1.5 room gate no longer voids anything
(owner decision 2026-07-22: always give a plan). The backup entry is
retired. AI adjustments must stay within +/-1 ATR and keep ordering.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.levels import (
    ADJUSTMENT_BAND_ATR_MULTIPLE,
    MIN_REWARD_RISK,
    AdjustmentProposal,
    apply_adjustments,
    bases_from_dimensions,
    compute_base_levels,
    decisions_to_detail,
    decisions_to_sniper,
)
from src.tiered_analysis.providers.base import (
    Coverage,
    DimensionResult,
    SourceKind,
)


def _bases(**overrides):
    inputs = dict(close=100.0, sma_20=96.0, sma_60=90.0, swing_low=94.0, atr=3.0)
    inputs.update(overrides)
    return compute_base_levels(**inputs)


class TestComputeBaseLevels(unittest.TestCase):
    def test_happy_path_chain(self):
        bases = _bases()
        # ideal = min(100, max(96, 94)) = 96; stop = 96 - 6 = 90;
        # target = 96 + 2*(96-90) = 108. No backup entry (retired).
        self.assertAlmostEqual(bases.entry.value, 96.0)
        self.assertAlmostEqual(bases.stop_loss.value, 90.0)
        self.assertAlmostEqual(bases.take_profit.value, 108.0)
        self.assertEqual(bases.warnings, [])

    def test_entry_capped_at_close(self):
        bases = _bases(close=95.0)  # both supports above the market
        self.assertAlmostEqual(bases.entry.value, 95.0)

    def test_bases_record_formula_and_inputs(self):
        bases = _bases()
        self.assertIn("support candidates", bases.entry.formula)
        self.assertAlmostEqual(bases.entry.inputs["close"], 100.0)
        self.assertAlmostEqual(bases.entry.inputs["sma_20"], 96.0)
        self.assertAlmostEqual(bases.stop_loss.inputs["atr_14"], 3.0)

    def test_missing_sma20_uses_swing_low(self):
        bases = _bases(sma_20=None)
        self.assertAlmostEqual(bases.entry.value, 94.0)

    def test_no_structural_supports_means_no_levels_with_warning(self):
        bases = _bases(sma_20=None, sma_60=None, swing_low=None)
        self.assertIsNone(bases.entry)
        self.assertIsNone(bases.take_profit)
        self.assertTrue(any("support" in w.lower() for w in bases.warnings))

    def test_no_close_means_no_levels_with_warning(self):
        bases = _bases(close=None)
        self.assertIsNone(bases.entry)
        self.assertTrue(bases.warnings)

    def test_chosen_reward_ratio_scales_the_target(self):
        bases = _bases(reward_risk=3.0)
        # target = 96 + 3*(96-90) = 114, and the formula names the ratio.
        self.assertAlmostEqual(bases.take_profit.value, 114.0)
        self.assertIn("3 ×", bases.take_profit.formula)

    def test_capped_target_below_the_chosen_goal_warns(self):
        # Resistance at 106 (> close 100) caps the 108 geometric target:
        # ratio (106-96)/6 = 1.67 clears the 1.5 floor but misses the 2x
        # goal -> plan stands with a "reward below goal" warning.
        bases = _bases(swing_high_20=106.0)
        self.assertAlmostEqual(bases.take_profit.value, 106.0)
        self.assertTrue(any("below" in w and "goal" in w for w in bases.warnings))

    def test_missing_atr_means_no_stop_and_no_target(self):
        bases = _bases(atr=None)
        self.assertIsNotNone(bases.entry)
        self.assertIsNone(bases.stop_loss)
        self.assertIsNone(bases.take_profit)
        self.assertTrue(bases.warnings)


class TestTrendAndRoomGates(unittest.TestCase):
    def test_trend_gate_voids_plan_in_downtrend(self):
        bases = _bases(close=89.0)  # close <= sma_60 (90)
        self.assertIsNone(bases.entry)
        self.assertIsNone(bases.take_profit)
        self.assertTrue(any("trend gate" in w for w in bases.warnings))

    def test_trend_gate_boundary_close_equal_sma60_is_downtrend(self):
        bases = _bases(close=90.0, sma_20=89.0, swing_low=88.0)
        self.assertIsNone(bases.entry)
        self.assertTrue(any("trend gate" in w for w in bases.warnings))

    def test_missing_sma60_skips_gate_with_warning(self):
        bases = _bases(sma_60=None)
        self.assertIsNotNone(bases.entry)
        self.assertTrue(any("trend gate skipped" in w for w in bases.warnings))

    def test_overhead_resistance_caps_target(self):
        # entry 96, stop 90, geometric target 108; nearest resistance 106
        # (above close 100) caps it: R:R = 10/6 = 1.67 >= 1.5 -> plan stands.
        bases = _bases(swing_high_20=106.0)
        self.assertAlmostEqual(bases.take_profit.value, 106.0)
        self.assertIn("resistance", bases.take_profit.formula)
        self.assertAlmostEqual(bases.take_profit.inputs["geometric_target"], 108.0)

    def test_thin_reward_still_gets_a_plan_with_warning(self):
        # Resistance at 104: capped R:R = (104-96)/6 = 1.33, below the
        # user's 2x goal — the plan stands and a warning says so (the old
        # 1.5 room gate no longer voids the plan).
        bases = _bases(swing_high_20=104.0)
        self.assertIsNotNone(bases.entry)
        self.assertAlmostEqual(bases.take_profit.value, 104.0)
        self.assertTrue(any("reward below goal" in w for w in bases.warnings))

    def test_resistance_below_close_is_ignored(self):
        # A "resistance" the price already broke through is not overhead.
        bases = _bases(swing_high_20=99.0)
        self.assertAlmostEqual(bases.take_profit.value, 108.0)

    def test_nearest_of_several_resistances_wins(self):
        bases = _bases(swing_high_20=107.0, swing_high_60=112.0, high_52w=120.0)
        self.assertAlmostEqual(bases.take_profit.value, 107.0)

    def test_no_overhead_resistance_keeps_geometric_target(self):
        bases = _bases(high_52w=100.0)  # at the 52w high: open air above
        self.assertAlmostEqual(bases.take_profit.value, 108.0)
        self.assertNotIn("resistance", bases.take_profit.formula)


def _reason(text: str) -> dict:
    """A minimal reasons entry: the flagged-check keyword + one sentence."""
    return {"check": "volatility", "text": text, "links": []}


class TestApplyAdjustments(unittest.TestCase):
    def test_in_band_adjustment_accepted(self):
        bases = _bases()
        # 96 -> 94.5: in band (1.5 < 3), ordering holds,
        # and R:R improves to (108-94.5)/(94.5-90) = 3.0.
        proposals = [
            AdjustmentProposal(
                level="entry", value=94.5, reasons=(_reason("support cluster"),),
                evidence=("technicals.sma_20",),
            )
        ]
        decisions, warnings = apply_adjustments(bases, proposals, atr=3.0)
        self.assertAlmostEqual(decisions["entry"].adjusted, 94.5)
        self.assertAlmostEqual(decisions["entry"].final, 94.5)
        self.assertIsNone(decisions["entry"].rejection)
        self.assertEqual(warnings, [])

    def test_unadjusted_levels_keep_base_as_final(self):
        decisions, _ = apply_adjustments(_bases(), [], atr=3.0)
        self.assertAlmostEqual(decisions["stop_loss"].final, 90.0)
        self.assertIsNone(decisions["stop_loss"].adjusted)

    def test_out_of_band_adjustment_rejected(self):
        self.assertEqual(ADJUSTMENT_BAND_ATR_MULTIPLE, 1.0)
        proposals = [
            AdjustmentProposal(level="entry", value=92.0, reasons=(_reason("x"),), evidence=("e",))
        ]  # |92 - 96| = 4 > 1 * ATR(3)
        decisions, warnings = apply_adjustments(_bases(), proposals, atr=3.0)
        self.assertIsNone(decisions["entry"].adjusted)
        self.assertAlmostEqual(decisions["entry"].final, 96.0)
        self.assertTrue(decisions["entry"].rejection)
        self.assertTrue(warnings)

    def test_no_atr_rejects_all_adjustments(self):
        bases = _bases(atr=None)
        proposals = [
            AdjustmentProposal(level="entry", value=95.0, reasons=(_reason("x"),), evidence=("e",))
        ]
        decisions, warnings = apply_adjustments(bases, proposals, atr=None)
        self.assertIsNone(decisions["entry"].adjusted)
        self.assertTrue(warnings)

    def test_ordering_violation_rejected(self):
        # Entry adjusted down to 93 (in band: |93-96| = 3), then the stop
        # adjusted up to 93 (in band: |93-90| = 3): the stop would sit ON
        # the entry, so the stop proposal is rejected for ordering.
        proposals = [
            AdjustmentProposal(level="entry", value=93.0, reasons=(_reason("x"),), evidence=("e",)),
            AdjustmentProposal(level="stop_loss", value=93.0, reasons=(_reason("x"),), evidence=("e",)),
        ]
        decisions, warnings = apply_adjustments(_bases(), proposals, atr=3.0)
        self.assertAlmostEqual(decisions["entry"].adjusted, 93.0)
        self.assertIsNone(decisions["stop_loss"].adjusted)
        self.assertTrue(any("order" in w.lower() for w in warnings))

    def test_reward_risk_degradation_no_longer_rejected(self):
        self.assertEqual(MIN_REWARD_RISK, 1.5)
        # Raise the entry to 97.5 (in band, ordering fine): with stop 90
        # and target 108 fixed, R:R becomes 10.5/7.5 = 1.4 — below the
        # old floor, but a thin ratio is a plan warning now, never a
        # reason to revert a level.
        proposals = [
            AdjustmentProposal(level="entry", value=97.5, reasons=(_reason("x"),), evidence=("e",))
        ]
        decisions, warnings = apply_adjustments(_bases(), proposals, atr=3.0)
        self.assertAlmostEqual(decisions["entry"].adjusted, 97.5)
        self.assertEqual(warnings, [])

    def test_adjustment_without_base_rejected(self):
        # No close -> no bases at all; a proposal for the entry has no
        # deterministic base to adjust and is rejected.
        bases = _bases(close=None)
        proposals = [
            AdjustmentProposal(level="entry", value=95.0, reasons=(_reason("x"),), evidence=("e",))
        ]
        decisions, warnings = apply_adjustments(bases, proposals, atr=3.0)
        self.assertIsNone(decisions["entry"].adjusted)
        self.assertTrue(decisions["entry"].rejection)

    def test_duplicate_proposal_rejected(self):
        proposals = [
            AdjustmentProposal(level="entry", value=97.0, reasons=(_reason("a"),), evidence=("e",)),
            AdjustmentProposal(level="entry", value=95.5, reasons=(_reason("b"),), evidence=("e",)),
        ]
        decisions, warnings = apply_adjustments(_bases(), proposals, atr=3.0)
        self.assertAlmostEqual(decisions["entry"].adjusted, 97.0)
        self.assertTrue(any("duplicate" in w.lower() for w in warnings))


class TestConverters(unittest.TestCase):
    def test_decisions_to_sniper_uses_final_values(self):
        proposals = [
            AdjustmentProposal(level="entry", value=94.5, reasons=(_reason("x"),), evidence=("e",))
        ]
        decisions, _ = apply_adjustments(_bases(), proposals, atr=3.0)
        sniper = decisions_to_sniper(decisions)
        self.assertAlmostEqual(sniper.entry, 94.5)
        self.assertAlmostEqual(sniper.stop_loss, 90.0)

    def test_detail_is_json_ready_and_complete(self):
        import json

        proposals = [
            AdjustmentProposal(
                level="entry", value=94.5, reasons=(_reason("why"),), evidence=("citation:1",)
            )
        ]
        decisions, warnings = apply_adjustments(_bases(), proposals, atr=3.0)
        detail = decisions_to_detail(decisions, warnings)
        json.dumps(detail)  # must not raise
        entry = detail["levels"]["entry"]
        self.assertAlmostEqual(entry["base"], 96.0)
        self.assertAlmostEqual(entry["adjusted"], 94.5)
        self.assertEqual(entry["reasons"], [_reason("why")])
        self.assertEqual(entry["evidence"], ["citation:1"])
        self.assertIn("formula", entry)
        self.assertIn("inputs", entry)


class TestBasesFromDimensions(unittest.TestCase):
    def _technicals(self, payload):
        return DimensionResult(
            dimension="technicals",
            kind=SourceKind.NUMERIC,
            coverage=Coverage.FULL,
            payload=payload,
        )

    def test_extracts_inputs_from_technicals_payload(self):
        dim = self._technicals(
            {"close": 100.0, "sma_20": 96.0, "sma_60": 90.0,
             "swing_low_20": 94.0, "atr_14": 3.0}
        )
        bases = bases_from_dimensions([dim])
        self.assertAlmostEqual(bases.entry.value, 96.0)

    def test_extracts_resistance_inputs_from_payload(self):
        dim = self._technicals(
            {"close": 100.0, "sma_20": 96.0, "sma_60": 90.0,
             "swing_low_20": 94.0, "atr_14": 3.0, "swing_high_20": 106.0}
        )
        bases = bases_from_dimensions([dim])
        self.assertAlmostEqual(bases.take_profit.value, 106.0)

    def test_missing_technicals_dimension_yields_warning_only(self):
        bases = bases_from_dimensions([])
        self.assertIsNone(bases.entry)
        self.assertTrue(bases.warnings)


if __name__ == "__main__":
    unittest.main()
