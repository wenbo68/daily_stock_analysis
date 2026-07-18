# -*- coding: utf-8 -*-
"""Tier 2: defender/attacker/judge evidence debate (v7).

v7 revision (owner spec 2026-07-18, on top of the same-day v6 — see
.claude/reviews/tier2-v5-design.md). One DEFENDER lists ALL the evidence
in the four dimension reports — bullish and bearish, no persona; one
ATTACKER independently lists its own evidence (in parallel, blind), diffs
the two lists (omissions become additions) and challenges reasoning; the
defender answers each challenge by checking the challenge itself (valid →
accept, invalid → rejection); one JUDGE rules with the final say.

v7 changes over v6:

- Citation checking belongs to CODE alone. Every link is ``{ref, value}``
  — the leaf field and the value copied EXACTLY as the report pages
  display it (``display_value``: whole numbers whole, decimals to 2
  places, billions worded). Code verifies the ref resolves, the value
  matches the report's display string, and the sentence contains that
  string. Failures go back to the same AI in up to ``MAX_FIX_ROUNDS``
  focused fix calls carrying only the broken bullets; bullets still
  broken after that are STRUCK — shown crossed out, excluded from every
  pool, never debated. The AI citation-check stages are gone.
- The debate therefore has ONE check axis (logic): the attacker files one
  check per defender item, the defender answers each challenge with one
  check, the judge issues one reason check per unattacked item and one
  binary ruling per attack.
- Sentiment links stay ``{ref: "citation:N", text: …}`` — the underlined
  words that jump to the news source.
- Scores are unchanged from v6: per dimension ``10 × bullish / total``,
  averaged across dimensions, at three pool snapshots — initial (the
  defender's surviving list), adjusted (after the defender's responses:
  conceded out, adopted additions in), final (as the judge ruled it;
  wrongly conceded items are restored, judge-valid additions count even
  if refused). Verdict on the 2-decimal final: < 4 sell, 4-6 hold, > 6
  buy. Empty final pool → 5.00, hold, warning.

6 base LLM calls across 5 sequential steps (openings parallel, each with
its own citation-fix loop; the reply call is skipped when nothing was
challenged), all temperature 0. Every stage fills a strict Pydantic form;
an invalid reply gets ONE retry with the errors shown, then:
defender/judge failures void the tier-2 verdict (tier-1 direction
stands), attacker failures degrade loudly, the summary's failure never
voids anything.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from .debate_models import (
    AttackerOpeningModel,
    AttackerReviewModel,
    CheckModel,
    CitationFixModel,
    DefenderOpeningModel,
    DefenderReplyModel,
    DIMENSION_PREFIX,
    DIMENSIONS,
    EvidenceItemModel,
    JudgeModel,
    MIN_ITEMS_PER_DIMENSION,
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
#: struck from the debate.
MAX_FIX_ROUNDS = 3

#: Stored-detail version marker — the frontend picks its renderer by this.
DETAIL_FORMAT = 7

_CITATION_REF_RE = re.compile(r"^citation:(\d+)$")


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
    #: The same formula over the defender's surviving list.
    initial_score: float
    #: …and over the pool as the defender's responses leave it.
    adjusted_score: float
    #: Per-pool audit: {initial|adjusted|final: {dimensions, bullish,
    #: bearish, total, score}}.
    pools: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DebateResult:
    #: The evidence tree, one dict per item (see _base_item for the shape).
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
                "adjusted_score": v.adjusted_score,
                "pools": v.pools,
                # Legacy keys kept so pre-v6 readers never crash.
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
    """Where a display value may appear in a claim sentence: the exact
    string, tolerating thousands separators ("1,234" for "1234") and — for
    text values — case/underscore looseness. Digit boundaries stop "205"
    from matching inside "1205" or "205.4". The frontend underliner builds
    the same pattern to highlight exactly the cited value."""
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


def _value_in_claim(value_text: str, claim: str) -> bool:
    return bool(value_pattern(value_text).search(claim))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
- Every item carries "links": one entry per report field the sentence
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
- Sentiment links use {{"ref": "citation:N", "text": the exact words of
  your sentence that rest on news source N}} and omit "value".
- Code verifies every link and sends failures back to you to fix;
  bullets that cannot be fixed are struck from the debate.
- Use only the evidence above; never invent facts or numbers."""

