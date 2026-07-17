# -*- coding: utf-8 -*-
"""Offline tests for the tier-2 defender/attacker/judge debate (v6).

Fake-LLM tests covering: the 5-step choreography (parallel openings →
attacker review → defender reply → judge → summary), the deterministic
pool scores (per dimension 10 × bullish/total, averaged; three snapshots
initial/adjusted/final), final-pool membership (judge + code value check;
defender stance irrelevant — resurrection included), mechanical link
verification ({text, ref, value} with value-mismatch auto-fail), dynamic
per-dimension ceilings, the Pydantic retry-once contract, and every
failure rule — defender/judge failures void the verdict (tier 2 falls
back to tier 1), attacker failures degrade loudly, and a broken summary
never voids a computed verdict.

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
    max_items_per_dimension,
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
        # "macd" is a grouping on purpose: the leaf-only link rule must
        # reject "technicals.macd" but accept "technicals.macd.signal".
        # Leaf count = 4 (close, rsi_14, score, macd.signal).
        payload={"close": 100.0, "rsi_14": 71.2, "score": 68, "macd": {"signal": 1.2}},
    )


def _sentiment():
    return DimensionResult(
        dimension="sentiment",
        kind=SourceKind.TEXTUAL,
        coverage=Coverage.FULL,
        narrative="Sentiment: positive. Big deal announced [1]. Doubts remain [2].",
        citations=[
            Citation(source_name="reuters", url="https://ex.com/1"),
            Citation(source_name="bloomberg", url="https://ex.com/2"),
        ],
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
# Reply builders — the default run: 4 defender items (T bullish ×2,
# S bullish + bearish), one attack on T2:logic (rejected, judge sides with
# the defender), one bearish addition S3 (accepted, judge checks pass).
#
# Scores (per dimension 10 × bullish/total, averaged):
#   initial  = (tech 10 + sent 5) / 2      = 7.50
#   adjusted = (tech 10 + sent 10/3) / 2   = 6.67   (S3 joins the pool)
#   final    = same pool                    = 6.67 → buy
# ---------------------------------------------------------------------------


def _link(text, ref, value=None):
    return {"text": text, "ref": ref, "value": value}


def _item(item_id, dimension, direction, claim, links):
    return {
        "id": item_id,
        "dimension": dimension,
        "direction": direction,
        "claim": claim,
        "links": links,
    }


def _check(verdict="valid", reason=None, citations=()):
    return {"verdict": verdict, "reason": reason, "citations": list(citations)}


def _checks(citation=None, logic=None):
    return {
        "citation_check": citation or _check(),
        "logic_check": logic or _check(),
    }


DEFENDER_ITEMS = [
    _item("T1", "technicals", "bullish",
          "The 14-day RSI (71.2) is above 70, showing strong momentum.",
          [_link("14-day RSI", "technicals.rsi_14", 71.2)]),
    _item("T2", "technicals", "bullish",
          "The closing price (100.0) holds above the 95 support.",
          [_link("closing price", "technicals.close", 100.0)]),
    _item("S1", "sentiment", "bullish",
          "A big deal was announced.",
          [_link("big deal", "citation:1")]),
    _item("S2", "sentiment", "bearish",
          "Doubts remain about the coverage.",
          [_link("Doubts remain", "citation:2")]),
]

ATTACKER_ITEMS = DEFENDER_ITEMS + [
    _item("S3", "sentiment", "bearish",
          "The deal is not closed yet.",
          [_link("deal", "citation:2")]),
]


def _defender_opening(items=None):
    return json.dumps(
        {"items": items or DEFENDER_ITEMS, "no_data_dimensions": []}
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
                    logic=_check("invalid", "One price point is not support.", ["technicals.close"])
                ),
                "S1": _checks(),
                "S2": _checks(),
            },
        }
    )


def _reply(responses=None):
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
        }
    )


def _judge(reason_checks=None, attack_rulings=None):
    return json.dumps(
        {
            "reason_checks": reason_checks
            or {
                "T1": _checks(),
                "T2": _checks(),
                "S1": _checks(),
                "S2": _checks(),
                "S3": _checks(),
            },
            "attack_rulings": attack_rulings
            if attack_rulings is not None
            else {
                "T2:logic": {
                    "verdict": "attack_wrong",
                    "reason": "The item claimed a level, which the data shows.",
                    "citations": ["technicals.close"],
                }
            },
        }
    )


def _summary():
    return json.dumps({"summary": "The surviving evidence leans bullish."})


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


class CeilingsTest(unittest.TestCase):
    def test_ceiling_is_the_leaf_count_of_the_report(self):
        ceilings = max_items_per_dimension(_dimensions())
        # close, rsi_14, score, macd.signal — the macd grouping is not a leaf.
        self.assertEqual(ceilings["technicals"], 4)

    def test_sentiment_ceiling_is_sources_times_two(self):
        ceilings = max_items_per_dimension(_dimensions())
        self.assertEqual(ceilings["sentiment"], 4)

    def test_ceiling_never_drops_below_the_floor(self):
        dims = [
            DimensionResult(
                dimension="technicals",
                kind=SourceKind.NUMERIC,
                coverage=Coverage.FULL,
                payload={"close": 100.0},
            )
        ]
        self.assertEqual(max_items_per_dimension(dims)["technicals"], 2)

    def test_too_many_items_for_the_ceiling_is_rejected(self):
        # 5 technicals items against a ceiling of 4 → retry with the error.
        extra = _item("T5", "technicals", "bullish",
                      "The technical score (68) is high.",
                      [_link("technical score", "technicals.score", 68)])
        many = [
            DEFENDER_ITEMS[0], DEFENDER_ITEMS[1],
            _item("T3", "technicals", "bullish",
                  "The technical score (68) is high.",
                  [_link("technical score", "technicals.score", 68)]),
            _item("T4", "technicals", "bullish",
                  "The MACD signal (1.2) is positive.",
                  [_link("MACD signal", "technicals.macd.signal", 1.2)]),
            extra, DEFENDER_ITEMS[2], DEFENDER_ITEMS[3],
        ]
        result, fake = _run(
            _replies(defender_opening=_defender_opening(items=many)),
            retry_replies={"defender_opening": _defender_opening()},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the DEFENDER analyst" in p
        )
        self.assertIn("the maximum is 4", retry_prompt)


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
        # initial: tech 10.0, sentiment 5.0 → 7.5
        self.assertEqual(verdict.initial_score, 7.5)
        # adjusted/final: S3 (bearish) joins → sentiment 10/3 → (10+3.33)/2
        self.assertEqual(verdict.adjusted_score, 6.67)
        self.assertEqual(verdict.final_score, 6.67)
        self.assertEqual(verdict.direction, Direction.BUY)
        self.assertEqual(verdict.summary, "The surviving evidence leans bullish.")
        self.assertEqual(verdict.pools["initial"]["dimensions"]["technicals"]["score"], 10.0)
        self.assertEqual(verdict.pools["initial"]["dimensions"]["sentiment"]["score"], 5.0)
        self.assertEqual(verdict.pools["final"]["bullish"], 3)
        self.assertEqual(verdict.pools["final"]["bearish"], 2)

    def test_the_openings_run_before_everything_else(self):
        _, fake = _run()
        stages = fake.stages()
        self.assertEqual(sorted(stages[:2]), ["attacker_opening", "defender_opening"])
        self.assertEqual(stages[2:], ["review", "reply", "judge", "summary"])

    def test_the_addition_joins_the_tree_renumbered_and_counted(self):
        result, _ = _run()
        addition = _item_by_id(result, "S3")
        self.assertTrue(addition["added_by_attacker"])
        self.assertEqual(addition["dimension"], "sentiment")
        self.assertTrue(addition["response"]["accepted"])
        self.assertEqual(addition["judge"]["citation"]["kind"], "reason_check")
        self.assertEqual(addition["judge"]["citation"]["verdict"], "valid")
        self.assertEqual(addition["final_status"], "counted")

    def test_defended_attack_is_recorded_on_the_item(self):
        result, _ = _run()
        item = _item_by_id(result, "T2")
        self.assertEqual(item["attacker_checks"]["logic"]["verdict"], "invalid")
        self.assertFalse(item["responses"]["logic"]["accepted"])
        self.assertEqual(item["judge"]["logic"]["kind"], "attack_ruling")
        self.assertEqual(item["judge"]["logic"]["verdict"], "attack_wrong")
        self.assertEqual(item["judge"]["citation"]["kind"], "reason_check")
        self.assertEqual(item["final_status"], "counted")

    def test_macro_econ_items_use_the_e_prefix(self):
        macro = DimensionResult(
            dimension="macro_econ",
            kind=SourceKind.NUMERIC,
            coverage=Coverage.FULL,
            payload={"unemployment_pct": 4.2, "cpi_yoy_pct": 3.4},
        )
        dims = [_technicals(), macro, _sentiment()]
        e_items = [
            _item("E1", "macro_econ", "bullish",
                  "Unemployment (4.2%) is low.",
                  [_link("Unemployment", "macro_econ.unemployment_pct", 4.2)]),
            _item("E2", "macro_econ", "bearish",
                  "CPI inflation (3.4%) is above target.",
                  [_link("CPI inflation", "macro_econ.cpi_yoy_pct", 3.4)]),
        ]
        items = DEFENDER_ITEMS + e_items
        match_map = [
            {"own_id": i["id"], "covered_by": i["id"]} for i in items
        ]
        checks = {i["id"]: _checks() for i in items}
        reason_checks = {i["id"]: _checks() for i in items}
        result, _ = _run(
            _replies(
                defender_opening=_defender_opening(items=items),
                attacker_opening=_attacker_opening(items=items),
                review=_review(checks=checks, match_map=match_map),
                judge=_judge(reason_checks=reason_checks, attack_rulings={}),
            ),
            dimensions=dims,
        )
        self.assertIsNotNone(result.verdict)
        self.assertEqual(_item_by_id(result, "E1")["dimension"], "macro_econ")
        # macro pool: 1 bullish of 2 → 5.0
        self.assertEqual(
            result.verdict.pools["initial"]["dimensions"]["macro_econ"]["score"], 5.0
        )


class FinalPoolTest(unittest.TestCase):
    """Membership: judge + code decide; the defender's stance never does."""

    def test_unattacked_item_judged_invalid_is_excluded(self):
        reason_checks = {
            "T1": _checks(logic=_check("invalid", "Does not follow.")),
            "T2": _checks(),
            "S1": _checks(),
            "S2": _checks(),
            "S3": _checks(),
        }
        result, _ = _run(_replies(judge=_judge(reason_checks=reason_checks)))
        item = _item_by_id(result, "T1")
        self.assertEqual(item["final_status"], "excluded")
        self.assertEqual(item["exclusion_reason"], "judge_invalid")
        # final pool: tech = T2 only (10.0), sentiment 10/3 → 6.67 buy
        self.assertEqual(result.verdict.final_score, 6.67)

    def test_upheld_attack_excludes_the_item(self):
        attack_rulings = {
            "T2:logic": {"verdict": "attack_right", "reason": "The attack is correct.", "citations": []}
        }
        result, _ = _run(_replies(judge=_judge(attack_rulings=attack_rulings)))
        item = _item_by_id(result, "T2")
        self.assertEqual(item["final_status"], "excluded")
        self.assertEqual(item["exclusion_reason"], "attack_upheld")

    def test_wrongly_conceded_item_is_restored_and_flagged(self):
        responses = {
            "T2:logic": _checks(),  # both checks valid → conceded…
            "add:S3": _checks(),
        }
        # …but the judge (default) rules the attack wrong → restored.
        result, _ = _run(_replies(reply=_reply(responses=responses)))
        item = _item_by_id(result, "T2")
        self.assertEqual(item["final_status"], "counted")
        self.assertTrue(
            any("evidence restored to the final pool" in w for w in result.warnings)
        )
        # The concession still shows in the adjusted pool (T2 out of it).
        self.assertEqual(result.verdict.pools["adjusted"]["total"], 4)
        self.assertEqual(result.verdict.pools["final"]["total"], 5)

    def test_wrongly_rejected_addition_is_included_and_flagged(self):
        responses = {
            "T2:logic": _checks(
                logic=_check("invalid", "The claim was about the level.", ["technicals.close"])
            ),
            "add:S3": _checks(logic=_check("invalid", "Not relevant.")),
        }
        # Judge (default) says S3's checks pass → included anyway.
        result, _ = _run(_replies(reply=_reply(responses=responses)))
        item = _item_by_id(result, "S3")
        self.assertEqual(item["final_status"], "counted")
        self.assertTrue(
            any("included in the final pool" in w for w in result.warnings)
        )
        # The refusal shows in the adjusted pool (S3 not in it).
        self.assertEqual(result.verdict.pools["adjusted"]["total"], 4)

    def test_addition_failing_a_judge_check_is_excluded(self):
        reason_checks = {
            "T1": _checks(), "T2": _checks(), "S1": _checks(), "S2": _checks(),
            "S3": _checks(citation=_check("invalid", "The source does not say that.")),
        }
        result, _ = _run(_replies(judge=_judge(reason_checks=reason_checks)))
        item = _item_by_id(result, "S3")
        self.assertEqual(item["final_status"], "excluded")
        self.assertEqual(item["exclusion_reason"], "judge_invalid")
        # final: tech 10, sentiment (S1 bullish, S2 bearish) 5 → 7.5
        self.assertEqual(result.verdict.final_score, 7.5)

    def test_empty_final_pool_defaults_to_neutral_five(self):
        reason_checks = {
            "T1": _checks(logic=_check("invalid", "Flawed.")),
            "T2": _checks(),
            "S1": _checks(logic=_check("invalid", "Flawed.")),
            "S2": _checks(logic=_check("invalid", "Flawed.")),
            "S3": _checks(logic=_check("invalid", "Flawed.")),
        }
        attack_rulings = {
            "T2:logic": {"verdict": "attack_right", "reason": "Correct.", "citations": []}
        }
        result, _ = _run(
            _replies(judge=_judge(reason_checks=reason_checks, attack_rulings=attack_rulings))
        )
        verdict = result.verdict
        self.assertEqual(verdict.pools["final"]["total"], 0)
        self.assertEqual(verdict.final_score, 5.0)
        self.assertEqual(verdict.direction, Direction.HOLD)
        self.assertTrue(any("no surviving evidence to weigh" in w for w in result.warnings))

    def test_thin_base_is_flagged_when_most_initial_evidence_dies(self):
        reason_checks = {
            "T1": _checks(logic=_check("invalid", "Flawed.")),
            "T2": _checks(),
            "S1": _checks(logic=_check("invalid", "Flawed.")),
            "S2": _checks(logic=_check("invalid", "Flawed.")),
            "S3": _checks(),
        }
        result, _ = _run(_replies(judge=_judge(reason_checks=reason_checks)))
        self.assertTrue(
            any("the weight rests on a thin base" in w for w in result.warnings)
        )


