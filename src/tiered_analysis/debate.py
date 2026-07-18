# -*- coding: utf-8 -*-
"""Tier 2: the evidence vote (v8).

v8 revision (owner spec 2026-07-18, replacing the v5-v7
defender/attacker/judge tree — see .claude/reviews/tier2-v5-design.md).
No roles. Two ANALYSTS independently list ALL the evidence in the four
dimension reports — bullish and bearish, blind to each other; a MERGE
call matches the two lists (same evidence + same direction = the same
bullet; an opposite-direction clash is a dispute and stays unmatched).
Membership is a majority vote with at most three votes per bullet:

- A bullet's author is automatically its first valid vote, so a bullet
  BOTH analysts listed independently starts 2-0 — confirmed, no checking.
- A CHECK round casts the second vote on every single-author bullet:
  2-0 confirmed or 1-1 tied.
- A DECIDING round breaks the ties: 2-1 in or 1-2 out. Three votes,
  so a tie is impossible.

Citations are code's job alone (carried over from v7): links are
``{ref, value}`` with the value copied exactly as the report pages
display it (``display_value``); sentiment links are bare
``{ref: citation:N}``, rendered by the UI as trailing [N] hyperlinks.
Code verifies every link — including the links inside vote reasons —
and sends failures back to the same AI in up to ``MAX_FIX_ROUNDS``
focused fix calls; bullets that cannot be fixed are STRUCK (crossed
out, never voted on, in no pool) and unfixable votes are discarded.

NO AI authors any number. The position score is computed by code from
the direction tags: ``10 × bullish / total`` over the whole pool (flat
counting — v9 owner spec; per-dimension counts are stored for the
section headers). Two snapshots: initial (the merged list, stored for
the audit trail only) and final (the bullets the votes left standing —
the displayed score). Verdict on the 2-decimal final: < 4 sell, 4-6
hold, > 6 buy. Empty final pool → 5.00, hold, warning.

5-6 base LLM calls (two lists parallel with their fix loops → merge →
check round → deciding round only when there are ties → summary), all
temperature 0. Every stage fills a strict Pydantic form; an invalid
reply gets ONE retry with the errors shown, then: both lists failing
voids the tier-2 verdict (tier-1 direction stands); one list failing
proceeds with the other; a failed merge drops the second list; a failed
check round counts bullets on their author's vote alone; a failed
deciding round excludes the tied bullets as unresolved; the summary's
failure never voids anything.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from .debate_models import (
    CitationFixModel,
    DIMENSION_PREFIX,
    DIMENSIONS,
    EvidenceItemModel,
    ListModel,
    MergeModel,
    MIN_ITEMS_PER_DIMENSION,
    VoteFixModel,
    VoteModel,
    VoteRoundModel,
    check_exact_keys,
    check_match_map,
    check_opening_items,
)
from .llm_support import (
    active_tracker,
    deterministic_summarizer,
    display_value,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult
from .schema import Direction, TierReport

#: Verdict bands on the 2-decimal final score (owner spec).
SELL_BELOW = 4.0
HOLD_MAX = 6.0

#: How many focused fix calls a broken citation gets before its bullet is
#: struck (or its vote discarded).
MAX_FIX_ROUNDS = 3

#: Stored-detail version marker — the frontend picks its renderer by this.
#: 9 = the flat-count score (10 × bullish / total over the whole pool);
#: stored format-8 runs share the same shapes with a per-dimension mean.
DETAIL_FORMAT = 9

_CITATION_REF_RE = re.compile(r"^citation:(\d+)$")

#: A vote reason that states a report-style number (a decimal or a
#: percentage) must cite it — bare integers like "above 50" are usually
#: thresholds, not report fields, so they are not forced.
_NUMERIC_REASON_RE = re.compile(r"\d+\.\d+|\d+(?:\.\d+)?\s?%")


def direction_from_final(final: float) -> Direction:
    """The fixed mapping from the 0-10 final score to a verdict."""
    if final < SELL_BELOW:
        return Direction.SELL
    if final <= HOLD_MAX:
        return Direction.HOLD
    return Direction.BUY


@dataclass(frozen=True)
class AnchoredReason:
    """A claim tied to evidence refs — still used by the tier-3 risk stage."""

    claim: str
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DebateVerdict:
    direction: Direction
    #: The final pool's score (per-dimension 10×bullish/total, averaged).
    final_score: float
    summary: str
    #: The same formula over the merged list before any voting.
    initial_score: float
    #: Per-pool audit: {initial|final: {dimensions, bullish, bearish,
    #: total, score}}.
    pools: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DebateResult:
    #: The evidence list, one dict per bullet (see _base_item for the shape).
    items: List[Dict[str, Any]] = field(default_factory=list)
    verdict: Optional[DebateVerdict] = None
    warnings: List[str] = field(default_factory=list)

    def to_detail(self) -> Dict[str, Any]:
        """JSON-ready audit trail for storage and the debate-tree UI."""
        verdict: Optional[Dict[str, Any]] = None
        if self.verdict is not None:
            v = self.verdict
            verdict = {
                "direction": v.direction.value,
                "final_score": v.final_score,
                # Legacy header field: the nearest whole number.
                "final_score_rounded": int(v.final_score + 0.5),
                "summary": v.summary,
                "initial_score": v.initial_score,
                "pools": v.pools,
                # Legacy keys kept so pre-v8 readers never crash.
                "adjusted_score": None,
                "confidence": None,
                "reasons_for": [],
                "reasons_against": [],
                "would_change_mind": None,
                "bull_summary": None,
                "bear_summary": None,
                "scoring": None,
                "weight": None,
            }
        return {
            "format": DETAIL_FORMAT,
            # Legacy key: pre-v5 readers iterate turns; v5+ has none.
            "turns": [],
            "items": [dict(item) for item in self.items],
            "verdict": verdict,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Payload helpers (leaf counting, value lookup, display-string matching)
# ---------------------------------------------------------------------------


def _leaf_count(node: Any) -> int:
    if isinstance(node, dict):
        return sum(_leaf_count(value) for value in node.values())
    return 1


def max_items_per_dimension(dimensions: Sequence[DimensionResult]) -> Dict[str, int]:
    """The dynamic ceilings: leaf-field count per numeric dimension,
    verified sources × 2 for sentiment, never below the floor."""
    ceilings: Dict[str, int] = {}
    for dim in dimensions:
        if dim.dimension not in DIMENSIONS:
            continue
        if dim.dimension == "sentiment":
            ceiling = 2 * len(dim.citations or [])
        else:
            ceiling = _leaf_count(dim.payload) if dim.payload else 0
        ceilings[dim.dimension] = max(ceiling, MIN_ITEMS_PER_DIMENSION)
    return ceilings


def _payload_value(ref: str, dimensions: Sequence[DimensionResult]) -> Tuple[bool, Any]:
    """(resolves-to-a-leaf, value) for a ``dimension.key[.subkey…]`` ref."""
    parts = ref.split(".")
    if len(parts) < 2:
        return False, None
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
        if node is not None and not isinstance(node, dict):
            return True, node
    return False, None


def _link_value_text(value: Any) -> str:
    """The link's claimed value as a display string (numbers a model sends
    as JSON numbers are normalized through the same formatter)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value).strip()
    return display_value(value)


