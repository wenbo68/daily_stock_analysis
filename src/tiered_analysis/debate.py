# -*- coding: utf-8 -*-
"""Tier 2: scored bull/bear debate with a deterministic verdict (v3).

Redesign (owner spec, 2026-07-15). The direction no longer comes from a
judge's opinion — it is computed by a fixed formula from numbers the LLMs
produce, so the whole ruling is auditable:

1. Each debater argues its case and returns JSON: the argument, the
   evidence refs it leans on, and an honest 0-10 whole-number bullishness
   score (0 = strongly bearish, 5 = neutral, 10 = strongly bullish).
2. A grading judge scores each debater on three validity axes, each a
   whole number 0-5: citation validity (does the cited evidence really say
   what the debater claims?), knowledge validity (is the financial
   knowledge correct?), logical validity (do the conclusions follow?).
3. Code (not the LLM) computes the verdict:
       weight   = (citation + knowledge + logic) / 15          per debater
       final    = (w_bull × s_bull + w_bear × s_bear) / (w_bull + w_bear)
       verdict  = round half-up → 0-3 sell, 4-6 hold, 7-10 buy
   Weighting by validity keeps role bias from cancelling out: the side
   that argued better pulls the final number toward itself.
4. A summary judge then writes the user-facing report AROUND the computed
   number: corrected bull/bear summaries (invalid claims dropped or fixed)
   and a decision summary supporting the verdict.

All tier-2 LLM calls run at temperature 0 so the same evidence produces
the same grades. Anti-fabrication contract unchanged: debaters may only
cite the supplied evidence bundle; refs are code-validated
(``validate_evidence``) and invalid ones dropped. An off-spec number
(non-whole bullishness, out-of-range grade) voids the verdict — the tier
then degrades and the tier-1 direction stands.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .llm_support import (
    deterministic_summarizer,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult
from .schema import Direction, TierReport

DEFAULT_ROUNDS = 1

#: weight = (citation + knowledge + logic) / this — three 0-5 axes.
VALIDITY_MAX_TOTAL = 15

#: Verdict thresholds on the rounded final score (owner spec).
SELL_MAX = 3
HOLD_MAX = 6


def direction_from_score(rounded: int) -> Direction:
    """The fixed mapping from the rounded 0-10 final score to a verdict."""
    if rounded <= SELL_MAX:
        return Direction.SELL
    if rounded <= HOLD_MAX:
        return Direction.HOLD
    return Direction.BUY


_CONTEXT_TEMPLATE = """Stock under debate: {symbol}
Tier-1 verdict so far: direction={direction}, score={score}, confidence={confidence}
Tier-1 levels: entry={entry}, backup={secondary_entry}, stop={stop_loss}, target={take_profit}

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence_block}
"""

_DEBATER_FORMAT = """Reply with JSON only:
{{"argument": "your case in at most 180 words of plain English",
 "citations": ["technicals.rsi_14", "citation:1"],
 "bullishness": <whole number 0-10>}}

Rules:
- "citations" must list every piece of evidence your argument leans on: a
  payload key path like "technicals.rsi_14" or "citation:N" for a news
  source from the evidence above.
- "bullishness" is your honest overall read of the stock after weighing
  your own argument: 0 = strongly bearish, 5 = neither, 10 = strongly
  bullish. Argue your role, but score honestly — a weak case deserves a
  modest number.
- Use only the evidence above; do not invent facts."""

_BULL_TEMPLATE = """{context}
Debate transcript so far:
{transcript}

You are the BULL analyst: argue the strongest honest case FOR buying
{symbol}, rebutting the bear's latest points if there are any.
""" + _DEBATER_FORMAT

_BEAR_TEMPLATE = """{context}
Debate transcript so far:
{transcript}

You are the BEAR analyst: argue the strongest honest case AGAINST buying
{symbol} (risks, weaknesses, counter-evidence), rebutting the bull's
latest points if there are any.
""" + _DEBATER_FORMAT

_GRADING_TEMPLATE = """{context}
Full debate transcript (each turn shows the debater's citations and its
0-10 bullishness score):
{transcript}

You are the research manager grading this debate. Do NOT pick a direction
— code computes the verdict from your grades. Grade each debater on three
axes, each a whole number from 0 (worthless) to 5 (flawless):

1. citation_validity — does the cited evidence really say what the
   debater claims? Check every citation against the evidence above.
   Example: the bull claims "momentum is strong" citing technicals.rsi_14
   and RSI really is high → 4-5. The bull claims "the technical score is
   low" but the cited score is actually 90 → 0-1.
