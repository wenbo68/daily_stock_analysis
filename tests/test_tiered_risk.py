# -*- coding: utf-8 -*-
"""Offline tests for the tier-3 risk vote (risk_detail format 2).

Fake-LLM tests covering: the vote choreography reused from tier 2 (two
blind risk lists in parallel with citation fix loops → merge → check
round on single-author risks → deciding round on 1-1 ties → summary),
the code-owned count → multiplier mapping (0 confirmed → 1.0, 1-3 →
0.5, 4+ → 0), the synthetic ``plan.<key>`` payload (tier-2 levels +
held shares, citable under the display-value contract), the no-floor
rule (an empty risk list is a valid answer), struck risks and discarded
votes, the failure rules (both lists failing voids the tier-3 verdict;
one list failing proceeds; a failed merge drops the second list; a
failed check round counts risks on the author's vote alone; a failed
deciding round excludes ties as unresolved; a broken summary never
voids), the stance passthrough (tier 3 echoes tier 2's direction and
never touches the levels), and code's ``apply_size_multiplier``.

The two list calls (and their fix loops) run in parallel threads, so
the fake LLM routes replies by prompt content, not call order.
"""
from __future__ import annotations

import json
import threading
import unittest

from src.tiered_analysis.llm_support import LlmUsageTracker
from src.tiered_analysis.providers.base import (
    Citation,
    Coverage,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.risk import (
    RiskEngine,
    RiskResult,
    RiskVerdict,
    apply_size_multiplier,
    multiplier_from_risk_count,
    plan_dimension,
    risk_ceilings,
)
from src.tiered_analysis.risk_models import (
    RiskItemModel,
    RiskListModel,
    check_risk_items,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.tiers import Tier3Stage, TierState


def _technicals():
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
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


def _tier2(direction=Direction.BUY, dimensions=()):
    # Plan display strings: entry "96", backup "94", stop "90", target "108".
    return TierReport(
        tier=2,
        symbol="AAPL",
        market=Market.US,
        coverage=Coverage.FULL,
        direction=direction,
        score=68,
        levels=SniperLevels(entry=96.0, secondary_entry=94.0,
                            stop_loss=90.0, take_profit=108.0),
        narrative="the bull case holds",
        dimensions=list(dimensions),
    )


# ---------------------------------------------------------------------------
# Reply builders — the default run:
#   first list:  T1 (RSI overbought), S1 (doubts, citation:2),
#                P1 (stop close under entry)
#   second list: T1/P1 identical (→ covered, confirmed 2-0),
#                T2 new (technical score cushion)
#   check round on S1/T2: S1 valid, T2 invalid (→ tied)
#   deciding round on T2: invalid → excluded 1-2 (outvoted)
#
# Confirmed risks: T1, P1, S1 = 3 of 4 listed → multiplier 0.5.
# ---------------------------------------------------------------------------


def _vlink(ref, value):
    return {"ref": ref, "value": value}


def _slink(number):
    return {"ref": f"citation:{number}"}


def _risk(item_id, group, claim, links):
    return {"id": item_id, "dimension": group, "claim": claim, "links": links}


def _vote(verdict="valid", reason=None, links=()):
    return {"verdict": verdict, "reason": reason, "links": list(links)}


RISKS_1 = [
    _risk("T1", "technicals",
          "The 14-day RSI (71.20) is overbought, so the entry may fill "
          "right before a pullback.",
          [_vlink("technicals.rsi_14", "71.20")]),
    _risk("S1", "sentiment",
          "Doubts remain about the deal coverage.",
          [_slink(2)]),
    _risk("P1", "plan",
          "The stop-loss (90) sits close under the entry (96), so normal "
          "volatility could stop the trade out.",
          [_vlink("plan.stop_loss", "90"), _vlink("plan.entry", "96")]),
]

RISKS_2 = [
    RISKS_1[0],
    _risk("T2", "technicals",
          "The technical score (68) leaves little cushion if momentum fades.",
          [_vlink("technicals.score", "68")]),
    RISKS_1[2],
]

DEFAULT_MATCH_MAP = [
    {"own_id": "T1", "covered_by": "T1"},
    {"own_id": "T2", "covered_by": None},
    {"own_id": "P1", "covered_by": "P1"},
]

BROKEN_P1 = _risk("P1", "plan",
                  "The stop-loss (999) sits close under the entry (96).",
                  [_vlink("plan.stop_loss", "999"), _vlink("plan.entry", "96")])


def _list_reply(items):
    return json.dumps({"items": items})


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
                "S1": _vote("valid", "Supported by the source.", [_slink(2)]),
                "T2": _vote("invalid",
                            "A merely decent score is not a concrete risk."),
            }
        }
    )


