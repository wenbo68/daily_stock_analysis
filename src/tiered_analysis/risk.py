# -*- coding: utf-8 -*-
"""Tier 3: the risk vote (risk_detail format 2).

Redesign (owner spec 2026-07-19) replacing the three risk personas +
risk judge: tier 3 now runs the SAME vote machinery as the tier-2
evidence vote, over RISK bullets — concrete, evidence-cited ways the
tier-2 trade plan could lose money.

- Two risk analysts list risks blind and in parallel; a merge call
  matches the two lists (a risk both listed independently is confirmed
  2-0 at birth); a check round casts the second vote on single-author
  risks; a deciding round breaks 1-1 ties. Citations follow the tier-2
  display-value contract, verified by code with fix loops; unfixable
  risks are struck, unfixable votes discarded.
- Risks carry NO direction tag and NO floor: an empty list is a valid
  answer. A fifth group ``plan`` (ids P1, P2…) covers risks about the
  plan itself — the engine exposes the tier-2 levels and the user's
  held shares as a synthetic ``plan.<key>`` payload so those numbers
  are citable under the same contract.
- NO AI picks the size. Code counts the confirmed risks and maps the
  count to the multiplier: 0 → 1.0 (full size), 1-3 → 0.5 (half),
  4+ → 0 (do not open / do not reduce). The stance is tier 2's own
  direction, echoed — tier 3 no longer re-judges it, and stop advice
  is gone (the tier-2 levels stand).

Failure rules mirror tier 2: both lists failing voids the tier-3
verdict (the tier-2 output stands, no multiplier); one list failing
proceeds with the other; a failed merge drops the second list; a failed
check round counts risks on their author's vote alone; a failed
deciding round excludes the tied risks as unresolved; the summary's
failure never voids anything.

``apply_size_multiplier`` stays code's job: the multiplier scales the
computed buy size, or — new with the ownership input — the held shares
a sell verdict says to exit.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .debate import (
    DebateEngine,
    MAX_FIX_ROUNDS,
    _link_detail,
    _links_text,
    _items_json,
    _strip_citation_markers,
    _vote_text,
    max_items_per_dimension,
)
from .debate_models import DIMENSIONS, MergeModel
from .providers.base import Coverage, DimensionResult, SourceKind
from .risk_models import (
    RISK_GROUP_PREFIX,
    RISK_GROUPS,
    RiskFixModel,
    RiskItemModel,
    RiskListModel,
    check_risk_items,
    check_risk_match_map,
)
from .llm_support import active_tracker, evidence_block, parse_llm_json
from .schema import Direction, TierReport

#: The only sizes code may pick: full position, half, or none.
SIZE_MULTIPLIERS = (0.0, 0.5, 1.0)

#: The fixed count → multiplier mapping (owner spec: deterministic on
#: purpose; every threshold is visible, nothing is judged).
FULL_SIZE_MAX_RISKS = 0  # this many confirmed risks or fewer → 1.0x
HALF_SIZE_MAX_RISKS = 3  # this many confirmed risks or fewer → 0.5x

#: Stored-detail version marker — the frontend picks its renderer by
#: this. Absent = the old persona/judge shape; 2 = the risk vote.
DETAIL_FORMAT = 2


def multiplier_from_risk_count(confirmed: int) -> float:
    """The fixed mapping from confirmed risks to the size multiplier."""
    if confirmed <= FULL_SIZE_MAX_RISKS:
        return 1.0
    if confirmed <= HALF_SIZE_MAX_RISKS:
        return 0.5
    return 0.0


@dataclass(frozen=True)
class RiskVerdict:
    #: Tier 2's direction, echoed — tier 3 does not re-judge it.
    stance: Direction
    size_multiplier: float
    summary: str
    confirmed_risks: int
    total_risks: int
    #: Per-pool audit: {initial|final: {groups: {group: count}, total}}.
    counts: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskResult:
    #: The risk list, one dict per bullet (same shape as the tier-2
    #: vote items, minus the direction tag).
    items: List[Dict[str, Any]] = field(default_factory=list)
    verdict: Optional[RiskVerdict] = None
    warnings: List[str] = field(default_factory=list)

    def to_detail(self) -> Dict[str, Any]:
        """JSON-ready audit trail for storage and the risk-tree UI."""
        verdict: Optional[Dict[str, Any]] = None
        if self.verdict is not None:
            v = self.verdict
            verdict = {
                "stance": v.stance.value,
                "size_multiplier": v.size_multiplier,
                "summary": v.summary,
                "confirmed_risks": v.confirmed_risks,
                "total_risks": v.total_risks,
                "counts": v.counts,
                # Legacy keys kept so pre-format-2 readers never crash.
                "confidence": None,
                "stop_advice": "keep",
                "tightened_stop": None,
                "key_risks": [],
            }
        return {
            "format": DETAIL_FORMAT,
            # Legacy key: the persona renderer iterates takes; there are none.
            "takes": [],
            "items": [dict(item) for item in self.items],
            "verdict": verdict,
            "warnings": list(self.warnings),
        }


def apply_size_multiplier(shares: int, multiplier: float, lot_size: int = 1) -> int:
    """Scale a computed share count by the risk multiplier — code, not LLM."""
    if multiplier not in SIZE_MULTIPLIERS:
        raise ValueError(
            f"size multiplier must be one of {SIZE_MULTIPLIERS}, got {multiplier}"
        )
    if shares <= 0 or lot_size <= 0:
        return 0
    return int(math.floor(shares * multiplier / lot_size)) * lot_size


# ---------------------------------------------------------------------------
# The plan payload (synthetic ``plan.<key>`` evidence group)
# ---------------------------------------------------------------------------


def plan_dimension(tier2: TierReport, ownership: int = 0) -> Optional[DimensionResult]:
    """The trade plan as citable evidence: the tier-2 levels plus the
    user's held shares, rendered like any other payload so ``plan.entry``
    resolves through the same citation checks."""
    payload: Dict[str, Any] = {}
    levels = tier2.levels
    for key, value in (
        ("entry", levels.entry),
        ("secondary_entry", levels.secondary_entry),
        ("stop_loss", levels.stop_loss),
        ("take_profit", levels.take_profit),
    ):
        if value is not None:
            payload[key] = value
    if ownership > 0:
        payload["ownership_shares"] = int(ownership)
    if not payload:
        return None
    return DimensionResult(
        dimension="plan",
        kind=SourceKind.NUMERIC,
        coverage=Coverage.FULL,
        payload=payload,
    )


def risk_ceilings(
    dimensions: Sequence[DimensionResult], plan: Optional[DimensionResult]
) -> Dict[str, int]:
    """Anti-flood ceilings per group (no floor): the tier-2 leaf-count
    ceilings for the four dimensions, the plan payload's field count for
    ``plan``."""
    ceilings = max_items_per_dimension(dimensions)
    if plan is not None and plan.payload:
        ceilings["plan"] = max(len(plan.payload), 2)
    return ceilings


# ---------------------------------------------------------------------------
# Prompts — one marker phrase per stage so tests can route replies.
# ---------------------------------------------------------------------------

_RISK_CONTEXT_TEMPLATE = """Stock under risk review: {symbol}
Tier-2 verdict (already decided — tier 3 does NOT re-judge the direction): {direction}, score={score}
The trade plan under stress test is the "plan" payload below: the price
levels{ownership_note}.

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence_block}
"""

_OWNERSHIP_NOTE = ", plus ownership_shares — the shares the user already holds"

_RISK_LINK_RULES = """Link rules (all checked mechanically by code):
- Every risk carries "links": one entry per report or plan field the
  sentence uses, each {{"ref": the leaf field, "value": the value copied
  EXACTLY as the report above displays it}}.
