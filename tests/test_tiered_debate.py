# -*- coding: utf-8 -*-
"""Offline tests for the tier-2 defender/attacker/judge debate (v5).

Fake-LLM tests covering: the 5-step choreography (parallel openings →
attacker review → defender reply → judge → summary), every row of the
weight ledger (1/1 correct keeps, 0/1 defender errors, 0/0 correctly
removed), the score formula final = 5 + weight × (adjusted − 5) with its
<4 / 4-6 / >6 verdict bands, leaf-only citation validation, the Pydantic
retry-once contract, and every failure rule — defender/judge failures
void the verdict (tier 2 falls back to tier 1), attacker failures degrade
loudly, and a broken summary never voids a computed verdict.

The two opening calls run in parallel threads, so the fake LLM routes
replies by prompt content, not call order.
"""
from __future__ import annotations

import json
import threading
import unittest

from src.tiered_analysis.debate import (
    DebateEngine,
    DebateResult,
    DebateVerdict,
    direction_from_final,
)
from src.tiered_analysis.llm_support import LlmUsageTracker, record_llm_usage
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
        # "macd" is a grouping on purpose: the leaf-only citation rule must
        # reject "technicals.macd" but accept "technicals.macd.signal".
        payload={"close": 100.0, "rsi_14": 71.2, "score": 68, "macd": {"signal": 1.2}},
    )


def _sentiment():
    return DimensionResult(
        dimension="sentiment",
        kind=SourceKind.TEXTUAL,
        coverage=Coverage.FULL,
        narrative="Sentiment: positive. Big deal announced [1].",
        citations=[Citation(source_name="reuters", url="https://ex.com/1")],
    )


def _dimensions():
    return [_technicals(), _sentiment()]


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


# ---------------------------------------------------------------------------
# Reply builders — the default run: 4 defender items, one attack on
# T2:logic (rejected, judge sides with the defender), one addition S3
# (accepted, judge says real). Ledger 5/5 → weight 1.0; initial 8,
# adjusted 7 → final 7.00 → buy.
# ---------------------------------------------------------------------------


def _item(item_id, dimension, direction, claim, citations):
    return {
        "id": item_id,
        "dimension": dimension,
        "direction": direction,
        "claim": claim,
        "citations": list(citations),
    }


def _check(verdict="valid", reason=None, citations=()):
    return {"verdict": verdict, "reason": reason, "citations": list(citations)}


def _checks(citation=None, logic=None):
    return {
        "citation_check": citation or _check(),
        "logic_check": logic or _check(),
    }


DEFENDER_ITEMS = [
    _item("T1", "technicals", "bullish", "RSI shows strong momentum.", ["technicals.rsi_14"]),
    _item("T2", "technicals", "bullish", "Price holds above 100.", ["technicals.close"]),
    _item("S1", "sentiment", "bullish", "A big deal was announced.", ["citation:1"]),
    _item("S2", "sentiment", "bearish", "Coverage may be one-sided.", ["citation:1"]),
]

ATTACKER_ITEMS = DEFENDER_ITEMS + [
    _item("S3", "sentiment", "bearish", "The deal is not closed yet.", ["citation:1"]),
]


def _defender_opening(items=None, initial_score=8):
    return json.dumps(
        {
            "items": items or DEFENDER_ITEMS,
            "no_data_dimensions": [],
            "initial_score": initial_score,
        }
    )


def _attacker_opening(items=None):
    return json.dumps({"items": items or ATTACKER_ITEMS, "no_data_dimensions": []})


def _review(checks=None, match_map=None):
    return json.dumps(
        {
            "match_map": match_map
            if match_map is not None
            else [
                {"own_id": "T1", "covered_by": "T1"},
                {"own_id": "T2", "covered_by": "T2"},
                {"own_id": "S1", "covered_by": "S1"},
                {"own_id": "S2", "covered_by": "S2"},
                {"own_id": "S3", "covered_by": None},
            ],
            "checks": checks
            or {
                "T1": _checks(),
                "T2": _checks(
                    logic=_check("invalid", "One price point is not a trend.", ["technicals.close"])
                ),
                "S1": _checks(),
                "S2": _checks(),
            },
        }
    )


