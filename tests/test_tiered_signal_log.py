# -*- coding: utf-8 -*-
"""Offline tests for the tier-report signal log adapter (slice 6).

Slice 6 does NOT build a parallel recommendation log: DSA already has the
decision_signals table (+ outcome evaluation job that fetches the forward
price path). The adapter under test converts a TierReport into a valid
decision-signal payload and submits it via DecisionSignalService as a
client. Coverage badges ride in data_quality_summary, which the existing
web signals page already renders.

The end-to-end tests write through the REAL DecisionSignalService into an
isolated temp sqlite DB (repo's established fixture pattern) — that is
what verifies our payload satisfies the service's enum contracts.
"""
from __future__ import annotations

import json
import os

import pytest

from src.tiered_analysis.providers.base import (
    Citation,
    Coverage,
    DimensionResult,
    Market,
    SourceKind,
)
from src.tiered_analysis.schema import Direction, SniperLevels, TierReport
from src.tiered_analysis.signal_log import (
    SignalLogResult,
    build_signal_payload,
    coerce_confidence,
    log_tier_report,
)


def _dimension(name="technicals", kind=SourceKind.NUMERIC,
               coverage=Coverage.FULL, payload=None, citations=None):
    return DimensionResult(
        dimension=name,
        kind=kind,
        coverage=coverage,
        payload=payload if payload is not None else {"score": 62},
        citations=citations,
    )


def _report(**overrides):
    fields = dict(
        tier=1,
        symbol="AAPL",
        market=Market.US,
        coverage=Coverage.FULL,
        direction=Direction.BUY,
        confidence="0.72",
        score=83,
        levels=SniperLevels(
            entry=210.0, secondary_entry=205.5, stop_loss=198.0, take_profit=232.0
        ),
        narrative="Uptrend intact; buy pullbacks.",
        dimensions=[_dimension()],
        warnings=[],
    )
    fields.update(overrides)
    return TierReport(**fields)


class TestCoerceConfidence:
    def test_fraction_passes_through(self):
        assert coerce_confidence("0.72") == pytest.approx(0.72)
        assert coerce_confidence(0.5) == pytest.approx(0.5)

    def test_percent_scale_is_normalized(self):
        assert coerce_confidence(83) == pytest.approx(0.83)
        assert coerce_confidence("100") == pytest.approx(1.0)

    def test_text_and_out_of_range_become_none(self):
        assert coerce_confidence("高") is None
        assert coerce_confidence(None) is None
        assert coerce_confidence(-3) is None
        assert coerce_confidence(250) is None