def _norm_text_value(text: str) -> str:
    """Loose comparison form for TEXT values only ("Golden_Cross" ↔
    "golden cross") — numbers never come through here."""
    return re.sub(r"[_\s]+", " ", text).strip().lower()


def _values_equal(claimed: str, expected: str) -> bool:
    if claimed == expected:
        return True
    if any(char.isdigit() for char in expected):
        return False  # numeric display strings must be copied exactly
    return _norm_text_value(claimed) == _norm_text_value(expected)


def value_pattern(value_text: str) -> "re.Pattern[str]":
    """Where a display value may appear in a sentence: the exact string,
    tolerating thousands separators ("1,234" for "1234") and — for text
    values — case/underscore looseness. Digit boundaries stop "205" from
    matching inside "1205" or "205.4". The frontend underliner builds the
    same pattern to highlight exactly the cited value."""
    parts: List[str] = []
    for index, char in enumerate(value_text):
        parts.append("[_ ]" if char == "_" else re.escape(char))
        if (
            char.isdigit()
            and index + 1 < len(value_text)
            and value_text[index + 1].isdigit()
        ):
            parts.append(",?")
    pattern = "".join(parts)
    if value_text[:1].isdigit() or (
        value_text[:1] == "-" and value_text[1:2].isdigit()
    ):
        pattern = r"(?<![\d.])" + pattern
    if value_text[-1:].isdigit():
        pattern += r"(?!\.?\d)"
    flags = 0 if any(char.isdigit() for char in value_text) else re.IGNORECASE
    return re.compile(pattern, flags)


def _value_in_text(value_text: str, sentence: str) -> bool:
    return bool(value_pattern(value_text).search(sentence))


