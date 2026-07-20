# -*- coding: utf-8 -*-
"""Offline tests for the tier-2 evidence vote (v11 — weighted 1-5).

Fake-LLM tests covering: the vote choreography (two blind analyst lists
in parallel, each with a code citation check + fix loop → merge → check
round on single-author bullets → deciding round on 1-1 ties → summary),
the vote arithmetic (author = first valid vote; both-listed = confirmed
2-0; majority of three decides), the deterministic weighted score
(every voter rates a bullet's importance 1-5; a bullet's weight is the
median of its voters' ratings, mean when there are two; score =
10 × Σweight(bullish) / Σweight(all); snapshots initial/final),
the display-value citation contract (links are {ref, value} copied
exactly as the report pages display it; sentiment links are bare
{ref: citation:N}), the vote citation contract (reasons stating numbers
must cite them; unfixable votes are discarded), struck bullets from
either analyst, the Pydantic retry-once contract, and every failure
rule — both lists failing voids the verdict (tier 2 falls back to
tier 1), one list failing proceeds with the other, a failed merge drops
the second list, a failed check round counts bullets on the author's
vote alone, a failed deciding round excludes ties as unresolved, and a
broken summary never voids a computed verdict.

The two list calls (and their fix loops) run in parallel threads, so
the fake LLM routes replies by prompt content, not call order.
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
    value_pattern,
)
from src.tiered_analysis.llm_support import (
    LlmUsageTracker,
    display_value,
    record_llm_usage,
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
        # "macd" is a grouping on purpose: the leaf-only link rule must
        # reject "technicals.macd" but accept "technicals.macd.signal".
        # Leaf count = 4 (close, rsi_14, score, macd.signal). Display
        # strings: close "100", rsi_14 "71.20", score "68", signal "1.20".
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
# Reply builders — the default run:
#   first list:  T1 bullish (RSI), T2 bearish (close), S1 bullish, S2 bearish
#   second list: T1/S1/S2 identical (→ covered, confirmed 2-0),
#                T2 bullish (tech score, → renumbered T3),
#                S3 bearish (→ stays S3)
#   check round on T2/T3/S3: T2 voted invalid (→ tied), T3/S3 valid
#   deciding round on T2: valid → counted 2-1
#
# Score (flat counting): initial = final = 10 × 3 bullish / 6 = 5.00 → hold
# ---------------------------------------------------------------------------


def _vlink(ref, value):
    return {"ref": ref, "value": value}


def _slink(number):
    return {"ref": f"citation:{number}"}


def _item(item_id, dimension, direction, claim, links, weight=2,
          weight_reason=None):
    return {
        "id": item_id,
        "dimension": dimension,
        "direction": direction,
        "claim": claim,
        "links": links,
        "weight": weight,
        "weight_reason": weight_reason,
    }


def _vote(verdict="valid", reason=None, links=(), weight=2,
          weight_reason=None):
    return {"verdict": verdict, "reason": reason, "links": list(links),
            "weight": weight, "weight_reason": weight_reason}


LIST_1 = [
    _item("T1", "technicals", "bullish",
          "The 14-day RSI (71.20) is above 70, showing strong momentum.",
          [_vlink("technicals.rsi_14", "71.20")]),
    _item("T2", "technicals", "bearish",
          "The closing price (100) is below the 105 resistance.",
          [_vlink("technicals.close", "100")]),
    _item("S1", "sentiment", "bullish",
          "A big deal was announced.",
          [_slink(1)]),
    _item("S2", "sentiment", "bearish",
          "Doubts remain about the coverage.",
          [_slink(2)]),
]

LIST_2 = [
    LIST_1[0],
    _item("T2", "technicals", "bullish",
          "The technical score (68) is strong.",
          [_vlink("technicals.score", "68")]),
    LIST_1[2],
    LIST_1[3],
    _item("S3", "sentiment", "bearish",
          "The deal is not closed yet.",
          [_slink(2)]),
]

DEFAULT_MATCH_MAP = [
    {"own_id": "T1", "covered_by": "T1"},
    {"own_id": "T2", "covered_by": None},
    {"own_id": "S1", "covered_by": "S1"},
    {"own_id": "S2", "covered_by": "S2"},
    {"own_id": "S3", "covered_by": None},
]

BROKEN_T2 = _item("T2", "technicals", "bearish",
                  "The closing price (999) is below the 105 resistance.",
                  [_vlink("technicals.close", "999")])


def _list_reply(items):
    return json.dumps({"items": items, "no_data_dimensions": []})


def _fix(items):
    return json.dumps({"items": items})


def _vote_fix(votes):
    return json.dumps({"votes": votes})


def _merge(match_map=None):
    return json.dumps(
        {"match_map": match_map if match_map is not None else DEFAULT_MATCH_MAP}
    )


def _check(votes=None):
    return json.dumps(
        {
            "votes": votes
            if votes is not None
            else {
                "T2": _vote("invalid",
                            "A single close below one level is not a trend."),
                "T3": _vote("valid", "The score reading is fair."),
                "S3": _vote("valid", "Supported by the source.", [_slink(2)]),
            }
        }
    )


def _decider(votes=None):
    return json.dumps(
        {
            "votes": votes
            if votes is not None
            else {
                "T2": _vote("valid",
                            "The bearish reading of the close is defensible."),
            }
        }
    )


def _summary():
    return json.dumps({"summary": "The evidence splits down the middle."})


def _replies(**overrides):
    replies = {
        "lister1": _list_reply(LIST_1),
        "lister2": _list_reply(LIST_2),
        "merge": _merge(),
        "check": _check(),
        "decider": _decider(),
        "summary": _summary(),
    }
    replies.update(overrides)
    return replies


# Marker → stage, checked in order — the fix markers must match before
# the generic role openers. The default reply set has no fix entries, so
# an unexpected fix round fails the test loudly.
MARKERS = [
    ("votes failed the code's citation check", "vote_fix"),
    ("bullets failed the code's citation check", "fix"),
    ("You are the FIRST analyst", "lister1"),
    ("You are the SECOND analyst", "lister2"),
    ("Match the two evidence lists", "merge"),
    ("cast the deciding vote", "decider"),
    ("cast the second vote", "check"),
    ("Write the user-facing report", "summary"),
]

RETRY_MARKER = "Your previous reply was invalid"


def stage_of(prompt):
    for marker, stage in MARKERS:
        if marker in prompt:
            return stage
    raise AssertionError(f"prompt matches no stage: {prompt[:120]}")


class RoutedSummarizer:
    """Routes replies by prompt content; thread-safe (the two lists and
    their fix loops run in parallel). ``retry_replies`` serve the second
    attempt of a stage."""

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


class DisplayValueTest(unittest.TestCase):
    """The Python port must mirror the frontend's formatValue exactly."""

    def test_whole_numbers_stay_whole(self):
        self.assertEqual(display_value(205.0), "205")
        self.assertEqual(display_value(68), "68")
        self.assertEqual(display_value(0), "0")

    def test_decimals_get_two_places(self):
        self.assertEqual(display_value(71.2), "71.20")
        self.assertEqual(display_value(202.23449935913087), "202.23")
        self.assertEqual(display_value(-0.9879906617313091), "-0.99")

    def test_big_numbers_are_worded(self):
        self.assertEqual(display_value(2_500_000), "2.50 million")
        self.assertEqual(display_value(3_200_000_000.0), "3.20 billion")
        self.assertEqual(display_value(1_500_000_000_000.0), "1.50 trillion")

    def test_text_passes_through(self):
        self.assertEqual(display_value("bullish"), "bullish")