def _decider(votes=None):
    return json.dumps(
        {
            "votes": votes
            if votes is not None
            else {
                "T2": _vote("invalid",
                            "The objection stands; the score is not a danger."),
            }
        }
    )


def _summary():
    return json.dumps({"summary": "Three risks survived; size is halved."})


def _replies(**overrides):
    replies = {
        "lister1": _list_reply(RISKS_1),
        "lister2": _list_reply(RISKS_2),
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
    ("risk bullets failed the code's citation check", "fix"),
    ("You are the FIRST risk analyst", "lister1"),
    ("You are the SECOND risk analyst", "lister2"),
    ("Match the two risk lists", "merge"),
    ("cast the deciding vote", "decider"),
    ("cast the second vote", "check"),
    ("Write the user-facing risk report", "summary"),
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


def _run(replies=None, retry_replies=None, dimensions=None,
         direction=Direction.BUY, ownership=0):
    fake = RoutedSummarizer(replies or _replies(), retry_replies)
    engine = RiskEngine(summarizer=fake)
    dims = dimensions or _dimensions()
    result = engine.run(
        "AAPL", _tier2(direction=direction, dimensions=dims), dims,
        ownership=ownership,
    )
    return result, fake


def _item_by_id(result, item_id):
    return next(i for i in result.items if i["id"] == item_id)


# ---------------------------------------------------------------------------


class MultiplierMappingTest(unittest.TestCase):
    def test_owner_spec_count_thresholds(self):
        self.assertEqual(multiplier_from_risk_count(0), 1.0)
        self.assertEqual(multiplier_from_risk_count(1), 0.5)
        self.assertEqual(multiplier_from_risk_count(3), 0.5)
        self.assertEqual(multiplier_from_risk_count(4), 0.0)
        self.assertEqual(multiplier_from_risk_count(10), 0.0)


class PlanDimensionTest(unittest.TestCase):
    def test_levels_and_ownership_become_citable_payload(self):
        plan = plan_dimension(_tier2(), ownership=300)
        self.assertEqual(plan.dimension, "plan")
        self.assertEqual(
            plan.payload,
            {"entry": 96.0, "secondary_entry": 94.0, "stop_loss": 90.0,
             "take_profit": 108.0, "ownership_shares": 300},
        )

    def test_zero_ownership_stays_out_of_the_payload(self):
        plan = plan_dimension(_tier2(), ownership=0)
        self.assertNotIn("ownership_shares", plan.payload)

    def test_no_levels_and_no_ownership_means_no_plan_group(self):
        bare = TierReport(
            tier=2, symbol="AAPL", market=Market.US, coverage=Coverage.FULL,
            direction=Direction.BUY,
        )
        self.assertIsNone(plan_dimension(bare, ownership=0))

    def test_ceilings_cover_the_plan_group_without_a_floor(self):
        plan = plan_dimension(_tier2(), ownership=300)
        ceilings = risk_ceilings(_dimensions(), plan)
        self.assertEqual(ceilings["technicals"], 4)  # leaf count
        self.assertEqual(ceilings["sentiment"], 4)  # 2 citations × 2
        self.assertEqual(ceilings["plan"], 5)  # payload fields


class RiskModelTest(unittest.TestCase):
    def test_empty_risk_list_is_valid(self):
        model = RiskListModel.model_validate({"items": []})
        self.assertEqual(model.items, [])

    def test_ceiling_enforced_but_no_floor(self):
        items = [RiskItemModel.model_validate(_risk(
            f"T{i}", "technicals", f"claim {i} (100)",
            [_vlink("technicals.close", "100")])) for i in (1, 2, 3)]
        with self.assertRaises(ValueError) as ctx:
            check_risk_items(items, ["technicals"], {"technicals": 2})
        self.assertIn("maximum is 2", str(ctx.exception))
        # No floor: zero items for a data group is fine.
        check_risk_items([], ["technicals"], {"technicals": 2})

    def test_items_must_stay_inside_data_groups(self):
        item = RiskItemModel.model_validate(_risk(
            "F1", "fundamentals", "claim (100)",
            [_vlink("technicals.close", "100")]))
        with self.assertRaises(ValueError) as ctx:
            check_risk_items([item], ["technicals"], {})
        self.assertIn("no collected data", str(ctx.exception))


class ChoreographyTest(unittest.TestCase):
    def test_default_run_calls_and_outcomes(self):
        result, fake = _run()
        stages = fake.stages()
        self.assertEqual(len(stages), 6)
        self.assertEqual(sorted(stages[:2]), ["lister1", "lister2"])
        self.assertEqual(stages[2:], ["merge", "check", "decider", "summary"])

        verdict = result.verdict
        self.assertEqual(verdict.stance, Direction.BUY)
        self.assertEqual(verdict.confirmed_risks, 3)
        self.assertEqual(verdict.total_risks, 4)
        self.assertEqual(verdict.size_multiplier, 0.5)
        self.assertEqual(verdict.counts["final"]["groups"],
                         {"technicals": 1, "sentiment": 1, "plan": 1})

        # Both-listed risks: confirmed 2-0 at birth, no votes attached.
        for confirmed_id in ("T1", "P1"):
            item = _item_by_id(result, confirmed_id)
            self.assertEqual(item["authors"], 2)
            self.assertEqual(item["votes"], [])
            self.assertEqual(item["final_status"], "counted")
        # Single-author risk with a valid check vote: counted 2-0.
        s1 = _item_by_id(result, "S1")
        self.assertEqual([v["role"] for v in s1["votes"]], ["checker"])
        self.assertEqual(s1["final_status"], "counted")
        # Tied risk outvoted 1-2 by the deciding round.
        t2 = _item_by_id(result, "T2")
        self.assertEqual([v["role"] for v in t2["votes"]],
                         ["checker", "decider"])
        self.assertEqual(t2["final_status"], "excluded")
        self.assertEqual(t2["exclusion_reason"], "outvoted")

    def test_all_covered_skips_check_round(self):
        replies = _replies(
            lister1=_list_reply([RISKS_1[0], RISKS_1[2]]),
            lister2=_list_reply([RISKS_1[0], RISKS_1[2]]),
            merge=_merge([
                {"own_id": "T1", "covered_by": "T1"},
                {"own_id": "P1", "covered_by": "P1"},
            ]),
        )
        result, fake = _run(replies)
        self.assertEqual(sorted(fake.stages()[:2]), ["lister1", "lister2"])
        self.assertEqual(fake.stages()[2:], ["merge", "summary"])
        self.assertIn(
            "every risk was listed by both analysts — check round skipped",
            result.warnings,
        )
        self.assertEqual(result.verdict.confirmed_risks, 2)
        self.assertEqual(result.verdict.size_multiplier, 0.5)

    def test_no_ties_means_no_deciding_round(self):
        replies = _replies(check=_check({
            "S1": _vote("valid", "Supported by the source.", [_slink(2)]),
            "T2": _vote("valid", "A thin cushion is a fair concern."),
        }))
        result, fake = _run(replies)
        self.assertEqual(fake.stages()[2:], ["merge", "check", "summary"])
        self.assertEqual(result.verdict.confirmed_risks, 4)
        self.assertEqual(result.verdict.size_multiplier, 0.0)

    def test_empty_lists_mean_full_size_and_three_calls(self):
        replies = _replies(lister1=_list_reply([]), lister2=_list_reply([]))
        result, fake = _run(replies)
        self.assertEqual(sorted(fake.stages()[:2]), ["lister1", "lister2"])
        self.assertEqual(fake.stages()[2:], ["summary"])
        self.assertEqual(result.items, [])
        self.assertEqual(result.verdict.confirmed_risks, 0)
        self.assertEqual(result.verdict.total_risks, 0)
        self.assertEqual(result.verdict.size_multiplier, 1.0)

    def test_one_empty_list_skips_merge_and_keeps_the_other(self):
        replies = _replies(
            lister1=_list_reply([]),
            check=_check({
                "T1": _vote("valid", "Overbought is a real entry risk."),
                "T2": _vote("valid", "A thin cushion is a fair concern."),
                "P1": _vote("valid", "The stop is tight."),
            }),
        )
        result, fake = _run(replies)
        # No merge call: nothing to match against an empty first list.
        self.assertNotIn("merge", fake.stages())
        self.assertEqual(fake.stages()[2:], ["check", "summary"])
        ids = sorted(i["id"] for i in result.items)
        self.assertEqual(ids, ["P1", "T1", "T2"])
        for item in result.items:
            self.assertEqual(item["authors"], 1)

    def test_ownership_appears_in_the_context(self):
        _result, fake = _run(ownership=300)
        lister_prompt = fake.prompts[0]
        self.assertIn("ownership_shares", lister_prompt)
        self.assertIn('"ownership_shares": "300"', lister_prompt)
        self.assertIn("plus ownership_shares", lister_prompt)

    def test_lister_prompt_shows_ceilings_and_no_minimum(self):
        _result, fake = _run()
        prompt = fake.prompts[0]
        self.assertIn("technicals: up to 4", prompt)
        self.assertIn("plan: up to 4", prompt)  # 4 levels, no ownership
        self.assertIn("There is NO minimum", prompt)

    def test_summary_prompt_states_the_fixed_mapping(self):
        _result, fake = _run()
        prompt = fake.prompts[-1]
        self.assertIn("0 confirmed = full size", prompt)
        self.assertIn("size multiplier: 0.5x", prompt)


class VoteOutcomeTest(unittest.TestCase):
    def test_decider_valid_rescues_a_tied_risk(self):
        replies = _replies(decider=_decider({
            "T2": _vote("valid", "The cushion concern is real."),
        }))
        result, _fake = _run(replies)
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["final_status"], "counted")
        self.assertEqual(result.verdict.confirmed_risks, 4)
        self.assertEqual(result.verdict.size_multiplier, 0.0)

    def test_no_deciding_vote_excludes_as_unresolved(self):
        replies = _replies(decider="not json")
        result, _fake = _run(replies, retry_replies={"decider": "still not json"})
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["final_status"], "excluded")
        self.assertEqual(t2["exclusion_reason"], "unresolved")
        self.assertIn(
            "deciding round invalid after retry — tied risks excluded as "
            "unresolved",
            result.warnings,
        )

    def test_check_degrade_counts_on_the_authors_vote_alone(self):
        replies = _replies(check="not json")
        result, fake = _run(replies, retry_replies={"check": "still not json"})
        self.assertNotIn("decider", fake.stages())
        self.assertIn(
            "check round invalid after retry — risks counted on their "
            "author's vote alone",
            result.warnings,
        )
        self.assertEqual(result.verdict.confirmed_risks, 4)
        self.assertEqual(result.verdict.size_multiplier, 0.0)


