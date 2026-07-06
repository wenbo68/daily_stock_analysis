# -*- coding: utf-8 -*-
"""Offline tests for the US fundamentals provider (slice 3).

EDGAR/Yahoo responses are canned fixtures; the live-fetch sanity check is
in the network-marked test at the bottom.
"""
from __future__ import annotations

import unittest

import pytest

from src.tiered_analysis.providers.base import Coverage, Market, SourceKind
from src.tiered_analysis.providers.fundamentals_us import (
    FundamentalsUSProvider,
    extract_annual_series,
    metrics_from_facts,
)


def _fy_row(end: str, val: float, fy: int) -> dict:
    return {"end": end, "val": val, "fy": fy, "fp": "FY", "form": "10-K"}


def _q_row(end: str, val: float, fy: int) -> dict:
    return {"end": end, "val": val, "fy": fy, "fp": "Q3", "form": "10-Q"}


def _concept(rows: list, unit: str = "USD") -> dict:
    return {"units": {unit: rows}}


# Two clean fiscal years; derived metrics are hand-computable:
# revenue 100e9 -> 110e9 (+10%), net income 20e9 -> 24.2e9 (+21%),
# net margin 22%, gross margin 40%, operating margin 30%, ROE 40%,
# current ratio 2.0, debt/equity 2.0.
FAKE_FACTS = {
    "cik": 320193,
    "entityName": "TESTCO",
    "facts": {
        "us-gaap": {
            "Revenues": _concept([
                _fy_row("2023-09-30", 100e9, 2023),
                _fy_row("2024-09-30", 110e9, 2024),
                _q_row("2024-06-30", 30e9, 2024),  # must be ignored
            ]),
            "NetIncomeLoss": _concept([
                _fy_row("2023-09-30", 20e9, 2023),
                _fy_row("2024-09-30", 24.2e9, 2024),
            ]),
            "GrossProfit": _concept([_fy_row("2024-09-30", 44e9, 2024)]),
            "OperatingIncomeLoss": _concept([_fy_row("2024-09-30", 33e9, 2024)]),
            "StockholdersEquity": _concept([_fy_row("2024-09-30", 60.5e9, 2024)]),
            "Liabilities": _concept([_fy_row("2024-09-30", 121e9, 2024)]),
            "AssetsCurrent": _concept([_fy_row("2024-09-30", 50e9, 2024)]),
            "LiabilitiesCurrent": _concept([_fy_row("2024-09-30", 25e9, 2024)]),
            "CashAndCashEquivalentsAtCarryingValue": _concept(
                [_fy_row("2024-09-30", 30e9, 2024)]
            ),
            "EarningsPerShareDiluted": _concept(
                [
                    _fy_row("2023-09-30", 1.0, 2023),
                    _fy_row("2024-09-30", 1.21, 2024),
                ],
                unit="USD/shares",
            ),
        }
    },
}

FAKE_YAHOO_INFO = {
    "trailingPE": 28.5,
    "forwardPE": 25.0,
    "priceToBook": 45.2,
    "priceToSalesTrailing12Months": 8.8,
    "marketCap": 3.4e12,
}


class TestExtractAnnualSeries(unittest.TestCase):
    def test_only_10k_fy_rows_survive(self):
        series = extract_annual_series(FAKE_FACTS, "Revenues")
        self.assertEqual(series, {"2023-09-30": 100e9, "2024-09-30": 110e9})

    def test_missing_concept_returns_empty(self):
        self.assertEqual(extract_annual_series(FAKE_FACTS, "NoSuchConcept"), {})

    def test_later_restatement_overrides_earlier_row(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": _concept([
                        _fy_row("2024-09-30", 1.0, 2024),
                        _fy_row("2024-09-30", 2.0, 2025),  # restated later
                    ])
                }
            }
        }
        self.assertEqual(extract_annual_series(facts, "Revenues"), {"2024-09-30": 2.0})


