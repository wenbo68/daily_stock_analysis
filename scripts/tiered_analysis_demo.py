# -*- coding: utf-8 -*-
"""Demo for the tiered-analysis v1 building blocks (pre-integration).

Runs the four dimension collectors on one symbol with your real .env keys
and prints what each gathered, with honest coverage labels. Technicals
shows "unavailable" until the price feed is wired in during integration.

Usage:
    .venv/bin/python scripts/tiered_analysis_demo.py AAPL
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from src.tiered_analysis.providers.registry import (  # noqa: E402
    detect_market,
    get_providers,
)

BAR = "=" * 62


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    market = detect_market(symbol)
    print(BAR)
    print(f"Tiered analysis v1 demo — {symbol} (market: {market.value})")
    print(BAR)

    for provider in get_providers(market):
        print(f"\n### Dimension: {provider.dimension} "
              f"[{provider.kind.value}] ###")
        try:
            result = provider.collect(symbol)
        except Exception as exc:  # demo must show failures, not die on them
            print(f"  crashed: {exc}")
            continue

        print(f"  coverage: {result.coverage.value}")
        print(f"  usable for trade numbers: {result.is_actionable}")

        if result.payload:
            for group, values in result.payload.items():
                print(f"  {group}: {values}")
        if result.narrative:
            print(f"  narrative: {result.narrative}")
        for citation in result.citations or []:
            print(f"  citation: {citation.url or citation.source_name}")
        for warning in result.warnings:
            print(f"  warning: {warning}")

    print(f"\n{BAR}")
    print("Note: technicals needs the price feed (integration step);")
    print("recommendation logging is exercised by the automated tests.")
    print(BAR)


if __name__ == "__main__":
    main()
