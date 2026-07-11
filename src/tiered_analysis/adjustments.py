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
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .levels import LEVEL_KEYS, AdjustmentProposal, BaseLevels
from .providers.base import DimensionResult

_CITATION_REF_RE = re.compile(r"^citation:(\d+)$")

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


class AdjusterConfigError(RuntimeError):
    """LLM configuration missing — surfaced as a warning, never a crash."""


def _default_summarizer(prompt: str) -> str:
    import os

    model = (os.getenv("LITELLM_MODEL") or "").strip()
    if not model:
        raise AdjusterConfigError(
            "LITELLM_MODEL is not set; the level adjuster needs the repo's "
            "standard LLM configuration"
        )
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def _parse_llm_json(raw: str) -> Optional[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _resolve_payload_ref(ref: str, dimensions: Sequence[DimensionResult]) -> bool:
    """True when ``dimension.key[.subkey…]`` points at real payload data."""
    parts = ref.split(".")
    if len(parts) < 2:
        return False
    dimension_name, path = parts[0], parts[1:]
    for dim in dimensions:
        if dim.dimension != dimension_name or not dim.payload:
            continue
        node: Any = dim.payload
        for segment in path:
            if not isinstance(node, dict) or segment not in node:
                node = None
                break
            node = node[segment]
        if node is not None:
            return True
    return False


def _validate_evidence(
    refs: Sequence[Any], dimensions: Sequence[DimensionResult]
) -> List[str]:
    citation_count = max(
        (len(dim.citations or []) for dim in dimensions if dim.dimension == "sentiment"),
        default=0,
    )
    valid: List[str] = []
    for raw in refs:
        ref = str(raw).strip()
        citation = _CITATION_REF_RE.match(ref)
        if citation:
            if 1 <= int(citation.group(1)) <= citation_count:
                valid.append(ref)
            continue
        if _resolve_payload_ref(ref, dimensions):
            valid.append(ref)
    return valid


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


def _evidence_block(dimensions: Sequence[DimensionResult]) -> str:
    blocks: List[str] = []
    for dim in dimensions:
        if dim.payload:
            blocks.append(
                f"[{dim.dimension} payload — cite as \"{dim.dimension}.<key>\"]\n"
                + json.dumps(dim.payload, ensure_ascii=False, default=str)
            )
        if dim.dimension == "sentiment" and dim.narrative:
            lines = [f"[sentiment narrative]\n{dim.narrative}"]
            for index, citation in enumerate(dim.citations or [], start=1):
                title = citation.title or citation.source_name
                lines.append(f"citation:{index} = {title} ({citation.url})")
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "(no evidence collected)"


class LevelAdjuster:
    """Asks the LLM for bounded, evidence-cited level adjustments."""

    def __init__(self, summarizer: Optional[Callable[[str], str]] = None):
        self._summarize = summarizer or _default_summarizer

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
            evidence_block=_evidence_block(dimensions),
        )
        try:
            raw = self._summarize(prompt)
        except Exception as exc:  # fail-loud as warnings, never crash the run
            return [], [f"level adjuster unavailable: {exc}"]

        parsed = _parse_llm_json(raw)
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
            evidence = _validate_evidence(item.get("evidence") or [], dimensions)
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
