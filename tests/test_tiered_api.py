# -*- coding: utf-8 -*-
"""Offline tests for the tiered-analysis API endpoint.

The real run takes minutes (LLM + data fetch), so the endpoint runs it
in a background thread and persists status/result to the tiered_runs
table; the client polls the run list/detail. Tests patch the runner with
fast fakes and use the repo-standard isolated sqlite fixture.
"""
from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import tiered
from src.tiered_analysis.integration import TieredRunOutcome
from src.tiered_analysis.providers.base import (
    Citation,
    Coverage,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.signal_log import SignalLogResult
from src.tiered_analysis.tiers import TierState


@pytest.fixture()
def isolated_db(tmp_path):
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "tiered_api.db"
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


@pytest.fixture()
def client(isolated_db):
    app = FastAPI()
    app.include_router(tiered.router, prefix="/tiered")
    return TestClient(app)


def _outcome(symbol="AAPL"):
    report = TierReport(
        tier=1,
        symbol=symbol,
        market=Market.US,
        coverage=Coverage.PARTIAL,
        direction=Direction.HOLD,
        score=56,
        levels=SniperLevels(entry=303.8, secondary_entry=294.7,
                            stop_loss=290.0, take_profit=325.0),
        narrative="Wait for a pullback.",
        dimensions=[
            DimensionResult(
                dimension="fundamentals", kind=SourceKind.NUMERIC,
                coverage=Coverage.FULL,
                payload={"growth": {"revenue_yoy_pct": 6.4}},
            ),
            DimensionResult(
                dimension="sentiment", kind=SourceKind.TEXTUAL,
                coverage=Coverage.PARTIAL,
                narrative="Sentiment: mixed.",
                citations=[Citation(source_name="Reuters",
                                    url="https://reuters.example/x",
                                    title="Reuters", snippet="q")],
                warnings=["one page blocked"],
            ),
        ],
        warnings=[],
    )
    state = TierState(symbol=symbol, market=Market.US, reports={1: report})
    signal = SignalLogResult(logged=True, signal_id=7, created=True)
    return TieredRunOutcome(report=report, state=state, signal=signal)


def _poll_until_done(client, task_id, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/tiered/runs/{task_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("run never finished")


class TestTieredAnalyzeEndpoint:
    def test_accepts_and_completes_run(self, client):
        with patch.object(tiered, "_run_analysis", lambda code: _outcome(code)):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            assert accepted.status_code == 202
            task_id = accepted.json()["task_id"]
            body = _poll_until_done(client, task_id)

        assert body["status"] == "done"
        result = body["result"]
        assert result["symbol"] == "AAPL"
        assert result["direction"] == "hold"
        assert result["score"] == 56
        assert result["coverage"] == "partial"
        assert result["levels"]["entry"] == 303.8
        assert result["signal"]["signal_id"] == 7
        dims = {d["dimension"]: d for d in result["dimensions"]}
        assert dims["fundamentals"]["payload"]["growth"]["revenue_yoy_pct"] == 6.4
        assert dims["sentiment"]["narrative"] == "Sentiment: mixed."
        assert dims["sentiment"]["citations"][0]["url"] == "https://reuters.example/x"

    def test_failed_run_reports_error(self, client):
        def boom(code):
            raise RuntimeError("upstream exploded")

        with patch.object(tiered, "_run_analysis", boom):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            body = _poll_until_done(client, accepted.json()["task_id"])

        assert body["status"] == "failed"
        assert "upstream exploded" in body["error"]

    def test_runs_list_is_history_newest_first(self, client):
        with patch.object(tiered, "_run_analysis", lambda code: _outcome(code)):
            first = client.post("/tiered/analyze",
                                json={"stock_code": "AAPL"}).json()["task_id"]
            _poll_until_done(client, first)
            second = client.post("/tiered/analyze",
                                 json={"stock_code": "NVDA"}).json()["task_id"]
            _poll_until_done(client, second)

        items = client.get("/tiered/runs").json()["items"]
        assert [item["stock_code"] for item in items[:2]] == ["NVDA", "AAPL"]
        assert all(item["status"] == "done" for item in items[:2])
        # summaries stay light — full reports come from the detail route
        assert all("result" not in item for item in items)

    def test_blank_stock_code_rejected(self, client):
        response = client.post("/tiered/analyze", json={"stock_code": "   "})
        assert response.status_code == 422

    def test_unknown_run_is_404(self, client):
        response = client.get("/tiered/runs/nope")
        assert response.status_code == 404