class ValuePatternTest(unittest.TestCase):
    """Where a display value counts as "in the sentence"."""

    def test_digit_boundaries_stop_partial_matches(self):
        self.assertIsNone(value_pattern("205").search("price 1205 today"))
        self.assertIsNone(value_pattern("205").search("price 205.4 today"))
        self.assertIsNotNone(value_pattern("205").search("price (205) today"))
        self.assertIsNotNone(value_pattern("205").search("ends at 205."))

    def test_exact_display_string_is_required(self):
        self.assertIsNone(value_pattern("71.20").search("RSI is 71.2 now"))
        self.assertIsNotNone(value_pattern("71.20").search("RSI is 71.20 now"))
        self.assertIsNone(value_pattern("71.20").search("was 271.20 then"))

    def test_thousands_separators_are_tolerated(self):
        self.assertIsNotNone(value_pattern("1234").search("volume of 1,234 shares"))
        self.assertIsNotNone(value_pattern("1234").search("volume of 1234 shares"))

    def test_text_values_are_loose_on_case_and_underscores(self):
        self.assertIsNotNone(value_pattern("golden_cross").search("a Golden Cross formed"))


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
        # 5 technicals bullets against a ceiling of 4 → retry with the error.
        many = [
            LIST_1[0], LIST_1[1],
            _item("T3", "technicals", "bullish",
                  "The technical score (68) is high.",
                  [_vlink("technicals.score", "68")]),
            _item("T4", "technicals", "bullish",
                  "The MACD signal (1.20) is positive.",
                  [_vlink("technicals.macd.signal", "1.20")]),
            _item("T5", "technicals", "bullish",
                  "The technical score (68) is strong.",
                  [_vlink("technicals.score", "68")]),
            LIST_1[2], LIST_1[3],
        ]
        result, fake = _run(
            _replies(lister1=_list_reply(many)),
            retry_replies={"lister1": _list_reply(LIST_1)},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn("the maximum is 4", retry_prompt)


class ChoreographyTest(unittest.TestCase):
    def test_full_run_six_calls_and_the_computed_verdict(self):
        result, fake = _run()
        self.assertEqual(
            sorted(fake.stages()),
            sorted(["lister1", "lister2", "merge", "check", "decider", "summary"]),
        )
        verdict = result.verdict
        self.assertIsNotNone(verdict)
        # flat counting: 3 bullish of 6 bullets → 5.0
        self.assertEqual(verdict.initial_score, 5.0)
        self.assertEqual(verdict.final_score, 5.0)
        self.assertEqual(verdict.direction, Direction.HOLD)
        self.assertEqual(verdict.summary, "The evidence splits down the middle.")
        self.assertEqual(
            verdict.pools["initial"]["dimensions"]["technicals"],
            {"bullish": 2, "bearish": 1, "total": 3,
             "bullish_weight": 4, "bearish_weight": 2, "total_weight": 6},
        )
        self.assertEqual(verdict.pools["final"]["bullish"], 3)
        self.assertEqual(verdict.pools["final"]["bearish"], 3)

    def test_the_two_lists_run_before_everything_else(self):
        _, fake = _run()
        stages = fake.stages()
        self.assertEqual(sorted(stages[:2]), ["lister1", "lister2"])
        self.assertEqual(stages[2:], ["merge", "check", "decider", "summary"])

    def test_both_listed_bullets_are_confirmed_without_any_vote(self):
        result, _ = _run()
        for item_id in ("T1", "S1", "S2"):
            item = _item_by_id(result, item_id)
            self.assertEqual(item["authors"], 2)
            self.assertEqual(item["votes"], [])
            self.assertEqual(item["final_status"], "counted")

    def test_the_uncovered_second_list_bullet_is_renumbered_in(self):
        result, _ = _run()
        t3 = _item_by_id(result, "T3")
        self.assertEqual(t3["authors"], 1)
        self.assertEqual(t3["claim"], "The technical score (68) is strong.")
        self.assertEqual(t3["final_status"], "counted")

    def test_a_tied_bullet_carries_both_votes_and_the_majority_wins(self):
        result, _ = _run()
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["authors"], 1)
        self.assertEqual(
            [(v["role"], v["verdict"]) for v in t2["votes"]],
            [("checker", "invalid"), ("decider", "valid")],
        )
        self.assertEqual(t2["final_status"], "counted")  # 2-1

    def test_all_covered_lists_skip_both_vote_rounds(self):
        match_map = [
            {"own_id": item["id"], "covered_by": item["id"]} for item in LIST_1
        ]
        result, fake = _run(
            _replies(lister2=_list_reply(LIST_1), merge=_merge(match_map))
        )
        self.assertEqual(
            sorted(fake.stages()),
            sorted(["lister1", "lister2", "merge", "summary"]),
        )
        self.assertTrue(
            any("check round skipped" in w for w in result.warnings)
        )
        for item in result.items:
            self.assertEqual(item["authors"], 2)
            self.assertEqual(item["final_status"], "counted")

    def test_no_ties_skips_the_deciding_round(self):
        votes = {
            "T2": _vote("valid", "Fair reading."),
            "T3": _vote("valid", "Fair reading."),
            "S3": _vote("valid", "Fair reading."),
        }
        result, fake = _run(_replies(check=_check(votes)))
        self.assertNotIn("decider", fake.stages())
        self.assertEqual(len(fake.prompts), 5)
        for item in result.items:
            self.assertEqual(item["final_status"], "counted")

    def test_model_written_source_markers_are_stripped(self):
        # The UI appends its own [N] hyperlinks, so a literal "[2]" the
        # model wrote in the sentence would show twice — code strips it
        # from claims and vote reasons alike.
        marked = _item("S3", "sentiment", "bearish",
                       "The deal is not closed yet [2].", [_slink(2)])
        second = [LIST_2[0], LIST_2[1], LIST_2[2], LIST_2[3], marked]
        votes = {
            "T2": _vote("valid", "Fair reading."),
            "T3": _vote("valid", "Fair reading."),
            "S3": _vote("valid", "Supported by the source [2].", [_slink(2)]),
        }
        result, _ = _run(
            _replies(lister2=_list_reply(second), check=_check(votes))
        )
        s3 = _item_by_id(result, "S3")
        self.assertEqual(s3["claim"], "The deal is not closed yet.")
        self.assertEqual(s3["votes"][0]["reason"], "Supported by the source.")

    def test_an_opposite_direction_match_is_rejected_and_becomes_a_dispute(self):
        # The second analyst reads the same RSI as bearish; matching it to
        # the first analyst's bullish bullet must be rejected — both
        # versions face the votes instead.
        rsi_bear = _item("T2", "technicals", "bearish",
                         "The 14-day RSI (71.20) is overbought territory.",
                         [_vlink("technicals.rsi_14", "71.20")])
        second = [LIST_1[0], rsi_bear, LIST_1[2], LIST_1[3], LIST_2[4]]
        bad_map = [
            {"own_id": "T1", "covered_by": "T1"},
            {"own_id": "T2", "covered_by": "T1"},  # opposite direction!
            {"own_id": "S1", "covered_by": "S1"},
            {"own_id": "S2", "covered_by": "S2"},
            {"own_id": "S3", "covered_by": None},
        ]
        good_map = [dict(row) for row in bad_map]
        good_map[1] = {"own_id": "T2", "covered_by": None}
        result, fake = _run(
            _replies(lister2=_list_reply(second), merge=_merge(bad_map)),
            retry_replies={"merge": _merge(good_map)},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "Match the two evidence lists" in p
        )
        self.assertIn("must be left unmatched", retry_prompt)
        t3 = _item_by_id(result, "T3")  # the bearish RSI, renumbered in
        self.assertEqual(t3["direction"], "bearish")
        self.assertEqual(t3["final_status"], "counted")