2. knowledge_validity — is the debater's financial knowledge correct?
   Example: a debater calls the stock overbought because RSI is 85 →
   correct use of RSI, 4-5. A debater calls the stock bearish "because
   RSI is low at 25" — a low RSI means oversold, if anything a rebound
   setup, so the knowledge is backwards → 0-1.
3. logical_validity — assuming the debater's facts were true, do its
   conclusions actually follow?
   Example: "revenue grew 40% and margins widened, so the business is
   strengthening" → sound, 4-5. "the product is popular, so the stock
   will double this quarter" → does not follow, 0-1.

Reply with JSON only:
{{"bull": {{"citation_validity": <0-5>, "knowledge_validity": <0-5>,
          "logical_validity": <0-5>,
          "notes": "1-2 plain-English sentences explaining the grades"}},
 "bear": {{"citation_validity": <0-5>, "knowledge_validity": <0-5>,
          "logical_validity": <0-5>,
          "notes": "1-2 plain-English sentences explaining the grades"}}}}"""

_SUMMARY_TEMPLATE = """{context}
Full debate transcript:
{transcript}

Your validity grades:
{grades}

Computed result (fixed formula — each debater's bullishness score weighted
by its validity grades): final bullishness {final} out of 10, rounded to
{rounded} → verdict {direction} (0-3 sell, 4-6 hold, 7-10 buy).

Write the user-facing report. Reply with JSON only:
{{"summary": "one plain-language paragraph explaining why the computed verdict is what it is",
 "bull_summary": "the bull case in at most 80 words — corrected: drop or fix any claims your grades found invalid",
 "bear_summary": "the bear case in at most 80 words — corrected the same way"}}

Rules:
- Support the computed verdict; if both sides graded poorly, say plainly
  that the debate was weak.
- Use only the transcript and evidence above; do not invent facts."""


@dataclass(frozen=True)
class DebateTurn:
    role: str  # "bull" | "bear"
    round: int
    argument: str
    #: The debater's honest 0-10 read; None when the reply was off-spec.
    bullishness: Optional[int] = None
    #: Code-validated evidence refs the argument leans on.
    citations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AnchoredReason:
    claim: str
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DebaterScore:
    """One debater's numbers: its own score plus the judge's grades."""

    bullishness: int
    citation_validity: int
    knowledge_validity: int
    logical_validity: int
    notes: Optional[str] = None

    @property
    def weight(self) -> float:
        return (
            self.citation_validity + self.knowledge_validity + self.logical_validity
        ) / VALIDITY_MAX_TOTAL


@dataclass(frozen=True)
class DebateVerdict:
    direction: Direction
    #: The validity-weighted average of the two bullishness scores, 0-10.
    final_score: float
    #: final_score rounded half-up — the number the direction maps from.
    final_score_rounded: int
    summary: str
    bull_summary: Optional[str] = None
    bear_summary: Optional[str] = None
    scoring: Optional[Dict[str, DebaterScore]] = None  # keys: "bull", "bear"


@dataclass(frozen=True)
class DebateResult:
    turns: List[DebateTurn] = field(default_factory=list)
    verdict: Optional[DebateVerdict] = None
    warnings: List[str] = field(default_factory=list)

    def to_detail(self) -> Dict[str, Any]:
        """JSON-ready audit trail for storage and the debate UI."""
        verdict: Optional[Dict[str, Any]] = None
        if self.verdict is not None:
            scoring: Optional[Dict[str, Any]] = None
            if self.verdict.scoring is not None:
                scoring = {
                    side: {
                        "bullishness": s.bullishness,
                        "citation_validity": s.citation_validity,
                        "knowledge_validity": s.knowledge_validity,
                        "logical_validity": s.logical_validity,
                        "weight": round(s.weight, 4),
                        "notes": s.notes,
                    }
                    for side, s in self.verdict.scoring.items()
                }
            verdict = {
                "direction": self.verdict.direction.value,
                "final_score": round(self.verdict.final_score, 3),
                "final_score_rounded": self.verdict.final_score_rounded,
                "summary": self.verdict.summary,
                "bull_summary": self.verdict.bull_summary,
                "bear_summary": self.verdict.bear_summary,
                "scoring": scoring,
                # Legacy keys kept so pre-redesign readers never crash.
                "confidence": None,
                "reasons_for": [],
                "reasons_against": [],
                "would_change_mind": None,
            }
        return {
            "turns": [
                {
                    "role": t.role,
                    "round": t.round,
                    "argument": t.argument,
                    "bullishness": t.bullishness,
                    "citations": list(t.citations),
                }
                for t in self.turns
            ],
            "verdict": verdict,
            "warnings": list(self.warnings),
        }


def _transcript(turns: Sequence[DebateTurn]) -> str:
    if not turns:
        return "(the debate is just starting)"
    blocks: List[str] = []
    for t in turns:
        header = f"[{t.role.upper()} — round {t.round}"
        if t.bullishness is not None:
            header += f" — bullishness {t.bullishness}/10"
        header += "]"
        body = t.argument
        if t.citations:
            body += "\ncited: " + ", ".join(t.citations)
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


def _whole_number(value: Any, low: int, high: int) -> Optional[int]:
    """value as an int in [low, high], or None when off-spec."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if float(value) != int(value):
        return None
    number = int(value)
    return number if low <= number <= high else None


