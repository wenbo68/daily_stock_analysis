# -*- coding: utf-8 -*-
"""Tier pipeline skeleton (docs/tiered-analysis-design.md §4).

Deterministic orchestration: stages run in a fixed order and every failure
surfaces as an explicit UNAVAILABLE report (fail-loud), never an exception
swallowed mid-pipeline.

Tier 1 delegates to the existing DSA single-shot analysis through an
injected ``analysis_runner`` callable so this package never imports the DSA
decision path (boundary rule, design doc §10); production wiring passes a
thin closure over the existing pipeline, tests pass fakes.

Tier 2 (bull/bear debate, v2 slice 4) and Tier 3 (risk stress test,
v2 slice 5) run the tiered package's own LLM engines and degrade to the
previous tier's direction on any failure.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from .providers.base import Coverage, DimensionResult, Market
from .schema import Direction, SniperLevels, TierReport, extract_price

_SNIPER_FIELDS = (
    ("entry", "ideal_buy"),
    ("secondary_entry", "secondary_buy"),
    ("stop_loss", "stop_loss"),
    ("take_profit", "take_profit"),
)


@dataclass
class TierState:
    """Shared state threaded through the tier stages for one symbol."""

    symbol: str
    market: Market
    reports: Dict[int, TierReport] = field(default_factory=dict)
    #: Collected dimension results, set by the orchestration layer so
    #: higher tiers can debate over the evidence (falls back to the
    #: dimensions attached to the tier-1 report when unset).
    dimensions: List[DimensionResult] = field(default_factory=list)


class TierStage(ABC):
    tier: int

    @abstractmethod
    def run(self, state: TierState) -> TierReport:
        """Produce this tier's report; failures return UNAVAILABLE reports."""


def _unwired_analysis_runner(symbol: str) -> Any:
    raise RuntimeError(
        "Tier 1 analysis_runner not wired yet; inject a closure over the "
        "existing DSA analysis pipeline"
    )


def _get(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, Mapping):
        return result.get(key, default)
    return getattr(result, key, default)


class Tier1Stage(TierStage):
    """Four-dimension collection + one LLM synthesis — today's DSA output."""

    tier = 1

    def __init__(
        self,
        analysis_runner: Callable[[str], Any] = _unwired_analysis_runner,
    ) -> None:
        self._analysis_runner = analysis_runner

    def run(self, state: TierState) -> TierReport:
        try:
            result = self._analysis_runner(state.symbol)
        except Exception as exc:
            return TierReport(
                tier=self.tier,
                symbol=state.symbol,
                market=state.market,
                coverage=Coverage.UNAVAILABLE,
                direction=Direction.UNKNOWN,
                warnings=[f"tier-1 analysis failed for {state.symbol}: {exc}"],
            )
        return self._adapt(state, result)

    def _adapt(self, state: TierState, result: Any) -> TierReport:
        warnings: List[str] = []
        levels, level_warnings = self._extract_levels(result)
        warnings.extend(level_warnings)

        score = _get(result, "sentiment_score")
        narrative = _get(result, "operation_advice") or None
        coverage = Coverage.FULL if not warnings else Coverage.PARTIAL
        return TierReport(
            tier=self.tier,
            symbol=state.symbol,
            market=state.market,
            coverage=coverage,
            direction=Direction.from_decision_type(_get(result, "decision_type")),
            confidence=_get(result, "confidence_level"),
            score=int(score) if isinstance(score, (int, float)) else None,
            levels=levels,
            narrative=narrative,
            warnings=warnings,
        )

    @staticmethod
    def _extract_levels(result: Any) -> tuple:
        dashboard = _get(result, "dashboard")
        sniper: Optional[Mapping] = None
        if isinstance(dashboard, Mapping):
            battle_plan = dashboard.get("battle_plan")
            if isinstance(battle_plan, Mapping):
                candidate = battle_plan.get("sniper_points")
                if isinstance(candidate, Mapping):
                    sniper = candidate
        if sniper is None:
            return SniperLevels(), ["sniper points missing from tier-1 result"]

        values: Dict[str, Optional[float]] = {}
        warnings: List[str] = []
        for target, source in _SNIPER_FIELDS:
            raw = sniper.get(source)
            price = extract_price(raw)
            if raw is not None and price is None:
                warnings.append(f"unparseable sniper level {source}={raw!r}")
            values[target] = price
        return SniperLevels(**values), warnings


