# -*- coding: utf-8 -*-
"""Tier 2: defender/attacker/judge evidence debate (v6).

v6 revision (owner spec 2026-07-18, on top of the 2026-07-17 v5 design —
see .claude/reviews/tier2-v5-design.md). One DEFENDER lists ALL the
evidence in the four dimension reports — bullish and bearish, no persona;
one ATTACKER independently lists its own evidence (in parallel, blind),
diffs the two lists (omissions become additions) and checks every item on
two axes (citation, logic); the defender answers each challenge by
checking the challenge itself (both valid → accept, either invalid →
rejection); one JUDGE rules with the final say — its own citation+logic
check pair on EVERY item plus a binary ruling per attack.

v6 changes:

- Per-dimension item ceilings are dynamic: the number of leaf fields in
  that dimension's report (sentiment: verified sources × 2), floor 2 —
  room for the whole report, not a quota.
- Evidence claims carry inline LINKS ``{text, ref, value}``: the exact
  words in the sentence, the leaf field they cite, and the claimed value.
  Code verifies all three mechanically; a value that does not match the
  report auto-fails the item's citation check — nobody can overrule
  arithmetic.
- NO AI authors any number. The position score is computed by code from
  the direction tags: per dimension ``10 × bullish / total``, averaged
  across dimensions, at three snapshots of the evidence pool —
  initial (the defender's raw list), adjusted (after the defender's
  responses: conceded out, accepted additions in), final (as the judge
  ruled it: only judge-valid items count; wrongly conceded items are
  restored, judge-approved additions count even if the defender refused
  them). The v5 weight formula is gone — pool filtering does its job.
- Verdict on the 2-decimal final: < 4 sell, 4-6 hold, > 6 buy.
  Empty final pool → 5.00, hold, warning.

6 LLM calls across 5 sequential steps (openings parallel; the reply call
is skipped when nothing was challenged), all temperature 0. Every stage
fills a strict Pydantic form; an invalid reply gets ONE retry with the
errors shown, then: defender/judge failures void the tier-2 verdict
(tier-1 direction stands), attacker failures degrade loudly, the
summary's failure never voids anything.
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
    DefenderOpeningModel,
    DefenderReplyModel,
    DIMENSION_PREFIX,
    DIMENSIONS,
    EvidenceItemModel,
    ItemChecksModel,
    JudgeModel,
    MIN_ITEMS_PER_DIMENSION,
    check_exact_keys,
    check_match_map,
    check_opening_items,
)
from .llm_support import (
    active_tracker,
    deterministic_summarizer,
    evidence_block,
    parse_llm_json,
    validate_evidence,
)
from .providers.base import DimensionResult
from .schema import Direction, TierReport

#: Verdict bands on the 2-decimal final score (owner spec).
SELL_BELOW = 4.0
HOLD_MAX = 6.0

#: The two check axes every reviewer applies.
AXES = ("citation", "logic")

#: Stored-detail version marker — the frontend picks its renderer by this.
DETAIL_FORMAT = 6

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
    #: The same formula over the defender's raw list.
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
# Payload helpers (leaf counting, value lookup, value matching)
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


def _decimals(number: float) -> int:
    if number == int(number):
        return 0  # "71" claims integer precision even though repr says 71.0
    text = repr(float(number))
    return len(text.split(".")[1]) if "." in text and "e" not in text else 0


def _values_match(claimed: Any, actual: Any) -> bool:
    """The claimed value equals the report's, allowing honest rounding."""
    try:
        claimed_f, actual_f = float(claimed), float(actual)
    except (TypeError, ValueError):
        return str(claimed).strip().lower() == str(actual).strip().lower()
    # Half a unit at the claimed precision: 401.1 matches 401.095.
    tolerance = 0.5 * 10 ** (-_decimals(claimed_f))
    return abs(claimed_f - actual_f) <= tolerance + 1e-9


