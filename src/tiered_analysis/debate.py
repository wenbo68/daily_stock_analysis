# -*- coding: utf-8 -*-
"""Tier 2: threaded bull/bear debate with a deterministic verdict (v4).

Redesign (owner spec, 2026-07-16). Two symmetric threads, each shaped like
a real investment-committee pitch — argue, be attacked, respond:

    thread A: bull argues → bear attacks it → bull responds + position score
    thread B: bear argues → bull attacks it → bear responds + position score

The two threads are independent, so each stage runs its two LLM calls in
parallel (arguments together, attacks together, responses together).
Attacks are structured along the same three axes the judge grades on:
citation validity, knowledge validity, logical validity.

The position score (0 = strongly bearish, 5 = neutral, 10 = strongly
bullish, whole number) is given only in the response turn — after the
debater has seen and answered the attack on its case.

A grading judge then scores each side 0-5 per axis over EVERYTHING it
wrote (argument, attack, and response — a lazy or false attack costs the
attacker points). Any grade below 5 must quote the exact offending
sentence verbatim plus a plain-English reason; the quote is code-checked
against the transcript and flagged when it does not match. Code (not the
LLM) computes the verdict:

    weight   = (citation + knowledge + logic) / 15          per debater
    final    = (w_bull × s_bull + w_bear × s_bear) / (w_bull + w_bear)
    verdict  = round half-up → 0-3 sell, 4-6 hold, 7-10 buy

A summary judge writes the user-facing prose AROUND the computed number;
its failure never voids the verdict. All calls run at temperature 0.
Anti-fabrication contract unchanged: debaters may only cite the supplied
evidence bundle; refs are code-validated and invalid ones dropped. An
off-spec number (non-whole position score, out-of-range grade) voids the
verdict — the tier degrades and the tier-1 direction stands.
"""
from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .llm_support import (
    active_tracker,
    deterministic_summarizer,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult
from .schema import Direction, TierReport

#: weight = (citation + knowledge + logic) / this — three 0-5 axes.
VALIDITY_MAX_TOTAL = 15

#: Verdict thresholds on the rounded final score (owner spec).
SELL_MAX = 3
HOLD_MAX = 6

GRADE_AXES = ("citation_validity", "knowledge_validity", "logical_validity")


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

_CITE_RULES = """- "citations" must list every piece of evidence you lean on: a payload
  key path like "technicals.rsi_14" or "citation:N" for a news source
  from the evidence above.
- Use only the evidence above; do not invent facts."""

_ROLE_TASK = {
    "bull": "argue the strongest honest case FOR buying {symbol}",
    "bear": (
        "argue the strongest honest case AGAINST buying {symbol} "
        "(risks, weaknesses, counter-evidence)"
    ),
}

_ARGUMENT_TEMPLATE = """{context}
You are the {role_upper} analyst: {role_task}.
Your opponent has not spoken yet — this is your opening argument.

Reply with JSON only:
{{"argument": "your case in at most 180 words of plain English",
 "citations": ["technicals.rsi_14", "citation:1"]}}

Rules:
""" + _CITE_RULES

_ATTACK_TEMPLATE = """{context}
You are the {role_upper} analyst. Your opponent, the {opponent_upper},
made this opening argument:

{opponent_block}

Attack that argument on exactly three fronts, quoting your opponent's own
sentences where you can:
1. citation validity — does the evidence it cites really say what it
   claims? Check its citations against the evidence above.
2. knowledge validity — is its financial knowledge correct?
3. logical validity — assuming its facts were true, do its conclusions
   actually follow?

If a front has no real weakness, say so honestly instead of inventing one
— a false attack will cost you with the judge.

Reply with JSON only:
{{"argument": "your attack in at most 180 words, covering the three fronts",
 "citations": ["technicals.rsi_14", "citation:1"]}}

Rules:
""" + _CITE_RULES

_RESPONSE_TEMPLATE = """{context}
You are the {role_upper} analyst. Your opening argument was:

{own_block}

The {opponent_upper} attacked it:

{attack_block}

Respond: defend the points you can defend, concede the points you cannot,
then give your final position score.

Reply with JSON only:
{{"argument": "your response in at most 150 words",
 "citations": ["technicals.rsi_14", "citation:1"],
 "position_score": <whole number 0-10>}}

Rules:
- "position_score" is your honest overall read of the stock after this
  exchange: 0 = strongly bearish, 5 = neither, 10 = strongly bullish.
  Argue your role, but score honestly — if the attack landed, move your
  number.
""" + _CITE_RULES

_GRADING_TEMPLATE = """{context}
Full debate transcript — each side wrote an opening argument, an attack
on the opponent's argument, and a response to the attack on its own:
{transcript}

You are the research manager grading this debate. Do NOT pick a direction
— code computes the verdict from your grades. Grade each side on three
axes, each a whole number from 0 (worthless) to 5 (flawless). The grade
covers EVERYTHING that side wrote — its argument, its attack, and its
response. A lazy, false, or invented attack costs the attacker points
exactly like a bad argument would.

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

For every axis give a score, and:
- score 5 → "quote" and "why" must be null (nothing was wrong).
- score below 5 → "quote" must be ONE exact sentence copied verbatim,
  character for character, from that side's own turns above, and "why"
  must explain in plain English what is wrong with it. Never paraphrase
  the quote — it is checked mechanically against the transcript.

Reply with JSON only:
{{"bull": {{"citation_validity": {{"score": <0-5>, "quote": <verbatim sentence or null>, "why": <reason or null>}},
          "knowledge_validity": {{"score": <0-5>, "quote": ..., "why": ...}},
          "logical_validity": {{"score": <0-5>, "quote": ..., "why": ...}}}},
 "bear": {{"citation_validity": {{...}}, "knowledge_validity": {{...}}, "logical_validity": {{...}}}}}}"""

_SUMMARY_TEMPLATE = """{context}
Full debate transcript:
{transcript}

Your validity grades:
{grades}

Computed result (fixed formula — each side's position score weighted by
its validity grades): final position score {final} out of 10, rounded to
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
    kind: str  # "argument" | "attack" | "response"
    argument: str
    #: The debater's honest 0-10 read; only response turns carry one.
    position_score: Optional[int] = None
    #: Code-validated evidence refs the text leans on.
    citations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AnchoredReason:
    claim: str
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AxisGrade:
    """One judge grade: the score plus, below 5, the offending sentence."""

    score: int
    quote: Optional[str] = None
    why: Optional[str] = None


@dataclass(frozen=True)
class DebaterScore:
    """One side's numbers: its own position score plus the judge's grades."""

    position_score: int
    citation_validity: AxisGrade
    knowledge_validity: AxisGrade
    logical_validity: AxisGrade

    @property
    def weight(self) -> float:
        return (
            self.citation_validity.score
            + self.knowledge_validity.score
            + self.logical_validity.score
        ) / VALIDITY_MAX_TOTAL


@dataclass(frozen=True)
class DebateVerdict:
    direction: Direction
    #: The validity-weighted average of the two position scores, 0-10.
    final_score: float
    #: final_score rounded half-up — the number the direction maps from.
    final_score_rounded: int
    summary: str
    bull_summary: Optional[str] = None
    bear_summary: Optional[str] = None
    scoring: Optional[Dict[str, DebaterScore]] = None  # keys: "bull", "bear"


def _axis_detail(grade: AxisGrade) -> Dict[str, Any]:
    return {"score": grade.score, "quote": grade.quote, "why": grade.why}


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
                        "position_score": s.position_score,
                        "citation_validity": _axis_detail(s.citation_validity),
                        "knowledge_validity": _axis_detail(s.knowledge_validity),
                        "logical_validity": _axis_detail(s.logical_validity),
                        "weight": round(s.weight, 4),
                        # Legacy alias kept so v3 readers never crash.
                        "bullishness": s.position_score,
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
                    "kind": t.kind,
                    "argument": t.argument,
                    "position_score": t.position_score,
                    "citations": list(t.citations),
                    # Legacy alias kept so v3 readers never crash.
                    "bullishness": t.position_score,
                }
                for t in self.turns
            ],
            "verdict": verdict,
            "warnings": list(self.warnings),
        }


def _turn_header(turn: DebateTurn) -> str:
    if turn.kind == "attack":
        opponent = "bear" if turn.role == "bull" else "bull"
        label = f"attack on the {opponent}'s argument"
    else:
        label = turn.kind
    header = f"[{turn.role.upper()} — {label}"
    if turn.position_score is not None:
        header += f" — position score {turn.position_score}/10"
    return header + "]"


def _turn_block(turn: DebateTurn) -> str:
    body = turn.argument
    if turn.citations:
        body += "\ncited: " + ", ".join(turn.citations)
    return f"{_turn_header(turn)}\n{body}"


def _transcript(turns: Sequence[DebateTurn]) -> str:
    if not turns:
        return "(the debate is just starting)"
    return "\n\n".join(_turn_block(t) for t in turns)


def _whole_number(value: Any, low: int, high: int) -> Optional[int]:
    """value as an int in [low, high], or None when off-spec."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if float(value) != int(value):
        return None
    number = int(value)
    return number if low <= number <= high else None


def _squash(text: str) -> str:
    """Whitespace-insensitive form for verbatim-quote checking."""
    return re.sub(r"\s+", " ", text).strip()


class DebateEngine:
    """Runs the threaded debate: argue/attack/respond (stages in parallel)
    → grading judge → code formula → summary judge. Never raises out of
    run()."""

    def __init__(self, summarizer: Optional[Callable[[str], str]] = None) -> None:
        # Temperature 0 by default: deterministic grades for the formula.
        self._summarize = summarizer or deterministic_summarizer

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
            # Stage 1 — both opening arguments, in parallel.
            bull_arg, bear_arg = self._stage_pair(
                self._argument_prompt(context, symbol, "bull"),
                self._argument_prompt(context, symbol, "bear"),
                ("bull", "bear"),
                "argument",
                dimensions,
                warnings,
            )
            turns = [bull_arg, bear_arg]  # partial transcript if a later stage dies
            # Stage 2 — each side attacks the other's argument, in parallel.
            bear_attack, bull_attack = self._stage_pair(
                self._attack_prompt(context, "bear", bull_arg),
                self._attack_prompt(context, "bull", bear_arg),
                ("bear", "bull"),
                "attack",
                dimensions,
                warnings,
            )
            turns = [bull_arg, bear_attack, bear_arg, bull_attack]
            # Stage 3 — each side answers the attack on its own case and
            # gives its position score, in parallel.
            bull_resp, bear_resp = self._stage_pair(
                self._response_prompt(context, "bull", bull_arg, bear_attack),
                self._response_prompt(context, "bear", bear_arg, bull_attack),
                ("bull", "bear"),
                "response",
                dimensions,
                warnings,
            )
            # Reading order: thread A (bull's case) then thread B (bear's).
            turns = [bull_arg, bear_attack, bull_resp, bear_arg, bull_attack, bear_resp]
            raw_grades = self._summarize(
                _GRADING_TEMPLATE.format(context=context, transcript=_transcript(turns))
            )
        except Exception as exc:  # fail-loud as a structured result
            return DebateResult(
                turns=turns,
                warnings=warnings + [f"debate LLM call failed: {exc}"],
            )

        scores = {t.role: t.position_score for t in (bull_resp, bear_resp)}
        missing = [role for role in ("bull", "bear") if scores.get(role) is None]
        if missing:
            return DebateResult(
                turns=turns,
                warnings=warnings
                + [
                    f"no usable position score from {', '.join(missing)} — "
                    "tier-2 verdict voided"
                ],
            )

        grades, grade_warnings = self._parse_grades(raw_grades, turns)
        warnings.extend(grade_warnings)
        if grades is None:
            return DebateResult(turns=turns, warnings=warnings)

        scoring = {
            side: DebaterScore(position_score=scores[side], **grades[side])
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

    # -- prompt builders ---------------------------------------------------

    @staticmethod
    def _argument_prompt(context: str, symbol: str, role: str) -> str:
        return _ARGUMENT_TEMPLATE.format(
            context=context,
            role_upper=role.upper(),
            role_task=_ROLE_TASK[role].format(symbol=symbol),
        )

    @staticmethod
    def _attack_prompt(context: str, role: str, opponent_argument: DebateTurn) -> str:
        opponent = opponent_argument.role
        return _ATTACK_TEMPLATE.format(
            context=context,
            role_upper=role.upper(),
            opponent_upper=opponent.upper(),
            opponent_block=_turn_block(opponent_argument),
        )

    @staticmethod
    def _response_prompt(
        context: str, role: str, own_argument: DebateTurn, attack: DebateTurn
    ) -> str:
        return _RESPONSE_TEMPLATE.format(
            context=context,
            role_upper=role.upper(),
            opponent_upper=attack.role.upper(),
            own_block=_turn_block(own_argument),
            attack_block=_turn_block(attack),
        )

    # -- stage execution ---------------------------------------------------

    def _stage_pair(
        self,
        prompt_a: str,
        prompt_b: str,
        roles: Tuple[str, str],
        kind: str,
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> Tuple[DebateTurn, DebateTurn]:
        """One debate stage: the two independent calls run in parallel."""
        # The usage tracker is thread-local; hand it to the workers so
        # their calls still count toward the run's AI-calls number.
        tracker = active_tracker()

        def call(prompt: str) -> str:
            if tracker is None:
                return self._summarize(prompt)
            with tracker.activate():
                return self._summarize(prompt)

        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(call, prompt_a)
            future_b = pool.submit(call, prompt_b)
            raw_a, raw_b = future_a.result(), future_b.result()
        turn_a, warnings_a = self._parse_turn(raw_a, roles[0], kind, dimensions)
        turn_b, warnings_b = self._parse_turn(raw_b, roles[1], kind, dimensions)
        warnings.extend(warnings_a)
        warnings.extend(warnings_b)
        return turn_a, turn_b

    # -- parsing -----------------------------------------------------------

    @staticmethod
    def _parse_turn(
        raw: str,
        role: str,
        kind: str,
        dimensions: Sequence[DimensionResult],
    ) -> Tuple[DebateTurn, List[str]]:
        """One debater reply → a turn; off-spec parts degrade, not crash."""
        warnings: List[str] = []
        expect_score = kind == "response"
        parsed = parse_llm_json(raw)
        if parsed is None:
            message = f"{role} {kind} was not JSON — kept as plain text"
            if expect_score:
                message += ", no score"
            warnings.append(message)
            return DebateTurn(role=role, kind=kind, argument=raw.strip()), warnings

        argument = str(parsed.get("argument") or "").strip() or raw.strip()

        position_score: Optional[int] = None
        if expect_score:
            position_score = _whole_number(parsed.get("position_score"), 0, 10)
            if position_score is None:
                warnings.append(
                    f"{role} position score {parsed.get('position_score')!r} is "
                    "not a whole number 0-10 — dropped"
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
                kind=kind,
                argument=argument,
                position_score=position_score,
                citations=tuple(citations),
            ),
            warnings,
        )

    @staticmethod
    def _parse_grades(
        raw: str, turns: Sequence[DebateTurn]
    ) -> Tuple[Optional[Dict[str, Dict[str, AxisGrade]]], List[str]]:
        """Judge grades → per-side AxisGrades; an off-spec score voids,
        a bad or missing quote only flags (the grade itself is usable)."""
        parsed = parse_llm_json(raw)
        if parsed is None:
            return None, ["grading judge returned unparseable output — tier-2 verdict voided"]

        side_text = {
            side: _squash(" ".join(t.argument for t in turns if t.role == side))
            for side in ("bull", "bear")
        }

        warnings: List[str] = []
        grades: Dict[str, Dict[str, AxisGrade]] = {}
        for side in ("bull", "bear"):
            node = parsed.get(side)
            if not isinstance(node, dict):
                return None, [f"grading judge gave no {side} grades — tier-2 verdict voided"]
            axes: Dict[str, AxisGrade] = {}
            for axis in GRADE_AXES:
                cell = node.get(axis)
                # Tolerate a bare number (v3-shaped reply): score, no comment.
                if isinstance(cell, dict):
                    raw_score, quote, why = cell.get("score"), cell.get("quote"), cell.get("why")
                else:
                    raw_score, quote, why = cell, None, None
                score = _whole_number(raw_score, 0, 5)
                if score is None:
                    return None, warnings + [
                        f"grading judge {side} {axis} {raw_score!r} is not "
                        "a whole number 0-5 — tier-2 verdict voided"
                    ]
                quote = str(quote).strip() if quote else None
                why = str(why).strip() if why else None
                if score == 5:
                    # A flawless grade needs no comment — N/A in the UI.
                    quote, why = None, None
                elif quote is None:
                    warnings.append(
                        f"grading judge gave no quote for {side} {axis} "
                        f"score {score}/5 — kept, flagged"
                    )
                elif _squash(quote) not in side_text[side]:
                    warnings.append(
                        f"grading judge quote for {side} {axis} not found "
                        "verbatim in the transcript — kept, flagged"
                    )
                axes[axis] = AxisGrade(score=score, quote=quote, why=why)
            grades[side] = axes
        return grades, warnings

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
            bull.weight * bull.position_score + bear.weight * bear.position_score
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
            f"{side}: position score {s.position_score}/10; "
            + "; ".join(
                f"{axis.split('_')[0]} {grade.score}/5"
                + (f' (quote: "{grade.quote}" — {grade.why})' if grade.quote else "")
                for axis, grade in (
                    ("citation_validity", s.citation_validity),
                    ("knowledge_validity", s.knowledge_validity),
                    ("logical_validity", s.logical_validity),
                )
            )
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
