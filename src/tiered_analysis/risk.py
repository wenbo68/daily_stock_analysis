# -*- coding: utf-8 -*-
"""Tier 3: risk stress test of the tier-2 verdict (v2 slice 5).

Reference pattern: TradingAgents graph/setup.py:140-165. Three risk
personas — conservative, aggressive, neutral — each critique the tier-2
verdict from their risk appetite; a risk judge merges them into a final
stance plus a **size multiplier** from the fixed enum {0, 0.5, 1.0} and
stop-loss keep/tighten advice.

Division of labor (design doc §1): the LLM chooses the multiplier from the
enum, but code applies it (``apply_size_multiplier``) and code validates a
tightened stop (strictly between the current stop and the entry) before it
touches a level. A multiplier outside the enum voids the whole verdict —
tier 3 then degrades and the tier-2 output stands.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .debate import AnchoredReason
from .llm_support import (
    default_summarizer,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult
from .schema import Direction, TierReport

PERSONAS = ("conservative", "aggressive", "neutral")

#: The only sizes the judge may pick: full position, half, or none.
SIZE_MULTIPLIERS = (0.0, 0.5, 1.0)

_STOP_ADVICE_VALUES = ("keep", "tighten")

_CONTEXT_TEMPLATE = """Stock under risk review: {symbol}
Tier-2 verdict: direction={direction}, confidence={confidence}
Tier-2 ruling: {narrative}
Levels: entry={entry}, backup={secondary_entry}, stop={stop_loss}, target={take_profit}

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence_block}
"""

_PERSONA_TEMPLATE = """{context}
You are the {persona_upper} risk reviewer{persona_hint}. In at most 150
words of plain English, assess this verdict from your risk appetite: what
could go wrong, is the stop sensible, and how much of a normal position
would you take? Use only the evidence above; do not invent facts."""

_PERSONA_HINTS = {
    "conservative": " (capital preservation first; skeptical of momentum)",
    "aggressive": " (opportunity-cost focused; willing to accept drawdowns)",
    "neutral": " (balance both; judge the plan on its own terms)",
}

_JUDGE_TEMPLATE = """{context}
The three risk reviews:
{takes}

You are the risk manager merging these reviews. Reply with JSON only:
{{"stance": "buy" | "hold" | "sell",
 "size_multiplier": 0 | 0.5 | 1.0,
 "stop_advice": "keep" | "tighten",
 "tightened_stop": null or a number strictly between the current stop and the entry,
 "summary": "one plain-language paragraph explaining the risk ruling",
 "key_risks": [{{"claim": "...", "evidence": ["technicals.rsi_14"]}}]}}

Rules:
- size_multiplier means: 1.0 = full computed position, 0.5 = half,
  0 = the direction stands but do not open a position now. Nothing else.
- Every key risk's "evidence" must reference the evidence above: a payload
  key path like "technicals.rsi_14" or "citation:N" for a sentiment source.
