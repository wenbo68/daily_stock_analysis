# -*- coding: utf-8 -*-
"""Deterministic base price levels + adjustment validation (v2 slice 3).

Anchor-and-adjust (docs/tiered-analysis-formulas.md §2-3): formulas compute
a base for every level; the LLM may propose bounded adjustments (validated
here); code re-checks ordering and reward-to-risk after every accepted
adjustment. A rejected adjustment never edits the number — the base stands
and the rejection is surfaced as a warning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .providers.base import DimensionResult
from .schema import SniperLevels
from .stops import DEFAULT_ATR_MULTIPLIER, suggest_atr_stop

#: Base target demands twice the upside of the accepted downside.
REWARD_RISK_MULTIPLE = 2.0

#: An adjusted set may not degrade reward-to-risk below this floor.
MIN_REWARD_RISK = 1.5

#: An adjustment may move a level at most one typical daily swing from its
#: base — beyond that it is re-invention, not context.
ADJUSTMENT_BAND_ATR_MULTIPLE = 1.0

#: Level keys, in both SniperLevels field order and adjustment-application
#: order (entries first so stop/target checks see the final entry).
LEVEL_KEYS = ("entry", "secondary_entry", "stop_loss", "take_profit")


def _valid(value: Optional[float]) -> bool:
    return value is not None and value > 0


@dataclass(frozen=True)
class LevelBasis:
    """One formula-computed level with its full audit trail."""

    value: float
    formula: str
    inputs: Dict[str, float]


@dataclass(frozen=True)
class BaseLevels:
    entry: Optional[LevelBasis] = None
    secondary_entry: Optional[LevelBasis] = None
    stop_loss: Optional[LevelBasis] = None
    take_profit: Optional[LevelBasis] = None
    warnings: List[str] = field(default_factory=list)

    def get(self, key: str) -> Optional[LevelBasis]:
        return getattr(self, key)

    @property
    def is_empty(self) -> bool:
        return all(self.get(key) is None for key in LEVEL_KEYS)


def compute_base_levels(
    close: Optional[float],
    sma_20: Optional[float] = None,
    sma_60: Optional[float] = None,
    swing_low: Optional[float] = None,
    atr: Optional[float] = None,
) -> BaseLevels:
    """The four base levels; missing inputs degrade loudly, never silently."""
    warnings: List[str] = []

    if not _valid(close):
        return BaseLevels(
            warnings=["no close price — deterministic levels cannot be computed"]
        )

    supports = [v for v in (sma_20, swing_low) if _valid(v)]
    if not supports:
        return BaseLevels(
            warnings=[
                "no support anchors (sma_20 / swing_low_20) — no entry base, "
                "so no deterministic levels"
            ]
        )

    entry_value = min(close, max(supports))
    entry = LevelBasis(
        value=entry_value,
        formula="min(close, max(sma_20, swing_low_20))",
        inputs=_present(close=close, sma_20=sma_20, swing_low_20=swing_low),
    )

    backup_candidates = [
        v for v in (sma_60, swing_low) if _valid(v) and v < entry_value
    ]
    secondary: Optional[LevelBasis] = None
    if backup_candidates:
        secondary = LevelBasis(
            value=max(backup_candidates),
            formula="max(support strictly below ideal entry: sma_60, swing_low_20)",
            inputs=_present(
                ideal_entry=entry_value, sma_60=sma_60, swing_low_20=swing_low
            ),
        )
    else:
        warnings.append(
            "no deeper support strictly below the ideal entry — no backup entry"
        )

    stop: Optional[LevelBasis] = None
    target: Optional[LevelBasis] = None
    stop_value = suggest_atr_stop(entry_value, atr)
    if stop_value is None:
        warnings.append(
            "no usable ATR — no volatility stop, and no target without a stop"
        )
    else:
        stop = LevelBasis(
            value=stop_value,
            formula="ideal_entry − 2 × atr_14",
            inputs={
                "ideal_entry": entry_value,
                "atr_14": atr,
                "multiplier": DEFAULT_ATR_MULTIPLIER,
            },
        )
        target = LevelBasis(
            value=entry_value + REWARD_RISK_MULTIPLE * (entry_value - stop_value),
            formula="ideal_entry + 2 × (ideal_entry − stop_loss)",
            inputs={
                "ideal_entry": entry_value,
                "stop_loss": stop_value,
                "reward_risk_multiple": REWARD_RISK_MULTIPLE,
            },
        )

    return BaseLevels(
        entry=entry,
        secondary_entry=secondary,
        stop_loss=stop,
        take_profit=target,
        warnings=warnings,
    )


def _present(**values: Optional[float]) -> Dict[str, float]:
    return {name: value for name, value in values.items() if value is not None}


def bases_from_dimensions(dimensions: Sequence[DimensionResult]) -> BaseLevels:
    """Pull the level inputs out of the technicals dimension payload."""
    payload: Optional[Dict[str, Any]] = None
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            payload = dim.payload
            break
    if payload is None:
        return BaseLevels(
            warnings=[
                "technicals unavailable — deterministic levels cannot be computed"
            ]
        )

    def _num(key: str) -> Optional[float]:
        value = payload.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    return compute_base_levels(
        close=_num("close"),
        sma_20=_num("sma_20"),
        sma_60=_num("sma_60"),
        swing_low=_num("swing_low_20"),
        atr=_num("atr_14"),
    )


@dataclass(frozen=True)
class AdjustmentProposal:
    """One LLM proposal, already evidence-validated by the adjuster."""

    level: str
    value: float
    reason: str
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LevelDecision:
    """Final verdict for one level: base, accepted adjustment, or rejection."""

    base: Optional[LevelBasis] = None
    adjusted: Optional[float] = None
    reason: Optional[str] = None
    evidence: Tuple[str, ...] = ()
    rejection: Optional[str] = None

    @property
    def final(self) -> Optional[float]:
        if self.adjusted is not None:
            return self.adjusted
        return self.base.value if self.base is not None else None


def _ordering_problem(finals: Dict[str, Optional[float]]) -> Optional[str]:
    """Sanity of the whole set for a buy; None when consistent."""
    entry = finals["entry"]
    backup = finals["secondary_entry"]
    stop = finals["stop_loss"]
    target = finals["take_profit"]

    pairs = [
        (stop, backup, "stop-loss must stay below the backup entry"),
        (stop, entry, "stop-loss must stay below the ideal entry"),
        (entry, target, "ideal entry must stay below the target"),
    ]
    for low, high, message in pairs:
        if low is not None and high is not None and low >= high:
            return f"levels out of order: {message}"
    if backup is not None and entry is not None and backup > entry:
        return "levels out of order: backup entry must not exceed the ideal entry"

    if entry is not None and stop is not None and target is not None:
        risk = entry - stop
        if risk > 0 and (target - entry) / risk < MIN_REWARD_RISK:
            return (
                f"reward-to-risk would fall below {MIN_REWARD_RISK} — the trade "
                "would no longer pay for its risk"
            )
    return None


def apply_adjustments(
    bases: BaseLevels,
    proposals: Sequence[AdjustmentProposal],
    atr: Optional[float],
) -> Tuple[Dict[str, LevelDecision], List[str]]:
    """Validate proposals one level at a time, in LEVEL_KEYS order.

    Each acceptance immediately re-checks ordering and reward-to-risk on
    the resulting set; a violation reverts that single proposal.
    """
    decisions: Dict[str, LevelDecision] = {
        key: LevelDecision(base=bases.get(key)) for key in LEVEL_KEYS
    }
    warnings: List[str] = []

    def _reject(proposal: AdjustmentProposal, why: str) -> None:
        decisions[proposal.level] = LevelDecision(
            base=bases.get(proposal.level),
            rejection=why,
        )
        warnings.append(f"adjustment for {proposal.level} rejected: {why}")

    ordered = sorted(
        (p for p in proposals if p.level in LEVEL_KEYS),
        key=lambda p: LEVEL_KEYS.index(p.level),
    )
    for proposal in (p for p in proposals if p.level not in LEVEL_KEYS):
        warnings.append(f"adjustment for unknown level {proposal.level!r} ignored")

    for proposal in ordered:
        current = decisions[proposal.level]
        if current.adjusted is not None:
            warnings.append(
                f"duplicate adjustment for {proposal.level} ignored "
                "(first proposal kept)"
            )
            continue
        base = bases.get(proposal.level)
        if base is None:
            _reject(proposal, "no deterministic base exists to adjust")
            continue
        if atr is None or atr <= 0:
            _reject(proposal, "no ATR available — the adjustment band is undefined")
            continue
        if abs(proposal.value - base.value) > ADJUSTMENT_BAND_ATR_MULTIPLE * atr:
            _reject(
                proposal,
                f"moves the level more than {ADJUSTMENT_BAND_ATR_MULTIPLE:g} × ATR "
                f"({atr:g}) away from its base {base.value:g}",
            )
            continue

        candidate = LevelDecision(
            base=base,
            adjusted=proposal.value,
            reason=proposal.reason,
            evidence=proposal.evidence,
        )
        finals = {
            key: (candidate.final if key == proposal.level else decisions[key].final)
            for key in LEVEL_KEYS
        }
        problem = _ordering_problem(finals)
        if problem is not None:
            _reject(proposal, problem)
            continue
        decisions[proposal.level] = candidate

    return decisions, warnings


def decisions_to_sniper(decisions: Dict[str, LevelDecision]) -> SniperLevels:
    return SniperLevels(**{key: decisions[key].final for key in LEVEL_KEYS})


def decisions_to_detail(
    decisions: Dict[str, LevelDecision], warnings: Sequence[str]
) -> Dict[str, Any]:
    """JSON-ready audit trail: base + formula + adjustment per level."""
    levels: Dict[str, Any] = {}
    for key in LEVEL_KEYS:
        decision = decisions[key]
        levels[key] = {
            "base": decision.base.value if decision.base else None,
            "formula": decision.base.formula if decision.base else None,
            "inputs": dict(decision.base.inputs) if decision.base else None,
            "adjusted": decision.adjusted,
            "reason": decision.reason,
            "evidence": list(decision.evidence),
            "rejection": decision.rejection,
            "final": decision.final,
        }
    return {"levels": levels, "warnings": list(warnings)}
