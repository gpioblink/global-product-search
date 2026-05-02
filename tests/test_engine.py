from __future__ import annotations

from global_product_search.extractors.base import BaseExtractor
from global_product_search.engine import ExtractorWeightRule, SearchEngine, search
from global_product_search.models import ProductCandidate


def test_engine_returns_scored_results(monkeypatch) -> None:
    class FakeExtractor(BaseExtractor):
        name = "fake"

        def supports(self, query):
            return 100

        def search(self, query, ctx):
            return [
                ProductCandidate(
                    source=self.name,
                    title="SM-S928B Case",
                    url="https://example.com/1",
                    price=1200,
                    shop_name="A",
                    raw_payload={"itemCaption": "SM-S928B accessory"},
                ),
                ProductCandidate(
                    source=self.name,
                    title="Generic Phone Case",
                    url="https://example.com/2",
                    price=900,
                    shop_name="B",
                    raw_payload={"itemCaption": "fallback"},
                ),
            ]

    monkeypatch.setattr("global_product_search.engine.discover_extractors", lambda: [FakeExtractor()])
    engine = SearchEngine()

    results = engine.search_text("SM-S928B", limit=2)

    assert len(results) == 2
    assert results[0].score >= results[1].score
    assert results[0].title == "SM-S928B Case"


def test_library_search_returns_candidates(monkeypatch) -> None:
    from global_product_search import engine as engine_module

    original = engine_module.SearchEngine

    class TestSearchEngine(original):
        def __init__(self) -> None:
            super().__init__()

        def search_text(self, text: str, *, limit: int = 10):
            return [
                ProductCandidate(
                    source="example",
                    title="Nintendo Switch",
                    url="https://example.com/switch",
                    price=32000,
                )
            ]

    monkeypatch.setattr(engine_module, "SearchEngine", TestSearchEngine)
    results = search("Nintendo Switch")

    assert len(results) == 1
    assert results[0].title == "Nintendo Switch"
    results[0]


def test_engine_dedupes_candidates_by_url(monkeypatch) -> None:
    class FakeExtractor(BaseExtractor):
        name = "fake"

        def supports(self, query):
            return 100

        def search(self, query, ctx):
            return [
                ProductCandidate(
                    source=self.name,
                    title="Duplicate Product",
                    url="https://example.com/shared",
                ),
                ProductCandidate(
                    source=self.name,
                    title="Duplicate Product Second Copy",
                    url="https://example.com/shared",
                ),
            ]

    monkeypatch.setattr("global_product_search.engine.discover_extractors", lambda: [FakeExtractor()])
    engine = SearchEngine()

    results = engine.search_text("duplicate", limit=10)

    assert len([result for result in results if result.url == "https://example.com/shared"]) == 1


def test_engine_includes_multiple_sources_when_scores_are_high(monkeypatch) -> None:
    class PrimaryExtractor(BaseExtractor):
        name = "primary"

        def supports(self, query):
            return 100

        def search(self, query, ctx):
            return [
                ProductCandidate(
                    source=self.name,
                    title="SM-S928B Primary Top",
                    url="https://example.com/primary-top",
                ),
                ProductCandidate(
                    source=self.name,
                    title="SM-S928B Primary Second",
                    url="https://example.com/primary-second",
                ),
            ]

    class SecondaryExtractor(BaseExtractor):
        name = "secondary"

        def supports(self, query):
            return 99

        def search(self, query, ctx):
            return [
                ProductCandidate(
                    source=self.name,
                    title="SM-S928B Secondary Top",
                    url="https://example.com/secondary-top",
                )
            ]

    monkeypatch.setattr(
        "global_product_search.engine.discover_extractors",
        lambda: [PrimaryExtractor(), SecondaryExtractor()],
    )
    engine = SearchEngine(multi_source_score_threshold=110.0)

    results = engine.search_text("SM-S928B", limit=2)

    assert len(results) == 2
    assert {result.source for result in results} == {"primary", "secondary"}


def test_engine_applies_regex_weight_rules(monkeypatch) -> None:
    class GeneralExtractor(BaseExtractor):
        name = "general"

        def supports(self, query):
            return 80

        def search(self, query, ctx):
            return [
                ProductCandidate(
                    source=self.name,
                    title="9784873115658 General Result",
                    url="https://example.com/general",
                )
            ]

    class BookExtractor(BaseExtractor):
        name = "books"

        def supports(self, query):
            return 70

        def search(self, query, ctx):
            return [
                ProductCandidate(
                    source=self.name,
                    title="9784873115658 Book Result",
                    url="https://example.com/books",
                )
            ]

    monkeypatch.setattr(
        "global_product_search.engine.discover_extractors",
        lambda: [GeneralExtractor(), BookExtractor()],
    )
    engine = SearchEngine(
        weight_rules=[
            ExtractorWeightRule(
                name="prefer_book_sources_for_isbn",
                extractor_pattern=r"^books$",
                query_pattern=r"(?m)^isbn:(10|13)$",
                weight=20.0,
            )
        ]
    )

    results = engine.search_text("9784873115658", limit=2)

    assert len(results) == 2
    assert results[0].source == "books"
