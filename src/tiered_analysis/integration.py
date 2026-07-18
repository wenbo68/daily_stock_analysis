# -*- coding: utf-8 -*-
"""Production wiring for tiered analysis.

This module makes the real connections the slices deliberately left
open, always as a CLIENT of existing DSA layers (boundary rule: never
import into or modify the decision path itself):

- ``dsa_bars_loader``: daily OHLCV bars for the technicals provider via
  ``DataFetcherManager`` (the existing multi-source failover layer).
- ``dsa_analysis_runner``: Tier 1 delegate — runs the existing DSA
  single-stock analysis via ``StockAnalysisPipeline`` with notifications
  off and returns the raw ``AnalysisResult``.
- ``run_tiered_analysis``: the one-call orchestrator — collect the four
  dimensions, run tiers 1..depth (v2 slice 6: depth 2 adds the bull/bear
  debate, depth 3 the risk stress test), replace the LLM-prose levels
  with formula bases + validated AI adjustments, compute the position
  size when the user's sizing settings are present, track the run's own
  LLM call/token usage, and log the deepest tier's recommendation into
  the existing decision-signal system.

Everything is injectable so tests stay offline; the defaults are the real
DSA layers.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .adjustments import LevelAdjuster
from .levels import (
    apply_adjustments,
    bases_from_dimensions,
    decisions_to_detail,
    decisions_to_sniper,
)
from .llm_support import LlmUsageTracker
from .providers.base import (
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
)
from .providers.registry import detect_market, get_providers
from .providers.technicals import Bar
from .risk import apply_size_multiplier
from .schema import Direction, SizingSlots, TierReport
from .settings import SizingSettings, load_sizing_settings, merge_overrides
from .signal_log import SignalLogResult, log_tier_report
from .sizing import SizingInputs, lot_size_for, size_position
from .tiers import Tier1Stage, Tier2Stage, Tier3Stage, TieredPipeline, TierState

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


#: Supported analysis depths: 1 = tier 1 only (v1 behavior), 2 = + debate,
#: 3 = + risk stress test.
SUPPORTED_DEPTHS = (1, 2, 3)


@dataclass(frozen=True)
class TieredRunOutcome:
    """Everything one tiered run produced.

    ``report`` stays the tier-1 report (it carries the dimension results
    the web cards render from); ``final_report`` is the deepest tier that
    ran — the same object at depth 1.
    """

    report: TierReport
    state: TierState
    signal: Optional[SignalLogResult]
    depth: int = 1
    final_report: Optional[TierReport] = None
    #: Sizing block (v2 slice 6): share count or explicit refusal reason.
    sizing: Optional[Dict[str, Any]] = None
    #: This run's own LLM call/token counts per stage (tier 1 excluded —
    #: its synthesis runs inside the DSA pipeline).
    llm_usage: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.final_report is None:
            object.__setattr__(self, "final_report", self.report)


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


def _risk_multiplier(state: TierState) -> Optional[float]:
    """The tier-3 judge's size multiplier, if a usable verdict exists."""
    report = state.reports.get(3)
    if report is None or not report.risk_detail:
        return None
    verdict = report.risk_detail.get("verdict") or {}
    value = verdict.get("size_multiplier")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _sizing_block(
    final: TierReport,
    market: Market,
    settings: SizingSettings,
    risk_multiplier: Optional[float],
) -> Tuple[Dict[str, Any], SizingSlots]:
    """Deterministic sizing of the deepest tier's call (v2 slices 1+6).

    The engine runs even when settings are absent so the UI gets an
    explicit ``sizing_off`` refusal instead of a missing section. The
    tier-3 multiplier is applied by code here — never by the LLM — and a
    multiplier of 0 keeps the slots filled with 0 shares ("the direction
    stands but do not open"), which is a statement, not an omission.
    """
    inputs = SizingInputs(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        entry=final.levels.entry,
        stop_loss=final.levels.stop_loss,
        direction=final.direction,
        market=market,
        max_position_fraction=settings.max_position_fraction,
        fee_fraction=settings.fee_fraction,
    )
    result = size_position(inputs)

    notes = list(result.notes) + list(settings.warnings)
    shares = result.shares
    shares_before_multiplier = None
    position_value = result.position_value
    risk_amount = result.risk_amount
    if result.is_sized and risk_multiplier is not None:
        shares_before_multiplier = result.shares
        # The multiplier is enum-validated by the risk parser; an
        # off-enum value here means a broken internal contract, and
        # apply_size_multiplier raising loudly is the right outcome.
        shares = apply_size_multiplier(
            result.shares, risk_multiplier, lot_size=result.lot_size
        )
        position_value = shares * inputs.entry
        risk_amount = shares * result.loss_per_share
        if shares == 0:
            notes.append(
                "Risk multiplier 0: the direction stands, but the risk "
                "judge says do not open a position now."
            )
        elif shares != shares_before_multiplier:
            notes.append(
                f"Risk stress verdict scaled the position to "
                f"{risk_multiplier:g}x of the computed size."
            )

    # A sell verdict on a stock the user holds gets a concrete exit size:
    # the held shares, scaled by the tier-3 multiplier when one exists
    # (no tier 3 → the full holding; a sell verdict means exit). This
    # needs no capital/risk settings — the count IS the holding.
    ownership = settings.ownership
    sell_shares = None
    sell_shares_before_multiplier = None
    if final.direction is Direction.SELL and ownership > 0:
        sell_shares = ownership
        if risk_multiplier is not None:
            sell_shares_before_multiplier = ownership
            sell_shares = apply_size_multiplier(
                ownership, risk_multiplier, lot_size=lot_size_for(market)
            )
            if sell_shares == 0:
                notes.append(
                    "Risk multiplier 0: the sell verdict stands, but the "
                    "risk stress says do not reduce the holding now."
                )
            elif sell_shares != ownership:
                notes.append(
                    f"Risk stress verdict scaled the exit to "
                    f"{risk_multiplier:g}x of the held shares."
                )

    detail: Dict[str, Any] = {
        "enabled": settings.is_enabled,
        "shares": shares,
        "shares_before_multiplier": shares_before_multiplier,
        "risk_multiplier": risk_multiplier,
        "ownership": ownership,
        "sell_shares": sell_shares,
        "sell_shares_before_multiplier": sell_shares_before_multiplier,
        "position_value": position_value,
        "risk_amount": risk_amount,
        "loss_per_share": result.loss_per_share,
        "lot_size": result.lot_size,
        "cap_applied": result.cap_applied,
        "reason_code": result.reason_code.value if result.reason_code else None,
        "refusal_reason": result.refusal_reason,
        "notes": notes,
        "inputs": {
            "capital": settings.capital,
            "risk_fraction": settings.risk_fraction,
            "max_position_fraction": settings.max_position_fraction,
            "fee_fraction": settings.fee_fraction,
            "entry": final.levels.entry,
            "stop_loss": final.levels.stop_loss,
        },
    }

    if not result.is_sized:
        return detail, SizingSlots()
    return detail, SizingSlots(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        shares=float(shares),
    )