def _reply(responses=None, adjusted_score=7):
    return json.dumps(
        {
            "responses": responses
            if responses is not None
            else {
                "T2:logic": _checks(
                    logic=_check(
                        "invalid",
                        "The claim was about the level, not the trend.",
                        ["technicals.close"],
                    )
                ),
                "add:S3": _checks(),
            },
            "adjusted_score": adjusted_score,
        }
    )


def _judge(reason_checks=None, attack_rulings=None, addition_rulings=None):
    return json.dumps(
        {
            "reason_checks": reason_checks
            or {"T1": _checks(), "T2": _checks(), "S1": _checks(), "S2": _checks()},
            "attack_rulings": attack_rulings
            if attack_rulings is not None
            else {
                "T2:logic": {
                    "verdict": "attack_wrong",
                    "reason": "The item claimed a level, which the data shows.",
                    "citations": ["technicals.close"],
                }
            },
            "addition_rulings": addition_rulings
            if addition_rulings is not None
            else {"S3": {"verdict": "real", "reason": "Genuinely missed.", "citations": []}},
        }
    )


def _summary():
    return json.dumps({"summary": "The defense held up and the case leans bullish."})


def _replies(**overrides):
    replies = {
        "defender_opening": _defender_opening(),
        "attacker_opening": _attacker_opening(),
        "review": _review(),
        "review_checks_only": _review(match_map=[]),
        "reply": _reply(),
        "judge": _judge(),
        "summary": _summary(),
    }
    replies.update(overrides)
    return replies


# Marker → stage, checked in order — the specific markers (reply,
# checks-only review) must match before the generic role openers.
MARKERS = [
    ("The attacker has challenged your evidence", "reply"),
    ("independent list is unavailable", "review_checks_only"),
    ("Compare the two evidence lists", "review"),
    ("You are the DEFENDER analyst", "defender_opening"),
    ("You are the ATTACKER analyst, working alone", "attacker_opening"),
    ("You are the JUDGE with the final say", "judge"),
    ("Write the user-facing report", "summary"),
]

RETRY_MARKER = "Your previous reply was invalid"


def stage_of(prompt):
    for marker, stage in MARKERS:
        if marker in prompt:
            return stage
    raise AssertionError(f"prompt matches no stage: {prompt[:120]}")


class RoutedSummarizer:
    """Routes replies by prompt content; thread-safe (openings run in
    parallel). ``retry_replies`` serve the second attempt of a stage."""

    def __init__(self, replies, retry_replies=None):
        self.replies = replies
        self.retry_replies = retry_replies or {}
        self.prompts = []
        self._lock = threading.Lock()

    def __call__(self, prompt):
        with self._lock:
            self.prompts.append(prompt)
        stage = stage_of(prompt)
        if RETRY_MARKER in prompt and stage in self.retry_replies:
            return self.retry_replies[stage]
        reply = self.replies[stage]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def stages(self):
        return [stage_of(p) for p in self.prompts]


def _run(replies=None, retry_replies=None, dimensions=None):
    fake = RoutedSummarizer(replies or _replies(), retry_replies)
    engine = DebateEngine(summarizer=fake)
    dims = dimensions or _dimensions()
    result = engine.run("AAPL", _tier1(dimensions=dims), dims)
    return result, fake


def _item_by_id(result, item_id):
    return next(i for i in result.items if i["id"] == item_id)


# ---------------------------------------------------------------------------