def _strip_citation_markers(text: str, links: Sequence[Any]) -> str:
    """Remove literal "[N]" tokens for sources the links already carry —
    the UI appends its own [N] hyperlinks, so a model-written marker
    would show twice."""
    for link in links:
        match = _CITATION_REF_RE.match(link.ref.strip() if hasattr(link, "ref") else "")
        if match:
            text = re.sub(r"\s*\[\s*" + match.group(1) + r"\s*\]", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Prompts — one marker phrase per stage so tests can route replies.
# ---------------------------------------------------------------------------

_CONTEXT_TEMPLATE = """Stock under debate: {symbol}
Tier-1 verdict so far: direction={direction}, score={score}, confidence={confidence}
Tier-1 levels: entry={entry}, backup={secondary_entry}, stop={stop_loss}, target={take_profit}

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence_block}
"""

_LINK_RULES = """Link rules (all checked mechanically by code):
- Every bullet carries "links": one entry per report field the sentence
  uses, each {{"ref": the leaf field, "value": the value copied EXACTLY
  as the report above displays it}}.
- The claim sentence must contain each linked value verbatim — "The
  14-day RSI (56.28) is above 50", never "RSI is high". Copy the
  displayed string exactly: if the report shows 56.28, write 56.28,
  never 56.3 or 56.280. Write values as plain numbers in the sentence —
  do not wrap them in quotation marks.
- A "ref" must point at ONE exact value, like "technicals.rsi_14" —
  grouping paths ("technicals.macd" when it holds sub-values) are
  rejected; cite the leaf ("technicals.macd.hist").
- Sentiment bullets cite news sources with {{"ref": "citation:N"}} and
  no "value" — the source numbers are shown as [N] links after the
  bullet.
- Code verifies every link and sends failures back to you to fix;
  bullets that cannot be fixed are struck from the list.
- Use only the evidence above; never invent facts or numbers."""

_VOTE_RULES = """Vote rules (checked mechanically by code):
- Every vote: "verdict" is "valid" or "invalid", plus a short plain
  "reason" — REQUIRED either way; a vote without a reason is rejected.
- If your reason states a number from the reports, cite it with a link
  {{"ref": the leaf field, "value": the value copied EXACTLY as the
  report displays it}} and write that exact value in your reason.
  Reasons resting on a news source use {{"ref": "citation:N"}}.
- The reason is a plain sentence for a human reader — never paste refs,
  link JSON, or "citation:N" text into it; refs belong in "links" only.
- Code verifies every link and sends failures back to you to fix; votes
  that cannot be fixed are discarded."""

_LIST_RULES = """Evidence-list rules:
- Group bullets by dimension: technicals, fundamentals, macro_econ, sentiment.
- Per-dimension bullet counts (floor-ceiling, computed from the reports):
  {ceilings}. The ceiling is room, not a quota — list every field that
  genuinely leans bullish or bearish, and skip neutral metadata (bar
  counts, dates, regions).
- If (and only if) a dimension truly has no collected data above, skip it
  and name it in "no_data_dimensions" — code verifies this.
- Each bullet: one atomic claim (one sentence) containing the cited names
  AND values, tagged "bullish" or "bearish". The direction tags ARE the
  score — code counts them; nobody writes a score.
- Bullet ids: T1, T2… for technicals, F1… for fundamentals, E1… for
  macro_econ, S1… for sentiment."""

_ITEM_SHAPE = """{{"id": "T1", "dimension": "technicals", "direction": "bullish",
  "claim": "The 14-day RSI (56.28) is above 50, showing bullish momentum.",
  "links": [{{"ref": "technicals.rsi_14", "value": "56.28"}}]}}"""

_LISTER1_TEMPLATE = """{context}
You are the FIRST analyst. Another analyst is building the same list
separately; neither of you sees the other's work. Take no side: list ALL
the evidence you can find in the reports above — bullish AND bearish.
Walk each report from top to bottom, field by field, so nothing is
skipped. You give no score; code computes the position score from your
direction tags.

{list_rules}

{link_rules}

Reply with JSON only:
{{"items": [{item_shape}],
 "no_data_dimensions": []}}"""

_LISTER2_TEMPLATE = """{context}
You are the SECOND analyst. Another analyst is building the same list
separately; you have NOT seen it. Take no side: list ALL the evidence
you can find in the reports above — bullish AND bearish. Work theme by
theme — momentum, trend, profitability, valuation, balance sheet, macro
pressures, news — then double-check you covered every report field. You
give no score; code computes the position score from your direction
tags.

{list_rules}

{link_rules}

Reply with JSON only:
{{"items": [{item_shape}],
 "no_data_dimensions": []}}"""

_CITATION_FIX_TEMPLATE = """Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

Some of your evidence bullets failed the code's citation check. Fix each
bullet listed below: point the ref at the right leaf field, copy the
value exactly as the report above displays it, and make sure the claim
sentence contains that exact value. Keep each bullet's "id" and
"dimension" unchanged; you may rewrite the claim, the links, and the
direction tag.

{link_rules}

The bullets to fix:
{bullets}

The code's error list:
{errors}

Reply with JSON only:
{{"items": [ ...every bullet above, corrected, same ids... ]}}"""

_VOTE_FIX_TEMPLATE = """Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence}

Some of your votes failed the code's citation check. Fix each vote
listed below: cite every number your reason states, copying the value
exactly as the report above displays it. Keep the same keys; you may
rewrite the reason and links, and reconsider the verdict with the
correct numbers in hand.

{vote_rules}

The votes to fix:
{votes}

The code's error list:
{errors}

Reply with JSON only:
{{"votes": {{ ...every vote above, corrected, same keys... }}}}"""

_MERGE_TEMPLATE = """{context}
Match the two evidence lists below. Two analysts worked independently;
your only job is the match map — code assembles the merged list.

The first analyst's list:
{first_items}

The second analyst's list:
{second_items}

For EVERY bullet on the second list, say which first-list bullet covers
the SAME evidence with the SAME direction ("covered_by": its id), or
null if there is none. Rules:
- "Covers" means the same underlying fact, even if worded differently.
- A bullet citing the same fact with the OPPOSITE direction is a real
  dispute — leave it unmatched (null) so both versions face the votes.
- Never stretch a match; an unmatched bullet simply joins the list.

Reply with JSON only:
{{"match_map": [{{"own_id": "T1", "covered_by": "T2"}}, {{"own_id": "F3", "covered_by": null}}]}}"""

_CHECK_TEMPLATE = """{context}
The merged evidence list (every bullet's numbers already code-verified):
{tree}

Each bullet named below was listed by only ONE of the two analysts, so
it has one vote so far (its author's). You cast the second vote on each:
- "valid" — the sentence says something TRUE about the verified values
  AND the bullish/bearish tag actually follows from the fact.
- "invalid" — the statement is wrong about the values, or the tag does
  not follow. Say why.
Vote on the bullet in front of you, not on the stock.

{vote_rules}

Reply with JSON only:
{{"votes": {{"T2": {{"verdict": "invalid", "reason": "why it is flawed", "links": [{{"ref": "technicals.close", "value": "100"}}]}}}}}}
"votes" must cover exactly these bullet ids: {check_ids}."""

_DECIDER_TEMPLATE = """{context}
The merged evidence list (every bullet's numbers already code-verified):
{tree}

The bullets below are TIED — one analyst listed each, and the check
vote went against it. You cast the deciding vote. For each bullet you
see the claim and the objection; weigh both and rule:
- "valid" — the bullet stands and counts in the score.
- "invalid" — the objection is right and the bullet is out.

{disputes}

{vote_rules}

Reply with JSON only:
{{"votes": {{"T2": {{"verdict": "valid", "reason": "why the bullet stands", "links": []}}}}}}
"votes" must cover exactly these bullet ids: {tied_ids}."""

_SUMMARY_TEMPLATE = """{context}
The voted evidence list:
{tree}

Computed result (fixed formula, already decided by code — the score is
10 × bullish bullets / total bullets over the pool the votes left
standing):
- final score {final} ({final_bullish} bullish vs {final_bearish}
  bearish of {final_total})
- verdict: {direction} (below 4 sell, 4-6 hold, above 6 buy)

Write the user-facing report. Reply with JSON only:
{{"summary": "one plain-language paragraph explaining why the computed verdict is what it is"}}

Rules:
- Support the computed verdict; if little evidence survived, say plainly
  that the case is weak.
- Use only the evidence above; do not invent facts."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_StageParse = Callable[[dict], Any]


class DebateEngine:
    """Runs the v8 evidence vote. Never raises out of run()."""

    # The fix loops are shared with the tier-3 risk engine (a subclass);
    # these hooks let it swap in its own item form and prompt wording
    # while the loop mechanics stay identical.
    FIX_ITEMS_MODEL: Any = CitationFixModel
    CITATION_FIX_TEMPLATE = _CITATION_FIX_TEMPLATE
    LINK_RULES = _LINK_RULES
    VOTE_FIX_TEMPLATE = _VOTE_FIX_TEMPLATE
    VOTE_RULES = _VOTE_RULES

    def __init__(self, summarizer: Optional[Callable[[str], str]] = None) -> None:
        # Temperature 0 by default: the same evidence rules the same way.
        self._summarize = summarizer or deterministic_summarizer

    # -- public entry ------------------------------------------------------

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
            # Display-formatted numbers: the model must cite what the
            # report pages show, so it only ever sees those strings.
            evidence_block=evidence_block(dimensions, display=True),
        )
        data_dimensions = [
            d.dimension
            for d in dimensions
            if d.dimension in DIMENSIONS
            and (d.payload or d.narrative or d.citations)
        ]
        warnings: List[str] = []
        items: List[Dict[str, Any]] = []
        try:
            return self._run_stages(
                context, dimensions, data_dimensions, warnings, items
            )
        except Exception as exc:  # fail-loud as a structured result
            return DebateResult(
                items=items, warnings=warnings + [f"debate LLM call failed: {exc}"]
            )

    # -- the steps ---------------------------------------------------------

    def _run_stages(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        data_dimensions: List[str],
        warnings: List[str],
        items: List[Dict[str, Any]],
    ) -> DebateResult:
        ceilings = max_items_per_dimension(dimensions)

        # Step 1 — the two analyst lists, in parallel (blind), each with
        # its own citation-fix loop.
        first, second = self._listers(
            context, dimensions, data_dimensions, ceilings, warnings
        )
        if first is None and second is None:
            warnings.append(
                "both analyst lists invalid after retry — tier-2 verdict voided"
            )
            return DebateResult(items=items, warnings=warnings)
        if first is None or second is None:
            which = "first" if first is None else "second"
            warnings.append(
                f"{which} analyst list invalid after retry — proceeding with "
                "the other list only"
            )

        # Step 2 — merge. Covered pairs = listed independently by both
        # (2-0 confirmed); uncovered second-list bullets join the list.
        items.extend(self._assemble(context, first, second, warnings))
        for item in items:
            if item["struck"]:
                warnings.append(
                    f"analyst {item['id']}: citations unfixable after "
                    f"{MAX_FIX_ROUNDS} fix attempts — struck from the list"
                )

        # Step 3 — the check round: the second vote on single-author
        # bullets. Bullets both analysts listed are already 2-0.
        check_ids = [
            item["id"] for item in items if not item["struck"] and item["authors"] < 2
        ]
        if check_ids:
            votes = self._vote_round(
                _CHECK_TEMPLATE.format(
                    context=context,
                    tree=_tree_text(items),
                    vote_rules=_VOTE_RULES,
                    check_ids=", ".join(check_ids),
                ),
                check_ids,
                dimensions,
                "check round",
                warnings,
            )
            if votes is None:
                warnings.append(
                    "check round invalid after retry — bullets counted on "
                    "their author's vote alone"
                )
            else:
                self._attach_votes(items, votes, "checker")
        else:
            warnings.append(
                "every bullet was listed by both analysts — check round skipped"
            )

        # Step 4 — the deciding round, only for 1-1 ties.
        tied_ids = [item["id"] for item in items if self._is_tied(item)]
        if tied_ids:
            by_id = {item["id"]: item for item in items}
            votes = self._vote_round(
                _DECIDER_TEMPLATE.format(
                    context=context,
                    tree=_tree_text(items),
                    disputes=_disputes_text([by_id[i] for i in tied_ids]),
                    vote_rules=_VOTE_RULES,
                    tied_ids=", ".join(tied_ids),
                ),
                tied_ids,
                dimensions,
                "deciding round",
                warnings,
            )
            if votes is None:
                warnings.append(
                    "deciding round invalid after retry — tied bullets "
                    "excluded as unresolved"
                )
            else:
                self._attach_votes(items, votes, "decider")

        # Outcomes — pure counting of the votes.
        self._apply_outcomes(items, warnings)

        pools = {
            "initial": _pool_detail(i for i in items if not i["struck"]),
            "final": _pool_detail(i for i in items if i["final_status"] == "counted"),
        }
        initial_score = pools["initial"]["score"] if pools["initial"]["total"] else 5.0
        if pools["final"]["total"]:
            final = pools["final"]["score"]
        else:
            final = 5.0
            warnings.append(
                "no surviving evidence to weigh — final score is neutral 5 by default"
            )
        merged = [i for i in items if not i["struck"]]
        survivors = sum(1 for i in merged if i["final_status"] == "counted")
        if merged and survivors * 2 < len(merged):
            warnings.append(
                "most of the merged evidence did not survive the votes — "
                "the final score rests on a thin base"
            )
        direction = direction_from_final(final)

        # Step 5 — the user-facing prose; its failure never voids anything.
        summary = self._summary(context, items, final, pools, direction, warnings)

        verdict = DebateVerdict(
            direction=direction,
            final_score=final,
            summary=summary,
            initial_score=initial_score,
            pools=pools,
        )
        return DebateResult(items=items, verdict=verdict, warnings=warnings)

    # -- step 1: the two lists ---------------------------------------------

    def _listers(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        data_dimensions: List[str],
        ceilings: Dict[str, int],
        warnings: List[str],
    ) -> Tuple[
        Optional[Tuple[List[EvidenceItemModel], Dict[str, List[str]]]],
        Optional[Tuple[List[EvidenceItemModel], Dict[str, List[str]]]],
    ]:
        """Each entry: (all items with fixes applied, still-broken map),
        or None when the list never validated."""
        ceiling_text = ", ".join(
            f"{dim}: {MIN_ITEMS_PER_DIMENSION}-{ceilings[dim]}"
            for dim in DIMENSIONS
            if dim in ceilings and dim in data_dimensions
        )
        list_rules = _LIST_RULES.format(ceilings=ceiling_text)
        prompts = [
            template.format(
                context=context,
                list_rules=list_rules,
                link_rules=_LINK_RULES,
                item_shape=_ITEM_SHAPE,
            )
            for template in (_LISTER1_TEMPLATE, _LISTER2_TEMPLATE)
        ]

        def parse(parsed: dict):
            model = ListModel.model_validate(parsed)
            check_opening_items(model.items, data_dimensions, ceilings)
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
                    model.items, dimensions, stage, stage_warnings
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

    def _assemble(
        self,
        context: str,
        first: Optional[Tuple[List[EvidenceItemModel], Dict[str, List[str]]]],
        second: Optional[Tuple[List[EvidenceItemModel], Dict[str, List[str]]]],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        """The merged bullet list: the first list's bullets (authors=2
        where the second analyst independently listed the same evidence),
        the second list's uncovered bullets renumbered in, and both
        lists' struck bullets kept for the audit trail."""
        if first is None:
            first, second = second, None  # the surviving list leads
        first_items, first_broken = first
        first_healthy = [m for m in first_items if m.id not in first_broken]

        covered: Dict[str, bool] = {}
        extra_models: List[EvidenceItemModel] = []
        extra_broken: Dict[str, List[str]] = {}
        if second is not None:
            second_items, second_broken = second
            second_healthy = [m for m in second_items if m.id not in second_broken]
            merge = self._merge(context, first_healthy, second_healthy, warnings)
            if merge is None:
                warnings.append("merge invalid after retry — second list dropped")
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

        # Renumber second-list bullets to continue the first list's ids.
        next_number: Dict[str, int] = {}
        for model in first_items:
            prefix = DIMENSION_PREFIX[model.dimension]
            next_number[prefix] = max(
                next_number.get(prefix, 0), int(model.id[len(prefix):])
            )
        items: List[Dict[str, Any]] = []
        for model in first_items:
            items.append(
                self._base_item(
                    model,
                    first_broken.get(model.id),
                    authors=2 if covered.get(model.id) else 1,
                )
            )
        for model in extra_models:
            prefix = DIMENSION_PREFIX[model.dimension]
            next_number[prefix] = next_number.get(prefix, 0) + 1
            renumbered = model.model_copy(update={"id": f"{prefix}{next_number[prefix]}"})
            items.append(
                self._base_item(renumbered, extra_broken.get(model.id), authors=1)
            )
        return items

    def _merge(
        self,
        context: str,
        first_healthy: Sequence[EvidenceItemModel],
        second_healthy: Sequence[EvidenceItemModel],
        warnings: List[str],
    ) -> Optional[MergeModel]:
        first_by_id = {m.id: m for m in first_healthy}
        second_by_id = {m.id: m for m in second_healthy}
        prompt = _MERGE_TEMPLATE.format(
            context=context,
            first_items=_items_json(first_healthy),
            second_items=_items_json(second_healthy),
        )

        def parse(parsed: dict) -> MergeModel:
            model = MergeModel.model_validate(parsed)
            check_match_map(
                model.match_map, list(second_by_id), first_by_id, second_by_id
            )
            return model

        model, stage_warnings = self._call_validated(prompt, parse, "merge")
        warnings.extend(stage_warnings)
        return model

    # -- citation verification + the fix loops -----------------------------

    def _text_link_errors(
        self,
        links: Sequence[Any],
        sentence: str,
        where_prefix: str,
        dimensions: Sequence[DimensionResult],
    ) -> List[str]:
        """Everything code checks about one sentence's links, phrased for
        the fix prompt. Empty list → the citations are good."""
        errors: List[str] = []
        for link in links:
            ref = link.ref.strip()
            where = f"{where_prefix} link {ref!r}"
            if _CITATION_REF_RE.match(ref):
                if not validate_evidence([ref], dimensions, leaf_only=True):
                    errors.append(f"{where}: citation number out of range")
                continue
            resolves, actual = _payload_value(ref, dimensions)
            if not resolves:
                errors.append(f"{where}: does not resolve to a single report value")
                continue
            expected = display_value(actual)
            claimed = _link_value_text(link.value)
            if not _values_equal(claimed, expected):
                errors.append(
                    f"{where}: claimed value {claimed!r} must be copied exactly "
                    f"as the report displays it: {expected!r}"
                )
                continue
            if not _value_in_text(expected, sentence):
                errors.append(
                    f"{where}: the value {expected!r} must appear in the "
                    "sentence exactly as the report displays it"
                )
        return errors

    def _link_errors(
        self, item: EvidenceItemModel, dimensions: Sequence[DimensionResult]
    ) -> List[str]:
        return self._text_link_errors(
            item.links, item.claim, f"item {item.id}", dimensions
        )

    def _vote_errors(
        self, key: str, vote: VoteModel, dimensions: Sequence[DimensionResult]
    ) -> List[str]:
        reason = vote.reason or ""
        errors = self._text_link_errors(
            vote.links, reason, f"vote {key}", dimensions
        )
        if _NUMERIC_REASON_RE.search(reason) and not vote.links:
            errors.append(
                f"vote {key}: the reason states a number — cite it with a link"
            )
        return errors

    def _fix_citations(
        self,
        items: Sequence[EvidenceItemModel],
        dimensions: Sequence[DimensionResult],
        stage: str,
        warnings: List[str],
    ) -> Tuple[List[EvidenceItemModel], Dict[str, List[str]]]:
        """Run the code citation check, send broken bullets back to the
        same AI (only the broken ones), splice fixes in, repeat up to
        MAX_FIX_ROUNDS. Returns (items with fixes applied, still-broken
        id → errors). Successful fixes leave no trace — the UI shows only
        the end state."""
        fixed = list(items)
        index_by_id = {item.id: index for index, item in enumerate(fixed)}
        broken: Dict[str, List[str]] = {}
        for item in fixed:
            errors = self._link_errors(item, dimensions)
            if errors:
                broken[item.id] = errors
        rounds = 0
        while broken and rounds < MAX_FIX_ROUNDS:
            rounds += 1
            prompt = self.CITATION_FIX_TEMPLATE.format(
                evidence=evidence_block(dimensions, display=True),
                link_rules=self.LINK_RULES,
                bullets=_items_json([fixed[index_by_id[i]] for i in broken]),
                errors="\n".join(
                    f"- {item_id}: {'; '.join(errors)}"
                    for item_id, errors in broken.items()
                ),
            )
            raw = self._summarize(prompt)
            parsed = parse_llm_json(raw)
            if parsed is None:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            try:
                reply = self.FIX_ITEMS_MODEL.model_validate(parsed)
            except ValidationError:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            for candidate in reply.items:
                if candidate.id not in broken:
                    continue  # untouched bullets must not be churned
                if candidate.dimension != fixed[index_by_id[candidate.id]].dimension:
                    continue  # id and dimension are frozen
                fixed[index_by_id[candidate.id]] = candidate
                errors = self._link_errors(candidate, dimensions)
                if errors:
                    broken[candidate.id] = errors
                else:
                    del broken[candidate.id]
        return fixed, broken

    def _fix_votes(
        self,
        votes: Dict[str, VoteModel],
        dimensions: Sequence[DimensionResult],
        stage: str,
        warnings: List[str],
    ) -> Dict[str, VoteModel]:
        """The same fix loop for vote reasons. Votes still broken after
        the rounds are DISCARDED (with a warning) — an objection that
        cannot back its numbers carries no weight."""
        fixed = dict(votes)
        broken: Dict[str, List[str]] = {}
        for key, vote in fixed.items():
            errors = self._vote_errors(key, vote, dimensions)
            if errors:
                broken[key] = errors
        rounds = 0
        while broken and rounds < MAX_FIX_ROUNDS:
            rounds += 1
            prompt = self.VOTE_FIX_TEMPLATE.format(
                evidence=evidence_block(dimensions, display=True),
                vote_rules=self.VOTE_RULES,
                votes=json.dumps(
                    {key: fixed[key].model_dump(exclude_none=True) for key in broken},
                    ensure_ascii=False,
                    indent=1,
                ),
                errors="\n".join(
                    f"- {key}: {'; '.join(errors)}" for key, errors in broken.items()
                ),
            )
            raw = self._summarize(prompt)
            parsed = parse_llm_json(raw)
            if parsed is None:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            try:
                reply = VoteFixModel.model_validate(parsed)
            except ValidationError:
                warnings.append(f"{stage} citation-fix reply invalid — fix round lost")
                continue
            for key, candidate in reply.votes.items():
                if key not in broken:
                    continue
                fixed[key] = candidate
                errors = self._vote_errors(key, candidate, dimensions)
                if errors:
                    broken[key] = errors
                else:
                    del broken[key]
        for key in broken:
            warnings.append(
                f"vote on {key} discarded — citations unfixable after "
                f"{MAX_FIX_ROUNDS} fix attempts"
            )
            del fixed[key]
        return fixed

    # -- steps 3-4: the vote rounds ----------------------------------------

    def _vote_round(
        self,
        prompt: str,
        required_ids: List[str],
        dimensions: Sequence[DimensionResult],
        stage: str,
        warnings: List[str],
    ) -> Optional[Dict[str, VoteModel]]:
        def parse(parsed: dict) -> VoteRoundModel:
            model = VoteRoundModel.model_validate(parsed)
            check_exact_keys(list(model.votes), required_ids, "votes")
            return model

        model, stage_warnings = self._call_validated(prompt, parse, stage)
        warnings.extend(stage_warnings)
        if model is None:
            return None
        return self._fix_votes(model.votes, dimensions, stage, warnings)

    @staticmethod
    def _attach_votes(
        items: List[Dict[str, Any]], votes: Dict[str, VoteModel], role: str
    ) -> None:
        by_id = {item["id"]: item for item in items}
        for key, vote in votes.items():
            reason = _strip_citation_markers(vote.reason or "", vote.links)
            by_id[key]["votes"].append(
                {
                    "role": role,
                    "verdict": vote.verdict,
                    "reason": reason or None,
                    "links": [
                        _link_detail(link) for link in vote.links
                    ],
                }
            )

    @staticmethod
    def _vote_by_role(item: Dict[str, Any], role: str) -> Optional[Dict[str, Any]]:
        return next((v for v in item["votes"] if v["role"] == role), None)

    def _is_tied(self, item: Dict[str, Any]) -> bool:
        """1-1: the author's implicit valid vote vs an invalid check vote."""
        if item["struck"] or item["authors"] >= 2:
            return False
        checker = self._vote_by_role(item, "checker")
        return checker is not None and checker["verdict"] == "invalid"

    def _apply_outcomes(
        self, items: List[Dict[str, Any]], warnings: List[str]
    ) -> None:
        """Majority of votes decides; the author is always a valid vote."""
        for item in items:
            if item["struck"]:
                continue  # excluded by code before any voting
            if item["authors"] >= 2:
                item["final_status"] = "counted"  # 2-0 at birth
                continue
            checker = self._vote_by_role(item, "checker")
            if checker is None or checker["verdict"] == "valid":
                # No second vote cast (degraded/discarded) → the author's
                # vote stands unopposed; a valid check vote → 2-0.
                item["final_status"] = "counted"
                continue
            decider = self._vote_by_role(item, "decider")
            if decider is None:
                item["final_status"] = "excluded"
                item["exclusion_reason"] = "unresolved"
                warnings.append(
                    f"no deciding vote for {item['id']} — excluded as unresolved"
                )
            elif decider["verdict"] == "valid":
                item["final_status"] = "counted"  # 2-1
            else:
                item["final_status"] = "excluded"  # 1-2
                item["exclusion_reason"] = "outvoted"

    # -- step 5 ------------------------------------------------------------

    def _summary(
        self,
        context: str,
        items: Sequence[Dict[str, Any]],
        final: float,
        pools: Dict[str, Any],
        direction: Direction,
        warnings: List[str],
    ) -> str:
        prompt = _SUMMARY_TEMPLATE.format(
            context=context,
            tree=_tree_text(items),
            final=f"{final:.2f}",
            final_bullish=pools["final"]["bullish"],
            final_bearish=pools["final"]["bearish"],
            final_total=pools["final"]["total"],
            direction=direction.value,
        )
        try:
            raw = self._summarize(prompt)
        except Exception as exc:
            warnings.append(f"summary LLM call failed: {exc} — computed verdict stands")
            return ""
        parsed = parse_llm_json(raw)
        if parsed is None:
            warnings.append("judge summary unparseable — computed verdict stands")
            return ""
        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            warnings.append("judge gave no summary")
        return summary

    # -- shared plumbing ---------------------------------------------------

    def _call_validated(
        self, prompt: str, parse: _StageParse, stage: str
    ) -> Tuple[Optional[Any], List[str]]:
        """One LLM call against a Pydantic form, with ONE retry that shows
        the model its validation errors. Returns (model|None, warnings)."""
        error = None
        raw = self._summarize(prompt)
        parsed = parse_llm_json(raw)
        if parsed is None:
            error = "the reply was not a JSON object"
        else:
            try:
                return parse(parsed), []
            except (ValidationError, ValueError) as exc:
                error = _validation_text(exc)

        retry_prompt = (
            f"{prompt}\n\nYour previous reply was invalid: {error}\n"
            "Reply again, following the JSON shape exactly. JSON only."
        )
        raw = self._summarize(retry_prompt)
        parsed = parse_llm_json(raw)
        if parsed is None:
            return None, [f"{stage} was not JSON even after a retry"]
        try:
            return (
                parse(parsed),
                [f"{stage} needed a retry — first reply was invalid"],
            )
        except (ValidationError, ValueError) as exc:
            return None, [f"{stage} invalid after retry: {_validation_text(exc)}"]

    @staticmethod
    def _base_item(
        model: EvidenceItemModel, problems: Optional[List[str]], authors: int
    ) -> Dict[str, Any]:
        """One list bullet. ``problems`` non-empty → the bullet is struck:
        code could not fix its citations, so it renders crossed out and
        never enters a pool. ``authors`` = how many analysts listed it
        independently (2 = confirmed at birth)."""
        struck = bool(problems)
        return {
            "id": model.id,
            "dimension": model.dimension,
            "direction": model.direction,
            "claim": _strip_citation_markers(model.claim, model.links),
            "links": [_link_detail(link) for link in model.links],
            "struck": struck,
            "problems": list(problems or []),
            "authors": authors,
            "votes": [],
            "final_status": "excluded" if struck else None,
            "exclusion_reason": "citation_failed" if struck else None,
        }


