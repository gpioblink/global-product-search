from __future__ import annotations

import os
from dataclasses import dataclass
import re
from typing import cast

import pytest

from global_product_search.context import SearchContext
from global_product_search.extractors.base import BaseExtractor, ExtractorSelfTestCase
from global_product_search.loader import discover_extractors
from global_product_search.query import normalize_query


@dataclass(frozen=True, slots=True)
class ExtractorCase:
    extractor: BaseExtractor
    case: ExtractorSelfTestCase


def _iter_extractor_cases() -> list[ExtractorCase]:
    cases: list[ExtractorCase] = []
    for extractor in discover_extractors():
        base_extractor = cast(BaseExtractor, extractor)
        for case in base_extractor._TESTS:
            cases.append(ExtractorCase(extractor=base_extractor, case=case))
    return cases


@pytest.mark.parametrize(
    ("extractor_case"),
    _iter_extractor_cases(),
    ids=lambda extractor_case: f"{extractor_case.extractor.name}:{extractor_case.case.name}",
)
@pytest.mark.skipif(os.getenv("GPS_RUN_LIVE_TESTS") != "1", reason="set GPS_RUN_LIVE_TESTS=1 for upstream smoke tests")
def test_builtin_extractor_test_case(extractor_case: ExtractorCase) -> None:
    extractor = extractor_case.extractor
    case = extractor_case.case

    if case.skip:
        pytest.skip(case.skip)
    missing_env = [key for key in case.requires_env if not os.getenv(key)]
    if missing_env:
        pytest.skip(f"missing required environment variables: {', '.join(missing_env)}")

    results = extractor.search(normalize_query(case.query), SearchContext(limit=10))

    assert len(results) >= case.min_results
    first_result = results[0].model_dump()
    for field_name, expected_value in case.expected_result.items():
        actual_value = first_result[field_name]
        if isinstance(expected_value, type):
            assert isinstance(actual_value, expected_value)
        elif isinstance(expected_value, str) and expected_value.startswith("startswith:"):
            assert isinstance(actual_value, str)
            assert actual_value.startswith(expected_value.removeprefix("startswith:"))
        elif isinstance(expected_value, str) and expected_value.startswith("re:"):
            assert isinstance(actual_value, str)
            assert re.match(expected_value.removeprefix("re:"), actual_value)
        else:
            assert actual_value == expected_value
