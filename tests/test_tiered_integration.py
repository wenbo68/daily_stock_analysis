# -*- coding: utf-8 -*-
"""Offline tests for the production wiring of tiered analysis (integration).

The three real connections are faked here (data manager, DSA pipeline,
signal logger); what's under test is the glue:

- dsa_bars_loader: DataFetcherManager daily DataFrame -> chronological Bars
- dsa_analysis_runner: closure over StockAnalysisPipeline as a client
- run_tiered_analysis: collect dimensions + tier run + merge + signal log
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import pandas as pd

from src.tiered_analysis.earnings import EarningsInfo
from src.tiered_analysis.integration import (
    dsa_bars_loader,
    dsa_analysis_runner,
    run_tiered_analysis,
)
from src.tiered_analysis.schema import Action, Outlook
from src.tiered_analysis.providers.base import (
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction


def _daily_df(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])


class FakeManager:
    def __init__(self, df):
        self._df = df
        self.calls = []

    def get_daily_data(self, stock_code, days=30):
        self.calls.append((stock_code, days))
        return self._df, "fake-source"


class TestDsaBarsLoader(unittest.TestCase):
    def test_maps_dataframe_to_chronological_bars(self):
        df = _daily_df([
            ("2026-07-03", 11.0, 12.0, 10.5, 11.5, 1000),
            ("2026-07-01", 10.0, 11.0, 9.5, 10.5, 900),  # out of order
            ("2026-07-02", 10.5, 11.5, 10.0, 11.0, 950),
        ])
        manager = FakeManager(df)
        bars = dsa_bars_loader("AAPL", manager=manager)
        self.assertEqual([b.date for b in bars],
                         ["2026-07-01", "2026-07-02", "2026-07-03"])
        self.assertEqual(bars[-1].close, 11.5)
        self.assertEqual(bars[0].high, 11.0)
        # enough calendar days requested to cover 60 trading bars
        self.assertGreaterEqual(manager.calls[0][1], 90)

    def test_rows_with_missing_prices_are_dropped(self):
        df = _daily_df([
            ("2026-07-01", 10.0, 11.0, 9.5, 10.5, 900),
            ("2026-07-02", None, None, None, None, None),
        ])
        bars = dsa_bars_loader("AAPL", manager=FakeManager(df))
        self.assertEqual(len(bars), 1)

    def test_empty_dataframe_returns_empty_list(self):
        bars = dsa_bars_loader("AAPL", manager=FakeManager(_daily_df([])))
        self.assertEqual(bars, [])


class TestDsaAnalysisRunner(unittest.TestCase):
    def test_runs_pipeline_as_client_without_notifications(self):
        sentinel = object()
        captured = {}

        class FakePipeline:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def process_single_stock(self, code, **kwargs):
                captured["code"] = code
                captured["run"] = kwargs
                return sentinel

        with patch("src.core.pipeline.StockAnalysisPipeline", FakePipeline):
            result = dsa_analysis_runner("AAPL")

        self.assertIs(result, sentinel)
        self.assertEqual(captured["code"], "AAPL")
        self.assertEqual(captured["init"].get("query_source"), "tiered_analysis")
        self.assertFalse(captured["run"].get("single_stock_notify"))

    def test_none_result_raises_so_tier1_reports_unavailable(self):
        class FakePipeline:
            def __init__(self, **kwargs):
                pass

            def process_single_stock(self, code, **kwargs):
                return None

        with patch("src.core.pipeline.StockAnalysisPipeline", FakePipeline):
            with self.assertRaises(RuntimeError):
                dsa_analysis_runner("AAPL")


class _StubProvider(DimensionProvider):
    kind = SourceKind.NUMERIC

    def __init__(self, name, result=None, crash=False):
        self.dimension = name
        self._result = result
        self._crash = crash

    def supports(self, market):
        return True

    def collect(self, symbol):
        if self._crash:
            raise RuntimeError("provider blew up")
        return self._result


def _dim(name, coverage=Coverage.FULL):
    return DimensionResult(
        dimension=name,
        kind=SourceKind.NUMERIC,
        coverage=coverage,
        payload={"x": 1},
    )


def _fake_analysis_result():
    return {
        "decision_type": "buy",
        "confidence_level": "0.7",
        "sentiment_score": 72,
        "operation_advice": "buy the pullback",
        "dashboard": {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": 210.0,
                    "secondary_buy": 205.0,
                    "stop_loss": 198.0,
                    "take_profit": 230.0,
                }
            }
        },
    }


def _no_earnings(symbol, market):
    """Offline stand-in for the yfinance earnings lookup."""
    return EarningsInfo()


class TestRunTieredAnalysis(unittest.TestCase):
    def _run(self, providers=None, log_signal=True, logger=None, runner=None):
        logged = []

        def default_logger(report, trace_id=None):
            logged.append((report, trace_id))
            return "log-result"

        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=providers if providers is not None
            else [_StubProvider("technicals", _dim("technicals"))],
            analysis_runner=runner or (lambda symbol: _fake_analysis_result()),
            signal_logger=logger or default_logger,
            log_signal=log_signal,
            trace_id="t-1",
            earnings_lookup=_no_earnings,
        )
        return outcome, logged

    def test_dimensions_attached_and_signal_logged(self):
        outcome, logged = self._run()
        report = outcome.report
        self.assertEqual(report.direction, Direction.BUY)
        self.assertEqual([d.dimension for d in report.dimensions], ["technicals"])
        self.assertEqual(outcome.signal, "log-result")
        self.assertEqual(logged[0][1], "t-1")
        self.assertIs(logged[0][0], report)  # the enriched report is logged

    def test_coverage_merges_worst_dimension(self):
        providers = [
            _StubProvider("technicals", _dim("technicals", Coverage.FULL)),
            _StubProvider("macro_econ", _dim("macro_econ", Coverage.PARTIAL)),
        ]
        outcome, _ = self._run(providers=providers)
        self.assertEqual(outcome.report.coverage, Coverage.PARTIAL)

    def test_all_full_stays_full(self):
        outcome, _ = self._run()
        self.assertEqual(outcome.report.coverage, Coverage.FULL)

    def test_crashing_provider_becomes_unavailable_dimension(self):
        providers = [_StubProvider("fundamentals", crash=True)]
        outcome, _ = self._run(providers=providers)
        dim = outcome.report.dimensions[0]
        self.assertEqual(dim.dimension, "fundamentals")
        self.assertEqual(dim.coverage, Coverage.UNAVAILABLE)
        self.assertTrue(any("provider blew up" in w for w in dim.warnings))
        self.assertEqual(outcome.report.coverage, Coverage.PARTIAL)

    def test_log_signal_false_skips_logging(self):
        outcome, logged = self._run(log_signal=False)
        self.assertIsNone(outcome.signal)
        self.assertEqual(logged, [])

    def test_failed_tier1_still_returns_report_with_dimensions(self):
        def broken_runner(symbol):
            raise RuntimeError("LLM down")

        outcome, _ = self._run(runner=broken_runner)
        self.assertEqual(outcome.report.direction, Direction.UNKNOWN)
        self.assertEqual(outcome.report.coverage, Coverage.PARTIAL)
        self.assertTrue(outcome.report.dimensions)


class _FakeDebateEngine:
    def __init__(self, verdict=None, warnings=()):
        self._verdict = verdict
        self._warnings = list(warnings)
        self.calls = []

    def run(self, symbol, tier1, dimensions):
        from src.tiered_analysis.debate import DebateResult

        self.calls.append(symbol)
        return DebateResult(verdict=self._verdict, warnings=self._warnings)


def _technicals_dim_with_levels():
    """Payload the base-level formulas can compute from.

    Bases: entry=96 (nearest support capped at close), backup=94,
    stop=90 (entry − 2×ATR), target=108 (entry + 2×(entry−stop); no
    swing-high keys → no overhead resistance to cap it). Trend gate
    passes: close 100 > sma_60 90.
    """
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
        payload={"close": 100.0, "sma_20": 96.0, "sma_60": 90.0,
                 "swing_low_20": 94.0, "atr_14": 3.0},
    )


def _debate_verdict(direction=Direction.BUY, score=7.4):
    from src.tiered_analysis.debate import DebateVerdict

    return DebateVerdict(direction=direction, final_score=score,
                         summary="the vote settled it", initial_score=score,
                         pools={})


class TestDepthRoutingAndSizing(unittest.TestCase):
    """Outlook redesign: depth 1|2 routing, outlook/action, sizing."""

    def _run(self, depth=1, sizing_settings=None, sizing_overrides=None,
             debate_verdict=None, analysis_result=None):
        from src.tiered_analysis.settings import SizingSettings
        from src.tiered_analysis.tiers import Tier2Stage

        logged = []
        runner_calls = []

        def logger(report, trace_id=None):
            logged.append(report)
            return "log-result"

        def runner(symbol):
            runner_calls.append(symbol)
            return analysis_result or _fake_analysis_result()

        debate_engine = _FakeDebateEngine(verdict=debate_verdict)
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider("technicals", _technicals_dim_with_levels())],
            analysis_runner=runner,
            signal_logger=logger,
            depth=depth,
            sizing_settings=sizing_settings or SizingSettings(),
            sizing_overrides=sizing_overrides,
            tier2_stage=Tier2Stage(engine=debate_engine),
            earnings_lookup=_no_earnings,
        )
        return outcome, logged, debate_engine, runner_calls

    def test_default_depth_is_tier1_only(self):
        outcome, logged, debate_engine, runner_calls = self._run()
        self.assertEqual(outcome.depth, 1)
        self.assertEqual(sorted(outcome.state.reports), [1])
        self.assertIs(outcome.final_report, outcome.report)
        self.assertEqual(runner_calls, ["AAPL"])  # the blob IS the judge
        self.assertEqual(debate_engine.calls, [])
        self.assertEqual(logged[0].tier, 1)
        self.assertEqual(outcome.outlook, Outlook.BULLISH)
        self.assertEqual(outcome.action, Action.ENTER)

    def test_depth_2_skips_the_blob_and_runs_the_vote(self):
        outcome, logged, debate_engine, runner_calls = self._run(
            depth=2, debate_verdict=_debate_verdict())
        # The one-blob tier-1 call must NOT run at depth 2.
        self.assertEqual(runner_calls, [])
        self.assertEqual(sorted(outcome.state.reports), [1, 2])
        self.assertEqual(outcome.final_report.tier, 2)
        self.assertEqual(outcome.final_report.direction, Direction.BUY)
        self.assertEqual(debate_engine.calls, ["AAPL"])
        # the foundation report says why it has no verdict of its own
        self.assertTrue(any("skipped" in w for w in outcome.report.warnings))
        # the ledger gets the deepest tier, with the evidence attached
        self.assertEqual(logged[0].tier, 2)
        self.assertTrue(logged[0].dimensions)

    def test_depth_2_failure_has_no_tier1_fallback(self):
        outcome, _, _, _ = self._run(depth=2, debate_verdict=None)
        self.assertEqual(outcome.final_report.direction, Direction.UNKNOWN)
        self.assertEqual(outcome.outlook, Outlook.UNKNOWN)
        self.assertEqual(outcome.action, Action.UNKNOWN)
        self.assertTrue(any("re-run" in w
                            for w in outcome.final_report.warnings))

    def test_invalid_depth_rejected(self):
        for depth in (0, 3, 4):
            with self.assertRaises(ValueError):
                self._run(depth=depth)

    def test_sizing_off_by_default_with_explicit_refusal(self):
        outcome, _, _, _ = self._run()
        self.assertFalse(outcome.sizing["enabled"])
        self.assertEqual(outcome.sizing["reason_code"], "sizing_off")
        self.assertTrue(outcome.final_report.sizing.is_empty)

    def test_enabled_sizing_computes_shares_from_final_levels(self):
        from src.tiered_analysis.settings import SizingSettings

        outcome, logged, _, _ = self._run(
            sizing_settings=SizingSettings(capital=100000.0,
                                           risk_fraction=0.01))
        # entry 96, stop 90 → loss/share 6 → floor(1000/6) = 166 shares
        self.assertEqual(outcome.sizing["shares"], 166)
        self.assertTrue(outcome.sizing["enabled"])
        self.assertEqual(outcome.final_report.sizing.shares, 166.0)
        # the sized position reaches the signal ledger
        self.assertEqual(logged[0].sizing.shares, 166.0)

    def test_hold_direction_refuses_sizing_and_maps_to_no_trade(self):
        result = _fake_analysis_result()
        result["decision_type"] = "hold"
        outcome, _, _, _ = self._run(analysis_result=result)
        self.assertEqual(outcome.sizing["reason_code"], "not_a_buy")
        self.assertEqual(outcome.outlook, Outlook.NEUTRAL)
        self.assertEqual(outcome.action, Action.NO_TRADE)

    def test_per_run_overrides_enable_sizing(self):
        outcome, _, _, _ = self._run(
            sizing_overrides={"capital": 100000.0, "risk_fraction": 0.01})
        self.assertEqual(outcome.sizing["shares"], 166)

    def test_bullish_while_holding_is_keep_holding(self):
        outcome, _, _, _ = self._run(sizing_overrides={"ownership": 300})
        self.assertEqual(outcome.outlook, Outlook.BULLISH)
        self.assertEqual(outcome.action, Action.KEEP_HOLDING)
        self.assertEqual(outcome.sizing["ownership"], 300)

    def test_bearish_with_ownership_sells_the_full_holding(self):
        outcome, _, _, _ = self._run(
            depth=2, debate_verdict=_debate_verdict(Direction.SELL, 2.5),
            sizing_overrides={"ownership": 300})
        self.assertEqual(outcome.outlook, Outlook.BEARISH)
        self.assertEqual(outcome.action, Action.SELL_ALL)
        self.assertEqual(outcome.sizing["sell_shares"], 300)
        # buy sizing still refuses with not_a_buy... unless settings off
        self.assertIn(outcome.sizing["reason_code"], ("not_a_buy", "sizing_off"))

    def test_bearish_without_ownership_is_no_trade(self):
        outcome, _, _, _ = self._run(
            depth=2, debate_verdict=_debate_verdict(Direction.SELL, 2.5))
        self.assertEqual(outcome.action, Action.NO_TRADE)
        self.assertEqual(outcome.sizing["ownership"], 0)
        self.assertIsNone(outcome.sizing["sell_shares"])

    def test_plan_review_emits_structured_warnings_and_shares_detail(self):
        outcome, _, _, _ = self._run(
            sizing_overrides={"capital": 100000.0, "risk_fraction": 0.01})
        self.assertIsNone(outcome.risk_card)  # retired 2026-07-22
        pw = outcome.plan_warnings
        self.assertEqual(sorted(pw), ["entry", "shares", "stop_loss", "take_profit"])
        gap = pw["stop_loss"][0]
        self.assertEqual(gap["id"], "gap_atr")
        # open = stop 90 − 1×ATR 3 = 87; loss = 166 × (96 − 87) = 1494
        self.assertAlmostEqual(gap["values"]["atr_open"], 87.0)
        self.assertAlmostEqual(gap["values"]["atr_loss"], 1494.0)
        self.assertEqual(pw["take_profit"], [])  # R:R exactly the 2× goal
        shares_detail = outcome.report.levels_detail["levels"]["shares"]
        self.assertEqual(shares_detail["base"], 166)
        self.assertEqual(shares_detail["final"], 166)
        self.assertIsNone(shares_detail["adjusted"])

    def test_plan_review_absent_on_non_buy(self):
        result = _fake_analysis_result()
        result["decision_type"] = "hold"
        outcome, _, _, _ = self._run(analysis_result=result)
        self.assertIsNone(outcome.plan_warnings)
        self.assertNotIn("shares",
                         (outcome.report.levels_detail or {}).get("levels", {}))

    def test_earnings_detail_rides_along(self):
        outcome, _, _, _ = self._run()
        self.assertIsNotNone(outcome.earnings)
        self.assertIsNone(outcome.earnings.next_date)

    def test_llm_usage_always_present_with_scope_note(self):
        outcome, _, _, _ = self._run(depth=2, debate_verdict=None)
        self.assertEqual(outcome.llm_usage["total"]["calls"], 0)  # all fakes
        self.assertIn("tier-1", outcome.llm_usage["scope"])


class TestPlanReviewAdjustments(unittest.TestCase):
    """The AI plan review through the full orchestrator, LLM faked."""

    def _run_with_reply(self, reply: str):
        from src.tiered_analysis.settings import SizingSettings

        payload = {"close": 100.0, "sma_20": 96.0, "sma_60": 90.0,
                   "swing_low_20": 94.0, "atr_14": 3.0,
                   "avg_volume_20": 1000.0}
        dim = DimensionResult(
            dimension="technicals", kind=SourceKind.NUMERIC,
            coverage=Coverage.FULL, payload=payload,
        )
        prompts = []

        def summarizer(prompt):
            prompts.append(prompt)
            return reply

        outcome = run_tiered_analysis(
            "AAPL", market=Market.US,
            providers=[_StubProvider("technicals", dim)],
            analysis_runner=lambda symbol: _fake_analysis_result(),
            signal_logger=lambda report, trace_id=None: None,
            log_signal=False,
            sizing_settings=SizingSettings(capital=100000.0,
                                           risk_fraction=0.01),
            earnings_lookup=_no_earnings,
            plan_summarizer=summarizer,
        )
        return outcome, prompts

    def test_ai_share_trim_with_cited_reason(self):
        # 166 shares are 16.6% of the 1000-share ADV → liquidity flags →
        # the fake AI trims to 50 with a verified link.
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 50,
            "reasons": [{
                "check": "liquidity",
                "text": ("The planned order is far above the 5% liquidity "
                         "limit against an average daily volume of 1000."),
                "links": [{"ref": "technicals.avg_volume_20", "value": "1000"}],
            }],
        }]})
        outcome, prompts = self._run_with_reply(reply)
        self.assertEqual(len(prompts), 1)
        self.assertIn("liquidity", prompts[0])
        self.assertEqual(outcome.sizing["shares"], 50)
        detail = outcome.report.levels_detail["levels"]["shares"]
        self.assertEqual(detail["base"], 166)
        self.assertEqual(detail["adjusted"], 50)
        self.assertEqual(detail["reasons"][0]["check"], "liquidity")
        self.assertIn("liquidity limit", detail["reasons"][0]["text"])
        self.assertEqual(detail["reasons"][0]["links"][0]["ref"],
                         "technicals.avg_volume_20")
        # gap warning recomputes off the trimmed count: 50 × (96−87) = 450
        gap = outcome.plan_warnings["stop_loss"][0]
        self.assertAlmostEqual(gap["values"]["atr_loss"], 450.0)
        self.assertEqual(outcome.llm_usage["stages"].get("plan_adjust", {})
                         .get("calls", 0), 0)  # fake summarizer records none

    def test_uncited_number_in_reason_drops_adjustment(self):
        # "12.34%" is stated but cited by nothing and matches no report
        # value → both rounds fail → the computed plan stands.
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 50,
            "reasons": [{
                "check": "liquidity",
                "text": ("Order flow above 12.34% of daily volume is "
                         "hard to exit, so the count comes down."),
                "links": [{"ref": "technicals.avg_volume_20",
                           "value": "1000"}],
            }],
        }]})
        outcome, prompts = self._run_with_reply(reply)
        self.assertEqual(len(prompts), 2)  # one call + one fix round
        self.assertEqual(outcome.sizing["shares"], 166)
        self.assertTrue(any("has no citation" in w
                            for w in outcome.report.warnings))

    def test_threshold_and_own_numbers_need_no_citation(self):
        # "5%" restates the liquidity threshold and "50" is the proposed
        # value itself — neither needs a link; "1000" is cited.
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 50,
            "reasons": [{
                "check": "liquidity",
                "text": ("Cutting to 50 keeps the order under the 5% "
                         "limit against the average daily volume of "
                         "1000."),
                "links": [{"ref": "technicals.avg_volume_20",
                           "value": "1000"}],
            }],
        }]})
        outcome, prompts = self._run_with_reply(reply)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(outcome.sizing["shares"], 50)

    def test_share_increase_rejected(self):
        reply = json.dumps({"adjustments": [{
            "target": "shares", "value": 500,
            "reasons": [{"check": "liquidity", "text": "More is better.",
                         "links": []}],
        }]})
        outcome, _ = self._run_with_reply(reply)
        self.assertEqual(outcome.sizing["shares"], 166)
        detail = outcome.report.levels_detail["levels"]["shares"]
        self.assertIsNone(detail["adjusted"])
        self.assertTrue(detail["rejection"])
        self.assertTrue(any("shares rejected" in w
                            for w in outcome.report.warnings))

    def test_unparseable_reply_keeps_computed_plan(self):
        outcome, prompts = self._run_with_reply("not json at all")
        self.assertEqual(len(prompts), 2)  # one call + one fix round
        self.assertEqual(outcome.sizing["shares"], 166)
        self.assertTrue(any("plan-review reply problem" in w
                            for w in outcome.report.warnings))


class TestRegistryBarsLoaderWiring(unittest.TestCase):
    def test_get_providers_accepts_bars_loader(self):
        from src.tiered_analysis.providers.registry import get_providers
        from src.tiered_analysis.providers.technicals import Bar

        closes = [100.0 + i * 0.5 for i in range(70)]
        bars = [
            Bar(high=c + 1.0, low=c - 1.0, close=c, date=f"d{i}")
            for i, c in enumerate(closes)
        ]
        providers = get_providers(Market.US, bars_loader=lambda symbol: bars)
        technicals = next(p for p in providers if p.dimension == "technicals")
        result = technicals.collect("AAPL")
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertIsNotNone(result.payload["score"])


if __name__ == "__main__":
    unittest.main()
