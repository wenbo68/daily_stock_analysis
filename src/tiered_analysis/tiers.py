# -*- coding: utf-8 -*-
"""Tier pipeline skeleton (docs/tiered-analysis-design.md §4).

Deterministic orchestration: stages run in a fixed order and every failure
surfaces as an explicit UNAVAILABLE report (fail-loud), never an exception
swallowed mid-pipeline.

Tier 1 delegates to the existing DSA single-shot analysis through an
injected ``analysis_runner`` callable so this package never imports the DSA
decision path (boundary rule, design doc §10); production wiring passes a
thin closure over the existing pipeline, tests pass fakes.

Tier 2 (the evidence vote) runs the tiered package's own LLM engine.
Outlook redesign (2026-07-20): tier 3 is retired — the deterministic
risk card replaced it — and a failed tier-2 debate no longer falls back
to the tier-1 one-blob verdict; the run fails honestly instead of
silently substituting the weakest judge.
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
    #: Shares of this stock the user already holds (per-run input, 0 =
    #: none) — drives the action table and the sell share count.
    ownership: int = 0
    #: Max hold time in weeks (per-run input, 2026-08-08): the debate
    #: judges evidence against this horizon and the grader scores at it.
    hold_weeks: int = 2


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
    """The evidence vote over the collected dimensions (v2 slice 4).

    The engine is injected for tests; the default is a lazy DebateEngine
    (the tiered package's own LLM calls). Any failure — no foundation
    report, no evidence, LLM down — is an UNAVAILABLE report with an
    UNKNOWN direction and explicit warnings. There is deliberately no
    fallback to the tier-1 one-blob verdict: substituting the weakest
    judge when the best one fails would present a downgrade as a result.
    """

    tier = 2

    def __init__(self, engine: Optional[Any] = None) -> None:
        self._engine = engine

    def _failed(self, state: TierState, levels: SniperLevels,
                warnings: List[str], detail: Optional[Dict[str, Any]] = None
                ) -> TierReport:
        return TierReport(
            tier=self.tier,
            symbol=state.symbol,
            market=state.market,
            coverage=Coverage.UNAVAILABLE,
            direction=Direction.UNKNOWN,
            levels=levels,
            warnings=warnings,
            debate_detail=detail,
        )

    def run(self, state: TierState) -> TierReport:
        foundation = state.reports.get(1)
        if foundation is None:
            return self._failed(
                state, SniperLevels(),
                ["tier 2 requires the data-layer foundation report"],
            )

        dimensions = state.dimensions or foundation.dimensions
        if not dimensions:
            return self._failed(
                state, foundation.levels,
                ["no collected evidence to vote on — no outlook (re-run)"],
            )

        engine = self._engine
        if engine is None:
            from .debate import DebateEngine

            engine = DebateEngine()
        result = engine.run(
            state.symbol, foundation, dimensions, hold_weeks=state.hold_weeks
        )

        if result.verdict is None:
            return self._failed(
                state, foundation.levels,
                list(result.warnings)
                + ["debate produced no verdict — no outlook (re-run)"],
                detail=result.to_detail(),
            )

        verdict = result.verdict
        return TierReport(
            tier=self.tier,
            symbol=state.symbol,
            market=state.market,
            coverage=Coverage.FULL,
            direction=verdict.direction,
            # The verdict is computed by formula from the vote outcomes,
            # so there is no judge confidence — the score lives in
            # debate_detail.verdict.final_score.
            confidence=None,
            score=foundation.score,
            levels=foundation.levels,
            narrative=verdict.summary or None,
            warnings=list(result.warnings),
            debate_detail=result.to_detail(),
        )


class TieredPipeline:
    """Runs stages 1..N in order, recording each tier's report in the state."""

    def __init__(
        self,
        tier1: Optional[Tier1Stage] = None,
        tier2: Optional[Tier2Stage] = None,
    ) -> None:
        self._stages: List[TierStage] = [
            tier1 or Tier1Stage(),
            tier2 or Tier2Stage(),
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
