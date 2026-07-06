# -*- coding: utf-8 -*-
"""Offline tests for tiered-analysis market detection and provider routing.

detect_market must delegate to data_provider.base._market_tag (single source
of truth) rather than re-implementing symbol rules.
"""
from __future__ import annotations

import unittest

from src.tiered_analysis.providers.base import Market, SourceKind
from src.tiered_analysis.providers.registry import detect_market, get_providers


class TestDetectMarket(unittest.TestCase):
    def test_us_symbol(self):
        self.assertEqual(detect_market("AAPL"), Market.US)

    def test_cn_symbol(self):
        self.assertEqual(detect_market("600519"), Market.CN)

    def test_hk_symbol(self):
        self.assertEqual(detect_market("hk00700"), Market.HK)

    def test_unknown_falls_back_to_cn_like_market_tag(self):
        # _market_tag defaults to "cn"; we must mirror, not invent, semantics.
        self.assertEqual(detect_market("000001"), Market.CN)


class TestProviderRouting(unittest.TestCase):
    def test_technicals_registered_for_all_markets(self):
        for market in (Market.US, Market.CN, Market.HK, Market.JP, Market.KR, Market.TW):
            providers = get_providers(market)
            dimensions = [p.dimension for p in providers]
            self.assertIn("technicals", dimensions)

    def test_registered_providers_declare_kind(self):
        for provider in get_providers(Market.US):
            self.assertIn(provider.kind, (SourceKind.NUMERIC, SourceKind.TEXTUAL))


if __name__ == "__main__":
    unittest.main()
