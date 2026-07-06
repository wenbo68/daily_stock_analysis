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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


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


def _default_searcher(query: str) -> List[SearchHit]:
    from src.search_service import SearchService

    response = SearchService().search(query, max_results=MAX_SOURCES)
    results = getattr(response, "results", None) or []
    return [
        SearchHit(title=str(r.title or r.url), url=str(r.url))
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

        citations = self._verify_citations(parsed, sources, warnings)
        if not citations:
            warnings.append("no verifiable citations survive — discarding narrative")
            return self._unavailable(warnings)

        label = str(parsed.get("sentiment_label") or "unlabeled").strip()
        narrative = f"Sentiment: {label}. {str(parsed['narrative']).strip()}"
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
            hits = self._searcher(f"{symbol} stock latest news and analyst sentiment")
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
                continue
            if text.strip():
                sources.append((hit, text.strip()))
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
    ) -> List[Citation]:
        citations: List[Citation] = []
        raw_citations = parsed.get("citations")
        if not isinstance(raw_citations, list):
            return citations

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
            citations.append(
                Citation(
                    source_name=hit.title,
                    url=hit.url,
                    title=hit.title,
                    snippet=quote,
                )
            )
        return citations