class DirectionBandsTest(unittest.TestCase):
    def test_owner_spec_bands_on_the_two_decimal_score(self):
        self.assertEqual(direction_from_final(0.0), Direction.SELL)
        self.assertEqual(direction_from_final(3.99), Direction.SELL)
        self.assertEqual(direction_from_final(4.0), Direction.HOLD)
        self.assertEqual(direction_from_final(5.0), Direction.HOLD)
        self.assertEqual(direction_from_final(6.0), Direction.HOLD)
        self.assertEqual(direction_from_final(6.01), Direction.BUY)
        self.assertEqual(direction_from_final(10.0), Direction.BUY)


class ChoreographyTest(unittest.TestCase):
    def test_full_run_six_calls_and_the_computed_verdict(self):
        result, fake = _run()
        self.assertEqual(
            sorted(fake.stages()),
            sorted(
                ["defender_opening", "attacker_opening", "review", "reply", "judge", "summary"]
            ),
        )
        verdict = result.verdict
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict.initial_score, 8)
        self.assertEqual(verdict.adjusted_score, 7)
        self.assertFalse(verdict.adjusted_kept)
        self.assertEqual((verdict.weight_numerator, verdict.weight_denominator), (5, 5))
        self.assertEqual(verdict.weight, 1.0)
        # final = 5 + 1.0 × (7 − 5) = 7.00 → buy
        self.assertEqual(verdict.final_score, 7.0)
        self.assertEqual(verdict.direction, Direction.BUY)
        self.assertEqual(verdict.summary, "The defense held up and the case leans bullish.")

    def test_the_openings_run_before_everything_else(self):
        _, fake = _run()
        stages = fake.stages()
        self.assertEqual(sorted(stages[:2]), ["attacker_opening", "defender_opening"])
        self.assertEqual(stages[2:], ["review", "reply", "judge", "summary"])

    def test_the_addition_joins_the_tree_renumbered_and_tagged(self):
        result, _ = _run()
        addition = _item_by_id(result, "S3")
        self.assertTrue(addition["added_by_attacker"])
        self.assertEqual(addition["dimension"], "sentiment")
        self.assertEqual(addition["claim"], "The deal is not closed yet.")
        self.assertTrue(addition["response"]["accepted"])
        self.assertEqual(addition["judge"]["verdict"], "real")
        self.assertEqual(addition["outcome"], "valid")

    def test_defended_attack_is_recorded_on_the_item(self):
        result, _ = _run()
        item = _item_by_id(result, "T2")
        self.assertEqual(item["attacker_checks"]["logic"]["verdict"], "invalid")
        self.assertFalse(item["responses"]["logic"]["accepted"])
        self.assertEqual(item["judge"]["logic"]["kind"], "attack_ruling")
        self.assertEqual(item["judge"]["logic"]["verdict"], "attack_wrong")
        self.assertEqual(item["judge"]["citation"]["kind"], "reason_check")
        self.assertEqual(item["outcome"], "valid")


