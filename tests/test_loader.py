from __future__ import annotations

from global_product_search.loader import discover_extractors


def test_builtin_extractors_are_discoverable() -> None:
    extractors = discover_extractors()
    assert len(extractors) >= 1
