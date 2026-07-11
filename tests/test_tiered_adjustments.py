# -*- coding: utf-8 -*-
"""Offline tests for the LLM level-adjustment contract (v2 slice 3).

The adjuster is the AI-facing half of anchor-and-adjust: it asks the LLM
for per-level adjustment proposals and enforces the evidence-anchoring
contract (every proposal must cite a resolvable dimension payload key or a
verified sentiment citation). Band/ordering checks live in levels.py.
"""
from __future__ import annotations

import json
import unittest

from src.tiered_analysis.adjustments import LevelAdjuster
from src.tiered_analysis.levels import compute_base_levels
from src.tiered_analysis.providers.base import (
    Citation,
    Coverage,
    DimensionResult,
    SourceKind,
)


def _technicals():
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
        payload={"close": 100.0, "sma_20": 96.0, "rsi_14": 71.2,
                 "macd": {"histogram": -0.4}},
    )


def _sentiment(n_citations=2):
    return DimensionResult(
        dimension="sentiment",
        kind=SourceKind.TEXTUAL,
        coverage=Coverage.FULL,
        narrative="Sentiment: positive. Earnings beat [1].",
        citations=[
            Citation(source_name=f"src{i}", url=f"https://ex.com/{i}")
            for i in range(1, n_citations + 1)
        ],
    )


def _bases():
    return compute_base_levels(
        close=100.0, sma_20=96.0, sma_60=90.0, swing_low=94.0, atr=3.0
    )


def _llm_reply(adjustments):
    return json.dumps({"adjustments": adjustments})


class TestLevelAdjuster(unittest.TestCase):
    def test_valid_proposal_with_payload_evidence(self):
        reply = _llm_reply([
            {"level": "entry", "value": 97.0, "reason": "RSI hot, wait lower",
             "evidence": ["technicals.rsi_14"]},
        ])
        adjuster = LevelAdjuster(summarizer=lambda prompt: reply)
        proposals, warnings = adjuster.propose(
            "AAPL", _bases(), [_technicals(), _sentiment()]
        )
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].level, "entry")
        self.assertAlmostEqual(proposals[0].value, 97.0)
        self.assertEqual(proposals[0].evidence, ("technicals.rsi_14",))
        self.assertEqual(warnings, [])

    def test_nested_payload_evidence_resolves(self):
        reply = _llm_reply([
            {"level": "stop_loss", "value": 91.0, "reason": "momentum fading",
             "evidence": ["technicals.macd.histogram"]},
        ])
        adjuster = LevelAdjuster(summarizer=lambda prompt: reply)
        proposals, _ = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(len(proposals), 1)

    def test_citation_evidence_validated_against_citation_count(self):
        ok = _llm_reply([
            {"level": "entry", "value": 97.0, "reason": "news",
             "evidence": ["citation:2"]},
        ])
        adjuster = LevelAdjuster(summarizer=lambda prompt: ok)
        proposals, _ = adjuster.propose(
            "AAPL", _bases(), [_technicals(), _sentiment(n_citations=2)]
        )
        self.assertEqual(len(proposals), 1)

        out_of_range = _llm_reply([
            {"level": "entry", "value": 97.0, "reason": "news",
             "evidence": ["citation:7"]},
        ])
        adjuster = LevelAdjuster(summarizer=lambda prompt: out_of_range)
        proposals, warnings = adjuster.propose(
            "AAPL", _bases(), [_technicals(), _sentiment(n_citations=2)]
        )
        self.assertEqual(proposals, [])
        self.assertTrue(warnings)

    def test_unverifiable_evidence_drops_the_proposal(self):
        reply = _llm_reply([
            {"level": "entry", "value": 97.0, "reason": "trust me",
             "evidence": ["technicals.made_up_key"]},
        ])
        adjuster = LevelAdjuster(summarizer=lambda prompt: reply)
        proposals, warnings = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(proposals, [])
        self.assertTrue(any("evidence" in w.lower() for w in warnings))

    def test_missing_evidence_or_reason_drops_the_proposal(self):
        reply = _llm_reply([
            {"level": "entry", "value": 97.0, "reason": "", "evidence": []},
            {"level": "stop_loss", "value": 91.0,
             "evidence": ["technicals.rsi_14"]},
        ])
        adjuster = LevelAdjuster(summarizer=lambda prompt: reply)
        proposals, warnings = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(proposals, [])
        self.assertEqual(len(warnings), 2)

    def test_unknown_level_key_dropped_with_warning(self):
        reply = _llm_reply([
            {"level": "moon_target", "value": 200.0, "reason": "x",
             "evidence": ["technicals.rsi_14"]},
        ])
        adjuster = LevelAdjuster(summarizer=lambda prompt: reply)
        proposals, warnings = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(proposals, [])
        self.assertTrue(warnings)

    def test_empty_adjustments_list_is_a_valid_answer(self):
        adjuster = LevelAdjuster(summarizer=lambda prompt: _llm_reply([]))
        proposals, warnings = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(proposals, [])
        self.assertEqual(warnings, [])

    def test_llm_failure_is_a_warning_not_a_crash(self):
        def boom(prompt):
            raise RuntimeError("model down")

        adjuster = LevelAdjuster(summarizer=boom)
        proposals, warnings = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(proposals, [])
        self.assertTrue(any("model down" in w for w in warnings))

    def test_non_json_reply_is_a_warning_not_a_crash(self):
        adjuster = LevelAdjuster(summarizer=lambda prompt: "sorry, no idea")
        proposals, warnings = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(proposals, [])
        self.assertTrue(warnings)

    def test_fenced_json_is_accepted(self):
        reply = "```json\n" + _llm_reply([
            {"level": "entry", "value": 97.0, "reason": "r",
             "evidence": ["technicals.rsi_14"]},
        ]) + "\n```"
        adjuster = LevelAdjuster(summarizer=lambda prompt: reply)
        proposals, _ = adjuster.propose("AAPL", _bases(), [_technicals()])
        self.assertEqual(len(proposals), 1)

    def test_no_bases_skips_the_llm_entirely(self):
        calls = []

        def spy(prompt):
            calls.append(prompt)
            return _llm_reply([])

        empty = compute_base_levels(close=None)
        adjuster = LevelAdjuster(summarizer=spy)
        proposals, warnings = adjuster.propose("AAPL", empty, [_technicals()])
        self.assertEqual(proposals, [])
        self.assertEqual(calls, [])
        self.assertTrue(warnings)

    def test_prompt_contains_bases_evidence_and_rules(self):
        captured = {}

        def spy(prompt):
            captured["prompt"] = prompt
            return _llm_reply([])

        LevelAdjuster(summarizer=spy).propose(
            "AAPL", _bases(), [_technicals(), _sentiment()]
        )
        prompt = captured["prompt"]
        self.assertIn("96.0", prompt)  # base entry value
        self.assertIn("rsi_14", prompt)  # payload evidence offered
        self.assertIn("citation:", prompt)  # citation ref grammar explained
        self.assertIn("ATR", prompt)  # band rule stated


if __name__ == "__main__":
    unittest.main()
