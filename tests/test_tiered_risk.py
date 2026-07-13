# -*- coding: utf-8 -*-
"""Offline tests for the tier-3 risk stress test (v2 slice 5).

Three risk personas (conservative/aggressive/neutral) critique the tier-2
verdict; a risk judge merges them into a stance + a size multiplier from
{0, 0.5, 1.0} + stop advice. The multiplier is applied by code (never the
LLM), invalid multipliers void the verdict, and every failure path falls
back to the tier-2 output.
"""
from __future__ import annotations

import json
import unittest

from src.tiered_analysis.risk import (
    PERSONAS,
    SIZE_MULTIPLIERS,
    RiskEngine,
    RiskResult,
    RiskVerdict,
    apply_size_multiplier,
)
from src.tiered_analysis.providers.base import (
    Coverage,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.tiers import Tier3Stage, TierState


def _technicals():
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
        payload={"close": 100.0, "rsi_14": 71.2, "atr_14": 3.0},
    )


def _tier2(direction=Direction.BUY):
    return TierReport(
        tier=2,
        symbol="AAPL",
        market=Market.US,
        coverage=Coverage.FULL,
        direction=direction,
        confidence="0.65",
        score=68,
        levels=SniperLevels(entry=96.0, secondary_entry=94.0,
                            stop_loss=90.0, take_profit=108.0),
        narrative="debate ruling: cautious buy",
    )


def _judge_json(**overrides):
    body = {
        "stance": "buy",
        "size_multiplier": 0.5,
        "confidence": 0.8,
        "stop_advice": "tighten",
        "tightened_stop": 92.0,
        "summary": "Take half the position; valuation risk argues for caution.",
        "key_risks": [
            {"claim": "RSI shows overheating", "evidence": ["technicals.rsi_14"]},
        ],
    }
    body.update(overrides)
    return json.dumps(body)


class ScriptedSummarizer:
    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self._replies:
            raise AssertionError("summarizer called more times than scripted")
        return self._replies.pop(0)


def _engine_run(judge_reply=None, replies=None):
    scripted = replies or ["take-c", "take-a", "take-n",
                           judge_reply or _judge_json()]
    llm = ScriptedSummarizer(scripted)
    result = RiskEngine(summarizer=llm).run("AAPL", _tier2(), [_technicals()])
    return result, llm


class TestRiskEngine(unittest.TestCase):
    def test_persona_fanout_then_judge(self):
        result, llm = _engine_run()
        self.assertEqual(len(llm.prompts), 4)
        self.assertEqual([t.persona for t in result.takes], list(PERSONAS))
        for prompt, persona in zip(llm.prompts[:3], PERSONAS):
            self.assertIn(persona.upper(), prompt)
            self.assertIn("rsi_14", prompt)  # evidence
            self.assertIn("debate ruling", prompt)  # tier-2 context
        # the judge sees all three takes
        self.assertIn("take-c", llm.prompts[3])
        self.assertIn("take-n", llm.prompts[3])

    def test_verdict_parsed(self):
        result, _ = _engine_run()
        verdict = result.verdict
        self.assertEqual(verdict.stance, Direction.BUY)
        self.assertEqual(verdict.size_multiplier, 0.5)
        self.assertAlmostEqual(verdict.confidence, 0.8)
        self.assertEqual(verdict.stop_advice, "tighten")
        self.assertAlmostEqual(verdict.tightened_stop, 92.0)
        self.assertIn("half the position", verdict.summary)
        self.assertEqual(result.warnings, [])

    def test_unusable_confidence_dropped_with_warning(self):
        # Mirrors the debate judge: a bad confidence never voids the verdict,
        # it just disappears with a note.
        for bad in (None, 1.4, "high"):
            result, _ = _engine_run(judge_reply=_judge_json(confidence=bad))
            self.assertIsNotNone(result.verdict)
            self.assertIsNone(result.verdict.confidence)
            self.assertTrue(any("confidence" in w for w in result.warnings))

    def test_multiplier_must_be_from_the_enum(self):
        self.assertEqual(SIZE_MULTIPLIERS, (0.0, 0.5, 1.0))
        result, _ = _engine_run(judge_reply=_judge_json(size_multiplier=0.7))
        self.assertIsNone(result.verdict)
        self.assertTrue(any("multiplier" in w for w in result.warnings))

    def test_multiplier_zero_is_valid(self):
        result, _ = _engine_run(
            judge_reply=_judge_json(size_multiplier=0, stance="buy")
        )
        self.assertEqual(result.verdict.size_multiplier, 0.0)

    def test_invalid_tightened_stop_dropped_with_warning(self):
        # tighten must land strictly between the current stop and the entry
        for bad in (97.0, 89.0, 90.0):  # above entry-ish / below / equal stop
            result, _ = _engine_run(
                judge_reply=_judge_json(tightened_stop=bad)
            )
            self.assertIsNone(result.verdict.tightened_stop)
            self.assertTrue(any("tightened stop" in w for w in result.warnings))

    def test_bad_stop_advice_downgrades_to_keep(self):
        result, _ = _engine_run(judge_reply=_judge_json(stop_advice="yolo"))
        self.assertEqual(result.verdict.stop_advice, "keep")
        self.assertTrue(result.warnings)

    def test_unanchored_risk_kept_but_flagged(self):
        result, _ = _engine_run(judge_reply=_judge_json(
            key_risks=[{"claim": "Trust me", "evidence": ["technicals.nope"]}]
        ))
        self.assertEqual(result.verdict.key_risks[0].evidence, ())
        self.assertTrue(any("not anchored" in w for w in result.warnings))

    def test_unusable_stance_means_no_verdict(self):
        result, _ = _engine_run(judge_reply=_judge_json(stance="maybe"))
        self.assertIsNone(result.verdict)

    def test_unparseable_judge_means_no_verdict(self):
        result, _ = _engine_run(judge_reply="it depends")
        self.assertIsNone(result.verdict)

    def test_llm_failure_keeps_partial_takes(self):
        def boom_on_third(prompt, calls=[]):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("model down")
            return "take"

        result = RiskEngine(summarizer=boom_on_third).run(
            "AAPL", _tier2(), [_technicals()]
        )
        self.assertIsNone(result.verdict)
        self.assertEqual(len(result.takes), 2)
        self.assertTrue(any("model down" in w for w in result.warnings))

    def test_to_detail_is_json_ready(self):
        result, _ = _engine_run()
        detail = result.to_detail()
        json.dumps(detail)
        self.assertEqual(detail["verdict"]["size_multiplier"], 0.5)
        self.assertEqual(len(detail["takes"]), 3)


