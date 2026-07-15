# -*- coding: utf-8 -*-
"""Offline tests for the tier-2 threaded debate (v4 redesign).

Fake-LLM tests covering: choreography (parallel arguments → parallel
attacks → parallel responses → grading judge → summary judge), the
deterministic verdict formula (validity-weighted average of the two
position scores), the 0-3/4-6/7-10 direction thresholds, evidence
validation of debater citations, mechanical verbatim checking of the
judge's quotes, and every degradation path — an off-spec position score
or grade voids the verdict (tier 2 then falls back to tier 1), a bad or
missing quote only flags, and a broken summary never voids a computed
verdict.

Because each stage runs its two calls in parallel threads, the fake LLM
routes replies by prompt content, not call order.
"""
from __future__ import annotations

import json
import threading
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


# Deterministic turn texts — the judge's quotes below must appear in these
# verbatim, exactly like the real quote check demands.
TEXTS = {
    "bull_argument": "Momentum is strong. The trend is up.",
    "bear_attack": "The bull overstates momentum.",
    "bull_response": "I stand by the momentum case.",
    "bear_argument": "Valuation is stretched. Downside risk is real.",
    "bull_attack": "The bear misreads valuation.",
    "bear_response": "I concede part of the valuation point.",
}


def _turn_json(text, citations=("technicals.rsi_14",), position_score=None):
    body = {"argument": text, "citations": list(citations)}
    if position_score is not None:
        body["position_score"] = position_score
    return json.dumps(body)


def _axis(score, quote=None, why=None):
    return {"score": score, "quote": quote, "why": why}


def _grades_json(bull=None, bear=None):
    """Default grades: bull (4,5,4) weight 13/15, bear (2,3,3) weight 8/15.
    Every sub-5 axis quotes a sentence that really exists in TEXTS."""
    return json.dumps(
        {
            "bull": bull
            or {
                "citation_validity": _axis(4, "The trend is up.", "Trend not in the cited field."),
                "knowledge_validity": _axis(5),
                "logical_validity": _axis(4, "Momentum is strong.", "Overstated from one indicator."),
            },
            "bear": bear
            or {
                "citation_validity": _axis(2, "Valuation is stretched.", "Cited ratio does not show that."),
                "knowledge_validity": _axis(3, "Downside risk is real.", "Asserted, not grounded."),
                "logical_validity": _axis(3, "The bull overstates momentum.", "Attack gave no specifics."),
            },
        }
    )


def _summary_json():
    return json.dumps(
        {
            "summary": "The weighted result lands at hold.",
            "bull_summary": "Corrected bull case.",
            "bear_summary": "Corrected bear case.",
        }
    )


# Prompt markers, one per distinct call the engine makes.
MARKERS = {
    "bull_argument": "You are the BULL analyst: argue",
    "bear_argument": "You are the BEAR analyst: argue",
    "bear_attack": "You are the BEAR analyst. Your opponent, the BULL",
    "bull_attack": "You are the BULL analyst. Your opponent, the BEAR",
    "bull_response": "You are the BULL analyst. Your opening argument was",
    "bear_response": "You are the BEAR analyst. Your opening argument was",
    "grading": "You are the research manager grading",
    "summary": "Write the user-facing report",
}


def _replies(bull_score=8, bear_score=3, grades=None, summary=None, **overrides):
    """The standard 8-call reply set, keyed by MARKERS name."""
    replies = {
        "bull_argument": _turn_json(TEXTS["bull_argument"]),
        "bear_argument": _turn_json(TEXTS["bear_argument"], citations=("citation:1",)),
        "bear_attack": _turn_json(TEXTS["bear_attack"], citations=()),
        "bull_attack": _turn_json(TEXTS["bull_attack"], citations=()),
        "bull_response": _turn_json(
            TEXTS["bull_response"], position_score=bull_score
        ),
        "bear_response": _turn_json(
            TEXTS["bear_response"], citations=("citation:1",), position_score=bear_score
        ),
        "grading": grades if grades is not None else _grades_json(),
        "summary": summary if summary is not None else _summary_json(),
    }
    replies.update(overrides)
    return replies


