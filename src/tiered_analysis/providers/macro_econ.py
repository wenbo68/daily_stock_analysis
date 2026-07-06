# -*- coding: utf-8 -*-
"""Macro-economic provider (docs/tiered-analysis-design.md §2.3a).

A US-centric shared background set from FRED — policy rate, Treasury
yields and curve spread, CPI inflation (as YoY), unemployment, VIX, oil,
broad dollar index. Valid context for every market, so the provider
supports all markets and its result is cached **once per region per day
and never fetched per ticker** (economic data is low-frequency and shared
by every symbol).

Requires a free FRED API key: set ``FRED_API_KEY`` (see .env.example).
Series IDs follow TradingAgents' curated list (dataflows/fred.py).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .base import (
    Citation,
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)

Observation = Tuple[str, float]  # (YYYY-MM-DD, value)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES_PAGE = "https://fred.stlouisfed.org/series/"
_FRED_TIMEOUT_SECONDS = 15
_LOOKBACK_DAYS = 460  # enough history for a 12-month YoY on monthly series

DEFAULT_CACHE_DIR = Path("data") / "tiered_analysis_cache"


class MacroConfigError(RuntimeError):
    """Raised when FRED is not configured (missing API key)."""


@dataclass(frozen=True)
class SeriesSpec:
    series_id: str
    group: str
    field: str
    transform: Optional[str] = None  # None = latest value; "yoy_pct" = YoY %


SERIES_SPECS: Tuple[SeriesSpec, ...] = (
    SeriesSpec("FEDFUNDS", "rates", "fed_funds_rate_pct"),
    SeriesSpec("DGS10", "rates", "treasury_10y_pct"),
    SeriesSpec("DGS2", "rates", "treasury_2y_pct"),
    SeriesSpec("T10Y2Y", "rates", "curve_10y_2y_pct"),
    SeriesSpec("CPIAUCSL", "inflation", "cpi_yoy_pct", transform="yoy_pct"),
    SeriesSpec("UNRATE", "labor", "unemployment_rate_pct"),
    SeriesSpec("VIXCLS", "markets", "vix"),
    SeriesSpec("DCOILWTICO", "markets", "wti_oil_usd"),
    SeriesSpec("DTWEXBGS", "markets", "dollar_index_broad"),
)


def cpi_yoy_pct(observations: List[Observation]) -> Optional[float]:
    """YoY percent change of a monthly index vs the same month last year."""
    if not observations:
        return None
    latest_date_str, latest_value = observations[-1]
    year, month = int(latest_date_str[:4]), int(latest_date_str[5:7])
    target = (year - 1, month)
    for date_str, value in observations:
        if (int(date_str[:4]), int(date_str[5:7])) == target:
            if value == 0:
                return None
            return (latest_value / value - 1.0) * 100.0
    return None


def _default_series_fetcher(series_id: str) -> List[Observation]:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise MacroConfigError(
            "FRED_API_KEY is not set; get a free key at fred.stlouisfed.org"
        )
    import requests

    start = (date.today() - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    response = requests.get(
        FRED_OBSERVATIONS_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
        },
        timeout=_FRED_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    observations: List[Observation] = []
    for row in response.json().get("observations", []):
        raw = row.get("value")
        if raw in (None, "", "."):  # FRED marks missing datapoints with "."
            continue
        try:
            observations.append((str(row.get("date")), float(raw)))
        except ValueError:
            continue
    return observations


class MacroEconProvider(DimensionProvider):
    """NUMERIC shared macro background, cached once per region per day."""

    dimension = "macro_econ"
    kind = SourceKind.NUMERIC
    region = "us"

    def __init__(
        self,
        series_fetcher: Callable[[str], List[Observation]] = _default_series_fetcher,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._series_fetcher = series_fetcher
        self._cache_dir = Path(cache_dir)
        self._today = today

    def supports(self, market: Market) -> bool:
        return True

    # The symbol is intentionally ignored: macro data is per-region.
    def collect(self, symbol: str) -> DimensionResult:
        cached = self._read_cache()
        if cached is not None:
            return cached

        payload, warnings = self._fetch_all()
        if payload is None:
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                coverage=Coverage.UNAVAILABLE,
                warnings=warnings,
            )

        coverage = Coverage.FULL if not warnings else Coverage.PARTIAL
        result = DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            coverage=coverage,
            payload=payload,
            citations=[self._citation()],
            warnings=warnings,
        )
        self._write_cache(result)
        return result

    def _citation(self) -> Citation:
        return Citation(
            source_name="FRED (Federal Reserve Economic Data)",
            url=FRED_SERIES_PAGE.rstrip("/"),
        )

    def _fetch_all(self) -> Tuple[Optional[Dict], List[str]]:
        groups: Dict[str, Dict[str, Optional[float]]] = {}
        observation_dates: Dict[str, Optional[str]] = {}
        warnings: List[str] = []
        got_any = False

        for spec in SERIES_SPECS:
            try:
                observations = self._series_fetcher(spec.series_id)
            except MacroConfigError as exc:
                # Not configured at all: one clear warning, no partial noise.
                return None, [str(exc)]
            except Exception as exc:
                warnings.append(f"FRED series {spec.series_id} failed: {exc}")
                observations = []

            value: Optional[float] = None
            latest_date: Optional[str] = None
            if observations:
                if spec.transform == "yoy_pct":
                    value = cpi_yoy_pct(observations)
                    if value is None:
                        warnings.append(
                            f"FRED series {spec.series_id}: no year-ago month "
                            "for YoY calculation"
                        )
                else:
                    value = observations[-1][1]
                latest_date = observations[-1][0]
            elif not warnings or spec.series_id not in warnings[-1]:
                warnings.append(f"FRED series {spec.series_id} returned no data")

            groups.setdefault(spec.group, {})[spec.field] = value
            observation_dates[spec.field] = latest_date
            got_any = got_any or value is not None

        if not got_any:
            return None, warnings

        payload = {
            "region": self.region,
            "as_of": self._today().isoformat(),
            **groups,
            "observation_dates": observation_dates,
        }
        return payload, warnings

    # ---- per-day cache ----

    def _cache_path(self) -> Path:
        return self._cache_dir / f"macro_econ_{self.region}_{self._today().isoformat()}.json"

    def _read_cache(self) -> Optional[DimensionResult]:
        path = self._cache_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return DimensionResult(
                dimension=self.dimension,
                kind=self.kind,
                coverage=Coverage(raw["coverage"]),
                payload=raw["payload"],
                citations=[self._citation()],
                warnings=list(raw.get("warnings", [])),
            )
        except FileNotFoundError:
            return None
        except Exception:
            return None  # corrupt cache: refetch, never fail on cache

    def _write_cache(self, result: DimensionResult) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path().write_text(
                json.dumps(
                    {
                        "coverage": result.coverage.value,
                        "payload": result.payload,
                        "warnings": result.warnings,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass  # a cold cache tomorrow is acceptable; failing the run is not
