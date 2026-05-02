from __future__ import annotations

import logging

from .context import SearchContext
from .loader import discover_extractors
from .models import ProductCandidate, SearchQuery
from .query import normalize_query

logger = logging.getLogger(__name__)


class SearchEngine:
    def __init__(
        self,
        *,
        debug: bool = False,
    ) -> None:
        self.debug = debug

    def list_extractors(self) -> list[str]:
        return [extractor.name for extractor in discover_extractors()]

    def search_text(self, text: str, *, limit: int = 10) -> list[ProductCandidate]:
        query = normalize_query(text)
        return self.search_query(query, limit=limit)

    def search_query(self, query: SearchQuery, *, limit: int = 10) -> list[ProductCandidate]:
        ctx = SearchContext.from_env(limit=limit, debug=self.debug)
        available = discover_extractors()
        # Ask every extractor how relevant it is for this query, then try the
        # highest-confidence ones first.
        selected = sorted(
            ((extractor.supports(query), extractor) for extractor in available),
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
        return deduped_results[:limit]


def search(text: str, *, limit: int = 10) -> list[ProductCandidate]:
    engine = SearchEngine()
    return engine.search_text(text, limit=limit)
