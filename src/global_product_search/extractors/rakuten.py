from __future__ import annotations

import os

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery
from .base import BaseExtractor, ExtractorSelfTestCase


class RakutenExtractor(BaseExtractor):
    name = "rakuten"
    endpoint = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
    _TESTS = [
        ExtractorSelfTestCase(
            name="keyword_search",
            query="Nintendo Switch",
            requires_env=("RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY"),
            expected_result={
                "source": "rakuten",
                "title": str,
                "url": "startswith:https://",
            },
        ),
        ExtractorSelfTestCase(
            name="model_search",
            query="SM-S928B",
            requires_env=("RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY"),
            expected_result={
                "source": "rakuten",
                "title": str,
                "url": "startswith:https://",
            },
        ),
    ]

    def supports(self, query: SearchQuery) -> int:
        if query.kind == "barcode":
            return 100
        if query.kind == "model":
            return 90
        return 80

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        app_id = os.getenv("RAKUTEN_APP_ID")
        access_key = os.getenv("RAKUTEN_ACCESS_KEY")
        if not app_id:
            raise RuntimeError("RAKUTEN_APP_ID is required for the rakuten extractor")
        if not access_key:
            raise RuntimeError("RAKUTEN_ACCESS_KEY is required for the rakuten extractor")

        keyword = query.normalized[0]
        params = {
            "applicationId": app_id,
            "accessKey": access_key,
            "keyword": keyword,
            "hits": min(ctx.limit, 30),
            "page": 1,
            "format": "json",
            "formatVersion": 2,
            "availability": 1,
            "field": 0,
            "imageFlag": 1,
            "elements": ",".join(
                [
                    "itemName",
                    "itemPrice",
                    "itemUrl",
                    "shopName",
                    "mediumImageUrls",
                    "itemCaption",
                    "itemCode",
                ]
            ),
        }
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

            image_url = None
            medium_image_urls = data.get("mediumImageUrls")
            if isinstance(medium_image_urls, list) and medium_image_urls:
                first = medium_image_urls[0]
                if isinstance(first, str):
                    image_url = first
                elif isinstance(first, dict):
                    raw_image_url = first.get("imageUrl")
                    if isinstance(raw_image_url, str):
                        image_url = raw_image_url

            price = None
            raw_price = data.get("itemPrice")
            if isinstance(raw_price, int):
                price = raw_price
            elif isinstance(raw_price, str) and raw_price.isdigit():
                price = int(raw_price)

            shop_name = data.get("shopName") if isinstance(data.get("shopName"), str) else None
            candidates.append(
                ProductCandidate(
                    source=self.name,
                    title=str(data.get("itemName") or ""),
                    url=str(data.get("itemUrl") or ""),
                    description=data.get("itemCaption") if isinstance(data.get("itemCaption"), str) else None,
                    price=price,
                    shop_name=shop_name,
                    image_url=image_url,
                    raw_payload=data,
                )
            )

        return candidates
