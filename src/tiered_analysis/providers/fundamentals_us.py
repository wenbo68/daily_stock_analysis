# -*- coding: utf-8 -*-
"""US fundamentals provider (docs/tiered-analysis-design.md §2.2).

Two deterministic sources, split by what each can actually answer:

- **SEC EDGAR companyfacts (XBRL)** — audited annual statements. Produces
  growth (revenue / net income / EPS YoY), profitability (margins, ROE) and
  balance-sheet health (current ratio, debt-to-equity, cash). Concept names
  follow Vibe-Trading's proven list (financial_statements_tool.py).
- **Yahoo summary** — market-priced valuation ratios that filings cannot
  provide (P/E, P/S, P/B, market cap).

Either source failing degrades coverage explicitly (partial/unavailable
with warnings) — an ok-but-empty response is treated as missing, never as
a silent blank.

SEC requires a descriptive User-Agent with contact info: set
``SEC_EDGAR_USER_AGENT`` in the environment (see .env.example).
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .base import (
    Citation,
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)

REVENUE_CONCEPTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
)
EPS_CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")

EDGAR_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

#: The Yahoo Finance page showing the cited valuation ratios: yfinance
#: itself has no per-request page, but the same figures are published on
#: the key-statistics subpage — cited so readers can verify at the source.
YAHOO_KEY_STATISTICS_URL = "https://finance.yahoo.com/quote/{symbol}/key-statistics"
EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_EDGAR_TIMEOUT_SECONDS = 15

# Yahoo .info key -> normalized valuation field.
_VALUATION_KEYS = (
    ("trailingPE", "pe_ttm"),
    ("forwardPE", "pe_forward"),
    ("priceToSalesTrailing12Months", "ps_ttm"),
    ("priceToBook", "pb"),
    ("marketCap", "market_cap"),
)


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _pick_unit(units: Mapping[str, Any]) -> List[Any]:
    for preferred in ("USD", "USD/shares"):
        if preferred in units:
            return units[preferred]
    for rows in units.values():
        return rows
    return []


def extract_annual_series(facts: Mapping[str, Any], concept: str) -> Dict[str, float]:
    """Fiscal-year values keyed by period-end date, 10-K/FY rows only.

    Later rows for the same period end (restatements in newer filings)
    override earlier ones.
    """
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    entry = gaap.get(concept)
    if not isinstance(entry, Mapping):
        return {}
    units = entry.get("units")
    if not isinstance(units, Mapping):
        return {}

    series: Dict[str, float] = {}
    for row in _pick_unit(units):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("fp", "")).upper() != "FY":
            continue
        if str(row.get("form", "")).upper() != "10-K":
            continue
        end = row.get("end")
        value = _to_float(row.get("val"))
        if end and value is not None:
            series[str(end)] = value
    return series


def _best_series(facts: Mapping[str, Any], concepts: Tuple[str, ...]) -> Dict[str, float]:
    """The concept variant with the most recent fiscal data wins.

    Companies migrate between XBRL tags (e.g. Apple stopped filing plain
    ``Revenues`` after FY2018); taking the first non-empty concept would
    silently serve years-stale numbers.
    """
    best: Dict[str, float] = {}
    best_end = ""
    for concept in concepts:
        series = extract_annual_series(facts, concept)
        if series and max(series) > best_end:
            best, best_end = series, max(series)
    return best


def _latest(series: Dict[str, float]) -> Tuple[Optional[str], Optional[float]]:
    if not series:
        return None, None
    end = max(series)
    return end, series[end]


def _yoy_pct(series: Dict[str, float]) -> Optional[float]:
    if len(series) < 2:
        return None
    ends = sorted(series)
    latest, prior = series[ends[-1]], series[ends[-2]]
    if prior == 0:
        return None
    return (latest - prior) / abs(prior) * 100.0


def _ratio_pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100.0


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def metrics_from_facts(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalized growth / profitability / balance-sheet metrics from EDGAR.

    Every ratio is computed strictly within one fiscal period (the latest
    revenue period end): mixing numerator and denominator from different
    fiscal years fabricates numbers, so a missing same-period counterpart
    yields None instead.
    """
    revenue = _best_series(facts, REVENUE_CONCEPTS)
    net_income = extract_annual_series(facts, "NetIncomeLoss")
    eps = _best_series(facts, EPS_CONCEPTS)
    gross_profit = extract_annual_series(facts, "GrossProfit")
    operating_income = extract_annual_series(facts, "OperatingIncomeLoss")
    equity = extract_annual_series(facts, "StockholdersEquity")
    liabilities = extract_annual_series(facts, "Liabilities")
    assets_current = extract_annual_series(facts, "AssetsCurrent")
    liabilities_current = extract_annual_series(facts, "LiabilitiesCurrent")
    cash = extract_annual_series(facts, "CashAndCashEquivalentsAtCarryingValue")

    period_end, _ = _latest(revenue)
    if period_end is None:
        period_end, _ = _latest(net_income)

    def at_period(series: Dict[str, float]) -> Optional[float]:
        return series.get(period_end) if period_end else None

    revenue_now = at_period(revenue)
    net_income_now = at_period(net_income)
    equity_now = at_period(equity)

    return {
        "growth": {
            "revenue_yoy_pct": _yoy_pct(revenue),
            "net_income_yoy_pct": _yoy_pct(net_income),
            "eps_yoy_pct": _yoy_pct(eps),
        },
        "profitability": {
            "gross_margin_pct": _ratio_pct(at_period(gross_profit), revenue_now),
            "operating_margin_pct": _ratio_pct(at_period(operating_income), revenue_now),
            "net_margin_pct": _ratio_pct(net_income_now, revenue_now),
            "roe_pct": _ratio_pct(net_income_now, equity_now),
        },
        "balance_sheet": {
            "current_ratio": _ratio(at_period(assets_current), at_period(liabilities_current)),
            "debt_to_equity": _ratio(at_period(liabilities), equity_now),
            "cash": at_period(cash),
        },
        "meta": {
            "entity_name": facts.get("entityName"),
            "period_end": period_end,
            "basis": "annual (10-K)",
        },
    }