class RoutedSummarizer:
    """Routes each prompt to a reply by its stage marker; thread-safe."""

    def __init__(self, replies):
        self._replies = replies
        self._lock = threading.Lock()
        self.prompts = {}

    def __call__(self, prompt):
        for name, marker in MARKERS.items():
            if marker in prompt:
                with self._lock:
                    self.prompts[name] = prompt
                reply = self._replies.get(name)
                if reply is None:
                    raise AssertionError(f"no scripted reply for stage {name}")
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise AssertionError("prompt matched no known stage: " + prompt[:120])


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
        llm = RoutedSummarizer(replies)
        return DebateEngine(summarizer=llm).run("AAPL", _tier1(), self._dims()), llm

    def test_full_choreography_and_the_weighted_verdict(self):
        result, llm = self._run(_replies())
        self.assertEqual(len(llm.prompts), 8)
        self.assertEqual(
            [(t.role, t.kind) for t in result.turns],
            [
                ("bull", "argument"),
                ("bear", "attack"),
                ("bull", "response"),
                ("bear", "argument"),
                ("bull", "attack"),
                ("bear", "response"),
            ],
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
        grades = _grades_json(
            bull={axis: _axis(5) for axis in (
                "citation_validity", "knowledge_validity", "logical_validity")},
            bear={
                "citation_validity": _axis(1, "Valuation is stretched.", "Not what the ratio shows."),
                "knowledge_validity": _axis(1, "Downside risk is real.", "No grounding."),
                "logical_validity": _axis(1, "The bull overstates momentum.", "No specifics."),
            },
        )
        result, _ = self._run(_replies(bull_score=8, bear_score=2, grades=grades))
        self.assertAlmostEqual(result.verdict.final_score, 7.0)
        self.assertEqual(result.verdict.direction, Direction.BUY)

    def test_both_zero_validity_defaults_to_neutral_five(self):
        zero = {
            "citation_validity": _axis(0, TEXTS["bull_argument"].split(". ")[0] + ".", "wrong"),
            "knowledge_validity": _axis(0, "The trend is up.", "wrong"),
            "logical_validity": _axis(0, "The trend is up.", "wrong"),
        }
        zero_bear = {
            "citation_validity": _axis(0, "Valuation is stretched.", "wrong"),
            "knowledge_validity": _axis(0, "Valuation is stretched.", "wrong"),
            "logical_validity": _axis(0, "Valuation is stretched.", "wrong"),
        }
        result, _ = self._run(_replies(grades=_grades_json(bull=zero, bear=zero_bear)))
        self.assertEqual(result.verdict.final_score, 5.0)
        self.assertEqual(result.verdict.direction, Direction.HOLD)
        self.assertTrue(any("zero validity" in w for w in result.warnings))

    def test_scoring_carries_grades_weights_and_comments(self):
        result, _ = self._run(_replies())
        bull = result.verdict.scoring["bull"]
        self.assertEqual(bull.position_score, 8)
        self.assertEqual(
            (
                bull.citation_validity.score,
                bull.knowledge_validity.score,
                bull.logical_validity.score,
            ),
            (4, 5, 4),
        )
        self.assertAlmostEqual(bull.weight, 13 / 15)
        # sub-5 grade carries the quoted sentence and the reason
        self.assertEqual(bull.citation_validity.quote, "The trend is up.")
        self.assertEqual(bull.citation_validity.why, "Trend not in the cited field.")
        # a flawless grade carries no comment (N/A in the UI)
        self.assertIsNone(bull.knowledge_validity.quote)
        self.assertIsNone(bull.knowledge_validity.why)

    def test_a_quote_on_a_perfect_grade_is_discarded(self):
        grades = _grades_json(
            bull={
                "citation_validity": _axis(5, "The trend is up.", "needless comment"),
                "knowledge_validity": _axis(5),
                "logical_validity": _axis(5),
            }
        )
        result, _ = self._run(_replies(grades=grades))
        self.assertIsNone(result.verdict.scoring["bull"].citation_validity.quote)
        self.assertEqual(result.warnings, [])

    def test_unverifiable_judge_quote_is_flagged_but_grade_stands(self):
        grades = _grades_json(
            bull={
                "citation_validity": _axis(4, "A sentence nobody wrote.", "made up"),
                "knowledge_validity": _axis(5),
                "logical_validity": _axis(5),
            }
        )
        result, _ = self._run(_replies(grades=grades))
        self.assertIsNotNone(result.verdict)
        self.assertEqual(result.verdict.scoring["bull"].citation_validity.score, 4)
        self.assertTrue(any("not found verbatim" in w for w in result.warnings))

    def test_missing_judge_quote_on_a_sub5_grade_is_flagged(self):
        grades = _grades_json(
            bull={
                "citation_validity": _axis(4),
                "knowledge_validity": _axis(5),
                "logical_validity": _axis(5),
            }
        )
        result, _ = self._run(_replies(grades=grades))
        self.assertIsNotNone(result.verdict)
        self.assertTrue(any("gave no quote" in w for w in result.warnings))

    def test_bare_number_grade_cell_is_tolerated(self):
        # A v3-shaped judge reply (plain ints) still grades; sub-5 scores
        # just get the missing-quote flag.
        grades = json.dumps(
            {
                "bull": {"citation_validity": 4, "knowledge_validity": 5,
                         "logical_validity": 4},
                "bear": {"citation_validity": 5, "knowledge_validity": 5,
                         "logical_validity": 5},
            }
        )
        result, _ = self._run(_replies(grades=grades))
        self.assertIsNotNone(result.verdict)
        self.assertAlmostEqual(result.verdict.scoring["bull"].weight, 13 / 15)
        self.assertTrue(any("gave no quote" in w for w in result.warnings))

    def test_debater_citations_are_validated(self):
        replies = _replies(
            bull_argument=_turn_json(
                TEXTS["bull_argument"],
                citations=("technicals.rsi_14", "technicals.nope"),
            )
        )
        result, _ = self._run(replies)
        self.assertEqual(result.turns[0].citations, ("technicals.rsi_14",))
        self.assertTrue(any("does not resolve" in w for w in result.warnings))

    def test_non_whole_position_score_voids_the_verdict(self):
        replies = _replies()
        replies["bear_response"] = _turn_json(TEXTS["bear_response"], position_score=7.5)
        result, _ = self._run(replies)
        self.assertIsNone(result.verdict)
        self.assertEqual(len(result.turns), 6)  # transcript kept
        self.assertTrue(any("verdict voided" in w for w in result.warnings))

    def test_non_json_response_keeps_text_but_voids_the_verdict(self):
        replies = _replies()
        replies["bull_response"] = "the vibes are good"
        result, _ = self._run(replies)
        bull_response = result.turns[2]
        self.assertEqual(bull_response.argument, "the vibes are good")
        self.assertIsNone(bull_response.position_score)
        self.assertIsNone(result.verdict)
        self.assertTrue(any("no usable position score from bull" in w
                            for w in result.warnings))

    def test_non_json_argument_degrades_but_the_debate_continues(self):
        # Only response turns carry the score, so a plain-text opening
        # argument is kept as-is and the verdict still computes.
        replies = _replies()
        replies["bear_argument"] = "just some prose"
        result, _ = self._run(replies)
        self.assertEqual(result.turns[3].argument, "just some prose")
        self.assertIsNotNone(result.verdict)
        self.assertTrue(any("bear argument was not JSON" in w for w in result.warnings))

    def test_unparseable_grading_judge_voids_the_verdict(self):
        result, _ = self._run(_replies(grades="no json here"))
        self.assertIsNone(result.verdict)
        self.assertTrue(any("unparseable" in w for w in result.warnings))

    def test_out_of_range_grade_voids_the_verdict(self):
        grades = _grades_json(
            bull={
                "citation_validity": _axis(6),
                "knowledge_validity": _axis(5),
                "logical_validity": _axis(5),
            }
        )
        result, _ = self._run(_replies(grades=grades))
        self.assertIsNone(result.verdict)
        self.assertTrue(any("whole number 0-5" in w for w in result.warnings))

    def test_broken_summary_never_voids_a_computed_verdict(self):
        result, _ = self._run(_replies(summary="not json"))
        self.assertIsNotNone(result.verdict)
        self.assertEqual(result.verdict.direction, Direction.HOLD)
        self.assertEqual(result.verdict.summary, "")
        self.assertTrue(any("verdict stands" in w for w in result.warnings))

    def test_summary_llm_failure_never_voids_a_computed_verdict(self):
        replies = _replies()
        replies["summary"] = RuntimeError("model down")
        result, _ = self._run(replies)
        self.assertIsNotNone(result.verdict)
        self.assertTrue(any("model down" in w for w in result.warnings))

    def test_llm_failure_mid_debate_keeps_the_partial_transcript(self):
        replies = _replies()
        replies["bear_attack"] = RuntimeError("model down")
        result, _ = self._run(replies)
        self.assertIsNone(result.verdict)
        # both opening arguments survive the stage-2 crash
        self.assertEqual(
            [(t.role, t.kind) for t in result.turns],
            [("bull", "argument"), ("bear", "argument")],
        )
        self.assertTrue(any("model down" in w for w in result.warnings))

    def test_parallel_stage_calls_report_into_the_active_tracker(self):
        # The tracker is thread-local; the engine must hand it to its
        # worker threads or 6 of the 8 calls vanish from the usage numbers.
        from src.tiered_analysis.llm_support import LlmUsageTracker, record_llm_usage

        inner = RoutedSummarizer(_replies())

        def summarizer(prompt):
            record_llm_usage(10, 5)
            return inner(prompt)

        tracker = LlmUsageTracker()
        with tracker.activate(), tracker.stage("tier2_debate"):
            result = DebateEngine(summarizer=summarizer).run(
                "AAPL", _tier1(), self._dims()
            )
        self.assertIsNotNone(result.verdict)
        detail = tracker.to_detail()
        self.assertEqual(detail["stages"]["tier2_debate"]["calls"], 8)
        self.assertEqual(detail["total"]["prompt_tokens"], 80)

    def test_argument_prompts_carry_evidence_and_tier1_context(self):
        _, llm = self._run(_replies())
        bull_prompt = llm.prompts["bull_argument"]
        self.assertIn("rsi_14", bull_prompt)  # evidence bundle
        self.assertIn("citation:N", bull_prompt)  # citation grammar
        self.assertIn("direction=buy", bull_prompt)  # tier-1 context
        self.assertIn("96.0", bull_prompt)  # tier-1 levels

    def test_attack_prompt_carries_the_opponents_argument_and_the_axes(self):
        _, llm = self._run(_replies())
        attack_prompt = llm.prompts["bear_attack"]
        self.assertIn(TEXTS["bull_argument"], attack_prompt)
        self.assertIn("cited: technicals.rsi_14", attack_prompt)
        self.assertIn("citation validity", attack_prompt)
        self.assertIn("logical validity", attack_prompt)

    def test_response_prompt_carries_own_argument_and_the_attack(self):
        _, llm = self._run(_replies())
        response_prompt = llm.prompts["bull_response"]
        self.assertIn(TEXTS["bull_argument"], response_prompt)
        self.assertIn(TEXTS["bear_attack"], response_prompt)
        self.assertIn("position_score", response_prompt)

    def test_grading_prompt_shows_all_six_turns_and_the_verbatim_rule(self):
        _, llm = self._run(_replies())
        grading_prompt = llm.prompts["grading"]
        for text in TEXTS.values():
            self.assertIn(text, grading_prompt)
        self.assertIn("position score 8/10", grading_prompt)
        self.assertIn("attack on the bull's argument", grading_prompt)
        self.assertIn("verbatim", grading_prompt)
        self.assertIn("costs the attacker points", grading_prompt)

    def test_summary_prompt_carries_the_computed_result_and_the_quotes(self):
        _, llm = self._run(_replies())
        summary_prompt = llm.prompts["summary"]
        self.assertIn("6.1", summary_prompt)  # final, 1 decimal
        self.assertIn("verdict hold", summary_prompt)
        self.assertIn("0-3 sell, 4-6 hold, 7-10 buy", summary_prompt)
        self.assertIn("citation 4/5", summary_prompt)  # grades block
        self.assertIn("The trend is up.", summary_prompt)  # judge quote

    def test_to_detail_is_json_ready_with_scoring_and_legacy_keys(self):
        result, _ = self._run(_replies())
        detail = result.to_detail()
        json.dumps(detail)  # must not raise
        verdict = detail["verdict"]
        self.assertEqual(verdict["direction"], "hold")
        self.assertEqual(verdict["final_score_rounded"], 6)
        bull_scoring = verdict["scoring"]["bull"]
        self.assertAlmostEqual(bull_scoring["weight"], 0.8667)
        self.assertEqual(bull_scoring["position_score"], 8)
        self.assertEqual(bull_scoring["citation_validity"],
                         {"score": 4, "quote": "The trend is up.",
                          "why": "Trend not in the cited field."})
        self.assertEqual(bull_scoring["knowledge_validity"],
                         {"score": 5, "quote": None, "why": None})
        first_turn = detail["turns"][0]
        self.assertEqual(first_turn["kind"], "argument")
        self.assertIsNone(first_turn["position_score"])
        self.assertEqual(detail["turns"][2]["position_score"], 8)
        self.assertEqual(first_turn["citations"], ["technicals.rsi_14"])
        # legacy keys pre-redesign readers rely on
        self.assertEqual(bull_scoring["bullishness"], 8)
        self.assertEqual(detail["turns"][2]["bullishness"], 8)
        self.assertIsNone(verdict["confidence"])
        self.assertEqual(verdict["reasons_for"], [])


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
        self.assertIsNone(report.confidence)  # no judge confidence since v3
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