class WeightLedgerTest(unittest.TestCase):
    """Every row of the agreed table, one scenario each."""

    def test_unattacked_reason_judged_invalid_costs_0_1(self):
        reason_checks = {
            "T1": _checks(logic=_check("invalid", "Does not follow.")),
            "T2": _checks(),
            "S1": _checks(),
            "S2": _checks(),
        }
        result, _ = _run(_replies(judge=_judge(reason_checks=reason_checks)))
        self.assertEqual(_item_by_id(result, "T1")["outcome"], "invalid")
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 5)
        )
        # weight 0.8, adjusted 7 → final 5 + 0.8×2 = 6.6 → buy
        self.assertEqual(result.verdict.final_score, 6.6)
        self.assertEqual(result.verdict.direction, Direction.BUY)

    def test_rejected_attack_the_judge_upholds_costs_0_1(self):
        attack_rulings = {
            "T2:logic": {"verdict": "attack_right", "reason": "The attack is correct.", "citations": []}
        }
        result, _ = _run(_replies(judge=_judge(attack_rulings=attack_rulings)))
        self.assertEqual(_item_by_id(result, "T2")["outcome"], "invalid")
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 5)
        )

    def test_correctly_conceded_attack_drops_the_reason_from_the_count(self):
        responses = {
            "T2:logic": _checks(),  # both checks valid → accepted (conceded)
            "add:S3": _checks(),
        }
        attack_rulings = {
            "T2:logic": {"verdict": "attack_right", "reason": "The attack is correct.", "citations": []}
        }
        result, _ = _run(
            _replies(reply=_reply(responses=responses), judge=_judge(attack_rulings=attack_rulings))
        )
        item = _item_by_id(result, "T2")
        self.assertEqual(item["outcome"], "neutral")
        self.assertEqual(item["count"], {"numerator": 0, "denominator": 0})
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 4)
        )
        self.assertEqual(result.verdict.weight, 1.0)

    def test_accepting_a_flawed_attack_costs_0_1_and_flags(self):
        responses = {
            "T2:logic": _checks(),  # accepted…
            "add:S3": _checks(),
        }
        # …but the judge (default reply) rules the attack wrong.
        result, _ = _run(_replies(reply=_reply(responses=responses)))
        self.assertEqual(_item_by_id(result, "T2")["outcome"], "invalid")
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 5)
        )
        self.assertTrue(
            any(
                "defender accepted an attack the judge ruled wrong" in w
                for w in result.warnings
            )
        )

    def test_adopted_bogus_addition_costs_0_1(self):
        addition_rulings = {"S3": {"verdict": "bogus", "reason": "Duplicated.", "citations": []}}
        result, _ = _run(_replies(judge=_judge(addition_rulings=addition_rulings)))
        self.assertEqual(_item_by_id(result, "S3")["outcome"], "invalid")
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 5)
        )

    def test_wrongly_rejected_real_addition_costs_0_1(self):
        responses = {
            "T2:logic": _checks(
                logic=_check("invalid", "The claim was about the level.", ["technicals.close"])
            ),
            "add:S3": _checks(logic=_check("invalid", "Not relevant.")),  # rejected…
        }
        # …but the judge (default reply) says the addition is real.
        result, _ = _run(_replies(reply=_reply(responses=responses)))
        self.assertEqual(_item_by_id(result, "S3")["outcome"], "invalid")
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 5)
        )

    def test_correctly_rejected_bogus_addition_is_excluded(self):
        responses = {
            "T2:logic": _checks(
                logic=_check("invalid", "The claim was about the level.", ["technicals.close"])
            ),
            "add:S3": _checks(logic=_check("invalid", "Invented.")),
        }
        addition_rulings = {"S3": {"verdict": "bogus", "reason": "Invented.", "citations": []}}
        result, _ = _run(
            _replies(
                reply=_reply(responses=responses),
                judge=_judge(addition_rulings=addition_rulings),
            )
        )
        item = _item_by_id(result, "S3")
        self.assertEqual(item["outcome"], "neutral")
        self.assertEqual(item["count"], {"numerator": 0, "denominator": 0})
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 4)
        )

    def test_empty_ledger_defaults_to_neutral_five(self):
        # Every defender item attacked and correctly conceded; the addition
        # correctly rejected as bogus → denominator 0 → final 5.00 hold.
        checks = {
            "T1": _checks(logic=_check("invalid", "Flawed.")),
            "T2": _checks(logic=_check("invalid", "Flawed.")),
            "S1": _checks(logic=_check("invalid", "Flawed.")),
            "S2": _checks(logic=_check("invalid", "Flawed.")),
        }
        responses = {
            "T1:logic": _checks(),
            "T2:logic": _checks(),
            "S1:logic": _checks(),
            "S2:logic": _checks(),
            "add:S3": _checks(logic=_check("invalid", "Invented.")),
        }
        attack_rulings = {
            key: {"verdict": "attack_right", "reason": "Correct.", "citations": []}
            for key in ("T1:logic", "T2:logic", "S1:logic", "S2:logic")
        }
        addition_rulings = {"S3": {"verdict": "bogus", "reason": "Invented.", "citations": []}}
        result, _ = _run(
            _replies(
                review=_review(checks=checks),
                reply=_reply(responses=responses, adjusted_score=3),
                judge=_judge(attack_rulings=attack_rulings, addition_rulings=addition_rulings),
            )
        )
        verdict = result.verdict
        self.assertEqual((verdict.weight_numerator, verdict.weight_denominator), (0, 0))
        self.assertEqual(verdict.weight, 0.0)
        self.assertEqual(verdict.final_score, 5.0)
        self.assertEqual(verdict.direction, Direction.HOLD)
        self.assertTrue(any("no surviving evidence to weigh" in w for w in result.warnings))

    def test_thin_base_is_flagged_when_most_initial_evidence_dies(self):
        # 3 of 4 defender reasons judged invalid → survivors 1 < half.
        reason_checks = {
            "T1": _checks(logic=_check("invalid", "Flawed.")),
            "T2": _checks(),
            "S1": _checks(logic=_check("invalid", "Flawed.")),
            "S2": _checks(logic=_check("invalid", "Flawed.")),
        }
        attack_rulings = {
            "T2:logic": {"verdict": "attack_right", "reason": "Correct.", "citations": []}
        }
        result, _ = _run(
            _replies(judge=_judge(reason_checks=reason_checks, attack_rulings=attack_rulings))
        )
        self.assertTrue(
            any("the weight rests on a thin base" in w for w in result.warnings)
        )

    def test_the_worked_example_from_the_design_doc(self):
        # Flip side of the doc's appendix: the defender concedes S1's attack
        # but the judge rules that attack wrong → 0/1 + flag; the other 3
        # reasons and the addition hold → weight 4/5; adjusted 7 →
        # final = 5 + 0.8 × 2 = 6.6.
        checks = {
            "T1": _checks(),
            "T2": _checks(),
            "S1": _checks(citation=_check("invalid", "Miscited.", ["citation:1"])),
            "S2": _checks(),
        }
        responses = {"S1:citation": _checks(), "add:S3": _checks()}
        attack_rulings = {
            "S1:citation": {"verdict": "attack_wrong", "reason": "The citation is fine.", "citations": []}
        }
        result, _ = _run(
            _replies(
                review=_review(checks=checks),
                reply=_reply(responses=responses),
                judge=_judge(attack_rulings=attack_rulings),
            )
        )
        verdict = result.verdict
        self.assertEqual((verdict.weight_numerator, verdict.weight_denominator), (4, 5))
        self.assertEqual(verdict.weight, 0.8)
        self.assertEqual(verdict.final_score, 6.6)