- Judge only from the reviews and evidence; do not add outside facts."""


@dataclass(frozen=True)
class PersonaTake:
    persona: str
    assessment: str


@dataclass(frozen=True)
class RiskVerdict:
    stance: Direction
    size_multiplier: float
    stop_advice: str
    tightened_stop: Optional[float]
    summary: str
    key_risks: Tuple[AnchoredReason, ...] = ()


@dataclass(frozen=True)
class RiskResult:
    takes: List[PersonaTake] = field(default_factory=list)
    verdict: Optional[RiskVerdict] = None
    warnings: List[str] = field(default_factory=list)

    def to_detail(self) -> Dict[str, Any]:
        """JSON-ready audit trail for storage and the future risk UI."""
        verdict: Optional[Dict[str, Any]] = None
        if self.verdict is not None:
            verdict = {
                "stance": self.verdict.stance.value,
                "size_multiplier": self.verdict.size_multiplier,
                "stop_advice": self.verdict.stop_advice,
                "tightened_stop": self.verdict.tightened_stop,
                "summary": self.verdict.summary,
                "key_risks": [
                    {"claim": r.claim, "evidence": list(r.evidence)}
                    for r in self.verdict.key_risks
                ],
            }
        return {
            "takes": [
                {"persona": t.persona, "assessment": t.assessment}
                for t in self.takes
            ],
            "verdict": verdict,
            "warnings": list(self.warnings),
        }


def apply_size_multiplier(shares: int, multiplier: float, lot_size: int = 1) -> int:
    """Scale a computed share count by the risk multiplier — code, not LLM."""
    if multiplier not in SIZE_MULTIPLIERS:
        raise ValueError(
            f"size multiplier must be one of {SIZE_MULTIPLIERS}, got {multiplier}"
        )
    if shares <= 0 or lot_size <= 0:
        return 0
    return int(math.floor(shares * multiplier / lot_size)) * lot_size


class RiskEngine:
    """Runs the three personas plus the risk judge; never raises out of run()."""

    def __init__(self, summarizer: Optional[Callable[[str], str]] = None) -> None:
        self._summarize = summarizer or default_summarizer

    def run(
        self,
        symbol: str,
        tier2: TierReport,
        dimensions: Sequence[DimensionResult],
    ) -> RiskResult:
        context = _CONTEXT_TEMPLATE.format(
            symbol=symbol,
            direction=tier2.direction.value,
            confidence=tier2.confidence,
            narrative=tier2.narrative,
            entry=tier2.levels.entry,
            secondary_entry=tier2.levels.secondary_entry,
            stop_loss=tier2.levels.stop_loss,
            take_profit=tier2.levels.take_profit,
            evidence_block=evidence_block(dimensions),
        )

        takes: List[PersonaTake] = []
        try:
            for persona in PERSONAS:
                assessment = self._summarize(
                    _PERSONA_TEMPLATE.format(
                        context=context,
                        persona_upper=persona.upper(),
                        persona_hint=_PERSONA_HINTS[persona],
                    )
                ).strip()
                takes.append(PersonaTake(persona=persona, assessment=assessment))
            takes_block = "\n\n".join(
                f"[{t.persona.upper()}]\n{t.assessment}" for t in takes
            )
            raw_verdict = self._summarize(
                _JUDGE_TEMPLATE.format(context=context, takes=takes_block)
            )
        except Exception as exc:  # fail-loud as a structured result
            return RiskResult(
                takes=takes,
                warnings=[f"risk stress LLM call failed: {exc}"],
            )

        verdict, warnings = self._parse_verdict(raw_verdict, tier2, dimensions)
        return RiskResult(takes=takes, verdict=verdict, warnings=warnings)

    @staticmethod
    def _parse_verdict(
        raw: str,
        tier2: TierReport,
        dimensions: Sequence[DimensionResult],
    ) -> Tuple[Optional[RiskVerdict], List[str]]:
        parsed = parse_llm_json(raw)
        if parsed is None:
            return None, ["risk judge returned unparseable output"]

        stance = Direction.from_decision_type(parsed.get("stance"))
        if stance is Direction.UNKNOWN:
            return None, [
                f"risk judge returned unusable stance {parsed.get('stance')!r}"
            ]

        multiplier = parsed.get("size_multiplier")
        if isinstance(multiplier, (int, float)) and float(multiplier) in SIZE_MULTIPLIERS:
            multiplier = float(multiplier)
        else:
            return None, [
                f"risk judge size multiplier {multiplier!r} is not one of "
                f"{SIZE_MULTIPLIERS} — verdict voided"
            ]

        warnings: List[str] = []

        stop_advice = str(parsed.get("stop_advice") or "").strip().lower()
        if stop_advice not in _STOP_ADVICE_VALUES:
            warnings.append(
                f"risk judge stop advice {parsed.get('stop_advice')!r} unusable — "
                "treated as 'keep'"
            )
            stop_advice = "keep"

        tightened_stop: Optional[float] = None
        raw_stop = parsed.get("tightened_stop")
        if stop_advice == "tighten" and isinstance(raw_stop, (int, float)):
            current_stop = tier2.levels.stop_loss
            entry = tier2.levels.entry
            value = float(raw_stop)
            if (
                current_stop is not None
                and entry is not None
                and current_stop < value < entry
            ):
                tightened_stop = value
            else:
                warnings.append(
                    f"tightened stop {value} is not strictly between the current "
                    f"stop ({current_stop}) and the entry ({entry}) — dropped"
                )

        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            warnings.append("risk judge gave no summary")

        key_risks: List[AnchoredReason] = []
        for item in parsed.get("key_risks") or []:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            if not claim:
                continue
            evidence = validate_evidence(item.get("evidence") or [], dimensions)
            if not evidence:
                warnings.append(
                    f"risk claim not anchored to evidence (kept, flagged): "
                    f"{claim[:80]}"
                )
            key_risks.append(AnchoredReason(claim=claim, evidence=tuple(evidence)))

        verdict = RiskVerdict(
            stance=stance,
            size_multiplier=multiplier,
            stop_advice=stop_advice,
            tightened_stop=tightened_stop,
            summary=summary,
            key_risks=tuple(key_risks),
        )
        return verdict, warnings