_CHECK_CITE_RULES = """- Citations inside checks are leaf refs like "technicals.rsi_14" or
  "citation:N"; invalid refs are stripped by code."""

_LIST_RULES = """Evidence-list rules:
- Group items by dimension: technicals, fundamentals, macro_econ, sentiment.
- Per-dimension item counts (floor-ceiling, computed from the reports):
  {ceilings}. The ceiling is room, not a quota — list every field that
  genuinely leans bullish or bearish, and skip neutral metadata (bar
  counts, dates, regions).
- If (and only if) a dimension truly has no collected data above, skip it
  and name it in "no_data_dimensions" — code verifies this.
- Each item: one atomic claim (one sentence) containing the cited names
  AND values, tagged "bullish" or "bearish". The direction tags ARE the
  score — code counts them; nobody writes a score.
- Item ids: T1, T2… for technicals, F1… for fundamentals, E1… for
  macro_econ, S1… for sentiment."""

_ITEM_SHAPE = """{{"id": "T1", "dimension": "technicals", "direction": "bullish",
  "claim": "The 14-day RSI (56.28) is above 50, showing bullish momentum.",
  "links": [{{"ref": "technicals.rsi_14", "value": "56.28"}}]}}"""

_DEFENDER_OPENING_TEMPLATE = """{context}
You are the DEFENDER analyst. You take no side: list ALL the evidence you
can find in the reports above — bullish AND bearish. You give no score;
code computes the position score from your direction tags.

{list_rules}

{link_rules}

Reply with JSON only:
{{"items": [{item_shape}],
 "no_data_dimensions": []}}"""

_ATTACKER_OPENING_TEMPLATE = """{context}
You are the ATTACKER analyst, working alone. Another analyst is building
an evidence list from these same reports; you have NOT seen it. Build your
own complete list — bullish AND bearish — so the two can be compared.
You take no position and give no score.

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

_ATTACKER_REVIEW_TEMPLATE = """{context}
You are the ATTACKER analyst. Compare the two evidence lists and check the
defender's work.

The defender's evidence list:
{defender_items}

Your own independent list, built before seeing theirs:
{own_items}

Do two jobs:

1. Match map — for EVERY item on your own list, say which defender item
   covers the same evidence ("covered_by": its id), or null if the
   defender genuinely missed it. Items you mark null are added to the
   debate automatically as your additions — never mark null just to add
   something; a bogus addition costs you with the judge.

