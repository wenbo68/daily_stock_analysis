# -*- coding: utf-8 -*-
"""Offline tests for the tier-2 scored debate (v3 redesign).

Fake-LLM tests covering: choreography (bull -> bear x rounds -> grading
judge -> summary judge), the deterministic verdict formula
(validity-weighted average of the debaters' bullishness scores), the
0-3/4-6/7-10 direction thresholds, evidence validation of debater
citations, and every degradation path — off-spec numbers void the verdict
(tier 2 then falls back to tier 1), but a broken summary never voids a
computed verdict.
"""
from __future__ import annotations

import json
import unittest

from src.tiered_analysis.debate import (
    DebateEngine,
    DebateResult,
    DebateVerdict,
    direction_from_score,
)
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


def _debater_json(bullishness, citations=("technicals.rsi_14",), argument="case"):
    return json.dumps(
        {"argument": argument, "citations": list(citations), "bullishness": bullishness}
    )


def _grades_json(bull=(4, 5, 4), bear=(2, 3, 3), **overrides):
    def _side(scores):
        c, k, l = scores
        return {
            "citation_validity": c,
            "knowledge_validity": k,
            "logical_validity": l,
            "notes": "graded",
        }

    body = {"bull": _side(bull), "bear": _side(bear)}
    body.update(overrides)
    return json.dumps(body)


def _summary_json():
    return json.dumps(
        {
            "summary": "The weighted result lands at hold.",
            "bull_summary": "Corrected bull case.",
            "bear_summary": "Corrected bear case.",
        }
    )


def _script(bull=8, bear=3, grades=None, summary=None):
    """The standard 4-call script: bull, bear, grading judge, summary judge."""
    return [
        _debater_json(bull),
        _debater_json(bear, citations=("citation:1",)),
        grades if grades is not None else _grades_json(),
        summary if summary is not None else _summary_json(),
    ]


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


class TestDirectionThresholds(unittest.TestCase):
    def test_owner_spec_ranges(self):
        for value in (0, 1, 2, 3):
            self.assertEqual(direction_from_score(value), Direction.SELL)
        for value in (4, 5, 6):
            self.assertEqual(direction_from_score(value), Direction.HOLD)
        for value in (7, 8, 9, 10):
            self.assertEqual(direction_from_score(value), Direction.BUY)