class VoteOutcomeTest(unittest.TestCase):
    """Majority of at most three votes; the author is always valid."""

    def test_outvoted_bullet_is_excluded(self):
        result, _ = _run(
            _replies(decider=_decider({"T2": _vote("invalid", "The objection holds.")}))
        )
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["final_status"], "excluded")  # 1-2
        self.assertEqual(t2["exclusion_reason"], "outvoted")
        # final: 3 bullish of the 5 remaining bullets → 6.0 hold
        self.assertEqual(result.verdict.final_score, 6.0)
        self.assertEqual(result.verdict.direction, Direction.HOLD)

    def test_failed_deciding_round_excludes_ties_as_unresolved(self):
        result, _ = _run(_replies(decider="not json"))
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["final_status"], "excluded")
        self.assertEqual(t2["exclusion_reason"], "unresolved")
        self.assertTrue(
            any("deciding round invalid after retry — tied bullets excluded" in w
                for w in result.warnings)
        )
        self.assertTrue(
            any("no deciding vote for T2" in w for w in result.warnings)
        )

    def test_failed_check_round_counts_bullets_on_the_author_alone(self):
        result, fake = _run(_replies(check="not json"))
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("check round invalid after retry — bullets counted on" in w
                for w in result.warnings)
        )
        self.assertNotIn("decider", fake.stages())
        for item in result.items:
            self.assertEqual(item["final_status"], "counted")

    def test_empty_final_pool_defaults_to_neutral_five(self):
        # Everything single-authored dies; the both-listed bullets are the
        # only survivors — so kill them too by making the second list fail
        # and voting every bullet down, unbreakable ties resolved against.
        votes = {
            item_id: _vote("invalid", "Flawed.")
            for item_id in ("T1", "T2", "S1", "S2")
        }
        deciders = {
            item_id: _vote("invalid", "The objection holds.")
            for item_id in ("T1", "T2", "S1", "S2")
        }
        result, _ = _run(
            _replies(
                lister2="not json",
                check=_check(votes),
                decider=_decider(deciders),
            )
        )
        verdict = result.verdict
        self.assertEqual(verdict.pools["final"]["total"], 0)
        self.assertEqual(verdict.final_score, 5.0)
        self.assertEqual(verdict.direction, Direction.HOLD)
        self.assertTrue(any("no surviving evidence to weigh" in w for w in result.warnings))
        self.assertTrue(
            any("the final score rests on a thin base" in w for w in result.warnings)
        )


