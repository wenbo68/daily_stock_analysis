# -*- coding: utf-8 -*-
"""Persistent history of tiered-analysis runs (tiered_runs table).

The web tiered page shows these as a clickable run list: a run starts as
``running``, flips to ``done`` (with the full serialized report) or
``failed`` (with the error), and stays in the list as history across page
navigation and server restarts.

Storage is the product's existing sqlite database via DatabaseManager —
one small table, no separate infrastructure.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 50


def _session():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


def create_run(task_id: str, stock_code: str) -> None:
    from src.storage import TieredRunRecord

    with _session() as session:
        session.add(TieredRunRecord(
            task_id=task_id,
            stock_code=stock_code,
            status="running",
        ))
        session.commit()


def _update_run(task_id: str, **fields: Any) -> None:
    from src.storage import TieredRunRecord

    with _session() as session:
        row = (
            session.query(TieredRunRecord)
            .filter_by(task_id=task_id)
            .one_or_none()
        )
        if row is None:
            logger.warning("tiered run %s vanished before update", task_id)
            return
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def mark_done(task_id: str, result: Dict[str, Any]) -> None:
    _update_run(task_id, status="done", result_json=json.dumps(result))


def mark_failed(task_id: str, error: str) -> None:
    _update_run(task_id, status="failed", error=str(error))


def _row_summary(row: Any) -> Dict[str, Any]:
    return {
        "task_id": row.task_id,
        "stock_code": row.stock_code,
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_runs(limit: int = DEFAULT_LIST_LIMIT) -> List[Dict[str, Any]]:
    """Newest-first run summaries (no result payloads — keep the list light)."""
    from src.storage import TieredRunRecord

    safe_limit = max(1, min(int(limit), 200))
    with _session() as session:
        rows = (
            session.query(TieredRunRecord)
            .order_by(TieredRunRecord.created_at.desc(), TieredRunRecord.id.desc())
            .limit(safe_limit)
            .all()
        )
        return [_row_summary(row) for row in rows]


def get_run(task_id: str) -> Optional[Dict[str, Any]]:
    """One run with its full result (None result if still running/failed)."""
    from src.storage import TieredRunRecord

    with _session() as session:
        row = (
            session.query(TieredRunRecord)
            .filter_by(task_id=task_id)
            .one_or_none()
        )
        if row is None:
            return None
        summary = _row_summary(row)
        summary["result"] = None
        if row.result_json:
            try:
                summary["result"] = json.loads(row.result_json)
            except ValueError:
                summary["error"] = (
                    (summary["error"] or "")
                    + " stored result unreadable (corrupt JSON)"
                ).strip()
        return summary
