# -*- coding: utf-8 -*-
"""Pydantic forms the tier-2 debate (v6) forces its LLM calls to fill.

Every stage of the debate (defender opening, attacker opening, attacker
review, defender reply, judge rulings) is a strict typed form, not free
prose: the engine hands the model the exact JSON shape, validates the
reply against these models, retries once with the validation errors shown,
and degrades/voids per the failure rules if the retry is still invalid.

Structural rules that depend on run-time data (which dimensions actually
have evidence, which item ids exist) live in the validator helpers at the
bottom — they raise ``ValueError`` with retry-friendly messages.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Tree order for the four dimension groups; also the id-prefix map.
DIMENSIONS: Tuple[str, ...] = ("technicals", "fundamentals", "macro_econ", "sentiment")
DIMENSION_PREFIX: Dict[str, str] = {
    "technicals": "T",
    "fundamentals": "F",
    "macro_econ": "E",
    "sentiment": "S",
}

#: Every dimension that has collected data must contribute at least this
#: many evidence items — a floor so no dimension is skipped. The ceiling is
#: dynamic (v6): the number of leaf fields in that dimension's report
#: (sentiment: verified sources × 2), never below the floor — room for the
#: whole report, not a quota.
MIN_ITEMS_PER_DIMENSION = 2

Dimension = Literal["technicals", "fundamentals", "macro_econ", "sentiment"]
ItemDirection = Literal["bullish", "bearish"]


class _StageModel(BaseModel):
    # Tolerate extra keys (models love adding commentary fields); never
    # let them through to storage though — only declared fields survive.
    model_config = ConfigDict(extra="ignore")


class LinkModel(_StageModel):
    """One inline citation: the exact words in the claim, the leaf field
    they cite, and (for payload refs) the value the sentence claims —
    all three are verified mechanically by code."""

    text: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    value: Optional[Union[float, str]] = None


class EvidenceItemModel(_StageModel):
    """One evidence item: an atomic claim with a direction tag whose cited
    words carry inline, value-checked links."""

    id: str = Field(min_length=1)
    dimension: Dimension
    direction: ItemDirection
    claim: str = Field(min_length=1)
    links: List[LinkModel] = Field(min_length=1)


class DefenderOpeningModel(_StageModel):
    """Stage 1a: the defender's full evidence list. No score — the
    position scores are computed by code from the direction tags (v6)."""

    items: List[EvidenceItemModel] = Field(min_length=1)
    no_data_dimensions: List[str] = Field(default_factory=list)


class AttackerOpeningModel(_StageModel):
    """Stage 1b: the attacker's independent list — no score, no stance."""

    items: List[EvidenceItemModel] = Field(min_length=1)
    no_data_dimensions: List[str] = Field(default_factory=list)


class CheckModel(_StageModel):
    """One citation-or-logic check; 'invalid' must say why, with citations."""

    verdict: Literal["valid", "invalid"]
    reason: Optional[str] = None
    citations: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _invalid_needs_reason(self) -> "CheckModel":
        if self.verdict == "invalid" and not (self.reason or "").strip():
            raise ValueError("an 'invalid' check must carry a non-empty reason")
        return self


class ItemChecksModel(_StageModel):
    """The check pair every reviewer applies to one object."""

    citation_check: CheckModel
    logic_check: CheckModel


class MatchEntryModel(_StageModel):
    """Stage 2 match map row: one attacker item → covering defender item."""

    own_id: str
    covered_by: Optional[str] = None


class AttackerReviewModel(_StageModel):
    """Stage 2: the semantic diff of the two lists + checks on every
    defender item. Additions are derived by code from the match map
    (covered_by null → the attacker item becomes an addition)."""

    match_map: List[MatchEntryModel] = Field(default_factory=list)
    checks: Dict[str, ItemChecksModel]


class DefenderReplyModel(_StageModel):
    """Stage 3: the defender's mechanical response to every challenge —
    checks ON the attack/addition itself. No score output (v6)."""

    responses: Dict[str, ItemChecksModel] = Field(default_factory=dict)