class WeightTest(unittest.TestCase):
    """v11: every voter rates a bullet 1-5; the bullet's weight is the
    median of its voters' ratings (mean when there are two) and the
    score is 10 × Σweight(bullish) / Σweight(all)."""

    RSI_HEAVY = _item("T1", "technicals", "bullish",
                      "The 14-day RSI (71.20) is above 70, showing strong momentum.",
                      [_vlink("technicals.rsi_14", "71.20")], weight=5,
                      weight_reason="Momentum this strong drives the thesis.")

    def test_a_heavy_bullet_moves_the_weighted_score(self):
        # Both authors rate the bullish RSI a 5 → its weight is 5 while
        # everything else stays 2. Bullish weight 5+2+2=9 of 15 total.
        first = [self.RSI_HEAVY, LIST_1[1], LIST_1[2], LIST_1[3]]
        second = [self.RSI_HEAVY, LIST_2[1], LIST_2[2], LIST_2[3], LIST_2[4]]
        result, _ = _run(
            _replies(lister1=_list_reply(first), lister2=_list_reply(second))
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(t1["author_weights"], [5, 5])
        self.assertEqual(t1["weight"], 5)
        self.assertEqual(result.verdict.pools["final"]["bullish_weight"], 9)
        self.assertEqual(result.verdict.pools["final"]["total_weight"], 15)
        self.assertEqual(result.verdict.final_score, round(10 * 9 / 15, 2))

    def test_three_voters_take_the_median(self):
        # T2: author 2, checker invalid 3, decider valid 3 → median 3.
        votes = {
            "T2": _vote("invalid", "A single close below one level is not a trend.",
                        weight=3),
            "T3": _vote("valid", "The score reading is fair."),
            "S3": _vote("valid", "Supported by the source.", [_slink(2)]),
        }
        decider = {"T2": _vote("valid", "The bearish reading is defensible.",
                               weight=3)}
        result, _ = _run(_replies(check=_check(votes), decider=_decider(decider)))
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["author_weights"], [2])
        self.assertEqual([v["weight"] for v in t2["votes"]], [3, 3])
        self.assertEqual(t2["weight"], 3)
        # bearish weight 3+2+2=7 of 13 → 10×6/13 bullish.
        self.assertEqual(result.verdict.final_score, round(10 * 6 / 13, 2))

    def test_two_voters_take_the_mean_so_halves_happen(self):
        # T3: its single author rated it 3; the checker rates it 2 → 2.5.
        heavy_score = _item("T2", "technicals", "bullish",
                            "The technical score (68) is strong.",
                            [_vlink("technicals.score", "68")], weight=3)
        second = [LIST_2[0], heavy_score, LIST_2[2], LIST_2[3], LIST_2[4]]
        result, _ = _run(_replies(lister2=_list_reply(second)))
        t3 = _item_by_id(result, "T3")
        self.assertEqual(t3["author_weights"], [3])
        self.assertEqual(t3["weight"], 2.5)
        self.assertEqual(result.verdict.pools["final"]["total_weight"], 12.5)

    def test_both_author_ratings_ride_in_on_the_match_map(self):
        # First analyst rates the RSI a 1, the second a 5 → mean 3.
        light = dict(self.RSI_HEAVY, weight=1)
        first = [light, LIST_1[1], LIST_1[2], LIST_1[3]]
        second = [self.RSI_HEAVY, LIST_2[1], LIST_2[2], LIST_2[3], LIST_2[4]]
        result, _ = _run(
            _replies(lister1=_list_reply(first), lister2=_list_reply(second))
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(t1["author_weights"], [1, 5])
        self.assertEqual(t1["weight"], 3)

    def test_an_omitted_weight_defaults_to_the_neutral_3(self):
        # Replies without any "weight" keys reproduce flat counting: every
        # weight lands on the 1-5 middle, so the sums cancel out.
        def stripped(items):
            return [
                {key: value for key, value in item.items()
                 if key not in ("weight", "weight_reason")}
                for item in items
            ]

        bare = {key: {"verdict": vote["verdict"], "reason": vote["reason"],
                      "links": vote["links"]}
                for key, vote in json.loads(_check())["votes"].items()}
        bare_decider = {key: {"verdict": vote["verdict"],
                              "reason": vote["reason"], "links": vote["links"]}
                        for key, vote in json.loads(_decider())["votes"].items()}
        result, _ = _run(
            _replies(
                lister1=_list_reply(stripped(LIST_1)),
                lister2=_list_reply(stripped(LIST_2)),
                check=_check(bare),
                decider=_decider(bare_decider),
            )
        )
        self.assertIsNotNone(result.verdict)
        self.assertEqual(_item_by_id(result, "T1")["author_weights"], [3, 3])
        self.assertEqual(result.verdict.final_score, 5.0)

    def test_the_author_rating_survives_a_citation_fix(self):
        # The fix reply comes back without the original rating or its
        # reason — code freezes both so they cannot silently reset.
        broken_heavy = dict(BROKEN_T2, weight=5, weight_reason="Key level.")
        result, _ = _run(
            _replies(
                lister1=_list_reply([LIST_1[0], broken_heavy, LIST_1[2], LIST_1[3]]),
                fix=_fix([LIST_1[1]]),  # the fixed bullet says weight 2
            )
        )
        t2 = _item_by_id(result, "T2")
        self.assertFalse(t2["struck"])
        self.assertEqual(t2["author_weights"], [5])
        self.assertEqual(t2["author_votes"][0]["weight_reason"], "Key level.")

    def test_author_votes_carry_the_lister_number_and_the_reason(self):
        # v11 attribution: a both-listed bullet keeps each lister's own
        # rating and reason; a second-list extra is lister 2's.
        first_heavy = dict(self.RSI_HEAVY, weight=4,
                           weight_reason="Strong but not decisive.")
        first = [first_heavy, LIST_1[1], LIST_1[2], LIST_1[3]]
        second = [self.RSI_HEAVY, LIST_2[1], LIST_2[2], LIST_2[3], LIST_2[4]]
        result, _ = _run(
            _replies(lister1=_list_reply(first), lister2=_list_reply(second))
        )
        t1 = _item_by_id(result, "T1")
        self.assertEqual(
            t1["author_votes"],
            [
                {"lister": 1, "weight": 4,
                 "weight_reason": "Strong but not decisive."},
                {"lister": 2, "weight": 5,
                 "weight_reason": "Momentum this strong drives the thesis."},
            ],
        )
        t2 = _item_by_id(result, "T2")  # single-author, from the first list
        self.assertEqual([v["lister"] for v in t2["author_votes"]], [1])
        t3 = _item_by_id(result, "T3")  # renumbered second-list extra
        self.assertEqual([v["lister"] for v in t3["author_votes"]], [2])

    def test_vote_score_reasons_are_stored_with_the_votes(self):
        votes = {
            "T2": _vote("invalid",
                        "A single close below one level is not a trend.",
                        weight=4, weight_reason="Levels drive the plan."),
            "T3": _vote("valid", "The score reading is fair."),
            "S3": _vote("valid", "Supported by the source.", [_slink(2)]),
        }
        result, _ = _run(_replies(check=_check(votes)))
        t2 = _item_by_id(result, "T2")
        checker = next(v for v in t2["votes"] if v["role"] == "checker")
        self.assertEqual(checker["weight"], 4)
        self.assertEqual(checker["weight_reason"], "Levels drive the plan.")


class StruckBulletTest(unittest.TestCase):
    """Bullets whose citations code cannot fix are struck — crossed out,
    never voted on, in no pool — from either analyst."""

    def test_an_unfixable_first_list_bullet_is_struck_and_sits_out(self):
        broken_first = [LIST_1[0], BROKEN_T2, LIST_1[2], LIST_1[3]]
        result, fake = _run(
            _replies(
                lister1=_list_reply(broken_first),
                fix=_fix([BROKEN_T2]),
                check=_check({
                    "T3": _vote("valid", "Fair reading."),
                    "S3": _vote("valid", "Fair reading."),
                }),
            )
        )
        self.assertEqual(fake.stages().count("fix"), 3)
        t2 = _item_by_id(result, "T2")
        self.assertTrue(t2["struck"])
        self.assertIsNone(t2["weight"])  # in no pool, so no final weight
        self.assertEqual(t2["final_status"], "excluded")
        self.assertEqual(t2["exclusion_reason"], "citation_failed")
        self.assertTrue(any("must be copied exactly" in p for p in t2["problems"]))
        self.assertTrue(
            any("struck from the list" in w for w in result.warnings)
        )
        # The struck bullet never reaches the merge or the votes…
        merge_prompt = next(p for p in fake.prompts if stage_of(p) == "merge")
        self.assertNotIn("999", merge_prompt)
        check_prompt = next(p for p in fake.prompts if stage_of(p) == "check")
        self.assertNotIn("999", check_prompt)
        # …and never enters a pool: initial = T1, S1, S2, T3, S3.
        self.assertEqual(result.verdict.pools["initial"]["total"], 5)
        # flat counting: 3 bullish of the 5 surviving bullets → 6.0
        self.assertEqual(result.verdict.initial_score, 6.0)

    def test_an_unfixable_second_list_bullet_is_struck_too(self):
        broken_s3 = _item("S3", "sentiment", "bearish",
                          "The deal is not closed yet.", [_slink(9)])
        second = [LIST_2[0], LIST_2[1], LIST_2[2], LIST_2[3], broken_s3]
        match_map = [row for row in DEFAULT_MATCH_MAP if row["own_id"] != "S3"]
        result, fake = _run(
            _replies(
                lister2=_list_reply(second),
                fix=_fix([broken_s3]),
                merge=_merge(match_map),
                check=_check({
                    "T2": _vote("valid", "Fair reading."),
                    "T3": _vote("valid", "Fair reading."),
                }),
            )
        )
        self.assertEqual(fake.stages().count("fix"), 3)
        s3 = _item_by_id(result, "S3")  # renumbered into the tree, struck
        self.assertTrue(s3["struck"])
        self.assertEqual(s3["exclusion_reason"], "citation_failed")
        self.assertEqual(s3["votes"], [])
        self.assertEqual(result.verdict.pools["initial"]["total"], 5)

    def test_a_fixed_bullet_rejoins_without_a_trace(self):
        broken_first = [LIST_1[0], BROKEN_T2, LIST_1[2], LIST_1[3]]
        result, fake = _run(
            _replies(
                lister1=_list_reply(broken_first),
                fix=_fix([LIST_1[1]]),
            )
        )
        self.assertEqual(fake.stages().count("fix"), 1)
        t2 = _item_by_id(result, "T2")
        self.assertFalse(t2["struck"])
        self.assertEqual(t2["links"][0]["value"], "100")
        self.assertEqual(t2["final_status"], "counted")
        self.assertFalse(any("struck" in w for w in result.warnings))

    def test_the_fix_prompt_carries_only_the_broken_bullets_and_errors(self):
        broken_first = [LIST_1[0], BROKEN_T2, LIST_1[2], LIST_1[3]]
        _, fake = _run(
            _replies(
                lister1=_list_reply(broken_first),
                fix=_fix([LIST_1[1]]),
            )
        )
        fix_prompt = next(p for p in fake.prompts if stage_of(p) == "fix")
        self.assertIn('"T2"', fix_prompt)
        self.assertIn("999", fix_prompt)
        self.assertNotIn("The 14-day RSI", fix_prompt)  # healthy bullets stay out
        self.assertIn("must be copied exactly", fix_prompt)
        self.assertIn("'100'", fix_prompt)  # the correct display string is shown


class VoteCitationTest(unittest.TestCase):
    """Vote reasons follow the same code-checked citation contract."""

    def test_a_numeric_reason_without_links_is_sent_back_to_fix(self):
        votes = {
            "T2": _vote("invalid", "The close of 100.00 tells nothing."),
            "T3": _vote("valid", "Fair reading."),
            "S3": _vote("valid", "Fair reading."),
        }
        fixed = {
            "T2": _vote("invalid",
                        "The close of 100 tells nothing on its own.",
                        [_vlink("technicals.close", "100")]),
        }
        result, fake = _run(
            _replies(check=_check(votes), vote_fix=_vote_fix(fixed))
        )
        self.assertEqual(fake.stages().count("vote_fix"), 1)
        vote_fix_prompt = next(p for p in fake.prompts if stage_of(p) == "vote_fix")
        self.assertIn("states a number — cite it with a link", vote_fix_prompt)
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["votes"][0]["links"][0]["ref"], "technicals.close")
        self.assertEqual(t2["final_status"], "counted")  # decider still saves it

    def test_a_vote_with_an_unfixable_citation_is_discarded(self):
        bad_vote = _vote("invalid", "The close is 999.00 which is wrong.",
                         [_vlink("technicals.close", "999")])
        votes = {
            "T2": bad_vote,
            "T3": _vote("valid", "Fair reading."),
            "S3": _vote("valid", "Fair reading."),
        }
        result, fake = _run(
            _replies(check=_check(votes), vote_fix=_vote_fix({"T2": bad_vote}))
        )
        self.assertEqual(fake.stages().count("vote_fix"), 3)
        self.assertTrue(
            any("vote on T2 discarded — citations unfixable" in w
                for w in result.warnings)
        )
        t2 = _item_by_id(result, "T2")
        # The discarded objection carries no weight: author unopposed.
        self.assertEqual(t2["votes"], [])
        self.assertEqual(t2["final_status"], "counted")
        self.assertNotIn("decider", fake.stages())

    def test_a_vote_link_value_must_match_the_display_string(self):
        votes = {
            "T2": _vote("invalid", "The close of 100 is neutral.",
                        [_vlink("technicals.close", "100.0")]),
            "T3": _vote("valid", "Fair reading."),
            "S3": _vote("valid", "Fair reading."),
        }
        fixed = {
            "T2": _vote("invalid", "The close of 100 is neutral.",
                        [_vlink("technicals.close", "100")]),
        }
        _, fake = _run(_replies(check=_check(votes), vote_fix=_vote_fix(fixed)))
        vote_fix_prompt = next(p for p in fake.prompts if stage_of(p) == "vote_fix")
        self.assertIn("must be copied exactly", vote_fix_prompt)