class ScoreHandlingTest(unittest.TestCase):
    def test_keep_resolves_to_the_initial_score(self):
        result, _ = _run(_replies(reply=_reply(adjusted_score="keep")))
        self.assertEqual(result.verdict.adjusted_score, 8)
        self.assertTrue(result.verdict.adjusted_kept)
        # weight 1.0, adjusted 8 → final 8.00 → buy
        self.assertEqual(result.verdict.final_score, 8.0)

    def test_no_challenges_skips_the_defender_reply(self):
        # Full coverage, no attacks, no additions → 5 calls, score kept.
        match_map = [
            {"own_id": item["id"], "covered_by": item["id"]} for item in DEFENDER_ITEMS
        ]
        result, fake = _run(
            _replies(
                attacker_opening=_attacker_opening(items=DEFENDER_ITEMS),
                review=_review(
                    checks={i["id"]: _checks() for i in DEFENDER_ITEMS},
                    match_map=match_map,
                ),
                judge=_judge(attack_rulings={}, addition_rulings={}),
            )
        )
        self.assertNotIn("reply", fake.stages())
        self.assertEqual(len(fake.prompts), 5)
        self.assertTrue(result.verdict.adjusted_kept)
        self.assertEqual(result.verdict.adjusted_score, 8)
        self.assertTrue(any("defender response skipped" in w for w in result.warnings))

    def test_non_whole_adjusted_score_voids_after_retry(self):
        result, _ = _run(_replies(reply=_reply(adjusted_score=7.5)))
        self.assertIsNone(result.verdict)
        self.assertTrue(
            any("defender reply invalid after retry" in w for w in result.warnings)
        )
        # The partial tree survives for the UI.
        self.assertEqual(len(result.items), 5)


