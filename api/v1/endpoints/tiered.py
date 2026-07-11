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
from pydantic import BaseModel, field_validator

from src.tiered_analysis import history

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_analysis(stock_code: str):
    """Indirection so tests can patch the multi-minute production run."""
    from src.tiered_analysis.integration import run_tiered_analysis

    return run_tiered_analysis(stock_code)


class TieredAnalyzeRequest(BaseModel):
    stock_code: str

    @field_validator("stock_code")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("stock_code must not be blank")
        return cleaned


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

    return {
        "symbol": report.symbol,
        "market": report.market.value,
        "tier": report.tier,
        "direction": report.direction.value,
        "score": report.score,
        "confidence": report.confidence,
        "coverage": report.coverage.value,
        "levels": {
            "entry": report.levels.entry,
            "secondary_entry": report.levels.secondary_entry,
            "stop_loss": report.levels.stop_loss,
            "take_profit": report.levels.take_profit,
        },
        "levels_detail": report.levels_detail,
        "narrative": report.narrative,
        "warnings": list(report.warnings),
        "dimensions": dimensions,
        "signal": signal,
    }


def _run_task(task_id: str, stock_code: str) -> None:
    try:
        outcome = _run_analysis(stock_code)
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
    worker = threading.Thread(
        target=_run_task,
        args=(task_id, request.stock_code),
        name=f"tiered-analysis-{request.stock_code}",
        daemon=True,
    )
    worker.start()
    return {"task_id": task_id, "stock_code": request.stock_code,
            "status": "running"}


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
