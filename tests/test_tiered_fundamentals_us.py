# -*- coding: utf-8 -*-
"""Offline tests for the US fundamentals provider (v2 envelope payload).

EDGAR/Yahoo responses are canned fixtures; the live-fetch sanity check is
in the network-marked test at the bottom.
"""
from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

import pytest

from src.tiered_analysis.providers.base import Coverage, Market, SourceKind
from src.tiered_analysis.providers.edgar_series import (
    extract_annual_series,
    extract_quarterly_series,
    ttm_value,
)
from src.tiered_analysis.providers.fundamentals_us import (
    OPERATING_CASH_FLOW_CONCEPTS,
    FundamentalsUSProvider,
    fcf_metrics,
    growth_trend_label,
    quarterly_growth_metrics,
    reaction_metrics,
    revision_pct,
    surprise_metrics,
)
from src.tiered_analysis.providers.technicals import is_envelope, metric_value

TODAY = date(2025, 7, 1)


def _fy_row(end: str, val: float, fy: int, start: str = None) -> dict:
    row = {"end": end, "val": val, "fy": fy, "fp": "FY", "form": "10-K"}
    if start:
        row["start"] = start
    return row


def _q_row(start: str, end: str, val: float, form: str = "10-Q") -> dict:
    return {"start": start, "end": end, "val": val, "fp": "Q3", "form": form}


def _concept(rows: list, unit: str = "USD") -> dict:
    return {"units": {unit: rows}}