class StruckRiskTest(unittest.TestCase):
    def test_unfixable_citation_strikes_the_risk_out_of_the_count(self):
        replies = _replies(
            lister1=_list_reply([RISKS_1[0], RISKS_1[1], BROKEN_P1]),
            fix=_fix([BROKEN_P1]),  # every fix round returns it still broken
            merge=_merge([
                {"own_id": "T1", "covered_by": "T1"},
                {"own_id": "T2", "covered_by": None},
                {"own_id": "P1", "covered_by": None},
            ]),
            check=_check({
                "S1": _vote("valid", "Supported by the source.", [_slink(2)]),
                "T2": _vote("valid", "A thin cushion is a fair concern."),
                "P2": _vote("valid", "The stop is close to the entry."),
            }),
        )
        result, fake = _run(replies)
        self.assertEqual(fake.stages().count("fix"), 3)

        struck = _item_by_id(result, "P1")
        self.assertTrue(struck["struck"])
        self.assertEqual(struck["final_status"], "excluded")
        self.assertEqual(struck["exclusion_reason"], "citation_failed")
        self.assertTrue(struck["problems"])
        self.assertTrue(
            any("P1: citations unfixable" in w for w in result.warnings)
        )
        # The healthy second-list P1 joined as P2; the struck one never
        # entered the merge prompt.
        merge_prompt = next(p for p in fake.prompts if stage_of(p) == "merge")
        self.assertNotIn("999", merge_prompt)
        self.assertEqual(result.verdict.total_risks, 4)  # T1, S1, T2, P2
        self.assertEqual(result.verdict.confirmed_risks, 4)


