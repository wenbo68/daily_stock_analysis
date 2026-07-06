# -*- coding: utf-8 -*-
"""Offline tests for the sentiment provider (slice 5).

Search, page fetch, and LLM are injected fakes. The citation-verification
rules (design doc §2.4) are the core under test: a citation survives only
if its source page was really fetched and its quote really appears there.
"""
from __future__ import annotations

import json
import unittest

from src.tiered_analysis.providers.base import Coverage, Market, SourceKind
from src.tiered_analysis.providers.sentiment import SearchHit, SentimentProvider

HITS = [
    SearchHit(title="Apple beats expectations", url="https://news.example/a"),
    SearchHit(title="iPhone demand cooling", url="https://blog.example/b"),
    SearchHit(title="Analyst upgrades AAPL", url="https://wire.example/c"),
]

PAGES = {
    "https://news.example/a": (
        "Apple reported quarterly revenue above analyst expectations, "
        "driven by strong services growth."
    ),
    "https://blog.example/b": (
        "Several suppliers report that iPhone demand is cooling in Asia "
        "heading into the second half."
    ),
    "https://wire.example/c": (
        "A major bank upgraded Apple to buy, citing resilient margins."
    ),
}


def _llm_json(citations, label="mixed", narrative="News flow is two-sided."):
    return json.dumps(
        {"narrative": narrative, "sentiment_label": label, "citations": citations}
    )


def _provider(searcher=None, fetcher=None, summarizer=None):
    return SentimentProvider(
        searcher=searcher or (lambda query: list(HITS)),
        fetcher=fetcher or (lambda url: PAGES.get(url, "")),
        summarizer=summarizer
        or (
            lambda prompt: _llm_json(
                [
                    {"source": 1, "quote": "revenue above analyst expectations"},
                    {"source": 2, "quote": "iPhone demand is cooling in Asia"},
                ]
            )
        ),
    )


class TestSentimentHappyPath(unittest.TestCase):
    def test_full_coverage_with_verified_citations(self):
        result = _provider().collect("AAPL")
        self.assertEqual(result.kind, SourceKind.TEXTUAL)
        self.assertEqual(result.coverage, Coverage.FULL)
        self.assertIn("mixed", result.narrative)
        self.assertIn("News flow is two-sided.", result.narrative)
        self.assertEqual(len(result.citations), 2)
        self.assertEqual(result.citations[0].url, "https://news.example/a")
        self.assertEqual(result.citations[1].url, "https://blog.example/b")

    def test_textual_is_never_actionable(self):
        # The sizing gate: TEXTUAL output must never feed numeric consumers.
        result = _provider().collect("AAPL")
        self.assertFalse(result.is_actionable)

    def test_quote_matching_ignores_case_and_whitespace(self):
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [{"source": 1, "quote": "Revenue   ABOVE analyst\nexpectations"}]
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.coverage, Coverage.FULL)

    def test_json_wrapped_in_code_fences_is_parsed(self):
        payload = _llm_json([{"source": 1, "quote": "strong services growth"}])
        summarizer = lambda prompt: f"```json\n{payload}\n```"  # noqa: E731
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.FULL)


class TestCitationVerification(unittest.TestCase):
    def test_fabricated_quote_is_dropped_with_warning(self):
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [
                {"source": 1, "quote": "strong services growth"},
                {"source": 2, "quote": "Apple is going bankrupt"},  # fabricated
            ]
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertEqual(len(result.citations), 1)
        self.assertTrue(any("quote not found" in w for w in result.warnings))

    def test_out_of_range_source_is_dropped(self):
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [
                {"source": 1, "quote": "strong services growth"},
                {"source": 99, "quote": "anything"},
            ]
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertEqual(len(result.citations), 1)
        self.assertTrue(any("invalid source index" in w for w in result.warnings))

    def test_zero_verified_citations_is_unavailable(self):
        # Narrative without one verifiable citation is untrustworthy.
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [{"source": 1, "quote": "totally made up claim"}]
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertIsNone(result.narrative)
        self.assertTrue(any("no verifiable citations" in w for w in result.warnings))


class TestFailureModes(unittest.TestCase):
    def test_search_failure_is_unavailable(self):
        def boom(query):
            raise RuntimeError("search provider down")

        result = _provider(searcher=boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertTrue(any("search provider down" in w for w in result.warnings))

    def test_no_search_results_is_unavailable(self):
        result = _provider(searcher=lambda query: []).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)

    def test_all_fetches_failing_is_unavailable(self):
        result = _provider(fetcher=lambda url: "").collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertTrue(any("no source pages" in w for w in result.warnings))

    def test_partial_fetch_failures_degrade_to_partial(self):
        pages = dict(PAGES)
        pages["https://blog.example/b"] = ""  # one page fails to fetch

        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [{"source": 1, "quote": "strong services growth"}]
        )
        result = _provider(
            fetcher=lambda url: pages.get(url, ""), summarizer=summarizer
        ).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertTrue(any("blog.example" in w for w in result.warnings))

    def test_llm_garbage_output_is_unavailable(self):
        result = _provider(summarizer=lambda prompt: "not json at all").collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertTrue(any("unparseable" in w for w in result.warnings))

    def test_llm_failure_is_unavailable(self):
        def boom(prompt):
            raise RuntimeError("LLM quota exhausted")

        result = _provider(summarizer=boom).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertTrue(any("LLM quota exhausted" in w for w in result.warnings))


class TestPromptContract(unittest.TestCase):
    def test_prompt_contains_only_fetched_sources(self):
        captured = {}

        def spy_summarizer(prompt):
            captured["prompt"] = prompt
            return _llm_json([{"source": 1, "quote": "strong services growth"}])

        pages = dict(PAGES)
        pages["https://blog.example/b"] = ""  # fails; must not reach the LLM
        _provider(
            fetcher=lambda url: pages.get(url, ""), summarizer=spy_summarizer
        ).collect("AAPL")
        self.assertIn("news.example/a", captured["prompt"])
        self.assertIn("wire.example/c", captured["prompt"])
        self.assertNotIn("blog.example/b", captured["prompt"])


class TestRegistryAndMarkets(unittest.TestCase):
    def test_supports_every_market(self):
        provider = _provider()
        for market in Market:
            self.assertTrue(provider.supports(market))

    def test_sentiment_routed_for_all_markets(self):
        from src.tiered_analysis.providers.registry import get_providers

        for market in (Market.US, Market.CN, Market.KR):
            dimensions = [p.dimension for p in get_providers(market)]
            self.assertIn("sentiment", dimensions)


if __name__ == "__main__":
    unittest.main()
