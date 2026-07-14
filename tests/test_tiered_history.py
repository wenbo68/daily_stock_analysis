# -*- coding: utf-8 -*-
"""Offline tests for the tiered run history (persistent run list).

Runs persist in the tiered_runs table so the web page keeps a clickable
history across navigation and server restarts. Uses the repo-standard
isolated sqlite fixture.
"""
from __future__ import annotations

import os

import pytest

from src.tiered_analysis.history import (
    create_run,
    get_run,
    list_runs,
    mark_done,
    mark_failed,
)


@pytest.fixture()
def isolated_db(tmp_path):
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "tiered_history.db"
    os.environ["DATABASE_PATH"] = str(db_path)
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


RESULT = {"symbol": "AAPL", "direction": "hold", "score": 56,
          "dimensions": [{"dimension": "technicals", "coverage": "full"}]}


class TestTieredRunHistory:
    def test_create_and_get_running_run(self, isolated_db):
        create_run("task-1", "AAPL")
        run = get_run("task-1")
        assert run["status"] == "running"
        assert run["stock_code"] == "AAPL"
        assert run["result"] is None
        assert run["created_at"]

    def test_mark_done_stores_result(self, isolated_db):
        create_run("task-1", "AAPL")
        mark_done("task-1", RESULT)
        run = get_run("task-1")
        assert run["status"] == "done"
        assert run["result"]["direction"] == "hold"
        assert run["result"]["dimensions"][0]["coverage"] == "full"

    def test_mark_failed_stores_error(self, isolated_db):
        create_run("task-1", "AAPL")
        mark_failed("task-1", "LLM quota exhausted")
        run = get_run("task-1")
        assert run["status"] == "failed"
        assert "LLM quota exhausted" in run["error"]

    def test_get_unknown_run_returns_none(self, isolated_db):
        assert get_run("nope") is None

    def test_list_runs_newest_first_without_results(self, isolated_db):
        create_run("task-1", "AAPL")
        mark_done("task-1", RESULT)
        create_run("task-2", "NVDA")
        runs = list_runs()
        assert [r["task_id"] for r in runs] == ["task-2", "task-1"]
        assert runs[0]["status"] == "running"
        assert runs[1]["status"] == "done"
        # list is lightweight: no full result payloads
        assert all("result" not in r for r in runs)

    def test_list_digest_has_direction_shares_and_tier(self, isolated_db):
        create_run("task-1", "AAPL")
        mark_done("task-1", {**RESULT,
                             "depth": 3,
                             "final": {"direction": "buy", "tier": 3},
                             "sizing": {"shares": 41}})
        create_run("task-2", "NVDA")  # still running — no digest yet
        runs = {r["task_id"]: r for r in list_runs()}
        assert runs["task-1"]["direction"] == "buy"
        assert runs["task-1"]["shares"] == 41
        assert runs["task-1"]["tier"] == 3
        assert runs["task-2"]["direction"] is None
        assert runs["task-2"]["shares"] is None
        assert runs["task-2"]["tier"] is None

    def test_list_digest_degrades_on_old_or_refused_runs(self, isolated_db):
        # v1 result: no final/sizing/depth -> top-level direction, dash
        # shares, and the top-level tier (v1 runs were tier 1 only)
        create_run("task-1", "AAPL")
        mark_done("task-1", {**RESULT, "tier": 1})
        # sizing ran but refused to buy (shares None) -> 0, like the report
        # card; no depth stored -> tier falls back to final.tier
        create_run("task-2", "MSFT")
        mark_done("task-2", {**RESULT,
                             "final": {"direction": "hold", "tier": 2},
                             "sizing": {"shares": None}})
        runs = {r["task_id"]: r for r in list_runs()}
        assert runs["task-1"]["direction"] == "hold"
        assert runs["task-1"]["shares"] is None
        assert runs["task-1"]["tier"] == 1
        assert runs["task-2"]["shares"] == 0
        assert runs["task-2"]["tier"] == 2

    def test_list_respects_limit(self, isolated_db):
        for index in range(5):
            create_run(f"task-{index}", "AAPL")
        assert len(list_runs(limit=3)) == 3

    def test_corrupt_result_json_surfaces_as_failed_parse(self, isolated_db):
        from src.storage import DatabaseManager, TieredRunRecord

        create_run("task-1", "AAPL")
        mark_done("task-1", RESULT)
        with DatabaseManager.get_instance().get_session() as session:
            row = session.query(TieredRunRecord).filter_by(task_id="task-1").one()
            row.result_json = "{not json"
            session.commit()
        run = get_run("task-1")
        assert run["result"] is None
        assert "unreadable" in (run["error"] or "")