class TestMetricsFromFacts(unittest.TestCase):
    def setUp(self):
        self.metrics = metrics_from_facts(FAKE_FACTS)

    def test_growth(self):
        growth = self.metrics["growth"]
        self.assertAlmostEqual(growth["revenue_yoy_pct"], 10.0)
        self.assertAlmostEqual(growth["net_income_yoy_pct"], 21.0)
        self.assertAlmostEqual(growth["eps_yoy_pct"], 21.0)

    def test_profitability(self):
        prof = self.metrics["profitability"]
        self.assertAlmostEqual(prof["net_margin_pct"], 22.0)
        self.assertAlmostEqual(prof["gross_margin_pct"], 40.0)
        self.assertAlmostEqual(prof["operating_margin_pct"], 30.0)
        self.assertAlmostEqual(prof["roe_pct"], 40.0)

    def test_balance_sheet(self):
        bs = self.metrics["balance_sheet"]
        self.assertAlmostEqual(bs["current_ratio"], 2.0)
        self.assertAlmostEqual(bs["debt_to_equity"], 2.0)
        self.assertAlmostEqual(bs["cash"], 30e9)

    def test_meta_carries_fiscal_period(self):
        self.assertEqual(self.metrics["meta"]["period_end"], "2024-09-30")

    def test_revenue_alias_used_when_revenues_missing(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": _concept([
                        _fy_row("2023-09-30", 50e9, 2023),
                        _fy_row("2024-09-30", 55e9, 2024),
                    ]),
                    "NetIncomeLoss": _concept([
                        _fy_row("2024-09-30", 11e9, 2024),
                    ]),
                }
            }
        }
        metrics = metrics_from_facts(facts)
        self.assertAlmostEqual(metrics["growth"]["revenue_yoy_pct"], 10.0)
        self.assertAlmostEqual(metrics["profitability"]["net_margin_pct"], 20.0)

    def test_stale_revenues_concept_loses_to_fresher_alias(self):
        # AAPL regression: the plain "Revenues" tag died in 2018; the fresher
        # RevenueFromContractWithCustomer... alias must win, and all ratios
        # must be computed on the fresh period, not the stale one.
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": _concept([
                        _fy_row("2017-09-30", 60e9, 2017),
                        _fy_row("2018-09-29", 66e9, 2018),
                    ]),
                    "RevenueFromContractWithCustomerExcludingAssessedTax": _concept([
                        _fy_row("2023-09-30", 100e9, 2023),
                        _fy_row("2024-09-30", 110e9, 2024),
                    ]),
                    "NetIncomeLoss": _concept([
                        _fy_row("2024-09-30", 24.2e9, 2024),
                    ]),
                }
            }
        }
        metrics = metrics_from_facts(facts)
        self.assertEqual(metrics["meta"]["period_end"], "2024-09-30")
        self.assertAlmostEqual(metrics["growth"]["revenue_yoy_pct"], 10.0)
        self.assertAlmostEqual(metrics["profitability"]["net_margin_pct"], 22.0)

    def test_no_cross_period_ratios(self):
        # Gross profit only exists for FY2023; revenue's latest is FY2024.
        # Mixing periods would fabricate a margin — must be None instead.
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": _concept([
                        _fy_row("2023-09-30", 100e9, 2023),
                        _fy_row("2024-09-30", 110e9, 2024),
                    ]),
                    "GrossProfit": _concept([_fy_row("2023-09-30", 40e9, 2023)]),
                    "NetIncomeLoss": _concept([_fy_row("2024-09-30", 24.2e9, 2024)]),
                }
            }
        }
        metrics = metrics_from_facts(facts)
        self.assertIsNone(metrics["profitability"]["gross_margin_pct"])
        self.assertAlmostEqual(metrics["profitability"]["net_margin_pct"], 22.0)

    def test_single_year_yields_no_growth_but_margins_survive(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": _concept([_fy_row("2024-09-30", 100e9, 2024)]),
                    "NetIncomeLoss": _concept([_fy_row("2024-09-30", 25e9, 2024)]),
                }
            }
        }
        metrics = metrics_from_facts(facts)
        self.assertIsNone(metrics["growth"]["revenue_yoy_pct"])
        self.assertAlmostEqual(metrics["profitability"]["net_margin_pct"], 25.0)


