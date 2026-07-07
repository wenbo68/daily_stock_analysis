# -*- coding: utf-8 -*-
"""Tiered-analysis API: run tier 1 for a symbol from the web UI.

A full run takes minutes (data fetch + LLM), so POST /analyze returns a
task id immediately and the client polls GET /tasks/{id}. Tasks live in
process memory — good enough for a single-user personal deployment; a
server restart forgets running tasks (the logged signal still lands in
the decision-signal system).
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_TASKS = 50
_tasks: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_tasks_lock = threading.Lock()


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
        entry: Dict[str, Any] = {
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
        }
        dimensions.append(entry)

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
        "narrative": report.narrative,
        "warnings": list(report.warnings),
        "dimensions": dimensions,
        "signal": signal,
    }


def _set_task(task_id: str, payload: Dict[str, Any]) -> None:
    with _tasks_lock:
        _tasks[task_id] = payload
        _tasks.move_to_end(task_id)
        while len(_tasks) > _MAX_TASKS:
            _tasks.popitem(last=False)


def _run_task(task_id: str, stock_code: str) -> None:
    try:
        outcome = _run_analysis(stock_code)
        _set_task(task_id, {
            "task_id": task_id,
            "stock_code": stock_code,
            "status": "done",
            "result": _serialize_outcome(outcome),
        })
    except Exception as exc:
        logger.error("tiered analysis task failed for %s: %s",
                     stock_code, exc, exc_info=True)
        _set_task(task_id, {
            "task_id": task_id,
            "stock_code": stock_code,
            "status": "failed",
            "error": str(exc),
        })


@router.post("/analyze", status_code=202)
def start_tiered_analysis(request: TieredAnalyzeRequest) -> Dict[str, Any]:
    """Kick off a tiered run in the background; returns a pollable task."""
    task_id = uuid.uuid4().hex
    _set_task(task_id, {
        "task_id": task_id,
        "stock_code": request.stock_code,
        "status": "running",
    })
    worker = threading.Thread(
        target=_run_task,
        args=(task_id, request.stock_code),
        name=f"tiered-analysis-{request.stock_code}",
        daemon=True,
    )
    worker.start()
    return {"task_id": task_id, "stock_code": request.stock_code,
            "status": "running"}


@router.get("/tasks/{task_id}")
def get_tiered_task(task_id: str) -> Dict[str, Any]:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task
