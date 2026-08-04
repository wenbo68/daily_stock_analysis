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

from .cross_fields import enrich_cross_fields
from .earnings import EarningsInfo, earnings_from_dimensions
from .levels import (
    apply_adjustments,
    bases_from_dimensions,
    decisions_to_detail,
    decisions_to_sniper,
)
from .llm_support import LlmUsageTracker
from .plan_review import review_plan, sizing_detail_dict
from .providers.base import (
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
)
from .providers.registry import detect_market, get_providers
from .providers.technicals import Bar, read_metric
from .schema import (
    Action,
    Direction,
    Outlook,
    SizingSlots,
    TierReport,
    derive_action,
)
from .settings import (
    SizingSettings,
    load_sizing_settings,
    merge_overrides,
    with_fallback_defaults,
)
from .signal_log import SignalLogResult, log_tier_report
from .sizing import SizingInputs, size_position
from .tiers import Tier1Stage, Tier2Stage, TierState

logger = logging.getLogger(__name__)

#: Calendar days of daily bars to request — comfortably covers the ~250
#: trading bars the 52-week high/low needs (weekends/holidays included).
BARS_CALENDAR_DAYS = 400


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


#: Supported analysis depths: 1 = the one-blob judge, 2 = the evidence
#: vote (which no longer runs the tier-1 blob at all — the debate is the
#: judge). Tier 3 is retired (outlook redesign, 2026-07-20).
SUPPORTED_DEPTHS = (1, 2)


@dataclass(frozen=True)
class TieredRunOutcome:
    """Everything one tiered run produced.

    ``report`` stays the tier-1/foundation report (it carries the
    dimension results the web cards render from); ``final_report`` is the
    deepest tier that ran — the same object at depth 1.
    """

    report: TierReport
    state: TierState
    signal: Optional[SignalLogResult]
    depth: int = 1
    final_report: Optional[TierReport] = None
    #: Sizing block (v2 slice 6): share count or explicit refusal reason.
    sizing: Optional[Dict[str, Any]] = None
    #: This run's own LLM call/token counts per stage (the depth-1 blob
    #: excluded — its synthesis runs inside the DSA pipeline).
    llm_usage: Optional[Dict[str, Any]] = None
    #: Outlook redesign: the impersonal judgment + the personal action
    #: (outlook × ownership code table).
    outlook: Outlook = Outlook.UNKNOWN
    action: Action = Action.UNKNOWN
    #: Next earnings date, read from the fundamentals payload (display
    #: lives on the fundamentals card; the debate weighs the event risk).
    earnings: Optional[EarningsInfo] = None
    #: Retired display-only risk card (2026-07-22) — always None on new
    #: runs; the field survives so old consumers keep a stable shape.
    risk_card: Optional[list] = None
    #: Plan review (2026-07-22): structured per-column warnings for the
    #: trade-plan card — {"entry"|"stop_loss"|"take_profit"|"shares":
    #: [{"id", "values"}]}. None when the run produced no buy plan.
    plan_warnings: Optional[Dict[str, Any]] = None

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
            return read_metric(dim.payload, "volatility", "atr_14")
    return None


#: The run-detail earnings block reads the same shared helper the plan
#: review's earnings gate uses (moved to earnings.py, 2026-07-27).
_earnings_from_dimensions = earnings_from_dimensions


def _sizing_block(
    final: TierReport,
    market: Market,
    settings: SizingSettings,
) -> Tuple[Dict[str, Any], SizingSlots]:
    """Deterministic sizing of the deepest tier's call (v2 slices 1+6).

    The engine runs even when settings are absent so the UI gets an
    explicit ``sizing_off`` refusal instead of a missing section.
    Outlook redesign: the tier-3 multiplier is gone — a bearish outlook
    on a held stock exits the FULL holding (reducing risk needs no
    permission), and the buy size comes from the formula + caps alone.
    """
    inputs = SizingInputs(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        entry=final.levels.entry,
        stop_loss=final.levels.stop_loss,
        direction=final.direction,
        market=market,
    )
    result = size_position(inputs)

    # A bearish outlook on a stock the user holds gets a concrete exit
    # size: the full holding. This needs no capital/risk settings — the
    # count IS the holding.
    ownership = settings.ownership
    sell_shares = None
    if final.direction is Direction.SELL and ownership > 0:
        sell_shares = ownership

    detail = sizing_detail_dict(
        settings, result, final.levels, ownership, sell_shares
    )

    if not result.is_sized:
        return detail, SizingSlots()
    return detail, SizingSlots(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        shares=float(result.shares),
    )


