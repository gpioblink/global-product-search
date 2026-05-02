from __future__ import annotations

from dataclasses import dataclass
import logging
import re

from .context import SearchContext
from .loader import discover_extractors
from .models import ProductCandidate, SearchQuery
from .query import normalize_query

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractorWeightRule:
    name: str
    extractor_pattern: str
    query_pattern: str
    weight: float


DEFAULT_WEIGHT_RULES = [
    ExtractorWeightRule(
        name="prefer_japanese_marketplaces_for_japanese_barcodes",
        extractor_pattern=r"^rakuten$",
        query_pattern=r"(?m)^barcode:country:japan$",
        weight=20.0,
    ),
    ExtractorWeightRule(
        name="deprioritize_rakuten_for_non_japanese_barcodes",
        extractor_pattern=r"^rakuten$",
        query_pattern=r"(?m)^barcode:country:non-japan$",
        weight=-10.0,
    ),
    ExtractorWeightRule(
        name="prefer_book_focused_sources_for_isbn",
        extractor_pattern=r"^techbookfest$",
        query_pattern=r"(?m)^isbn:(10|13)$",
        weight=25.0,
    ),
]


class SearchEngine:
    def __init__(
        self,
        *,
        debug: bool = False,
        weight_rules: list[ExtractorWeightRule] | None = None,
        multi_source_score_threshold: float = 100.0,
    ) -> None:
        self.debug = debug
        self.weight_rules = weight_rules or DEFAULT_WEIGHT_RULES
        self.multi_source_score_threshold = multi_source_score_threshold

    def list_extractors(self) -> list[str]:
        return [extractor.name for extractor in discover_extractors()]

    def search_text(self, text: str, *, limit: int = 10) -> list[ProductCandidate]:
        query = normalize_query(text)
        return self.search_query(query, limit=limit)

    def search_query(self, query: SearchQuery, *, limit: int = 10) -> list[ProductCandidate]:
        ctx = SearchContext.from_env(limit=limit, debug=self.debug)
        available = discover_extractors()
        query_context = "\n".join(
            [
                f"raw:{query.raw}",
                f"kind:{query.kind}",
                *[f"normalized:{normalized}" for normalized in query.normalized],
                *query.signals,
            ]
        )
        # Ask every extractor how relevant it is for this query, then try the
        # highest-confidence ones first, including regex-based source boosts for
        # query traits such as ISBNs or regional barcode prefixes.
        selected = sorted(
            (
                (
                    extractor.supports(query)
                    + sum(
                        rule.weight
                        for rule in self.weight_rules
                        if re.search(rule.extractor_pattern, extractor.name)
                        and re.search(rule.query_pattern, query_context)
                    ),
                    extractor,
                )
                for extractor in available
            ),
            key=lambda item: item[0],
            reverse=True,
        )

        results: list[ProductCandidate] = []
        failures: list[RuntimeError] = []
        for support_score, extractor in selected:
            if support_score <= 0:
                continue
            try:
                extracted = extractor.search(query, ctx)
            except RuntimeError as exc:
                failures.append(exc)
                logger.warning("Extractor %s failed: %s", extractor.name, exc)
                continue
            except Exception as exc:
                logger.warning("Extractor %s failed: %s", extractor.name, exc)
                continue
            for index, candidate in enumerate(extracted):
                title = candidate.title.casefold()
                caption = ""
                item_caption = candidate.raw_payload.get("itemCaption")
                item_code = candidate.raw_payload.get("itemCode")
                if isinstance(item_caption, str):
                    caption = item_caption.casefold()
                if isinstance(item_code, str):
                    caption = f"{caption} {item_code.casefold()}".strip()

                # Start with the extractor-level support score, then reward
                # candidates whose title or payload text contains normalized
                # query tokens such as model numbers or barcodes.
                score = float(support_score)
                for normalized in query.normalized:
                    token = normalized.casefold()
                    if token and token in title:
                        score += 10.0
                    elif token and token in caption:
                        score += 6.0

                # Preserve some of the upstream ordering so earlier API results
                # stay ahead when textual signals are otherwise similar.
                score += max(0.0, 5.0 - (index * 0.2))
                results.append(candidate.model_copy(update={"score": score}))

        deduped: dict[str, ProductCandidate] = {}
        for candidate in results:
            normalized_url = candidate.url.strip().casefold()
            if normalized_url:
                # A stable product URL is the strongest duplicate key.
                key = f"url:{normalized_url}"
            else:
                # Fall back to a looser title+shop key when the source does not
                # expose a usable canonical URL.
                normalized_title = candidate.title.strip().casefold()
                normalized_shop = (candidate.shop_name or "").strip().casefold()
                key = f"title:{normalized_title}|shop:{normalized_shop}"

            current = deduped.get(key)
            if current is None or candidate.score > current.score:
                deduped[key] = candidate

        if not deduped and failures:
            raise failures[0]

        deduped_results = list(deduped.values())
        deduped_results.sort(key=lambda candidate: candidate.score, reverse=True)

        selected_results: list[ProductCandidate] = []
        selected_keys: set[str] = set()
        represented_sources: set[str] = set()
        for candidate in deduped_results:
            if candidate.score < self.multi_source_score_threshold:
                continue
            if candidate.source in represented_sources:
                continue
            candidate_key = candidate.url.strip().casefold() or (
                f"{candidate.title.strip().casefold()}|{(candidate.shop_name or '').strip().casefold()}"
            )
            selected_results.append(candidate)
            selected_keys.add(candidate_key)
            represented_sources.add(candidate.source)
            if len(selected_results) >= limit:
                return selected_results[:limit]

        for candidate in deduped_results:
            candidate_key = candidate.url.strip().casefold() or (
                f"{candidate.title.strip().casefold()}|{(candidate.shop_name or '').strip().casefold()}"
            )
            if candidate_key in selected_keys:
                continue
            selected_results.append(candidate)
            selected_keys.add(candidate_key)
            if len(selected_results) >= limit:
                break

        return selected_results[:limit]


def search(text: str, *, limit: int = 10) -> list[ProductCandidate]:
    engine = SearchEngine()
    return engine.search_text(text, limit=limit)
