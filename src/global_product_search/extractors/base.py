from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import re
import time
from typing import Any
from typing import Protocol, runtime_checkable

import httpx

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery

logger = logging.getLogger(__name__)


@runtime_checkable
class Extractor(Protocol):
    name: str

    def supports(self, query: SearchQuery) -> int:
        ...

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        ...


@dataclass(frozen=True, slots=True)
class ExtractorSelfTestCase:
    name: str
    query: str
    skip: str | None = None
    requires_env: tuple[str, ...] = field(default_factory=tuple)
    min_results: int = 1
    expected_result: dict[str, Any] = field(default_factory=dict)


class BaseExtractor(ABC):
    name: str
    _TESTS: list[ExtractorSelfTestCase] = []

    def download_json(
        self,
        ctx: SearchContext,
        url: str,
        *,
        note: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: Any = None,
        method: str = "GET",
    ) -> dict[str, Any]:
        logger.info("[%s] %s", self.name, note)
        if ctx.debug:
            logger.debug("[%s] %s %s", self.name, method.upper(), url)

        client = httpx.Client()
        try:
            for attempt in range(3):
                response = client.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    headers=headers,
                    data=data,
                    timeout=10.0,
                )
                if response.status_code == 429 and attempt < 2:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        time.sleep(float(retry_after))
                        continue

                    match = re.search(r"Try again in (\d+) seconds", response.text)
                    if match:
                        time.sleep(float(match.group(1)))
                        continue

                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError(f"{self.name} API returned a non-object JSON payload")
                return payload
            raise RuntimeError(f"{self.name} API request failed after repeated retries")
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            raise RuntimeError(f"{self.name} API request failed: {detail}") from exc
        finally:
            client.close()

    @abstractmethod
    def supports(self, query: SearchQuery) -> int:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        raise NotImplementedError
