# -*- coding: utf-8 -*-
"""Display-only risk card (outlook redesign, 2026-07-20; trimmed 2026-07-21).

Six deterministic pre-trade checks computed from data the run already
has. ZERO LLM calls, and by explicit owner decision the card affects
NOTHING: sizing, levels, outlook, and action never read it.

Trimmed by owner decision (2026-07-21): concentration, cash-after-buy,
max-planned-loss, one-day VaR, staleness, both-entries and
ownership-context are gone — concentration/ownership return with the
future portfolio feature, VaR folded into the gap check, the rest were
redundant or meaningless at run time.

Each entry is {id, status, values}: status "flag" means a threshold
crossed, "na" means the inputs for it don't exist on this run (with
values explaining what's missing), "ok" otherwise. All user-facing
wording lives in the frontend i18n layer — the backend ships numbers
only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .providers.base import DimensionResult
from .schema import SniperLevels
from .settings import SizingSettings

#: Order of the card — frozen so the UI numbering is stable. Old stored
#: runs carry the retired 13-id card; the frontend renders both shapes.
RISK_CARD_IDS = (
    "liquidity",
    "gap_stress",
    "volatility",
    "reward_risk",
    "stop_atr",
    "stop_vs_swing_low",
)

#: Position larger than this share of average daily volume is hard to
#: exit in one day without moving the price.
ADV_FLAG_FRACTION = 0.05
#: A stock that typically moves more than this per day is flagged risky.
VOLATILITY_FLAG_FRACTION = 0.04
#: How far past the stop the ATR gap scenario assumes the open lands.
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
    """The 6 entries, in RISK_CARD_IDS order, always all present."""
    tech = _technicals_payload(dimensions)
    close = _num(tech, "close")
    atr = _num(tech, "atr_14")

    shares = _sizing_num(sizing, "shares")
    risk_amount = _sizing_num(sizing, "risk_amount")
    is_sized = shares is not None and shares > 0

    entry = levels.entry
    stop = levels.stop_loss
    target = levels.take_profit

    card: List[Dict[str, Any]] = []

    # 1. liquidity — share count vs average daily volume.
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

    # 2. gap stress — a stop order sells at the OPEN when bad news lands
    # overnight, not at the stop price. Two overnight scenarios:
    # (a) the worst single daily drop of the loaded history hits from the
    #     entry — does it even gap past the stop, and at what extra cost;
    # (b) the open lands 1 ATR below the stop.
    worst_day = _num(tech, "worst_day_1y")
    if is_sized and entry is not None and stop is not None and atr:
        atr_open = stop - GAP_ATR_MULTIPLE * atr
        atr_loss = shares * (entry - atr_open)
        values: Dict[str, Any] = dict(
            entry=entry, stop_loss=stop, shares=shares,
            loss_at_stop=risk_amount,
            atr_14=atr, gap_atr_multiple=GAP_ATR_MULTIPLE,
            atr_open=atr_open, atr_loss=atr_loss,
            atr_extra=(atr_loss - risk_amount) if risk_amount is not None else None,
        )
        worst_gaps = False
        if worst_day is not None:
            worst_open = entry * (1.0 + worst_day)
            worst_gaps = worst_open < stop
            values.update(worst_day_1y=worst_day, worst_open=worst_open,
                          worst_gaps_stop=worst_gaps)
            if worst_gaps:
                worst_loss = shares * (entry - worst_open)
                values.update(
                    worst_loss=worst_loss,
                    worst_extra=(worst_loss - risk_amount)
                    if risk_amount is not None else None,
                )
        card.append(_entry("gap_stress", "flag" if worst_gaps else "ok", **values))
    else:
        card.append(_entry("gap_stress", "na", is_sized=is_sized))

    # 3. volatility — typical daily swing as a share of price.
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

    # 4. reward-to-risk — the plan's actual ratio vs the ratio the user
    # asked for (resistance may have capped the target below the goal;
    # the 1.5 hard floor already voided anything worse upstream).
    goal = settings.reward_risk
    if entry is not None and stop is not None and target is not None and entry > stop:
        ratio = (target - entry) / (entry - stop)
        card.append(_entry(
            "reward_risk",
            "flag" if ratio < goal - 1e-3 else "ok",
            entry=entry, stop_loss=stop, take_profit=target,
            ratio=ratio, goal=goal,
        ))
    else:
        card.append(_entry("reward_risk", "na", goal=goal))

    # 5. stop distance in typical daily swings.
    if entry is not None and stop is not None and atr:
        card.append(_entry(
            "stop_atr", "ok",
            entry=entry, stop_loss=stop, atr_14=atr,
            atr_multiple=(entry - stop) / atr,
        ))
    else:
        card.append(_entry("stop_atr", "na"))

    # 6. stop vs the 20-day low — a stop above it dies to a routine retest.
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

    assert [item["id"] for item in card] == list(RISK_CARD_IDS)
    return card