class LinkVerificationTest(unittest.TestCase):
    def test_value_mismatch_auto_fails_the_citation_check(self):
        # The defender claims close = 999 (report says 100). The first
        # attempt is bounced with the mismatch shown; the model repeats
        # itself, so the lenient retry keeps the item but code fails it —
        # even though every AI ruled it valid.
        bad = [
            DEFENDER_ITEMS[0],
            _item("T2", "technicals", "bullish",
                  "The closing price (999.0) holds above the 95 support.",
                  [_link("closing price", "technicals.close", 999.0)]),
            DEFENDER_ITEMS[2], DEFENDER_ITEMS[3],
        ]
        checks = {"T1": _checks(), "T2": _checks(), "S1": _checks(), "S2": _checks()}
        result, fake = _run(
            _replies(
                defender_opening=_defender_opening(items=bad),
                review=_review(checks=checks),
                reply=_reply(responses={"add:S3": _checks()}),
                judge=_judge(attack_rulings={}),
            )
        )
        item = _item_by_id(result, "T2")
        self.assertEqual(item["value_check"]["verdict"], "invalid")
        self.assertEqual(item["final_status"], "excluded")
        self.assertEqual(item["exclusion_reason"], "value_mismatch")
        self.assertTrue(
            any("citation check failed mechanically" in w for w in result.warnings)
        )
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the DEFENDER analyst" in p
        )
        self.assertIn("does not match", retry_prompt)
        # final: tech = T1 only → 10, sentiment 10/3 → 6.67
        self.assertEqual(result.verdict.final_score, 6.67)

    def test_rounding_tolerance_accepts_honest_rounding(self):
        items = [
            _item("T1", "technicals", "bullish",
                  "The 14-day RSI (71) is above 70.",
                  [_link("14-day RSI", "technicals.rsi_14", 71)]),
        ] + DEFENDER_ITEMS[1:]
        result, _ = _run(_replies(defender_opening=_defender_opening(items=items)))
        self.assertEqual(_item_by_id(result, "T1")["value_check"]["verdict"], "valid")

    def test_group_path_link_is_dropped_leaf_kept(self):
        items = [
            _item("T1", "technicals", "bullish",
                  "The 14-day RSI (71.2) is above 70 and MACD confirms.",
                  [_link("14-day RSI", "technicals.rsi_14", 71.2),
                   _link("MACD", "technicals.macd", 1.2)]),
        ] + DEFENDER_ITEMS[1:]
        result, fake = _run(
            _replies(defender_opening=_defender_opening(items=items)),
            retry_replies={"defender_opening": _defender_opening(items=items)},
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual([link["ref"] for link in t1["links"]], ["technicals.rsi_14"])
        self.assertEqual(t1["value_check"]["verdict"], "valid")
        self.assertTrue(
            any("does not resolve to a single report value" in w for w in result.warnings)
        )

    def test_link_text_missing_from_the_claim_is_dropped(self):
        items = [
            _item("T1", "technicals", "bullish",
                  "The 14-day RSI (71.2) is above 70.",
                  [_link("14-day RSI", "technicals.rsi_14", 71.2),
                   _link("relative strength", "technicals.rsi_14", 71.2)]),
        ] + DEFENDER_ITEMS[1:]
        result, _ = _run(
            _replies(defender_opening=_defender_opening(items=items)),
            retry_replies={"defender_opening": _defender_opening(items=items)},
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(len(t1["links"]), 1)
        self.assertTrue(any("not found in the claim" in w for w in result.warnings))

    def test_an_item_with_no_verifiable_links_fails_mechanically(self):
        items = [
            _item("T1", "technicals", "bullish",
                  "The 14-day RSI (71.2) is above 70.",
                  [_link("14-day RSI", "technicals.rsi_9", 71.2)]),
        ] + DEFENDER_ITEMS[1:]
        result, _ = _run(
            _replies(defender_opening=_defender_opening(items=items)),
            retry_replies={"defender_opening": _defender_opening(items=items)},
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(t1["links"], [])
        self.assertEqual(t1["value_check"]["verdict"], "invalid")
        self.assertEqual(t1["final_status"], "excluded")


class ScoreHandlingTest(unittest.TestCase):
    def test_no_challenges_skips_the_defender_reply(self):
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
                judge=_judge(
                    reason_checks={i["id"]: _checks() for i in DEFENDER_ITEMS},
                    attack_rulings={},
                ),
            )
        )
        self.assertNotIn("reply", fake.stages())
        self.assertEqual(len(fake.prompts), 5)
        # Nothing challenged → adjusted pool = initial pool.
        self.assertEqual(result.verdict.adjusted_score, result.verdict.initial_score)
        self.assertTrue(any("defender response skipped" in w for w in result.warnings))


class RetryContractTest(unittest.TestCase):
    def test_an_invalid_first_reply_is_retried_with_the_errors_shown(self):
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
                  [_link("Margins", "technicals.close", 100.0)]),
            _item("F2", "fundamentals", "bullish", "Revenue grew.",
                  [_link("Revenue", "technicals.close", 100.0)]),
        ]
        result, fake = _run(
            _replies(defender_opening=_defender_opening(items=items)),
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
        result, _ = _run(
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
        responses = {
            "T2:logic": _checks(
                logic=_check("invalid", "The claim was about the level.", ["technicals.close"])
            )
        }
        reason_checks = {i["id"]: _checks() for i in DEFENDER_ITEMS}
        result, fake = _run(
            _replies(
                attacker_opening="not json",
                reply=_reply(responses=responses),
                judge=_judge(reason_checks=reason_checks),
            )
        )
        self.assertIsNotNone(result.verdict)
        self.assertIn("review_checks_only", fake.stages())
        self.assertTrue(
            any("attacker opening invalid after retry — proceeding without additions" in w
                for w in result.warnings)
        )
        self.assertEqual(len(result.items), 4)

    def test_attacker_review_invalid_twice_degrades_to_no_challenges(self):
        reason_checks = {i["id"]: _checks() for i in DEFENDER_ITEMS}
        result, fake = _run(
            _replies(
                review="not json",
                judge=_judge(reason_checks=reason_checks, attack_rulings={}),
            )
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("attacker review invalid after retry" in w for w in result.warnings)
        )
        self.assertNotIn("reply", fake.stages())
        # No additions → pools count only the defender's list.
        self.assertEqual(result.verdict.pools["final"]["total"], 4)

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
    def test_opening_prompts_carry_the_ceilings_and_the_link_rules(self):
        _, fake = _run()
        defender = next(p for p in fake.prompts if "You are the DEFENDER analyst" in p)
        self.assertIn("technicals: 2-4", defender)
        self.assertIn("sentiment: 2-4", defender)
        self.assertIn("room, not a quota", defender)
        self.assertIn("Link rules", defender)
        self.assertIn("automatically fails the item's citation", defender)
        self.assertIn("You give no score", defender)
        attacker = next(
            p for p in fake.prompts if "You are the ATTACKER analyst, working alone" in p
        )
        self.assertIn("you have NOT seen it", attacker)

    def test_review_prompt_shows_both_lists_and_the_verified_values_rule(self):
        _, fake = _run()
        review = next(p for p in fake.prompts if "Compare the two evidence lists" in p)
        self.assertIn("The deal is not closed yet.", review)
        self.assertIn("The 14-day RSI (71.2)", review)
        self.assertIn("Code has already", review)
        self.assertIn("T1, T2, S1, S2", review)

    def test_reply_prompt_lists_every_challenge_with_its_key(self):
        _, fake = _run()
        reply = next(
            p for p in fake.prompts if "The attacker has challenged your evidence" in p
        )
        self.assertIn('"T2:logic"', reply)
        self.assertIn('"add:S3"', reply)
        self.assertIn("you MISSED this", reply)
        self.assertIn("You give no", reply)

    def test_judge_prompt_requires_checks_for_every_item_including_additions(self):
        _, fake = _run()
        judge = next(p for p in fake.prompts if "You are the JUDGE with the final say" in p)
        self.assertIn('"reason_checks" must cover exactly: T1, T2, S1, S2, S3', judge)
        self.assertIn('"attack_rulings" must cover exactly: T2:logic', judge)
        self.assertIn("added by the ATTACKER", judge)
        self.assertIn("regardless of what the defender said", judge)

    def test_summary_prompt_carries_the_computed_pool_scores(self):
        _, fake = _run()
        summary = next(p for p in fake.prompts if "Write the user-facing report" in p)
        self.assertIn("initial score 7.50", summary)
        self.assertIn("adjusted score 6.67", summary)
        self.assertIn("final score 6.67", summary)
        self.assertIn("3 bullish vs 2 bearish of 5", summary)
        self.assertIn("verdict: buy", summary)


class DetailShapeTest(unittest.TestCase):
    def test_to_detail_is_json_ready_with_the_v6_marker_and_legacy_keys(self):
        result, _ = _run()
        detail = result.to_detail()
        json.dumps(detail)  # must not raise
        self.assertEqual(detail["format"], 6)
        self.assertEqual(detail["turns"], [])
        self.assertEqual(len(detail["items"]), 5)
        verdict = detail["verdict"]
        self.assertEqual(verdict["direction"], "buy")
        self.assertEqual(verdict["final_score"], 6.67)
        self.assertEqual(verdict["initial_score"], 7.5)
        self.assertEqual(verdict["adjusted_score"], 6.67)
        self.assertIn("final", verdict["pools"])
        self.assertEqual(verdict["pools"]["final"]["total"], 5)
        # Legacy keys pre-v6 readers touch must exist and be inert.
        self.assertIsNone(verdict["confidence"])
        self.assertIsNone(verdict["scoring"])
        self.assertIsNone(verdict["weight"])
        self.assertEqual(verdict["reasons_for"], [])

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
                initial_score=7.5,
                adjusted_score=6.5,
                pools={},
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
        self.assertEqual(report.debate_detail["format"], 6)

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