class RetryContractTest(unittest.TestCase):
    def test_an_invalid_first_reply_is_retried_with_the_errors_shown(self):
        bad = _list_reply([LIST_1[0], LIST_1[2], LIST_1[3]])
        result, fake = _run(
            _replies(lister1=bad),
            retry_replies={"lister1": _list_reply(LIST_1)},
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("first analyst list needed a retry" in w for w in result.warnings)
        )
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn("only 1 item(s)", retry_prompt)

    def test_a_link_without_a_value_is_rejected_by_the_form(self):
        items = [
            _item("T1", "technicals", "bullish",
                  "The 14-day RSI (71.20) is above 70.",
                  [{"ref": "technicals.rsi_14"}]),
        ] + LIST_1[1:]
        result, fake = _run(
            _replies(lister1=_list_reply(items)),
            retry_replies={"lister1": _list_reply(LIST_1)},
        )
        self.assertIsNotNone(result.verdict)
        retry_prompt = next(
            p for p in fake.prompts
            if RETRY_MARKER in p and "You are the FIRST analyst" in p
        )
        self.assertIn('must carry "value"', retry_prompt)

    def test_a_match_map_pointing_at_unknown_ids_is_rejected(self):
        bad_map = [dict(row) for row in DEFAULT_MATCH_MAP]
        bad_map[0] = {"own_id": "T1", "covered_by": "T9"}
        result, _ = _run(
            _replies(merge=_merge(bad_map)),
            retry_replies={"merge": _merge()},
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(any("merge needed a retry" in w for w in result.warnings))


class FailureRulesTest(unittest.TestCase):
    def test_both_lists_invalid_twice_voids(self):
        result, _ = _run(_replies(lister1="not json", lister2="not json"))
        self.assertIsNone(result.verdict)
        self.assertEqual(result.items, [])
        self.assertTrue(
            any("both analyst lists invalid after retry — tier-2 verdict voided" in w
                for w in result.warnings)
        )

    def test_one_list_invalid_twice_proceeds_with_the_other(self):
        votes = {
            item_id: _vote("valid", "Fair reading.")
            for item_id in ("T1", "T2", "S1", "S2", "S3")
        }
        result, fake = _run(
            _replies(lister1="not json", check=_check(votes))
        )
        self.assertIsNotNone(result.verdict)
        self.assertNotIn("merge", fake.stages())
        self.assertTrue(
            any("first analyst list invalid after retry — proceeding with "
                "the other list only" in w for w in result.warnings)
        )
        # The surviving list's bullets are all single-author.
        self.assertEqual(len(result.items), 5)
        for item in result.items:
            self.assertEqual(item["authors"], 1)

    def test_merge_invalid_twice_drops_the_second_list(self):
        votes = {
            item_id: _vote("valid", "Fair reading.")
            for item_id in ("T1", "T2", "S1", "S2")
        }
        result, fake = _run(
            _replies(merge="not json", check=_check(votes))
        )
        self.assertIsNotNone(result.verdict)
        self.assertTrue(
            any("merge invalid after retry — second list dropped" in w
                for w in result.warnings)
        )
        self.assertEqual(len(result.items), 4)  # first list only

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

    def test_llm_failure_mid_debate_fails_loud_without_a_verdict(self):
        result, _ = _run(_replies(merge=RuntimeError("llm down")))
        self.assertIsNone(result.verdict)
        self.assertTrue(any("debate LLM call failed" in w for w in result.warnings))


class UsageTrackingTest(unittest.TestCase):
    def test_parallel_list_calls_report_into_the_active_tracker(self):
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

    def test_fix_round_calls_are_counted_too(self):
        routed = RoutedSummarizer(
            _replies(
                lister1=_list_reply([LIST_1[0], BROKEN_T2, LIST_1[2], LIST_1[3]]),
                fix=_fix([LIST_1[1]]),
            )
        )

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
        self.assertEqual(detail["stages"]["tier2_debate"]["calls"], 7)


class PromptContentTest(unittest.TestCase):
    def test_list_prompts_carry_the_ceilings_and_the_link_rules(self):
        _, fake = _run()
        first = next(p for p in fake.prompts if "You are the FIRST analyst" in p)
        self.assertIn("technicals: 2-4", first)
        self.assertIn("sentiment: 2-4", first)
        self.assertIn("room, not a quota", first)
        self.assertIn("Link rules", first)
        self.assertIn("copied EXACTLY", first)
        self.assertIn("do not wrap them in quotation marks", first)
        self.assertIn("You give no score", first)
        second = next(p for p in fake.prompts if "You are the SECOND analyst" in p)
        self.assertIn("you have NOT seen it", second)

    def test_the_evidence_block_shows_display_values(self):
        _, fake = _run()
        first = next(p for p in fake.prompts if "You are the FIRST analyst" in p)
        # The model never sees the raw floats — only the display strings.
        self.assertIn('"rsi_14": "71.20"', first)
        self.assertIn('"close": "100"', first)
        self.assertIn('"signal": "1.20"', first)

    def test_merge_prompt_shows_both_lists_and_the_direction_rule(self):
        _, fake = _run()
        merge = next(p for p in fake.prompts if "Match the two evidence lists" in p)
        self.assertIn("The technical score (68) is strong.", merge)
        self.assertIn("The 14-day RSI (71.20)", merge)
        self.assertIn("OPPOSITE direction", merge)
        self.assertIn("code assembles the merged list", merge)

    def test_check_prompt_names_the_single_author_bullets_only(self):
        _, fake = _run()
        check = next(p for p in fake.prompts if "cast the second vote" in p)
        self.assertIn("T2, T3, S3", check)
        self.assertIn("already code-verified", check)
        self.assertIn("listed by BOTH analysts", check)  # the tree shows authorship
        self.assertIn("Vote rules", check)

    def test_decider_prompt_shows_the_claim_and_the_objection(self):
        _, fake = _run()
        decider = next(p for p in fake.prompts if "cast the deciding vote" in p)
        self.assertIn('"votes" must cover exactly these bullet ids: T2', decider)
        self.assertIn("objection: A single close below one level", decider)
        self.assertIn("The closing price (100) is below the 105 resistance.", decider)

    def test_summary_prompt_carries_the_computed_pool_scores(self):
        _, fake = _run()
        summary = next(p for p in fake.prompts if "Write the user-facing report" in p)
        self.assertNotIn("initial score", summary)
        self.assertIn("final score 5.00", summary)
        self.assertIn("3 bullish vs 3", summary)
        self.assertIn("bearish of 6", summary)
        # The builders rate everything a 2: bullish weight 6 of 12 total.
        self.assertIn("bullish weight 6", summary)
        self.assertIn("of 12 total", summary)
        self.assertIn("outlook: neutral", summary)
        self.assertNotIn("verdict:", summary)

    def test_list_and_vote_prompts_carry_the_weight_rubric(self):
        _, fake = _run()
        first = next(p for p in fake.prompts if "You are the FIRST analyst" in p)
        self.assertIn("5 (very important", first)
        self.assertIn('"weight": 3', first)  # the item shape shows it
        self.assertIn('"weight_reason"', first)
        check = next(p for p in fake.prompts if "cast the second vote" in p)
        self.assertIn("regardless of your", check)
        self.assertIn("median of all voters' weights", check)
        self.assertIn('"weight_reason"', check)


class DetailShapeTest(unittest.TestCase):
    def test_to_detail_is_json_ready_with_the_v11_marker_and_legacy_keys(self):
        result, _ = _run()
        detail = result.to_detail()
        json.dumps(detail)  # must not raise
        self.assertEqual(detail["format"], 11)
        self.assertEqual(detail["turns"], [])
        self.assertEqual(len(detail["items"]), 6)
        verdict = detail["verdict"]
        self.assertEqual(verdict["direction"], "hold")
        self.assertEqual(verdict["final_score"], 5.0)
        self.assertEqual(verdict["initial_score"], 5.0)
        self.assertIn("final", verdict["pools"])
        self.assertNotIn("adjusted", verdict["pools"])
        self.assertEqual(verdict["pools"]["final"]["total"], 6)
        # Legacy keys pre-v8 readers touch must exist and be inert.
        self.assertIsNone(verdict["adjusted_score"])
        self.assertIsNone(verdict["confidence"])
        self.assertIsNone(verdict["scoring"])
        self.assertIsNone(verdict["weight"])
        self.assertEqual(verdict["reasons_for"], [])

    def test_voided_run_still_serializes(self):
        result, _ = _run(_replies(lister1="not json", lister2="not json"))
        detail = result.to_detail()
        json.dumps(detail)
        self.assertIsNone(detail["verdict"])
        self.assertEqual(detail["items"], [])


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
        self.assertEqual(report.debate_detail["format"], 11)

    def test_no_verdict_is_unknown_never_tier1_fallback(self):
        # Outlook redesign: a failed vote fails honestly — no silently
        # substituting the one-blob judge's direction.
        engine = _FakeEngine(DebateResult(warnings=["judge exploded"]))
        state = self._state(_tier1(Direction.BUY), dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertTrue(any("re-run" in w for w in report.warnings))

    def test_missing_tier1_report_is_unavailable(self):
        report = Tier2Stage(engine=_FakeEngine(None)).run(self._state())
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)

    def test_no_evidence_skips_engine_entirely(self):
        engine = _FakeEngine(self._verdict_result())
        state = self._state(_tier1(Direction.BUY))  # no dimensions anywhere
        report = Tier2Stage(engine=engine).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, Direction.UNKNOWN)
        self.assertEqual(engine.calls, [])

    def test_dimensions_fall_back_to_tier1_report(self):
        engine = _FakeEngine(self._verdict_result())
        tier1 = _tier1(Direction.BUY, dimensions=[_technicals()])
        report = Tier2Stage(engine=engine).run(self._state(tier1))
        self.assertEqual(report.coverage, Coverage.FULL)
        self.assertEqual(engine.calls, [("AAPL", 1)])


if __name__ == "__main__":
    unittest.main()
