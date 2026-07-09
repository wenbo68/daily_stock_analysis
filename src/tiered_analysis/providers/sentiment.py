# -*- coding: utf-8 -*-
"""Sentiment provider (docs/tiered-analysis-design.md §2.4).

TEXTUAL: LLM + web search + **verified citations**, not hard-coded
scrapers. The anti-fabrication contract:

- The LLM never sees or emits URLs. It receives numbered excerpts from
  pages this code really fetched, and may only cite those numbers plus a
  verbatim quote.
- A citation survives only if its quote actually appears in the fetched
  page text (case/whitespace-insensitive). Fabricated quotes are dropped
  with a warning; zero surviving citations makes the whole result
  UNAVAILABLE — an uncited narrative is worthless for a product users
  trade on.
- ``is_actionable`` is False by construction (TEXTUAL): this output can
  never feed position sizing.

Honest caveat from the design doc: generic search surfaces news/blog
sentiment, not true retail-forum sentiment (Guba/Xueqiu/Naver are
login-walled). Good enough for v1; native retail sources are v5+.

Default wiring reuses DSA's existing pieces lazily: ``SearchService``
(multi-provider web search), ``fetch_url_content`` (page text), and
litellm with the repo's ``LITELLM_MODEL`` convention.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .base import (
    Citation,
    Coverage,
    DimensionProvider,
    DimensionResult,
    Market,
    SourceKind,
)

MAX_SOURCES = 5
_EXCERPT_CHARS = 1200

_PROMPT_TEMPLATE = """You are a financial news sentiment analyst.

Below are {count} numbered source excerpts about {symbol}, fetched today.
Using ONLY these sources, write a balanced sentiment summary.

Respond with STRICT JSON only, no other text:
{{
  "narrative": "<120-200 word summary of the news sentiment>",
  "sentiment_label": "<bullish | bearish | neutral | mixed>",
  "citations": [
    {{"source": <source number>, "quote": "<short verbatim quote copied exactly from that source>"}}
  ]
}}

Rules:
- Every claim in the narrative must be supported by at least one citation.
- Inside the narrative, put an inline marker like [1] or [2] right after each
  claim, using the same source numbers as your citations list.
- Quotes must be copied verbatim from the excerpts; do not paraphrase inside quotes.
- Cite only source numbers that exist above.

