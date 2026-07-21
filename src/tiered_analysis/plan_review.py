# -*- coding: utf-8 -*-
"""AI plan review (owner redesign 2026-07-22).

The old display-only risk card is gone; its six deterministic checks now
do something:

- **Adjustable checks** — liquidity (order > 5% of the average daily
  volume), volatility (typical daily swing > 4% of price), stop distance
  (outside the healthy 1-3 ATR band) and stop-vs-swing-low (stop resting
  at/above the 20-day low) are handed to ONE LLM call that may adjust
  the plan: trim the share count, move the stop, move the target. Every
  accepted adjustment carries a code-validated, link-cited reason (the
  same citation contract as the tier-2 debate: values copied exactly as
  the report displays them, each with a {ref, value} link; sentiment
  claims cite citation:N).
- **Warning checks** — the two overnight-gap scenarios and a
  reward-to-risk shortfall become structured per-column warnings on the
  trade-plan card. The backend ships numbers only; the frontend words
  them.

Everything degrades loudly: no LLM, unparseable reply, invalid links →
the computed plan stands and a warning says why.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .debate import (
    _NUMERIC_REASON_RE,
    _link_value_text,
    _payload_value,
    _value_in_text,
    _values_equal,
)
from .levels import (
    LEVEL_KEYS,
    AdjustmentProposal,
    BaseLevels,
    apply_adjustments,
    decisions_to_detail,
    decisions_to_sniper,
)
from .llm_support import (
    LlmConfigError,
    _CITATION_REF_RE,
    default_summarizer,
    display_value,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult, Market
from .schema import Direction, SizingSlots, SniperLevels
from .settings import SizingSettings
from .sizing import SizingInputs, SizingResult, size_position

logger = logging.getLogger(__name__)

#: Order larger than this share of average daily volume is hard to exit
#: in one day without moving the price → the AI trims the share count.
ADV_FLAG_FRACTION = 0.05
#: Typical daily swing above this % of price → the AI reviews shares,
#: stop and target together.
VOLATILITY_FLAG_PCT = 4.0
#: Healthy stop distance band in ATRs; outside it the AI reviews the stop.
STOP_ATR_MIN = 1.0
STOP_ATR_MAX = 3.0
#: How far past the stop the ATR gap scenario assumes the open lands.
GAP_ATR_MULTIPLE = 1.0

#: Adjustable targets the LLM may propose (the entry is formula-owned).
_ADJUSTABLE = ("stop_loss", "take_profit", "shares")


@dataclass(frozen=True)
class PlanReview:
    """Everything the review produced, ready for the run outcome."""

    levels: SniperLevels
    levels_detail: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    #: Structured per-column warnings for the trade-plan card:
    #: {"entry"|"stop_loss"|"take_profit"|"shares": [{"id", "values"}]}.
    plan_warnings: Optional[Dict[str, List[Dict[str, Any]]]] = None
    sizing_detail: Optional[Dict[str, Any]] = None
    sizing_slots: SizingSlots = field(default_factory=SizingSlots)


def _tech_payload(dimensions: Sequence[DimensionResult]) -> Dict[str, Any]:
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            return dim.payload
    return {}


def _num(payload: Dict[str, Any], key: str) -> Optional[float]:
    value = payload.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _size(
    levels: SniperLevels,
    direction: Direction,
    market: Market,
    settings: SizingSettings,
) -> Tuple[SizingInputs, SizingResult]:
    inputs = SizingInputs(
        capital=settings.capital,
        risk_fraction=settings.risk_fraction,
        entry=levels.entry,
        stop_loss=levels.stop_loss,
        direction=direction,
        market=market,
        max_position_fraction=settings.max_position_fraction,
        fee_fraction=settings.fee_fraction,
    )
    return inputs, size_position(inputs)


def sizing_detail_dict(
    settings: SizingSettings,
    result: SizingResult,
    levels: SniperLevels,
    ownership: int,
    sell_shares: Optional[int],
    shares: Optional[int] = None,
    risk_amount: Optional[float] = None,
    extra_notes: Sequence[str] = (),
) -> Dict[str, Any]:
    """The JSON sizing block; ``shares``/``risk_amount`` override the
    engine's numbers when the AI trimmed the count."""
    final_shares = result.shares if shares is None else shares
    final_risk = result.risk_amount if risk_amount is None else risk_amount
    position_value = (
        final_shares * levels.entry
        if final_shares is not None and levels.entry is not None
        else result.position_value
    )
    return {
        "enabled": settings.is_enabled,
        "shares": final_shares,
        "ownership": ownership,
        "sell_shares": sell_shares,
        "position_value": position_value,
        "risk_amount": final_risk,
        "loss_per_share": result.loss_per_share,
        "lot_size": result.lot_size,
        "cap_applied": result.cap_applied,
        "reason_code": result.reason_code.value if result.reason_code else None,
        "refusal_reason": result.refusal_reason,
        "notes": list(result.notes) + list(settings.warnings) + list(extra_notes),
        "inputs": {
            "capital": settings.capital,
            "risk_fraction": settings.risk_fraction,
            "max_position_fraction": settings.max_position_fraction,
            "fee_fraction": settings.fee_fraction,
            "reward_risk": settings.reward_risk,
            "entry": levels.entry,
            "stop_loss": levels.stop_loss,
        },
    }