class TestBuildSignalPayload:
    def test_happy_path_mapping(self):
        payload, skip = build_signal_payload(_report(), trace_id="trace-1")
        assert skip is None
        assert payload["stock_code"] == "AAPL"
        assert payload["market"] == "us"
        assert payload["source_type"] == "agent"
        assert payload["source_agent"] == "tiered_analysis"
        assert payload["trigger_source"] == "tiered_analysis"
        assert payload["trace_id"] == "trace-1"
        assert payload["action"] == "buy"
        assert payload["confidence"] == pytest.approx(0.72)
        assert payload["score"] == 83
        # entry_low/high are the sorted pair of the two entry levels
        assert payload["entry_low"] == pytest.approx(205.5)
        assert payload["entry_high"] == pytest.approx(210.0)
        assert payload["stop_loss"] == pytest.approx(198.0)
        assert payload["target_price"] == pytest.approx(232.0)
        assert payload["reason"] == "Uptrend intact; buy pullbacks."
        assert payload["metadata"]["tier"] == 1
        assert payload["metadata"]["sizing_empty"] is True

    def test_coverage_maps_to_known_quality_levels(self):
        # The repo's quality normalizer does not know the word "full" —
        # translate explicitly so badges never collapse to "unknown".
        for coverage, expected in (
            (Coverage.FULL, "high"),
            (Coverage.PARTIAL, "low"),
            (Coverage.UNAVAILABLE, "poor"),
        ):
            payload, _ = build_signal_payload(_report(coverage=coverage))
            assert payload["data_quality_summary"]["level"] == expected
            assert payload["data_quality_summary"]["coverage"] == coverage.value

    def test_per_dimension_coverage_badges(self):
        report = _report(dimensions=[
            _dimension("technicals", coverage=Coverage.FULL),
            _dimension("fundamentals", coverage=Coverage.PARTIAL),
            _dimension("sentiment", kind=SourceKind.TEXTUAL,
                       coverage=Coverage.UNAVAILABLE, payload=None),
        ])
        payload, _ = build_signal_payload(report)
        badges = payload["data_quality_summary"]["dimensions"]
        assert badges == {
            "technicals": "full",
            "fundamentals": "partial",
            "sentiment": "unavailable",
        }

    def test_sentiment_citations_land_in_evidence(self):
        citation = Citation(
            source_name="Reuters", url="https://reuters.example/x",
            title="Reuters", snippet="quote",
        )
        report = _report(dimensions=[
            _dimension("sentiment", kind=SourceKind.TEXTUAL,
                       coverage=Coverage.FULL, payload=None,
                       citations=[citation]),
        ])
        payload, _ = build_signal_payload(report)
        entries = payload["evidence"]["dimensions"]
        assert entries[0]["dimension"] == "sentiment"
        assert entries[0]["citations"] == ["https://reuters.example/x"]
        # TEXTUAL never feeds sizing; the flag must survive into evidence.
        assert entries[0]["is_actionable"] is False

    def test_dimension_payloads_and_narrative_land_in_evidence(self):
        # The web signal detail must show the full four-dimension reports,
        # not just coverage badges.
        citation = Citation(
            source_name="Reuters", url="https://reuters.example/x",
            title="Reuters", snippet="quote",
        )
        report = _report(dimensions=[
            _dimension("fundamentals", payload={"growth": {"revenue_yoy_pct": 6.4}}),
            DimensionResult(
                dimension="sentiment", kind=SourceKind.TEXTUAL,
                coverage=Coverage.PARTIAL,
                narrative="Sentiment: mixed. Two-sided news flow.",
                citations=[citation],
                warnings=["one page blocked"],
            ),
        ])
        payload, _ = build_signal_payload(report)
        entries = {e["dimension"]: e for e in payload["evidence"]["dimensions"]}
        assert entries["fundamentals"]["payload"] == {
            "growth": {"revenue_yoy_pct": 6.4}
        }
        assert "payload" not in entries["sentiment"]  # textual has none
        assert entries["sentiment"]["narrative"].startswith("Sentiment: mixed")
        assert entries["sentiment"]["warnings"] == ["one page blocked"]

    def test_urlless_citation_falls_back_to_source_name(self):
        # Numeric sources (e.g. price bars) cite a source name, not a URL —
        # evidence must never contain a bare null.
        citation = Citation(source_name="ohlcv-bars")
        report = _report(dimensions=[
            _dimension("technicals", citations=[citation]),
        ])
        payload, _ = build_signal_payload(report)
        assert payload["evidence"]["dimensions"][0]["citations"] == ["ohlcv-bars"]

    def test_warnings_are_capped(self):
        report = _report(warnings=[f"warning {i}" for i in range(50)])
        payload, _ = build_signal_payload(report)
        assert len(payload["data_quality_summary"]["warnings"]) == 20

    def test_unknown_direction_is_skipped(self):
        payload, skip = build_signal_payload(_report(direction=Direction.UNKNOWN))
        assert payload is None
        assert "direction" in skip

    def test_unknown_market_is_skipped(self):
        payload, skip = build_signal_payload(_report(market=Market.UNKNOWN))
        assert payload is None
        assert "market" in skip

    def test_missing_levels_stay_none(self):
        payload, skip = build_signal_payload(_report(levels=SniperLevels()))
        assert skip is None
        assert payload["entry_low"] is None
        assert payload["entry_high"] is None
        assert payload["stop_loss"] is None
        assert payload["target_price"] is None


class TestLogTierReport:
    def test_logs_via_injected_service(self):
        captured = {}

        class FakeService:
            def create_signal(self, payload):
                captured.update(payload)
                return {"item": {"id": 42}, "created": True}

        result = log_tier_report(_report(), service=FakeService())
        assert isinstance(result, SignalLogResult)
        assert result.logged is True
        assert result.signal_id == 42
        assert result.created is True
        assert captured["stock_code"] == "AAPL"

    def test_skip_reports_are_not_sent(self):
        class ExplodingService:
            def create_signal(self, payload):
                raise AssertionError("must not be called")

        result = log_tier_report(
            _report(direction=Direction.UNKNOWN), service=ExplodingService()
        )
        assert result.logged is False
        assert "direction" in result.reason

    def test_service_failure_never_raises(self):
        class BrokenService:
            def create_signal(self, payload):
                raise RuntimeError("db locked")

        result = log_tier_report(_report(), service=BrokenService())
        assert result.logged is False
        assert "db locked" in result.reason


@pytest.fixture()
def isolated_db(tmp_path):
    """Repo-standard isolated sqlite DB (see tests/test_decision_signal_service.py)."""
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "tiered_signal_log.db"
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


class TestEndToEndWithRealService:
    def test_payload_satisfies_real_service_contract(self, isolated_db):
        from sqlalchemy import select

        from src.storage import DecisionSignalRecord

        result = log_tier_report(_report(), trace_id="tier-e2e-1")
        assert result.logged is True, result.reason
        assert result.created is True

        with isolated_db.get_session() as session:
            row = session.execute(select(DecisionSignalRecord)).scalars().one()
        assert row.stock_code == "AAPL"
        assert row.market == "us"
        assert row.source_type == "agent"
        assert row.source_agent == "tiered_analysis"
        assert row.action == "buy"
        assert row.status == "active"  # outcome job picks up active signals
        assert row.entry_low == pytest.approx(205.5)
        assert row.target_price == pytest.approx(232.0)
        quality = json.loads(row.data_quality_summary_json)
        assert quality["level"] == "high"
        assert quality["dimensions"]["technicals"] == "full"

    def test_same_report_twice_is_not_duplicated(self, isolated_db):
        first = log_tier_report(_report(), trace_id="tier-dup-1")
        second = log_tier_report(_report(), trace_id="tier-dup-1")
        assert first.logged is True and first.created is True
        assert second.logged is True
        assert second.created is False  # existing signal reused, no dup row
