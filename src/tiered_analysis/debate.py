# -*- coding: utf-8 -*-
"""Tier 2: defender/attacker/judge evidence debate (v5).

Redesign (owner spec, 2026-07-17, see .claude/reviews/tier2-v5-design.md).
No forced bull/bear personas: one DEFENDER lists ALL the evidence it finds
in the four dimension reports — bullish and bearish — and scores its
honest read (0-10, 5 neutral). One ATTACKER, having first built its own
independent list (in parallel, so omission-finding is a diff, not an
assignment), checks every defender item on two axes (citation, logic) and
adds what the defender missed. The defender responds mechanically — its
own checks ON each attack/addition; both pass → accept, either fails →
rejection — then adjusts its score. One JUDGE has the final say with
binary rulings. Code (never an LLM) counts the weight ledger:

    1/1  every item the defender correctly kept in the pool
    0/1  every item the defender got wrong (kept bad / dropped good)
    0/0  items correctly removed (conceded reasons, rejected bogus additions)

    weight = correct keeps / (correct keeps + errors)
    final  = 5 + weight × (adjusted − 5)        (2 decimals)
    verdict: < 4 sell, 4-6 hold, > 6 buy

6 LLM calls across 5 sequential steps (the two openings run in parallel),
all at temperature 0. Every stage fills a strict Pydantic form; an invalid
reply gets ONE retry with the validation errors shown, then the failure
rules apply: defender/judge failures void the tier-2 verdict (tier-1
direction stands), attacker failures degrade loudly, the summary's
failure never voids anything. Citations must resolve to a single payload
value (leaf paths, never groupings) or an in-range sentiment citation;
invalid refs are stripped by code before anyone grades them.
"""
from __future__ import annotations

