# -*- coding: utf-8 -*-
"""Tiered-analysis API: run tier 1 for a symbol from the web UI.

A full run takes minutes (data fetch + LLM), so POST /analyze returns a
task id immediately; the run executes in a background thread. Runs
persist in the tiered_runs table (src/tiered_analysis/history.py), so
GET /runs serves a clickable history that survives page navigation and
server restarts, and GET /runs/{task_id} returns the stored full report.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.tiered_analysis import history

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_analysis(stock_code: str, depth: int = 1,
                  sizing_overrides: Optional[Dict[str, float]] = None):
    """Indirection so tests can patch the multi-minute production run."""
    from src.tiered_analysis.integration import run_tiered_analysis

    return run_tiered_analysis(
        stock_code, depth=depth, sizing_overrides=sizing_overrides
    )


class SizingOverride(BaseModel):
    """Per-run sizing inputs; saved settings fill whatever is omitted."""

    capital: Optional[float] = Field(default=None, gt=0)
    risk_fraction: Optional[float] = Field(default=None, gt=0, lt=1)
    #: Shares of this stock the user already holds (0 = none). Lets a
    #: sell verdict print a share count and tier 3 scale the exit.
    ownership: Optional[int] = Field(default=None, ge=0)


class TieredAnalyzeRequest(BaseModel):
    stock_code: str
    #: 1 = the one-blob judge, 2 = the evidence vote. Tier 3 is retired
    #: (outlook redesign) — depth 3 is a validation error, not a clamp.
    depth: int = Field(default=1, ge=1, le=2)
    sizing: Optional[SizingOverride] = None

    @field_validator("stock_code")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("stock_code must not be blank")
        return cleaned


def _serialize_levels(levels: Any) -> Dict[str, Any]:
    return {
        "entry": levels.entry,
        "secondary_entry": levels.secondary_entry,
        "stop_loss": levels.stop_loss,
        "take_profit": levels.take_profit,
    }


def _serialize_tier_section(report: Any) -> Optional[Dict[str, Any]]:
    """Tier 2/3 section: verdict + audit trail, no dimension duplication."""
    if report is None:
        return None
    section: Dict[str, Any] = {
        "tier": report.tier,
        "coverage": report.coverage.value,
        "direction": report.direction.value,
        "confidence": report.confidence,
        "score": report.score,
        "levels": _serialize_levels(report.levels),
        "narrative": report.narrative,
        "warnings": list(report.warnings),
    }
    if report.debate_detail is not None:
        section["debate_detail"] = report.debate_detail
    if report.risk_detail is not None:
        section["risk_detail"] = report.risk_detail
    return section


def _serialize_outcome(outcome: Any) -> Dict[str, Any]:
    report = outcome.report
    dimensions = []
    for dim in report.dimensions:
        dimensions.append({
            "dimension": dim.dimension,
            "kind": dim.kind.value,
            "coverage": dim.coverage.value,
            "is_actionable": dim.is_actionable,
            "payload": dim.payload,
            "narrative": dim.narrative,
            "warnings": list(dim.warnings),
            "citations": [
                {
                    "source_name": c.source_name,
                    "url": c.url,
                    "title": c.title,
                    "snippet": c.snippet,
                }
                for c in (dim.citations or [])
            ],
        })

    signal: Optional[Dict[str, Any]] = None
    if outcome.signal is not None:
        signal = {
            "logged": outcome.signal.logged,
            "signal_id": outcome.signal.signal_id,
            "created": outcome.signal.created,
            "reason": outcome.signal.reason,
        }

    state_reports = getattr(outcome.state, "reports", {}) or {}
    final = outcome.final_report or report
    return {
        "symbol": report.symbol,
        "market": report.market.value,
        "tier": report.tier,
        "direction": report.direction.value,
        "score": report.score,
        "confidence": report.confidence,
        "coverage": report.coverage.value,
        "levels": _serialize_levels(report.levels),
        "levels_detail": report.levels_detail,
        "narrative": report.narrative,
        "warnings": list(report.warnings),
        "dimensions": dimensions,
        "signal": signal,
        # v2 slice 6 (additive): depth, deeper-tier sections, sizing, cost.
        "depth": outcome.depth,
        "final": {
            "tier": final.tier,
            "direction": final.direction.value,
            "outlook": outcome.outlook.value,
            "action": outcome.action.value,
            "coverage": final.coverage.value,
            "confidence": final.confidence,
            "levels": _serialize_levels(final.levels),
        },
        "tier2": _serialize_tier_section(state_reports.get(2)),
        "sizing": outcome.sizing,
        "llm_usage": outcome.llm_usage,
        # Outlook redesign (additive): the impersonal judgment, the
        # personal action, the warning-only earnings date, and the
        # display-only 13-entry risk card.
        "outlook": outcome.outlook.value,
        "action": outcome.action.value,
        "earnings": outcome.earnings.to_detail() if outcome.earnings else None,
        "risk_card": outcome.risk_card,
    }


def _run_task(task_id: str, stock_code: str, depth: int = 1,
              sizing_overrides: Optional[Dict[str, float]] = None) -> None:
    try:
        outcome = _run_analysis(stock_code, depth=depth,
                                sizing_overrides=sizing_overrides)
        history.mark_done(task_id, _serialize_outcome(outcome))
    except Exception as exc:
        logger.error("tiered analysis task failed for %s: %s",
                     stock_code, exc, exc_info=True)
        history.mark_failed(task_id, str(exc))


@router.post("/analyze", status_code=202)
def start_tiered_analysis(request: TieredAnalyzeRequest) -> Dict[str, Any]:
    """Kick off a tiered run in the background; returns a pollable task."""
    task_id = uuid.uuid4().hex
    history.create_run(task_id, request.stock_code)
    sizing_overrides: Optional[Dict[str, float]] = None
    if request.sizing is not None:
        sizing_overrides = request.sizing.model_dump(exclude_none=True) or None
    worker = threading.Thread(
        target=_run_task,
        args=(task_id, request.stock_code, request.depth, sizing_overrides),
        name=f"tiered-analysis-{request.stock_code}",
        daemon=True,
    )
    worker.start()
    return {"task_id": task_id, "stock_code": request.stock_code,
            "depth": request.depth, "status": "running"}


@router.get("/sizing-defaults")
def get_sizing_defaults() -> Dict[str, Optional[float]]:
    """Saved sizing settings (.env-backed) — capital and risk fraction —
    so the run form can show the values a run would use when the user
    provides none. Both are null when no defaults are configured."""
    from src.tiered_analysis.settings import load_sizing_settings

    settings = load_sizing_settings()
    return {"capital": settings.capital,
            "risk_fraction": settings.risk_fraction}


@router.get("/runs")
def list_tiered_runs(limit: int = 50) -> Dict[str, List[Dict[str, Any]]]:
    """Run history, newest first (summaries only)."""
    return {"items": history.list_runs(limit=limit)}


@router.get("/runs/{task_id}")
def get_tiered_run(task_id: str) -> Dict[str, Any]:
    """One run with its stored full report."""
    run = history.get_run(task_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run
