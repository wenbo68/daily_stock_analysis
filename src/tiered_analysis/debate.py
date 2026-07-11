# -*- coding: utf-8 -*-
"""Tier 2: bull/bear debate over the collected evidence (v2 slice 4).

Reference pattern: TradingAgents graph/setup.py:122-138. One LLM argues the
case FOR the stock (bull), another argues AGAINST (bear), for a configurable
number of rounds; a research-manager judge weighs the transcript and issues
a structured verdict (direction, confidence, anchored reasons, and what
evidence would change its mind).

Anti-fabrication contract (same spirit as slices 3 and the sentiment
provider): debaters and judge may only reference the supplied evidence
bundle; the judge's reasons carry evidence refs which are validated against
the dimension payloads / sentiment citations — an unanchored claim is kept
but flagged in warnings, never silently trusted. Any LLM failure degrades
to no verdict; the tier stage then falls back to the Tier 1 direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .llm_support import (
    default_summarizer,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult
from .schema import Direction, TierReport

DEFAULT_ROUNDS = 1

_CONTEXT_TEMPLATE = """Stock under debate: {symbol}
Tier-1 verdict so far: direction={direction}, score={score}, confidence={confidence}
Tier-1 levels: entry={entry}, backup={secondary_entry}, stop={stop_loss}, target={take_profit}

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence_block}
"""

_BULL_TEMPLATE = """{context}
Debate transcript so far:
{transcript}

You are the BULL analyst. In at most 180 words of plain English, argue the
strongest honest case FOR buying {symbol}, using only the evidence above.
Rebut the bear's latest points if there are any. Do not invent facts."""

_BEAR_TEMPLATE = """{context}
Debate transcript so far:
{transcript}

You are the BEAR analyst. In at most 180 words of plain English, argue the
strongest honest case AGAINST buying {symbol} (risks, weaknesses,
counter-evidence), using only the evidence above. Rebut the bull's latest
points. Do not invent facts."""

_JUDGE_TEMPLATE = """{context}
Full debate transcript:
{transcript}

You are the research manager judging this debate. Weigh both sides against
the evidence and reply with JSON only:
{{"direction": "buy" | "hold" | "sell",
 "confidence": 0.0 to 1.0,
 "summary": "one plain-language paragraph explaining your ruling",
 "reasons_for": [{{"claim": "...", "evidence": ["technicals.rsi_14"]}}],
 "reasons_against": [{{"claim": "...", "evidence": ["citation:1"]}}],
 "would_change_mind": "what new evidence would flip this verdict"}}

Rules:
- Every claim's "evidence" list must reference the evidence above: a payload
  key path like "technicals.rsi_14" or "citation:N" for a sentiment source.
- Judge only from the transcript and evidence; do not add outside facts."""


@dataclass(frozen=True)
class DebateTurn:
    role: str  # "bull" | "bear"
    round: int
    argument: str


@dataclass(frozen=True)
class AnchoredReason:
    claim: str
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DebateVerdict:
    direction: Direction
    confidence: Optional[float]
    summary: str
    reasons_for: Tuple[AnchoredReason, ...] = ()
    reasons_against: Tuple[AnchoredReason, ...] = ()
    would_change_mind: Optional[str] = None


@dataclass(frozen=True)
class DebateResult:
    turns: List[DebateTurn] = field(default_factory=list)
    verdict: Optional[DebateVerdict] = None
    warnings: List[str] = field(default_factory=list)

    def to_detail(self) -> Dict[str, Any]:
        """JSON-ready audit trail for storage and the future debate UI."""
        verdict: Optional[Dict[str, Any]] = None
        if self.verdict is not None:
            verdict = {
                "direction": self.verdict.direction.value,
                "confidence": self.verdict.confidence,
                "summary": self.verdict.summary,
                "reasons_for": [
                    {"claim": r.claim, "evidence": list(r.evidence)}
                    for r in self.verdict.reasons_for
                ],
                "reasons_against": [
                    {"claim": r.claim, "evidence": list(r.evidence)}
                    for r in self.verdict.reasons_against
                ],
                "would_change_mind": self.verdict.would_change_mind,
            }
        return {
            "turns": [
                {"role": t.role, "round": t.round, "argument": t.argument}
                for t in self.turns
            ],
            "verdict": verdict,
            "warnings": list(self.warnings),
        }


def _transcript(turns: Sequence[DebateTurn]) -> str:
    if not turns:
        return "(the debate is just starting)"
    return "\n\n".join(
        f"[{t.role.upper()} — round {t.round}]\n{t.argument}" for t in turns
    )


class DebateEngine:
    """Runs bull/bear rounds plus the judge; never raises out of run()."""

    def __init__(
        self,
        summarizer: Optional[Callable[[str], str]] = None,
        rounds: int = DEFAULT_ROUNDS,
    ) -> None:
        if rounds < 1:
            raise ValueError("rounds must be >= 1")
        self._summarize = summarizer or default_summarizer
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
        try:
            for round_number in range(1, self._rounds + 1):
                for role, template in (("bull", _BULL_TEMPLATE), ("bear", _BEAR_TEMPLATE)):
                    argument = self._summarize(
                        template.format(
                            context=context,
                            symbol=symbol,
                            transcript=_transcript(turns),
                        )
                    ).strip()
                    turns.append(
                        DebateTurn(role=role, round=round_number, argument=argument)
                    )
            raw_verdict = self._summarize(
                _JUDGE_TEMPLATE.format(context=context, transcript=_transcript(turns))
            )
        except Exception as exc:  # fail-loud as a structured result
            return DebateResult(
                turns=turns,
                warnings=[f"debate LLM call failed: {exc}"],
            )

        verdict, warnings = self._parse_verdict(raw_verdict, dimensions)
        return DebateResult(turns=turns, verdict=verdict, warnings=warnings)

    @staticmethod
    def _parse_verdict(
        raw: str, dimensions: Sequence[DimensionResult]
    ) -> Tuple[Optional[DebateVerdict], List[str]]:
        parsed = parse_llm_json(raw)
        if parsed is None:
            return None, ["judge returned unparseable output"]

        direction = Direction.from_decision_type(parsed.get("direction"))
        if direction is Direction.UNKNOWN:
            return None, [
                f"judge returned unusable direction {parsed.get('direction')!r}"
            ]

        warnings: List[str] = []

        confidence = parsed.get("confidence")
        if isinstance(confidence, (int, float)) and 0 <= confidence <= 1:
            confidence = float(confidence)
        else:
            warnings.append(f"judge confidence {confidence!r} unusable — dropped")
            confidence = None

        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            warnings.append("judge gave no summary")

        def _reasons(key: str) -> Tuple[AnchoredReason, ...]:
            reasons: List[AnchoredReason] = []
            for item in parsed.get(key) or []:
                if not isinstance(item, dict):
                    continue
                claim = str(item.get("claim") or "").strip()
                if not claim:
                    continue
                evidence = validate_evidence(item.get("evidence") or [], dimensions)
                if not evidence:
                    warnings.append(
                        f"judge claim not anchored to evidence (kept, flagged): "
                        f"{claim[:80]}"
                    )
                reasons.append(AnchoredReason(claim=claim, evidence=tuple(evidence)))
            return tuple(reasons)

        verdict = DebateVerdict(
            direction=direction,
            confidence=confidence,
            summary=summary,
            reasons_for=_reasons("reasons_for"),
            reasons_against=_reasons("reasons_against"),
            would_change_mind=(
                str(parsed.get("would_change_mind")).strip()
                if parsed.get("would_change_mind")
                else None
            ),
        )
        return verdict, warnings
