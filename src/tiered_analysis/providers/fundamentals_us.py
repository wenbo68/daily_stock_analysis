# -*- coding: utf-8 -*-
"""US fundamentals provider — v2 envelope payload (2026-07-29).

Field list per the TODO.md fundamentals audit: quarterly growth replaces
the stale annual YoY, the earnings block grows surprise history / the
realized earnings-day move / estimate revisions / the ex-dividend date,
profitability gains free cash flow, and the low-signal fields (net
margin, raw cash, P/B, annual YoY) are retired. Every published metric
ships as a ``{name, explanation, interpretation, value}`` envelope —
the same contract as technicals v2 — and computed metrics carry UI
formula receipts in ``DimensionResult.formulas``.

Sources, split by what each can actually answer:

- **SEC EDGAR companyfacts (XBRL)** — audited statements: quarterly
  growth (10-Q), margins / ROE / balance-sheet ratios (10-K), free cash
  flow (TTM from FY + YTD rows). Series math lives in
  ``edgar_series.py``.
- **Yahoo summary (yfinance)** — market-priced valuation ratios, the
  sector/industry profile and the ex-dividend date.
- **Yahoo earnings data (yfinance)** — the earnings calendar (next
  date), the surprise history and the analyst EPS estimate trend.
- **Daily bars** (optional, injected) — the realized earnings-day moves.

EDGAR statements + Yahoo valuation are the core: either failing degrades
coverage explicitly (partial/unavailable with warnings). The event and
history blocks are auxiliary — they warn, never degrade — matching the
long-standing rule that an event-calendar miss is not a statements
failure. An ok-but-empty response is treated as missing, never as a
silent blank.

SEC requires a descriptive User-Agent with contact info: set
``SEC_EDGAR_USER_AGENT`` in the environment (see .env.example).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .base import (
    Citation,
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)
from .edgar_series import (
    EPS_CONCEPTS,
    CAPEX_CONCEPTS,
    OPERATING_CASH_FLOW_CONCEPTS,
    REVENUE_CONCEPTS,
    best_series,
    extract_annual_series,
    extract_quarterly_series,
    prior_quarter_end,
    quarterly_yoy_pct,
    ttm_value,
)
from .technicals import make_metric, metric_value

EDGAR_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

#: The Yahoo Finance pages showing the cited figures: yfinance itself has
#: no per-request page, but the same numbers are published on the quote
#: subpages — cited so readers can verify at the source.
YAHOO_KEY_STATISTICS_URL = "https://finance.yahoo.com/quote/{symbol}/key-statistics"
YAHOO_ANALYSIS_URL = "https://finance.yahoo.com/quote/{symbol}/analysis"
EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_EDGAR_TIMEOUT_SECONDS = 15

# Yahoo .info key -> normalized valuation field (P/B retired 2026-07-29:
# only informative for banks/asset-heavy names).
_VALUATION_KEYS = (
    ("trailingPE", "pe_ttm"),
    ("forwardPE", "pe_forward"),
    ("priceToSalesTrailing12Months", "ps_ttm"),
    ("marketCap", "market_cap"),
)

#: Growth-trend dead band, in percentage points of YoY change: a swing
#: smaller than this is "steady", not a real acceleration/deceleration.
GROWTH_TREND_BAND_PP = 2.0
#: Quarterly EPS YoY is meaningless off a near-zero base.
EPS_YOY_MIN_BASE = 0.05
#: The earnings history window: the last N reported quarters.
SURPRISE_REPORTS = 4
#: Earnings-day moves need at least this many reports to mean anything.
REACTION_MIN_REPORTS = 2


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number  # NaN guard
    return None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _ratio_pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100.0


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _has_values(section: Optional[Mapping[str, Any]]) -> bool:
    return bool(section) and any(
        metric_value(node) is not None for node in section.values()
    )


def _epoch_to_date(value: Any) -> Optional[date]:
    number = _to_float(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Pure metric computations (all offline-testable)
# ---------------------------------------------------------------------------


def growth_trend_label(
    yoy_now: Optional[float], yoy_prior: Optional[float]
) -> Optional[str]:
    """accelerating / slowing / steady with a ±2pp dead band."""
    if yoy_now is None or yoy_prior is None:
        return None
    delta = yoy_now - yoy_prior
    if delta > GROWTH_TREND_BAND_PP:
        return "accelerating"
    if delta < -GROWTH_TREND_BAND_PP:
        return "slowing"
    return "steady"


def quarterly_growth_metrics(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """Quarterly YoY + trend for revenue and EPS, with receipt inputs.

    Returns per series: ``yoy`` (%), ``now``/``year_ago`` (the receipt
    ingredients), ``yoy_prior`` (the previous quarter's YoY, feeding the
    trend), ``trend`` and ``end`` (the quarter end used).
    """
    out: Dict[str, Any] = {}
    for series_key, concepts, min_base in (
        ("revenue", REVENUE_CONCEPTS, None),
        ("eps", EPS_CONCEPTS, EPS_YOY_MIN_BASE),
    ):
        series = best_series(facts, concepts, extract_quarterly_series)
        entry: Dict[str, Any] = {
            "yoy": None, "now": None, "year_ago": None,
            "yoy_prior": None, "trend": None, "end": None,
        }
        if series:
            latest = max(series)
            entry["end"] = latest
            current = quarterly_yoy_pct(series, latest)
            if current is not None and (
                min_base is None or abs(current[2]) >= min_base
            ):
                entry["yoy"], entry["now"], entry["year_ago"] = current
            prior_end = prior_quarter_end(series, latest)
            if prior_end is not None:
                prior = quarterly_yoy_pct(series, prior_end)
                if prior is not None and (
                    min_base is None or abs(prior[2]) >= min_base
                ):
                    entry["yoy_prior"] = prior[0]
            entry["trend"] = growth_trend_label(
                entry["yoy"], entry["yoy_prior"]
            )
        out[series_key] = entry
    return out


def annual_statement_metrics(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """Margins / ROE / balance-sheet ratios, strictly within one fiscal
    period (the latest revenue period end): mixing numerator and
    denominator from different fiscal years fabricates numbers, so a
    missing same-period counterpart yields None instead. Receipt
    ingredients ride along with each value.
    """
    revenue = best_series(facts, REVENUE_CONCEPTS)
    net_income = extract_annual_series(facts, "NetIncomeLoss")
    gross_profit = extract_annual_series(facts, "GrossProfit")
    operating_income = extract_annual_series(facts, "OperatingIncomeLoss")
    equity = extract_annual_series(facts, "StockholdersEquity")
    liabilities = extract_annual_series(facts, "Liabilities")
    assets_current = extract_annual_series(facts, "AssetsCurrent")
    liabilities_current = extract_annual_series(facts, "LiabilitiesCurrent")

    period_end = max(revenue) if revenue else (max(net_income) if net_income else None)

    def at_period(series: Dict[str, float]) -> Optional[float]:
        return series.get(period_end) if period_end else None

    revenue_now = at_period(revenue)
    net_income_now = at_period(net_income)
    equity_now = at_period(equity)

    return {
        "period_end": period_end,
        "entity_name": facts.get("entityName"),
        "gross_margin_pct": _ratio_pct(at_period(gross_profit), revenue_now),
        "gross_profit": at_period(gross_profit),
        "operating_margin_pct": _ratio_pct(at_period(operating_income), revenue_now),
        "operating_income": at_period(operating_income),
        "revenue": revenue_now,
        "roe_pct": _ratio_pct(net_income_now, equity_now),
        "net_income": net_income_now,
        "equity": equity_now,
        "current_ratio": _ratio(at_period(assets_current), at_period(liabilities_current)),
        "assets_current": at_period(assets_current),
        "liabilities_current": at_period(liabilities_current),
        "debt_to_equity": _ratio(at_period(liabilities), equity_now),
        "liabilities": at_period(liabilities),
    }


def fcf_metrics(facts: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Free cash flow = operating cash flow − capital spending, both on
    the same basis (TTM when the YTD rows allow it, else the latest
    fiscal year). Mismatched bases would fabricate a number, so they
    downgrade together."""
    ocf = ttm_value(facts, OPERATING_CASH_FLOW_CONCEPTS)
    capex = ttm_value(facts, CAPEX_CONCEPTS)
    if ocf is None or capex is None:
        return None
    if ocf[2] != capex[2] or ocf[1] != capex[1]:
        # Recompute both on the annual basis: ttm_value falls back to
        # annual only when TTM pieces are missing, so a mismatch means
        # exactly one side had them.
        ocf_annual = best_series(facts, OPERATING_CASH_FLOW_CONCEPTS)
        capex_annual = best_series(facts, CAPEX_CONCEPTS)
        shared = set(ocf_annual) & set(capex_annual)
        if not shared:
            return None
        end = max(shared)
        return {
            "fcf": ocf_annual[end] - capex_annual[end],
            "operating_cash_flow": ocf_annual[end],
            "capital_spending": capex_annual[end],
            "end": end,
            "basis": "annual",
        }
    return {
        "fcf": ocf[0] - capex[0],
        "operating_cash_flow": ocf[0],
        "capital_spending": capex[0],
        "end": ocf[1],
        "basis": ocf[2],
    }


