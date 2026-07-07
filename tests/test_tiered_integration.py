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