# ---------------------------------------------------------------------------
# Pool counting
# ---------------------------------------------------------------------------


def _pool_detail(items) -> Dict[str, Any]:
    """Flat counting: 10 × bullish / total over the whole pool. The
    per-dimension counts feed the section headers (`Technicals: ↑3 ↓4`)."""
    per_dimension: Dict[str, Dict[str, Any]] = {}
    for item in items:
        stats = per_dimension.setdefault(
            item["dimension"], {"bullish": 0, "bearish": 0, "total": 0}
        )
        stats["total"] += 1
        stats["bullish" if item["direction"] == "bullish" else "bearish"] += 1
    bullish = bearish = total = 0
    for dimension in DIMENSIONS:
        stats = per_dimension.get(dimension)
        if not stats:
            continue
        bullish += stats["bullish"]
        bearish += stats["bearish"]
        total += stats["total"]
    return {
        "dimensions": per_dimension,
        "bullish": bullish,
        "bearish": bearish,
        "total": total,
        "score": round(10 * bullish / total, 2) if total else None,
    }


# ---------------------------------------------------------------------------
# Prompt-side rendering helpers
# ---------------------------------------------------------------------------


def _validation_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return "; ".join(parts) or str(exc)
    return str(exc)


def _link_detail(link) -> Dict[str, Any]:
    """The stored link shape: payload links keep their display-string
    value; sentiment links are bare refs (the UI renders [N])."""
    ref = link.ref.strip()
    if _CITATION_REF_RE.match(ref):
        return {"ref": ref, "value": None}
    return {"ref": ref, "value": _link_value_text(link.value)}


