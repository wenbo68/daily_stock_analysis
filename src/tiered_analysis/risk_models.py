# -*- coding: utf-8 -*-
"""Pydantic forms the tier-3 risk vote (risk_detail format 2) forces its
LLM calls to fill.

Tier 3 reuses the tier-2 vote machinery (two blind listers → merge →
check vote → deciding vote, citations checked by code with fix loops)
over RISK bullets: concrete things that could go wrong with the tier-2
trade plan. Differences from the tier-2 evidence forms:

- Risk bullets carry NO direction tag — every bullet is a risk; code
  counts the confirmed ones and maps the count to the size multiplier.
- A fifth group ``plan`` covers risks about the trade plan itself (the
  levels, the held shares); its values are cited as ``plan.<key>`` from
  a synthetic payload the engine builds from the tier-2 report.
- No per-group floor: an empty risk list is a legitimate answer ("no
  material risks — full size"), so only the anti-flood ceiling applies.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Sequence, Tuple

from pydantic import Field

from .debate_models import (
    LinkModel,
    MatchEntryModel,
    _StageModel,
    check_exact_keys,
)

#: Tree order for the five risk groups; also the id-prefix map. The four
#: report dimensions keep their tier-2 prefixes; plan risks are P1, P2…
RISK_GROUPS: Tuple[str, ...] = (
    "technicals",
    "fundamentals",
    "macro_econ",
    "sentiment",
    "plan",
)
RISK_GROUP_PREFIX: Dict[str, str] = {
    "technicals": "T",
    "fundamentals": "F",
    "macro_econ": "E",
    "sentiment": "S",
    "plan": "P",
}

RiskGroup = Literal["technicals", "fundamentals", "macro_econ", "sentiment", "plan"]


class RiskItemModel(_StageModel):
    """One risk bullet: an atomic 'what could go wrong' claim whose cited
    values carry code-verified links. The group is stored under the key
    ``dimension`` so the vote machinery and the UI treat risk bullets and
    tier-2 evidence bullets the same way."""

    id: str = Field(min_length=1)
    dimension: RiskGroup
    claim: str = Field(min_length=1)
    links: List[LinkModel] = Field(min_length=1)


class RiskListModel(_StageModel):
    """Step 1: one analyst's full risk list. Empty is allowed — finding
    no material risks is an answer, not a failure."""

    items: List[RiskItemModel] = Field(default_factory=list)


class RiskFixModel(_StageModel):
    """A risk citation-fix round's reply: corrected bullets, same ids."""

    items: List[RiskItemModel] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Run-time structural validators (retry-friendly ValueErrors)
# ---------------------------------------------------------------------------


def check_risk_items(
    items: Sequence[RiskItemModel],
    allowed_groups: Sequence[str],
    max_per_group: Dict[str, int],
) -> None:
    """Enforce the id scheme, the allowed groups, and the ceiling.

    ``allowed_groups`` is the code-verified list of groups that have data
    to cite (dimensions with evidence, plus ``plan`` when the tier-2 plan
    carries values). ``max_per_group`` is the anti-flood ceiling; there
    is NO floor — an empty group simply has no risks.
    """
    errors: List[str] = []
    seen_ids: Dict[str, str] = {}
    per_group: Dict[str, int] = {}
    for item in items:
        per_group[item.dimension] = per_group.get(item.dimension, 0) + 1
        prefix = RISK_GROUP_PREFIX[item.dimension]
        if not (item.id.startswith(prefix) and item.id[len(prefix):].isdigit()):
            errors.append(
                f"item id {item.id!r} must be {prefix}<number> for {item.dimension}"
            )
        if item.id in seen_ids:
            errors.append(f"duplicate item id {item.id!r}")
        seen_ids[item.id] = item.dimension
        if item.dimension not in allowed_groups:
            errors.append(
                f"item {item.id!r} cites group {item.dimension!r} which has "
                "no collected data — no risks can rest on it"
            )
    for group, count in per_group.items():
        ceiling = max_per_group.get(group)
        if ceiling is not None and count > ceiling:
            errors.append(
                f"group {group!r} has {count} risks — the maximum is {ceiling}"
            )
    if errors:
        raise ValueError("; ".join(errors))


def check_risk_match_map(
    match_map: Sequence[MatchEntryModel],
    own_ids: Sequence[str],
    first_ids: Sequence[str],
) -> None:
    """Every second-list risk mapped exactly once, to a real first-list
    risk or null. (No direction rule — risks have no direction; two
    bullets naming the same danger are simply the same risk.)"""
    check_exact_keys([m.own_id for m in match_map], list(own_ids), "match_map entry")
    bad_targets = [
        entry.own_id
        for entry in match_map
        if entry.covered_by is not None and entry.covered_by not in first_ids
    ]
    if bad_targets:
        raise ValueError(
            "match_map covered_by must be an existing first-list risk id or "
            f"null; bad entries for: {', '.join(bad_targets)}"
        )
