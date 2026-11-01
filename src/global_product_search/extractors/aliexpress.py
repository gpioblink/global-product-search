from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
from urllib.parse import urlsplit

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery
from ._commerce import _CommerceExtractor, amount, object_list, product_url, required_env, text
from .base import ExtractorSelfTestCase


def _sign(params: dict[str, str], secret: str) -> str:
    canonical = "".join(key + value for key, value in sorted(params.items()) if key != "sign" and key and value)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.md5).hexdigest().upper()


class AliExpressExtractor(_CommerceExtractor):
    name = "aliexpress"
    genres = ("electronic-parts",)
    flags = ("kind:model", "kind:keyword", "domain:electronic-parts", "channel:official-api")
    endpoint = "https://eco.taobao.com/router/rest"
    _TESTS = [ExtractorSelfTestCase(
        name="keyword_search", query="source:aliexpress ESP32",
        requires_env=("ALIEXPRESS_APP_KEY", "ALIEXPRESS_APP_SECRET", "ALIEXPRESS_TRACKING_ID"),
        expected_result={"source": "aliexpress", "url": "startswith:https://"},
    )]

    def supports(self, query: SearchQuery) -> int:
        return 75 if query.kind in {"model", "keyword"} else 0

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        params = {
            "method": "aliexpress.affiliate.product.query",
            "app_key": required_env("ALIEXPRESS_APP_KEY", self.name),
            "tracking_id": required_env("ALIEXPRESS_TRACKING_ID", self.name),
            "format": "json", "v": "2.0", "sign_method": "hmac",
            "timestamp": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
            "keywords": query.raw, "page_no": "1", "page_size": str(min(ctx.limit, 50)),
            "target_currency": os.getenv("ALIEXPRESS_CURRENCY", "USD"),
            "target_language": os.getenv("ALIEXPRESS_LANGUAGE", "EN"),
            "ship_to_country": os.getenv("ALIEXPRESS_COUNTRY", "US"),
        }
        params["sign"] = _sign(params, required_env("ALIEXPRESS_APP_SECRET", self.name))
        payload = self.request_json(self.endpoint, data=params)
        if payload.get("error_response"):
            raise RuntimeError("aliexpress API reported an error; check app permissions, signing and quota")
        envelope = payload.get("aliexpress_affiliate_product_query_response")
        result = envelope.get("resp_result") if isinstance(envelope, dict) else None
        if not isinstance(result, dict) or str(result.get("resp_code")) != "200":
            raise RuntimeError("aliexpress API did not return a successful product query")
        result = result.get("result")
        if isinstance(result, dict) and result.get("total_record_count") == 0:
            return []
        products = result.get("products") if isinstance(result, dict) else None
        if not isinstance(products, dict):
            raise RuntimeError("aliexpress API returned an invalid product collection")
        candidates = []
        for item in object_list(products, "product", self.name)[:ctx.limit]:
            url = product_url(item.get("product_detail_url"), ("aliexpress.com",))
            title = text(item.get("product_title"))
            if not url or not title or not re.fullmatch(r"/item/\d+\.html", urlsplit(url).path):
                continue
            candidates.append(ProductCandidate(
                source=self.name, title=title, url=url, shop_name="AliExpress",
                image_url=text(item.get("product_main_image_url")),
                price=amount(item.get("target_sale_price")),
                currency=text(item.get("target_sale_price_currency")), raw_payload=item,
            ))
        return candidates
