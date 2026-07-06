# -*- coding: utf-8 -*-
"""Offline tests for the macro-economic provider (slice 4).

FRED responses are canned observation lists; caching uses temp dirs. The
live check is the network-marked test at the bottom (needs FRED_API_KEY).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pytest

from src.tiered_analysis.providers.base import Coverage, Market, SourceKind
from src.tiered_analysis.providers.macro_econ import (
    MacroConfigError,
    MacroEconProvider,
    SERIES_SPECS,
    cpi_yoy_pct,
)

# 13 monthly CPI observations: latest 320.0 vs year-ago 310.0 -> +3.2258%.
CPI_OBS = [(f"2025-{m:02d}-01", 310.0 + m * 0.5) for m in range(7, 13)]
CPI_OBS += [(f"2026-{m:02d}-01", 313.5 + m * 0.5) for m in range(1, 6)]
CPI_OBS += [("2026-06-01", 320.0)]
CPI_OBS[0] = ("2025-06-01", 310.0)

DAILY_VALUES = {
    "FEDFUNDS": 4.33,
    "DGS10": 4.40,
    "DGS2": 4.00,
    "T10Y2Y": 0.40,
    "UNRATE": 4.10,
    "VIXCLS": 17.50,
    "DCOILWTICO": 68.20,
    "DTWEXBGS": 121.00,
}


def _fake_fetcher(calls=None):
    def fetch(series_id):
        if calls is not None:
            calls.append(series_id)
        if series_id == "CPIAUCSL":
            return list(CPI_OBS)
        if series_id in DAILY_VALUES:
            return [("2026-07-03", DAILY_VALUES[series_id])]
        raise KeyError(series_id)

    return fetch


class TestCpiYoy(unittest.TestCase):
    def test_yoy_from_monthly_index(self):
        self.assertAlmostEqual(cpi_yoy_pct(CPI_OBS), (320.0 / 310.0 - 1) * 100.0)

    def test_missing_year_ago_month_returns_none(self):
        self.assertIsNone(cpi_yoy_pct([("2026-06-01", 320.0)]))

    def test_empty_returns_none(self):
        self.assertIsNone(cpi_yoy_pct([]))


class TestMacroEconProvider(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _provider(self, fetcher=None, today=None):
        return MacroEconProvider(
            series_fetcher=fetcher or _fake_fetcher(),
            cache_dir=self.cache_dir,
            today=today or (lambda: date(2026, 7, 7)),
        )

    def test_supports_every_market(self):
        provider = self._provider()
        for market in Market:
            self.assertTrue(provider.supports(market))

    def test_full_payload(self):
        result = self._provider().collect("AAPL")
        self.assertEqual(result.kind, SourceKind.NUMERIC)
        self.assertEqual(result.coverage, Coverage.FULL)
        payload = result.payload
        self.assertEqual(payload["region"], "us")
        self.assertAlmostEqual(payload["rates"]["fed_funds_rate_pct"], 4.33)
        self.assertAlmostEqual(payload["rates"]["curve_10y_2y_pct"], 0.40)
        self.assertAlmostEqual(
            payload["inflation"]["cpi_yoy_pct"], (320.0 / 310.0 - 1) * 100.0
        )
        self.assertAlmostEqual(payload["labor"]["unemployment_rate_pct"], 4.10)
        self.assertAlmostEqual(payload["markets"]["vix"], 17.50)
        self.assertEqual(payload["observation_dates"]["vix"], "2026-07-03")
        self.assertTrue(result.citations)

    def test_one_series_failing_is_partial_with_warning(self):
        base = _fake_fetcher()

        def flaky(series_id):
            if series_id == "VIXCLS":
                raise RuntimeError("FRED 500")
            return base(series_id)

        result = self._provider(fetcher=flaky).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertIsNone(result.payload["markets"]["vix"])
        self.assertTrue(any("VIXCLS" in w for w in result.warnings))

    def test_all_series_failing_is_unavailable(self):
        def broken(series_id):
            raise RuntimeError("network down")

        result = self._provider(fetcher=broken).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertFalse(result.is_actionable)
        self.assertFalse(list(self.cache_dir.iterdir()))  # failures not cached

    def test_missing_api_key_aborts_with_single_clear_warning(self):
        def unconfigured(series_id):
            raise MacroConfigError("FRED_API_KEY is not set")

        result = self._provider(fetcher=unconfigured).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("FRED_API_KEY", result.warnings[0])

    def test_cached_once_per_day_never_per_ticker(self):
        calls = []
        provider = self._provider(fetcher=_fake_fetcher(calls))
        first = provider.collect("AAPL")
        second = provider.collect("600519")  # different ticker, same day
        self.assertEqual(len(calls), len(SERIES_SPECS))  # one fetch round only
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(second.coverage, Coverage.FULL)

    def test_cache_is_per_day(self):
        calls = []
        fetcher = _fake_fetcher(calls)
        day = [date(2026, 7, 7)]
        provider = self._provider(fetcher=fetcher, today=lambda: day[0])
        provider.collect("AAPL")
        day[0] = date(2026, 7, 8)
        provider.collect("AAPL")
        self.assertEqual(len(calls), 2 * len(SERIES_SPECS))

    def test_cache_survives_new_provider_instance(self):
        calls = []
        self._provider(fetcher=_fake_fetcher(calls)).collect("AAPL")
        fresh = self._provider(fetcher=_fake_fetcher(calls))
        result = fresh.collect("MSFT")
        self.assertEqual(len(calls), len(SERIES_SPECS))
        self.assertEqual(result.coverage, Coverage.FULL)

    def test_corrupt_cache_file_triggers_refetch(self):
        calls = []
        provider = self._provider(fetcher=_fake_fetcher(calls))
        provider.collect("AAPL")
        cache_file = next(self.cache_dir.iterdir())
        cache_file.write_text("{not json", encoding="utf-8")
        fresh = self._provider(fetcher=_fake_fetcher(calls))
        result = fresh.collect("AAPL")
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertEqual(len(calls), 2 * len(SERIES_SPECS))

    def test_partial_results_are_cached_too(self):
        base = _fake_fetcher()

        def flaky(series_id):
            if series_id == "VIXCLS":
                raise RuntimeError("FRED 500")
            return base(series_id)

        calls = []

        def counting_flaky(series_id):
            calls.append(series_id)
            return flaky(series_id)

        provider = self._provider(fetcher=counting_flaky)
        provider.collect("AAPL")
        second = provider.collect("AAPL")
        self.assertEqual(len(calls), len(SERIES_SPECS))
        self.assertEqual(second.coverage, Coverage.PARTIAL)
        self.assertTrue(any("VIXCLS" in w for w in second.warnings))


class TestRegistryIncludesMacro(unittest.TestCase):
    def test_macro_routed_for_all_markets(self):
        from src.tiered_analysis.providers.registry import get_providers

        for market in (Market.US, Market.CN, Market.KR):
            dimensions = [p.dimension for p in get_providers(market)]
            self.assertIn("macro_econ", dimensions)


@pytest.mark.network
@pytest.mark.skipif(not os.getenv("FRED_API_KEY"), reason="FRED_API_KEY not set")
class TestLiveFredSanity(unittest.TestCase):
    def test_live_us_macro_is_plausible(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = MacroEconProvider(cache_dir=Path(tmp))
            result = provider.collect("AAPL")
        self.assertIn(result.coverage, (Coverage.FULL, Coverage.PARTIAL))
        rates = result.payload["rates"]
        self.assertGreater(rates["treasury_10y_pct"] or 0, 0.5)
        self.assertLess(rates["treasury_10y_pct"] or 99, 15.0)
        inflation = result.payload["inflation"]["cpi_yoy_pct"]
        self.assertIsNotNone(inflation)
        self.assertGreater(inflation, -5.0)
        self.assertLess(inflation, 15.0)


if __name__ == "__main__":
    unittest.main()
