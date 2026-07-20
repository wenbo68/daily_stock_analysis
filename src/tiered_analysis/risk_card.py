# -*- coding: utf-8 -*-
"""Display-only risk card (outlook redesign, 2026-07-20).

Thirteen deterministic numbers — the pre-trade checks a firm's risk desk
and a disciplined trader would run — computed from data the run already
has. ZERO LLM calls, and by explicit owner decision the card affects
NOTHING: sizing, levels, outlook, and action never read it. The user
reviews these in real runs and decides later which to wire in.

Entries 1-7 are risk-department-side (money at stake), 8-13 trader-side
(plan discipline). Each entry is {id, status, values}: status "flag"
means a threshold crossed, "na" means the inputs for it don't exist on
this run (with values explaining what's missing), "ok" otherwise. All
user-facing wording lives in the frontend i18n layer — the backend ships
numbers only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .providers.base import DimensionResult
from .schema import SniperLevels
from .settings import SizingSettings

#: Order of the card — frozen so the UI numbering is stable.
RISK_CARD_IDS = (
    "concentration",
    "cash",
    "max_loss",
    "liquidity",
    "var",
    "gap_stress",
    "volatility",
    "reward_risk",
    "stop_atr",
    "stop_vs_swing_low",
    "staleness",
    "both_entries",
    "ownership_context",
)

#: Position larger than this share of average daily volume is hard to
#: exit in one day without moving the price.
ADV_FLAG_FRACTION = 0.05
#: A stock that typically moves more than this per day is flagged risky.
VOLATILITY_FLAG_FRACTION = 0.04
#: How far past the stop the gap scenario assumes the open lands.
GAP_ATR_MULTIPLE = 1.0

_Status = str  # "ok" | "flag" | "na"


def _entry(entry_id: str, status: _Status, **values: Any) -> Dict[str, Any]:
    return {"id": entry_id, "status": status, "values": values}


def _technicals_payload(
    dimensions: Sequence[DimensionResult],
) -> Dict[str, Any]:
    for dim in dimensions:
        if dim.dimension == "technicals" and dim.payload:
            return dim.payload
    return {}


def _num(payload: Dict[str, Any], key: str) -> Optional[float]:
    value = payload.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _sizing_num(sizing: Optional[Dict[str, Any]], key: str) -> Optional[float]:
    if not isinstance(sizing, dict):
        return None
    value = sizing.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_risk_card(
    dimensions: Sequence[DimensionResult],
    levels: SniperLevels,
    sizing: Optional[Dict[str, Any]],
    settings: SizingSettings,
) -> List[Dict[str, Any]]:
    """The 13 entries, in RISK_CARD_IDS order, always all present."""
    tech = _technicals_payload(dimensions)
    close = _num(tech, "close")
    atr = _num(tech, "atr_14")

    capital = settings.capital
    risk_fraction = settings.risk_fraction
    ownership = settings.ownership

    shares = _sizing_num(sizing, "shares")
    position_value = _sizing_num(sizing, "position_value")
    risk_amount = _sizing_num(sizing, "risk_amount")
    cap_applied = bool(sizing.get("cap_applied")) if isinstance(sizing, dict) else False
    is_sized = shares is not None and shares > 0

    entry = levels.entry
    stop = levels.stop_loss
    target = levels.take_profit
    secondary = levels.secondary_entry

    card: List[Dict[str, Any]] = []

    # 1. concentration — money parked in this one name vs the cap.
    if is_sized and position_value is not None and capital:
        fraction = position_value / capital
        card.append(_entry(
            "concentration",
            "flag" if cap_applied else "ok",
            position_value=position_value, capital=capital,
            fraction=fraction,
            cap_fraction=settings.max_position_fraction,
            cap_applied=cap_applied,
        ))
    else:
        card.append(_entry("concentration", "na", is_sized=is_sized))

    # 2. cash — what remains after the buy.
    if is_sized and position_value is not None and capital:
        card.append(_entry(
            "cash", "ok",
            position_value=position_value, capital=capital,
            cash_left=capital - position_value,
        ))
    else:
        card.append(_entry("cash", "na", is_sized=is_sized))

    # 3. max planned loss — the stop-hit loss vs the requested risk %.
    if is_sized and risk_amount is not None and capital:
        fraction = risk_amount / capital
        drifted = (
            risk_fraction is not None and fraction > float(risk_fraction) * 1.001
        )
        card.append(_entry(
            "max_loss",
            "flag" if drifted else "ok",
            risk_amount=risk_amount, capital=capital, fraction=fraction,
            requested_fraction=risk_fraction,
        ))
    else:
        card.append(_entry("max_loss", "na", is_sized=is_sized))

    # 4. liquidity — share count vs average daily volume.
    avg_volume = _num(tech, "avg_volume_20")
    if is_sized and avg_volume:
        fraction = shares / avg_volume
        card.append(_entry(
            "liquidity",
            "flag" if fraction > ADV_FLAG_FRACTION else "ok",
            shares=shares, avg_volume_20=avg_volume, fraction_of_adv=fraction,
            flag_fraction=ADV_FLAG_FRACTION,
        ))
    else:
        card.append(_entry(
            "liquidity", "na", is_sized=is_sized, has_volume=avg_volume is not None
        ))

    # 5. crude 1-day VaR — the worst-5% day applied to the position.
    worst_day = _num(tech, "worst_day_5pct")
    if is_sized and position_value is not None and worst_day is not None:
        var_amount = abs(worst_day) * position_value
        exceeds_plan = risk_amount is not None and var_amount > risk_amount
        card.append(_entry(
            "var",
            "flag" if exceeds_plan else "ok",
            worst_day_5pct=worst_day, position_value=position_value,
            var_amount=var_amount, risk_amount=risk_amount,
        ))
    else:
        card.append(_entry(
            "var", "na", is_sized=is_sized, has_history=worst_day is not None
        ))

    # 6. gap stress — the open lands 1 ATR below the stop.
    if is_sized and entry is not None and stop is not None and atr:
        gap_price = stop - GAP_ATR_MULTIPLE * atr
        loss_if_gap = shares * (entry - gap_price)
        card.append(_entry(
            "gap_stress", "ok",
            stop_loss=stop, atr_14=atr, gap_atr_multiple=GAP_ATR_MULTIPLE,
            gap_price=gap_price, loss_at_stop=risk_amount,
            loss_if_gap=loss_if_gap,
        ))
    else:
        card.append(_entry("gap_stress", "na", is_sized=is_sized))

    # 7. volatility — typical daily swing as a share of price.
    if atr and close:
        fraction = atr / close
        card.append(_entry(
            "volatility",
            "flag" if fraction > VOLATILITY_FLAG_FRACTION else "ok",
            atr_14=atr, close=close, atr_fraction=fraction,
            flag_fraction=VOLATILITY_FLAG_FRACTION,
        ))
    else:
        card.append(_entry("volatility", "na"))

    # 8. reward-to-risk — enforced >= 1.5 upstream; shown as one number.
    if entry is not None and stop is not None and target is not None and entry > stop:
        card.append(_entry(
            "reward_risk", "ok",
            entry=entry, stop_loss=stop, take_profit=target,
            ratio=(target - entry) / (entry - stop),
        ))
    else:
        card.append(_entry("reward_risk", "na"))

    # 9. stop distance in typical daily swings.
    if entry is not None and stop is not None and atr:
        card.append(_entry(
            "stop_atr", "ok",
            entry=entry, stop_loss=stop, atr_14=atr,
            atr_multiple=(entry - stop) / atr,
        ))
    else:
        card.append(_entry("stop_atr", "na"))

    # 10. stop vs the 20-day low — a stop above it dies to a routine retest.
    swing_low = _num(tech, "swing_low_20")
    if stop is not None and swing_low is not None:
        above = stop >= swing_low
        card.append(_entry(
            "stop_vs_swing_low",
            "flag" if above else "ok",
            stop_loss=stop, swing_low_20=swing_low, stop_at_or_above_swing_low=above,
        ))
    else:
        card.append(_entry("stop_vs_swing_low", "na"))

    # 11. staleness — the run-time geometry snapshot (fresh by construction).
    if close is not None and (entry is not None or stop is not None):
        card.append(_entry(
            "staleness", "ok",
            close=close, entry=entry, stop_loss=stop, take_profit=target,
            close_below_stop=stop is not None and close < stop,
            close_vs_entry_fraction=(
                (close - entry) / entry if entry else None
            ),
        ))
    else:
        card.append(_entry("staleness", "na"))

    # 12. both entries fill — the double-fill exposure sizing ignores today.
    if is_sized and entry is not None and secondary is not None and stop is not None:
        combined_shares = 2 * shares
        combined_cost = shares * (entry + secondary)
        combined_risk = shares * ((entry - stop) + (secondary - stop))
        budget = capital * float(risk_fraction) if capital and risk_fraction else None
        busts = budget is not None and combined_risk > budget * 1.001
        card.append(_entry(
            "both_entries",
            "flag" if busts else "ok",
            shares_each=shares, combined_shares=combined_shares,
            entry=entry, secondary_entry=secondary,
            combined_cost=combined_cost, combined_risk=combined_risk,
            risk_budget=budget,
            combined_fraction=(combined_cost / capital) if capital else None,
        ))
    else:
        card.append(_entry(
            "both_entries", "na",
            is_sized=is_sized, has_secondary=secondary is not None,
        ))

    # 13. ownership context — what the book looks like if you buy while
    # already holding (or just what you hold, when nothing new is sized).
    if ownership > 0 and close is not None:
        held_value = ownership * close
        new_shares = shares if is_sized else 0.0
        combined_shares = ownership + new_shares
        combined_value = held_value + (position_value or 0.0)
        combined_fraction = (combined_value / capital) if capital else None
        over_cap = (
            combined_fraction is not None
            and combined_fraction > settings.max_position_fraction
        )
        card.append(_entry(
            "ownership_context",
            "flag" if over_cap else "ok",
            ownership=ownership, close=close, held_value=held_value,
            new_shares=new_shares, combined_shares=combined_shares,
            combined_value=combined_value, combined_fraction=combined_fraction,
            cap_fraction=settings.max_position_fraction,
        ))
    else:
        card.append(_entry("ownership_context", "na", ownership=ownership))

    assert [item["id"] for item in card] == list(RISK_CARD_IDS)
    return card