def run_tiered_analysis(
    symbol: str,
    market: Optional[Market] = None,
    providers: Optional[Sequence[DimensionProvider]] = None,
    analysis_runner: Optional[Callable[[str], Any]] = None,
    signal_logger: Callable[..., Any] = log_tier_report,
    log_signal: bool = True,
    trace_id: Optional[str] = None,
    level_adjuster: Optional[Any] = None,
    depth: int = 1,
    sizing_settings: Optional[SizingSettings] = None,
    sizing_overrides: Optional[Mapping[str, Any]] = None,
    tier2_stage: Optional[Tier2Stage] = None,
    tier3_stage: Optional[Tier3Stage] = None,
) -> TieredRunOutcome:
    """Run tiers 1..``depth`` for one symbol with full production wiring.

    Collects the four dimensions, runs tier 1, replaces the LLM-prose
    price levels with deterministic bases + validated AI adjustments
    (v2 slice 3, anchor-and-adjust), attaches the dimension results
    (with merged coverage) to the tier-1 report, then — per ``depth`` —
    runs the tier-2 debate and tier-3 risk stress test, sizes the deepest
    tier's call (settings absent → explicit ``sizing_off`` refusal), and,
    unless ``log_signal`` is False, records the deepest tier's
    recommendation in the existing decision-signal system.

    ``sizing_overrides`` may carry per-run ``capital`` / ``risk_fraction``
    values (the API's per-run override) on top of the saved settings.
    """
    if depth not in SUPPORTED_DEPTHS:
        raise ValueError(f"depth must be one of {SUPPORTED_DEPTHS}, got {depth}")
    if market is None:
        market = detect_market(symbol)
    if providers is None:
        providers = get_providers(market, bars_loader=dsa_bars_loader)
    if analysis_runner is None:
        analysis_runner = dsa_analysis_runner
    if level_adjuster is None:
        level_adjuster = LevelAdjuster()
    if sizing_settings is None:
        sizing_settings = load_sizing_settings()
    if sizing_overrides:
        sizing_settings = merge_overrides(
            sizing_settings,
            capital=sizing_overrides.get("capital"),
            risk_fraction=sizing_overrides.get("risk_fraction"),
            ownership=sizing_overrides.get("ownership"),
        )

    tracker = LlmUsageTracker()
    with tracker.activate():
        dimensions = _collect_dimensions(providers, symbol)

        pipeline = TieredPipeline(tier1=Tier1Stage(analysis_runner=analysis_runner))
        state = pipeline.run(symbol, market, up_to_tier=1)

        # Anchor-and-adjust levels: formula bases from the technicals payload,
        # bounded evidence-cited LLM adjustments, code re-validation. This
        # intentionally replaces the DSA sniper levels (LLM prose) as the
        # report's tradeable numbers; the audit trail lands in levels_detail.
        bases = bases_from_dimensions(dimensions)
        with tracker.stage("level_adjuster"):
            proposals, adjuster_warnings = level_adjuster.propose(
                symbol, bases, dimensions
            )
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
        state.dimensions = list(dimensions)
        state.ownership = sizing_settings.ownership

        final = report
        if depth >= 2:
            with tracker.stage("tier2_debate"):
                final = (tier2_stage or Tier2Stage()).run(state)
            state.reports[2] = final
        if depth >= 3:
            with tracker.stage("tier3_risk"):
                final = (tier3_stage or Tier3Stage()).run(state)
            state.reports[3] = final

    sizing_detail, sizing_slots = _sizing_block(
        final, market, sizing_settings, _risk_multiplier(state)
    )
    final = replace(final, sizing=sizing_slots)
    if not final.dimensions:
        # Tier 2/3 reports are built lean; the deepest report carries the
        # evidence so the signal ledger and consumers see it.
        final = replace(final, dimensions=list(dimensions))
    state.reports[final.tier] = final
    if final.tier == 1:
        report = final

    signal: Optional[SignalLogResult] = None
    if log_signal:
        signal = signal_logger(final, trace_id=trace_id)

    return TieredRunOutcome(
        report=report,
        state=state,
        signal=signal,
        depth=depth,
        final_report=final,
        sizing=sizing_detail,
        llm_usage=tracker.to_detail(),
    )