class TestApplySizeMultiplier(unittest.TestCase):
    def test_code_applies_the_multiplier(self):
        self.assertEqual(apply_size_multiplier(100, 0.5), 50)
        self.assertEqual(apply_size_multiplier(100, 1.0), 100)
        self.assertEqual(apply_size_multiplier(100, 0.0), 0)

    def test_lot_rounding_after_scaling(self):
        # 150 * 0.5 = 75 -> below one CN lot -> 0
        self.assertEqual(apply_size_multiplier(150, 0.5, lot_size=100), 0)
        self.assertEqual(apply_size_multiplier(400, 0.5, lot_size=100), 200)

    def test_rejects_off_enum_multiplier(self):
        with self.assertRaises(ValueError):
            apply_size_multiplier(100, 0.7)


class _FakeEngine:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def run(self, symbol, tier2, dimensions):
        self.calls.append(symbol)
        return self._result


class TestTier3Stage(unittest.TestCase):
    def _state(self, tier2=None, dimensions=None):
        state = TierState(symbol="AAPL", market=Market.US)
        if tier2 is not None:
            state.reports[2] = tier2
        state.dimensions = dimensions or []
        return state

    def _verdict_result(self, **overrides):
        fields = dict(
            stance=Direction.BUY, size_multiplier=0.5, stop_advice="tighten",
            tightened_stop=92.0, summary="half size", key_risks=(),
        )
        fields.update(overrides)
        return RiskResult(takes=[], verdict=RiskVerdict(**fields))

    def test_verdict_sets_stance_multiplier_and_tightened_stop(self):
        state = self._state(_tier2(), dimensions=[_technicals()])
        report = Tier3Stage(engine=_FakeEngine(self._verdict_result())).run(state)
        self.assertEqual(report.tier, 3)
        self.assertEqual(report.coverage, Coverage.FULL)
        self.assertEqual(report.direction, Direction.BUY)
        self.assertAlmostEqual(report.levels.stop_loss, 92.0)  # tightened by code
        self.assertAlmostEqual(report.levels.entry, 96.0)  # others carried
        self.assertEqual(report.risk_detail["verdict"]["size_multiplier"], 0.5)
        self.assertEqual(report.narrative, "half size")

    def test_keep_advice_leaves_stop_untouched(self):
        result = self._verdict_result(stop_advice="keep", tightened_stop=None)
        state = self._state(_tier2(), dimensions=[_technicals()])
        report = Tier3Stage(engine=_FakeEngine(result)).run(state)
        self.assertAlmostEqual(report.levels.stop_loss, 90.0)

    def test_no_verdict_falls_back_to_tier2(self):
        state = self._state(_tier2(Direction.HOLD), dimensions=[_technicals()])
        report = Tier3Stage(engine=_FakeEngine(RiskResult(warnings=["down"]))).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.HOLD)
        self.assertTrue(any("falls back to tier 2" in w for w in report.warnings))

    def test_missing_tier2_report_is_unavailable(self):
        report = Tier3Stage(engine=_FakeEngine(None)).run(self._state())
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)

    def test_no_evidence_skips_engine(self):
        engine = _FakeEngine(self._verdict_result())
        report = Tier3Stage(engine=engine).run(self._state(_tier2()))
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.BUY)
        self.assertEqual(engine.calls, [])


if __name__ == "__main__":
    unittest.main()