class TestFundamentalsUSProvider(unittest.TestCase):
    def _provider(self, facts_loader=None, valuation_loader=None):
        return FundamentalsUSProvider(
            facts_loader=facts_loader or (lambda symbol: FAKE_FACTS),
            valuation_loader=valuation_loader or (lambda symbol: FAKE_YAHOO_INFO),
        )

    def test_supports_us_only(self):
        provider = self._provider()
        self.assertTrue(provider.supports(Market.US))
        for market in (Market.CN, Market.HK, Market.JP, Market.KR, Market.TW):
            self.assertFalse(provider.supports(market))

    def test_full_coverage_with_both_sources(self):
        result = self._provider().collect("AAPL")
        self.assertEqual(result.kind, SourceKind.NUMERIC)
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertTrue(result.is_actionable)
        payload = result.payload
        self.assertAlmostEqual(payload["valuation"]["pe_ttm"], 28.5)
        self.assertAlmostEqual(payload["valuation"]["market_cap"], 3.4e12)
        self.assertAlmostEqual(payload["growth"]["revenue_yoy_pct"], 10.0)
        self.assertAlmostEqual(payload["profitability"]["roe_pct"], 40.0)
        self.assertAlmostEqual(payload["balance_sheet"]["current_ratio"], 2.0)

    def test_edgar_citation_carries_companyfacts_url(self):
        result = self._provider().collect("AAPL")
        urls = [c.url for c in result.citations if c.url]
        self.assertTrue(
            any("data.sec.gov/api/xbrl/companyfacts/CIK0000320193" in u for u in urls)
        )

    def test_edgar_down_degrades_to_partial_with_warning(self):
        def _edgar_boom(symbol):
            raise RuntimeError("SEC rate limited")

        result = self._provider(facts_loader=_edgar_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertTrue(result.is_actionable)  # valuation still present
        self.assertIsNone(result.payload.get("growth"))
        self.assertTrue(any("SEC rate limited" in w for w in result.warnings))

    def test_yahoo_down_degrades_to_partial_with_warning(self):
        def _yahoo_boom(symbol):
            raise RuntimeError("yahoo unavailable")

        result = self._provider(valuation_loader=_yahoo_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertIsNone(result.payload.get("valuation"))
        self.assertAlmostEqual(result.payload["growth"]["revenue_yoy_pct"], 10.0)
        self.assertTrue(any("yahoo unavailable" in w for w in result.warnings))

    def test_both_down_is_unavailable_not_silent(self):
        def _boom(symbol):
            raise RuntimeError("down")

        result = self._provider(facts_loader=_boom, valuation_loader=_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertFalse(result.is_actionable)
        self.assertEqual(len(result.warnings), 2)

    def test_empty_yahoo_info_counts_as_missing_not_full(self):
        # Design doc §2.2: ok-but-empty responses are the silent-blank trap.
        result = self._provider(valuation_loader=lambda symbol: {}).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertIsNone(result.payload.get("valuation"))


class TestRegistryIncludesFundamentals(unittest.TestCase):
    def test_fundamentals_routed_for_us_only(self):
        from src.tiered_analysis.providers.registry import get_providers

        us_dimensions = [p.dimension for p in get_providers(Market.US)]
        cn_dimensions = [p.dimension for p in get_providers(Market.CN)]
        self.assertIn("fundamentals", us_dimensions)
        self.assertNotIn("fundamentals", cn_dimensions)


@pytest.mark.network
class TestLiveEdgarSanity(unittest.TestCase):
    """Live sanity check that real AAPL data is what we expect."""

    def test_aapl_fundamentals_are_plausible(self):
        from datetime import datetime

        provider = FundamentalsUSProvider()
        result = provider.collect("AAPL")
        self.assertIn(result.coverage, (Coverage.FULL, Coverage.PARTIAL))
        payload = result.payload
        growth = payload.get("growth") or {}
        prof = payload.get("profitability") or {}
        meta = payload.get("meta") or {}
        # Data must be from a recent fiscal year, not a dead XBRL tag's era.
        period_end = str(meta.get("period_end") or "1900")
        self.assertGreaterEqual(int(period_end[:4]), datetime.now().year - 2)
        # Apple: net margin in the 15-40% band; a cross-period mixup breaks this.
        self.assertGreater(prof.get("net_margin_pct") or 0, 15.0)
        self.assertLess(prof.get("net_margin_pct") or 100, 40.0)
        self.assertIsNotNone(growth.get("revenue_yoy_pct"))


if __name__ == "__main__":
    unittest.main()