# ---------------------------------------------------------------------------
# Deterministic checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Check:
    """One flagged deterministic check, phrased for the LLM prompt."""

    name: str
    text: str


def _flagged_checks(
    tech: Dict[str, Any],
    levels: SniperLevels,
    shares: Optional[int],
) -> List[_Check]:
    checks: List[_Check] = []
    entry, stop = levels.entry, levels.stop_loss
    atr = _num(tech, "atr_14")
    avg_volume = _num(tech, "avg_volume_20")
    volatility = _num(tech, "volatility_pct")
    swing_low = _num(tech, "swing_low_20")

    if shares and avg_volume:
        fraction = shares / avg_volume
        if fraction > ADV_FLAG_FRACTION:
            checks.append(_Check(
                "liquidity",
                f"the planned {shares} shares are "
                f"{fraction * 100:.1f}% of the average daily volume "
                f"({display_value(avg_volume)}), above the "
                f"{ADV_FLAG_FRACTION:.0%} limit — propose a reduced "
                '"shares" so the order can exit in one day',
            ))
    if volatility is not None and volatility > VOLATILITY_FLAG_PCT:
        checks.append(_Check(
            "volatility",
            f"the typical daily swing is {display_value(volatility)}% of the "
            f"price (technicals.volatility_pct), above the "
            f"{VOLATILITY_FLAG_PCT:g}% limit — review the share count, the "
            "stop and the target together and adjust what the volatility "
            "actually threatens",
        ))
    if entry is not None and stop is not None and atr:
        multiple = (entry - stop) / atr
        if multiple < STOP_ATR_MIN or multiple > STOP_ATR_MAX:
            checks.append(_Check(
                "stop_distance",
                f"the stop sits {multiple:.2f} ATR from the entry, outside "
                f"the healthy {STOP_ATR_MIN:g}-{STOP_ATR_MAX:g} band — "
                'propose a corrected "stop_loss"',
            ))
    if stop is not None and swing_low is not None and stop >= swing_low:
        checks.append(_Check(
            "stop_vs_swing_low",
            f"the stop {display_value(stop)} rests at or above the 20-day "
            f"swing low ({display_value(swing_low)}), where a routine "
            'retest would trigger it — propose a "stop_loss" below that low',
        ))
    return checks


def build_plan_warnings(
    tech: Dict[str, Any],
    levels: SniperLevels,
    shares: Optional[int],
    risk_amount: Optional[float],
    reward_goal: float,
) -> Dict[str, List[Dict[str, Any]]]:
    """The structured per-column warnings (numbers only, no wording)."""
    warnings: Dict[str, List[Dict[str, Any]]] = {
        "entry": [], "stop_loss": [], "take_profit": [], "shares": [],
    }
    entry, stop, target = levels.entry, levels.stop_loss, levels.take_profit
    atr = _num(tech, "atr_14")
    worst_day = _num(tech, "worst_day_1y")

    sized = shares is not None and shares > 0
    if sized and entry is not None and stop is not None and atr:
        atr_open = stop - GAP_ATR_MULTIPLE * atr
        atr_loss = shares * (entry - atr_open)
        warnings["stop_loss"].append({
            "id": "gap_atr",
            "values": {
                "entry": entry, "stop_loss": stop, "shares": shares,
                "atr_14": atr, "gap_atr_multiple": GAP_ATR_MULTIPLE,
                "atr_open": atr_open, "atr_loss": atr_loss,
                "loss_at_stop": risk_amount,
                "atr_extra": (
                    atr_loss - risk_amount if risk_amount is not None else None
                ),
            },
        })
        if worst_day is not None:
            worst_open = entry * (1.0 + worst_day)
            if worst_open < stop:
                worst_loss = shares * (entry - worst_open)
                warnings["stop_loss"].append({
                    "id": "gap_worst",
                    "values": {
                        "entry": entry, "stop_loss": stop, "shares": shares,
                        "worst_day_1y": worst_day, "worst_open": worst_open,
                        "worst_loss": worst_loss,
                        "loss_at_stop": risk_amount,
                        "worst_extra": (
                            worst_loss - risk_amount
                            if risk_amount is not None else None
                        ),
                    },
                })
    if entry is not None and stop is not None and target is not None and entry > stop:
        ratio = (target - entry) / (entry - stop)
        if ratio < reward_goal - 1e-3:
            warnings["take_profit"].append({
                "id": "reward_below_goal",
                "values": {
                    "entry": entry, "stop_loss": stop, "take_profit": target,
                    "ratio": ratio, "goal": reward_goal,
                },
            })
    return warnings


