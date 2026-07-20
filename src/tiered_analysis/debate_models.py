# -*- coding: utf-8 -*-
"""Pydantic forms the tier-2 debate (v8) forces its LLM calls to fill.

Every stage of the debate (two analyst lists, the merge match-map, the
check round, the deciding round, citation fixes) is a strict typed form,
not free prose: the engine hands the model the exact JSON shape,
validates the reply against these models, retries once with the
validation errors shown, and degrades/voids per the failure rules if the
retry is still invalid.

v8: no defender/attacker/judge roles. Two analysts list evidence
independently; a merge call matches the two lists; every bullet's author
is its first valid vote (a bullet both analysts listed independently is
confirmed 2-0 on the spot); a check round casts the second vote on
single-author bullets; a deciding round breaks 1-1 ties. Citations are
code's job alone — links are ``{ref, value}`` (sentiment: bare
``{ref: citation:N}`` rendered as a trailing [N]) and every link,
including the ones inside vote reasons, is verified mechanically with a
fix loop. Structural rules that depend on run-time data live in the
validator helpers at the bottom — they raise ``ValueError`` with
retry-friendly messages.
"""
from __future__ import annotations

import re
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
#: dynamic: the number of leaf fields in that dimension's report
#: (sentiment: verified sources × 2), never below the floor — room for the
#: whole report, not a quota.
MIN_ITEMS_PER_DIMENSION = 2

Dimension = Literal["technicals", "fundamentals", "macro_econ", "sentiment"]
ItemDirection = Literal["bullish", "bearish"]

#: Importance weight of one bullet, rated by each voter (owner spec
#: 2026-07-20, widened to 1-5 the same day): 1 = very minor, 3 = normal
#: evidence, 5 = very important (could change the whole thesis).
#: Schema-validated — an out-of-range weight fails the form and triggers
#: the normal retry; an OMITTED weight degrades to 3 (the neutral
#: middle), which reproduces the old flat counting exactly.
Weight = Literal[1, 2, 3, 4, 5]
DEFAULT_WEIGHT = 3

_CITATION_REF_RE = re.compile(r"^citation:(\d+)$")


class _StageModel(BaseModel):
    # Tolerate extra keys (models love adding commentary fields); never
    # let them through to storage though — only declared fields survive.
    model_config = ConfigDict(extra="ignore")


class LinkModel(_StageModel):
    """One citation. Payload refs carry "value" — the value copied exactly
    as the report displays it (code verifies the copy AND that the
    sentence contains it). Sentiment refs ("citation:N") carry nothing
    extra — the UI renders them as trailing [N] links."""

    ref: str = Field(min_length=1)
    value: Optional[Union[float, str]] = None

    @model_validator(mode="after")
    def _payload_needs_value(self) -> "LinkModel":
        ref = self.ref.strip()
        if not _CITATION_REF_RE.match(ref) and (
            self.value is None
            or (isinstance(self.value, str) and not self.value.strip())
        ):
            raise ValueError(
                f'link {ref!r} must carry "value" — the value copied exactly '
                "as the report displays it"
            )
        return self


class EvidenceItemModel(_StageModel):
    """One evidence bullet: an atomic claim with a direction tag whose
    cited values carry code-verified links."""

    id: str = Field(min_length=1)
    dimension: Dimension
    direction: ItemDirection
    claim: str = Field(min_length=1)
    links: List[LinkModel] = Field(min_length=1)
    #: The author's own importance rating of this bullet (1-5).
    weight: Weight = DEFAULT_WEIGHT
    #: One short plain sentence saying why the rating is what it is —
    #: shown in the UI when the user clicks the author's check mark.
    weight_reason: Optional[str] = None


class ListModel(_StageModel):
    """Step 1: one analyst's full evidence list. No score — the position
    scores are computed by code from the direction tags."""

    items: List[EvidenceItemModel] = Field(min_length=1)
    no_data_dimensions: List[str] = Field(default_factory=list)


class CitationFixModel(_StageModel):
    """A bullet citation-fix round's reply: corrected bullets, same ids."""

    items: List[EvidenceItemModel] = Field(min_length=1)


class MatchEntryModel(_StageModel):
    """Merge match-map row: one second-list bullet → the first-list
    bullet covering the same evidence (same direction), or null."""

    own_id: str
    covered_by: Optional[str] = None


class MergeModel(_StageModel):
    """Step 2: the semantic diff of the two lists. Covered pairs mean the
    bullet was listed independently by both analysts (confirmed 2-0);
    uncovered second-list bullets join the merged list."""

    match_map: List[MatchEntryModel] = Field(default_factory=list)


class VoteModel(_StageModel):
    """One vote on a bullet: valid/invalid with a short reason — required
    either way, because the UI shows the reason when the user clicks the
    vote's mark. Numbers inside the reason must be cited with the same
    code-checked links the bullets use."""

    verdict: Literal["valid", "invalid"]
    reason: Optional[str] = None
    links: List[LinkModel] = Field(default_factory=list)
    #: The voter's own importance rating of the bullet (1-5), cast
    #: regardless of the verdict — it joins the bullet's weight median.
    weight: Weight = DEFAULT_WEIGHT
    #: One short plain sentence explaining the rating (see the item's
    #: field of the same name).
    weight_reason: Optional[str] = None

    @model_validator(mode="after")
    def _needs_reason(self) -> "VoteModel":
        if not (self.reason or "").strip():
            raise ValueError("every vote must carry a short non-empty reason")
        return self


class VoteRoundModel(_StageModel):
    """Steps 3 and 4: one vote per requested bullet id."""

    votes: Dict[str, VoteModel] = Field(default_factory=dict)


class VoteFixModel(_StageModel):
    """A vote citation-fix round's reply: corrected votes, same keys."""

    votes: Dict[str, VoteModel] = Field(default_factory=dict)


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
    first_items: Dict[str, EvidenceItemModel],
    own_items: Dict[str, EvidenceItemModel],
) -> None:
    """Every second-list bullet mapped exactly once, to a real first-list
    bullet of the SAME direction — a bullet citing the same evidence with
    the opposite direction is a genuine dispute and must stay unmatched
    so the votes can settle it."""
    check_exact_keys([m.own_id for m in match_map], list(own_ids), "match_map entry")
    bad_targets: List[str] = []
    direction_clashes: List[str] = []
    for entry in match_map:
        if entry.covered_by is None:
            continue
        if entry.covered_by not in first_items:
            bad_targets.append(entry.own_id)
            continue
        if (
            own_items[entry.own_id].direction
            != first_items[entry.covered_by].direction
        ):
            direction_clashes.append(entry.own_id)
    errors: List[str] = []
    if bad_targets:
        errors.append(
            "match_map covered_by must be an existing first-list bullet id or "
            f"null; bad entries for: {', '.join(bad_targets)}"
        )
    if direction_clashes:
        errors.append(
            "covered_by requires the SAME direction; opposite-direction "
            "bullets are disputes and must be left unmatched (null): "
            f"{', '.join(direction_clashes)}"
        )
    if errors:
        raise ValueError("; ".join(errors))
