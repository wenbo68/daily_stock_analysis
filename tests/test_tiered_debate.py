# -*- coding: utf-8 -*-
"""Offline tests for the tier-2 bull/bear debate (v2 slice 4).

Fake-LLM tests covering: round choreography (bull -> bear x rounds ->
judge), verdict parsing, evidence anchoring of judge claims, and every
degradation path (LLM failure, unparseable judge, unusable direction) —
each of which must fall back to the tier-1 direction, never crash.
"""
from __future__ import annotations

import json
import unittest

from src.tiered_analysis.debate import DebateEngine, DebateResult, DebateVerdict
from src.tiered_analysis.providers.base import (
    Citation,
    Coverage,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.tiers import Tier2Stage, TierState


def _technicals():
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
        payload={"close": 100.0, "rsi_14": 71.2, "score": 68},
    )


def _sentiment():
    return DimensionResult(
        dimension="sentiment",
        kind=SourceKind.TEXTUAL,
        coverage=Coverage.FULL,
        narrative="Sentiment: positive. Big deal announced [1].",
        citations=[Citation(source_name="reuters", url="https://ex.com/1")],
    )


def _tier1(direction=Direction.BUY, dimensions=()):
    return TierReport(
        tier=1,
        symbol="AAPL",
        market=Market.US,
        coverage=Coverage.FULL,
        direction=direction,
        score=68,
        levels=SniperLevels(entry=96.0, secondary_entry=94.0,
                            stop_loss=90.0, take_profit=108.0),
        narrative="buy the pullback",
        dimensions=list(dimensions),
    )


def _judge_json(direction="hold", confidence=0.62, **overrides):
    body = {
        "direction": direction,
        "confidence": confidence,
        "summary": "The bear's valuation concern outweighs the momentum case.",
        "reasons_for": [
            {"claim": "Momentum is strong", "evidence": ["technicals.rsi_14"]},
        ],
        "reasons_against": [
            {"claim": "News-driven spike may fade", "evidence": ["citation:1"]},
        ],
        "would_change_mind": "a confirmed earnings beat",
    }
    body.update(overrides)
    return json.dumps(body)


