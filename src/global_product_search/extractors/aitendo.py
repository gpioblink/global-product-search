from __future__ import annotations

import re
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup, Tag
import httpx

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery
from ._commerce import amount, product_url
from .base import BaseExtractor, ExtractorSelfTestCase


class AitendoExtractor(BaseExtractor):
    name = "aitendo"
    genres = ("electronic-parts",)
    flags = ("kind:model", "kind:keyword", "region:japan", "domain:electronic-parts", "channel:public-html")
    origin = "https://www.aitendo.com"
    endpoint = origin + "/product-list"
    user_agent = "global-product-search/0.1"
    _TESTS = [ExtractorSelfTestCase(
        name="keyword_search", query="source:aitendo ESP32",
        expected_result={"source": "aitendo", "url": "startswith:https://www.aitendo.com/product/"},
    )]

    def supports(self, query: SearchQuery) -> int:
        return 90 if query.kind == "model" else 75 if query.kind == "keyword" else 0

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        try:
            with httpx.Client(headers={"User-Agent": self.user_agent}, timeout=10.0) as client:
                robots = client.get(self.origin + "/robots.txt")
                if robots.status_code != 404:
                    robots.raise_for_status()
                    policy = RobotFileParser()
                    policy.parse(robots.text.splitlines())
                    if not policy.can_fetch(self.user_agent, self.endpoint):
                        raise RuntimeError("aitendo robots.txt does not allow product search")
                response = client.get(self.endpoint, params={"keyword": query.raw})
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"aitendo public search failed (HTTP {exc.response.status_code})") from None
        except httpx.RequestError as exc:
            raise RuntimeError(f"aitendo public search failed ({type(exc).__name__})") from None
        return self._parse_results(response.text, ctx.limit)

    def _parse_results(self, html: str, limit: int) -> list[ProductCandidate]:
        page = BeautifulSoup(html, "html.parser")
        cards = page.select(".itemlist_box .item_data[data-product-id]")
        candidates = []
        for card in cards[:limit]:
            name = card.select_one(".goods_name")
            link = card.select_one("a[href]")
            if name is None or not isinstance(link, Tag):
                continue
            href = link.get("href")
            url = product_url(urljoin(self.origin, href), ("aitendo.com",)) if isinstance(href, str) else None
            if not url or not re.fullmatch(r"https://www\.aitendo\.com/product/\d+", url):
                continue
            model = card.select_one(".model_number_value")
            description = card.select_one(".item_desc")
            price_element = card.select_one(".tax_incl_price .figure")
            # A range or a missing tax-inclusive price is unknown, not a made-up
            # single price. Keep the displayed tax-inclusive text in raw data.
            price_text = price_element.get_text(strip=True) if price_element else ""
            price = amount(price_text.removesuffix("円"))
            image = card.select_one(".global_photo img[src]")
            image_url = image.get("src") if isinstance(image, Tag) else None
            raw = {"product_id": card.get("data-product-id"), "display_price": price_text}
            title = name.get_text("", strip=True)
            if not title:
                continue
            model_text = model.get_text("", strip=True) if model else None
            candidates.append(ProductCandidate(
                source=self.name, title=f"{title} [{model_text}]" if model_text else title,
                url=url, shop_name="aitendo", price=price, currency="JPY",
                model=model_text,
                description=description.get_text(" ", strip=True) if description else None,
                image_url=urljoin(self.origin, image_url) if isinstance(image_url, str) else None,
                raw_payload=raw,
            ))
        if cards and not candidates:
            raise RuntimeError("aitendo product cards no longer contain valid product data")
        if not cards and page.select_one(".itemlist_box") is None:
            raise RuntimeError("aitendo search page layout is not recognized")
        return candidates
