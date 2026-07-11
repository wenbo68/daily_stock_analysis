# -*- coding: utf-8 -*-
"""Production wiring for tiered analysis v1.

This module makes the three real connections the slices deliberately left
open, always as a CLIENT of existing DSA layers (boundary rule: never
import into or modify the decision path itself):

- ``dsa_bars_loader``: daily OHLCV bars for the technicals provider via
  ``DataFetcherManager`` (the existing multi-source failover layer).
- ``dsa_analysis_runner``: Tier 1 delegate — runs the existing DSA
  single-stock analysis via ``StockAnalysisPipeline`` with notifications
  off and returns the raw ``AnalysisResult``.
- ``run_tiered_analysis``: the one-call orchestrator — collect the four
  dimensions, run the tier pipeline, merge coverage, attach dimensions to
  the tier-1 report, and log the recommendation into the existing
  decision-signal system (visible on the web decision-signals page).

Everything is injectable so tests stay offline; the defaults are the real
DSA layers.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable, List, Optional, Sequence

from .adjustments import LevelAdjuster
from .levels import (
    apply_adjustments,
    bases_from_dimensions,
    decisions_to_detail,
    decisions_to_sniper,
)
from .providers.base import (
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
)
from .providers.registry import detect_market, get_providers
from .providers.technicals import Bar
from .schema import TierReport
from .signal_log import SignalLogResult, log_tier_report
from .tiers import Tier1Stage, TieredPipeline, TierState

logger = logging.getLogger(__name__)

#: Calendar days of daily bars to request — comfortably covers the 60
#: trading bars the technicals score needs (weekends/holidays included).
BARS_CALENDAR_DAYS = 120


def dsa_bars_loader(symbol: str, manager: Any = None) -> List[Bar]:
    """Daily bars via DSA's multi-source data layer, oldest first."""
    if manager is None:
        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager()

    df, _source = manager.get_daily_data(symbol, days=BARS_CALENDAR_DAYS)
    if df is None or df.empty:
        return []

    frame = df.dropna(subset=["open", "high", "low", "close"])
    frame = frame.sort_values("date")
    return [
        Bar(
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            open=float(row["open"]),
            volume=float(row["volume"]) if row.get("volume") is not None else None,
            date=str(row["date"]),
        )
        for row in frame.to_dict("records")
    ]


def dsa_analysis_runner(symbol: str) -> Any:
    """Run the existing DSA single-stock analysis as a client.

    Returns the raw ``AnalysisResult`` (Tier1Stage adapts it). Raises on a
    None result so Tier1Stage converts the failure into an UNAVAILABLE
    report instead of a silent blank.
    """
    from src.core.pipeline import StockAnalysisPipeline

    pipeline = StockAnalysisPipeline(
        query_id=uuid.uuid4().hex,
        query_source="tiered_analysis",
    )
    result = pipeline.process_single_stock(
        code=symbol,
        single_stock_notify=False,
    )
    if result is None:
        raise RuntimeError(f"DSA analysis returned no result for {symbol}")
    return result


@dataclass(frozen=True)
class TieredRunOutcome:
    """Everything one tiered run produced."""

    report: TierReport
    state: TierState
    signal: Optional[SignalLogResult]


def _merge_coverage(report: Coverage, dimensions: Sequence[DimensionResult]) -> Coverage:
    """Overall coverage: full only if everything is full; honest otherwise."""
    statuses = [report] + [dim.coverage for dim in dimensions]
    if all(status == Coverage.FULL for status in statuses):
        return Coverage.FULL
    if all(status == Coverage.UNAVAILABLE for status in statuses):
        return Coverage.UNAVAILABLE
    return Coverage.PARTIAL


def _collect_dimensions(
    providers: Sequence[DimensionProvider], symbol: str
) -> List[DimensionResult]:
    results: List[DimensionResult] = []
    for provider in providers:
        try:
            results.append(provider.collect(symbol))
        except Exception as exc:  # providers are fail-loud, but belt+braces
            results.append(
                DimensionResult(
                    dimension=provider.dimension,
                    kind=provider.kind,
                    coverage=Coverage.UNAVAILABLE,
                    warnings=[f"{provider.dimension} provider crashed: {exc}"],
                )
            )
    return results


def _technicals_atr(dimensions: Sequence[DimensionResult]) -> Optional[float]:
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            value = dim.payload.get("atr_14")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def run_tiered_analysis(
    symbol: str,
    market: Optional[Market] = None,
    providers: Optional[Sequence[DimensionProvider]] = None,
    analysis_runner: Optional[Callable[[str], Any]] = None,
    signal_logger: Callable[..., Any] = log_tier_report,
    log_signal: bool = True,
    trace_id: Optional[str] = None,
    level_adjuster: Optional[Any] = None,
) -> TieredRunOutcome:
    """Run tier 1 for one symbol with full production wiring.

    Collects the four dimensions, runs the tier pipeline, replaces the
    LLM-prose price levels with deterministic bases + validated AI
    adjustments (v2 slice 3, anchor-and-adjust), attaches the dimension
    results (with merged coverage) to the tier-1 report, and — unless
    ``log_signal`` is False — records the recommendation in the existing
    decision-signal system.
    """
    if market is None:
        market = detect_market(symbol)
    if providers is None:
        providers = get_providers(market, bars_loader=dsa_bars_loader)
    if analysis_runner is None:
        analysis_runner = dsa_analysis_runner
    if level_adjuster is None:
        level_adjuster = LevelAdjuster()

    dimensions = _collect_dimensions(providers, symbol)

    pipeline = TieredPipeline(tier1=Tier1Stage(analysis_runner=analysis_runner))
    state = pipeline.run(symbol, market, up_to_tier=1)

    # Anchor-and-adjust levels: formula bases from the technicals payload,
    # bounded evidence-cited LLM adjustments, code re-validation. This
    # intentionally replaces the DSA sniper levels (LLM prose) as the
    # report's tradeable numbers; the audit trail lands in levels_detail.
    bases = bases_from_dimensions(dimensions)
    proposals, adjuster_warnings = level_adjuster.propose(symbol, bases, dimensions)
    decisions, adjust_warnings = apply_adjustments(
        bases, proposals, atr=_technicals_atr(dimensions)
    )
    level_warnings = list(bases.warnings) + adjuster_warnings + adjust_warnings

    tier1 = state.reports[1]
    report = replace(
        tier1,
        dimensions=dimensions,
        coverage=_merge_coverage(tier1.coverage, dimensions),
        levels=decisions_to_sniper(decisions),
        levels_detail=decisions_to_detail(decisions, level_warnings),
        warnings=list(tier1.warnings) + level_warnings,
    )
    state.reports[1] = report

    signal: Optional[SignalLogResult] = None
    if log_signal:
        signal = signal_logger(report, trace_id=trace_id)

    return TieredRunOutcome(report=report, state=state, signal=signal)