class TestDebateEngine(unittest.TestCase):
    def _dims(self):
        return [_technicals(), _sentiment()]

    def _run(self, replies):
        llm = ScriptedSummarizer(replies)
        return DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims()), llm

    def test_one_round_is_bull_bear_grader_summarizer(self):
        result, llm = self._run(_script())
        self.assertEqual(len(llm.prompts), 4)
        self.assertEqual(
            [(t.role, t.round) for t in result.turns],
            [("bull", 1), ("bear", 1)],
        )
        # bull 8 weighted 13/15, bear 3 weighted 8/15:
        # (13*8 + 8*3) / 21 = 128/21 ≈ 6.095 → 6 → hold
        self.assertAlmostEqual(result.verdict.final_score, 128 / 21)
        self.assertEqual(result.verdict.final_score_rounded, 6)
        self.assertEqual(result.verdict.direction, Direction.HOLD)
        self.assertEqual(result.verdict.summary, "The weighted result lands at hold.")
        self.assertEqual(result.verdict.bull_summary, "Corrected bull case.")
        self.assertEqual(result.warnings, [])

    def test_better_argued_side_pulls_the_final_number(self):
        # bull 8 at full validity, bear 2 at 3/15 → (1*8 + 0.2*2)/1.2 = 7 → buy
        result, _ = self._run(_script(bull=8, bear=2, grades=_grades_json(
            bull=(5, 5, 5), bear=(1, 1, 1))))
        self.assertAlmostEqual(result.verdict.final_score, 7.0)
        self.assertEqual(result.verdict.direction, Direction.BUY)

    def test_both_zero_validity_defaults_to_neutral_five(self):
        result, _ = self._run(_script(grades=_grades_json(bull=(0, 0, 0), bear=(0, 0, 0))))
        self.assertEqual(result.verdict.final_score, 5.0)
        self.assertEqual(result.verdict.direction, Direction.HOLD)
        self.assertTrue(any("zero validity" in w for w in result.warnings))

    def test_scoring_carries_grades_and_weights(self):
        result, _ = self._run(_script())
        bull = result.verdict.scoring["bull"]
        self.assertEqual(bull.bullishness, 8)
        self.assertEqual(
            (bull.citation_validity, bull.knowledge_validity, bull.logical_validity),
            (4, 5, 4),
        )
        self.assertAlmostEqual(bull.weight, 13 / 15)
        self.assertEqual(bull.notes, "graded")

    def test_debater_citations_are_validated(self):
        replies = _script()
        replies[0] = _debater_json(8, citations=("technicals.rsi_14", "technicals.nope"))
        result, _ = self._run(replies)
        self.assertEqual(result.turns[0].citations, ("technicals.rsi_14",))
        self.assertTrue(any("does not resolve" in w for w in result.warnings))

    def test_non_whole_bullishness_voids_the_verdict(self):
        replies = _script()
        replies[1] = _debater_json(7.5)
        result, _ = self._run(replies[:3])  # summary call never happens
        self.assertIsNone(result.verdict)
        self.assertEqual(len(result.turns), 2)  # transcript kept
        self.assertTrue(any("verdict voided" in w for w in result.warnings))

    def test_non_json_debater_keeps_text_but_voids_the_verdict(self):
        replies = _script()
        replies[0] = "the vibes are good"
        result, _ = self._run(replies[:3])
        self.assertEqual(result.turns[0].argument, "the vibes are good")
        self.assertIsNone(result.turns[0].bullishness)
        self.assertIsNone(result.verdict)

    def test_unparseable_grading_judge_voids_the_verdict(self):
        result, _ = self._run(_script(grades="no json here")[:3])
        self.assertIsNone(result.verdict)
        self.assertTrue(any("unparseable" in w for w in result.warnings))

    def test_out_of_range_grade_voids_the_verdict(self):
        result, _ = self._run(_script(grades=_grades_json(bull=(6, 5, 4)))[:3])
        self.assertIsNone(result.verdict)
        self.assertTrue(any("whole number 0-5" in w for w in result.warnings))

    def test_broken_summary_never_voids_a_computed_verdict(self):
        result, _ = self._run(_script(summary="not json"))
        self.assertIsNotNone(result.verdict)
        self.assertEqual(result.verdict.direction, Direction.HOLD)
        self.assertEqual(result.verdict.summary, "")
        self.assertTrue(any("verdict stands" in w for w in result.warnings))

    def test_summary_llm_failure_never_voids_a_computed_verdict(self):
        replies = _script()[:3]
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            if calls["n"] > 3:
                raise RuntimeError("model down")
            return replies[calls["n"] - 1]

        result = DebateEngine(summarizer=flaky).run("AAPL", _tier1(), self._dims())
        self.assertIsNotNone(result.verdict)
        self.assertTrue(any("model down" in w for w in result.warnings))

    def test_two_rounds_use_each_debaters_last_score(self):
        replies = [
            _debater_json(2),  # bull r1
            _debater_json(3, citations=("citation:1",)),  # bear r1
            _debater_json(8),  # bull r2 — this one counts
            _debater_json(3, citations=("citation:1",)),  # bear r2
            _grades_json(),
            _summary_json(),
        ]
        llm = ScriptedSummarizer(replies)
        result = DebateEngine(summarizer=llm, rounds=2).run(
            "AAPL", _tier1(), self._dims()
        )
        self.assertEqual(len(result.turns), 4)
        self.assertEqual(result.verdict.scoring["bull"].bullishness, 8)
        # the bear's round-2 prompt must contain the bull's round-2 turn
        self.assertIn("bullishness 8/10", llm.prompts[3])

    def test_prompts_carry_evidence_and_tier1_context(self):
        _, llm = self._run(_script())
        bull_prompt = llm.prompts[0]
        self.assertIn("rsi_14", bull_prompt)  # evidence bundle
        self.assertIn("citation:N", bull_prompt)  # citation grammar
        self.assertIn("direction=buy", bull_prompt)  # tier-1 context
        self.assertIn("96.0", bull_prompt)  # tier-1 levels

    def test_grading_prompt_shows_scores_and_citations(self):
        _, llm = self._run(_script())
        grading_prompt = llm.prompts[2]
        self.assertIn("bullishness 8/10", grading_prompt)
        self.assertIn("cited: technicals.rsi_14", grading_prompt)
        self.assertIn("citation_validity", grading_prompt)

    def test_summary_prompt_carries_the_computed_result(self):
        _, llm = self._run(_script())
        summary_prompt = llm.prompts[3]
        self.assertIn("6.1", summary_prompt)  # final, 1 decimal
        self.assertIn("verdict hold", summary_prompt)
        self.assertIn("0-3 sell, 4-6 hold, 7-10 buy", summary_prompt)
        self.assertIn("citation 4/5", summary_prompt)  # grades block

    def test_llm_failure_mid_debate_keeps_partial_transcript(self):
        def flaky(prompt):
            if "BEAR" in prompt:
                raise RuntimeError("model down")
            return _debater_json(8)

        result = DebateEngine(summarizer=flaky).run("AAPL", _tier1(), self._dims())
        self.assertIsNone(result.verdict)
        self.assertEqual([t.role for t in result.turns], ["bull"])
        self.assertTrue(any("model down" in w for w in result.warnings))

    def test_to_detail_is_json_ready_with_scoring_and_legacy_keys(self):
        result, _ = self._run(_script())
        detail = result.to_detail()
        json.dumps(detail)  # must not raise
        verdict = detail["verdict"]
        self.assertEqual(verdict["direction"], "hold")
        self.assertEqual(verdict["final_score_rounded"], 6)
        self.assertAlmostEqual(verdict["scoring"]["bull"]["weight"], 0.8667)
        self.assertEqual(detail["turns"][0]["bullishness"], 8)
        self.assertEqual(detail["turns"][0]["citations"], ["technicals.rsi_14"])
        # legacy keys pre-redesign readers rely on
        self.assertIsNone(verdict["confidence"])
        self.assertEqual(verdict["reasons_for"], [])

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
                direction=direction,
                final_score=6.1,
                final_score_rounded=6,
                summary="ruling",
            ),
        )

    def test_verdict_updates_direction_and_keeps_levels(self):
        engine = _FakeEngine(self._verdict_result())
        state = self._state(_tier1(Direction.BUY), dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.tier, 2)
        self.assertEqual(report.coverage, Coverage.FULL)
        self.assertEqual(report.direction, Direction.HOLD)  # formula overruled
        self.assertIsNone(report.confidence)  # no judge confidence in v3
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
