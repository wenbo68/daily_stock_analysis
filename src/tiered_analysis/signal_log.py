# -*- coding: utf-8 -*-
"""Log tier reports into DSA's existing decision-signal system (slice 6).

DSA already has the recommendation log the design doc asked for: the
``decision_signals`` table (every recommendation with entry/stop/target),
the outcome job that fetches the subsequent price path
(``decision_signal_outcome_service``), and a web page that renders each
signal's ``data_quality_summary``. Building a parallel log would violate
the repo's reuse rule — so this module is a thin CLIENT adapter:

- ``build_signal_payload``: pure mapping TierReport -> service payload.
  Coverage badges ride in ``data_quality_summary`` (overall level plus a
  per-dimension map); the existing signals page displays them as-is.
- ``log_tier_report``: submits via ``DecisionSignalService`` (injected in
  tests). Logging must never crash an analysis run — failures come back
  as a structured ``SignalLogResult`` with the reason, not an exception.

Boundary note: this imports DSA services as a client, same as Tier1Stage
consumes DSA analysis results. It does not modify the decision path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .providers.base import Coverage, Market
from .schema import Direction, TierReport, coerce_price

logger = logging.getLogger(__name__)

SOURCE_TYPE = "agent"
SOURCE_AGENT = "tiered_analysis"
TRIGGER_SOURCE = "tiered_analysis"
GENERATOR = "tiered_analysis_v1"
#: data_quality_summary warning cap — keep the stored JSON bounded.
MAX_LOGGED_WARNINGS = 20

#: The signal service's quality normalizer knows "partial"/"unavailable"
#: but NOT "full" (it would collapse to "unknown") — translate explicitly.
_COVERAGE_TO_QUALITY = {
    Coverage.FULL: "high",
    Coverage.PARTIAL: "low",
    Coverage.UNAVAILABLE: "poor",
}


@dataclass(frozen=True)
class SignalLogResult:
    """Outcome of one logging attempt — never an exception."""

    logged: bool
    reason: Optional[str] = None
    signal_id: Optional[int] = None
    created: Optional[bool] = None


def coerce_confidence(value: Any) -> Optional[float]:
    """Normalize TierReport's textual confidence to the service's 0-1 scale.

    Accepts fractions ("0.72"), percent-scale numbers (83 -> 0.83), and
    returns None for text labels or out-of-range values — a missing
    confidence is honest; a fabricated one is not.
    """
    number = coerce_price(value)
    if number is None:
        return None
    if 0.0 <= number <= 1.0:
        return number
    if 1.0 < number <= 100.0:
        return number / 100.0
    return None


def build_signal_payload(
    report: TierReport, trace_id: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Map a TierReport to a DecisionSignalService payload.

    Returns ``(payload, None)`` or ``(None, skip_reason)`` — reports with
    no usable direction or market are skipped, not force-fitted.
    """
    if report.direction == Direction.UNKNOWN:
        return None, "direction is unknown — nothing to log"
    if report.market == Market.UNKNOWN:
        return None, "market is unknown — the signal service requires one"

    entries = [
        level
        for level in (report.levels.entry, report.levels.secondary_entry)
        if level is not None
    ]

    payload: Dict[str, Any] = {
        "stock_code": report.symbol,
        "market": report.market.value,
        "source_type": SOURCE_TYPE,
        "source_agent": SOURCE_AGENT,
        "trace_id": trace_id,
        "trigger_source": TRIGGER_SOURCE,
        "action": report.direction.value,
        "confidence": coerce_confidence(report.confidence),
        "score": report.score,
        "entry_low": min(entries) if entries else None,
        "entry_high": max(entries) if entries else None,
        "stop_loss": report.levels.stop_loss,
        "target_price": report.levels.take_profit,
        "reason": report.narrative,
        "data_quality_summary": {
            "level": _COVERAGE_TO_QUALITY[report.coverage],
            "coverage": report.coverage.value,
            "dimensions": {
                dim.dimension: dim.coverage.value for dim in report.dimensions
            },
            "warnings": list(report.warnings[:MAX_LOGGED_WARNINGS]),
        },
        "evidence": {"dimensions": _evidence_entries(report)},
        "metadata": {
            "generator": GENERATOR,
            "tier": report.tier,
            "sizing_empty": report.sizing.is_empty,
        },
    }
    return payload, None


def _evidence_entries(report: TierReport) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for dim in report.dimensions:
        entry: Dict[str, Any] = {
            "dimension": dim.dimension,
            "kind": dim.kind.value,
            "coverage": dim.coverage.value,
            "is_actionable": dim.is_actionable,
        }
        if dim.citations:
            entry["citations"] = [citation.url for citation in dim.citations]
        entries.append(entry)
    return entries


def _default_service():
    from src.services.decision_signal_service import DecisionSignalService

    return DecisionSignalService()


def log_tier_report(
    report: TierReport,
    service: Any = None,
    trace_id: Optional[str] = None,
) -> SignalLogResult:
    """Persist one tier report as a decision signal; never raises."""
    payload, skip_reason = build_signal_payload(report, trace_id=trace_id)
    if payload is None:
        return SignalLogResult(logged=False, reason=skip_reason)

    try:
        if service is None:
            service = _default_service()
        response = service.create_signal(payload) or {}
    except Exception as exc:
        logger.warning(
            "tiered_analysis signal log failed for %s: %s", report.symbol, exc
        )
        return SignalLogResult(
            logged=False, reason=f"signal service failed: {exc}"
        )

    item = response.get("item") or {}
    return SignalLogResult(
        logged=True,
        signal_id=item.get("id"),
        created=bool(response.get("created")),
    )