- The claim sentence must contain each linked value verbatim — "The
  14-day RSI (71.20) is overbought", never "RSI is high". Copy the
  displayed string exactly: if the report shows 71.20, write 71.20,
  never 71.2 or 71.200. Write values as plain numbers in the sentence —
  do not wrap them in quotation marks.
- A "ref" must point at ONE exact value, like "technicals.rsi_14" or
  "plan.stop_loss" — grouping paths are rejected; cite the leaf.
- Risks resting on a news source cite it with {{"ref": "citation:N"}}
  and no "value" — the source numbers are shown as [N] links after the
  bullet.
- Code verifies every link and sends failures back to you to fix; risks
  that cannot be fixed are struck from the list.
- Use only the evidence above; never invent facts or numbers."""

_RISK_LIST_RULES = """Risk-list rules:
- Group risks by where their evidence lives: technicals, fundamentals,
  macro_econ, sentiment — plus "plan" for risks about the trade plan
  itself (a stop too close to the entry, a thin reward for the risk, a
  large holding exposed).
- List only REAL risks: a concrete, evidence-backed way this plan loses
  money. Do not restate neutral facts, and never invent a risk to fill
  space — an empty list is a valid answer when the evidence shows no
  material danger.
- Per-group maximum counts: {ceilings}. There is NO minimum.
- Each risk: one atomic claim (one sentence) containing the cited names
  AND values. Code counts the confirmed risks — the count sets the
  position-size multiplier; nobody writes a score.