def surprise_metrics(
    rows: Sequence[Mapping[str, Any]], today: date
) -> Dict[str, Any]:
    """Beat count + average surprise over the last reported quarters.

    Rows carry ``date`` (ISO), ``eps_estimate``, ``eps_actual``,
    ``surprise_pct``. Only rows with a reported actual on/before today
    count; rows without an estimate are excluded from the beat count
    (you cannot beat a bar that was never set).
    """
    past: List[Tuple[date, Mapping[str, Any]]] = []
    for row in rows:
        try:
            when = date.fromisoformat(str(row.get("date") or "")[:10])
        except ValueError:
            continue
        if when > today or _to_float(row.get("eps_actual")) is None:
            continue
        past.append((when, row))
    past.sort(key=lambda item: item[0], reverse=True)
    recent = past[:SURPRISE_REPORTS]

    beats = total = 0
    surprises: List[float] = []
    for _when, row in recent:
        actual = _to_float(row.get("eps_actual"))
        estimate = _to_float(row.get("eps_estimate"))
        if estimate is not None and actual is not None:
            total += 1
            if actual >= estimate:
                beats += 1
        surprise = _to_float(row.get("surprise_pct"))
        if surprise is None and estimate not in (None, 0) and actual is not None:
            surprise = (actual - estimate) / abs(estimate) * 100.0
        if surprise is not None:
            surprises.append(surprise)

    return {
        "beats": f"{beats}/{total}" if total else None,
        "avg_surprise_pct": _round(mean(surprises)) if surprises else None,
        "report_dates": [when for when, _row in recent],
    }