def _items_json(items: Sequence[EvidenceItemModel]) -> str:
    return json.dumps(
        [item.model_dump(exclude_none=True) for item in items],
        ensure_ascii=False,
        indent=1,
    )


def _links_text(links: Sequence[Dict[str, Any]]) -> str:
    parts = []
    for link in links:
        if link.get("value") is not None:
            parts.append(f"{link['ref']} = {link['value']}")
        else:
            parts.append(link["ref"])
    return "; ".join(parts)


def _vote_text(vote: Dict[str, Any]) -> str:
    text = vote["verdict"]
    if vote["reason"]:
        text += f" — {vote['reason']}"
    if vote["links"]:
        text += f" [{_links_text(vote['links'])}]"
    return text


def _tree_text(items: Sequence[Dict[str, Any]]) -> str:
    """The merged list as indented text for the vote/summary prompts.
    Struck bullets sit out and are omitted."""
    lines: List[str] = []
    for dimension in DIMENSIONS:
        group = [
            i for i in items if i["dimension"] == dimension and not i["struck"]
        ]
        if not group:
            continue
        lines.append(f"- {dimension}")
        for item in group:
            source = (
                "listed by BOTH analysts" if item["authors"] >= 2 else "one analyst"
            )
            lines.append(
                f"  - [{item['id']}] ({item['direction']}, {source}) {item['claim']}"
            )
            if item["links"]:
                lines.append(f"    links: {_links_text(item['links'])}")
            for vote in item["votes"]:
                lines.append(f"    - {vote['role']} vote: {_vote_text(vote)}")
    return "\n".join(lines) if lines else "(no evidence was listed)"


def _disputes_text(tied_items: Sequence[Dict[str, Any]]) -> str:
    """Claim + objection for every tied bullet, for the deciding prompt."""
    lines: List[str] = []
    for item in tied_items:
        checker = next(v for v in item["votes"] if v["role"] == "checker")
        lines.append(
            f"- [{item['id']}] claim ({item['direction']}): {item['claim']}\n"
            f"  objection: {checker['reason'] or '(no reason given)'}"
        )
    return "\n".join(lines) if lines else "(none)"