class ScriptedSummarizer:
    """Returns queued replies in order; records every prompt."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self._replies:
            raise AssertionError("summarizer called more times than scripted")
        return self._replies.pop(0)


class TestDebateEngine(unittest.TestCase):
    def _dims(self):
        return [_technicals(), _sentiment()]

    def test_one_round_is_bull_bear_judge(self):
        llm = ScriptedSummarizer(["bull says up", "bear says down", _judge_json()])
        result = DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims())
        self.assertEqual(len(llm.prompts), 3)
        self.assertEqual(
            [(t.role, t.round) for t in result.turns],
            [("bull", 1), ("bear", 1)],
        )
        self.assertEqual(result.verdict.direction, Direction.HOLD)
        self.assertAlmostEqual(result.verdict.confidence, 0.62)
        self.assertIn("valuation concern", result.verdict.summary)
        self.assertEqual(result.warnings, [])

    def test_two_rounds_produce_four_turns_and_shared_transcript(self):
        llm = ScriptedSummarizer(
            ["bull r1", "bear r1", "bull r2", "bear r2", _judge_json()]
        )
        result = DebateEngine(summarizer=llm, rounds=2).run(
            "AAPL", _tier1(), self._dims()
        )
        self.assertEqual(len(result.turns), 4)
        # the bear's round-2 prompt must contain the bull's round-2 argument
        self.assertIn("bull r2", llm.prompts[3])
        # the judge sees the whole transcript
        self.assertIn("bear r2", llm.prompts[4])

    def test_prompts_carry_evidence_and_tier1_context(self):
        llm = ScriptedSummarizer(["b", "r", _judge_json()])
        DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims())
        bull_prompt = llm.prompts[0]
        self.assertIn("rsi_14", bull_prompt)  # evidence bundle
        self.assertIn("citation:1", bull_prompt)  # citation grammar
        self.assertIn("direction=buy", bull_prompt)  # tier-1 context
        self.assertIn("96.0", bull_prompt)  # tier-1 levels

    def test_judge_reason_evidence_is_validated(self):
        result_json = _judge_json(
            reasons_for=[{"claim": "Momentum", "evidence": ["technicals.rsi_14"]}],
            reasons_against=[{"claim": "Made up", "evidence": ["technicals.nope"]}],
        )
        llm = ScriptedSummarizer(["b", "r", result_json])
        result = DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims())
        self.assertEqual(
            result.verdict.reasons_for[0].evidence, ("technicals.rsi_14",)
        )
        # unanchored claim is kept but flagged
        self.assertEqual(result.verdict.reasons_against[0].evidence, ())
        self.assertTrue(any("not anchored" in w for w in result.warnings))

    def test_bad_confidence_dropped_with_warning(self):
        llm = ScriptedSummarizer(["b", "r", _judge_json(confidence=7)])
        result = DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims())
        self.assertIsNone(result.verdict.confidence)
        self.assertTrue(any("confidence" in w for w in result.warnings))

    def test_unparseable_judge_means_no_verdict(self):
        llm = ScriptedSummarizer(["b", "r", "the vibes are good"])
        result = DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims())
        self.assertIsNone(result.verdict)
        self.assertTrue(result.warnings)

    def test_unusable_direction_means_no_verdict(self):
        llm = ScriptedSummarizer(["b", "r", _judge_json(direction="yolo")])
        result = DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims())
        self.assertIsNone(result.verdict)

    def test_llm_failure_mid_debate_keeps_partial_transcript(self):
        def flaky(prompt):
            if "BEAR" in prompt:
                raise RuntimeError("model down")
            return "bull argument"

        llm_calls = []

        def wrapper(prompt):
            llm_calls.append(prompt)
            return flaky(prompt)

        result = DebateEngine(summarizer=wrapper).run("AAPL", _tier1(), self._dims())
        self.assertIsNone(result.verdict)
        self.assertEqual([t.role for t in result.turns], ["bull"])
        self.assertTrue(any("model down" in w for w in result.warnings))

    def test_to_detail_is_json_ready(self):
        llm = ScriptedSummarizer(["b", "r", _judge_json()])
        result = DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims())
        detail = result.to_detail()
        json.dumps(detail)  # must not raise
        self.assertEqual(detail["verdict"]["direction"], "hold")
        self.assertEqual(len(detail["turns"]), 2)

    def test_rejects_zero_rounds(self):
        with self.assertRaises(ValueError):
            DebateEngine(summarizer=lambda p: "", rounds=0)


class _FakeEngine:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def run(self, symbol, tier1, dimensions):
        self.calls.append((symbol, len(list(dimensions))))
        return self._result


class TestTier2Stage(unittest.TestCase):
    def _state(self, tier1=None, dimensions=None):
        state = TierState(symbol="AAPL", market=Market.US)
        if tier1 is not None:
            state.reports[1] = tier1
        if dimensions is not None:
            state.dimensions = dimensions
        return state

    def _verdict_result(self, direction=Direction.HOLD):
        return DebateResult(
            turns=[],
            verdict=DebateVerdict(
                direction=direction, confidence=0.62, summary="ruling"
            ),
        )

    def test_verdict_updates_direction_and_keeps_levels(self):
        engine = _FakeEngine(self._verdict_result())
        state = self._state(_tier1(Direction.BUY), dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.tier, 2)
        self.assertEqual(report.coverage, Coverage.FULL)
        self.assertEqual(report.direction, Direction.HOLD)  # judge overruled
        self.assertEqual(report.confidence, "0.62")
        self.assertAlmostEqual(report.levels.entry, 96.0)
        self.assertEqual(report.narrative, "ruling")
        self.assertIsNotNone(report.debate_detail)

    def test_no_verdict_falls_back_to_tier1_direction(self):
        engine = _FakeEngine(DebateResult(warnings=["judge exploded"]))
        state = self._state(_tier1(Direction.BUY), dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.BUY)
        self.assertTrue(any("falls back to tier 1" in w for w in report.warnings))

    def test_missing_tier1_report_is_unavailable(self):
        report = Tier2Stage(engine=_FakeEngine(None)).run(self._state())
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)

    def test_no_evidence_skips_engine_entirely(self):
        engine = _FakeEngine(self._verdict_result())
        state = self._state(_tier1(Direction.BUY))  # no dimensions anywhere
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.BUY)
        self.assertEqual(engine.calls, [])

    def test_dimensions_fall_back_to_tier1_report(self):
        engine = _FakeEngine(self._verdict_result())
        tier1 = _tier1(Direction.BUY, dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(self._state(tier1))
        self.assertEqual(report.coverage, Coverage.FULL)
        self.assertEqual(engine.calls, [("AAPL", 1)])


if __name__ == "__main__":
    unittest.main()