# Hand-computable fixture:
# - annual FY2024: revenue 110e9, gross 44e9 (40%), operating 33e9 (30%),
#   net income 24.2e9, equity 60.5e9 (ROE 40%), current ratio 2.0, D/E 2.0
# - quarterly revenue: latest 30e9 vs 25e9 a year ago (+20%); prior quarter
#   28e9 vs 25e9 (+12%) -> accelerating (+8pp)
# - quarterly EPS: 1.10 vs 1.00 (+10%); prior 1.045 vs 0.95 (+10%) -> steady
# - cash flow TTM: OCF 100+90-80=110e9, capex 10+9-8=11e9 -> FCF 99e9 (ttm)
FAKE_FACTS = {
    "cik": 320193,
    "entityName": "TESTCO",
    "facts": {
        "us-gaap": {
            "Revenues": _concept([
                _fy_row("2023-09-30", 100e9, 2023),
                _fy_row("2024-09-30", 110e9, 2024),
                _q_row("2023-10-01", "2023-12-30", 24e9),
                _q_row("2023-12-31", "2024-03-30", 25e9),
                _q_row("2024-03-31", "2024-06-29", 25e9),
                _q_row("2024-09-29", "2024-12-28", 27e9),
                _q_row("2024-12-29", "2025-03-29", 28e9),
                _q_row("2025-03-30", "2025-06-28", 30e9),
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
            "EarningsPerShareDiluted": _concept(
                [
                    _fy_row("2023-09-30", 1.0, 2023),
                    _fy_row("2024-09-30", 1.21, 2024),
                    _q_row("2023-12-31", "2024-03-30", 0.95),
                    _q_row("2024-03-31", "2024-06-29", 1.0),
                    _q_row("2024-12-29", "2025-03-29", 1.045),
                    _q_row("2025-03-30", "2025-06-28", 1.10),
                ],
                unit="USD/shares",
            ),
            "NetCashProvidedByUsedInOperatingActivities": _concept([
                _fy_row("2024-09-30", 100e9, 2024, start="2023-10-01"),
                _q_row("2023-10-01", "2024-06-29", 80e9),
                _q_row("2024-10-01", "2025-06-28", 90e9),
            ]),
            "PaymentsToAcquirePropertyPlantAndEquipment": _concept([
                _fy_row("2024-09-30", 10e9, 2024, start="2023-10-01"),
                _q_row("2023-10-01", "2024-06-29", 8e9),
                _q_row("2024-10-01", "2025-06-28", 9e9),
            ]),
        }
    },
}

FAKE_INFO = {
    "trailingPE": 28.5,
    "forwardPE": 25.0,
    "priceToSalesTrailing12Months": 8.8,
    "marketCap": 3.4e12,
    "sector": "Technology",
    "industry": "Consumer Electronics",
    # 2025-08-10 UTC — after the fixture's "today" (2025-07-01).
    "exDividendDate": 1754784000,
}

FAKE_EARNINGS_ROWS = [
    {"date": "2025-07-20", "eps_estimate": 1.20, "eps_actual": None, "surprise_pct": None},
    {"date": "2025-04-25", "eps_estimate": 1.00, "eps_actual": 1.10, "surprise_pct": 10.0},
    {"date": "2025-01-25", "eps_estimate": 1.00, "eps_actual": 0.95, "surprise_pct": -5.0},
    # surprise_pct absent -> computed from actual/estimate (+5%)
    {"date": "2024-10-25", "eps_estimate": 1.00, "eps_actual": 1.05, "surprise_pct": None},
    {"date": "2024-07-25", "eps_estimate": 1.00, "eps_actual": 1.00, "surprise_pct": 0.0},
]

FAKE_EPS_TREND = {"current": 1.20, "days_ago_90": 1.00}

FAKE_EARNINGS_FIELDS = {"next_earnings_date": "2025-07-20", "days_until_earnings": 19}


def _bar(day: str, close: float) -> SimpleNamespace:
    return SimpleNamespace(date=day, close=close)


# Around 2025-04-25: 100 -> 108 (+8%); around 2025-01-25: 100 -> 94 (-6%).
FAKE_BARS = [
    _bar("2025-01-24", 100.0),
    _bar("2025-01-27", 94.0),
    _bar("2025-04-25", 100.0),
    _bar("2025-04-28", 108.0),
]


def _provider(**overrides) -> FundamentalsUSProvider:
    kwargs = dict(
        facts_loader=lambda symbol: FAKE_FACTS,
        info_loader=lambda symbol: FAKE_INFO,
        earnings_lookup=lambda symbol: FAKE_EARNINGS_FIELDS,
        earnings_history_loader=lambda symbol: FAKE_EARNINGS_ROWS,
        eps_trend_loader=lambda symbol: FAKE_EPS_TREND,
        bars_loader=lambda symbol: FAKE_BARS,
        today=lambda: TODAY,
    )
    kwargs.update(overrides)
    return FundamentalsUSProvider(**kwargs)


class TestEdgarSeries(unittest.TestCase):
    def test_only_10k_fy_rows_survive_annual(self):
        series = extract_annual_series(FAKE_FACTS, "Revenues")
        self.assertEqual(series, {"2023-09-30": 100e9, "2024-09-30": 110e9})

    def test_quarterly_rows_are_quarter_spans_only(self):
        series = extract_quarterly_series(FAKE_FACTS, "Revenues")
        self.assertIn("2025-06-28", series)
        self.assertNotIn("2024-09-30", series)  # FY row has no ~90d span

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

    def test_ttm_value_combines_fy_and_ytd(self):
        value, end, basis = ttm_value(FAKE_FACTS, OPERATING_CASH_FLOW_CONCEPTS)
        self.assertAlmostEqual(value, 110e9)
        self.assertEqual(end, "2025-06-28")
        self.assertEqual(basis, "ttm")

    def test_ttm_falls_back_to_annual_without_ytd_rows(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "NetCashProvidedByUsedInOperatingActivities": _concept(
                        [_fy_row("2024-09-30", 100e9, 2024, start="2023-10-01")]
                    ),
                }
            }
        }
        value, end, basis = ttm_value(facts, OPERATING_CASH_FLOW_CONCEPTS)
        self.assertAlmostEqual(value, 100e9)
        self.assertEqual(basis, "annual")


class TestQuarterlyGrowth(unittest.TestCase):
    def test_revenue_yoy_and_acceleration(self):
        growth = quarterly_growth_metrics(FAKE_FACTS)
        self.assertAlmostEqual(growth["revenue"]["yoy"], 20.0)
        self.assertAlmostEqual(growth["revenue"]["yoy_prior"], 12.0)
        self.assertEqual(growth["revenue"]["trend"], "accelerating")
        self.assertEqual(growth["revenue"]["end"], "2025-06-28")

    def test_eps_yoy_steady_inside_dead_band(self):
        growth = quarterly_growth_metrics(FAKE_FACTS)
        self.assertAlmostEqual(growth["eps"]["yoy"], 10.0)
        self.assertEqual(growth["eps"]["trend"], "steady")

    def test_trend_label_dead_band(self):
        self.assertEqual(growth_trend_label(10.0, 7.0), "accelerating")
        self.assertEqual(growth_trend_label(10.0, 13.0), "slowing")
        self.assertEqual(growth_trend_label(10.0, 9.0), "steady")
        self.assertIsNone(growth_trend_label(None, 9.0))

    def test_missing_year_ago_quarter_yields_none(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenues": _concept([
                        _q_row("2025-03-30", "2025-06-28", 30e9),
                    ])
                }
            }
        }
        growth = quarterly_growth_metrics(facts)
        self.assertIsNone(growth["revenue"]["yoy"])
        self.assertIsNone(growth["revenue"]["trend"])