- Risk ids: T1, T2… for technicals, F1… for fundamentals, E1… for
  macro_econ, S1… for sentiment, P1… for plan."""

_RISK_ITEM_SHAPE = """{{"id": "T1", "dimension": "technicals",
  "claim": "The 14-day RSI (71.20) is in overbought territory, so the entry may fill right before a pullback.",
  "links": [{{"ref": "technicals.rsi_14", "value": "71.20"}}]}}"""

_RISK_LISTER1_TEMPLATE = """{context}
You are the FIRST risk analyst. Another risk analyst is stress-testing
the same plan separately; neither of you sees the other's work. List
every REAL risk to this plan you can find in the reports above. Walk
each report from top to bottom, field by field, and check the plan
payload last, so nothing is skipped.

{list_rules}

{link_rules}

Reply with JSON only:
{{"items": [{item_shape}]}}"""

_RISK_LISTER2_TEMPLATE = """{context}
You are the SECOND risk analyst. Another risk analyst is stress-testing
the same plan separately; you have NOT seen their work. List every REAL
risk to this plan you can find in the reports above. Work threat by
threat — trend reversal, stretched valuation, balance-sheet strain,
macro pressure, adverse news, and the plan's own numbers — then
double-check you covered every report.

{list_rules}

{link_rules}

Reply with JSON only:
{{"items": [{item_shape}]}}"""

_RISK_CITATION_FIX_TEMPLATE = """Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

Some of your risk bullets failed the code's citation check. Fix each
bullet listed below: point the ref at the right leaf field, copy the
value exactly as the report above displays it, and make sure the claim
sentence contains that exact value. Keep each bullet's "id" and
"dimension" unchanged; you may rewrite the claim and the links.

{link_rules}

The bullets to fix:
{bullets}

The code's error list:
{errors}

Reply with JSON only:
{{"items": [ ...every bullet above, corrected, same ids... ]}}"""

_RISK_MERGE_TEMPLATE = """{context}
Match the two risk lists below. Two analysts worked independently; your
only job is the match map — code assembles the merged list.

The first analyst's list:
{first_items}

The second analyst's list:
{second_items}

For EVERY risk on the second list, say which first-list risk names the
SAME danger ("covered_by": its id), or null if there is none. Rules:
- "Covers" means the same underlying risk, even if worded differently.
- Never stretch a match; an unmatched risk simply joins the list.

