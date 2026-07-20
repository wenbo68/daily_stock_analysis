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
from src.tiered_analysis.earnings import EarningsInfo
from src.tiered_analysis.schema import (
    Action,
    Direction,
    Outlook,
    SniperLevels,
    TierReport,
)
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


def _deep_outcome(symbol="AAPL"):
    """Depth-2 outcome with a debate section and a sizing block."""
    base = _outcome(symbol)
    tier2 = TierReport(
        tier=2, symbol=symbol, market=Market.US,
        coverage=Coverage.FULL, direction=Direction.BUY,
        confidence="0.70", levels=base.report.levels,
        narrative="bull case holds",
        debate_detail={"verdict": {"direction": "buy", "confidence": 0.7}},
    )
    state = TierState(
        symbol=symbol, market=Market.US,
        reports={1: base.report, 2: tier2},
    )
    sizing = {"enabled": True, "shares": 83,
              "reason_code": None, "refusal_reason": None, "notes": []}
    llm_usage = {"stages": {"tier2_debate": {"calls": 3, "prompt_tokens": 900,
                                             "completion_tokens": 300}},
                 "total": {"calls": 3, "prompt_tokens": 900,
                           "completion_tokens": 300},
                 "scope": "tiered-package LLM calls only"}
    return TieredRunOutcome(
        report=base.report, state=state, signal=base.signal,
        depth=2, final_report=tier2, sizing=sizing, llm_usage=llm_usage,
        outlook=Outlook.BULLISH, action=Action.ENTER,
        earnings=EarningsInfo(next_date="2026-07-24", days_until=4),
        risk_card=[{"id": "volatility", "status": "ok", "values": {}}],
    )


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
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
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
        def boom(code, **kwargs):
            raise RuntimeError("upstream exploded")

        with patch.object(tiered, "_run_analysis", boom):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            body = _poll_until_done(client, accepted.json()["task_id"])

        assert body["status"] == "failed"
        assert "upstream exploded" in body["error"]

    def test_runs_list_is_history_newest_first(self, client):
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
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

    def test_sizing_defaults_reflect_env_settings(self, client, monkeypatch):
        monkeypatch.setenv("TIERED_SIZING_CAPITAL", "100000")
        monkeypatch.setenv("TIERED_SIZING_RISK_FRACTION", "0.01")
        response = client.get("/tiered/sizing-defaults")
        assert response.status_code == 200
        assert response.json() == {"capital": 100000.0, "risk_fraction": 0.01}

    def test_sizing_defaults_null_when_unconfigured(self, client, monkeypatch):
        monkeypatch.delenv("TIERED_SIZING_CAPITAL", raising=False)
        monkeypatch.delenv("TIERED_SIZING_RISK_FRACTION", raising=False)
        response = client.get("/tiered/sizing-defaults")
        assert response.status_code == 200
        assert response.json() == {"capital": None, "risk_fraction": None}


class TestTieredDepthAndSizingApi:
    """v2 slice 6: depth parameter, sizing override, new response sections."""

    def test_depth_out_of_range_rejected(self, client):
        # Tier 3 is retired: depth 3 is an error, not a clamp (user
        # decision, 2026-07-20).
        for depth in (0, 3, 4):
            response = client.post(
                "/tiered/analyze", json={"stock_code": "AAPL", "depth": depth})
            assert response.status_code == 422

    def test_invalid_sizing_override_rejected(self, client):
        response = client.post("/tiered/analyze", json={
            "stock_code": "AAPL",
            "sizing": {"capital": -5, "risk_fraction": 0.01},
        })
        assert response.status_code == 422
        response = client.post("/tiered/analyze", json={
            "stock_code": "AAPL",
            "sizing": {"risk_fraction": 1.5},
        })
        assert response.status_code == 422
        response = client.post("/tiered/analyze", json={
            "stock_code": "AAPL",
            "sizing": {"ownership": -1},
        })
        assert response.status_code == 422

    def test_ownership_reaches_the_runner(self, client):
        captured = {}

        def fake_run(code, depth=1, sizing_overrides=None):
            captured["sizing_overrides"] = sizing_overrides
            return _deep_outcome(code)

        with patch.object(tiered, "_run_analysis", fake_run):
            accepted = client.post("/tiered/analyze", json={
                "stock_code": "AAPL",
                "depth": 2,
                "sizing": {"ownership": 300},
            })
            assert accepted.status_code == 202
            _poll_until_done(client, accepted.json()["task_id"])

        assert captured["sizing_overrides"] == {"ownership": 300}

    def test_depth_and_sizing_reach_the_runner(self, client):
        captured = {}

        def fake_run(code, depth=1, sizing_overrides=None):
            captured["code"] = code
            captured["depth"] = depth
            captured["sizing_overrides"] = sizing_overrides
            return _deep_outcome(code)

        with patch.object(tiered, "_run_analysis", fake_run):
            accepted = client.post("/tiered/analyze", json={
                "stock_code": "AAPL",
                "depth": 2,
                "sizing": {"capital": 50000, "risk_fraction": 0.02},
            })
            assert accepted.status_code == 202
            assert accepted.json()["depth"] == 2
            _poll_until_done(client, accepted.json()["task_id"])

        assert captured["depth"] == 2
        assert captured["sizing_overrides"] == {"capital": 50000.0,
                                                "risk_fraction": 0.02}

    def test_deep_run_response_contract(self, client):
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _deep_outcome(code)):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL", "depth": 2})
            body = _poll_until_done(client, accepted.json()["task_id"])

        result = body["result"]
        assert result["depth"] == 2
        # tier-1 fields keep their v1 shape for the existing UI
        assert result["direction"] == "hold"
        assert result["tier"] == 1
        # the deepest tier is what the user should act on
        assert result["final"]["tier"] == 2
        assert result["final"]["direction"] == "buy"
        assert result["final"]["outlook"] == "bullish"
        assert result["final"]["action"] == "enter"
        assert result["tier2"]["debate_detail"]["verdict"]["direction"] == "buy"
        assert result["sizing"]["shares"] == 83
        assert result["llm_usage"]["total"]["calls"] == 3
        # outlook redesign additions
        assert result["outlook"] == "bullish"
        assert result["action"] == "enter"
        assert result["earnings"]["next_date"] == "2026-07-24"
        assert result["earnings"]["is_near"] is True
        assert result["risk_card"][0]["id"] == "volatility"

    def test_v1_shaped_outcome_serializes_with_defaults(self, client):
        # An outcome without the new fields (depth-1 run) must still
        # produce the additive keys, as explicit "not run" values.
        with patch.object(tiered, "_run_analysis",
                          lambda code, **kwargs: _outcome(code)):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            body = _poll_until_done(client, accepted.json()["task_id"])

        result = body["result"]
        assert result["depth"] == 1
        assert result["final"]["tier"] == 1
        assert result["tier2"] is None
        assert result["sizing"] is None
        assert result["llm_usage"] is None
        assert result["outlook"] == "unknown"
        assert result["action"] == "unknown"
        assert result["earnings"] is None
        assert result["risk_card"] is None