def run_tiered_analysis(
    symbol: str,
    market: Optional[Market] = None,
    providers: Optional[Sequence[DimensionProvider]] = None,
    analysis_runner: Optional[Callable[[str], Any]] = None,
    signal_logger: Callable[..., Any] = log_tier_report,
    log_signal: bool = True,
    trace_id: Optional[str] = None,
    depth: int = 1,
    sizing_settings: Optional[SizingSettings] = None,
    sizing_overrides: Optional[Mapping[str, Any]] = None,
    tier2_stage: Optional[Tier2Stage] = None,
    earnings_lookup: Optional[Callable[[str, Market], EarningsInfo]] = None,
    plan_summarizer: Optional[Callable[[str], str]] = None,
    cross_bars_loader: Optional[Callable[[str], List[Bar]]] = None,
) -> TieredRunOutcome:
    """Run one symbol at ``depth`` with full production wiring.

    Pipeline (plan-review redesign, 2026-07-22): data layer (four
    dimensions; fundamentals carries the next earnings date) → formula
    levels → the chosen judge (depth 1 = the DSA one-blob synthesis;
    depth 2 = the evidence vote, WITHOUT running the blob) → on a BUY
    verdict, the AI plan review (deterministic checks may trim shares /
    move stop / move target, with cited reasons, and produce the
    trade-plan card's structured warnings) → outlook + action (code
    table over ownership) → sizing. Unless ``log_signal`` is False, the
    deepest tier's recommendation lands in the decision-signal system.

    ``sizing_overrides`` may carry per-run ``capital`` / ``risk_fraction``
    / ``ownership`` values (the API's per-run override) on top of the
    saved settings. ``earnings_lookup`` is a test seam; production reads
    the date the fundamentals provider already fetched.
    ``cross_bars_loader`` is a test/demo seam: injected providers skip
    the cross-provider enrichment unless a loader is passed explicitly.
    """
    if depth not in SUPPORTED_DEPTHS:
        raise ValueError(f"depth must be one of {SUPPORTED_DEPTHS}, got {depth}")
    if market is None:
        market = detect_market(symbol)
    # Cross-provider enrichment (sector comparison, implied/realized
    # ratio) runs only with production wiring: injected providers mean
    # a test harness whose canned payloads must pass through untouched
    # — unless the harness opts in with its own ``cross_bars_loader``.
    if providers is None:
        providers = get_providers(market, bars_loader=dsa_bars_loader)
        if cross_bars_loader is None:
            cross_bars_loader = dsa_bars_loader
    if analysis_runner is None:
        analysis_runner = dsa_analysis_runner
    if sizing_settings is None:
        sizing_settings = load_sizing_settings()
    if sizing_overrides:
        sizing_settings = merge_overrides(
            sizing_settings,
            capital=sizing_overrides.get("capital"),
            risk_fraction=sizing_overrides.get("risk_fraction"),
            ownership=sizing_overrides.get("ownership"),
            reward_risk=sizing_overrides.get("reward_risk"),
        )
    # Every run sizes (owner decision 2026-07-24): missing capital/risk
    # fall back to the web form's defaults instead of disabling sizing.
    sizing_settings = with_fallback_defaults(sizing_settings)
    tracker = LlmUsageTracker()
    with tracker.activate():
        dimensions = _collect_dimensions(providers, symbol)
        dimensions = enrich_cross_fields(dimensions, cross_bars_loader)

        # Formula-only levels: deterministic bases from the technicals
        # payload; the adjustment machinery runs with zero proposals so
        # the audit-trail shape (base/formula/inputs per level) stays.
        bases = bases_from_dimensions(
            dimensions, reward_risk=sizing_settings.reward_risk
        )
        decisions, adjust_warnings = apply_adjustments(
            bases, [], atr=_technicals_atr(dimensions)
        )
        level_warnings = list(bases.warnings) + adjust_warnings
        levels = decisions_to_sniper(decisions)
        levels_detail = decisions_to_detail(decisions, level_warnings)

        # The next earnings date rides in the fundamentals payload (the
        # provider fetched it); the injectable lookup is a test seam.
        earnings = (
            earnings_lookup(symbol, market)
            if earnings_lookup is not None
            else _earnings_from_dimensions(dimensions)
        )
        extra_warnings = level_warnings

        state = TierState(symbol=symbol, market=market)
        if depth == 1:
            tier1 = Tier1Stage(analysis_runner=analysis_runner).run(state)
            report = replace(
                tier1,
                dimensions=dimensions,
                coverage=_merge_coverage(tier1.coverage, dimensions),
                levels=levels,
                levels_detail=levels_detail,
                warnings=list(tier1.warnings) + extra_warnings,
            )
        else:
            # Depth 2 skips the one-blob call entirely: the debate is the
            # judge, so the foundation report is the data layer + levels
            # with no verdict of its own. That is the documented depth-2
            # contract, not a data problem — so no warning for it.
            report = TierReport(
                tier=1,
                symbol=symbol,
                market=market,
                coverage=_merge_coverage(Coverage.FULL, dimensions),
                direction=Direction.UNKNOWN,
                levels=levels,
                levels_detail=levels_detail,
                dimensions=dimensions,
                warnings=extra_warnings,
            )
        state.reports[1] = report
        state.dimensions = list(dimensions)
        state.ownership = sizing_settings.ownership

        final = report
        if depth >= 2:
            with tracker.stage("tier2_debate"):
                final = (tier2_stage or Tier2Stage()).run(state)
            state.reports[2] = final

        # AI plan review (BUY verdicts only): the deterministic checks
        # may trim the share count or move stop/target with cited
        # reasons, and produce the plan card's structured warnings.
        review = None
        if final.direction is Direction.BUY and bases.get("entry") is not None:
            with tracker.stage("plan_adjust"):
                review = review_plan(
                    symbol, dimensions, bases, final.direction, market,
                    sizing_settings, ownership=sizing_settings.ownership,
                    summarizer=plan_summarizer,
                )

    plan_warnings: Optional[Dict[str, Any]] = None
    if review is not None:
        depth1_same = final is report
        # Review warnings land on the foundation report only (the plan
        # card's notes); the tier-2 card keeps its own warnings.
        report = replace(
            report,
            levels=review.levels,
            levels_detail=review.levels_detail,
            warnings=list(report.warnings) + list(review.warnings),
        )
        final = report if depth1_same else replace(
            final, levels=review.levels, levels_detail=review.levels_detail
        )
        state.reports[1] = report
        sizing_detail, sizing_slots = review.sizing_detail, review.sizing_slots
        plan_warnings = review.plan_warnings
    else:
        sizing_detail, sizing_slots = _sizing_block(final, market, sizing_settings)
    final = replace(final, sizing=sizing_slots)
    if not final.dimensions:
        # Tier-2 reports are built lean; the deepest report carries the
        # evidence so the signal ledger and consumers see it.
        final = replace(final, dimensions=list(dimensions))
    state.reports[final.tier] = final
    if final.tier == 1:
        report = final

    outlook = Outlook.from_direction(final.direction)
    action = derive_action(outlook, sizing_settings.ownership)

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
        outlook=outlook,
        action=action,
        earnings=earnings,
        plan_warnings=plan_warnings,
    )
