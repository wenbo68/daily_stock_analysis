# -*- coding: utf-8 -*-
"""Market detection and provider routing for tiered analysis.

Market detection delegates to ``data_provider.base._market_tag`` — the
repo's single source of truth for symbol->market rules — imported lazily so
that the pure-math indicator modules stay importable without the heavy
data_provider dependency tree.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from .base import DimensionProvider, Market
from .fundamentals_us import FundamentalsUSProvider
from .macro_econ import MacroEconProvider
from .sentiment import SentimentProvider
from .technicals import TechnicalsProvider


def detect_market(symbol: str) -> Market:
    """Map a symbol to its market family via the existing _market_tag rules."""
    from data_provider.base import _market_tag

    tag = _market_tag(symbol)
    try:
        return Market(tag)
    except ValueError:
        return Market.UNKNOWN


def get_providers(
    market: Market,
    bars_loader: Optional[Callable] = None,
) -> List[DimensionProvider]:
    """All dimension providers covering the given market.

    All four dimensions are registered: technicals (all markets),
    fundamentals (US), macro_econ (all markets, shared per-day cache),
    sentiment (all markets, LLM+search+verified citations).

    ``bars_loader`` feeds the technicals provider (production passes the
    data_provider-backed loader; omitting it leaves the unwired default
    that fails loud).
    """
    technicals = (
        TechnicalsProvider(bars_loader=bars_loader)
        if bars_loader is not None
        else TechnicalsProvider()
    )
    candidates: List[DimensionProvider] = [
        technicals,
        FundamentalsUSProvider(),
        MacroEconProvider(),
        SentimentProvider(),
    ]
    return [provider for provider in candidates if provider.supports(market)]
