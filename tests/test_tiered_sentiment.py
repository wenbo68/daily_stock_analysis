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

    def test_blocked_fetch_falls_back_to_search_extract(self):
        # News sites often block automated readers; the search provider's
        # own extract is still tool-fetched text we can verify quotes in.
        hits = [
            SearchHit(
                title="Reuters on Apple",
                url="https://reuters.example/x",
                snippet="Apple extended its chip partnership with Broadcom.",
            )
        ]
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [{"source": 1, "quote": "chip partnership with Broadcom"}]
        )
        result = _provider(
            searcher=lambda symbol: hits,
            fetcher=lambda url: "",  # every direct page fetch is blocked
            summarizer=summarizer,
        ).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.PARTIAL)
        self.assertEqual(len(result.citations), 1)
        self.assertTrue(any("search extract" in w for w in result.warnings))

    def test_fabricated_quote_still_dropped_against_search_extract(self):
        hits = [
            SearchHit(
                title="Reuters on Apple",
                url="https://reuters.example/x",
                snippet="Apple extended its chip partnership with Broadcom.",
            )
        ]
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [{"source": 1, "quote": "Apple is going bankrupt"}]
        )
        result = _provider(
            searcher=lambda symbol: hits,
            fetcher=lambda url: "",
            summarizer=summarizer,
        ).collect("AAPL")
        self.assertEqual(result.coverage, Coverage.UNAVAILABLE)
        self.assertEqual(len(result.citations or []), 0)

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


class TestInlineCitationsAndDedup(unittest.TestCase):
    """The narrative carries inline [n] markers and the reference list is
    deduplicated: one entry per source, numbered in order of first use, so
    the web page can show MLA-style inline citations without repeats."""

    def test_markers_renumbered_to_deduped_source_order(self):
        # LLM cites source 2 first, then source 1; the final reference list
        # follows that order, and the inline markers are rewritten to match.
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [
                {"source": 2, "quote": "iPhone demand is cooling in Asia"},
                {"source": 1, "quote": "revenue above analyst expectations"},
            ],
            narrative="Demand is cooling [2]. Revenue beat expectations [1].",
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertIn("cooling [1].", result.narrative)
        self.assertIn("expectations [2].", result.narrative)
        self.assertEqual(len(result.citations), 2)
        self.assertEqual(result.citations[0].url, "https://blog.example/b")
        self.assertEqual(result.citations[1].url, "https://news.example/a")

    def test_same_source_cited_twice_yields_one_reference(self):
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [
                {"source": 1, "quote": "strong services growth"},
                {"source": 1, "quote": "revenue above analyst expectations"},
            ],
            narrative="Services grew [1]. Revenue also beat [1].",
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].url, "https://news.example/a")
        self.assertIn("grew [1].", result.narrative)
        self.assertIn("beat [1].", result.narrative)

    def test_marker_for_dropped_citation_is_removed(self):
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [
                {"source": 1, "quote": "strong services growth"},
                {"source": 2, "quote": "Apple is going bankrupt"},  # fabricated
            ],
            narrative="Services grew [1]. Apple is going bankrupt [2].",
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertIn("[1]", result.narrative)
        self.assertNotIn("[2]", result.narrative)
        self.assertIn("bankrupt.", result.narrative)

    def test_marker_pointing_nowhere_is_removed(self):
        summarizer = lambda prompt: _llm_json(  # noqa: E731
            [{"source": 1, "quote": "strong services growth"}],
            narrative="Services grew [1]. Something big is coming [7].",
        )
        result = _provider(summarizer=summarizer).collect("AAPL")
        self.assertNotIn("[7]", result.narrative)
        self.assertIn("coming.", result.narrative)

    def test_prompt_asks_for_inline_markers(self):
        captured = {}

        def spy_summarizer(prompt):
            captured["prompt"] = prompt
            return _llm_json([{"source": 1, "quote": "strong services growth"}])

        _provider(summarizer=spy_summarizer).collect("AAPL")
        self.assertIn("marker", captured["prompt"].lower())


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


class TestDefaultSearchWiring(unittest.TestCase):
    """The default searcher must go through DSA's real SearchService API.

    Regression for the live-check failure: SearchService has no ``search``
    method; the supported entry point is the ``get_search_service()``
    singleton and its ``search_stock_news`` method.
    """

    def test_default_searcher_uses_search_stock_news(self):
        from unittest.mock import patch

        from src.search_service import SearchResponse, SearchResult
        from src.tiered_analysis.providers.sentiment import _default_searcher

        captured = {}

        class FakeService:
            def search_stock_news(self, stock_code, stock_name,
                                  max_results=5, focus_keywords=None):
                captured["stock_code"] = stock_code
                captured["max_results"] = max_results
                captured["focus_keywords"] = focus_keywords
                return SearchResponse(
                    query="q",
                    results=[
                        SearchResult(
                            title="Apple beats expectations",
                            snippet="search-provider extract text",
                            url="https://news.example/a",
                            source="news.example",
                        ),
                        SearchResult(title="", snippet="s", url="", source="x"),
                    ],
                    provider="Tavily",
                )

        with patch(
            "src.search_service.get_search_service", return_value=FakeService()
        ):
            hits = _default_searcher("AAPL")

        self.assertEqual(captured["stock_code"], "AAPL")
        self.assertEqual(captured["max_results"], 5)
        # Live check showed the service's own query beats a hand-built one.
        self.assertIsNone(captured["focus_keywords"])
        # Result without a URL is dropped; the good one is kept.
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://news.example/a")
        self.assertEqual(hits[0].title, "Apple beats expectations")
        # The search provider's extract rides along for fetch-blocked pages.
        self.assertEqual(hits[0].snippet, "search-provider extract text")

    def test_default_searcher_failed_response_returns_empty(self):
        from unittest.mock import patch

        from src.search_service import SearchResponse
        from src.tiered_analysis.providers.sentiment import _default_searcher

        class FakeService:
            def search_stock_news(self, stock_code, stock_name,
                                  max_results=5, focus_keywords=None):
                return SearchResponse(
                    query="q", results=[], provider="none",
                    success=False, error_message="no provider configured",
                )

        with patch(
            "src.search_service.get_search_service", return_value=FakeService()
        ):
            self.assertEqual(_default_searcher("AAPL"), [])


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