class VoteCitationTest(unittest.TestCase):
    def test_numeric_reason_without_links_gets_a_fix_call(self):
        replies = _replies(
            check=_check({
                "S1": _vote("valid", "Supported by the source.", [_slink(2)]),
                "T2": _vote("invalid", "The RSI is already 71.20."),
            }),
            vote_fix=_vote_fix({
                "T2": _vote("invalid", "The RSI is already 71.20.",
                            [_vlink("technicals.rsi_14", "71.20")]),
            }),
        )
        result, fake = _run(replies)
        self.assertIn("vote_fix", fake.stages())
        t2 = _item_by_id(result, "T2")
        checker = t2["votes"][0]
        self.assertEqual(checker["links"][0]["ref"], "technicals.rsi_14")

    def test_unfixable_vote_is_discarded_and_the_author_stands(self):
        bad_vote = _vote("invalid", "The RSI is already 71.20.")
        replies = _replies(
            check=_check({
                "S1": _vote("valid", "Supported by the source.", [_slink(2)]),
                "T2": bad_vote,
            }),
            vote_fix=_vote_fix({"T2": bad_vote}),
        )
        result, fake = _run(replies)
        self.assertEqual(fake.stages().count("vote_fix"), 3)
        self.assertTrue(
            any("vote on T2 discarded" in w for w in result.warnings)
        )
        # No opposing vote survived → the author's vote stands unopposed.
        t2 = _item_by_id(result, "T2")
        self.assertEqual(t2["votes"], [])
        self.assertEqual(t2["final_status"], "counted")
        self.assertEqual(result.verdict.confirmed_risks, 4)