def _value_renderings(value: Any) -> List[str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return [str(value).strip()]
    texts = [f"{number:g}"]
    if number == int(number):
        texts.append(str(int(number)))
    for digits in (1, 2, 3, 4):
        texts.append(f"{number:.{digits}f}")
    return texts


def _value_in_text(value: Any, claim: str) -> bool:
    haystack = claim.replace(",", "")
    return any(text and text in haystack for text in _value_renderings(value))


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
- Every item carries "links": one entry per piece of evidence the sentence
  uses, each {{"text": the exact words in your sentence, "ref": the leaf
  field, "value": the value copied from the report}}.
- "text" must appear word-for-word inside your claim sentence.
- The claim sentence must state the actual VALUE from the report —
  "The 14-day RSI (56.28) is above 50", never "RSI is high". A value that
  does not match the report automatically fails the item's citation
  check; nobody can overrule that.
- A "ref" must point at ONE exact value, like "technicals.rsi_14" —
  grouping paths ("technicals.macd" when it holds sub-values) are
  rejected; cite the leaf ("technicals.macd.hist").
- Sentiment links use "ref": "citation:N" (news source N above) and omit
  "value".
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
  "links": [{{"text": "14-day RSI", "ref": "technicals.rsi_14", "value": 56.28}}]}}"""

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

2. Checks — for EVERY defender item, two checks. Code has already
   verified that every number in the claims matches the report
   (mismatches are failed automatically), so:
   - citation_check: does the sentence say something TRUE about those
     verified values? ("RSI (56.28) shows the stock is overbought" is a
     false statement about a correct number.)
   - logic_check: does the bullish/bearish tag actually follow from the
     fact?
   Verdict "valid" or "invalid"; an "invalid" needs a reason and
   citations. If an item has no real flaw, mark both checks valid — a
   false attack costs you with the judge.

{check_cite_rules}

Reply with JSON only:
{{"match_map": [{{"own_id": "T1", "covered_by": "T2"}}, {{"own_id": "F3", "covered_by": null}}],
 "checks": {{"T1": {{"citation_check": {{"verdict": "valid", "reason": null, "citations": []}},
                   "logic_check": {{"verdict": "invalid", "reason": "why it is flawed", "citations": ["technicals.rsi_14"]}}}}}}}}
"checks" must cover exactly these defender item ids: {defender_ids}."""

_ATTACKER_CHECKS_ONLY_TEMPLATE = """{context}
You are the ATTACKER analyst. Compare the two evidence lists — but your
own independent list is unavailable this run, so skip the match map (send
it empty) and only check the defender's work.

The defender's evidence list:
{defender_items}

For EVERY defender item, two checks. Code has already verified that every
number in the claims matches the report, so:
- citation_check: does the sentence say something TRUE about those
  verified values?
- logic_check: does the bullish/bearish tag actually follow from the fact?
Verdict "valid" or "invalid"; an "invalid" needs a reason and citations.
If an item has no real flaw, mark both checks valid — a false attack
costs you with the judge.

{check_cite_rules}

Reply with JSON only:
{{"match_map": [],
 "checks": {{"T1": {{"citation_check": {{"verdict": "valid", "reason": null, "citations": []}},
                   "logic_check": {{"verdict": "invalid", "reason": "why it is flawed", "citations": ["technicals.rsi_14"]}}}}}}}}
"checks" must cover exactly these defender item ids: {defender_ids}."""

_DEFENDER_REPLY_TEMPLATE = """{context}
You are the DEFENDER analyst. The attacker has challenged your evidence.
Your original list:
{defender_items}

The challenges, each with its response key:
{challenges}

For EVERY challenge, run your own two checks ON THE CHALLENGE ITSELF
(not on your original item):
- citation_check: do the challenge's citations really say what it claims?
- logic_check: does the challenge's reasoning actually hold?
If BOTH your checks come back valid, you are accepting the challenge —
conceding the attack, or adopting the added evidence. If EITHER check is
invalid, that check's reason + citations ARE your rejection. You give no
score; code recounts the pool from what survives.

{check_cite_rules}

Reply with JSON only:
{{"responses": {{"T2:logic": {{"citation_check": {{"verdict": "valid", "reason": null, "citations": []}},
                            "logic_check": {{"verdict": "invalid", "reason": "why the challenge fails", "citations": ["technicals.rsi_14"]}}}}}}}}
"responses" must cover exactly these keys: {challenge_keys}."""