class TestFcf(unittest.TestCase):
    def test_ttm_fcf(self):
        fcf = fcf_metrics(FAKE_FACTS)
        self.assertAlmostEqual(fcf["fcf"], 99e9)
        self.assertEqual(fcf["basis"], "ttm")
        self.assertAlmostEqual(fcf["operating_cash_flow"], 110e9)
        self.assertAlmostEqual(fcf["capital_spending"], 11e9)

    def test_missing_capex_yields_none(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "NetCashProvidedByUsedInOperatingActivities": _concept(
                        [_fy_row("2024-09-30", 100e9, 2024, start="2023-10-01")]
                    ),
                }
            }
        }
        self.assertIsNone(fcf_metrics(facts))


class TestSurpriseAndReaction(unittest.TestCase):
    def test_beats_and_average_surprise(self):
        metrics = surprise_metrics(FAKE_EARNINGS_ROWS, TODAY)
        self.assertEqual(metrics["beats"], "3/4")
        self.assertAlmostEqual(metrics["avg_surprise_pct"], 2.5)
        # future row (no actual yet) excluded from the report dates
        self.assertNotIn(date(2025, 7, 20), metrics["report_dates"])

    def test_reaction_moves_and_worst(self):
        report_dates = [date(2025, 4, 25), date(2025, 1, 25)]
        metrics = reaction_metrics(FAKE_BARS, report_dates)
        self.assertAlmostEqual(metrics["avg_abs_pct"], 7.0)
        self.assertAlmostEqual(metrics["worst_pct"], -6.0)

    def test_reaction_needs_two_reports(self):
        metrics = reaction_metrics(FAKE_BARS, [date(2025, 4, 25)])
        self.assertIsNone(metrics["avg_abs_pct"])
        self.assertIsNone(metrics["worst_pct"])

    def test_revision_pct_and_zero_base_guard(self):
        self.assertAlmostEqual(revision_pct(FAKE_EPS_TREND), 20.0)
        self.assertIsNone(revision_pct({"current": 0.5, "days_ago_90": 0.0}))