class FailureRulesTest(unittest.TestCase):
    def test_both_lists_failing_voids_the_tier3_verdict(self):
        replies = _replies(lister1="not json", lister2="also not json")
        result, _fake = _run(
            replies,
            retry_replies={"lister1": "nope", "lister2": "nope"},
        )
        self.assertIsNone(result.verdict)
        self.assertIn(
            "both analyst lists invalid after retry — tier-3 risk verdict "
            "voided",
            result.warnings,
        )

    def test_one_list_failing_proceeds_with_the_other(self):
        replies = _replies(
            lister2="not json",
            check=_check({
                "T1": _vote("valid", "Overbought is a real entry risk."),
                "S1": _vote("valid", "Supported by the source.", [_slink(2)]),
                "P1": _vote("valid", "The stop is tight."),
            }),
        )
        result, fake = _run(replies, retry_replies={"lister2": "still bad"})
        self.assertNotIn("merge", fake.stages())
        self.assertIn(
            "second analyst list invalid after retry — proceeding with the "
            "other list only",
            result.warnings,
        )
        self.assertEqual(result.verdict.total_risks, 3)

    def test_failed_merge_drops_the_second_list(self):
        replies = _replies(
            merge="not json",
            check=_check({
                "T1": _vote("valid", "Overbought is a real entry risk."),
                "S1": _vote("valid", "Supported by the source.", [_slink(2)]),
                "P1": _vote("valid", "The stop is tight."),
            }),
        )
        result, _fake = _run(replies, retry_replies={"merge": "still bad"})
        self.assertIn(
            "merge invalid after retry — second list dropped", result.warnings
        )
        self.assertEqual(sorted(i["id"] for i in result.items),
                         ["P1", "S1", "T1"])

    def test_broken_summary_never_voids_the_computed_verdict(self):
        replies = _replies(summary="not json")
        result, _fake = _run(replies)
        self.assertIsNotNone(result.verdict)
        self.assertEqual(result.verdict.summary, "")
        self.assertIn(
            "judge summary unparseable — computed verdict stands",
            result.warnings,
        )

    def test_llm_crash_returns_a_structured_result(self):
        replies = _replies(lister1=RuntimeError("boom"),
                           lister2=RuntimeError("boom"))
        result, _fake = _run(replies)
        self.assertIsNone(result.verdict)
        self.assertTrue(
            any("risk vote LLM call failed" in w for w in result.warnings)
        )


class UsageTrackingTest(unittest.TestCase):
    def test_parallel_lister_calls_land_in_the_active_tracker(self):
        from src.tiered_analysis.llm_support import record_llm_usage

        fake = RoutedSummarizer(_replies())

        def counting(prompt):
            record_llm_usage(10, 5)
            return fake(prompt)

        tracker = LlmUsageTracker()
        engine = RiskEngine(summarizer=counting)
        dims = _dimensions()
        with tracker.activate():
            engine.run("AAPL", _tier2(dimensions=dims), dims)
        self.assertEqual(tracker.to_detail()["total"]["calls"], 6)


