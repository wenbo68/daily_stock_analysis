# -*- coding: utf-8 -*-
"""Tier report envelope (docs/tiered-analysis-design.md §3.1, §4).

v1 outputs direction only. The sizing slots (capital / risk_fraction /
shares) are reserved in the schema from day one but stay empty until the
deterministic sizing engine lands in v2 — printing a share count creates an
obligation to justify it with a backtest, which v1 does not have.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .providers.base import Coverage, DimensionResult, Market


class Direction(str, Enum):
    """Normalized trade direction, mapped from DSA's decision_type."""

    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    UNKNOWN = "unknown"

    @classmethod
    def from_decision_type(cls, value: Optional[str]) -> "Direction":
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.UNKNOWN


def coerce_price(value: object) -> Optional[float]:
    """Best-effort float from DSA's str|int|float price fields.

    DSA sniper-point values may be numbers, numeric strings, or markers
    like "N/A". Anything non-numeric becomes None — callers must surface a
    warning rather than let a bad level pass silently.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


@dataclass(frozen=True)
class SizingSlots:
    """Reserved position-sizing fields — intentionally always empty in v1."""

    capital: Optional[float] = None
    risk_fraction: Optional[float] = None
    shares: Optional[float] = None

    @property
    def is_empty(self) -> bool:
        return self.capital is None and self.risk_fraction is None and self.shares is None


@dataclass(frozen=True)
class SniperLevels:
    """Normalized price levels from DSA's sniper points."""

    entry: Optional[float] = None
    secondary_entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass(frozen=True)
class TierReport:
    """Output of one tier for one symbol: report + decision."""

    tier: int
    symbol: str
    market: Market
    coverage: Coverage
    direction: Direction
    confidence: Optional[str] = None
    score: Optional[int] = None
    levels: SniperLevels = field(default_factory=SniperLevels)
    narrative: Optional[str] = None
    dimensions: List[DimensionResult] = field(default_factory=list)
    sizing: SizingSlots = field(default_factory=SizingSlots)
    warnings: List[str] = field(default_factory=list)
