# -*- coding: utf-8 -*-
"""Deterministic technical indicators (docs/tiered-analysis-design.md §2.1).

Pure Python over OHLCV bars — no numpy/pandas, no network. Fetching is
decoupled: ``TechnicalsProvider`` receives a ``bars_loader`` callable so the
indicator core stays reproducible and offline-testable. Indicators are pure
math over price series and therefore market-agnostic.

ATR is intentionally included: it is the standard input for the future
volatility-adaptive stops and risk-based sizing (design doc §3.2) and is
absent from the legacy ``stock_analyzer.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .base import (
    Citation,
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)

RSI_PERIOD = 14
ATR_PERIOD = 14
BIAS_PERIOD = 20
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
# Bars needed so every indicator in the payload can be computed.
FULL_HISTORY_BARS = 60
# One trading year of bars — the 52-week high/low window every desk
# references. With less history the "52w" keys honestly cover what exists
# (bars_count in the payload discloses the real window).
YEAR_BARS = 250
# Bars needed for the minimum viable set (RSI/ATR need period + 1).
MIN_HISTORY_BARS = max(RSI_PERIOD, ATR_PERIOD) + 1
# Daily returns needed before a 5th-percentile "worst day" means anything.
MIN_RETURNS_FOR_TAIL = 20
#: Payload keys allowed to be None without downgrading coverage — volume
#: is source-dependent (some feeds omit it), unlike price history;
#: volatility_pct is derived from atr_14, whose absence is already flagged.
OPTIONAL_PAYLOAD_KEYS = frozenset({"avg_volume_20", "volatility_pct"})


@dataclass(frozen=True)
class Bar:
    """One daily OHLCV bar; only the fields the indicators need."""

    high: float
    low: float
    close: float
    open: Optional[float] = None
    volume: Optional[float] = None
    date: Optional[str] = None


def compute_sma(closes: List[float], period: int) -> Optional[float]:
    """Simple moving average of the most recent ``period`` closes."""
    if period <= 0 or len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
    """EMA aligned to input; None until the seed SMA at index period-1."""
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    series: List[Optional[float]] = [None] * (period - 1)
    ema = sum(values[:period]) / period
    series.append(ema)
    multiplier = 2.0 / (period + 1)
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        series.append(ema)
    return series


def compute_ema(closes: List[float], period: int) -> Optional[float]:
    """Exponential moving average (SMA-seeded) of the close series."""
    series = _ema_series(closes, period)
    return series[-1] if series else None


def compute_wilder_rsi(closes: List[float], period: int = RSI_PERIOD) -> Optional[float]:
    """RSI with Wilder smoothing; needs ``period + 1`` closes.

    A series with zero average gain and zero average loss is neutral (50).
    """
    if period <= 0 or len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0 and avg_gain == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def compute_macd(
    closes: List[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> Optional[Dict[str, float]]:
    """MACD line, signal line, and histogram for the latest bar."""
    if len(closes) < slow + signal - 1:
        return None
    fast_series = _ema_series(closes, fast)
    slow_series = _ema_series(closes, slow)
    macd_line = [
        f - s
        for f, s in zip(fast_series, slow_series)
        if f is not None and s is not None
    ]
    signal_series = _ema_series(macd_line, signal)
    signal_value = signal_series[-1]
    if signal_value is None:
        return None
    macd_value = macd_line[-1]
    return {
        "macd": macd_value,
        "signal": signal_value,
        "histogram": macd_value - signal_value,
    }


def compute_atr(bars: List[Bar], period: int = ATR_PERIOD) -> Optional[float]:
    """Average True Range with Wilder smoothing; needs ``period + 1`` bars.

    True range includes gaps: max(high-low, |high-prev_close|, |low-prev_close|).
    """
    if period <= 0 or len(bars) < period + 1:
        return None
    true_ranges: List[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        bar = bars[i]
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
        )
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


SWING_LOOKBACK = 20


def compute_swing_low(bars: List[Bar], lookback: int = SWING_LOOKBACK) -> Optional[float]:
    """Lowest traded low of the last ``lookback`` bars — a floor the market
    has already defended once; a support anchor for the level formulas."""
    if not bars or lookback <= 0:
        return None
    return min(bar.low for bar in bars[-lookback:])


def compute_swing_high(bars: List[Bar], lookback: int = SWING_LOOKBACK) -> Optional[float]:
    """Highest traded high of the last ``lookback`` bars — a ceiling the
    market has already rejected once; a resistance anchor for the target."""
    if not bars or lookback <= 0:
        return None
    return max(bar.high for bar in bars[-lookback:])


def compute_avg_volume(bars: List[Bar], lookback: int = SWING_LOOKBACK) -> Optional[float]:
    """Mean daily volume over the last ``lookback`` bars; None when the
    data source ships no volume."""
    if not bars or lookback <= 0:
        return None
    volumes = [bar.volume for bar in bars[-lookback:] if bar.volume is not None and bar.volume > 0]
    if not volumes:
        return None
    return sum(volumes) / len(volumes)


def compute_worst_day_pct_1y(
    closes: List[float], lookback: int = YEAR_BARS
) -> Optional[float]:
    """Worst single daily return (close-to-close) over the last trading
    year, AS A PERCENT — the honest "how bad has one day actually gotten"
    number the gap-risk check stresses with.

    Two corrections over the retired ``worst_day_1y`` (2026-07-26):

    It returns a percent (-16.97), not a raw fraction (-0.1697). Every
    neighbouring field in this payload — ``volatility_pct``, the bias
    readings — is already a percent, and two unit conventions in one
    payload is a misreading waiting to happen, for a reader or an LLM.

    And it honours ``lookback`` instead of scanning every loaded close,
    so a field named for one year cannot quietly report the worst day of
    the two-plus years the bar loader actually fetches.

    Needs at least MIN_RETURNS_FOR_TAIL returns; with fewer observations
    the extreme is noise, so None (loud) beats a fake number.
    """
    if lookback <= 0:
        return None
    window = closes[-(lookback + 1):]
    if len(window) < MIN_RETURNS_FOR_TAIL + 1:
        return None
    returns = [
        window[i] / window[i - 1] - 1.0
        for i in range(1, len(window))
        if window[i - 1] > 0
    ]
    if len(returns) < MIN_RETURNS_FOR_TAIL:
        return None
    return round(min(returns) * 100.0, 2)


def compute_bias(closes: List[float], period: int = BIAS_PERIOD) -> Optional[float]:
    """BIAS: percentage deviation of the latest close from its SMA."""
    sma = compute_sma(closes, period)
    if sma is None or sma == 0.0:
        return None
    return (closes[-1] - sma) / sma * 100.0


def _unwired_bars_loader(symbol: str) -> List[Bar]:
    """Placeholder loader until the tier pipeline wires a real data source."""
    raise RuntimeError(
        "technicals bars_loader not wired yet; inject one built on the "
        "existing data_provider multi-source layer"
    )


class TechnicalsProvider(DimensionProvider):
    """NUMERIC technicals for any market (indicators are market-agnostic).

    No composite score is published (owner decision, 2026-07-26). This
    payload is handed to the LLM stages verbatim, so a code-computed
    0-100 verdict sitting in it would pre-answer the very question those
    stages exist to answer — they anchor on the number instead of reading
    the fields. Old stored runs still carry their ``score``.
    """

    dimension = "technicals"
    kind = SourceKind.NUMERIC

    def __init__(
        self,
        bars_loader: Callable[[str], List[Bar]] = _unwired_bars_loader,
        source_name: str = "ohlcv-bars",
    ) -> None:
        self._bars_loader = bars_loader
        self._source_name = source_name

    def supports(self, market: Market) -> bool:
        return True

    def collect(self, symbol: str) -> DimensionResult:
        try:
            bars = list(self._bars_loader(symbol))
        except Exception as exc:  # fail-loud as a structured result
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                coverage=Coverage.UNAVAILABLE,
                warnings=[f"bars_loader failed for {symbol}: {exc}"],
            )

        if len(bars) < MIN_HISTORY_BARS:
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                coverage=Coverage.UNAVAILABLE,
                warnings=[
                    f"insufficient history for {symbol}: "
                    f"{len(bars)} bars < {MIN_HISTORY_BARS} required"
                ],
            )

        closes = [bar.close for bar in bars]
        atr = compute_atr(bars)
        payload: Dict[str, object] = {
            "close": closes[-1],
            "bars_count": len(bars),
            "sma_20": compute_sma(closes, 20),
            "sma_60": compute_sma(closes, FULL_HISTORY_BARS),
            "ema_12": compute_ema(closes, MACD_FAST),
            "ema_26": compute_ema(closes, MACD_SLOW),
            "rsi_14": compute_wilder_rsi(closes),
            "macd": compute_macd(closes),
            "atr_14": atr,
            # Typical daily swing as % of price — stated here so LLM stages
            # can cite it directly (plan review's volatility check).
            "volatility_pct": (
                round(atr / closes[-1] * 100, 2)
                if atr is not None and closes[-1] > 0
                else None
            ),
            "swing_low_20": compute_swing_low(bars),
            "swing_high_20": compute_swing_high(bars),
            "swing_low_60": compute_swing_low(bars, FULL_HISTORY_BARS),
            "swing_high_60": compute_swing_high(bars, FULL_HISTORY_BARS),
            "high_52w": compute_swing_high(bars, YEAR_BARS),
            "low_52w": compute_swing_low(bars, YEAR_BARS),
            "avg_volume_20": compute_avg_volume(bars),
            "worst_day_pct_1y": compute_worst_day_pct_1y(closes),
            "bias_20": compute_bias(closes),
        }

        missing = [
            key
            for key, value in payload.items()
            if value is None and key not in OPTIONAL_PAYLOAD_KEYS
        ]
        coverage = Coverage.FULL if not missing else Coverage.PARTIAL
        warnings = (
            [f"indicators lacking history: {', '.join(sorted(missing))}"]
            if missing
            else []
        )
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            coverage=coverage,
            payload=payload,
            citations=[Citation(source_name=self._source_name)],
            warnings=warnings,
        )
