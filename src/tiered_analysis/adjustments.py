# -*- coding: utf-8 -*-
"""LLM level adjustments under the evidence-anchoring contract (v2 slice 3).

The AI may propose moving a base level, but every proposal must cite at
least one verifiable reference — a dimension payload key that actually
resolves (``technicals.rsi_14``) or a verified sentiment citation number
(``citation:2``). Unverifiable proposals are dropped with a warning, in
the same spirit as the sentiment provider's quote verification. Band,
ordering, and reward-to-risk enforcement live in levels.apply_adjustments.

This is a separate, tiered-package-owned LLM call: Tier 1's own synthesis
happens inside DSA's decision path, which we never modify.
"""
from __future__ import annotations

import json
from typing import Callable, List, Optional, Sequence, Tuple

from .levels import LEVEL_KEYS, AdjustmentProposal, BaseLevels
from .llm_support import (
    default_summarizer,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult

_PROMPT_TEMPLATE = """You are reviewing formula-computed trade levels for {symbol}.

The deterministic base levels (value, formula, inputs):
{bases_json}

Collected evidence you may cite:
{evidence_block}

You may propose adjusting a level ONLY when the evidence justifies it.
Rules:
- An adjustment may move a level at most 1 x ATR away from its base; larger
  moves will be rejected by code.
- Every proposal must cite at least one evidence reference in "evidence":
  either a payload key path like "technicals.rsi_14" (must exist above) or
  "citation:N" for a numbered sentiment source above.
- Valid level keys: entry, secondary_entry, stop_loss, take_profit.
- Proposing NO adjustments is a perfectly good answer.

Reply with JSON only:
{{"adjustments": [{{"level": "entry", "value": 123.4,
 "reason": "one plain-language sentence", "evidence": ["citation:1"]}}]}}
"""


def _bases_json(bases: BaseLevels) -> str:
    body = {}
    for key in LEVEL_KEYS:
        basis = bases.get(key)
        if basis is not None:
            body[key] = {
                "value": basis.value,
                "formula": basis.formula,
                "inputs": basis.inputs,
            }
    return json.dumps(body, ensure_ascii=False, indent=1)


class LevelAdjuster:
    """Asks the LLM for bounded, evidence-cited level adjustments."""

    def __init__(self, summarizer: Optional[Callable[[str], str]] = None):
        self._summarize = summarizer or default_summarizer

    def propose(
        self,
        symbol: str,
        bases: BaseLevels,
        dimensions: Sequence[DimensionResult],
    ) -> Tuple[List[AdjustmentProposal], List[str]]:
        if bases.is_empty:
            return [], ["no base levels — AI adjustment skipped"]

        prompt = _PROMPT_TEMPLATE.format(
            symbol=symbol,
            bases_json=_bases_json(bases),
            evidence_block=evidence_block(dimensions),
        )
        try:
            raw = self._summarize(prompt)
        except Exception as exc:  # fail-loud as warnings, never crash the run
            return [], [f"level adjuster unavailable: {exc}"]

        parsed = parse_llm_json(raw)
        if parsed is None or not isinstance(parsed.get("adjustments"), list):
            return [], ["level adjuster returned unparseable output — bases kept"]

        proposals: List[AdjustmentProposal] = []
        warnings: List[str] = []
        for item in parsed["adjustments"]:
            if not isinstance(item, dict):
                warnings.append("malformed adjustment entry ignored")
                continue
            level = str(item.get("level", "")).strip()
            if level not in LEVEL_KEYS:
                warnings.append(f"adjustment for unknown level {level!r} ignored")
                continue
            value = item.get("value")
            if not isinstance(value, (int, float)) or value <= 0:
                warnings.append(f"adjustment for {level} has no usable value — dropped")
                continue
            reason = str(item.get("reason", "")).strip()
            if not reason:
                warnings.append(f"adjustment for {level} gives no reason — dropped")
                continue
            evidence = validate_evidence(item.get("evidence") or [], dimensions)
            if not evidence:
                warnings.append(
                    f"adjustment for {level} cites no verifiable evidence — dropped"
                )
                continue
            proposals.append(
                AdjustmentProposal(
                    level=level,
                    value=float(value),
                    reason=reason,
                    evidence=tuple(evidence),
                )
            )
        return proposals, warnings