Reply with JSON only:
{{"match_map": [{{"own_id": "T1", "covered_by": "T2"}}, {{"own_id": "F3", "covered_by": null}}]}}"""

_RISK_CHECK_TEMPLATE = """{context}
The merged risk list (every bullet's numbers already code-verified):
{tree}

Each risk named below was listed by only ONE of the two analysts, so it
has one vote so far (its author's). You cast the second vote on each:
- "valid" — the sentence says something TRUE about the verified values
  AND it describes a real risk to this plan.
- "invalid" — the statement is wrong about the values, or it is not
  actually a risk (a neutral fact, a stretch, a double-count of another
  bullet). Say why.
Vote on the risk in front of you, not on the stock.

{vote_rules}

Reply with JSON only:
{{"votes": {{"T2": {{"verdict": "invalid", "reason": "why it is flawed", "links": [{{"ref": "technicals.close", "value": "100"}}]}}}}}}
"votes" must cover exactly these risk ids: {check_ids}."""

_RISK_DECIDER_TEMPLATE = """{context}
The merged risk list (every bullet's numbers already code-verified):
{tree}

The risks below are TIED — one analyst listed each, and the check vote
went against it. You cast the deciding vote. For each risk you see the
claim and the objection; weigh both and rule:
- "valid" — the risk is real and counts toward the size multiplier.
- "invalid" — the objection is right and the risk is out.

{disputes}

{vote_rules}

Reply with JSON only:
{{"votes": {{"T2": {{"verdict": "valid", "reason": "why the risk stands", "links": []}}}}}}
"votes" must cover exactly these risk ids: {tied_ids}."""

_RISK_SUMMARY_TEMPLATE = """{context}
The voted risk list:
{tree}

Computed result (fixed rule, already decided by code — {confirmed}
confirmed risk(s) of {total} listed; 0 confirmed = full size, 1-3 =
half size, 4 or more = no position):
- size multiplier: {multiplier}x

Write the user-facing risk report. Reply with JSON only:
{{"summary": "one plain-language paragraph naming the surviving risks and explaining why the size multiplier is what it is"}}

Rules:
- The tier-2 direction stands; do not re-judge it.
- If no risks survived, say plainly that the stress test found nothing
  material.
- Use only the evidence above; do not invent facts."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RiskEngine(DebateEngine):
    """Runs the tier-3 risk vote. Never raises out of run().

    Subclasses the tier-2 vote engine for the shared machinery — the
    validated-call/retry plumbing, the citation and vote fix loops, the
    vote rounds and the majority outcomes — and swaps in risk forms,
    risk prompts, and the count → multiplier mapping.
    """

    FIX_ITEMS_MODEL = RiskFixModel
    CITATION_FIX_TEMPLATE = _RISK_CITATION_FIX_TEMPLATE
    LINK_RULES = _RISK_LINK_RULES

    def run(
        self,
        symbol: str,
        tier2: TierReport,
        dimensions: Sequence[DimensionResult],
        ownership: int = 0,
    ) -> RiskResult:
        plan = plan_dimension(tier2, ownership)
        all_dims: List[DimensionResult] = list(dimensions)
        if plan is not None:
            all_dims.append(plan)
        context = _RISK_CONTEXT_TEMPLATE.format(
            symbol=symbol,
            direction=tier2.direction.value,
            score=tier2.score,
            ownership_note=_OWNERSHIP_NOTE if ownership > 0 else "",
            evidence_block=evidence_block(all_dims, display=True),
        )
        allowed_groups = [
            d.dimension
            for d in dimensions
            if d.dimension in DIMENSIONS
            and (d.payload or d.narrative or d.citations)
        ]
        if plan is not None:
            allowed_groups.append("plan")
        ceilings = risk_ceilings(dimensions, plan)

        warnings: List[str] = []
        items: List[Dict[str, Any]] = []
        try:
            return self._risk_stages(
                context, all_dims, allowed_groups, ceilings, tier2, warnings, items
            )
        except Exception as exc:  # fail-loud as a structured result
            return RiskResult(
                items=items,
                warnings=warnings + [f"risk vote LLM call failed: {exc}"],
            )

    # -- the steps ---------------------------------------------------------

    def _risk_stages(
        self,
        context: str,
        all_dims: Sequence[DimensionResult],
        allowed_groups: List[str],
        ceilings: Dict[str, int],
        tier2: TierReport,
        warnings: List[str],
        items: List[Dict[str, Any]],
    ) -> RiskResult:
        # Step 1 — the two risk lists, in parallel (blind), each with its
        # own citation-fix loop.
        first, second = self._risk_listers(
            context, all_dims, allowed_groups, ceilings, warnings
        )
        if first is None and second is None:
            warnings.append(
                "both analyst lists invalid after retry — tier-3 risk verdict voided"
            )
            return RiskResult(items=items, warnings=warnings)
        if first is None or second is None:
            which = "first" if first is None else "second"
            warnings.append(
                f"{which} analyst list invalid after retry — proceeding with "
                "the other list only"
            )

        # Step 2 — merge. Covered pairs = listed independently by both
        # (2-0 confirmed); uncovered second-list risks join the list.
        items.extend(self._assemble_risks(context, first, second, warnings))
        for item in items:
            if item["struck"]:
                warnings.append(
                    f"analyst {item['id']}: citations unfixable after "
                    f"{MAX_FIX_ROUNDS} fix attempts — struck from the list"
                )

        # Step 3 — the check round: the second vote on single-author risks.
        live = [item for item in items if not item["struck"]]
        check_ids = [item["id"] for item in live if item["authors"] < 2]
        if check_ids:
            votes = self._vote_round(
                _RISK_CHECK_TEMPLATE.format(
                    context=context,
                    tree=_risk_tree_text(items),
                    vote_rules=self.VOTE_RULES,
                    check_ids=", ".join(check_ids),
                ),
                check_ids,
                all_dims,
                "check round",
                warnings,
            )
            if votes is None:
                warnings.append(
                    "check round invalid after retry — risks counted on "
                    "their author's vote alone"
                )
            else:
                self._attach_votes(items, votes, "checker")
        elif live:
            warnings.append(
                "every risk was listed by both analysts — check round skipped"
            )

        # Step 4 — the deciding round, only for 1-1 ties.
        tied_ids = [item["id"] for item in items if self._is_tied(item)]
        if tied_ids:
            by_id = {item["id"]: item for item in items}
            votes = self._vote_round(
                _RISK_DECIDER_TEMPLATE.format(
                    context=context,
                    tree=_risk_tree_text(items),
                    disputes=_risk_disputes_text([by_id[i] for i in tied_ids]),
                    vote_rules=self.VOTE_RULES,
                    tied_ids=", ".join(tied_ids),
                ),
                tied_ids,
                all_dims,
                "deciding round",
                warnings,
            )
            if votes is None:
                warnings.append(
                    "deciding round invalid after retry — tied risks "
                    "excluded as unresolved"
                )
            else:
                self._attach_votes(items, votes, "decider")

        # Outcomes — pure counting of the votes, then the fixed mapping.
        self._apply_outcomes(items, warnings)

        counts = {
            "initial": _count_detail(i for i in items if not i["struck"]),
            "final": _count_detail(
                i for i in items if i["final_status"] == "counted"
            ),
        }
        confirmed = counts["final"]["total"]
        total = counts["initial"]["total"]
        multiplier = multiplier_from_risk_count(confirmed)

        # Step 5 — the user-facing prose; its failure never voids anything.
        summary = self._risk_summary(
            context, items, confirmed, total, multiplier, warnings
        )

        verdict = RiskVerdict(
            stance=tier2.direction,
            size_multiplier=multiplier,
            summary=summary,
            confirmed_risks=confirmed,
            total_risks=total,
            counts=counts,
        )
        return RiskResult(items=items, verdict=verdict, warnings=warnings)

    # -- step 1: the two lists ---------------------------------------------

    def _risk_listers(
        self,
        context: str,
        all_dims: Sequence[DimensionResult],
        allowed_groups: List[str],
        ceilings: Dict[str, int],
        warnings: List[str],
    ) -> Tuple[
        Optional[Tuple[List[RiskItemModel], Dict[str, List[str]]]],
        Optional[Tuple[List[RiskItemModel], Dict[str, List[str]]]],
    ]:
        """Each entry: (all items with fixes applied, still-broken map),
        or None when the list never validated."""
        ceiling_text = ", ".join(
            f"{group}: up to {ceilings[group]}"
            for group in RISK_GROUPS
            if group in ceilings and group in allowed_groups
        )
        list_rules = _RISK_LIST_RULES.format(ceilings=ceiling_text)
        prompts = [
            template.format(
                context=context,
                list_rules=list_rules,
                link_rules=self.LINK_RULES,
                item_shape=_RISK_ITEM_SHAPE,
            )
            for template in (_RISK_LISTER1_TEMPLATE, _RISK_LISTER2_TEMPLATE)
        ]

        def parse(parsed: dict):
            model = RiskListModel.model_validate(parsed)
            check_risk_items(model.items, allowed_groups, ceilings)
            return model

        # The usage tracker is thread-local; hand it to the workers so
        # their calls still count toward the run's AI-calls number.
        tracker = active_tracker()

        def run_stage(prompt: str, stage: str):
            def job():
                model, stage_warnings = self._call_validated(prompt, parse, stage)
                if model is None:
                    return None, stage_warnings
                fixed_items, broken = self._fix_citations(
                    model.items, all_dims, stage, stage_warnings
                )
                return (fixed_items, broken), stage_warnings

            if tracker is None:
                return job()
            with tracker.activate():
                return job()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(run_stage, prompts[0], "first analyst list"),
                pool.submit(run_stage, prompts[1], "second analyst list"),
            ]
            (first, first_warnings), (second, second_warnings) = (
                futures[0].result(),
                futures[1].result(),
            )
        warnings.extend(first_warnings)
        warnings.extend(second_warnings)
        return first, second

    # -- step 2: the merge -------------------------------------------------

    def _assemble_risks(
        self,
        context: str,
        first: Optional[Tuple[List[RiskItemModel], Dict[str, List[str]]]],
        second: Optional[Tuple[List[RiskItemModel], Dict[str, List[str]]]],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        """The merged risk list: the first list's risks (authors=2 where
        the second analyst independently listed the same danger), the
        second list's uncovered risks renumbered in, and both lists'
        struck risks kept for the audit trail."""
        if first is None:
            first, second = second, None  # the surviving list leads
        first_items, first_broken = first
        first_healthy = [m for m in first_items if m.id not in first_broken]

        covered: Dict[str, bool] = {}
        extra_models: List[RiskItemModel] = []
        extra_broken: Dict[str, List[str]] = {}
        if second is not None:
            second_items, second_broken = second
            second_healthy = [m for m in second_items if m.id not in second_broken]
            if not first_healthy or not second_healthy:
                # Nothing to match against — no merge call needed; every
                # healthy second-list risk simply joins the list.
                extra_models.extend(second_healthy)
            else:
                merge = self._merge_risks(
                    context, first_healthy, second_healthy, warnings
                )
                if merge is None:
                    warnings.append("merge invalid after retry — second list dropped")
                    second_broken = {}
                else:
                    second_by_id = {m.id: m for m in second_healthy}
                    for entry in merge.match_map:
                        if entry.covered_by is not None:
                            covered[entry.covered_by] = True
                        else:
                            extra_models.append(second_by_id[entry.own_id])
            for item_id, problems in second_broken.items():
                model = next(m for m in second_items if m.id == item_id)
                extra_models.append(model)
                extra_broken[item_id] = problems

        # Renumber second-list risks to continue the first list's ids.
        next_number: Dict[str, int] = {}
        for model in first_items:
            prefix = RISK_GROUP_PREFIX[model.dimension]
            next_number[prefix] = max(
                next_number.get(prefix, 0), int(model.id[len(prefix):])
            )
        items: List[Dict[str, Any]] = []
        for model in first_items:
            items.append(
                _risk_item(
                    model,
                    first_broken.get(model.id),
                    authors=2 if covered.get(model.id) else 1,
                )
            )
        for model in extra_models:
            prefix = RISK_GROUP_PREFIX[model.dimension]
            next_number[prefix] = next_number.get(prefix, 0) + 1
            renumbered = model.model_copy(
                update={"id": f"{prefix}{next_number[prefix]}"}
            )
            items.append(
                _risk_item(renumbered, extra_broken.get(model.id), authors=1)
            )
        return items

    def _merge_risks(
        self,
        context: str,
        first_healthy: Sequence[RiskItemModel],
        second_healthy: Sequence[RiskItemModel],
        warnings: List[str],
    ) -> Optional[MergeModel]:
        first_ids = [m.id for m in first_healthy]
        second_ids = [m.id for m in second_healthy]
        prompt = _RISK_MERGE_TEMPLATE.format(
            context=context,
            first_items=_items_json(first_healthy),
            second_items=_items_json(second_healthy),
        )

        def parse(parsed: dict) -> MergeModel:
            model = MergeModel.model_validate(parsed)
            check_risk_match_map(model.match_map, second_ids, first_ids)
            return model

        model, stage_warnings = self._call_validated(prompt, parse, "merge")
        warnings.extend(stage_warnings)
        return model

    # -- step 5 ------------------------------------------------------------

    def _risk_summary(
        self,
        context: str,
        items: Sequence[Dict[str, Any]],
        confirmed: int,
        total: int,
        multiplier: float,
        warnings: List[str],
    ) -> str:
        prompt = _RISK_SUMMARY_TEMPLATE.format(
            context=context,
            tree=_risk_tree_text(items),
            confirmed=confirmed,
            total=total,
            multiplier=f"{multiplier:g}",
        )
        try:
            raw = self._summarize(prompt)
        except Exception as exc:
            warnings.append(
                f"summary LLM call failed: {exc} — computed verdict stands"
            )
            return ""
        parsed = parse_llm_json(raw)
        if parsed is None:
            warnings.append("judge summary unparseable — computed verdict stands")
            return ""
        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            warnings.append("judge gave no summary")
        return summary


# ---------------------------------------------------------------------------
# Item + count helpers
# ---------------------------------------------------------------------------


def _risk_item(
    model: RiskItemModel, problems: Optional[List[str]], authors: int
) -> Dict[str, Any]:
    """One risk bullet. ``problems`` non-empty → struck: code could not
    fix its citations, so it renders crossed out and never counts.
    ``authors`` = how many analysts listed it independently (2 =
    confirmed at birth)."""
    struck = bool(problems)
    return {
        "id": model.id,
        "dimension": model.dimension,
        "claim": _strip_citation_markers(model.claim, model.links),
        "links": [_link_detail(link) for link in model.links],
        "struck": struck,
        "problems": list(problems or []),
        "authors": authors,
        "votes": [],
        "final_status": "excluded" if struck else None,
        "exclusion_reason": "citation_failed" if struck else None,
    }


def _count_detail(items) -> Dict[str, Any]:
    """Per-group and total risk counts for one pool snapshot."""
    groups: Dict[str, int] = {}
    for item in items:
        groups[item["dimension"]] = groups.get(item["dimension"], 0) + 1
    return {"groups": groups, "total": sum(groups.values())}


# ---------------------------------------------------------------------------
# Prompt-side rendering helpers
# ---------------------------------------------------------------------------


def _risk_tree_text(items: Sequence[Dict[str, Any]]) -> str:
    """The merged risk list as indented text for the vote/summary
    prompts. Struck risks sit out and are omitted."""
    lines: List[str] = []
    for group in RISK_GROUPS:
        rows = [i for i in items if i["dimension"] == group and not i["struck"]]
        if not rows:
            continue
        lines.append(f"- {group}")
        for item in rows:
            source = (
                "listed by BOTH analysts" if item["authors"] >= 2 else "one analyst"
            )
            lines.append(f"  - [{item['id']}] ({source}) {item['claim']}")
            if item["links"]:
                lines.append(f"    links: {_links_text(item['links'])}")
            for vote in item["votes"]:
                lines.append(f"    - {vote['role']} vote: {_vote_text(vote)}")
    return "\n".join(lines) if lines else "(no risks were listed)"


def _risk_disputes_text(tied_items: Sequence[Dict[str, Any]]) -> str:
    """Claim + objection for every tied risk, for the deciding prompt."""
    lines: List[str] = []
    for item in tied_items:
        checker = next(v for v in item["votes"] if v["role"] == "checker")
        lines.append(
            f"- [{item['id']}] claim: {item['claim']}\n"
            f"  objection: {checker['reason'] or '(no reason given)'}"
        )
    return "\n".join(lines) if lines else "(none)"