2. Checks — for EVERY defender item, ONE check. Code has already
   verified every linked value against the report, so the numbers are
   not in question. Check the reasoning: does the sentence say something
   TRUE about those verified values ("RSI (56.28) shows the stock is
   overbought" is a false statement about a correct number), and does
   the bullish/bearish tag actually follow from the fact?
   Verdict "valid" or "invalid"; an "invalid" needs a reason and
   citations. If an item has no real flaw, mark it valid — a false
   attack costs you with the judge.

{check_cite_rules}

Reply with JSON only:
{{"match_map": [{{"own_id": "T1", "covered_by": "T2"}}, {{"own_id": "F3", "covered_by": null}}],
 "checks": {{"T1": {{"verdict": "valid", "reason": null, "citations": []}},
            "T2": {{"verdict": "invalid", "reason": "why it is flawed", "citations": ["technicals.rsi_14"]}}}}}}
"checks" must cover exactly these defender item ids: {defender_ids}."""

_ATTACKER_CHECKS_ONLY_TEMPLATE = """{context}
You are the ATTACKER analyst. Compare the two evidence lists — but your
own independent list is unavailable this run, so skip the match map (send
it empty) and only check the defender's work.

The defender's evidence list:
{defender_items}

For EVERY defender item, ONE check. Code has already verified every
linked value against the report, so the numbers are not in question.
Check the reasoning: does the sentence say something TRUE about those
verified values, and does the bullish/bearish tag actually follow from
the fact? Verdict "valid" or "invalid"; an "invalid" needs a reason and
citations. If an item has no real flaw, mark it valid — a false attack
costs you with the judge.

{check_cite_rules}

Reply with JSON only:
{{"match_map": [],
 "checks": {{"T1": {{"verdict": "valid", "reason": null, "citations": []}},
            "T2": {{"verdict": "invalid", "reason": "why it is flawed", "citations": ["technicals.rsi_14"]}}}}}}
"checks" must cover exactly these defender item ids: {defender_ids}."""

_DEFENDER_REPLY_TEMPLATE = """{context}
You are the DEFENDER analyst. The attacker has challenged your evidence.
Your original list:
{defender_items}

The challenges, each with its response key:
{challenges}

For EVERY challenge, run your own ONE check ON THE CHALLENGE ITSELF (not
on your original item): does the challenge's reasoning actually hold
against the report? If your check comes back valid, you are accepting
the challenge — conceding the attack, or adopting the added evidence. If
your check is invalid, its reason + citations ARE your rejection. You
give no score; code recounts the pool from what survives.

{check_cite_rules}

Reply with JSON only:
{{"responses": {{"T2": {{"verdict": "invalid", "reason": "why the challenge fails", "citations": ["technicals.rsi_14"]}}}}}}
"responses" must cover exactly these keys: {challenge_keys}."""

_JUDGE_TEMPLATE = """{context}
You are the JUDGE with the final say. Below is the full debate tree —
the defender's evidence, the attacker's checks and additions, and the
defender's responses. Do NOT pick a direction and do NOT score anything —
code counts the verdict from the items your rulings leave standing.

{tree}

Two ruling sets:

1. reason_checks — for every UNATTACKED item, defender-listed AND
   attacker-added, your OWN check. Code has already verified every
   linked value, so the numbers are not in question: does the sentence
   say something TRUE about them, and does the bullish/bearish tag
   follow from the fact? An attacker addition counts as genuine evidence
   only if your check passes — rule on it regardless of what the
   defender said.
2. attack_rulings — for EVERY attacked item, rule "attack_right" (the
   attack found a real flaw) or "attack_wrong" (the attack itself is
   mistaken). Read the defender's response as input, but rule on the
   attack itself.

Every ruling needs a short plain-English reason; cite evidence where it
helps.

{check_cite_rules}

Reply with JSON only:
{{"reason_checks": {{"T1": {{"verdict": "valid", "reason": null, "citations": []}}}},
 "attack_rulings": {{"T2": {{"verdict": "attack_wrong", "reason": "why", "citations": []}}}}}}
"reason_checks" must cover exactly: {check_ids}.
"attack_rulings" must cover exactly: {attack_keys}."""

_SUMMARY_TEMPLATE = """{context}
Full debate tree:
{tree}

Computed result (fixed formula, already decided by code — per dimension
the score is 10 × bullish items / total items, averaged across the
dimensions present in the pool):
- initial score {initial} (the defender's surviving list)
- adjusted score {adjusted} (after the defender's responses)
- final score {final} (only the items the judge's rulings left standing:
  {final_bullish} bullish vs {final_bearish} bearish of {final_total})
- verdict: {direction} (below 4 sell, 4-6 hold, above 6 buy)

Write the user-facing report. Reply with JSON only:
{{"summary": "one plain-language paragraph explaining why the computed verdict is what it is"}}

Rules:
- Support the computed verdict; if little evidence survived, say plainly
  that the case is weak.
- Use only the tree and evidence above; do not invent facts."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_StageParse = Callable[[dict], Any]


class DebateEngine:
    """Runs the v7 debate. Never raises out of run()."""

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

    # -- the five steps ----------------------------------------------------

    def _run_stages(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        data_dimensions: List[str],
        warnings: List[str],
        items: List[Dict[str, Any]],
    ) -> DebateResult:
        ceilings = max_items_per_dimension(dimensions)

        # Step 1 — the two openings, in parallel (the attacker's own list
        # must be built blind; it depends only on the reports). Each
        # worker runs its own citation-fix loop before returning.
        defender_opening, attacker_items = self._openings(
            context, dimensions, data_dimensions, ceilings, warnings
        )
        if defender_opening is None:
            warnings.append("defender opening invalid after retry — tier-2 verdict voided")
            return DebateResult(items=items, warnings=warnings)
        opening_items, still_broken = defender_opening
        if attacker_items is None:
            warnings.append(
                "attacker opening invalid after retry — proceeding without additions"
            )

        for model in opening_items:
            items.append(self._base_item(model, still_broken.get(model.id)))
        for item_id in still_broken:
            warnings.append(
                f"defender {item_id}: citations unfixable after "
                f"{MAX_FIX_ROUNDS} fix attempts — struck from the debate"
            )
        active = [model for model in opening_items if model.id not in still_broken]
        active_ids = [model.id for model in active]
        by_id = {item["id"]: item for item in items}

        # Step 2 — attacker compares + checks (struck bullets sit out).
        review = self._attacker_review(
            context, dimensions, active, attacker_items, active_ids, warnings
        )
        additions: List[Dict[str, Any]] = []
        if review is None:
            warnings.append(
                "attacker review invalid after retry — proceeding without "
                "attacks or additions"
            )
        else:
            for item_id in active_ids:
                by_id[item_id]["attacker_check"] = self._check_detail(
                    review.checks[item_id], dimensions, "attacker", warnings
                )
            additions = self._materialize_additions(
                review, attacker_items, items, warnings
            )
            items.extend(additions)

        # Step 3 — defender responds to every challenge. Skipped (nothing
        # to say) when nothing was challenged.
        challenge_keys = self._challenge_keys(items)
        if challenge_keys:
            reply = self._defender_reply(
                context, dimensions, active, items, challenge_keys, warnings
            )
            if reply is None:
                warnings.append(
                    "defender reply invalid after retry — tier-2 verdict voided"
                )
                return DebateResult(items=items, warnings=warnings)
            self._attach_responses(items, reply, dimensions, warnings)
        else:
            warnings.append(
                "attacker raised no challenges — defender response skipped"
            )

        # Step 4 — the judge's binary rulings, final say.
        judge = self._judge(context, dimensions, items, warnings)
        if judge is None:
            warnings.append("judge rulings invalid after retry — tier-2 verdict voided")
            return DebateResult(items=items, warnings=warnings)
        self._apply_rulings(items, judge, dimensions, warnings)

        # The three pool snapshots, one counting formula.
        pools = {
            "initial": _pool_detail(
                i for i in items if not i["added_by_attacker"] and not i["struck"]
            ),
            "adjusted": _pool_detail(i for i in items if _in_adjusted_pool(i)),
            "final": _pool_detail(i for i in items if i["final_status"] == "counted"),
        }
        initial_score = pools["initial"]["score"] if pools["initial"]["total"] else 5.0
        adjusted_score = pools["adjusted"]["score"] if pools["adjusted"]["total"] else 5.0
        if pools["final"]["total"]:
            final = pools["final"]["score"]
        else:
            final = 5.0
            warnings.append(
                "no surviving evidence to weigh — final score is neutral 5 by default"
            )
        defender_items = [i for i in items if not i["added_by_attacker"]]
        survivors = sum(1 for i in defender_items if i["final_status"] == "counted")
        if defender_items and survivors * 2 < len(defender_items):
            warnings.append(
                "most of the defender's initial evidence did not survive — "
                "the weight rests on a thin base"
            )
        direction = direction_from_final(final)

        # Step 5 — the user-facing prose; its failure never voids anything.
        summary = self._summary(
            context, items, initial_score, adjusted_score, final, pools, direction,
            warnings,
        )

        verdict = DebateVerdict(
            direction=direction,
            final_score=final,
            summary=summary,
            initial_score=initial_score,
            adjusted_score=adjusted_score,
            pools=pools,
        )
        return DebateResult(items=items, verdict=verdict, warnings=warnings)

    # -- step 1 ------------------------------------------------------------

    def _openings(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        data_dimensions: List[str],
        ceilings: Dict[str, int],
        warnings: List[str],
    ) -> Tuple[
        Optional[Tuple[List[EvidenceItemModel], Dict[str, List[str]]]],
        Optional[List[EvidenceItemModel]],
    ]:
        """(defender (items, still-broken map) | None, attacker items | None).

        The defender keeps its unfixable bullets (they render struck);
        the attacker's are dropped — a broken bullet cannot become an
        addition."""
        ceiling_text = ", ".join(
            f"{dim}: {MIN_ITEMS_PER_DIMENSION}-{ceilings[dim]}"
            for dim in DIMENSIONS
            if dim in ceilings and dim in data_dimensions
        )
        list_rules = _LIST_RULES.format(ceilings=ceiling_text)
        defender_prompt = _DEFENDER_OPENING_TEMPLATE.format(
            context=context,
            list_rules=list_rules,
            link_rules=_LINK_RULES,
            item_shape=_ITEM_SHAPE,
        )
        attacker_prompt = _ATTACKER_OPENING_TEMPLATE.format(
            context=context,
            list_rules=list_rules,
            link_rules=_LINK_RULES,
            item_shape=_ITEM_SHAPE,
        )

        def parse_opening(model_cls):
            def parse(parsed: dict):
                model = model_cls.model_validate(parsed)
                check_opening_items(model.items, data_dimensions, ceilings)
                return model

            return parse

        # The usage tracker is thread-local; hand it to the workers so
        # their calls still count toward the run's AI-calls number.
        tracker = active_tracker()

        def run_stage(prompt: str, parse: _StageParse, stage: str):
            def job():
                model, stage_warnings = self._call_validated(prompt, parse, stage)
                if model is None:
                    return None, {}, stage_warnings
                fixed_items, broken = self._fix_citations(
                    model.items, dimensions, stage, stage_warnings
                )
                return fixed_items, broken, stage_warnings

            if tracker is None:
                return job()
            with tracker.activate():
                return job()

        with ThreadPoolExecutor(max_workers=2) as pool:
            defender_future = pool.submit(
                run_stage,
                defender_prompt,
                parse_opening(DefenderOpeningModel),
                "defender opening",
            )
            attacker_future = pool.submit(
                run_stage,
                attacker_prompt,
                parse_opening(AttackerOpeningModel),
                "attacker opening",
            )
            defender_items, defender_broken, defender_warnings = defender_future.result()
            attacker_raw, attacker_broken, attacker_warnings = attacker_future.result()
        warnings.extend(defender_warnings)
        warnings.extend(attacker_warnings)

        attacker_items: Optional[List[EvidenceItemModel]] = None
        if attacker_raw is not None:
            attacker_items = [m for m in attacker_raw if m.id not in attacker_broken]
            for item_id in attacker_broken:
                warnings.append(
                    f"attacker {item_id}: citations unfixable after "
                    f"{MAX_FIX_ROUNDS} fix attempts — bullet dropped"
                )
        defender = (
            None if defender_items is None else (defender_items, defender_broken)
        )
        return defender, attacker_items

    # -- citation verification + the fix loop ------------------------------

    def _link_errors(
        self, item: EvidenceItemModel, dimensions: Sequence[DimensionResult]
    ) -> List[str]:
        """Everything code checks about one bullet's links, phrased for
        the fix prompt. Empty list → the bullet's citations are good."""
        errors: List[str] = []
        for link in item.links:
            ref = link.ref.strip()
            where = f"item {item.id} link {ref!r}"
            if _CITATION_REF_RE.match(ref):
                if not validate_evidence([ref], dimensions, leaf_only=True):
                    errors.append(f"{where}: citation number out of range")
                elif _squash(link.text or "") not in _squash(item.claim):
                    errors.append(
                        f'{where}: "text" is not found verbatim in the claim'
                    )
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
            if not _value_in_claim(expected, item.claim):
                errors.append(
                    f"{where}: the value {expected!r} must appear in the claim "
                    "sentence exactly as the report displays it"
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
            prompt = _CITATION_FIX_TEMPLATE.format(
                evidence=evidence_block(dimensions, display=True),
                link_rules=_LINK_RULES,
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
                reply = CitationFixModel.model_validate(parsed)
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

    # -- step 2 ------------------------------------------------------------

    def _attacker_review(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        active: Sequence[EvidenceItemModel],
        attacker_items: Optional[List[EvidenceItemModel]],
        active_ids: List[str],
        warnings: List[str],
    ) -> Optional[AttackerReviewModel]:
        own_ids = [item.id for item in attacker_items] if attacker_items else []
        if attacker_items is not None:
            prompt = _ATTACKER_REVIEW_TEMPLATE.format(
                context=context,
                defender_items=_items_json(active),
                own_items=_items_json(attacker_items),
                check_cite_rules=_CHECK_CITE_RULES,
                defender_ids=", ".join(active_ids),
            )
        else:
            prompt = _ATTACKER_CHECKS_ONLY_TEMPLATE.format(
                context=context,
                defender_items=_items_json(active),
                check_cite_rules=_CHECK_CITE_RULES,
                defender_ids=", ".join(active_ids),
            )

        def parse(parsed: dict) -> AttackerReviewModel:
            model = AttackerReviewModel.model_validate(parsed)
            check_exact_keys(list(model.checks), active_ids, "checks")
            check_match_map(model.match_map, own_ids, active_ids)
            return model

        model, stage_warnings = self._call_validated(prompt, parse, "attacker review")
        warnings.extend(stage_warnings)
        return model

    def _materialize_additions(
        self,
        review: AttackerReviewModel,
        attacker_items: Optional[List[EvidenceItemModel]],
        defender_items: List[Dict[str, Any]],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        """Uncovered attacker items join the tree, renumbered to continue
        the defender's ids so the tree reads as one list."""
        if attacker_items is None:
            return []
        own_by_id = {item.id: item for item in attacker_items}
        next_number: Dict[str, int] = {}
        for item in defender_items:
            prefix = DIMENSION_PREFIX[item["dimension"]]
            number = int(item["id"][len(prefix):])
            next_number[prefix] = max(next_number.get(prefix, 0), number)

        additions: List[Dict[str, Any]] = []
        for entry in review.match_map:
            if entry.covered_by is not None:
                continue
            own = own_by_id[entry.own_id]
            prefix = DIMENSION_PREFIX[own.dimension]
            next_number[prefix] = next_number.get(prefix, 0) + 1
            renumbered = own.model_copy(
                update={"id": f"{prefix}{next_number[prefix]}"}
            )
            addition = self._base_item(renumbered, None)
            addition["added_by_attacker"] = True
            additions.append(addition)
        return additions

    # -- step 3 ------------------------------------------------------------

    @staticmethod
    def _challenge_keys(items: Sequence[Dict[str, Any]]) -> List[str]:
        """Attacked items are keyed by their id, additions "add:<id>"."""
        keys: List[str] = []
        for item in items:
            if item["struck"]:
                continue
            if item["added_by_attacker"]:
                keys.append(f"add:{item['id']}")
                continue
            check = item.get("attacker_check")
            if check and check["verdict"] == "invalid":
                keys.append(item["id"])
        return keys

    def _defender_reply(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        active: Sequence[EvidenceItemModel],
        items: Sequence[Dict[str, Any]],
        challenge_keys: List[str],
        warnings: List[str],
    ) -> Optional[DefenderReplyModel]:
        prompt = _DEFENDER_REPLY_TEMPLATE.format(
            context=context,
            defender_items=_items_json(active),
            challenges=_challenges_text(items),
            check_cite_rules=_CHECK_CITE_RULES,
            challenge_keys=", ".join(challenge_keys),
        )

        def parse(parsed: dict) -> DefenderReplyModel:
            model = DefenderReplyModel.model_validate(parsed)
            check_exact_keys(list(model.responses), challenge_keys, "responses")
            return model

        model, stage_warnings = self._call_validated(prompt, parse, "defender reply")
        warnings.extend(stage_warnings)
        return model

    def _attach_responses(
        self,
        items: List[Dict[str, Any]],
        reply: DefenderReplyModel,
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> None:
        by_id = {item["id"]: item for item in items}
        for key, check in reply.responses.items():
            detail = self._check_detail(check, dimensions, "defender", warnings)
            item_id = key[len("add:"):] if key.startswith("add:") else key
            by_id[item_id]["response"] = {
                # The defender's check confirms the challenge → accepted.
                "accepted": check.verdict == "valid",
                "check": detail,
            }

    # -- step 4 ------------------------------------------------------------

    def _judge(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        items: Sequence[Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[JudgeModel]:
        attack_keys = [
            key for key in self._challenge_keys(items) if not key.startswith("add:")
        ]
        check_ids = [
            item["id"]
            for item in items
            if not item["struck"] and item["id"] not in attack_keys
        ]
        prompt = _JUDGE_TEMPLATE.format(
            context=context,
            tree=_tree_text(items),
            check_cite_rules=_CHECK_CITE_RULES,
            check_ids=", ".join(check_ids) or "(none)",
            attack_keys=", ".join(attack_keys) or "(none)",
        )

        def parse(parsed: dict) -> JudgeModel:
            model = JudgeModel.model_validate(parsed)
            check_exact_keys(list(model.reason_checks), check_ids, "reason_checks")
            check_exact_keys(list(model.attack_rulings), attack_keys, "attack_rulings")
            return model

        model, stage_warnings = self._call_validated(prompt, parse, "judge rulings")
        warnings.extend(stage_warnings)
        return model

    def _apply_rulings(
        self,
        items: List[Dict[str, Any]],
        judge: JudgeModel,
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> None:
        """Final-pool membership: the judge's rulings (struck bullets are
        already out). The defender's stance is irrelevant here — wrongly
        conceded items are restored, judge-approved additions count even
        if refused."""
        for item in items:
            if item["struck"]:
                continue  # excluded by code before the debate began
            attacked = item["id"] in judge.attack_rulings
            if attacked:
                ruling = judge.attack_rulings[item["id"]]
                item["judge"] = {
                    "kind": "attack_ruling",
                    "verdict": ruling.verdict,
                    "reason": ruling.reason,
                    "citations": self._clean_refs(
                        ruling.citations, dimensions, "judge", warnings
                    ),
                }
                counted = ruling.verdict == "attack_wrong"
                if counted:
                    response = item.get("response")
                    if response and response["accepted"]:
                        warnings.append(
                            "defender accepted an attack the judge ruled wrong "
                            f"({item['id']}) — evidence restored to the final pool"
                        )
                item["final_status"] = "counted" if counted else "excluded"
                item["exclusion_reason"] = None if counted else "attack_upheld"
            else:
                check = judge.reason_checks[item["id"]]
                item["judge"] = {
                    "kind": "reason_check",
                    "verdict": check.verdict,
                    "reason": (check.reason or "").strip() or None,
                    "citations": self._clean_refs(
                        check.citations, dimensions, "judge", warnings
                    ),
                }
                counted = check.verdict == "valid"
                item["final_status"] = "counted" if counted else "excluded"
                item["exclusion_reason"] = None if counted else "judge_invalid"
            if (
                counted
                and item["added_by_attacker"]
                and item.get("response") is not None
                and not item["response"]["accepted"]
            ):
                warnings.append(
                    "defender rejected added evidence the judge ruled valid "
                    f"({item['id']}) — included in the final pool"
                )

    # -- step 5 ------------------------------------------------------------

    def _summary(
        self,
        context: str,
        items: Sequence[Dict[str, Any]],
        initial: float,
        adjusted: float,
        final: float,
        pools: Dict[str, Any],
        direction: Direction,
        warnings: List[str],
    ) -> str:
        prompt = _SUMMARY_TEMPLATE.format(
            context=context,
            tree=_tree_text(items),
            initial=f"{initial:.2f}",
            adjusted=f"{adjusted:.2f}",
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
        model: EvidenceItemModel, problems: Optional[List[str]]
    ) -> Dict[str, Any]:
        """One tree item. ``problems`` non-empty → the bullet is struck:
        code could not fix its citations, so it renders crossed out and
        never enters a pool."""
        struck = bool(problems)
        return {
            "id": model.id,
            "dimension": model.dimension,
            "direction": model.direction,
            "claim": model.claim.strip(),
            "links": [_link_detail(link) for link in model.links],
            "struck": struck,
            "problems": list(problems or []),
            "added_by_attacker": False,
            "attacker_check": None,
            "response": None,
            "judge": None,
            "final_status": "excluded" if struck else None,
            "exclusion_reason": "citation_failed" if struck else None,
        }

    def _check_detail(
        self,
        check: CheckModel,
        dimensions: Sequence[DimensionResult],
        owner: str,
        warnings: List[str],
    ) -> Dict[str, Any]:
        return {
            "verdict": check.verdict,
            "reason": (check.reason or "").strip() or None,
            "citations": self._clean_refs(check.citations, dimensions, owner, warnings),
        }

    @staticmethod
    def _clean_refs(
        refs: Sequence[str],
        dimensions: Sequence[DimensionResult],
        owner: str,
        warnings: List[str],
    ) -> List[str]:
        cleaned = [str(ref).strip() for ref in refs if str(ref).strip()]
        valid = validate_evidence(cleaned, dimensions, leaf_only=True)
        if len(valid) < len(cleaned):
            warnings.append(
                f"{owner} cited evidence that does not resolve to a single "
                "value — invalid refs dropped"
            )
        return valid


# ---------------------------------------------------------------------------
# Pool counting
# ---------------------------------------------------------------------------


def _in_adjusted_pool(item: Dict[str, Any]) -> bool:
    """The pool as the defender's responses leave it: surviving original
    items minus conceded ones, plus additions it accepted."""
    if item["struck"]:
        return False
    response = item.get("response")
    if item["added_by_attacker"]:
        return bool(response and response["accepted"])
    return not (response and response["accepted"])  # accepted attack → conceded


def _pool_detail(items) -> Dict[str, Any]:
    """Per-dimension 10 × bullish/total, averaged across dimensions."""
    per_dimension: Dict[str, Dict[str, Any]] = {}
    for item in items:
        stats = per_dimension.setdefault(
            item["dimension"], {"bullish": 0, "bearish": 0, "total": 0, "score": None}
        )
        stats["total"] += 1
        stats["bullish" if item["direction"] == "bullish" else "bearish"] += 1
    scores: List[float] = []
    bullish = bearish = total = 0
    for dimension in DIMENSIONS:
        stats = per_dimension.get(dimension)
        if not stats:
            continue
        stats["score"] = round(10 * stats["bullish"] / stats["total"], 2)
        scores.append(10 * stats["bullish"] / stats["total"])
        bullish += stats["bullish"]
        bearish += stats["bearish"]
        total += stats["total"]
    return {
        "dimensions": per_dimension,
        "bullish": bullish,
        "bearish": bearish,
        "total": total,
        "score": round(sum(scores) / len(scores), 2) if scores else None,
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
    value; sentiment links keep the words to underline."""
    ref = link.ref.strip()
    if _CITATION_REF_RE.match(ref):
        return {"ref": ref, "value": None, "text": (link.text or "").strip()}
    return {"ref": ref, "value": _link_value_text(link.value), "text": None}


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
        elif link.get("text"):
            parts.append(f"{link['text']} → {link['ref']}")
        else:
            parts.append(link["ref"])
    return "; ".join(parts)


def _check_text(check: Dict[str, Any]) -> str:
    if check["verdict"] == "valid":
        return "valid"
    text = f"INVALID — {check['reason']}"
    if check["citations"]:
        text += f" [cites: {', '.join(check['citations'])}]"
    return text


def _response_text(response: Dict[str, Any]) -> str:
    verdict = "ACCEPTED" if response["accepted"] else "REJECTED"
    return (
        f"defender response ({verdict}): check on the challenge: "
        f"{_check_text(response['check'])}"
    )


def _tree_text(items: Sequence[Dict[str, Any]]) -> str:
    """The debate tree as indented text for the judge/summary prompts.
    Struck bullets sit out of the debate and are omitted."""
    lines: List[str] = []
    for dimension in DIMENSIONS:
        group = [
            i for i in items if i["dimension"] == dimension and not i["struck"]
        ]
        if not group:
            continue
        lines.append(f"- {dimension}")
        for item in group:
            source = "added by the ATTACKER" if item["added_by_attacker"] else "defender"
            lines.append(
                f"  - [{item['id']}] ({item['direction']}, {source}) {item['claim']}"
            )
            if item["links"]:
                lines.append(f"    links: {_links_text(item['links'])}")
            if item["added_by_attacker"]:
                if item["response"] is not None:
                    lines.append(f"    - {_response_text(item['response'])}")
                continue
            check = item.get("attacker_check")
            if not check:
                continue
            lines.append(
                f"    - attacker check ({item['id']}): {_check_text(check)}"
            )
            if item["response"] is not None:
                lines.append(f"      - {_response_text(item['response'])}")
    return "\n".join(lines) if lines else "(no evidence was listed)"


def _challenges_text(items: Sequence[Dict[str, Any]]) -> str:
    """The challenge list for the defender-reply prompt, keys included."""
    lines: List[str] = []
    for item in items:
        if item["struck"]:
            continue
        if item["added_by_attacker"]:
            links = f" [{_links_text(item['links'])}]" if item["links"] else ""
            lines.append(
                f'- key "add:{item["id"]}" — the attacker says you MISSED this '
                f"evidence: ({item['direction']}) {item['claim']}{links}"
            )
            continue
        check = item.get("attacker_check")
        if check and check["verdict"] == "invalid":
            lines.append(
                f'- key "{item["id"]}" — attack on your item '
                f"{item['id']}: {_check_text(check)}"
            )
    return "\n".join(lines) if lines else "(none)"