class CitationRulesTest(unittest.TestCase):
    def test_group_path_citations_are_stripped_leaves_kept(self):
        items = [
            _item("T1", "technicals", "bullish", "MACD crossed up.",
                  ["technicals.macd", "technicals.macd.signal"]),
            _item("T2", "technicals", "bullish", "Price holds above 100.",
                  ["technicals.close"]),
            _item("S1", "sentiment", "bullish", "A big deal was announced.", ["citation:1"]),
            _item("S2", "sentiment", "bearish", "Coverage may be one-sided.", ["citation:1"]),
        ]
        result, _ = _run(_replies(defender_opening=_defender_opening(items=items)))
        t1 = _item_by_id(result, "T1")
        self.assertEqual(t1["citations"], ["technicals.macd.signal"])
        self.assertTrue(
            any("does not resolve to a single value" in w for w in result.warnings)
        )

    def test_out_of_range_sentiment_citations_are_stripped(self):
        items = [dict(DEFENDER_ITEMS[0]), dict(DEFENDER_ITEMS[1]),
                 _item("S1", "sentiment", "bullish", "A big deal was announced.",
                       ["citation:1", "citation:9"]),
                 dict(DEFENDER_ITEMS[3])]
        result, _ = _run(_replies(defender_opening=_defender_opening(items=items)))
        self.assertEqual(_item_by_id(result, "S1")["citations"], ["citation:1"])