def reaction_metrics(
    bars: Sequence[Any], report_dates: Sequence[date]
) -> Dict[str, Any]:
    """Realized close-to-close moves around past report dates, from the
    daily bars: last close on/before the report date → first close
    after it (BMO/AMC timing is not distinguishable from date-only
    data, so the bracketing pair is the honest read)."""
    dated: List[Tuple[date, float]] = []
    for bar in bars:
        raw = getattr(bar, "date", None)
        close = getattr(bar, "close", None)
        if raw is None or close is None:
            continue
        try:
            dated.append((date.fromisoformat(str(raw)[:10]), float(close)))
        except ValueError:
            continue
    dated.sort(key=lambda item: item[0])

    moves: List[float] = []
    for report in report_dates:
        before = [close for when, close in dated if when <= report]
        after = [close for when, close in dated if when > report]
        if before and after and before[-1] != 0:
            moves.append((after[0] - before[-1]) / before[-1] * 100.0)

    if len(moves) < REACTION_MIN_REPORTS:
        return {"avg_abs_pct": None, "worst_pct": None, "count": len(moves)}
    return {
        "avg_abs_pct": _round(mean(abs(move) for move in moves)),
        "worst_pct": _round(min(moves)),
        "count": len(moves),
    }


def revision_pct(trend: Mapping[str, Any]) -> Optional[float]:
    """Percent change of the current-quarter consensus EPS estimate vs
    90 days ago; a near-zero base makes the percentage meaningless."""
    now = _to_float(trend.get("current"))
    then = _to_float(trend.get("days_ago_90"))
    if now is None or then is None or abs(then) < EPS_YOY_MIN_BASE:
        return None
    return (now - then) / abs(then) * 100.0


# ---------------------------------------------------------------------------
# Default loaders (thin network shims; everything above stays pure)
# ---------------------------------------------------------------------------


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


def _default_info_loader(symbol: str) -> Mapping[str, Any]:
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


def _default_earnings_history_loader(symbol: str) -> List[Dict[str, Any]]:
    """Past + upcoming earnings rows from yfinance's earnings-dates table."""
    import yfinance as yf

    frame = yf.Ticker(symbol).get_earnings_dates(limit=12)
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: List[Dict[str, Any]] = []
    for stamp, record in frame.iterrows():
        when = stamp.date().isoformat() if hasattr(stamp, "date") else str(stamp)[:10]
        rows.append(
            {
                "date": when,
                "eps_estimate": record.get("EPS Estimate"),
                "eps_actual": record.get("Reported EPS"),
                "surprise_pct": record.get("Surprise(%)"),
            }
        )
    return rows