def _has_values(section: Optional[Mapping[str, Any]]) -> bool:
    return bool(section) and any(v is not None for v in section.values())


def _edgar_user_agent() -> str:
    return os.getenv(
        "SEC_EDGAR_USER_AGENT",
        "daily_stock_analysis tiered-analysis (SEC_EDGAR_USER_AGENT not set)",
    )


_cik_cache: Dict[str, int] = {}


def _resolve_cik(symbol: str) -> int:
    """Ticker -> CIK via SEC's public mapping file (cached in-process)."""
    global _cik_cache
    if not _cik_cache:
        import requests

        response = requests.get(
            EDGAR_TICKERS_URL,
            headers={"User-Agent": _edgar_user_agent()},
            timeout=_EDGAR_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        _cik_cache = {
            str(row.get("ticker", "")).upper(): int(row["cik_str"])
            for row in response.json().values()
            if isinstance(row, Mapping) and row.get("cik_str") is not None
        }
    cik = _cik_cache.get(symbol.upper())
    if cik is None:
        raise LookupError(f"no SEC CIK found for ticker {symbol!r}")
    return cik


def _default_facts_loader(symbol: str) -> Mapping[str, Any]:
    import requests

    cik = _resolve_cik(symbol)
    response = requests.get(
        EDGAR_COMPANYFACTS_URL.format(cik=cik),
        headers={"User-Agent": _edgar_user_agent()},
        timeout=_EDGAR_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _default_valuation_loader(symbol: str) -> Mapping[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.get_info() if hasattr(ticker, "get_info") else (ticker.info or {})
    return info if isinstance(info, Mapping) else {}


def _default_earnings_lookup(symbol: str) -> Mapping[str, Any]:
    """Next earnings date as payload-ready fields (empty dict = unknown)."""
    from ..earnings import next_earnings_info

    info = next_earnings_info(symbol, Market.US)
    if info.next_date is None:
        return {}
    return {
        "next_earnings_date": info.next_date,
        "days_until_earnings": info.days_until,
    }


class FundamentalsUSProvider(DimensionProvider):
    """NUMERIC US fundamentals: EDGAR statements + Yahoo valuation."""

    dimension = "fundamentals"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        facts_loader: Callable[[str], Mapping[str, Any]] = _default_facts_loader,
        valuation_loader: Callable[[str], Mapping[str, Any]] = _default_valuation_loader,
        earnings_lookup: Callable[[str], Mapping[str, Any]] = _default_earnings_lookup,
    ) -> None:
        self._facts_loader = facts_loader
        self._valuation_loader = valuation_loader
        self._earnings_lookup = earnings_lookup

    def supports(self, market: Market) -> bool:
        return market == Market.US

    def collect(self, symbol: str) -> DimensionResult:
        payload: Dict[str, Any] = {}
        citations: List[Citation] = []
        warnings: List[str] = []

        edgar_ok = self._collect_edgar(symbol, payload, citations, warnings)
        yahoo_ok = self._collect_valuation(symbol, payload, citations, warnings)
        self._collect_earnings_date(symbol, payload, warnings)

        if not edgar_ok and not yahoo_ok:
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                coverage=Coverage.UNAVAILABLE,
                warnings=warnings,
            )
        coverage = Coverage.FULL if (edgar_ok and yahoo_ok) else Coverage.PARTIAL
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            coverage=coverage,
            payload=payload,
            citations=citations,
            warnings=warnings,
        )

    def _collect_earnings_date(
        self,
        symbol: str,
        payload: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        """Auxiliary next-earnings-date fields (never degrades coverage —
        an event-calendar miss is not a statements failure). The deep
        analysis reads these to weigh event risk near a report date."""
        try:
            fields = self._earnings_lookup(symbol)
        except Exception as exc:
            warnings.append(f"earnings date lookup failed for {symbol}: {exc}")
            return
        for key, value in (fields or {}).items():
            if value is not None:
                payload[key] = value

    def _collect_edgar(
        self,
        symbol: str,
        payload: Dict[str, Any],
        citations: List[Citation],
        warnings: List[str],
    ) -> bool:
        try:
            facts = self._facts_loader(symbol)
        except Exception as exc:
            warnings.append(f"EDGAR fundamentals failed for {symbol}: {exc}")
            return False

        metrics = metrics_from_facts(facts)
        contributed = any(
            _has_values(metrics.get(section))
            for section in ("growth", "profitability", "balance_sheet")
        )
        if not contributed:
            warnings.append(f"EDGAR returned no usable annual facts for {symbol}")
            return False

        payload.update(metrics)
        cik = facts.get("cik")
        citations.append(
            Citation(
                source_name="SEC EDGAR companyfacts (XBRL)",
                url=(
                    EDGAR_COMPANYFACTS_URL.format(cik=int(cik))
                    if isinstance(cik, (int, float, str)) and str(cik).isdigit()
                    else None
                ),
            )
        )
        return True

    def _collect_valuation(
        self,
        symbol: str,
        payload: Dict[str, Any],
        citations: List[Citation],
        warnings: List[str],
    ) -> bool:
        try:
            info = self._valuation_loader(symbol)
        except Exception as exc:
            warnings.append(f"Yahoo valuation failed for {symbol}: {exc}")
            return False

        valuation = {
            target: _to_float(info.get(source))
            for source, target in _VALUATION_KEYS
        }
        if not _has_values(valuation):
            # ok-but-empty is the silent-blank trap: surface it explicitly.
            warnings.append(f"Yahoo returned no valuation ratios for {symbol}")
            return False

        payload["valuation"] = valuation
        citations.append(
            Citation(
                source_name="Yahoo Finance summary (yfinance)",
                url=YAHOO_KEY_STATISTICS_URL.format(symbol=symbol),
            )
        )
        return True