class RetryContractTest(unittest.TestCase):
    def test_an_invalid_first_reply_is_retried_with_the_errors_shown(self):
        # First defender opening breaks the per-dimension floor (one lonely
        # technicals item); the retry is valid and the run completes.
        bad = _defender_opening(
            items=[DEFENDER_ITEMS[0], DEFENDER_ITEMS[2], DEFENDER_ITEMS[3]]
        )
        result, fake = _run(
            _replies(defender_opening=bad),
            retry_replies={"defender_opening": _defender_opening()},
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("defender opening needed a retry" in w for w in result.warnings)
        )
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the DEFENDER analyst" in p
        )
        self.assertIn("only 1 item(s)", retry_prompt)

    def test_items_in_a_dimension_without_data_are_rejected(self):
        items = DEFENDER_ITEMS + [
            _item("F1", "fundamentals", "bullish", "Margins are widening.",
                  ["technicals.close"]),
            _item("F2", "fundamentals", "bullish", "Revenue grew.",
                  ["technicals.close"]),
        ]
        bad = _defender_opening(items=items)
        result, fake = _run(
            _replies(defender_opening=bad),
            retry_replies={"defender_opening": _defender_opening()},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the DEFENDER analyst" in p
        )
        self.assertIn("no collected data", retry_prompt)

    def test_a_match_map_pointing_at_unknown_ids_is_rejected(self):
        bad_map = [
            {"own_id": "T1", "covered_by": "T9"},
            {"own_id": "T2", "covered_by": "T2"},
            {"own_id": "S1", "covered_by": "S1"},
            {"own_id": "S2", "covered_by": "S2"},
            {"own_id": "S3", "covered_by": None},
        ]
        result, fake = _run(
            _replies(review=_review(match_map=bad_map)),
            retry_replies={"review": _review()},
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(any("attacker review needed a retry" in w for w in result.warnings))


class FailureRulesTest(unittest.TestCase):
    def test_defender_opening_invalid_twice_voids(self):
        result, _ = _run(_replies(defender_opening="not json"))
        self.assertIsNone(result.verdict)
        self.assertEqual(result.items, [])
        self.assertTrue(
            any("defender opening invalid after retry — tier-2 verdict voided" in w
                for w in result.warnings)
        )

    def test_attacker_opening_invalid_twice_degrades_to_checks_only(self):
        # Without the independent list there is no addition, so the reply
        # and judge fixtures must not mention S3.
        responses = {
            "T2:logic": _checks(
                logic=_check("invalid", "The claim was about the level.", ["technicals.close"])
            )
        }
        result, fake = _run(
            _replies(
                attacker_opening="not json",
                reply=_reply(responses=responses),
                judge=_judge(addition_rulings={}),
            )
        )
        self.assertIsNotNone(result.verdict)
        self.assertIn("review_checks_only", fake.stages())
        self.assertTrue(
            any("attacker opening invalid after retry — proceeding without additions" in w
                for w in result.warnings)
        )
        # No additions can exist without the independent list.
        self.assertEqual(len(result.items), 4)

    def test_attacker_review_invalid_twice_degrades_to_no_challenges(self):
        # With no review there are no attacks and no additions, so the
        # judge fixture must carry only its own reason checks.
        result, fake = _run(
            _replies(
                review="not json",
                judge=_judge(attack_rulings={}, addition_rulings={}),
            )
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("attacker review invalid after retry" in w for w in result.warnings)
        )
        # No challenges → the reply stage is skipped; the judge still
        # reviews every reason on its own.
        self.assertNotIn("reply", fake.stages())
        self.assertEqual(
            (result.verdict.weight_numerator, result.verdict.weight_denominator), (4, 4)
        )

    def test_judge_invalid_twice_voids_but_keeps_the_tree(self):
        result, _ = _run(_replies(judge="not json"))
        self.assertIsNone(result.verdict)
        self.assertEqual(len(result.items), 5)
        self.assertTrue(
            any("judge rulings invalid after retry — tier-2 verdict voided" in w
                for w in result.warnings)
        )

    def test_broken_summary_never_voids_a_computed_verdict(self):
        result, _ = _run(_replies(summary="not json"))
        self.assertIsNotNone(result.verdict)
        self.assertEqual(result.verdict.summary, "")
        self.assertTrue(
            any("judge summary unparseable — computed verdict stands" in w
                for w in result.warnings)
        )

    def test_summary_llm_failure_never_voids_a_computed_verdict(self):
        result, _ = _run(_replies(summary=RuntimeError("llm down")))
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("summary LLM call failed" in w and "computed verdict stands" in w
                for w in result.warnings)
        )

    def test_llm_failure_mid_debate_keeps_the_partial_tree(self):
        result, _ = _run(_replies(review=RuntimeError("llm down")))
        self.assertIsNone(result.verdict)
        self.assertEqual(len(result.items), 4)  # the defender's list survives
        self.assertTrue(any("debate LLM call failed" in w for w in result.warnings))


class UsageTrackingTest(unittest.TestCase):
    def test_parallel_opening_calls_report_into_the_active_tracker(self):
        routed = RoutedSummarizer(_replies())

        def fake(prompt):
            record_llm_usage(10, 5)
            return routed(prompt)

        engine = DebateEngine(summarizer=fake)
        tracker = LlmUsageTracker()
        dims = _dimensions()
        with tracker.activate():
            with tracker.stage("tier2_debate"):
                result = engine.run("AAPL", _tier1(dimensions=dims), dims)
        self.assertIsNotNone(result.verdict)
        detail = tracker.to_detail()
        self.assertEqual(detail["stages"]["tier2_debate"]["calls"], 6)
        self.assertEqual(detail["stages"]["tier2_debate"]["prompt_tokens"], 60)