Sources:
{sources}
"""


class SentimentConfigError(RuntimeError):
    """Raised when the default LLM/search wiring is not configured."""


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    #: The search provider's own extract of the page (e.g. Tavily returns
    #: ~500 chars of real page text). Fallback source text when the site
    #: blocks our direct page fetch — still tool-fetched, so citation
    #: verification against it stays honest.
    snippet: str = ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


#: Inline citation marker as the LLM writes it, e.g. " [2]". The optional
#: leading whitespace is captured so a removed marker doesn't leave a
#: dangling space before the following period.
_MARKER_RE = re.compile(r"\s*\[(\d+)\]")


def _rewrite_markers(narrative: str, index_map: dict) -> str:
    """Renumber inline [n] markers to the deduplicated reference list.

    Markers whose source didn't survive citation verification (or never
    existed) are removed — an inline pointer to nothing would be worse
    than no pointer.
    """

    def _replace(match: "re.Match[str]") -> str:
        new_index = index_map.get(int(match.group(1)))
        return f" [{new_index}]" if new_index else ""

    rewritten = _MARKER_RE.sub(_replace, narrative)
    return re.sub(r"\s{2,}", " ", rewritten).strip()


def _parse_llm_json(raw: str) -> Optional[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _default_searcher(symbol: str) -> List[SearchHit]:
    """Search recent news via DSA's configured SearchService singleton.

    ``get_search_service()`` wires up whichever providers have keys in the
    env (Tavily/Brave/...); ``search_stock_news`` is its supported entry
    point. We let the service build its own query — the live check showed
    it beats a hand-built one (it knows the market's query conventions).
    """
    from src.search_service import get_search_service

    response = get_search_service().search_stock_news(
        stock_code=symbol,
        stock_name=symbol,
        max_results=MAX_SOURCES,
    )
    results = getattr(response, "results", None) or []
    return [
        SearchHit(
            title=str(r.title or r.url),
            url=str(r.url),
            snippet=str(getattr(r, "snippet", "") or ""),
        )
        for r in results
        if getattr(r, "url", None)
    ]


def _default_fetcher(url: str) -> str:
    from src.search_service import fetch_url_content

    return fetch_url_content(url)


def _default_summarizer(prompt: str) -> str:
    import os

    model = (os.getenv("LITELLM_MODEL") or "").strip()
    if not model:
        raise SentimentConfigError(
            "LITELLM_MODEL is not set; the sentiment provider needs the "
            "repo's standard LLM configuration"
        )
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


class SentimentProvider(DimensionProvider):
    """TEXTUAL news sentiment with tool-verified citations, any market."""

    dimension = "sentiment"
    kind = SourceKind.TEXTUAL

    def __init__(
        self,
        searcher: Callable[[str], List[SearchHit]] = _default_searcher,
        fetcher: Callable[[str], str] = _default_fetcher,
        summarizer: Callable[[str], str] = _default_summarizer,
    ) -> None:
        self._searcher = searcher
        self._fetcher = fetcher
        self._summarizer = summarizer

    def supports(self, market: Market) -> bool:
        return True

    def collect(self, symbol: str) -> DimensionResult:
        warnings: List[str] = []

        sources, search_warnings = self._gather_sources(symbol)
        warnings.extend(search_warnings)
        if not sources:
            return self._unavailable(warnings)

        raw = self._summarize(symbol, sources, warnings)
        if raw is None:
            return self._unavailable(warnings)

        parsed = _parse_llm_json(raw)
        if parsed is None or not str(parsed.get("narrative") or "").strip():
            warnings.append("LLM sentiment output unparseable or empty")
            return self._unavailable(warnings)

        citations, index_map = self._verify_citations(parsed, sources, warnings)
        if not citations:
            warnings.append("no verifiable citations survive — discarding narrative")
            return self._unavailable(warnings)

        label = str(parsed.get("sentiment_label") or "unlabeled").strip()
        body = _rewrite_markers(str(parsed["narrative"]).strip(), index_map)
        narrative = f"Sentiment: {label}. {body}"
        coverage = Coverage.FULL if not warnings else Coverage.PARTIAL
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            coverage=coverage,
            narrative=narrative,
            citations=citations,
            warnings=warnings,
        )

    def _unavailable(self, warnings: List[str]) -> DimensionResult:
        return DimensionResult(
            dimension=self.dimension,
            kind=self.kind,
            coverage=Coverage.UNAVAILABLE,
            warnings=warnings,
        )

    def _gather_sources(
        self, symbol: str
    ) -> Tuple[List[Tuple[SearchHit, str]], List[str]]:
        """Search, then fetch each hit; only really-fetched pages survive."""
        warnings: List[str] = []
        try:
            hits = self._searcher(symbol)
        except Exception as exc:
            return [], [f"sentiment search failed for {symbol}: {exc}"]
        if not hits:
            return [], [f"sentiment search returned no results for {symbol}"]

        sources: List[Tuple[SearchHit, str]] = []
        for hit in hits[:MAX_SOURCES]:
            try:
                text = self._fetcher(hit.url) or ""
            except Exception as exc:
                warnings.append(f"fetch failed for {hit.url}: {exc}")
                text = ""
            if text.strip():
                sources.append((hit, text.strip()))
            elif hit.snippet.strip():
                # Site blocked the direct fetch; the search provider's own
                # extract is shorter but still real tool-fetched page text.
                sources.append((hit, hit.snippet.strip()))
                warnings.append(
                    f"page fetch blocked for {hit.url}; "
                    "using shorter search extract instead"
                )
            else:
                warnings.append(f"fetch returned no content for {hit.url}")

        if not sources:
            warnings.append(f"no source pages could be fetched for {symbol}")
        return sources, warnings

    def _summarize(
        self,
        symbol: str,
        sources: List[Tuple[SearchHit, str]],
        warnings: List[str],
    ) -> Optional[str]:
        blocks = [
            f"[{index}] {hit.title} ({hit.url})\n{text[:_EXCERPT_CHARS]}"
            for index, (hit, text) in enumerate(sources, start=1)
        ]
        prompt = _PROMPT_TEMPLATE.format(
            count=len(sources), symbol=symbol, sources="\n\n".join(blocks)
        )
        try:
            return self._summarizer(prompt)
        except Exception as exc:
            warnings.append(f"sentiment LLM failed for {symbol}: {exc}")
            return None

    @staticmethod
    def _verify_citations(
        parsed: dict,
        sources: List[Tuple[SearchHit, str]],
        warnings: List[str],
    ) -> Tuple[List[Citation], dict]:
        """Verify quotes, then collapse to one reference per source.

        Returns the deduplicated citations (numbered in order of first
        verified use) plus a map from the LLM's source numbers to the final
        reference numbers, so inline [n] markers can be rewritten to match.
        """
        raw_citations = parsed.get("citations")
        if not isinstance(raw_citations, list):
            return [], {}

        first_quote: dict = {}  # source index -> first verified quote
        order: List[int] = []
        for entry in raw_citations:
            if not isinstance(entry, dict):
                continue
            index = entry.get("source")
            quote = str(entry.get("quote") or "").strip()
            if not isinstance(index, int) or not (1 <= index <= len(sources)):
                warnings.append(f"citation dropped: invalid source index {index!r}")
                continue
            hit, text = sources[index - 1]
            if not quote or _normalize(quote) not in _normalize(text):
                warnings.append(
                    f"citation dropped: quote not found in {hit.url}: {quote[:80]!r}"
                )
                continue
            if index not in first_quote:
                first_quote[index] = quote
                order.append(index)

        citations: List[Citation] = []
        index_map: dict = {}
        for new_index, source_index in enumerate(order, start=1):
            hit, _ = sources[source_index - 1]
            index_map[source_index] = new_index
            citations.append(
                Citation(
                    source_name=hit.title,
                    url=hit.url,
                    title=hit.title,
                    snippet=first_quote[source_index],
                )
            )
        return citations, index_map
