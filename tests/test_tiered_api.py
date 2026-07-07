# -*- coding: utf-8 -*-
"""Offline tests for the tiered-analysis API endpoint.

The real run takes minutes (LLM + data fetch), so the endpoint runs it in
a background thread and the client polls a task id. Tests patch the
runner with fast fakes.
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

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


def _client():
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
        response = client.get(f"/tiered/tasks/{task_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("task never finished")


class TestTieredAnalyzeEndpoint(unittest.TestCase):
    def test_accepts_and_completes_task(self):
        client = _client()
        with patch.object(tiered, "_run_analysis", lambda code: _outcome(code)):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            self.assertEqual(accepted.status_code, 202)
            task_id = accepted.json()["task_id"]
            body = _poll_until_done(client, task_id)

        self.assertEqual(body["status"], "done")
        result = body["result"]
        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["direction"], "hold")
        self.assertEqual(result["score"], 56)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["levels"]["entry"], 303.8)
        self.assertEqual(result["signal"]["signal_id"], 7)
        dims = {d["dimension"]: d for d in result["dimensions"]}
        self.assertEqual(dims["fundamentals"]["payload"]["growth"]["revenue_yoy_pct"], 6.4)
        self.assertEqual(dims["sentiment"]["narrative"], "Sentiment: mixed.")
        self.assertEqual(dims["sentiment"]["citations"][0]["url"],
                         "https://reuters.example/x")

    def test_failed_run_reports_error(self):
        client = _client()

        def boom(code):
            raise RuntimeError("upstream exploded")

        with patch.object(tiered, "_run_analysis", boom):
            accepted = client.post("/tiered/analyze",
                                   json={"stock_code": "AAPL"})
            body = _poll_until_done(client, accepted.json()["task_id"])

        self.assertEqual(body["status"], "failed")
        self.assertIn("upstream exploded", body["error"])

    def test_blank_stock_code_rejected(self):
        client = _client()
        response = client.post("/tiered/analyze", json={"stock_code": "   "})
        self.assertEqual(response.status_code, 422)

    def test_unknown_task_is_404(self):
        client = _client()
        response = client.get("/tiered/tasks/nope")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
