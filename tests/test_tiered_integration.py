# -*- coding: utf-8 -*-
"""Offline tests for the production wiring of tiered analysis (integration).

The three real connections are faked here (data manager, DSA pipeline,
signal logger); what's under test is the glue:

- dsa_bars_loader: DataFetcherManager daily DataFrame -> chronological Bars
- dsa_analysis_runner: closure over StockAnalysisPipeline as a client
- run_tiered_analysis: collect dimensions + tier run + merge + signal log
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from src.tiered_analysis.integration import (
    dsa_bars_loader,
    dsa_analysis_runner,
    run_tiered_analysis,
)
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


class _FakeAdjuster:
    """No-LLM stand-in for LevelAdjuster."""

    def propose(self, symbol, bases, dimensions):
        return [], []


class _FakeDebateEngine:
    def __init__(self, verdict=None, warnings=()):
        self._verdict = verdict
        self._warnings = list(warnings)
        self.calls = []

    def run(self, symbol, tier1, dimensions):
        from src.tiered_analysis.debate import DebateResult

        self.calls.append(symbol)
        return DebateResult(verdict=self._verdict, warnings=self._warnings)


class _FakeRiskEngine:
    def __init__(self, verdict=None, warnings=()):
        self._verdict = verdict
        self._warnings = list(warnings)
        self.calls = []

    def run(self, symbol, tier2, dimensions):
        from src.tiered_analysis.risk import RiskResult

        self.calls.append(symbol)
        return RiskResult(verdict=self._verdict, warnings=self._warnings)


def _technicals_dim_with_levels():
    """Payload the base-level formulas can compute from.

    Bases: entry=96 (max(sma_20, swing_low) capped at close), backup=94,
    stop=90 (entry − 2×ATR), target=108 (entry + 2×(entry−stop)).
    """
    return DimensionResult(
        dimension="technicals",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
        payload={"close": 100.0, "sma_20": 96.0, "sma_60": 90.0,
                 "swing_low_20": 94.0, "atr_14": 3.0},
    )


def _buy_verdicts():
    from src.tiered_analysis.debate import DebateVerdict
    from src.tiered_analysis.risk import RiskVerdict

    debate = DebateVerdict(direction=Direction.BUY, final_score=7.4,
                           summary="bull case holds up", initial_score=7.5,
                           adjusted_score=7.4, pools={})
    risk = RiskVerdict(stance=Direction.BUY, size_multiplier=0.5,
                       stop_advice="keep", tightened_stop=None,
                       summary="half size")
    return debate, risk


class TestDepthRoutingAndSizing(unittest.TestCase):
    """v2 slice 6: depth 1|2|3 routing, sizing, and cost visibility."""

    def _run(self, depth=1, sizing_settings=None, sizing_overrides=None,
             debate_verdict=None, risk_verdict=None):
        from src.tiered_analysis.settings import SizingSettings
        from src.tiered_analysis.tiers import Tier2Stage, Tier3Stage

        logged = []

        def logger(report, trace_id=None):
            logged.append(report)
            return "log-result"

        debate_engine = _FakeDebateEngine(verdict=debate_verdict)
        risk_engine = _FakeRiskEngine(verdict=risk_verdict)
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider("technicals", _technicals_dim_with_levels())],
            analysis_runner=lambda symbol: _fake_analysis_result(),
            signal_logger=logger,
            level_adjuster=_FakeAdjuster(),
            depth=depth,
            sizing_settings=sizing_settings or SizingSettings(),
            sizing_overrides=sizing_overrides,
            tier2_stage=Tier2Stage(engine=debate_engine),
            tier3_stage=Tier3Stage(engine=risk_engine),
        )
        return outcome, logged, debate_engine, risk_engine

    def test_default_depth_is_tier1_only(self):
        outcome, logged, debate_engine, risk_engine = self._run()
        self.assertEqual(outcome.depth, 1)
        self.assertEqual(sorted(outcome.state.reports), [1])
        self.assertIs(outcome.final_report, outcome.report)
        self.assertEqual(debate_engine.calls, [])
        self.assertEqual(risk_engine.calls, [])
        self.assertEqual(logged[0].tier, 1)

    def test_depth_2_runs_debate_and_logs_tier2_direction(self):
        debate, _ = _buy_verdicts()
        outcome, logged, debate_engine, risk_engine = self._run(
            depth=2, debate_verdict=debate)
        self.assertEqual(sorted(outcome.state.reports), [1, 2])
        self.assertEqual(outcome.final_report.tier, 2)
        self.assertEqual(outcome.final_report.direction, Direction.BUY)
        self.assertEqual(debate_engine.calls, ["AAPL"])
        self.assertEqual(risk_engine.calls, [])
        # the ledger gets the deepest tier, with the evidence attached
        self.assertEqual(logged[0].tier, 2)
        self.assertTrue(logged[0].dimensions)

    def test_depth_3_runs_both_stages(self):
        debate, risk = _buy_verdicts()
        outcome, logged, _, risk_engine = self._run(
            depth=3, debate_verdict=debate, risk_verdict=risk)
        self.assertEqual(sorted(outcome.state.reports), [1, 2, 3])
        self.assertEqual(outcome.final_report.tier, 3)
        self.assertEqual(risk_engine.calls, ["AAPL"])
        self.assertEqual(logged[0].tier, 3)

    def test_invalid_depth_rejected(self):
        with self.assertRaises(ValueError):
            self._run(depth=4)
        with self.assertRaises(ValueError):
            self._run(depth=0)

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

    def test_tier3_multiplier_is_applied_by_code(self):
        from src.tiered_analysis.settings import SizingSettings

        debate, risk = _buy_verdicts()  # multiplier 0.5
        outcome, _, _, _ = self._run(
            depth=3, debate_verdict=debate, risk_verdict=risk,
            sizing_settings=SizingSettings(capital=100000.0,
                                           risk_fraction=0.01))
        self.assertEqual(outcome.sizing["shares_before_multiplier"], 166)
        self.assertEqual(outcome.sizing["shares"], 83)
        self.assertEqual(outcome.sizing["risk_multiplier"], 0.5)
        self.assertEqual(outcome.final_report.sizing.shares, 83.0)

    def test_multiplier_zero_keeps_explicit_zero_position(self):
        from dataclasses import replace as dc_replace

        from src.tiered_analysis.settings import SizingSettings

        debate, risk = _buy_verdicts()
        risk = dc_replace(risk, size_multiplier=0.0)
        outcome, _, _, _ = self._run(
            depth=3, debate_verdict=debate, risk_verdict=risk,
            sizing_settings=SizingSettings(capital=100000.0,
                                           risk_fraction=0.01))
        self.assertEqual(outcome.sizing["shares"], 0)
        self.assertTrue(any("do not open" in note
                            for note in outcome.sizing["notes"]))
        # 0 shares is a statement, not an omission — slots stay filled
        self.assertEqual(outcome.final_report.sizing.shares, 0.0)

    def test_hold_direction_refuses_sizing(self):
        from src.tiered_analysis.settings import SizingSettings

        result = _fake_analysis_result()
        result["decision_type"] = "hold"
        outcome = run_tiered_analysis(
            "AAPL",
            market=Market.US,
            providers=[_StubProvider("technicals",
                                     _technicals_dim_with_levels())],
            analysis_runner=lambda symbol: result,
            log_signal=False,
            level_adjuster=_FakeAdjuster(),
            sizing_settings=SizingSettings(capital=100000.0,
                                           risk_fraction=0.01),
        )
        self.assertEqual(outcome.sizing["reason_code"], "not_a_buy")
        self.assertTrue(outcome.final_report.sizing.is_empty)

    def test_per_run_overrides_enable_sizing(self):
        outcome, _, _, _ = self._run(
            sizing_overrides={"capital": 100000.0, "risk_fraction": 0.01})
        self.assertEqual(outcome.sizing["shares"], 166)

    def test_llm_usage_always_present_with_scope_note(self):
        outcome, _, _, _ = self._run(depth=3, debate_verdict=None,
                                     risk_verdict=None)
        self.assertEqual(outcome.llm_usage["total"]["calls"], 0)  # all fakes
        self.assertIn("tier-1", outcome.llm_usage["scope"])


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
