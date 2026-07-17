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
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .providers.base import DimensionResult

_CITATION_REF_RE = re.compile(r"^citation:(\d+)$")


class LlmConfigError(RuntimeError):
    """LLM configuration missing — callers surface this as a warning."""


@dataclass
class _StageUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


#: What the usage numbers cover — stored with them so a reader of an old
#: run is never left guessing (tier 1's synthesis runs inside DSA's own
#: pipeline and is billed/tracked there, not here).
USAGE_SCOPE_NOTE = (
    "tiered-package LLM calls only; the tier-1 synthesis runs inside the "
    "DSA pipeline and is not counted here"
)

_UNATTRIBUTED_STAGE = "unattributed"

_active = threading.local()


class LlmUsageTracker:
    """Per-run LLM call/token counter, grouped by pipeline stage.

    The orchestrator activates one tracker for the run and opens a stage
    around each LLM-using step; ``default_summarizer`` reports into
    whichever tracker is active on the current thread. No tracker active
    (v1 call sites, tests with fake summarizers) → recording is a no-op.
    """

    def __init__(self) -> None:
        self._stages: Dict[str, _StageUsage] = {}
        self._current: Optional[str] = None
        # Debate stages run two LLM calls in parallel threads; both report
        # into the same tracker.
        self._lock = threading.Lock()

    @contextmanager
    def activate(self):
        previous = getattr(_active, "tracker", None)
        _active.tracker = self
        try:
            yield self
        finally:
            _active.tracker = previous

    @contextmanager
    def stage(self, name: str):
        previous = self._current
        self._current = name
        try:
            yield
        finally:
            self._current = previous

    def record(
        self, prompt_tokens: Optional[int], completion_tokens: Optional[int]
    ) -> None:
        with self._lock:
            stage = self._stages.setdefault(
                self._current or _UNATTRIBUTED_STAGE, _StageUsage()
            )
            stage.calls += 1
            stage.prompt_tokens += int(prompt_tokens or 0)
            stage.completion_tokens += int(completion_tokens or 0)

    def to_detail(self) -> Dict[str, Any]:
        total = _StageUsage()
        for usage in self._stages.values():
            total.calls += usage.calls
            total.prompt_tokens += usage.prompt_tokens
            total.completion_tokens += usage.completion_tokens
        return {
            "stages": {name: u.as_dict() for name, u in self._stages.items()},
            "total": total.as_dict(),
            "scope": USAGE_SCOPE_NOTE,
        }


def record_llm_usage(
    prompt_tokens: Optional[int], completion_tokens: Optional[int]
) -> None:
    """Report one LLM call to the active tracker, if any."""
    tracker = getattr(_active, "tracker", None)
    if tracker is not None:
        tracker.record(prompt_tokens, completion_tokens)


def active_tracker() -> Optional["LlmUsageTracker"]:
    """The tracker active on this thread, or None.

    The tracker lives in thread-local storage, so code that fans LLM calls
    out to worker threads (the debate's parallel stages) must capture it
    here and re-``activate()`` it inside each worker — otherwise those
    calls silently vanish from the run's usage numbers.
    """
    return getattr(_active, "tracker", None)


def _summarize(prompt: str, temperature: float) -> str:
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
        temperature=temperature,
    )
    usage = getattr(response, "usage", None)
    record_llm_usage(
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )
    return response.choices[0].message.content or ""


def default_summarizer(prompt: str) -> str:
    return _summarize(prompt, temperature=0.2)


def deterministic_summarizer(prompt: str) -> str:
    """Zero-temperature summarizer: the scored tier-2 debate uses it so the
    same evidence grades the same way on every run."""
    return _summarize(prompt, temperature=0.0)


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


def resolve_payload_ref(
    ref: str, dimensions: Sequence[DimensionResult], leaf_only: bool = False
) -> bool:
    """True when ``dimension.key[.subkey…]`` points at real payload data.

    ``leaf_only=True`` (the v5 debate's citation rule) additionally
    requires the path to land on an actual value — a number, text, flag,
    or simple list — never on a grouping like ``technicals.macd``.
    """
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
        if node is not None and not (leaf_only and isinstance(node, dict)):
            return True
    return False


def validate_evidence(
    refs: Sequence[Any],
    dimensions: Sequence[DimensionResult],
    leaf_only: bool = False,
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
        if resolve_payload_ref(ref, dimensions, leaf_only=leaf_only):
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