import json
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
    MAX_ITEMS_PER_DIMENSION,
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
DETAIL_FORMAT = 5


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
    #: 5 + weight × (adjusted − 5), rounded to 2 decimals.
    final_score: float
    summary: str
    initial_score: int
    adjusted_score: int
    #: True when the defender answered "keep" (or there was nothing to adjust).
    adjusted_kept: bool
    weight_numerator: int
    weight_denominator: int
    #: correct keeps / (correct keeps + errors); 0 on an empty ledger.
    weight: float


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
                "adjusted_kept": v.adjusted_kept,
                "weight": {
                    "numerator": v.weight_numerator,
                    "denominator": v.weight_denominator,
                    "value": v.weight,
                },
                # Legacy keys kept so pre-v5 readers never crash.
                "confidence": None,
                "reasons_for": [],
                "reasons_against": [],
                "would_change_mind": None,
                "bull_summary": None,
                "bear_summary": None,
                "scoring": None,
            }
        return {
            "format": DETAIL_FORMAT,
            # Legacy key: pre-v5 readers iterate turns; v5 has none.
            "turns": [],
            "items": [dict(item) for item in self.items],
            "verdict": verdict,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Prompts — one marker phrase per stage so tests can route replies.
# ---------------------------------------------------------------------------

_CONTEXT_TEMPLATE = """Stock under debate: {symbol}
Tier-1 verdict so far: direction={direction}, score={score}, confidence={confidence}
Tier-1 levels: entry={entry}, backup={secondary_entry}, stop={stop_loss}, target={take_profit}

Collected evidence (the ONLY facts you may use — no outside knowledge):
{evidence_block}
"""

_CITE_RULES = """Citation rules (checked mechanically — invalid refs are stripped):
- A payload citation must point at ONE exact value, like "technicals.rsi_14"
  or "fundamentals.revenue_yoy_pct". Grouping paths that hold several values
  (like "technicals.macd" when it contains sub-values) are rejected — cite
  the leaf, like "technicals.macd.signal".
- "citation:N" cites news source N from the sentiment evidence above.
- Cite only the evidence above; never invent facts or references."""

_LIST_RULES = """Evidence-list rules:
- Group items by dimension: technicals, fundamentals, macro_econ, sentiment.
- For every dimension that has data above, list {min_items} to {max_items}
  items. If (and only if) a dimension truly has no collected data above,
  skip it and name it in "no_data_dimensions" — code verifies this.
- Each item: one atomic claim (one sentence), tagged "bullish" or
  "bearish", with at least one citation.
- Item ids: T1, T2… for technicals, F1… for fundamentals, M1… for
  macro_econ, S1… for sentiment."""

_ITEM_SHAPE = """{{"id": "T1", "dimension": "technicals", "direction": "bullish",
  "claim": "one-sentence claim", "citations": ["technicals.rsi_14"]}}"""

_DEFENDER_OPENING_TEMPLATE = """{context}
You are the DEFENDER analyst. You take no side: list ALL the evidence you
can find in the reports above — bullish AND bearish — then give your
honest initial position score (0 = strongly bearish, 5 = neutral,
10 = strongly bullish, whole number) based on everything you listed.

{list_rules}

{cite_rules}

Reply with JSON only:
{{"items": [{item_shape}],
 "no_data_dimensions": [],
 "initial_score": <whole number 0-10>}}"""

_ATTACKER_OPENING_TEMPLATE = """{context}
You are the ATTACKER analyst, working alone. Another analyst is building
an evidence list from these same reports; you have NOT seen it. Build your
own complete list — bullish AND bearish — so the two can be compared.
You take no position and give no score.

{list_rules}

{cite_rules}

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

2. Checks — for EVERY defender item, two checks:
   - citation_check: does the cited data really say what the claim says?
   - logic_check: does the direction tag actually follow from the fact?
   Verdict "valid" or "invalid"; an "invalid" needs a reason and
   citations. If an item has no real flaw, mark both checks valid — a
   false attack costs you with the judge.

{cite_rules}

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

For EVERY defender item, two checks:
- citation_check: does the cited data really say what the claim says?
- logic_check: does the direction tag actually follow from the fact?
Verdict "valid" or "invalid"; an "invalid" needs a reason and citations.
If an item has no real flaw, mark both checks valid — a false attack
costs you with the judge.

{cite_rules}

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
invalid, that check's reason + citations ARE your rejection.

Then give your adjusted position score (whole number 0-10) reflecting all
the evidence as you now see it — or the word "keep" if your initial score
{initial_score} still stands.

{cite_rules}

Reply with JSON only:
{{"responses": {{"T2:logic": {{"citation_check": {{"verdict": "valid", "reason": null, "citations": []}},
                            "logic_check": {{"verdict": "invalid", "reason": "why the challenge fails", "citations": ["technicals.rsi_14"]}}}}}},
 "adjusted_score": <whole number 0-10 or "keep">}}
"responses" must cover exactly these keys: {challenge_keys}."""

_JUDGE_TEMPLATE = """{context}
You are the JUDGE with the final say. Below is the full debate tree —
the defender's evidence, the attacker's checks and additions, and the
defender's responses. Do NOT pick a direction and do NOT score anything —
code computes the verdict from your binary rulings.

{tree}

Three ruling sets:

1. reason_checks — for EVERY defender-listed item, your OWN independent
   citation_check and logic_check on the item (the attacker may have
   missed a flaw or invented one; you check from scratch).
2. attack_rulings — for EVERY attack, rule "attack_right" (the attack
   found a real flaw) or "attack_wrong" (the attack itself is mistaken).
   Read the defender's response as input, but rule on the attack itself.
3. addition_rulings — for EVERY attacker addition, rule "real" (genuine
   evidence the defender missed) or "bogus" (invented, duplicated, or
   miscited). Rule regardless of what the defender said about it.

Every ruling needs a short plain-English reason; cite evidence where it
helps.

{cite_rules}

Reply with JSON only:
{{"reason_checks": {{"T1": {{"citation_check": {{"verdict": "valid", "reason": null, "citations": []}},
                          "logic_check": {{"verdict": "valid", "reason": null, "citations": []}}}}}},
 "attack_rulings": {{"T2:logic": {{"verdict": "attack_wrong", "reason": "why", "citations": []}}}},
 "addition_rulings": {{"F3": {{"verdict": "real", "reason": "why", "citations": []}}}}}}
"reason_checks" must cover exactly: {defender_ids}.
"attack_rulings" must cover exactly: {attack_keys}.
"addition_rulings" must cover exactly: {addition_ids}."""

_SUMMARY_TEMPLATE = """{context}
Full debate tree:
{tree}

Computed result (fixed formula, already decided by code):
- initial position score {initial}, adjusted {adjusted}
- weight = {numerator}/{denominator} = {weight} (the share of the evidence
  pool the defender handled correctly, per the judge)
- final = 5 + weight × (adjusted − 5) = {final} out of 10
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
    """Runs the v5 debate. Never raises out of run()."""

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
        # Step 1 — the two openings, in parallel (the attacker's own list
        # must be built blind, so it is a separate call; it depends only
        # on the reports, so it costs no wall-clock).
        opening, attacker_opening = self._openings(
            context, dimensions, data_dimensions, warnings
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

        # Step 3 — defender responds to every challenge + adjusts. Skipped
        # (score kept) when nothing was challenged.
        challenge_keys = self._challenge_keys(items)
        adjusted_score = opening.initial_score
        adjusted_kept = True
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
            if isinstance(reply.adjusted_score, int):
                adjusted_score = reply.adjusted_score
                adjusted_kept = adjusted_score == opening.initial_score
        else:
            warnings.append(
                "attacker raised no challenges — defender response skipped, "
                "initial score kept"
            )

        # Step 4 — the judge's binary rulings, final say.
        judge = self._judge(context, dimensions, items, warnings)
        if judge is None:
            warnings.append("judge rulings invalid after retry — tier-2 verdict voided")
            return DebateResult(items=items, warnings=warnings)
        numerator, denominator = self._apply_rulings(
            items, judge, dimensions, warnings
        )

        weight = round(numerator / denominator, 4) if denominator else 0.0
        if denominator == 0:
            warnings.append(
                "no surviving evidence to weigh — final score is neutral 5 by default"
            )
        defender_items = [i for i in items if not i["added_by_attacker"]]
        survivors = sum(1 for i in defender_items if i["count"]["numerator"] == 1)
        if defender_items and survivors * 2 < len(defender_items):
            warnings.append(
                "most of the defender's initial evidence did not survive — "
                "the weight rests on a thin base"
            )

        final = round(5 + weight * (adjusted_score - 5), 2)
        direction = direction_from_final(final)

        # Step 5 — the user-facing prose; its failure never voids anything.
        summary = self._summary(
            context,
            items,
            opening.initial_score,
            adjusted_score,
            numerator,
            denominator,
            weight,
            final,
            direction,
            warnings,
        )

        verdict = DebateVerdict(
            direction=direction,
            final_score=final,
            summary=summary,
            initial_score=opening.initial_score,
            adjusted_score=adjusted_score,
            adjusted_kept=adjusted_kept,
            weight_numerator=numerator,
            weight_denominator=denominator,
            weight=weight,
        )
        return DebateResult(items=items, verdict=verdict, warnings=warnings)

    # -- step 1 ------------------------------------------------------------

    def _openings(
        self,
        context: str,
        dimensions: Sequence[DimensionResult],
        data_dimensions: List[str],
        warnings: List[str],
    ) -> Tuple[Optional[DefenderOpeningModel], Optional[AttackerOpeningModel]]:
        list_rules = _LIST_RULES.format(
            min_items=MIN_ITEMS_PER_DIMENSION, max_items=MAX_ITEMS_PER_DIMENSION
        )
        defender_prompt = _DEFENDER_OPENING_TEMPLATE.format(
            context=context,
            list_rules=list_rules,
            cite_rules=_CITE_RULES,
            item_shape=_ITEM_SHAPE,
        )
        attacker_prompt = _ATTACKER_OPENING_TEMPLATE.format(
            context=context,
            list_rules=list_rules,
            cite_rules=_CITE_RULES,
            item_shape=_ITEM_SHAPE,
        )

        def parse_defender(parsed: dict) -> DefenderOpeningModel:
            model = DefenderOpeningModel.model_validate(parsed)
            check_opening_items(model.items, data_dimensions)
            return model

        def parse_attacker(parsed: dict) -> AttackerOpeningModel:
            model = AttackerOpeningModel.model_validate(parsed)
            check_opening_items(model.items, data_dimensions)
            return model

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
                run_stage, (defender_prompt, parse_defender, "defender opening")
            )
            attacker_future = pool.submit(
                run_stage, (attacker_prompt, parse_attacker, "attacker opening")
            )
            defender_model, defender_warnings = defender_future.result()
            attacker_model, attacker_warnings = attacker_future.result()
        warnings.extend(defender_warnings)
        warnings.extend(attacker_warnings)
        return defender_model, attacker_model

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
                cite_rules=_CITE_RULES,
                defender_ids=", ".join(defender_ids),
            )
        else:
            prompt = _ATTACKER_CHECKS_ONLY_TEMPLATE.format(
                context=context,
                defender_items=_items_json(opening.items),
                cite_rules=_CITE_RULES,
                defender_ids=", ".join(defender_ids),
            )

        def parse(parsed: dict) -> AttackerReviewModel:
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
            initial_score=opening.initial_score,
            cite_rules=_CITE_RULES,
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
        defender_ids = [i["id"] for i in items if not i["added_by_attacker"]]
        addition_ids = [i["id"] for i in items if i["added_by_attacker"]]
        attack_keys = [
            key for key in self._challenge_keys(items) if not key.startswith("add:")
        ]
        prompt = _JUDGE_TEMPLATE.format(
            context=context,
            tree=_tree_text(items),
            cite_rules=_CITE_RULES,
            defender_ids=", ".join(defender_ids) or "(none)",
            attack_keys=", ".join(attack_keys) or "(none)",
            addition_ids=", ".join(addition_ids) or "(none)",
        )

        def parse(parsed: dict) -> JudgeModel:
            model = JudgeModel.model_validate(parsed)
            check_exact_keys(list(model.reason_checks), defender_ids, "reason_checks")
            check_exact_keys(list(model.attack_rulings), attack_keys, "attack_rulings")
            check_exact_keys(
                list(model.addition_rulings), addition_ids, "addition_rulings"
            )
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
    ) -> Tuple[int, int]:
        """The weight ledger: 1/1 correct keeps, 0/1 defender errors,
        0/0 correctly removed. Returns (numerator, denominator)."""
        numerator = 0
        denominator = 0
        for item in items:
            if item["added_by_attacker"]:
                num, den = self._score_addition(item, judge, dimensions, warnings)
            else:
                num, den = self._score_defender_item(item, judge, dimensions, warnings)
            item["count"] = {"numerator": num, "denominator": den}
            item["outcome"] = (
                "valid" if num == 1 else "invalid" if den == 1 else "neutral"
            )
            numerator += num
            denominator += den
        return numerator, denominator

    def _score_defender_item(
        self,
        item: Dict[str, Any],
        judge: JudgeModel,
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> Tuple[int, int]:
        own_checks = judge.reason_checks[item["id"]]
        judge_detail: Dict[str, Any] = {}
        any_bad = False
        any_conceded = False
        for axis in AXES:
            attacker_check = (item.get("attacker_checks") or {}).get(axis)
            attacked = attacker_check is not None and attacker_check["verdict"] == "invalid"
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
                response = item["responses"].get(axis)
                accepted = bool(response and response["accepted"])
                if ruling.verdict == "attack_wrong":
                    if accepted:
                        # Dropped good evidence — the judge overrules in the
                        # defender's favor, but the score already excluded it.
                        any_bad = True
                        warnings.append(
                            f"defender accepted an attack the judge ruled wrong "
                            f"({key}) — counted against the defender, flagged"
                        )
                    # rejected + attack_wrong → the reason stands (axis ok)
                else:  # attack_right
                    if accepted:
                        any_conceded = True  # correctly dropped → 0/0
                    else:
                        any_bad = True  # kept bad evidence
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
                    any_bad = True  # the judge caught what the attacker waved through
        item["judge"] = judge_detail
        if any_bad:
            return 0, 1
        if any_conceded:
            return 0, 0
        return 1, 1

    def _score_addition(
        self,
        item: Dict[str, Any],
        judge: JudgeModel,
        dimensions: Sequence[DimensionResult],
        warnings: List[str],
    ) -> Tuple[int, int]:
        ruling = judge.addition_rulings[item["id"]]
        item["judge"] = {
            "kind": "addition_ruling",
            "verdict": ruling.verdict,
            "reason": ruling.reason,
            "citations": self._clean_refs(
                ruling.citations, dimensions, "judge", warnings
            ),
        }
        response = item.get("response")
        accepted = bool(response and response["accepted"])
        if ruling.verdict == "real":
            return (1, 1) if accepted else (0, 1)  # wrongly refused real evidence
        # bogus addition: correctly filtered → excluded; adopted → error
        return (0, 1) if accepted else (0, 0)

    # -- step 5 ------------------------------------------------------------

    def _summary(
        self,
        context: str,
        items: Sequence[Dict[str, Any]],
        initial: int,
        adjusted: int,
        numerator: int,
        denominator: int,
        weight: float,
        final: float,
        direction: Direction,
        warnings: List[str],
    ) -> str:
        prompt = _SUMMARY_TEMPLATE.format(
            context=context,
            tree=_tree_text(items),
            initial=initial,
            adjusted=adjusted,
            numerator=numerator,
            denominator=denominator,
            weight=f"{weight:.4f}",
            final=f"{final:.2f}",
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

    def _base_item(
        self,
        model: EvidenceItemModel,
        dimensions: Sequence[DimensionResult],
        owner: str,
        warnings: List[str],
    ) -> Dict[str, Any]:
        return {
            "id": model.id,
            "dimension": model.dimension,
            "direction": model.direction,
            "claim": model.claim.strip(),
            "citations": self._clean_refs(
                model.citations, dimensions, owner, warnings
            ),
            "added_by_attacker": False,
            "attacker_checks": None,
            "responses": {axis: None for axis in AXES},
            "response": None,
            "judge": None,
            "count": None,
            "outcome": None,
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


def _check_text(check: Dict[str, Any]) -> str:
    if check["verdict"] == "valid":
        return "valid"
    text = f"INVALID — {check['reason']}"
    if check["citations"]:
        text += f" [cites: {', '.join(check['citations'])}]"
    return text


def _response_text(response: Dict[str, Any]) -> str:
    if response["accepted"]:
        return "defender response: ACCEPTED (both checks on the challenge came back valid)"
    parts = [
        f"{axis} check on the challenge: {_check_text(response[f'{axis}_check'])}"
        for axis in AXES
    ]
    return "defender response: REJECTED — " + "; ".join(parts)


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
            cites = f" [cites: {', '.join(item['citations'])}]" if item["citations"] else ""
            lines.append(
                f"  - [{item['id']}] ({item['direction']}, {source}) {item['claim']}{cites}"
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
            cites = (
                f" [cites: {', '.join(item['citations'])}]" if item["citations"] else ""
            )
            lines.append(
                f'- key "add:{item["id"]}" — the attacker says you MISSED this '
                f"evidence: ({item['direction']}) {item['claim']}{cites}"
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