def _default_eps_trend_loader(symbol: str) -> Mapping[str, Any]:
    """Current-quarter consensus EPS estimate now vs 90 days ago."""
    import yfinance as yf

    frame = yf.Ticker(symbol).eps_trend
    if frame is None or getattr(frame, "empty", True):
        return {}
    if "0q" not in frame.index:
        return {}
    row = frame.loc["0q"]
    return {"current": row.get("current"), "days_ago_90": row.get("90daysAgo")}


def _default_today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class FundamentalsUSProvider(DimensionProvider):
    """NUMERIC US fundamentals: EDGAR statements + Yahoo market data."""

    dimension = "fundamentals"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        facts_loader: Callable[[str], Mapping[str, Any]] = _default_facts_loader,
        info_loader: Callable[[str], Mapping[str, Any]] = _default_info_loader,
        earnings_lookup: Callable[[str], Mapping[str, Any]] = _default_earnings_lookup,
        earnings_history_loader: Callable[
            [str], Sequence[Mapping[str, Any]]
        ] = _default_earnings_history_loader,
        eps_trend_loader: Callable[[str], Mapping[str, Any]] = _default_eps_trend_loader,
        bars_loader: Optional[Callable[[str], Sequence[Any]]] = None,
        today: Callable[[], date] = _default_today,
    ) -> None:
        self._facts_loader = facts_loader
        self._info_loader = info_loader
        self._earnings_lookup = earnings_lookup
        self._earnings_history_loader = earnings_history_loader
        self._eps_trend_loader = eps_trend_loader
        self._bars_loader = bars_loader
        self._today = today

    def supports(self, market: Market) -> bool:
        return market == Market.US

    def collect(self, symbol: str) -> DimensionResult:
        citations: List[Citation] = []
        warnings: List[str] = []
        formulas: Dict[str, Any] = {}

        info = self._load_info(symbol, warnings)
        facts = self._load_facts(symbol, warnings)

        earnings_group = self._earnings_group(symbol, info, citations, warnings, formulas)
        payload: Dict[str, Any] = {
            "profile": self._profile_group(info),
            "earnings": earnings_group,
            "growth": self._growth_group(facts, formulas),
            "profitability": self._profitability_group(facts, formulas),
            "balance_sheet": self._balance_group(facts, formulas),
            "valuation": self._valuation_group(symbol, info, citations, warnings),
            "meta": self._meta_group(facts),
        }

        edgar_ok = facts is not None and any(
            _has_values(payload[group])
            for group in ("growth", "profitability", "balance_sheet")
        )
        if facts is not None and not edgar_ok:
            warnings.append(f"EDGAR returned no usable statement facts for {symbol}")
        if edgar_ok:
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
        yahoo_ok = _has_values(payload["valuation"])

        if not edgar_ok and not yahoo_ok:
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                coverage=Coverage.UNAVAILABLE,
                warnings=warnings,
            )
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            coverage=Coverage.FULL if (edgar_ok and yahoo_ok) else Coverage.PARTIAL,
            payload=payload,
            citations=citations,
            warnings=warnings,
            formulas=formulas or None,
        )

    # ---- source fetches -------------------------------------------------

    def _load_info(
        self, symbol: str, warnings: List[str]
    ) -> Optional[Mapping[str, Any]]:
        try:
            return self._info_loader(symbol) or {}
        except Exception as exc:
            warnings.append(f"Yahoo summary failed for {symbol}: {exc}")
            return None

    def _load_facts(
        self, symbol: str, warnings: List[str]
    ) -> Optional[Mapping[str, Any]]:
        try:
            return self._facts_loader(symbol)
        except Exception as exc:
            warnings.append(f"EDGAR fundamentals failed for {symbol}: {exc}")
            return None

    # ---- payload groups --------------------------------------------------

    @staticmethod
    def _profile_group(info: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        sector = info.get("sector") if info else None
        industry = info.get("industry") if info else None
        return {
            "sector": make_metric(
                "sector",
                "The company's sector classification.",
                sector if isinstance(sector, str) else None,
                interpretation=(
                    "Margins, leverage and valuation only mean anything "
                    "against industry peers; the sector also says which "
                    "macro series matter most (oil for energy, the 10y "
                    "yield for long-duration tech)."
                ),
            ),
            "industry": make_metric(
                "industry",
                "The finer industry classification within the sector.",
                industry if isinstance(industry, str) else None,
                interpretation=(
                    "The peer group this company's ratios should be "
                    "compared against."
                ),
            ),
        }

    def _earnings_group(
        self,
        symbol: str,
        info: Optional[Mapping[str, Any]],
        citations: List[Citation],
        warnings: List[str],
        formulas: Dict[str, Any],
    ) -> Dict[str, Any]:
        today = self._today()

        next_date: Optional[str] = None
        days_until: Optional[int] = None
        try:
            fields = self._earnings_lookup(symbol) or {}
            raw_date = fields.get("next_earnings_date")
            next_date = raw_date if isinstance(raw_date, str) else None
            raw_days = fields.get("days_until_earnings")
            days_until = raw_days if isinstance(raw_days, int) else None
        except Exception as exc:
            warnings.append(f"earnings date lookup failed for {symbol}: {exc}")

        surprises: Dict[str, Any] = {
            "beats": None, "avg_surprise_pct": None, "report_dates": []
        }
        try:
            rows = self._earnings_history_loader(symbol)
        except Exception as exc:
            rows = []
            warnings.append(f"earnings history failed for {symbol}: {exc}")
        if rows:
            surprises = surprise_metrics(rows, today)
            citations.append(
                Citation(
                    source_name="Earnings history via Yahoo Finance (yfinance)",
                    url=YAHOO_ANALYSIS_URL.format(symbol=symbol),
                )
            )
        else:
            warnings.append(
                f"no earnings history rows for {symbol} — surprise and "
                "earnings-day-move fields omitted"
            )

        reaction: Dict[str, Any] = {"avg_abs_pct": None, "worst_pct": None, "count": 0}
        if surprises["report_dates"] and self._bars_loader is not None:
            try:
                bars = self._bars_loader(symbol)
            except Exception as exc:
                bars = []
                warnings.append(f"bars for earnings reaction failed: {exc}")
            if bars:
                reaction = reaction_metrics(bars, surprises["report_dates"])
                if reaction["avg_abs_pct"] is None and reaction["count"]:
                    warnings.append(
                        "too few earnings reports inside the bar history "
                        f"({reaction['count']}) for the earnings-day move"
                    )

        revision: Optional[float] = None
        try:
            trend = self._eps_trend_loader(symbol) or {}
        except Exception as exc:
            trend = {}
            warnings.append(f"EPS estimate trend failed for {symbol}: {exc}")
        if trend:
            revision = revision_pct(trend)

        ex_div = _epoch_to_date(info.get("exDividendDate")) if info else None
        if ex_div is not None and ex_div < today:
            ex_div = None  # a past ex-div date is noise, not a coming gap

        if days_until is not None and next_date is not None:
            formulas["earnings.days_until_earnings"] = {
                "formula": "next_earnings_date − today",
                "inputs": {
                    "next_earnings_date": next_date,
                    "today": today.isoformat(),
                },
            }
        if surprises["beats"] is not None:
            formulas["earnings.beats_4q"] = {
                "formula": (
                    "reports with actual EPS ≥ the analyst estimate, out "
                    f"of the last {SURPRISE_REPORTS} reported quarters"
                ),
                "inputs": {},
            }
        if surprises["avg_surprise_pct"] is not None:
            formulas["earnings.avg_surprise_pct_4q"] = {
                "formula": (
                    "mean of (actual EPS − estimate) / |estimate| × 100 "
                    f"over the last {SURPRISE_REPORTS} reported quarters"
                ),
                "inputs": {},
            }
        if reaction["avg_abs_pct"] is not None:
            formulas["earnings.reaction_avg_abs_pct"] = {
                "formula": (
                    "mean absolute close-to-close % move across each of "
                    "the last report dates (last close before the report "
                    "→ first close after it)"
                ),
                "inputs": {},
            }
        if reaction["worst_pct"] is not None:
            formulas["earnings.reaction_worst_pct"] = {
                "formula": (
                    "most negative close-to-close % move across those "
                    "same report dates"
                ),
                "inputs": {},
            }
        if revision is not None:
            formulas["earnings.eps_rev_90d_pct"] = {
                "formula": "(estimate_now − estimate_90d_ago) / |estimate_90d_ago| × 100",
                "inputs": {
                    "estimate_now": _to_float(trend.get("current")),
                    "estimate_90d_ago": _to_float(trend.get("days_ago_90")),
                },
            }

        return {
            "next_earnings_date": make_metric(
                "next earnings date",
                "The date the company next reports quarterly results.",
                next_date,
                interpretation=(
                    "A report inside the hold window means the stock can "
                    "gap straight past a stop overnight — exit before it "
                    "or size for it."
                ),
            ),
            "days_until_earnings": make_metric(
                "days until earnings",
                "Days from today until that report.",
                days_until,
                interpretation=(
                    "Small = the event risk is live now; the plan's "
                    "earnings warning fires inside a week."
                ),
            ),
            "beats_4q": make_metric(
                "earnings beats (last 4)",
                "How many of the last reported quarters came in at or "
                "above the analyst EPS estimate.",
                surprises["beats"],
                interpretation=(
                    "Consistent beaters get the benefit of the doubt "
                    "into a report; habitual missers lose it."
                ),
            ),
            "avg_surprise_pct_4q": make_metric(
                "avg earnings surprise (last 4)",
                "Average gap between reported EPS and the analyst "
                "estimate over those quarters, in %.",
                surprises["avg_surprise_pct"],
                interpretation=(
                    "Says whether the company tends to clear the bar "
                    "analysts set — not how the stock reacts; read it "
                    "with the earnings-day move below."
                ),
            ),
            "reaction_avg_abs_pct": make_metric(
                "typical earnings-day move (last 4)",
                "Average size of the close-to-close move around the "
                "last few reports, ignoring direction, in %.",
                reaction["avg_abs_pct"],
                interpretation=(
                    "The realized event risk: a stock that moves ±10% on "
                    "earnings needs a different plan than one that moves "
                    "±2%."
                ),
            ),
            "reaction_worst_pct": make_metric(
                "worst earnings-day drop (last 4)",
                "The most negative close-to-close move around those "
                "reports, in %.",
                reaction["worst_pct"],
                interpretation=(
                    "How badly holding through a report has actually "
                    "gone recently."
                ),
            ),
            "eps_rev_90d_pct": make_metric(
                "EPS estimate revision (90d)",
                "Change in the analyst consensus EPS estimate for the "
                "current quarter versus 90 days ago, in %.",
                _round(revision),
                interpretation=(
                    "Rising estimates tend to pull the price up over "
                    "weeks; cuts are a headwind even on a good chart."
                ),
            ),
            "ex_dividend_date": make_metric(
                "ex-dividend date",
                "The next date the stock trades without its dividend; "
                "the price mechanically opens lower by roughly the "
                "dividend amount.",
                ex_div.isoformat() if ex_div else None,
                interpretation=(
                    "A small scheduled gap-down that can clip a tight "
                    "stop on a long."
                ),
            ),
        }

    @staticmethod
    def _growth_group(
        facts: Optional[Mapping[str, Any]], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        growth = (
            quarterly_growth_metrics(facts)
            if facts is not None
            else {"revenue": {}, "eps": {}}
        )
        revenue = growth.get("revenue") or {}
        eps = growth.get("eps") or {}

        trend_branches = [
            {"label": "accelerating", "condition": "yoy_now − yoy_prior > 2"},
            {"label": "slowing", "condition": "yoy_now − yoy_prior < -2"},
            {"label": "steady", "condition": None},
        ]
        for series_key, entry in (("revenue", revenue), ("eps", eps)):
            if entry.get("yoy") is not None:
                formulas[f"growth.{series_key}_yoy_q"] = {
                    "formula": (
                        f"({series_key}_q − {series_key}_q_year_ago) / "
                        f"|{series_key}_q_year_ago| × 100"
                    ),
                    "inputs": {
                        f"{series_key}_q": entry["now"],
                        f"{series_key}_q_year_ago": entry["year_ago"],
                    },
                }
            if entry.get("trend") is not None:
                formulas[f"growth.{series_key}_growth_trend"] = {
                    "branches": trend_branches,
                    "inputs": {
                        "yoy_now": round(entry["yoy"], 2),
                        "yoy_prior": round(entry["yoy_prior"], 2),
                    },
                }

        return {
            "revenue_yoy_q": make_metric(
                "quarterly revenue YoY",
                "Latest reported quarter's revenue versus the same "
                "quarter last year, in %.",
                _round(revenue.get("yoy")),
                interpretation=(
                    "Positive and rising = an expanding business; the "
                    "direction of change matters more than the level."
                ),
            ),
            "revenue_growth_trend": make_metric(
                "revenue growth trend",
                "Whether that growth rate sped up or slowed versus the "
                "previous quarter (±2 percentage-point dead band).",
                revenue.get("trend"),
                interpretation=(
                    "Acceleration is the classic fuel for multi-week "
                    "runs; deceleration often ends them while growth is "
                    "still positive."
                ),
            ),
            "eps_yoy_q": make_metric(
                "quarterly EPS YoY",
                "Latest reported quarter's earnings per share versus "
                "the same quarter last year, in %.",
                _round(eps.get("yoy")),
                interpretation=(
                    "Diverges from revenue growth when margins or the "
                    "share count move; buybacks boost it, dilution "
                    "drags it."
                ),
            ),
            "eps_growth_trend": make_metric(
                "EPS growth trend",
                "Whether EPS growth sped up or slowed versus the "
                "previous quarter (±2 percentage-point dead band).",
                eps.get("trend"),
                interpretation=(
                    "The market pays for the change in trajectory, not "
                    "the level."
                ),
            ),
        }

    @staticmethod
    def _profitability_group(
        facts: Optional[Mapping[str, Any]], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        annual = annual_statement_metrics(facts) if facts is not None else {}
        fcf = fcf_metrics(facts) if facts is not None else None

        if annual.get("gross_margin_pct") is not None:
            formulas["profitability.gross_margin_pct"] = {
                "formula": "gross_profit / revenue × 100",
                "inputs": {
                    "gross_profit": annual["gross_profit"],
                    "revenue": annual["revenue"],
                },
            }
        if annual.get("operating_margin_pct") is not None:
            formulas["profitability.operating_margin_pct"] = {
                "formula": "operating_income / revenue × 100",
                "inputs": {
                    "operating_income": annual["operating_income"],
                    "revenue": annual["revenue"],
                },
            }
        if annual.get("roe_pct") is not None:
            formulas["profitability.roe_pct"] = {
                "formula": "net_income / equity × 100",
                "inputs": {
                    "net_income": annual["net_income"],
                    "equity": annual["equity"],
                },
            }
        if fcf is not None:
            formulas["profitability.fcf"] = {
                "formula": "operating_cash_flow − capital_spending",
                "inputs": {
                    "operating_cash_flow": fcf["operating_cash_flow"],
                    "capital_spending": fcf["capital_spending"],
                },
            }

        fcf_basis = (
            f"trailing twelve months to {fcf['end']}"
            if fcf and fcf["basis"] == "ttm"
            else (f"fiscal year ended {fcf['end']}" if fcf else "period unavailable")
        )
        return {
            "gross_margin_pct": make_metric(
                "gross margin",
                "Percent of each sales dollar left after the direct "
                "cost of making the product (latest fiscal year).",
                _round(annual.get("gross_margin_pct")),
                interpretation=(
                    "High or rising = pricing power; falling = "
                    "competition or cost pressure biting."
                ),
            ),
            "operating_margin_pct": make_metric(
                "operating margin",
                "Percent of sales left after all operating costs, "
                "before interest and taxes (latest fiscal year).",
                _round(annual.get("operating_margin_pct")),
                interpretation=(
                    "The efficiency number the market judges at "
                    "earnings; a trend break here moves the stock."
                ),
            ),
            "roe_pct": make_metric(
                "ROE",
                "Yearly profit as a percent of the shareholders' "
                "capital tied up in the business.",
                _round(annual.get("roe_pct")),
                interpretation=(
                    "Sustained ~15%+ marks a quality business; very low "
                    "or negative means the business burns capital."
                ),
            ),
            "fcf": make_metric(
                "free cash flow",
                "Cash generated after operating costs and capital "
                f"spending ({fcf_basis}).",
                _round(fcf["fcf"], 0) if fcf else None,
                interpretation=(
                    "Positive and close to reported profit = the "
                    "earnings are real; reported profits with negative "
                    "cash flow is a red flag."
                ),
            ),
        }

    @staticmethod
    def _balance_group(
        facts: Optional[Mapping[str, Any]], formulas: Dict[str, Any]
    ) -> Dict[str, Any]:
        annual = annual_statement_metrics(facts) if facts is not None else {}

        if annual.get("current_ratio") is not None:
            formulas["balance_sheet.current_ratio"] = {
                "formula": "current_assets / current_liabilities",
                "inputs": {
                    "current_assets": annual["assets_current"],
                    "current_liabilities": annual["liabilities_current"],
                },
            }
        if annual.get("debt_to_equity") is not None:
            formulas["balance_sheet.debt_to_equity"] = {
                "formula": "total_liabilities / equity",
                "inputs": {
                    "total_liabilities": annual["liabilities"],
                    "equity": annual["equity"],
                },
            }

        return {
            "current_ratio": make_metric(
                "current ratio",
                "Short-term assets divided by short-term liabilities — "
                "can it pay what's due within a year (latest fiscal "
                "year).",
                _round(annual.get("current_ratio")),
                interpretation=(
                    "Above about 1.5 is comfortable; below 1 hints at a "
                    "cash crunch, where bad news hits twice as hard."
                ),
            ),
            "debt_to_equity": make_metric(
                "debt to equity",
                "Total liabilities compared to shareholders' capital — "
                "how leveraged the company is.",
                _round(annual.get("debt_to_equity")),
                interpretation=(
                    "High leverage amplifies moves both ways and hurts "
                    "most when rates are high; compare within the same "
                    "industry."
                ),
            ),
        }

    @staticmethod
    def _valuation_group(
        symbol: str,
        info: Optional[Mapping[str, Any]],
        citations: List[Citation],
        warnings: List[str],
    ) -> Dict[str, Any]:
        values = {
            target: _to_float(info.get(source)) if info else None
            for source, target in _VALUATION_KEYS
        }
        if info is not None and not any(v is not None for v in values.values()):
            # ok-but-empty is the silent-blank trap: surface it explicitly.
            warnings.append(f"Yahoo returned no valuation ratios for {symbol}")
        elif any(v is not None for v in values.values()):
            citations.append(
                Citation(
                    source_name="Yahoo Finance summary (yfinance)",
                    url=YAHOO_KEY_STATISTICS_URL.format(symbol=symbol),
                )
            )

        return {
            "pe_ttm": make_metric(
                "trailing P/E",
                "Price divided by the last 12 months of profit — how "
                "many years of current profit you pay for the stock.",
                _round(values["pe_ttm"]),
                interpretation=(
                    "High = big expectations already priced in, good "
                    "news is needed just to hold the level; low = cheap, "
                    "or the market expects decline."
                ),
            ),
            "pe_forward": make_metric(
                "forward P/E",
                "Price divided by the profit analysts expect over the "
                "next 12 months.",
                _round(values["pe_forward"]),
                interpretation=(
                    "Well below the trailing P/E = analysts expect "
                    "growth; above it = expected shrinkage."
                ),
            ),
            "ps_ttm": make_metric(
                "P/S",
                "Price divided by the last 12 months of sales.",
                _round(values["ps_ttm"]),
                interpretation=(
                    "The valuation gauge for unprofitable names where "
                    "P/E is meaningless."
                ),
            ),
            "market_cap": make_metric(
                "market cap",
                "Total value of all the company's shares, in dollars.",
                values["market_cap"],
                interpretation=(
                    "Mega caps grind, small caps gap and squeeze; also "
                    "sets what liquidity to expect."
                ),
            ),
        }

    @staticmethod
    def _meta_group(facts: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        annual = annual_statement_metrics(facts) if facts is not None else {}
        growth = (
            quarterly_growth_metrics(facts)
            if facts is not None
            else {"revenue": {}, "eps": {}}
        )
        period_end_q = (growth.get("revenue") or {}).get("end") or (
            (growth.get("eps") or {}).get("end")
        )
        entity = annual.get("entity_name")
        return {
            "entity_name": make_metric(
                "company",
                "The registrant name on the SEC filings.",
                entity if isinstance(entity, str) else None,
                interpretation=(
                    "Confirms the filings belong to the ticker being "
                    "analyzed."
                ),
            ),
            "period_end": make_metric(
                "annual statements period end",
                "The fiscal year end the margins, ROE and balance-sheet "
                "ratios come from.",
                annual.get("period_end"),
                interpretation=(
                    "Nearly a year old = treat those numbers as stale "
                    "background."
                ),
            ),
            "period_end_q": make_metric(
                "quarterly statements period end",
                "The quarter end the quarterly growth fields come from.",
                period_end_q,
                interpretation=(
                    "Right after an annual report the latest 10-Q can "
                    "lag a full quarter — check this date before "
                    "treating growth as fresh."
                ),
            ),
            "basis": make_metric(
                "statement basis",
                "Which sources feed this report.",
                "annual 10-K + quarterly 10-Q (SEC EDGAR); market data via Yahoo",
                interpretation=(
                    "Audited SEC filings for the statements; Yahoo for "
                    "the market-priced and analyst-derived fields."
                ),
            ),
        }