class TestFundamentalsUSProvider(unittest.TestCase):
    def test_supports_us_only(self):
        provider = _provider()
        self.assertTrue(provider.supports(Market.US))
        for market in (Market.CN, Market.HK, Market.JP, Market.KR, Market.TW):
            self.assertFalse(provider.supports(market))

    def test_full_coverage_envelope_payload(self):
        result = _provider().collect("AAPL")
        self.assertEqual(result.kind, SourceKind.NUMERIC)
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertTrue(result.is_actionable)
        payload = result.payload

        for group, key, expected in (
            ("profile", "sector", "Technology"),
            ("earnings", "next_earnings_date", "2025-07-20"),
            ("earnings", "beats_4q", "3/4"),
            ("earnings", "avg_surprise_pct_4q", 2.5),
            ("earnings", "reaction_avg_abs_pct", 7.0),
            ("earnings", "reaction_worst_pct", -6.0),
            ("earnings", "eps_rev_90d_pct", 20.0),
            ("earnings", "ex_dividend_date", "2025-08-10"),
            ("growth", "revenue_yoy_q", 20.0),
            ("growth", "revenue_growth_trend", "accelerating"),
            ("growth", "eps_yoy_q", 10.0),
            ("growth", "eps_growth_trend", "steady"),
            ("profitability", "gross_margin_pct", 40.0),
            ("profitability", "operating_margin_pct", 30.0),
            ("profitability", "roe_pct", 40.0),
            ("profitability", "fcf", 99e9),
            ("balance_sheet", "current_ratio", 2.0),
            ("balance_sheet", "debt_to_equity", 2.0),
            ("valuation", "pe_ttm", 28.5),
            ("valuation", "market_cap", 3.4e12),
            ("meta", "period_end", "2024-09-30"),
            ("meta", "period_end_q", "2025-06-28"),
        ):
            node = payload[group][key]
            self.assertTrue(is_envelope(node), f"{group}.{key} not an envelope")
            self.assertEqual(metric_value(node), expected, f"{group}.{key}")
            self.assertIn("interpretation", node, f"{group}.{key}")

    def test_retired_fields_are_gone(self):
        payload = _provider().collect("AAPL").payload
        self.assertNotIn("net_margin_pct", payload["profitability"])
        self.assertNotIn("cash", payload["balance_sheet"])
        self.assertNotIn("pb", payload["valuation"])
        self.assertNotIn("revenue_yoy_pct", payload["growth"])

    def test_formula_receipts_for_computed_metrics(self):
        result = _provider().collect("AAPL")
        formulas = result.formulas
        self.assertAlmostEqual(
            formulas["growth.revenue_yoy_q"]["inputs"]["revenue_q"], 30e9
        )
        self.assertEqual(
            [b["label"] for b in formulas["growth.revenue_growth_trend"]["branches"]],
            ["accelerating", "slowing", "steady"],
        )
        self.assertAlmostEqual(
            formulas["profitability.fcf"]["inputs"]["operating_cash_flow"], 110e9
        )
        self.assertIn("balance_sheet.current_ratio", formulas)
        self.assertIn("earnings.days_until_earnings", formulas)

    def test_past_ex_dividend_date_is_filtered(self):
        provider = _provider(today=lambda: date(2025, 9, 1))
        payload = provider.collect("AAPL").payload
        self.assertIsNone(metric_value(payload["earnings"]["ex_dividend_date"]))

    def test_edgar_down_degrades_to_partial_with_warning(self):
        def _edgar_boom(symbol):
            raise RuntimeError("SEC rate limited")

        result = _provider(facts_loader=_edgar_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertTrue(result.is_actionable)  # valuation still present
        self.assertIsNone(metric_value(result.payload["growth"]["revenue_yoy_q"]))
        self.assertTrue(any("SEC rate limited" in w for w in result.warnings))

    def test_yahoo_down_degrades_to_partial_with_warning(self):
        def _yahoo_boom(symbol):
            raise RuntimeError("yahoo unavailable")

        result = _provider(info_loader=_yahoo_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertIsNone(metric_value(result.payload["valuation"]["pe_ttm"]))
        self.assertAlmostEqual(
            metric_value(result.payload["growth"]["revenue_yoy_q"]), 20.0
        )
        self.assertTrue(any("yahoo unavailable" in w for w in result.warnings))

    def test_both_down_is_unavailable_not_silent(self):
        def _boom(symbol):
            raise RuntimeError("down")

        result = _provider(facts_loader=_boom, info_loader=_boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertFalse(result.is_actionable)

    def test_empty_yahoo_info_counts_as_missing_not_full(self):
        # Design doc §2.2: ok-but-empty responses are the silent-blank trap.
        result = _provider(info_loader=lambda symbol: {}).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertTrue(
            any("no valuation ratios" in w for w in result.warnings)
        )

    def test_auxiliary_failures_never_degrade_coverage(self):
        def _boom(symbol):
            raise RuntimeError("aux down")

        result = _provider(
            earnings_lookup=_boom,
            earnings_history_loader=_boom,
            eps_trend_loader=_boom,
        ).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertIsNone(
            metric_value(result.payload["earnings"]["next_earnings_date"])
        )
        self.assertTrue(any("aux down" in w for w in result.warnings))

    def test_edgar_citation_carries_companyfacts_url(self):
        result = _provider().collect("AAPL")
        urls = [c.url for c in result.citations if c.url]
        self.assertTrue(
            any("data.sec.gov/api/xbrl/companyfacts/CIK0000320193" in u for u in urls)
        )


class TestEarningsFromDimensions(unittest.TestCase):
    def test_reads_v2_nested_envelopes(self):
        from src.tiered_analysis.earnings import earnings_from_dimensions

        result = _provider().collect("AAPL")
        info = earnings_from_dimensions([result])
        self.assertEqual(info.next_date, "2025-07-20")
        self.assertEqual(info.days_until, 19)

    def test_reads_v1_flat_payload(self):
        from src.tiered_analysis.earnings import earnings_from_dimensions

        legacy = SimpleNamespace(
            dimension="fundamentals",
            payload={"next_earnings_date": "2025-08-01", "days_until_earnings": 3},
        )
        info = earnings_from_dimensions([legacy])
        self.assertEqual(info.next_date, "2025-08-01")
        self.assertEqual(info.days_until, 3)


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
        meta = payload.get("meta") or {}
        # Data must be from a recent fiscal year, not a dead XBRL tag's era.
        period_end = str(metric_value(meta.get("period_end")) or "1900")
        self.assertGreaterEqual(int(period_end[:4]), datetime.now().year - 2)
        # Apple: operating margin in the 20-45% band; a cross-period mixup
        # breaks this.
        operating = metric_value(payload["profitability"]["operating_margin_pct"])
        self.assertGreater(operating or 0, 20.0)
        self.assertLess(operating or 100, 45.0)
        self.assertIsNotNone(
            metric_value(payload["growth"]["revenue_yoy_q"])
        )


if __name__ == "__main__":
    unittest.main()
