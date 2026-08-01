# -*- coding: utf-8 -*-
"""Seed one artificial BULLISH depth-2 (tier-2 debate) run into history.

Purpose: a stored demo run that exercises every current alt-page surface
— the v2 technicals payload with formula receipts, the formula levels
with a resistance-capped target, the AI plan review (an accepted stop /
shares adjustment with cited reasons), the structured plan warnings, and
a v11 weighted debate with a bullish verdict — without any network or
LLM calls.

How: the REAL pipeline (`run_tiered_analysis`, depth 2) runs over
synthetic-but-realistic inputs. The four dimension providers are the
real classes with canned loaders; the debate engine and the plan
reviewer are the real engines fed scripted LLM replies whose citations
are built from the actual payload display values (so every mechanical
citation check passes the same way a good model's reply would).

Usage:
    python scripts/seed_demo_tiered_run.py            # store the run
    python scripts/seed_demo_tiered_run.py --dry-run  # print, no store

The run is stored under symbol DEMO so it can never be mistaken for a
real analysis.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import sys
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tiered_analysis.debate import (  # noqa: E402
    DebateEngine,
    gradable_field_refs,
)
from src.tiered_analysis.levels import bases_from_dimensions  # noqa: E402
from src.tiered_analysis.llm_support import display_value as dv  # noqa: E402
from src.tiered_analysis.plan_review import _flagged_checks  # noqa: E402
from src.tiered_analysis.providers.base import Market  # noqa: E402
from src.tiered_analysis.providers.fundamentals_us import (  # noqa: E402
    FundamentalsUSProvider,
)
from src.tiered_analysis.providers.macro_econ import MacroEconProvider  # noqa: E402
from src.tiered_analysis.providers.positioning import (  # noqa: E402
    PositioningUSProvider,
)
from src.tiered_analysis.providers.technicals import (  # noqa: E402
    Bar,
    TechnicalsProvider,
    read_metric,
)
from src.tiered_analysis.schema import Direction  # noqa: E402
from src.tiered_analysis.settings import SizingSettings  # noqa: E402
from src.tiered_analysis.sizing import SizingInputs, size_position  # noqa: E402
from src.tiered_analysis.tiers import Tier2Stage  # noqa: E402

SYMBOL = "DEMO"
CAPITAL = 100_000.0
RISK_FRACTION = 0.01
REWARD_RISK = 2.0

TODAY = date.today()


# ---------------------------------------------------------------------------
# Synthetic price history: a one-year uptrend with real pivots
# ---------------------------------------------------------------------------


def _business_days(count: int) -> list:
    """The last `count` weekdays, oldest first, ending yesterday-ish."""
    days = []
    day = TODAY - timedelta(days=1)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return list(reversed(days))


def demo_bars(count: int = 320) -> list:
    """Drifting sine wave: an uptrend with genuine pivot highs/lows.

    Tuned so the last close sits above the 50/200-day averages (no
    downtrend flag), below a recent pivot high (a resistance exists to
    cap the target), and above a recent pivot low (a support exists
    under the stop). The final 5 bars carry a volume bump so the volume
    ratio reads > 1.
    """
    days = _business_days(count)
    bars = []
    price = 100.0
    for i in range(count):
        price *= 1.0012
        close = price * (1 + 0.025 * math.sin(i / 9.0))
        volume = 52e6 if i >= count - 5 else 40e6
        bars.append(Bar(
            high=close * 1.012,
            low=close * 0.988,
            close=close,
            open=close * 0.996,
            volume=volume,
            date=days[i].isoformat(),
        ))
    return bars


def demo_index_bars(count: int = 320) -> list:
    """A calm benchmark uptrend: bullish regime, and the stock beats it."""
    bars = []
    price = 5000.0
    for i in range(count):
        price *= 1.0005
        bars.append(Bar(high=price * 1.004, low=price * 0.996, close=price))
    return bars


# ---------------------------------------------------------------------------
# Canned loaders for the three non-technical providers
# ---------------------------------------------------------------------------


def _fy(end: str, val: float, fy: int, start: str = None) -> dict:
    row = {"end": end, "val": val, "fy": fy, "fp": "FY", "form": "10-K"}
    if start:
        row["start"] = start
    return row


def _concept(rows: list, unit: str = "USD") -> dict:
    return {"units": {unit: rows}}


def _q(end: date, val: float) -> dict:
    """One single-quarter 10-Q row (~90-day span)."""
    return {
        "start": (end - timedelta(days=90)).isoformat(),
        "end": end.isoformat(),
        "val": val,
        "fp": "Q3",
        "form": "10-Q",
    }


def _ytd(start: date, end: date, val: float) -> dict:
    """One cumulative (year-to-date) 10-Q cash-flow row."""
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "val": val,
        "fp": "Q3",
        "form": "10-Q",
    }


#: Eight ~91-day-spaced quarter ends, newest (a month ago) first — so the
#: quarterly growth fields read as fresh whenever the demo is seeded.
Q_ENDS = [TODAY - timedelta(days=32 + 91 * i) for i in range(8)]
#: Newest-first values: latest quarter +20% YoY vs +12% the quarter
#: before -> revenue trend "accelerating"; EPS +16.7% vs +10.2%.
REV_Q = [30e9, 28e9, 27e9, 26e9, 25e9, 25e9, 24e9, 23e9]
EPS_Q = [1.40, 1.30, 1.25, 1.22, 1.20, 1.18, 1.15, 1.10]

_FY_END = date(2025, 9, 30)
_PRIOR_YTD_END = Q_ENDS[0] - timedelta(days=364)

FAKE_FACTS = {
    "cik": 999999,
    "entityName": "Demo Corp",
    "facts": {
        "us-gaap": {
            "Revenues": _concept(
                [
                    _fy("2024-09-30", 96e9, 2024),
                    _fy("2025-09-30", 110e9, 2025),
                ]
                + [_q(end, val) for end, val in zip(Q_ENDS, REV_Q)]
            ),
            # FY + matching YTD spans -> TTM net income 24.2+19-16=27.2e9,
            # same period end as the TTM FCF (32e9) -> ratio ≈ 117.65%.
            "NetIncomeLoss": _concept([
                _fy("2024-09-30", 19e9, 2024),
                _fy("2025-09-30", 24.2e9, 2025, start="2024-10-01"),
                _ytd(date(2025, 10, 1), Q_ENDS[0], 19e9),
                _ytd(date(2024, 10, 1), _PRIOR_YTD_END, 16e9),
            ]),
            "GrossProfit": _concept([_fy("2025-09-30", 50.6e9, 2025)]),
            "OperatingIncomeLoss": _concept([_fy("2025-09-30", 34.1e9, 2025)]),
            "StockholdersEquity": _concept([_fy("2025-09-30", 60.5e9, 2025)]),
            "Liabilities": _concept([_fy("2025-09-30", 72.6e9, 2025)]),
            "AssetsCurrent": _concept([_fy("2025-09-30", 55e9, 2025)]),
            "LiabilitiesCurrent": _concept([_fy("2025-09-30", 27.5e9, 2025)]),
            "EarningsPerShareDiluted": _concept(
                [
                    _fy("2024-09-30", 4.1, 2024),
                    _fy("2025-09-30", 5.2, 2025),
                ]
                + [_q(end, val) for end, val in zip(Q_ENDS, EPS_Q)],
                unit="USD/shares",
            ),
            # FY + matching YTD spans -> free cash flow on the TTM basis:
            # OCF 40 + 33 − 30 = 43e9; capex 10 + 8 − 7 = 11e9; FCF 32e9.
            "NetCashProvidedByUsedInOperatingActivities": _concept([
                _fy("2025-09-30", 40e9, 2025, start="2024-10-01"),
                _ytd(date(2025, 10, 1), Q_ENDS[0], 33e9),
                _ytd(date(2024, 10, 1), _PRIOR_YTD_END, 30e9),
            ]),
            "PaymentsToAcquirePropertyPlantAndEquipment": _concept([
                _fy("2025-09-30", 10e9, 2025, start="2024-10-01"),
                _ytd(date(2025, 10, 1), Q_ENDS[0], 8e9),
                _ytd(date(2024, 10, 1), _PRIOR_YTD_END, 7e9),
            ]),
        }
    },
}

FAKE_YAHOO_INFO = {
    "trailingPE": 28.5,
    "forwardPE": 24.8,
    "priceToSalesTrailing12Months": 7.9,
    "marketCap": 850e9,
    "sector": "Technology",
    "industry": "Semiconductors",
}

# Inside positioning's 21-day implied-report-move window, outside the
# 7-day earnings_soon plan warning — so the demo shows the implied move
# without tripping the report warning.
EARNINGS_DATE = TODAY + timedelta(days=16)

#: Past report dates ~3 weeks after each quarter end; all four beats, so
#: the demo shows "4/4" with a mid-single-digit average surprise.
FAKE_EARNINGS_HISTORY = [
    {"date": EARNINGS_DATE.isoformat(), "eps_estimate": 1.50,
     "eps_actual": None, "surprise_pct": None},
] + [
    {"date": (end + timedelta(days=21)).isoformat(),
     "eps_estimate": estimate, "eps_actual": actual, "surprise_pct": None}
    for end, estimate, actual in zip(
        Q_ENDS[:4], [1.30, 1.22, 1.18, 1.15], EPS_Q[:4]
    )
]

FAKE_EPS_TREND = {"current": 1.50, "days_ago_90": 1.38}

FAKE_POSITIONING_INFO = {
    "sharesShort": 21_000_000,
    "sharesShortPriorMonth": 26_000_000,
    "shortPercentOfFloat": 0.018,
    "shortRatio": 1.4,
    "floatShares": 1_150_000_000,
    "sharesOutstanding": 1_240_000_000,
    "heldPercentInstitutions": 0.671,
    "heldPercentInsiders": 0.032,
    # Two weeks ago, midnight UTC — FINRA's usual lag.
    "dateShortInterest": calendar.timegm(
        (TODAY - timedelta(days=14)).timetuple()
    ),
}

def _last_quarter_end(today: date) -> date:
    """The most recent calendar quarter end — the 13F as-of date."""
    quarter_month = ((today.month - 1) // 3) * 3
    if quarter_month == 0:
        return date(today.year - 1, 12, 31)
    last_day = calendar.monthrange(today.year, quarter_month)[1]
    return date(today.year, quarter_month, last_day)


_Q13F = _last_quarter_end(TODAY).isoformat()

FAKE_HOLDERS = [
    {"pctHeld": pct, "date_reported": _Q13F}
    for pct in (0.062, 0.048, 0.041, 0.033, 0.027,
                0.022, 0.019, 0.016, 0.013, 0.011)
]

FAKE_INSIDER_ROWS = [
    {"date": (TODAY - timedelta(days=18)).isoformat(),
     "text": "Purchase at price 148.20 per share.",
     "shares": 12_000, "value": 1_778_400},
    {"date": (TODAY - timedelta(days=41)).isoformat(),
     "text": "Purchase at price 141.75 per share.",
     "shares": 7_000, "value": 992_250},
    {"date": (TODAY - timedelta(days=66)).isoformat(),
     "text": "Purchase at price 137.10 per share.",
     "shares": 5_000, "value": 685_500},
    {"date": (TODAY - timedelta(days=95)).isoformat(),
     "text": "Sale at price 133.00 per share.",
     "shares": 4_000, "value": 532_000},
]

def fake_option_board(price: float) -> dict:
    """The CBOE-board shape the v2 options loader returns: underlying
    price + 30-day ATM implied volatility + per-expiration sums and
    at-the-money quotes. The straddle mids are ~5.4% of the price, so
    the implied report-day move reads ±5.4% on the first expiration
    after EARNINGS_DATE (18 days out)."""
    def chain(days_out, call_oi, put_oi, call_volume, put_volume):
        call_mid = 0.0275 * price
        put_mid = 0.026 * price
        return {
            "expiration": (TODAY + timedelta(days=days_out)).isoformat(),
            "call_oi": call_oi, "put_oi": put_oi,
            "call_volume": call_volume, "put_volume": put_volume,
            "atm_strike": round(price),
            "atm_call_bid": round(call_mid - 0.2, 2),
            "atm_call_ask": round(call_mid + 0.2, 2),
            "atm_put_bid": round(put_mid - 0.2, 2),
            "atm_put_ask": round(put_mid + 0.2, 2),
        }
    return {
        "current_price": price,
        "iv30": 27.5,
        "chains": [
            chain(18, 410_000.0, 330_000.0, 96_000.0, 71_000.0),
            chain(46, 265_000.0, 240_000.0, 41_000.0, 36_000.0),
        ],
    }


def _monthly_dates(count: int) -> list:
    """First-of-month dates, oldest first, ending last month."""
    year, month = TODAY.year, TODAY.month
    out = []
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        out.append(f"{year:04d}-{month:02d}-01")
    return list(reversed(out))


def fake_fred_series(series_id: str) -> list:
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    if series_id == "CPIAUCSL":
        # 14 monthly index points, ~2.8% year-over-year.
        dates = _monthly_dates(14)
        return [
            (day, round(314.0 * (1.0023 ** i), 3))
            for i, day in enumerate(dates)
        ]
    latest = {
        "FEDFUNDS": 4.33,
        "DGS10": 4.38,
        "DGS2": 3.88,
        "T10Y2Y": 0.50,
        "UNRATE": 4.1,
        "VIXCLS": 16.52,
        "DCOILWTICO": 68.34,
        "DTWEXBGS": 121.16,
    }[series_id]
    return [(yesterday, latest)]


# ---------------------------------------------------------------------------
# Scripted LLM replies (built from the ACTUAL payload display values)
# ---------------------------------------------------------------------------


class ScriptedLlm:
    """Routes debate/plan prompts to prebuilt replies; any citation-fix
    or retry prompt aborts loudly — a fix round means this script built
    a reply the mechanical checks rejected, which must be repaired here,
    not papered over."""

    def __init__(self, replies: dict) -> None:
        self.replies = replies
        # (marker, stage) checked in order; fix markers come first.
        self.markers = [
            ("votes failed the code's citation check", "ABORT_vote_fix"),
            ("bullets failed the code's citation check", "ABORT_item_fix"),
            ("summary failed the code's citation check", "ABORT_summary_fix"),
            ("Your previous reply had citation problems", "ABORT_plan_fix"),
            ("Your previous reply was invalid", "ABORT_retry"),
            ("Your earlier accepted adjustments were applied", "ABORT_round2"),
            ("You are the FIRST analyst", "lister1"),
            ("You are the SECOND analyst", "lister2"),
            ("cast the deciding vote", "decider"),
            ("cast the second vote", "check"),
            ("Write the user-facing report", "summary"),
            ("You are the risk reviewer", "plan"),
        ]

    def __call__(self, prompt: str) -> str:
        for marker, stage in self.markers:
            if marker in prompt:
                if stage.startswith("ABORT"):
                    raise AssertionError(
                        f"unexpected {stage} prompt — the scripted reply "
                        f"failed a mechanical check:\n{prompt[-2500:]}"
                    )
                return self.replies[stage]
        raise AssertionError(f"prompt matches no stage: {prompt[:200]}")


def _grade(direction, claim, links=(), weight=3, reason=None):
    return {"direction": direction, "claim": claim, "links": list(links),
            "weight": weight, "weight_reason": reason}


def _link(ref, value):
    return {"ref": ref, "value": value}


def build_debate_replies(payloads: dict) -> dict:
    """Grade sheets (v12 opening) whose cited values are read from the
    live payloads — the same numbers the engine's citation checker will
    verify against. Every gradable field gets exactly one grade: the
    scripted evidence below, neutral everywhere else."""
    tech = payloads["technicals"]
    fund = payloads["fundamentals"]
    pos = payloads["positioning"]
    macro = payloads["macro_econ"]

    def tval(group, key):
        return dv(tech[group][key]["value"])

    close_d = tval("price", "close")
    sma50_d = tval("daily", "sma_50")
    trend_d = tval("weekly", "trend")
    rs_d = tval("market", "rs_label")
    range_d = tval("price", "range_pct_1y")
    def fval(group, key):
        return dv(fund[group][key]["value"])

    rev_d = fval("growth", "revenue_yoy_q")
    rev_trend_d = fval("growth", "revenue_growth_trend")
    margin_d = fval("profitability", "operating_margin_pct")
    pe_d = fval("valuation", "pe_ttm")
    # Positioning is v2 envelopes now — cite the unwrapped values.
    short_d = dv(pos["short_interest"]["short_pct_of_float"]["value"])
    inst_d = dv(pos["ownership"]["institutional_pct"]["value"])
    buys_d = dv(pos["insider_activity_6m"]["buy_count"]["value"])
    vix_d = dv(macro["markets"]["vix"])
    fed_d = dv(macro["rates"]["fed_funds_rate_pct"])
    dxy_d = dv(macro["markets"]["dollar_index_broad"])

    # The scripted evidence, keyed by the graded field. The engine
    # injects each graded field's own citation, so links carry only the
    # OTHER fields a claim mentions.
    graded = {
        "technicals.weekly.trend": _grade(
            "bullish",
            f"The weekly trend reads {trend_d}: rising averages and higher"
            " pivot highs and lows agree on direction.",
            [], 5,
            "Trend agreement across timeframes is the core of the setup."),
        "technicals.price.close": _grade(
            "bullish",
            f"The close ({close_d}) holds above the 50-day average"
            f" ({sma50_d}), the classic pullback-buy zone.",
            [_link("technicals.daily.sma_50", sma50_d)], 4,
            "Price above the mid-term average keeps the dip buyable."),
        "technicals.market.rs_label": _grade(
            "bullish",
            f"The stock is a market {rs_d}, beating the benchmark over"
            " both one and three months.",
            [], 4,
            "Leaders hold up best when the market wobbles."),
        "technicals.price.range_pct_1y": _grade(
            "bearish",
            f"The price already sits at {range_d} of its one-year range,"
            " so much of the move is behind it.",
            [], 2,
            "A high range position caps the easy upside."),
        "fundamentals.growth.revenue_yoy_q": _grade(
            "bullish",
            f"Quarterly sales grew {rev_d}% year over year and the"
            f" pace is {rev_trend_d}.",
            [_link("fundamentals.growth.revenue_growth_trend", rev_trend_d)],
            4,
            "Accelerating growth is the classic swing fuel."),
        "fundamentals.profitability.operating_margin_pct": _grade(
            "bullish",
            f"Operating earnings are {margin_d}% of sales — a highly"
            " profitable business.",
            [], 3, "Strong margins cushion bad quarters."),
        "fundamentals.valuation.pe_ttm": _grade(
            "bearish",
            f"The trailing price to earnings of {pe_d} prices in a lot of"
            " good news.",
            [], 2,
            "Rich valuation, but not extreme for a leader."),
        "positioning.short_interest.short_pct_of_float": _grade(
            "bullish",
            f"Short interest is only {short_d}% of the float — no crowded"
            " bet against the stock.",
            [], 3,
            "Low short interest removes one source of selling."),
        "positioning.insider_activity_6m.buy_count": _grade(
            "bullish",
            f"Insiders made {buys_d} open-market purchases in six months"
            " against a single sale.",
            [], 4, "Insiders buy for only one reason."),
        "positioning.ownership.institutional_pct": _grade(
            "bullish",
            f"Institutions hold {inst_d}% — a solid sponsor base without"
            " being fully crowded.",
            [], 3,
            "Sponsorship supports pullbacks."),
        "macro_econ.markets.vix": _grade(
            "bullish",
            f"The VIX at {vix_d} shows a calm market — favorable for"
            " swing entries.",
            [], 3,
            "Calm tape favors trend continuation."),
        "macro_econ.rates.fed_funds_rate_pct": _grade(
            "bearish",
            f"The federal funds rate at {fed_d}% is still restrictive"
            " for valuations.",
            [], 2,
            "Rates are a headwind, but a known one."),
    }

    # The second analyst grades the same fields identically (confirming
    # them 2-0 by code merge) plus one extra bearish macro grade — it
    # stays single-author, so the check round gets something real to
    # vote on. Its bullet renumbers to E3 (after the two shared macro
    # bullets).
    extra = {
        "macro_econ.markets.dollar_index_broad": _grade(
            "bearish",
            f"The broad dollar index at {dxy_d} pressures overseas"
            " earnings.",
            [], 2,
            "A strong dollar shaves reported growth."),
    }

    # One grade per code-enumerated field: the scripted evidence above,
    # neutral everywhere else — exactly the contract the engine checks.
    refs = gradable_field_refs(
        [SimpleNamespace(dimension=name, payload=payload)
         for name, payload in payloads.items()]
    )

    def sheet(evidence: dict) -> str:
        grades = {}
        for dimension_refs in refs.values():
            for ref in dimension_refs:
                grades[ref] = evidence.get(ref, {"direction": "neutral"})
        return json.dumps({"grades": grades})

    check_votes = {
        "E3": {"verdict": "valid",
               "reason": f"The dollar index reading ({dxy_d}) is genuinely"
                         " elevated and the drag on overseas earnings is"
                         " real, if modest.",
               "links": [_link("macro_econ.markets.dollar_index_broad",
                               dxy_d)],
               "weight": 2,
               "weight_reason": "A real but second-order headwind."},
    }

    summary = {
        "summary": [
            {"text": "The weight of the surviving evidence is clearly"
                     " bullish: an intact weekly uptrend, market"
                     " leadership, growing and profitable fundamentals,"
                     " and supportive positioning outweigh a rich"
                     " valuation and restrictive rates.",
             "links": [], "children": []},
            {"text": "The main risks are the extended one-year range"
                     " position and macro headwinds — both argue for"
                     " taking the pullback entry rather than chasing.",
             "links": [], "children": []},
        ],
        "technicals": [
            {"text": f"The weekly trend is {trend_d} and the close"
                     f" ({close_d}) holds above the 50-day average"
                     f" ({sma50_d}).",
             "links": [_link("technicals.weekly.trend", trend_d),
                       _link("technicals.price.close", close_d),
                       _link("technicals.daily.sma_50", sma50_d)],
             "children": []},
        ],
        "fundamentals": [
            {"text": f"Quarterly sales grew {rev_d}% and are"
                     f" {rev_trend_d}, with operating earnings at"
                     f" {margin_d}% of sales; the trailing price to"
                     f" earnings of {pe_d} is the price of that quality.",
             "links": [_link("fundamentals.growth.revenue_yoy_q", rev_d),
                       _link("fundamentals.growth.revenue_growth_trend",
                             rev_trend_d),
                       _link("fundamentals.profitability.operating_margin_pct",
                             margin_d),
                       _link("fundamentals.valuation.pe_ttm", pe_d)],
             "children": []},
        ],
        "positioning": [
            {"text": "Insider buying, low short interest and solid"
                     " institutional sponsorship all lean bullish.",
             "links": [], "children": []},
        ],
        "macro_econ": [
            {"text": "A calm volatility backdrop argues for entries;"
                     " restrictive rates and a firm dollar argue for"
                     " modest position size.",
             "links": [], "children": []},
        ],
    }

    return {
        "lister1": sheet(graded),
        "lister2": sheet({**graded, **extra}),
        "check": json.dumps({"votes": check_votes}),
        "decider": json.dumps({"votes": {}}),
        "summary": json.dumps(summary),
    }


def build_plan_reply(tech: dict, bases, base_shares) -> str:
    """Adjustments answering exactly the checks that actually flagged,
    each reason citing live report values."""
    from src.tiered_analysis.levels import decisions_to_sniper, apply_adjustments

    atr = read_metric(tech, "volatility", "atr_14")
    support = read_metric(tech, "levels", "support_1")
    entry = bases.entry.value
    base_stop = bases.stop_loss.value

    decisions, _ = apply_adjustments(bases, [], atr=atr)
    base_levels = decisions_to_sniper(decisions)
    flagged = {c.name for c in _flagged_checks(tech, base_levels, base_shares)}

    adjustments = []
    stop_final = base_stop
    if "stop_vs_support" in flagged and support is not None:
        # Just below the support pivot, still within 1 ATR of the base.
        stop_final = round(max(support - 0.15 * atr, base_stop - 0.95 * atr), 2)
        adjustments.append({
            "target": "stop_loss",
            "value": stop_final,
            "reasons": [{
                "check": "stop_vs_support",
                "text": f"Moved the stop below the nearest support"
                        f" ({dv(support)}) so a routine retest of that"
                        " pivot floor cannot stop the trade out.",
                "links": [_link("technicals.levels.support_1", dv(support))],
            }],
        })

    trim_checks = [c for c in ("volatility", "liquidity", "downtrend")
                   if c in flagged]
    if trim_checks:
        mech = size_position(SizingInputs(
            capital=CAPITAL, risk_fraction=RISK_FRACTION,
            entry=entry, stop_loss=stop_final,
            direction=Direction.BUY, market=Market.US,
        )).shares or 0
        proposed = max(1, int(mech * 0.75))
        atr_pct = read_metric(tech, "volatility", "atr_pct")
        reasons = []
        if "volatility" in trim_checks:
            reasons.append({
                "check": "volatility",
                "text": f"The typical daily swing is {dv(atr_pct)}% of the"
                        " price, so the count is trimmed to keep a one-day"
                        " shock inside the planned risk.",
                "links": [_link("technicals.volatility.atr_pct",
                                dv(atr_pct))],
            })
        for check in trim_checks:
            if check == "volatility":
                continue
            reasons.append({
                "check": check,
                "text": "The flagged risk is reduced by carrying fewer"
                        " shares.",
                "links": [],
            })
        if proposed < mech:
            adjustments.append({"target": "shares", "value": proposed,
                                "reasons": reasons})

    return json.dumps({"adjustments": adjustments})


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_outcome():
    macro_cache = Path(tempfile.mkdtemp(prefix="demo-macro-cache-"))
    bars = demo_bars()
    index_bars = demo_index_bars()
    providers = [
        TechnicalsProvider(
            bars_loader=lambda s: bars,
            index_bars_loader=lambda: index_bars,
            benchmark_name="S&P 500",
        ),
        FundamentalsUSProvider(
            facts_loader=lambda s: FAKE_FACTS,
            info_loader=lambda s: FAKE_YAHOO_INFO,
            earnings_lookup=lambda s: {
                "next_earnings_date": EARNINGS_DATE.isoformat(),
                "days_until_earnings": (EARNINGS_DATE - TODAY).days,
            },
            earnings_history_loader=lambda s: FAKE_EARNINGS_HISTORY,
            eps_trend_loader=lambda s: FAKE_EPS_TREND,
            bars_loader=lambda s: bars,
            today=lambda: TODAY,
        ),
        PositioningUSProvider(
            info_loader=lambda s: FAKE_POSITIONING_INFO,
            holders_loader=lambda s: FAKE_HOLDERS,
            insider_loader=lambda s: FAKE_INSIDER_ROWS,
            options_loader=lambda s: fake_option_board(bars[-1].close),
            earnings_lookup=lambda s: EARNINGS_DATE.isoformat(),
            today=lambda: TODAY,
        ),
        MacroEconProvider(
            series_fetcher=fake_fred_series,
            cache_dir=macro_cache,
        ),
    ]

    # Pre-collect once to build the scripted replies from live values;
    # collect() is deterministic, so the pipeline's own collection sees
    # identical payloads (macro reads its own fresh cache).
    payloads = {p.dimension: p.collect(SYMBOL).payload for p in providers}
    dimensions = [p.collect(SYMBOL) for p in providers]

    settings = SizingSettings(
        capital=CAPITAL, risk_fraction=RISK_FRACTION, reward_risk=REWARD_RISK,
    )
    bases = bases_from_dimensions(dimensions, reward_risk=REWARD_RISK)
    base_shares = size_position(SizingInputs(
        capital=CAPITAL, risk_fraction=RISK_FRACTION,
        entry=bases.entry.value if bases.entry else None,
        stop_loss=bases.stop_loss.value if bases.stop_loss else None,
        direction=Direction.BUY, market=Market.US,
    )).shares

    replies = build_debate_replies(payloads)
    replies["plan"] = build_plan_reply(
        payloads["technicals"], bases, base_shares
    )
    llm = ScriptedLlm(replies)

    from src.tiered_analysis.integration import run_tiered_analysis

    return run_tiered_analysis(
        SYMBOL,
        market=Market.US,
        providers=providers,
        depth=2,
        sizing_settings=settings,
        tier2_stage=Tier2Stage(engine=DebateEngine(summarizer=llm)),
        plan_summarizer=llm,
        log_signal=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the run summary; do not store it")
    args = parser.parse_args()

    outcome = build_outcome()
    final = outcome.final_report
    detail = outcome.report.levels_detail or {}
    tech = next(
        d for d in outcome.report.dimensions if d.dimension == "technicals"
    )

    print(f"direction:     {final.direction.value} (outlook "
          f"{outcome.outlook.value})")
    verdict = (final.debate_detail or {}).get("verdict") or {}
    print(f"debate score:  {verdict.get('final_score')} "
          f"(format {(final.debate_detail or {}).get('format')})")
    for key, level in (detail.get("levels") or {}).items():
        print(f"  {key}: base={level.get('base')} "
              f"adjusted={level.get('adjusted')} final={level.get('final')}")
    print(f"plan warnings: "
          f"{ {k: [w['id'] for w in v] for k, v in (outcome.plan_warnings or {}).items()} }")
    print(f"volume order:  {list(tech.payload['volume'].keys())}")
    print(f"ranking name:  {tech.payload['price']['range_pct_1y']['name']}")
    print(f"ranking recpt: {tech.formulas['price.range_pct_1y']['formula']}")

    pos = next(
        d for d in outcome.report.dimensions if d.dimension == "positioning"
    )
    print(f"13F up to:     {pos.payload['meta']['ownership_as_of']['value']}")
    print(f"implied move:  ±{pos.payload['options']['implied_report_move_pct']['value']}%")

    assert final.direction is Direction.BUY, "demo run must be bullish"
    assert (final.debate_detail or {}).get("verdict"), "debate verdict missing"
    assert pos.payload["options"]["implied_report_move_pct"]["value"] is not None, (
        "demo implied report-day move must be populated"
    )

    if args.dry_run:
        print("\ndry run — nothing stored")
        return

    from api.v1.endpoints.tiered import _serialize_outcome
    from src.tiered_analysis import history

    task_id = f"demo-{uuid.uuid4().hex[:12]}"
    history.create_run(task_id, SYMBOL, inputs={
        "tier": 2, "capital": CAPITAL, "risk_fraction": RISK_FRACTION,
        "reward_risk": REWARD_RISK,
    })
    history.mark_done(task_id, _serialize_outcome(outcome))
    print(f"\nstored demo run: task_id={task_id} symbol={SYMBOL}")
    print("open the tiered (alt) page — the run appears in the history list")


if __name__ == "__main__":
    main()
