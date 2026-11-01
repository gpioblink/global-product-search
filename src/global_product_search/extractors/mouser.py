from __future__ import annotations

import re

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery
from ._commerce import _CommerceExtractor, amount, object_list, required_env, text
from .base import ExtractorSelfTestCase


class MouserExtractor(_CommerceExtractor):
    name = "mouser"
    genres = ("electronic-parts",)
    flags = ("kind:model", "kind:keyword", "domain:electronic-parts", "channel:official-api")
    endpoint = "https://api.mouser.com/api/v1/search/keyword"
    _TESTS = [ExtractorSelfTestCase(
        name="keyword_search", query="source:mouser NE555", requires_env=("MOUSER_API_KEY",),
        expected_result={"source": "mouser", "url": "startswith:https://"},
    )]

    def supports(self, query: SearchQuery) -> int:
        return 95 if query.kind == "model" else 80 if query.kind == "keyword" else 0

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        payload = self.request_json(self.endpoint,
            params={"apiKey": required_env("MOUSER_API_KEY", self.name)},
            json={"SearchByKeywordRequest": {
                "keyword": query.raw, "records": min(ctx.limit, 50),
                "startingRecord": 0, "searchOptions": "None",
            }},
        )
        if payload.get("Errors"):
            raise RuntimeError("mouser API reported a search error; check account permissions and quota")
        result = payload.get("SearchResults")
        if not isinstance(result, dict):
            raise RuntimeError("mouser API returned invalid search results")
        if result.get("NumberOfResult") == 0:
            return []
        candidates = []
        for item in object_list(result, "Parts", self.name)[:ctx.limit]:
            # The API's ProductDetailUrl is the actual product page, never a
            # constructed store search URL. Regional Mouser domains are valid.
            url = text(item.get("ProductDetailUrl"))
            if not url or not re.match(r"^https://(?:[a-z0-9-]+\.)*mouser\.(?:[a-z]{2,3}|(?:co|com)\.[a-z]{2})/ProductDetail/", url, re.IGNORECASE):
                continue
            model = text(item.get("ManufacturerPartNumber"))
            title = model or text(item.get("Description"))
            if not title:
                continue
            breaks = item.get("PriceBreaks")
            breaks = [b for b in breaks if isinstance(b, dict)] if isinstance(breaks, list) else []
            breaks.sort(key=lambda b: amount(b.get("Quantity")) or float("inf"))
            first = breaks[0] if breaks else {}
            raw_price = text(first.get("Price")) or ""
            raw_price = re.sub(r"^[^\d]*|[^\d.]*$", "", raw_price)
            price = amount(raw_price) if "," not in raw_price or "." in raw_price else None
            candidates.append(ProductCandidate(
                source=self.name, title=title, url=url, shop_name="Mouser",
                description=text(item.get("Description")), model=model,
                brand=text(item.get("Manufacturer")), image_url=text(item.get("ImagePath")),
                price=price, currency=text(first.get("Currency")), raw_payload=item,
            ))
        return candidates
