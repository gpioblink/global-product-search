from __future__ import annotations

import os

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery
from .base import BaseExtractor, ExtractorSelfTestCase


class RakutenBooksExtractor(BaseExtractor):
    name = "rakuten_books"
    genres = ("books-general",)
    flags = (
        "kind:barcode",
        "kind:keyword",
        "region:japan",
        "domain:books-general",
        "product:book",
        "channel:books-api",
    )
    endpoint = "https://openapi.rakuten.co.jp/services/api/BooksTotal/Search/20170404"
    _TESTS = [
        ExtractorSelfTestCase(
            name="keyword_search",
            query="genre:books-general Python",
            requires_env=("RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY"),
            expected_result={
                "source": "rakuten_books",
                "title": str,
                "url": "startswith:https://",
            },
        ),
        ExtractorSelfTestCase(
            name="isbn_search",
            query="genre:books-general 9784873115658",
            requires_env=("RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY"),
            expected_result={
                "source": "rakuten_books",
                "title": str,
                "url": "startswith:https://",
            },
        ),
    ]

    def supports(self, query: SearchQuery) -> int:
        if query.kind == "barcode":
            return 95
        if query.kind == "keyword":
            return 85
        return 0

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        app_id = os.getenv("RAKUTEN_APP_ID")
        access_key = os.getenv("RAKUTEN_ACCESS_KEY")
        if not app_id:
            raise RuntimeError("RAKUTEN_APP_ID is required for the rakuten_books extractor")
        if not access_key:
            raise RuntimeError("RAKUTEN_ACCESS_KEY is required for the rakuten_books extractor")

        params: dict[str, object] = {
            "applicationId": app_id,
            "accessKey": access_key,
            "hits": min(ctx.limit, 30),
            "page": 1,
            "format": "json",
            "formatVersion": 2,
            "availability": 1,
            "outOfStockFlag": 0,
            "field": 0,
            "orFlag": 0,
            "elements": ",".join(
                [
                    "title",
                    "author",
                    "publisherName",
                    "isbn",
                    "jan",
                    "itemCaption",
                    "salesDate",
                    "itemPrice",
                    "itemUrl",
                    "mediumImageUrl",
                    "booksGenreId",
                ]
            ),
        }
        if query.kind == "barcode":
            params["isbnjan"] = query.normalized[0]
        else:
            params["keyword"] = query.normalized[0]

        payload = self.download_json(
            ctx,
            self.endpoint,
            note="Downloading search API JSON",
            params=params,
        )

        items = payload.get("Items") or payload.get("items") or []
        candidates: list[ProductCandidate] = []
        for item in items:
            if "Item" in item:
                data = item["Item"]
            else:
                data = item
            if not isinstance(data, dict):
                continue

            price = None
            raw_price = data.get("itemPrice")
            if isinstance(raw_price, int):
                price = raw_price
            elif isinstance(raw_price, str) and raw_price.isdigit():
                price = int(raw_price)

            gtins: list[str] = []
            for key in ("isbn", "jan"):
                value = data.get(key)
                if isinstance(value, str) and value and value not in gtins:
                    gtins.append(value)

            publisher_name = data.get("publisherName")
            author = data.get("author")
            candidates.append(
                ProductCandidate(
                    source=self.name,
                    title=str(data.get("title") or ""),
                    url=str(data.get("itemUrl") or ""),
                    description=data.get("itemCaption") if isinstance(data.get("itemCaption"), str) else None,
                    price=price,
                    shop_name="Rakuten Books",
                    image_url=data.get("mediumImageUrl") if isinstance(data.get("mediumImageUrl"), str) else None,
                    brand=publisher_name if isinstance(publisher_name, str) else None,
                    model=author if isinstance(author, str) else None,
                    gtins=gtins,
                    raw_payload=data,
                )
            )

        return candidates