# ---------------------------------------------------------------------------
# The LLM adjustment call
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """You are the risk reviewer of a swing-trade BUY plan for {symbol}.

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

The computed plan (deterministic formulas):
- entry = {entry} ({entry_formula})
- stop_loss = {stop_loss} ({stop_formula})
- take_profit = {take_profit} ({target_formula})
- shares = {shares} (capital × risk fraction ÷ (entry − stop_loss))

Deterministic checks flagged these problems:
{checks}

Propose adjustments that fix ONLY the flagged problems. Rules (all
checked mechanically by code):
- Reply with JSON only:
  {{"adjustments": [{{"target": "stop_loss" | "take_profit" | "shares",
    "value": <number>, "reason": "<one or two sentences>",
    "links": [{{"ref": "technicals.volatility_pct", "value": "4.3"}}]}}]}}
- At most one adjustment per target. An empty list is a valid answer if
  no change genuinely helps.
- "shares" may only go DOWN from {shares}.
- A price move must stay within 1 ATR ({atr}) of its computed value, and
  keep stop_loss < entry < take_profit.
- The reason must state every report number it relies on EXACTLY as the
  report above displays it, each cited in "links" with {{"ref": the leaf
  field, "value": the displayed value}}; claims resting on a news source
  cite {{"ref": "citation:N"}} with no value. Plain sentences only —
  never paste refs or link JSON into the reason text."""

_FIX_TEMPLATE = """{prompt}

Your previous reply had citation problems that code could not verify:
{errors}

Send the corrected JSON (same shape). Fix every listed problem: point
each ref at the right leaf field, copy the value exactly as the report
displays it, and make sure the reason sentence contains that value."""


def _link_errors(
    links: Sequence[Dict[str, Any]],
    sentence: str,
    where: str,
    dimensions: Sequence[DimensionResult],
) -> List[str]:
    errors: List[str] = []
    for link in links:
        ref = str(link.get("ref", "")).strip()
        if not ref:
            errors.append(f"{where}: link without a ref")
            continue
        if _CITATION_REF_RE.match(ref):
            if not validate_evidence([ref], dimensions, leaf_only=True):
                errors.append(f"{where} link {ref!r}: citation number out of range")
            continue
        resolves, actual = _payload_value(ref, dimensions)
        if not resolves:
            errors.append(
                f"{where} link {ref!r}: does not resolve to a single report value"
            )
            continue
        expected = display_value(actual)
        claimed = _link_value_text(link.get("value"))
        if not _values_equal(claimed, expected):
            errors.append(
                f"{where} link {ref!r}: claimed value {claimed!r} must be "
                f"copied exactly as the report displays it: {expected!r}"
            )
            continue
        if not _value_in_text(expected, sentence):
            errors.append(
                f"{where} link {ref!r}: the value {expected!r} must appear "
                "in the reason exactly as the report displays it"
            )
    if _NUMERIC_REASON_RE.search(sentence) and not links:
        errors.append(f"{where}: the reason states a number — cite it with a link")
    return errors


