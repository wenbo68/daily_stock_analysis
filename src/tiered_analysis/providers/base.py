# -*- coding: utf-8 -*-
"""Provider contract for tiered analysis (docs/tiered-analysis-design.md §5).

Core rule (§1): every tradeable number is produced by deterministic code
(NUMERIC); LLM+search output (TEXTUAL) carries citations and never feeds
numeric consumers such as position sizing. ``DimensionResult.is_actionable``
is the gate numeric consumers must check.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Market(str, Enum):
    """Market family tags, mirroring data_provider.base._market_tag values."""

    CN = "cn"
    US = "us"
    HK = "hk"
    JP = "jp"
    KR = "kr"
    TW = "tw"
    UNKNOWN = "unknown"


class SourceKind(str, Enum):
    NUMERIC = "numeric"
    TEXTUAL = "textual"


class Coverage(str, Enum):
    """Explicit degradation: providers never silently return blanks."""

    FULL = "full"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Citation:
    """A verifiable reference.

    NUMERIC dimensions cite their data source; TEXTUAL dimensions cite
    articles. A citation URL must be the product of a real fetch performed
    by a tool, never a model-asserted URL.
    """

    source_name: str
    url: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    retrieved_at: Optional[str] = None


@dataclass(frozen=True)
class DimensionResult:
    """Unified return body for every dimension provider."""

    dimension: str
    kind: SourceKind
    coverage: Coverage
    payload: Optional[Dict[str, Any]] = None
    narrative: Optional[str] = None
    citations: List[Citation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """True only for NUMERIC results carrying real data.

        Numeric consumers (e.g. future position sizing) must gate on this so
        thin or degraded data can never silently flow into a share count.
        """
        return (
            self.kind == SourceKind.NUMERIC
            and self.coverage != Coverage.UNAVAILABLE
            and bool(self.payload)
        )


class DimensionProvider(ABC):
    """One implementation per (dimension x market family)."""

    dimension: str
    kind: SourceKind

    @abstractmethod
    def supports(self, market: Market) -> bool:
        """Whether this provider covers the given market family."""

    @abstractmethod
    def collect(self, symbol: str) -> DimensionResult:
        """Collect this dimension for one symbol.

        Failures must surface as ``Coverage.UNAVAILABLE`` results with
        warnings (fail-loud), never as raised exceptions or silent blanks.
        """