class AttackRulingModel(_StageModel):
    """Stage 4: the judge's binary ruling on one attack."""

    verdict: Literal["attack_right", "attack_wrong"]
    reason: str = Field(min_length=1)
    citations: List[str] = Field(default_factory=list)


class JudgeModel(_StageModel):
    """Stage 4: the judge's complete ruling set — its own citation+logic
    check pair for EVERY item (defender-listed and attacker-added alike;
    an addition is "real" simply when both checks pass), plus a binary
    ruling per attack. The engine checks the key sets exactly."""

    reason_checks: Dict[str, ItemChecksModel] = Field(default_factory=dict)
    attack_rulings: Dict[str, AttackRulingModel] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run-time structural validators (retry-friendly ValueErrors)
# ---------------------------------------------------------------------------


def check_opening_items(
    items: Sequence[EvidenceItemModel],
    data_dimensions: Sequence[str],
    max_per_dimension: Dict[str, int],
) -> None:
    """Enforce the per-dimension floor/dynamic-ceiling and the id scheme.

    ``data_dimensions`` is the code-verified list of dimensions that have
    collected evidence — the "no data" escape hatch cannot be used for
    them, and dimensions outside it may not carry items.
    ``max_per_dimension`` is the code-computed ceiling per dimension
    (leaf-field count; sentiment sources × 2; never below the floor).
    """
    errors: List[str] = []
    seen_ids: Dict[str, str] = {}
    per_dimension: Dict[str, int] = {}
    for item in items:
        per_dimension[item.dimension] = per_dimension.get(item.dimension, 0) + 1
        prefix = DIMENSION_PREFIX[item.dimension]
        if not (item.id.startswith(prefix) and item.id[len(prefix):].isdigit()):
            errors.append(
                f"item id {item.id!r} must be {prefix}<number> for {item.dimension}"
            )
        if item.id in seen_ids:
            errors.append(f"duplicate item id {item.id!r}")
        seen_ids[item.id] = item.dimension
        if item.dimension not in data_dimensions:
            errors.append(
                f"item {item.id!r} cites dimension {item.dimension!r} which has "
                "no collected data — that dimension must be skipped"
            )
    for dimension in data_dimensions:
        count = per_dimension.get(dimension, 0)
        ceiling = max_per_dimension.get(dimension, MIN_ITEMS_PER_DIMENSION)
        if count < MIN_ITEMS_PER_DIMENSION:
            errors.append(
                f"dimension {dimension!r} has data but only {count} item(s) — "
                f"list {MIN_ITEMS_PER_DIMENSION}-{ceiling}"
            )
        elif count > ceiling:
            errors.append(
                f"dimension {dimension!r} has {count} items — "
                f"the maximum is {ceiling}"
            )
    if errors:
        raise ValueError("; ".join(errors))


def check_exact_keys(given: Sequence[str], required: Sequence[str], what: str) -> None:
    """The stage must cover exactly ``required`` — no gaps, no inventions."""
    missing = [key for key in required if key not in given]
    extra = [key for key in given if key not in required]
    errors: List[str] = []
    if missing:
        errors.append(f"missing {what} for: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown {what} keys: {', '.join(extra)}")
    if errors:
        raise ValueError("; ".join(errors))


def check_match_map(
    match_map: Sequence[MatchEntryModel],
    own_ids: Sequence[str],
    defender_ids: Sequence[str],
) -> None:
    """Every attacker item mapped exactly once, to a real defender id."""
    check_exact_keys([m.own_id for m in match_map], list(own_ids), "match_map entry")
    bad_targets = [
        m.own_id
        for m in match_map
        if m.covered_by is not None and m.covered_by not in defender_ids
    ]
    if bad_targets:
        raise ValueError(
            "match_map covered_by must be an existing defender item id or null; "
            f"bad entries for: {', '.join(bad_targets)}"
        )