_JUDGE_TEMPLATE = """{context}
You are the JUDGE with the final say. Below is the full debate tree —
the defender's evidence, the attacker's checks and additions, and the
defender's responses. Do NOT pick a direction and do NOT score anything —
code counts the verdict from the items your rulings leave standing.

{tree}

Two ruling sets:

1. reason_checks — for EVERY item, defender-listed AND attacker-added,
   your OWN independent pair of checks. Code has already verified the
   numbers, so:
   - citation_check: does the sentence say something TRUE about the
     verified values?
   - logic_check: does the bullish/bearish tag follow from the fact?
   An attacker addition counts as genuine evidence only if both your
   checks pass — rule on it regardless of what the defender said.
2. attack_rulings — for EVERY attack, rule "attack_right" (the attack
   found a real flaw) or "attack_wrong" (the attack itself is mistaken).
   Read the defender's response as input, but rule on the attack itself.

Every ruling needs a short plain-English reason; cite evidence where it
helps.

{check_cite_rules}

Reply with JSON only:
{{"reason_checks": {{"T1": {{"citation_check": {{"verdict": "valid", "reason": null, "citations": []}},
                          "logic_check": {{"verdict": "valid", "reason": null, "citations": []}}}}}},
 "attack_rulings": {{"T2:logic": {{"verdict": "attack_wrong", "reason": "why", "citations": []}}}}}}
"reason_checks" must cover exactly: {item_ids}.
"attack_rulings" must cover exactly: {attack_keys}."""