def _parse_adjustments(
    parsed: Optional[dict],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(usable adjustment dicts, shape errors)."""
    if parsed is None:
        return [], ["reply was not valid JSON"]
    raw = parsed.get("adjustments")
    if not isinstance(raw, list):
        return [], ['reply carries no "adjustments" list']
    usable: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen: set = set()
    for index, item in enumerate(raw):
        where = f"adjustment {index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{where}: not an object")
            continue
        target = str(item.get("target", "")).strip()
        if target not in _ADJUSTABLE:
            errors.append(
                f"{where}: target must be one of {', '.join(_ADJUSTABLE)}"
            )
            continue
        if target in seen:
            errors.append(f"{where}: duplicate target {target!r}")
            continue
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{where}: value must be a number")
            continue
        reason = str(item.get("reason", "")).strip()
        if not reason:
            errors.append(f"{where}: reason is required")
            continue
        links = item.get("links")
        links = (
            [link for link in links if isinstance(link, dict)]
            if isinstance(links, list)
            else []
        )
        seen.add(target)
        usable.append({
            "target": target, "value": float(value),
            "reason": reason, "links": links,
        })
    return usable, errors


def _request_adjustments(
    symbol: str,
    dimensions: Sequence[DimensionResult],
    bases: BaseLevels,
    base_shares: Optional[int],
    checks: Sequence[_Check],
    atr: Optional[float],
    summarizer: Callable[[str], str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """One call + one fix round; returns (adjustments, warnings)."""

    def basis(key: str) -> Tuple[str, str]:
        b = bases.get(key)
        return (
            (display_value(b.value), b.formula) if b is not None else ("—", "no base")
        )

    entry_v, entry_f = basis("entry")
    stop_v, stop_f = basis("stop_loss")
    target_v, target_f = basis("take_profit")
    prompt = _PROMPT_TEMPLATE.format(
        symbol=symbol,
        evidence=evidence_block(dimensions, display=True),
        entry=entry_v, entry_formula=entry_f,
        stop_loss=stop_v, stop_formula=stop_f,
        take_profit=target_v, target_formula=target_f,
        shares=base_shares if base_shares is not None else "—",
        checks="\n".join(f"- {check.name}: {check.text}" for check in checks),
        atr=display_value(atr) if atr is not None else "—",
    )

    warnings: List[str] = []
    adjustments, errors = _parse_adjustments(parse_llm_json(summarizer(prompt)))
    for adjustment in adjustments:
        errors.extend(_link_errors(
            adjustment["links"], adjustment["reason"],
            f'adjustment "{adjustment["target"]}"', dimensions,
        ))
    if errors:
        fix_prompt = _FIX_TEMPLATE.format(
            prompt=prompt, errors="\n".join(f"- {error}" for error in errors)
        )
        adjustments, errors = _parse_adjustments(parse_llm_json(summarizer(fix_prompt)))
        kept: List[Dict[str, Any]] = []
        for adjustment in adjustments:
            link_problems = _link_errors(
                adjustment["links"], adjustment["reason"],
                f'adjustment "{adjustment["target"]}"', dimensions,
            )
            if link_problems:
                warnings.append(
                    f"plan-review adjustment for {adjustment['target']} dropped "
                    f"— citations unfixable: {'; '.join(link_problems)}"
                )
            else:
                kept.append(adjustment)
        adjustments = kept
        warnings.extend(
            f"plan-review reply problem: {error}" for error in errors
        )
    return adjustments, warnings


# ---------------------------------------------------------------------------
# The whole review
# ---------------------------------------------------------------------------


def _shares_detail(
    base_inputs: SizingInputs,
    base_result: SizingResult,
    final_inputs: SizingInputs,
    final_result: SizingResult,
    ai_shares: Optional[int],
    ai_reason: Optional[str],
    ai_links: Sequence[Dict[str, Any]],
    rejection: Optional[str],
) -> Dict[str, Any]:
    """The trade-plan card's shares column, in the level-detail shape.

    base = the count from the computed levels; adjusted = what the run
    actually uses when that changed (levels moved and/or the AI trimmed
    it); adjusted_inputs = the final levels the mechanical recompute
    used, so the frontend receipt can show that arithmetic.
    """
    base = base_result.shares
    final = ai_shares if ai_shares is not None else final_result.shares
    adjusted = final if final is not None and final != base else None
    detail: Dict[str, Any] = {
        "base": base,
        "formula": (
            "capital × risk_fraction ÷ (entry − stop_loss)"
            if base is not None else None
        ),
        "inputs": {
            "capital": base_inputs.capital,
            "risk_fraction": base_inputs.risk_fraction,
            "entry": base_inputs.entry,
            "stop_loss": base_inputs.stop_loss,
        } if base is not None else None,
        "adjusted": adjusted,
        "reason": ai_reason if adjusted is not None else None,
        "evidence": [],
        "links": [dict(link) for link in ai_links] if adjusted is not None else [],
        "rejection": rejection,
        "final": final,
    }
    if adjusted is not None and final_result.shares != base:
        detail["adjusted_inputs"] = {
            "capital": final_inputs.capital,
            "risk_fraction": final_inputs.risk_fraction,
            "entry": final_inputs.entry,
            "stop_loss": final_inputs.stop_loss,
        }
    return detail


def review_plan(
    symbol: str,
    dimensions: Sequence[DimensionResult],
    bases: BaseLevels,
    direction: Direction,
    market: Market,
    settings: SizingSettings,
    ownership: int = 0,
    summarizer: Optional[Callable[[str], str]] = None,
) -> PlanReview:
    """Run the checks, maybe the LLM, and produce the final plan block.

    Only called for BUY verdicts (there is nothing to size or adjust on
    a hold/sell). Every failure path keeps the computed plan and says so.
    """
    tech = _tech_payload(dimensions)
    atr = _num(tech, "atr_14")
    warnings: List[str] = []

    # The computed plan: base levels, base share count.
    base_decisions, base_adj_warnings = apply_adjustments(bases, [], atr=atr)
    warnings.extend(base_adj_warnings)
    base_levels = decisions_to_sniper(base_decisions)
    base_inputs, base_result = _size(base_levels, direction, market, settings)

    checks = _flagged_checks(tech, base_levels, base_result.shares)

    adjustments: List[Dict[str, Any]] = []
    if checks:
        try:
            adjustments, request_warnings = _request_adjustments(
                symbol, dimensions, bases, base_result.shares, checks, atr,
                summarizer or default_summarizer,
            )
            warnings.extend(request_warnings)
        except LlmConfigError as exc:
            warnings.append(f"plan review skipped: {exc}")
        except Exception as exc:  # LLM transport failures degrade loudly
            logger.warning("plan review LLM call failed for %s: %s", symbol, exc)
            warnings.append(f"plan review LLM call failed: {exc}")

    price_proposals = [
        AdjustmentProposal(
            level=a["target"], value=a["value"], reason=a["reason"],
            links=tuple(a["links"]),
        )
        for a in adjustments
        if a["target"] in LEVEL_KEYS
    ]
    decisions, adjust_warnings = apply_adjustments(bases, price_proposals, atr=atr)
    warnings.extend(adjust_warnings)
    levels = decisions_to_sniper(decisions)

    # Mechanical share recompute from the final levels.
    final_inputs, final_result = _size(levels, direction, market, settings)

    # The AI's share trim: reductions only, floored to the lot size.
    ai_shares: Optional[int] = None
    ai_reason: Optional[str] = None
    ai_links: Sequence[Dict[str, Any]] = ()
    shares_rejection: Optional[str] = None
    shares_proposal = next(
        (a for a in adjustments if a["target"] == "shares"), None
    )
    if shares_proposal is not None:
        lot = final_result.lot_size
        proposed = int(math.floor(shares_proposal["value"] / lot)) * lot
        mechanical = final_result.shares
        if mechanical is None:
            shares_rejection = "no computed share count exists to adjust"
        elif proposed <= 0:
            shares_rejection = (
                f"proposed count {shares_proposal['value']:g} rounds down to "
                "zero — a trim cannot erase the position"
            )
        elif proposed >= mechanical:
            shares_rejection = (
                f"proposed count {proposed} is not below the computed "
                f"{mechanical} — shares may only be trimmed"
            )
        else:
            ai_shares = proposed
            ai_reason = shares_proposal["reason"]
            ai_links = shares_proposal["links"]
        if shares_rejection is not None:
            warnings.append(f"adjustment for shares rejected: {shares_rejection}")

    final_shares = ai_shares if ai_shares is not None else final_result.shares
    final_risk = (
        final_shares * final_result.loss_per_share
        if final_shares is not None and final_result.loss_per_share is not None
        else final_result.risk_amount
    )

    sell_shares = ownership if direction is Direction.SELL and ownership > 0 else None
    trim_notes = (
        [f"share count trimmed by the AI plan review: "
         f"{final_result.shares} → {ai_shares}"]
        if ai_shares is not None else []
    )
    sizing_detail = sizing_detail_dict(
        settings, final_result, levels, ownership, sell_shares,
        shares=final_shares, risk_amount=final_risk, extra_notes=trim_notes,
    )
    slots = (
        SizingSlots(
            capital=settings.capital,
            risk_fraction=settings.risk_fraction,
            shares=float(final_shares),
        )
        if final_shares is not None and final_shares > 0
        else SizingSlots()
    )

    levels_detail = decisions_to_detail(decisions, list(bases.warnings) + warnings)
    levels_detail["levels"]["shares"] = _shares_detail(
        base_inputs, base_result, final_inputs, final_result,
        ai_shares, ai_reason, ai_links, shares_rejection,
    )

    plan_warnings = build_plan_warnings(
        tech, levels, final_shares, final_risk, settings.reward_risk
    )

    return PlanReview(
        levels=levels,
        levels_detail=levels_detail,
        warnings=warnings,
        plan_warnings=plan_warnings,
        sizing_detail=sizing_detail,
        sizing_slots=slots,
    )