class Tier2Stage(TierStage):
    """Bull/bear debate over the tier-1 evidence (v2 slice 4).

    The engine is injected for tests; the default is a lazy DebateEngine
    (the tiered package's own LLM call). Any failure — no tier-1 report,
    no evidence, LLM down, unparseable judge — degrades to an UNAVAILABLE
    report whose direction falls back to tier 1, never an exception.
    """

    tier = 2

    def __init__(self, engine: Optional[Any] = None) -> None:
        self._engine = engine

    def run(self, state: TierState) -> TierReport:
        tier1 = state.reports.get(1)
        if tier1 is None:
            return TierReport(
                tier=self.tier,
                symbol=state.symbol,
                market=state.market,
                coverage=Coverage.UNAVAILABLE,
                direction=Direction.UNKNOWN,
                warnings=["tier 2 requires a tier-1 report"],
            )

        dimensions = state.dimensions or tier1.dimensions
        if not dimensions:
            return TierReport(
                tier=self.tier,
                symbol=state.symbol,
                market=state.market,
                coverage=Coverage.UNAVAILABLE,
                direction=tier1.direction,
                levels=tier1.levels,
                warnings=[
                    "no collected evidence to debate — tier 2 skipped, "
                    "direction falls back to tier 1"
                ],
            )

        engine = self._engine
        if engine is None:
            from .debate import DebateEngine

            engine = DebateEngine()
        result = engine.run(state.symbol, tier1, dimensions)

        if result.verdict is None:
            return TierReport(
                tier=self.tier,
                symbol=state.symbol,
                market=state.market,
                coverage=Coverage.UNAVAILABLE,
                direction=tier1.direction,
                score=tier1.score,
                levels=tier1.levels,
                warnings=list(result.warnings)
                + ["debate produced no verdict — direction falls back to tier 1"],
                debate_detail=result.to_detail(),
            )

        verdict = result.verdict
        return TierReport(
            tier=self.tier,
            symbol=state.symbol,
            market=state.market,
            coverage=Coverage.FULL,
            direction=verdict.direction,
            # v3 scored debate: the verdict is computed by formula, so
            # there is no judge confidence to report — the bullishness
            # number lives in debate_detail.verdict.final_score.
            confidence=None,
            score=tier1.score,
            levels=tier1.levels,
            narrative=verdict.summary or None,
            warnings=list(result.warnings),
            debate_detail=result.to_detail(),
        )


class Tier3Stage(TierStage):
    """Risk stress test of the tier-2 verdict (v2 slice 5).

    Same degradation contract as Tier2Stage: no tier-2 report, no
    evidence, or no usable risk verdict → UNAVAILABLE, direction falls
    back to tier 2. A code-validated tightened stop is the only level a
    risk verdict may change; the size multiplier is applied by code in
    the sizing flow (slice 6), never here.
    """

    tier = 3

    def __init__(self, engine: Optional[Any] = None) -> None:
        self._engine = engine

    def run(self, state: TierState) -> TierReport:
        tier2 = state.reports.get(2)
        if tier2 is None:
            return TierReport(
                tier=self.tier,
                symbol=state.symbol,
                market=state.market,
                coverage=Coverage.UNAVAILABLE,
                direction=Direction.UNKNOWN,
                warnings=["tier 3 requires a tier-2 report"],
            )

        tier1 = state.reports.get(1)
        dimensions = state.dimensions or (tier1.dimensions if tier1 else [])
        if not dimensions:
            return TierReport(
                tier=self.tier,
                symbol=state.symbol,
                market=state.market,
                coverage=Coverage.UNAVAILABLE,
                direction=tier2.direction,
                levels=tier2.levels,
                warnings=[
                    "no collected evidence for the risk stress test — tier 3 "
                    "skipped, direction falls back to tier 2"
                ],
            )

        engine = self._engine
        if engine is None:
            from .risk import RiskEngine

            engine = RiskEngine()
        result = engine.run(state.symbol, tier2, dimensions)

        if result.verdict is None:
            return TierReport(
                tier=self.tier,
                symbol=state.symbol,
                market=state.market,
                coverage=Coverage.UNAVAILABLE,
                direction=tier2.direction,
                score=tier2.score,
                levels=tier2.levels,
                warnings=list(result.warnings)
                + ["risk stress produced no verdict — direction falls back to tier 2"],
                risk_detail=result.to_detail(),
            )

        verdict = result.verdict
        levels = tier2.levels
        if verdict.tightened_stop is not None:
            # Already code-validated (strictly between current stop and entry).
            levels = SniperLevels(
                entry=levels.entry,
                secondary_entry=levels.secondary_entry,
                stop_loss=verdict.tightened_stop,
                take_profit=levels.take_profit,
            )
        return TierReport(
            tier=self.tier,
            symbol=state.symbol,
            market=state.market,
            coverage=Coverage.FULL,
            direction=verdict.stance,
            confidence=(
                f"{verdict.confidence:.2f}" if verdict.confidence is not None else None
            ),
            score=tier2.score,
            levels=levels,
            narrative=verdict.summary or None,
            warnings=list(result.warnings),
            risk_detail=result.to_detail(),
        )


class TieredPipeline:
    """Runs stages 1..N in order, recording each tier's report in the state."""

    def __init__(
        self,
        tier1: Optional[Tier1Stage] = None,
        tier2: Optional[Tier2Stage] = None,
        tier3: Optional[Tier3Stage] = None,
    ) -> None:
        self._stages: List[TierStage] = [
            tier1 or Tier1Stage(),
            tier2 or Tier2Stage(),
            tier3 or Tier3Stage(),
        ]

    def run(self, symbol: str, market: Market, up_to_tier: int = 1) -> TierState:
        supported = [stage.tier for stage in self._stages]
        if up_to_tier not in supported:
            raise ValueError(
                f"up_to_tier must be one of {supported}, got {up_to_tier}"
            )
        state = TierState(symbol=symbol, market=market)
        for stage in self._stages:
            if stage.tier > up_to_tier:
                break
            state.reports[stage.tier] = stage.run(state)
        return state