class DebateEngine:
    """Runs the scored debate: debaters → grading judge → code formula →
    summary judge. Never raises out of run()."""

    def __init__(
        self,
        summarizer: Optional[Callable[[str], str]] = None,
        rounds: int = DEFAULT_ROUNDS,
    ) -> None:
        if rounds < 1:
            raise ValueError("rounds must be >= 1")
        # Temperature 0 by default: deterministic grades for the formula.
        self._summarize = summarizer or deterministic_summarizer
        self._rounds = rounds

    def run(
        self,
        symbol: str,
        tier1: TierReport,
        dimensions: Sequence[DimensionResult],
    ) -> DebateResult:
        context = _CONTEXT_TEMPLATE.format(
            symbol=symbol,
            direction=tier1.direction.value,
            score=tier1.score,
            confidence=tier1.confidence,
            entry=tier1.levels.entry,
            secondary_entry=tier1.levels.secondary_entry,
            stop_loss=tier1.levels.stop_loss,
            take_profit=tier1.levels.take_profit,
            evidence_block=evidence_block(dimensions),
        )

        turns: List[DebateTurn] = []
        warnings: List[str] = []
        try:
            for round_number in range(1, self._rounds + 1):
                for role, template in (("bull", _BULL_TEMPLATE), ("bear", _BEAR_TEMPLATE)):
                    raw = self._summarize(
                        template.format(
                            context=context,
                            symbol=symbol,
                            transcript=_transcript(turns),
                        )
                    )
                    turn, turn_warnings = self._parse_turn(
                        raw, role, round_number, dimensions
                    )
                    turns.append(turn)
                    warnings.extend(turn_warnings)
            raw_grades = self._summarize(
                _GRADING_TEMPLATE.format(context=context, transcript=_transcript(turns))
            )
        except Exception as exc:  # fail-loud as a structured result
            return DebateResult(
                turns=turns,
                warnings=warnings + [f"debate LLM call failed: {exc}"],
            )

        scores = {t.role: t.bullishness for t in turns}  # last turn wins
        missing = [role for role in ("bull", "bear") if scores.get(role) is None]
        if missing:
            return DebateResult(
                turns=turns,
                warnings=warnings
                + [
                    f"no usable bullishness score from {', '.join(missing)} — "
                    "tier-2 verdict voided"
                ],
            )

        grades, grade_warnings = self._parse_grades(raw_grades)
        warnings.extend(grade_warnings)
        if grades is None:
            return DebateResult(turns=turns, warnings=warnings)

        scoring = {
            side: DebaterScore(bullishness=scores[side], **grades[side])
            for side in ("bull", "bear")
        }
        final, final_warnings = self._final_score(scoring)
        warnings.extend(final_warnings)
        rounded = int(math.floor(final + 0.5))  # half-up, not banker's
        direction = direction_from_score(rounded)

        summary, bull_summary, bear_summary, summary_warnings = self._summaries(
            context, turns, scoring, final, rounded, direction
        )
        warnings.extend(summary_warnings)

        verdict = DebateVerdict(
            direction=direction,
            final_score=final,
            final_score_rounded=rounded,
            summary=summary,
            bull_summary=bull_summary,
            bear_summary=bear_summary,
            scoring=scoring,
        )
        return DebateResult(turns=turns, verdict=verdict, warnings=warnings)

    @staticmethod
    def _parse_turn(
        raw: str,
        role: str,
        round_number: int,
        dimensions: Sequence[DimensionResult],
    ) -> Tuple[DebateTurn, List[str]]:
        """One debater reply → a turn; off-spec parts degrade, not crash."""
        warnings: List[str] = []
        parsed = parse_llm_json(raw)
        if parsed is None:
            warnings.append(
                f"{role} reply was not JSON — argument kept as plain text, no score"
            )
            return (
                DebateTurn(role=role, round=round_number, argument=raw.strip()),
                warnings,
            )

        argument = str(parsed.get("argument") or "").strip() or raw.strip()

        bullishness = _whole_number(parsed.get("bullishness"), 0, 10)
        if bullishness is None:
            warnings.append(
                f"{role} bullishness {parsed.get('bullishness')!r} is not a "
                "whole number 0-10 — dropped"
            )

        raw_citations = [str(c).strip() for c in parsed.get("citations") or []]
        citations = validate_evidence(raw_citations, dimensions)
        if len(citations) < len(raw_citations):
            warnings.append(
                f"{role} cited evidence that does not resolve — invalid refs dropped"
            )

        return (
            DebateTurn(
                role=role,
                round=round_number,
                argument=argument,
                bullishness=bullishness,
                citations=tuple(citations),
            ),
            warnings,
        )

    @staticmethod
    def _parse_grades(
        raw: str,
    ) -> Tuple[Optional[Dict[str, Dict[str, Any]]], List[str]]:
        """Judge grades → per-side axis dicts; any off-spec grade voids."""
        parsed = parse_llm_json(raw)
        if parsed is None:
            return None, ["grading judge returned unparseable output — tier-2 verdict voided"]

        grades: Dict[str, Dict[str, Any]] = {}
        for side in ("bull", "bear"):
            node = parsed.get(side)
            if not isinstance(node, dict):
                return None, [f"grading judge gave no {side} grades — tier-2 verdict voided"]
            axes: Dict[str, Any] = {}
            for axis in ("citation_validity", "knowledge_validity", "logical_validity"):
                value = _whole_number(node.get(axis), 0, 5)
                if value is None:
                    return None, [
                        f"grading judge {side} {axis} {node.get(axis)!r} is not "
                        "a whole number 0-5 — tier-2 verdict voided"
                    ]
                axes[axis] = value
            axes["notes"] = str(node.get("notes") or "").strip() or None
            grades[side] = axes
        return grades, []

    @staticmethod
    def _final_score(scoring: Dict[str, DebaterScore]) -> Tuple[float, List[str]]:
        """The deterministic verdict number: validity-weighted average."""
        bull, bear = scoring["bull"], scoring["bear"]
        total_weight = bull.weight + bear.weight
        if total_weight == 0:
            return 5.0, [
                "both debaters graded zero validity — final score defaults "
                "to neutral 5"
            ]
        final = (
            bull.weight * bull.bullishness + bear.weight * bear.bullishness
        ) / total_weight
        return final, []

    def _summaries(
        self,
        context: str,
        turns: Sequence[DebateTurn],
        scoring: Dict[str, DebaterScore],
        final: float,
        rounded: int,
        direction: Direction,
    ) -> Tuple[str, Optional[str], Optional[str], List[str]]:
        """The user-facing prose; its failure never voids the computed verdict."""
        grades_block = "\n".join(
            f"{side}: citation {s.citation_validity}/5, knowledge "
            f"{s.knowledge_validity}/5, logic {s.logical_validity}/5"
            + (f" — {s.notes}" if s.notes else "")
            for side, s in scoring.items()
        )
        try:
            raw = self._summarize(
                _SUMMARY_TEMPLATE.format(
                    context=context,
                    transcript=_transcript(turns),
                    grades=grades_block,
                    final=f"{final:.1f}",
                    rounded=rounded,
                    direction=direction.value,
                )
            )
        except Exception as exc:
            return "", None, None, [
                f"summary LLM call failed: {exc} — computed verdict stands"
            ]

        parsed = parse_llm_json(raw)
        if parsed is None:
            return "", None, None, [
                "judge summary unparseable — computed verdict stands"
            ]

        summary = str(parsed.get("summary") or "").strip()
        warnings: List[str] = [] if summary else ["judge gave no summary"]
        bull_summary = str(parsed.get("bull_summary") or "").strip() or None
        bear_summary = str(parsed.get("bear_summary") or "").strip() or None
        return summary, bull_summary, bear_summary, warnings