_SUMMARY_TEMPLATE = """{context}
Full debate tree:
{tree}

Computed result (fixed formula, already decided by code — per dimension
the score is 10 × bullish items / total items, averaged across the
dimensions present in the pool):
- initial score {initial} (the defender's raw list)
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

_StageParse = Callable[[dict, bool], Any]


class DebateEngine:
    """Runs the v6 debate. Never raises out of run()."""

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
            evidence_block=evidence_block(dimensions),
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
        # must be built blind; it depends only on the reports).
        opening, attacker_opening = self._openings(
            context, dimensions, data_dimensions, ceilings, warnings
        )
        if opening is None:
            warnings.append("defender opening invalid after retry — tier-2 verdict voided")
            return DebateResult(items=items, warnings=warnings)
        if attacker_opening is None:
            warnings.append(
                "attacker opening invalid after retry — proceeding without additions"
            )

        for model in opening.items:
            items.append(self._base_item(model, dimensions, "defender", warnings))
        defender_ids = [item["id"] for item in items]
        by_id = {item["id"]: item for item in items}

        # Step 2 — attacker compares + checks.
        review = self._attacker_review(
            context, dimensions, opening, attacker_opening, defender_ids, warnings
        )
        additions: List[Dict[str, Any]] = []
        if review is None:
            warnings.append(
                "attacker review invalid after retry — proceeding without "
                "attacks or additions"
            )
        else:
            for item_id in defender_ids:
                by_id[item_id]["attacker_checks"] = self._checks_detail(
                    review.checks[item_id], dimensions, "attacker", warnings
                )
            additions = self._materialize_additions(
                review, attacker_opening, items, dimensions, warnings
            )
            items.extend(additions)

        # Step 3 — defender responds to every challenge. Skipped (nothing
        # to say) when nothing was challenged.
        challenge_keys = self._challenge_keys(items)
        if challenge_keys:
            reply = self._defender_reply(
                context, dimensions, opening, items, challenge_keys, warnings
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
            "initial": _pool_detail(i for i in items if not i["added_by_attacker"]),
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
    ) -> Tuple[Optional[DefenderOpeningModel], Optional[AttackerOpeningModel]]:
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
            def parse(parsed: dict, strict: bool):
                model = model_cls.model_validate(parsed)
                check_opening_items(model.items, data_dimensions, ceilings)
                if strict:
                    # First attempt: every link problem — including value
                    # mismatches — is shown back for one correction pass.
                    errors: List[str] = []
                    for item in model.items:
                        errors.extend(self._link_errors(item, dimensions))
                    if errors:
                        raise ValueError("; ".join(errors))
                return model

            return parse

        # The usage tracker is thread-local; hand it to the workers so
        # their calls still count toward the run's AI-calls number.
        tracker = active_tracker()

        def run_stage(job: Tuple[str, _StageParse, str]):
            prompt, parse, stage = job
            if tracker is None:
                return self._call_validated(prompt, parse, stage)
            with tracker.activate():
                return self._call_validated(prompt, parse, stage)

        with ThreadPoolExecutor(max_workers=2) as pool:
            defender_future = pool.submit(
                run_stage,
                (defender_prompt, parse_opening(DefenderOpeningModel), "defender opening"),
            )
            attacker_future = pool.submit(
                run_stage,
                (attacker_prompt, parse_opening(AttackerOpeningModel), "attacker opening"),
            )
            defender_model, defender_warnings = defender_future.result()
            attacker_model, attacker_warnings = attacker_future.result()
        warnings.extend(defender_warnings)
        warnings.extend(attacker_warnings)
        return defender_model, attacker_model

    # -- link verification -------------------------------------------------

    def _link_errors(
        self, item: EvidenceItemModel, dimensions: Sequence[DimensionResult]
    ) -> List[str]:
        """Structural + value problems, phrased for the retry prompt."""
        errors: List[str] = []
        claim = _squash(item.claim)
        for link in item.links:
            where = f"item {item.id} link {link.ref!r}"
            if _squash(link.text) not in claim:
                errors.append(f'{where}: "text" is not found verbatim in the claim')
            citation = _CITATION_REF_RE.match(link.ref.strip())
            if citation:
                if not validate_evidence([link.ref], dimensions, leaf_only=True):
                    errors.append(f"{where}: citation number out of range")
                continue
            resolves, actual = _payload_value(link.ref, dimensions)
            if not resolves:
                errors.append(
                    f"{where}: does not resolve to a single report value"
                )
                continue
            if link.value is None:
                errors.append(f"{where}: payload links must carry the value")
                continue
            if not _values_match(link.value, actual):
                errors.append(
                    f"{where}: claimed value {link.value!r} does not match the "
                    f"report's {actual!r}"
                )
            if not _value_in_text(link.value, item.claim):
                errors.append(
                    f"{where}: the value {link.value!r} must appear in the "
                    "claim sentence itself"
                )
        return errors

    def _verified_links(
        self,
        item: EvidenceItemModel,
        dimensions: Sequence[DimensionResult],
        owner: str,
        warnings: List[str],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """(surviving links, value problems). Structurally broken links are
        dropped with a note; value mismatches keep the link but fail the
        item's citation check mechanically — code overrules everyone."""
        links: List[Dict[str, Any]] = []
        problems: List[str] = []
        claim = _squash(item.claim)
        for link in item.links:
            if _squash(link.text) not in claim:
                warnings.append(
                    f"{owner} {item.id}: link text {link.text!r} not found in "
                    "the claim — link dropped"
                )
                continue
            ref = link.ref.strip()
            if _CITATION_REF_RE.match(ref):
                if not validate_evidence([ref], dimensions, leaf_only=True):
                    warnings.append(
                        f"{owner} {item.id}: citation {ref!r} out of range — "
                        "link dropped"
                    )
                    continue
                links.append({"text": link.text, "ref": ref, "value": None})
                continue
            resolves, actual = _payload_value(ref, dimensions)
            if not resolves:
                warnings.append(
                    f"{owner} {item.id}: link {ref!r} does not resolve to a "
                    "single report value — link dropped"
                )
                continue
            entry = {"text": link.text, "ref": ref, "value": link.value}
            if link.value is None or not _values_match(link.value, actual):
                problems.append(
                    f"claimed {link.value!r} for {ref}, the report says {actual!r}"
                )
                entry["mismatch"] = True
            elif not _value_in_text(link.value, item.claim):
                problems.append(f"value {link.value!r} missing from the sentence")
                entry["mismatch"] = True
            links.append(entry)
        if not links:
            problems.append("no verifiable links survived")
        return links, problems

    # -- step 2 ------------------------------------------------------------

    def _attacker_review(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        opening: DefenderOpeningModel,
        attacker_opening: Optional[AttackerOpeningModel],
        defender_ids: List[str],
        warnings: List[str],
    ) -> Optional[AttackerReviewModel]:
        own_ids = (
            [item.id for item in attacker_opening.items] if attacker_opening else []
        )
        if attacker_opening is not None:
            prompt = _ATTACKER_REVIEW_TEMPLATE.format(
                context=context,
                defender_items=_items_json(opening.items),
                own_items=_items_json(attacker_opening.items),
                check_cite_rules=_CHECK_CITE_RULES,
                defender_ids=", ".join(defender_ids),
            )
        else:
            prompt = _ATTACKER_CHECKS_ONLY_TEMPLATE.format(
                context=context,
                defender_items=_items_json(opening.items),
                check_cite_rules=_CHECK_CITE_RULES,
                defender_ids=", ".join(defender_ids),
            )

        def parse(parsed: dict, strict: bool) -> AttackerReviewModel:
            model = AttackerReviewModel.model_validate(parsed)
            check_exact_keys(list(model.checks), defender_ids, "checks")
            check_match_map(model.match_map, own_ids, defender_ids)
            return model

        model, stage_warnings = self._call_validated(prompt, parse, "attacker review")
        warnings.extend(stage_warnings)
        return model

    def _materialize_additions(
        self,
        review: AttackerReviewModel,
        attacker_opening: Optional[AttackerOpeningModel],
        defender_items: List[Dict[str, Any]],
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        """Uncovered attacker items join the tree, renumbered to continue
        the defender's ids so the tree reads as one list."""
        if attacker_opening is None:
            return []
        own_by_id = {item.id: item for item in attacker_opening.items}
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
            addition = self._base_item(renumbered, dimensions, "attacker", warnings)
            addition["added_by_attacker"] = True
            additions.append(addition)
        return additions

    # -- step 3 ------------------------------------------------------------

    @staticmethod
    def _challenge_keys(items: Sequence[Dict[str, Any]]) -> List[str]:
        """Attacks are keyed "<item id>:<axis>", additions "add:<id>"."""
        keys: List[str] = []
        for item in items:
            if item["added_by_attacker"]:
                keys.append(f"add:{item['id']}")
                continue
            checks = item.get("attacker_checks")
            if not checks:
                continue
            for axis in AXES:
                if checks[axis]["verdict"] == "invalid":
                    keys.append(f"{item['id']}:{axis}")
        return keys

    def _defender_reply(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        opening: DefenderOpeningModel,
        items: Sequence[Dict[str, Any]],
        challenge_keys: List[str],
        warnings: List[str],
    ) -> Optional[DefenderReplyModel]:
        prompt = _DEFENDER_REPLY_TEMPLATE.format(
            context=context,
            defender_items=_items_json(opening.items),
            challenges=_challenges_text(items),
            check_cite_rules=_CHECK_CITE_RULES,
            challenge_keys=", ".join(challenge_keys),
        )

        def parse(parsed: dict, strict: bool) -> DefenderReplyModel:
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
        for key, checks in reply.responses.items():
            detail = self._response_detail(checks, dimensions, warnings)
            if key.startswith("add:"):
                by_id[key[len("add:"):]]["response"] = detail
            else:
                item_id, axis = key.split(":", 1)
                by_id[item_id]["responses"][axis] = detail

    # -- step 4 ------------------------------------------------------------

    def _judge(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        items: Sequence[Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[JudgeModel]:
        item_ids = [i["id"] for i in items]
        attack_keys = [
            key for key in self._challenge_keys(items) if not key.startswith("add:")
        ]
        prompt = _JUDGE_TEMPLATE.format(
            context=context,
            tree=_tree_text(items),
            check_cite_rules=_CHECK_CITE_RULES,
            item_ids=", ".join(item_ids) or "(none)",
            attack_keys=", ".join(attack_keys) or "(none)",
        )

        def parse(parsed: dict, strict: bool) -> JudgeModel:
            model = JudgeModel.model_validate(parsed)
            check_exact_keys(list(model.reason_checks), item_ids, "reason_checks")
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
        """Final-pool membership: code's value check + the judge's rulings.
        The defender's stance is irrelevant here — wrongly conceded items
        are restored, judge-approved additions count even if refused."""
        for item in items:
            own_checks = judge.reason_checks[item["id"]]
            judge_detail: Dict[str, Any] = {}
            reasons: List[str] = []
            if item["value_check"]["verdict"] == "invalid":
                reasons.append("value_mismatch")
            for axis in AXES:
                attacker_check = (item.get("attacker_checks") or {}).get(axis)
                attacked = (
                    not item["added_by_attacker"]
                    and attacker_check is not None
                    and attacker_check["verdict"] == "invalid"
                )
                if attacked:
                    key = f"{item['id']}:{axis}"
                    ruling = judge.attack_rulings[key]
                    judge_detail[axis] = {
                        "kind": "attack_ruling",
                        "verdict": ruling.verdict,
                        "reason": ruling.reason,
                        "citations": self._clean_refs(
                            ruling.citations, dimensions, "judge", warnings
                        ),
                    }
                    if ruling.verdict == "attack_right":
                        reasons.append("attack_upheld")
                    else:
                        response = item["responses"].get(axis)
                        if response and response["accepted"]:
                            warnings.append(
                                "defender accepted an attack the judge ruled "
                                f"wrong ({key}) — evidence restored to the "
                                "final pool"
                            )
                else:
                    check = getattr(own_checks, f"{axis}_check")
                    judge_detail[axis] = {
                        "kind": "reason_check",
                        "verdict": check.verdict,
                        "reason": check.reason,
                        "citations": self._clean_refs(
                            check.citations, dimensions, "judge", warnings
                        ),
                    }
                    if check.verdict == "invalid":
                        reasons.append("judge_invalid")
            item["judge"] = judge_detail
            counted = not reasons
            item["final_status"] = "counted" if counted else "excluded"
            item["exclusion_reason"] = reasons[0] if reasons else None
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
        the model its validation errors. The retry parse runs in lenient
        mode (link problems degrade instead of failing the stage).
        Returns (model|None, warnings)."""
        error = None
        raw = self._summarize(prompt)
        parsed = parse_llm_json(raw)
        if parsed is None:
            error = "the reply was not a JSON object"
        else:
            try:
                return parse(parsed, True), []
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
                parse(parsed, False),
                [f"{stage} needed a retry — first reply was invalid"],
            )
        except (ValidationError, ValueError) as exc:
            return None, [f"{stage} invalid after retry: {_validation_text(exc)}"]

    def _base_item(
        self,
        model: EvidenceItemModel,
        dimensions: Sequence[DimensionResult],
        owner: str,
        warnings: List[str],
    ) -> Dict[str, Any]:
        links, problems = self._verified_links(model, dimensions, owner, warnings)
        if problems:
            warnings.append(
                f"{owner} {model.id}: {'; '.join(problems)} — citation check "
                "failed mechanically"
            )
        return {
            "id": model.id,
            "dimension": model.dimension,
            "direction": model.direction,
            "claim": model.claim.strip(),
            "links": links,
            "value_check": {
                "verdict": "invalid" if problems else "valid",
                "problems": problems,
            },
            "added_by_attacker": False,
            "attacker_checks": None,
            "responses": {axis: None for axis in AXES},
            "response": None,
            "judge": None,
            "final_status": None,
            "exclusion_reason": None,
        }

    def _checks_detail(
        self,
        checks: ItemChecksModel,
        dimensions: Sequence[DimensionResult],
        owner: str,
        warnings: List[str],
    ) -> Dict[str, Any]:
        return {
            axis: self._check_detail(
                getattr(checks, f"{axis}_check"), dimensions, owner, warnings
            )
            for axis in AXES
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

    def _response_detail(
        self,
        checks: ItemChecksModel,
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> Dict[str, Any]:
        detail = self._checks_detail(checks, dimensions, "defender", warnings)
        accepted = all(detail[axis]["verdict"] == "valid" for axis in AXES)
        return {
            "accepted": accepted,
            "citation_check": detail["citation"],
            "logic_check": detail["logic"],
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
    """The pool as the defender's responses leave it: original items minus
    conceded ones, plus additions it accepted."""
    if item["added_by_attacker"]:
        response = item.get("response")
        return bool(response and response["accepted"])
    for axis in AXES:
        response = (item.get("responses") or {}).get(axis)
        if response is not None and response["accepted"]:
            return False  # conceded
    return True


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


def _items_json(items: Sequence[EvidenceItemModel]) -> str:
    return json.dumps(
        [item.model_dump() for item in items], ensure_ascii=False, indent=1
    )


def _links_text(links: Sequence[Dict[str, Any]]) -> str:
    parts = []
    for link in links:
        text = f"{link['text']} → {link['ref']}"
        if link.get("value") is not None:
            text += f" = {link['value']}"
        if link.get("mismatch"):
            text += " (VALUE MISMATCH — auto-failed by code)"
        parts.append(text)
    return "; ".join(parts)


def _check_text(check: Dict[str, Any]) -> str:
    if check["verdict"] == "valid":
        return "valid"
    text = f"INVALID — {check['reason']}"
    if check["citations"]:
        text += f" [cites: {', '.join(check['citations'])}]"
    return text


def _response_text(response: Dict[str, Any]) -> str:
    parts = [
        f"{axis} check on the challenge: {_check_text(response[f'{axis}_check'])}"
        for axis in AXES
    ]
    verdict = "ACCEPTED" if response["accepted"] else "REJECTED"
    return f"defender response ({verdict}): " + "; ".join(parts)


def _tree_text(items: Sequence[Dict[str, Any]]) -> str:
    """The debate tree as indented text for the judge/summary prompts."""
    lines: List[str] = []
    for dimension in DIMENSIONS:
        group = [i for i in items if i["dimension"] == dimension]
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
            if item["value_check"]["verdict"] == "invalid":
                lines.append(
                    "    - CODE: citation check auto-failed — "
                    + "; ".join(item["value_check"]["problems"])
                )
            if item["added_by_attacker"]:
                if item["response"] is not None:
                    lines.append(f"    - {_response_text(item['response'])}")
                continue
            checks = item.get("attacker_checks")
            if not checks:
                continue
            for axis in AXES:
                lines.append(
                    f"    - attacker {axis} check ({item['id']}:{axis}): "
                    f"{_check_text(checks[axis])}"
                )
                response = item["responses"].get(axis)
                if response is not None:
                    lines.append(f"      - {_response_text(response)}")
    return "\n".join(lines) if lines else "(no evidence was listed)"


def _challenges_text(items: Sequence[Dict[str, Any]]) -> str:
    """The challenge list for the defender-reply prompt, keys included."""
    lines: List[str] = []
    for item in items:
        if item["added_by_attacker"]:
            links = f" [{_links_text(item['links'])}]" if item["links"] else ""
            lines.append(
                f'- key "add:{item["id"]}" — the attacker says you MISSED this '
                f"evidence: ({item['direction']}) {item['claim']}{links}"
            )
            continue
        checks = item.get("attacker_checks")
        if not checks:
            continue
        for axis in AXES:
            if checks[axis]["verdict"] != "invalid":
                continue
            lines.append(
                f'- key "{item["id"]}:{axis}" — attack on your item '
                f"{item['id']} ({axis}): {_check_text(checks[axis])}"
            )
    return "\n".join(lines) if lines else "(none)"
