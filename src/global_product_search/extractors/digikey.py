from __future__ import annotations

import hashlib
import os
import re
import threading
import time

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery
from ._commerce import _CommerceExtractor, amount, object_list, required_env, text
from .base import ExtractorSelfTestCase


class DigiKeyExtractor(_CommerceExtractor):
    name = "digikey"
    genres = ("electronic-parts",)
    flags = ("kind:model", "kind:keyword", "domain:electronic-parts", "channel:official-api")
    _tokens: dict[tuple[str, str, str], tuple[str, float]] = {}
    _token_lock = threading.Lock()
    _TESTS = [ExtractorSelfTestCase(
        name="keyword_search", query="source:digikey NE555",
        requires_env=("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET"),
        expected_result={"source": "digikey", "url": "startswith:https://"},
    )]

    def supports(self, query: SearchQuery) -> int:
        return 95 if query.kind == "model" else 80 if query.kind == "keyword" else 0

    def _access_token(self, host: str, client_id: str, secret: str) -> str:
        key = (host, client_id, hashlib.sha256(secret.encode()).hexdigest())
        with self._token_lock:
            cached = self._tokens.get(key)
            if cached and cached[1] > time.monotonic():
                return cached[0]
            payload = self.request_json(f"https://{host}/v1/oauth2/token", data={
                "client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
            })
            token = text(payload.get("access_token"))
            lifetime = payload.get("expires_in")
            if not token or not isinstance(lifetime, (int, float)) or lifetime <= 0:
                raise RuntimeError("digikey OAuth response did not contain a valid access token")
            self._tokens[key] = (token, time.monotonic() + max(0, lifetime - 30))
            return token

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        client_id = required_env("DIGIKEY_CLIENT_ID", self.name)
        secret = required_env("DIGIKEY_CLIENT_SECRET", self.name)
        sandbox = os.getenv("DIGIKEY_SANDBOX", "false").lower() == "true"
        host = "sandbox-api.digikey.com" if sandbox else "api.digikey.com"
        token = self._access_token(host, client_id, secret)
        currency = os.getenv("DIGIKEY_CURRENCY", "USD").upper()
        payload = self.request_json(f"https://{host}/products/v4/search/keyword", headers={
            "Authorization": f"Bearer {token}", "X-DIGIKEY-Client-Id": client_id,
            "X-DIGIKEY-Locale-Site": os.getenv("DIGIKEY_SITE", "US"),
            "X-DIGIKEY-Locale-Language": os.getenv("DIGIKEY_LANGUAGE", "en"),
            "X-DIGIKEY-Locale-Currency": currency,
        }, json={"Keywords": query.raw, "Limit": min(ctx.limit, 50), "Offset": 0})
        locale = payload.get("SearchLocaleUsed")
        if isinstance(locale, dict):
            currency = text(locale.get("Currency")) or currency
        candidates = []
        for item in object_list(payload, "Products", self.name)[:ctx.limit]:
            url = text(item.get("ProductUrl"))
            if not url or not re.match(r"^https://(?:[a-z0-9-]+\.)*digikey\.(?:[a-z]{2,3}|(?:co|com)\.[a-z]{2})/(?:[a-z]{2}/)?(?:products/detail/|product-detail/)", url):
                continue
            model = text(item.get("ManufacturerProductNumber"))
            description = item.get("Description")
            description = description if isinstance(description, dict) else {}
            title = model or text(description.get("ProductDescription"))
            if not url or not title:
                continue
            manufacturer = item.get("Manufacturer")
            candidates.append(ProductCandidate(
                source=self.name, title=title, url=url, shop_name="DigiKey",
                description=text(description.get("DetailedDescription")) or text(description.get("ProductDescription")),
                price=amount(item.get("UnitPrice")), currency=currency,
                image_url=text(item.get("PhotoUrl")), model=model,
                brand=text(manufacturer.get("Name")) if isinstance(manufacturer, dict) else None,
                raw_payload=item,
            ))
        return candidates
