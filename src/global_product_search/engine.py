from __future__ import annotations

from dataclasses import dataclass
import logging
import re

from .context import SearchContext
from .extractors.base import Extractor
from .loader import discover_extractors
from .models import ProductCandidate, SearchQuery
from .query import InvalidQueryError, normalize_query

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractorWeightRule:
    name: str
    extractor_flag_pattern: str
    query_pattern: str
    weight: float


@dataclass(frozen=True, slots=True)
class ExtractorInfo:
    name: str
    genres: tuple[str, ...]
    flags: tuple[str, ...]


DEFAULT_WEIGHT_RULES = [
    ExtractorWeightRule(
        name="prefer_barcode_capable_extractors_for_barcode_queries",
        extractor_flag_pattern=r"^kind:barcode$",
        query_pattern=r"(?m)^kind:barcode$",
        weight=25.0,
    ),
    ExtractorWeightRule(
        name="prefer_model_capable_extractors_for_model_queries",
        extractor_flag_pattern=r"^kind:model$",
        query_pattern=r"(?m)^kind:model$",
        weight=20.0,
    ),
    ExtractorWeightRule(
        name="prefer_keyword_capable_extractors_for_keyword_queries",
        extractor_flag_pattern=r"^kind:keyword$",
        query_pattern=r"(?m)^kind:keyword$",
        weight=15.0,
    ),
    ExtractorWeightRule(
        name="prefer_japanese_sources_for_japanese_barcodes",
        extractor_flag_pattern=r"^region:japan$",
        query_pattern=r"(?m)^barcode:country:japan$",
        weight=20.0,
    ),
    ExtractorWeightRule(
        name="deprioritize_japanese_sources_for_non_japanese_barcodes",
        extractor_flag_pattern=r"^region:japan$",
        query_pattern=r"(?m)^barcode:country:non-japan$",
        weight=-10.0,
    ),
    ExtractorWeightRule(
        name="prefer_general_store_sources_when_requested",
        extractor_flag_pattern=r"^domain:general-store$",
        query_pattern=r"(?m)^genre:generic$",
        weight=25.0,
    ),
    ExtractorWeightRule(
        name="prefer_general_book_sources_when_requested",
        extractor_flag_pattern=r"^domain:books-general$",
        query_pattern=r"(?m)^genre:books-general$",
        weight=15.0,
    ),
    ExtractorWeightRule(
        name="prefer_specialized_books_api_for_book_queries",
        extractor_flag_pattern=r"^channel:books-api$",
        query_pattern=r"(?m)^(genre:books-general|isbn:(10|13)|product:book)$",
        weight=20.0,
    ),
    ExtractorWeightRule(
        name="prefer_doujin_technical_book_sources_when_requested",
        extractor_flag_pattern=r"^domain:books-doujin-technical$",
        query_pattern=r"(?m)^genre:books-doujin-technical$",
        weight=25.0,
    ),
    ExtractorWeightRule(
        name="prefer_book_sources_for_book_queries",
        extractor_flag_pattern=r"^product:book$",
        query_pattern=r"(?m)^(isbn:(10|13)|product:book)$",
        weight=20.0,
    ),
    ExtractorWeightRule(
        name="deprioritize_general_store_for_doujin_technical_book_queries",
        extractor_flag_pattern=r"^domain:general-store$",
        query_pattern=r"(?m)^genre:books-doujin-technical$",
        weight=-5.0,
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

    def list_extractor_infos(self) -> list[ExtractorInfo]:
        return [
            ExtractorInfo(
                name=extractor.name,
                genres=getattr(extractor, "genres", ()),
                flags=getattr(extractor, "flags", ()),
            )
            for extractor in discover_extractors()
        ]

    def search_text(self, text: str, *, limit: int = 10) -> list[ProductCandidate]:
        query = normalize_query(text)
        return self.search_query(query, limit=limit)

    def search_query(self, query: SearchQuery, *, limit: int = 10) -> list[ProductCandidate]:
        ctx = SearchContext.from_env(limit=limit, debug=self.debug)
        requested_genres = set(query.preferred_genres)
        discovered = discover_extractors()
        if query.requested_sources:
            known_sources = {extractor.name for extractor in discovered}
            unknown = sorted(set(query.requested_sources) - known_sources)
            if unknown:
                raise InvalidQueryError(f"Unknown source(s): {', '.join(unknown)}")
            # Explicit source selection takes precedence over genre routing.
            # Filter before supports() or search() can contact any upstream.
            available = [e for e in discovered if e.name in query.requested_sources]
        else:
            available = [
                e for e in discovered
                if not getattr(e, "genres", ()) or requested_genres.intersection(e.genres)
            ]
        query_context = "\n".join(
            [
                f"raw:{query.raw}",
                f"kind:{query.kind}",
                *[f"normalized:{normalized}" for normalized in query.normalized],
                *query.signals,
            ]
        )
        # Ask every extractor how relevant it is for this query, then try the
        # highest-confidence ones first, including regex-based boosts derived
        # from extractor flags such as kind, region, and product domain.
        selected: list[tuple[float, Extractor]] = []
        for extractor in available:
            base_score = extractor.supports(query)
            matched_rules = [
                rule
                for rule in self.weight_rules
                if re.search(rule.query_pattern, query_context)
                and any(
                    re.search(rule.extractor_flag_pattern, flag)
                    for flag in getattr(extractor, "flags", ())
                )
            ]
            total_score = base_score + sum(rule.weight for rule in matched_rules)
            selected.append((total_score, extractor))
            if ctx.debug:
                logger.debug(
                    "[engine] extractor=%s base=%.1f weights=%s total=%.1f",
                    extractor.name,
                    float(base_score),
                    ", ".join(f"{rule.name}:{rule.weight:+.1f}" for rule in matched_rules) or "-",
                    float(total_score),
                )
        selected.sort(key=lambda item: item[0], reverse=True)

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
                if query.requested_sources and candidate.source not in query.requested_sources:
                    continue
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
