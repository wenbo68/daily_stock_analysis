# -*- coding: utf-8 -*-
"""Shared plumbing for the tiered package's own LLM calls (v2).

Used by the level adjuster (slice 3) and the tier-2 debate (slice 4).
These calls are owned by the tiered package — Tier 1's synthesis happens
inside DSA's decision path, which this package never modifies.

The evidence helpers implement the anchoring contract: LLM claims may only
reference collected evidence — a dimension payload key path that actually
resolves (``technicals.rsi_14``) or a verified sentiment citation number
(``citation:2``).
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Sequence

from .providers.base import DimensionResult

_CITATION_REF_RE = re.compile(r"^citation:(\d+)$")


class LlmConfigError(RuntimeError):
    """LLM configuration missing — callers surface this as a warning."""


def default_summarizer(prompt: str) -> str:
    import os

    model = (os.getenv("LITELLM_MODEL") or "").strip()
    if not model:
        raise LlmConfigError(
            "LITELLM_MODEL is not set; tiered-analysis LLM stages need the "
            "repo's standard LLM configuration"
        )
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def parse_llm_json(raw: str) -> Optional[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def resolve_payload_ref(ref: str, dimensions: Sequence[DimensionResult]) -> bool:
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


def validate_evidence(
    refs: Sequence[Any], dimensions: Sequence[DimensionResult]
) -> List[str]:
    """Keep only refs that resolve: payload paths or in-range citations."""
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
        if resolve_payload_ref(ref, dimensions):
            valid.append(ref)
    return valid


def evidence_block(dimensions: Sequence[DimensionResult]) -> str:
    """The evidence bundle LLM stages may cite, with the ref grammar shown."""
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
