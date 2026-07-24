# -*- coding: utf-8 -*-
"""US positioning provider (docs/tiered-analysis-design.md §2.4).

Who holds the stock and who can be forced to transact — the four
questions a trade thesis always has to answer: who is on the other side,
how crowded the trade is, who can be squeezed, and what the informed
parties are doing. Every number is a published figure fetched through
yfinance; no LLM anywhere in this dimension:

- **Short interest** — FINRA/exchange settlement data (published twice a
  month with roughly a two-week lag; ``as_of`` carries the report date).
- **Ownership structure** — quarterly 13F institutional filings (up to
  45 days late) plus the float/insider split from the Yahoo summary.
- **Insider activity** — SEC Form 4 open-market buys and sells over the
  trailing six months. Awards, option exercises and gifts are excluded:
  only open-market trades carry conviction.
- **Options positioning** — put/call open interest and volume summed
  over the nearest expirations (daily data, the freshest block here).

Each block failing degrades coverage explicitly (partial/unavailable
with warnings) — an ok-but-empty response is treated as missing, never
as a silent blank. Lagged blocks carry their as-of dates so a reader
never mistakes a two-week-old short-interest print for today's.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .base import (
    Citation,
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)

#: The Yahoo Finance page showing each block's numbers: yfinance itself
#: has no per-request page, but every block's figures are published on a
#: quote subpage — cited so readers can verify the data at the source.
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{symbol}"

#: Near-dated expirations are where positioning information concentrates;
#: walking the whole board would cost one request per expiration.
MAX_OPTION_EXPIRATIONS = 4

#: The Form 4 lookback: trailing six months.
INSIDER_WINDOW_DAYS = 183

_TOP_HOLDERS_COUNT = 10


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number  # NaN guard
    return None


def _epoch_to_date(value: Any) -> Optional[str]:
    """Yahoo's ``dateShortInterest`` is unix seconds; show it as a date."""
    number = _to_float(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _fraction_pct(value: Any) -> Optional[float]:
    """Yahoo serves ownership/short ratios as fractions (0.0234 = 2.34%)."""
    number = _to_float(value)
    return number * 100.0 if number is not None else None


def _has_values(section: Optional[Mapping[str, Any]]) -> bool:
    return bool(section) and any(v is not None for v in section.values())


def short_interest_metrics(info: Mapping[str, Any]) -> Dict[str, Any]:
    """The crowdedness-and-squeeze block from the Yahoo summary fields."""
    shares_short = _to_float(info.get("sharesShort"))
    prior = _to_float(info.get("sharesShortPriorMonth"))
    float_shares = _to_float(info.get("floatShares"))

    short_pct = _fraction_pct(info.get("shortPercentOfFloat"))
    if short_pct is None and shares_short is not None and float_shares:
        short_pct = shares_short / float_shares * 100.0

    change_pct: Optional[float] = None
    if shares_short is not None and prior:
        change_pct = (shares_short - prior) / prior * 100.0

    return {
        "short_pct_of_float": short_pct,
        "days_to_cover": _to_float(info.get("shortRatio")),
        "shares_short": shares_short,
        "change_vs_prior_month_pct": change_pct,
        "as_of": _epoch_to_date(info.get("dateShortInterest")),
    }


def ownership_metrics(
    info: Mapping[str, Any],
    holders: Optional[Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    """Who holds it: 13F institutional %, insider %, top-10 concentration.

    ``holders`` rows come from the institutional-holders table; ``pctHeld``
    (older yfinance: ``% Out``) is each holder's fraction of shares
    outstanding.
    """
    top10: Optional[float] = None
    if holders:
        fractions = [
            _to_float(row.get("pctHeld", row.get("% Out")))
            for row in list(holders)[:_TOP_HOLDERS_COUNT]
        ]
        present = [fraction for fraction in fractions if fraction is not None]
        if present:
            top10 = sum(present) * 100.0

    return {
        "institutional_pct": _fraction_pct(info.get("heldPercentInstitutions")),
        "insider_pct": _fraction_pct(info.get("heldPercentInsiders")),
        "top10_institutions_pct": top10,
        "float_shares": _to_float(info.get("floatShares")),
        "shares_outstanding": _to_float(info.get("sharesOutstanding")),
    }


def _trade_kind(text: str) -> Optional[str]:
    """Open-market buy/sell from the Form 4 row text; anything else
    (awards, exercises, gifts, conversions) is not a conviction trade."""
    lowered = text.lower()
    if "purchase" in lowered:
        return "buy"
    if "sale" in lowered:
        return "sell"
    return None


def insider_metrics(
    rows: Sequence[Mapping[str, Any]], today: date
) -> Dict[str, Any]:
    """Net open-market insider activity over the trailing window.

    Rows carry ``date`` (ISO string), ``text``, ``shares``, ``value``.
    Rows with unparseable dates or non-open-market text are skipped.
    Zero counts are real information — no insider traded — not a blank.
    """
    cutoff = today - timedelta(days=INSIDER_WINDOW_DAYS)
    buys = sells = 0
    net_shares = 0.0
    net_value = 0.0
    for row in rows:
        raw_date = str(row.get("date") or "")
        try:
            when = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        if when < cutoff or when > today:
            continue
        kind = _trade_kind(str(row.get("text") or ""))
        if kind is None:
            continue
        shares = _to_float(row.get("shares")) or 0.0
        value = _to_float(row.get("value")) or 0.0
        if kind == "buy":
            buys += 1
            net_shares += shares
            net_value += value
        else:
            sells += 1
            net_shares -= shares
            net_value -= value
    return {
        "buy_count": buys,
        "sell_count": sells,
        "net_shares": net_shares,
        "net_value_usd": net_value,
    }


def options_metrics(chains: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Put/call ratios over the fetched expirations' summed totals."""
    call_oi = sum(_to_float(chain.get("call_oi")) or 0.0 for chain in chains)
    put_oi = sum(_to_float(chain.get("put_oi")) or 0.0 for chain in chains)
    call_volume = sum(_to_float(chain.get("call_volume")) or 0.0 for chain in chains)
    put_volume = sum(_to_float(chain.get("put_volume")) or 0.0 for chain in chains)
    return {
        "put_call_oi_ratio": put_oi / call_oi if call_oi else None,
        "put_call_volume_ratio": put_volume / call_volume if call_volume else None,
        "total_open_interest": call_oi + put_oi,
        "expirations_covered": len(chains),
    }


# ---------------------------------------------------------------------------
# Default loaders (thin yfinance shims; everything above stays pure)
# ---------------------------------------------------------------------------


def _default_info_loader(symbol: str) -> Mapping[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.get_info() if hasattr(ticker, "get_info") else (ticker.info or {})
    return info if isinstance(info, Mapping) else {}


def _default_holders_loader(symbol: str) -> List[Dict[str, Any]]:
    import yfinance as yf

    frame = yf.Ticker(symbol).institutional_holders
    if frame is None or getattr(frame, "empty", True):
        return []
    return frame.to_dict("records")


def _default_insider_loader(symbol: str) -> List[Dict[str, Any]]:
    import yfinance as yf

    frame = yf.Ticker(symbol).insider_transactions
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: List[Dict[str, Any]] = []
    for record in frame.to_dict("records"):
        start = record.get("Start Date")
        if hasattr(start, "date"):
            date_text: Optional[str] = start.date().isoformat()
        else:
            date_text = str(start)[:10] if start is not None else None
        text = next(
            (record[key] for key in ("Text", "Transaction")
             if isinstance(record.get(key), str)),
            "",
        )
        rows.append(
            {
                "date": date_text,
                "text": text,
                "shares": record.get("Shares"),
                "value": record.get("Value"),
            }
        )
    return rows


def _frame_column_sum(frame: Any, column: str) -> float:
    try:
        series = frame[column]
    except (KeyError, TypeError):
        return 0.0
    return float(series.fillna(0).sum())


def _default_options_loader(symbol: str) -> List[Dict[str, Any]]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    chains: List[Dict[str, Any]] = []
    for expiration in list(ticker.options or ())[:MAX_OPTION_EXPIRATIONS]:
        chain = ticker.option_chain(expiration)
        chains.append(
            {
                "expiration": expiration,
                "call_oi": _frame_column_sum(chain.calls, "openInterest"),
                "put_oi": _frame_column_sum(chain.puts, "openInterest"),
                "call_volume": _frame_column_sum(chain.calls, "volume"),
                "put_volume": _frame_column_sum(chain.puts, "volume"),
            }
        )
    return chains


def _default_today() -> date:
    return datetime.now(timezone.utc).date()


class PositioningUSProvider(DimensionProvider):
    """NUMERIC US positioning: short interest, ownership, insiders, options."""

    dimension = "positioning"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        info_loader: Callable[[str], Mapping[str, Any]] = _default_info_loader,
        holders_loader: Callable[[str], Sequence[Mapping[str, Any]]] = _default_holders_loader,
        insider_loader: Callable[[str], Sequence[Mapping[str, Any]]] = _default_insider_loader,
        options_loader: Callable[[str], Sequence[Mapping[str, Any]]] = _default_options_loader,
        today: Callable[[], date] = _default_today,
    ) -> None:
        self._info_loader = info_loader
        self._holders_loader = holders_loader
        self._insider_loader = insider_loader
        self._options_loader = options_loader
        self._today = today

    def supports(self, market: Market) -> bool:
        # US disclosure only for now: FINRA short interest, 13F, Form 4.
        # A-share margin balances / HK short positions are separate designs.
        return market == Market.US

    def collect(self, symbol: str) -> DimensionResult:
        payload: Dict[str, Any] = {}
        citations: List[Citation] = []
        warnings: List[str] = []

        info = self._load_info(symbol, warnings)
        blocks_ok = [
            self._collect_short_interest(symbol, info, payload, citations, warnings),
            self._collect_ownership(symbol, info, payload, citations, warnings),
            self._collect_insiders(symbol, payload, citations, warnings),
            self._collect_options(symbol, payload, citations, warnings),
        ]

        if not any(blocks_ok):
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                coverage=Coverage.UNAVAILABLE,
                warnings=warnings,
            )
        coverage = Coverage.FULL if all(blocks_ok) else Coverage.PARTIAL
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            coverage=coverage,
            payload=payload,
            citations=citations,
            warnings=warnings,
        )

    def _load_info(
        self, symbol: str, warnings: List[str]
    ) -> Optional[Mapping[str, Any]]:
        try:
            return self._info_loader(symbol) or {}
        except Exception as exc:
            warnings.append(f"Yahoo summary failed for {symbol}: {exc}")
            return None

    def _collect_short_interest(
        self,
        symbol: str,
        info: Optional[Mapping[str, Any]],
        payload: Dict[str, Any],
        citations: List[Citation],
        warnings: List[str],
    ) -> bool:
        if info is None:
            return False  # the fetch failure is already on the warnings
        metrics = short_interest_metrics(info)
        if not _has_values(metrics):
            # ok-but-empty is the silent-blank trap: surface it explicitly.
            warnings.append(f"Yahoo returned no short-interest fields for {symbol}")
            return False
        payload["short_interest"] = metrics
        citations.append(
            Citation(
                source_name="FINRA short interest via Yahoo Finance (yfinance)",
                url=f"{YAHOO_QUOTE_URL.format(symbol=symbol)}/key-statistics",
            )
        )
        return True

    def _collect_ownership(
        self,
        symbol: str,
        info: Optional[Mapping[str, Any]],
        payload: Dict[str, Any],
        citations: List[Citation],
        warnings: List[str],
    ) -> bool:
        if info is None:
            return False
        holders: Optional[Sequence[Mapping[str, Any]]] = None
        try:
            holders = self._holders_loader(symbol)
        except Exception as exc:
            # Concentration alone degrades; the summary fields still count.
            warnings.append(f"institutional holders failed for {symbol}: {exc}")
        metrics = ownership_metrics(info, holders)
        if not _has_values(metrics):
            warnings.append(f"Yahoo returned no ownership fields for {symbol}")
            return False
        payload["ownership"] = metrics
        citations.append(
            Citation(
                source_name="13F institutional holdings via Yahoo Finance (yfinance)",
                url=f"{YAHOO_QUOTE_URL.format(symbol=symbol)}/holders",
            )
        )
        return True

    def _collect_insiders(
        self,
        symbol: str,
        payload: Dict[str, Any],
        citations: List[Citation],
        warnings: List[str],
    ) -> bool:
        try:
            rows = self._insider_loader(symbol)
        except Exception as exc:
            warnings.append(f"insider transactions failed for {symbol}: {exc}")
            return False
        payload["insider_activity_6m"] = insider_metrics(rows or [], self._today())
        citations.append(
            Citation(
                source_name="SEC Form 4 insider transactions via Yahoo Finance (yfinance)",
                url=f"{YAHOO_QUOTE_URL.format(symbol=symbol)}/insider-transactions",
            )
        )
        return True

    def _collect_options(
        self,
        symbol: str,
        payload: Dict[str, Any],
        citations: List[Citation],
        warnings: List[str],
    ) -> bool:
        try:
            chains = self._options_loader(symbol)
        except Exception as exc:
            warnings.append(f"options chain failed for {symbol}: {exc}")
            return False
        if not chains:
            warnings.append(f"no listed options found for {symbol}")
            return False
        payload["options"] = options_metrics(chains)
        citations.append(
            Citation(
                source_name="Yahoo Finance options chain (yfinance)",
                url=f"{YAHOO_QUOTE_URL.format(symbol=symbol)}/options",
            )
        )
        return True