class DetailShapeTest(unittest.TestCase):
    def test_format_2_with_legacy_keys(self):
        result, _fake = _run()
        detail = result.to_detail()
        self.assertEqual(detail["format"], 2)
        self.assertEqual(detail["takes"], [])
        verdict = detail["verdict"]
        self.assertEqual(verdict["stance"], "buy")
        self.assertEqual(verdict["size_multiplier"], 0.5)
        self.assertEqual(verdict["confirmed_risks"], 3)
        self.assertEqual(verdict["total_risks"], 4)
        # Legacy keys so pre-format-2 readers never crash.
        self.assertIsNone(verdict["confidence"])
        self.assertEqual(verdict["stop_advice"], "keep")
        self.assertIsNone(verdict["tightened_stop"])
        self.assertEqual(verdict["key_risks"], [])
        json.dumps(detail)  # JSON-ready end to end

    def test_items_carry_no_direction(self):
        result, _fake = _run()
        for item in result.items:
            self.assertNotIn("direction", item)


class ApplySizeMultiplierTest(unittest.TestCase):
    def test_code_applies_the_multiplier(self):
        self.assertEqual(apply_size_multiplier(100, 1.0), 100)
        self.assertEqual(apply_size_multiplier(100, 0.5), 50)
        self.assertEqual(apply_size_multiplier(100, 0.0), 0)

    def test_lot_rounding_after_scaling(self):
        self.assertEqual(apply_size_multiplier(300, 0.5, lot_size=100), 100)
        self.assertEqual(apply_size_multiplier(400, 0.5, lot_size=100), 200)

    def test_rejects_off_enum_multiplier(self):
        with self.assertRaises(ValueError):
            apply_size_multiplier(100, 0.75)


class _FakeEngine:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, symbol, tier2, dimensions, ownership=0):
        self.calls.append(
            {"symbol": symbol, "tier2": tier2, "ownership": ownership}
        )
        return self.result


def _verdict(multiplier=0.5, stance=Direction.BUY):
    return RiskVerdict(
        stance=stance,
        size_multiplier=multiplier,
        summary="three risks survived",
        confirmed_risks=3,
        total_risks=4,
        counts={"initial": {"groups": {}, "total": 4},
                "final": {"groups": {}, "total": 3}},
    )


class TestTier3Stage(unittest.TestCase):
    def _state(self, ownership=0):
        dims = _dimensions()
        tier2 = _tier2(dimensions=dims)
        state = TierState(symbol="AAPL", market=Market.US, ownership=ownership)
        state.reports[2] = tier2
        state.dimensions = dims
        return state, tier2

    def test_verdict_echoes_tier2_and_keeps_the_levels(self):
        state, tier2 = self._state(ownership=300)
        engine = _FakeEngine(RiskResult(verdict=_verdict()))
        report = Tier3Stage(engine=engine).run(state)
        self.assertEqual(report.tier, 3)
        self.assertEqual(report.direction, tier2.direction)
        self.assertEqual(report.levels, tier2.levels)
        self.assertEqual(report.narrative, "three risks survived")
        self.assertEqual(report.risk_detail["format"], 2)
        self.assertIsNone(report.confidence)
        # The stage hands the state's held shares to the engine.
        self.assertEqual(engine.calls[0]["ownership"], 300)

    def test_no_verdict_falls_back_to_tier2(self):
        state, tier2 = self._state()
        engine = _FakeEngine(RiskResult(warnings=["boom"]))
        report = Tier3Stage(engine=engine).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(report.direction, tier2.direction)
        self.assertTrue(
            any("falls back to tier 2" in w for w in report.warnings)
        )

    def test_missing_tier2_report_is_unavailable(self):
        state = TierState(symbol="AAPL", market=Market.US)
        report = Tier3Stage(engine=_FakeEngine(RiskResult())).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)

    def test_no_evidence_skips_engine(self):
        state = TierState(symbol="AAPL", market=Market.US)
        state.reports[2] = _tier2()
        engine = _FakeEngine(RiskResult())
        report = Tier3Stage(engine=engine).run(state)
        self.assertEqual(report.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(engine.calls, [])


if __name__ == "__main__":
    unittest.main()