class PromptContentTest(unittest.TestCase):
    def test_opening_prompts_carry_evidence_and_the_rules(self):
        _, fake = _run()
        defender = next(p for p in fake.prompts if "You are the DEFENDER analyst" in p)
        self.assertIn("rsi_14", defender)
        self.assertIn("2 to 4", defender)
        self.assertIn("no_data_dimensions", defender)
        attacker = next(
            p for p in fake.prompts if "You are the ATTACKER analyst, working alone" in p
        )
        self.assertIn("you have NOT seen it", attacker)
        self.assertNotIn("initial_score", attacker)

    def test_review_prompt_shows_both_lists_and_the_required_ids(self):
        _, fake = _run()
        review = next(p for p in fake.prompts if "Compare the two evidence lists" in p)
        self.assertIn("The deal is not closed yet.", review)  # own list
        self.assertIn("RSI shows strong momentum.", review)  # defender list
        self.assertIn("T1, T2, S1, S2", review)

    def test_reply_prompt_lists_every_challenge_with_its_key(self):
        _, fake = _run()
        reply = next(
            p for p in fake.prompts if "The attacker has challenged your evidence" in p
        )
        self.assertIn('"T2:logic"', reply)
        self.assertIn('"add:S3"', reply)
        self.assertIn("you MISSED this", reply)
        self.assertIn('"keep"', reply)

    def test_judge_prompt_carries_the_tree_and_the_ruling_keys(self):
        _, fake = _run()
        judge = next(p for p in fake.prompts if "You are the JUDGE with the final say" in p)
        self.assertIn("added by the ATTACKER", judge)
        self.assertIn("attacker logic check (T2:logic)", judge)
        self.assertIn("defender response: REJECTED", judge)
        self.assertIn('"attack_rulings" must cover exactly: T2:logic', judge)
        self.assertIn('"addition_rulings" must cover exactly: S3', judge)

    def test_summary_prompt_carries_the_computed_numbers(self):
        _, fake = _run()
        summary = next(p for p in fake.prompts if "Write the user-facing report" in p)
        self.assertIn("weight = 5/5", summary)
        self.assertIn("final = 5 + weight × (adjusted − 5) = 7.00", summary)
        self.assertIn("verdict: buy", summary)


class DetailShapeTest(unittest.TestCase):
    def test_to_detail_is_json_ready_with_the_v5_marker_and_legacy_keys(self):
        result, _ = _run()
        detail = result.to_detail()
        json.dumps(detail)  # must not raise
        self.assertEqual(detail["format"], 5)
        self.assertEqual(detail["turns"], [])
        self.assertEqual(len(detail["items"]), 5)
        verdict = detail["verdict"]
        self.assertEqual(verdict["direction"], "buy")
        self.assertEqual(verdict["final_score"], 7.0)
        self.assertEqual(verdict["initial_score"], 8)
        self.assertEqual(verdict["adjusted_score"], 7)
        self.assertFalse(verdict["adjusted_kept"])
        self.assertEqual(
            verdict["weight"], {"numerator": 5, "denominator": 5, "value": 1.0}
        )
        # Legacy keys pre-v5 readers touch must exist and be inert.
        self.assertIsNone(verdict["confidence"])
        self.assertIsNone(verdict["scoring"])
        self.assertEqual(verdict["reasons_for"], [])
        self.assertEqual(verdict["reasons_against"], [])

    def test_voided_run_still_serializes_its_partial_tree(self):
        result, _ = _run(_replies(judge="not json"))
        detail = result.to_detail()
        json.dumps(detail)
        self.assertIsNone(detail["verdict"])
        self.assertEqual(len(detail["items"]), 5)


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
            items=[],
            verdict=DebateVerdict(
                direction=direction,
                final_score=6.0,
                summary="ruling",
                initial_score=7,
                adjusted_score=6,
                adjusted_kept=False,
                weight_numerator=3,
                weight_denominator=3,
                weight=1.0,
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
        self.assertEqual(report.debate_detail["format"], 5)

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
