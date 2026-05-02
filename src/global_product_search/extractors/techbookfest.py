from __future__ import annotations

import json
import logging
from urllib.parse import quote

import httpx

from ..context import SearchContext
from ..models import ProductCandidate, SearchQuery
from .base import BaseExtractor, ExtractorSelfTestCase

logger = logging.getLogger(__name__)


class TechbookfestExtractor(BaseExtractor):
    name = "techbookfest"
    genres = ("books-doujin-technical",)
    flags = ("keyword", "doujin", "technical-book", "marketplace")
    app_version = "20260429a-web"
    site_origin = "https://techbookfest.org"
    graphql_endpoint = "https://techbookfest.org/api/graphql"
    search_page_url = "https://techbookfest.org/market/search"
    search_query = """
query MarketSearchQuery($query: String!, $orderBy: SearchProductsOrder, $first: Int!) {
  searchProducts(first: $first, query: $query, orderBy: $orderBy) {
    edges {
      node {
        ... on ProductInfoSearchResult {
          product {
            id
            databaseID
            name
            description
            organization {
              id
              name
            }
            coverImage {
              id
              url
              height
              width
            }
            ebookVariant: productVariant(kind: MARKET_EBOOK) {
              id
              price
              kind
            }
            realbookVariant: productVariant(kind: MARKET_EBOOK_AND_PAPER) {
              id
              price
              kind
            }
          }
          score
          contentSearch
          nameHiglights
          organizationNameHighlights
          descriptionHighlights
          contentHighlights
        }
      }
    }
  }
}
""".strip()
    _TESTS = [
        ExtractorSelfTestCase(
            name="keyword_search",
            query="組み込みLinux",
            expected_result={
                "source": "techbookfest",
                "title": str,
                "url": "startswith:https://techbookfest.org/",
                "brand": str,
            },
        )
    ]

    def supports(self, query: SearchQuery) -> int:
        if query.kind == "keyword":
            return 95
        return 0

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[ProductCandidate]:
        keyword = query.normalized[0]
        with httpx.Client(follow_redirects=True) as client:
            logger.info("[%s] Downloading search page", self.name)
            if ctx.debug:
                logger.debug("[%s] GET %s", self.name, self.search_page_url)
            response = client.get(
                self.search_page_url,
                params={"q": keyword},
                timeout=10.0,
            )
            response.raise_for_status()

            xsrf_token = client.cookies.get("XSRF-TOKEN")
            if not xsrf_token:
                raise RuntimeError("techbookfest search page did not issue an XSRF token")

            payload = self.download_json(
                ctx,
                self.graphql_endpoint,
                client=client,
                method="POST",
                note="Downloading search API JSON",
                params={
                    "operationName": "MarketSearchQuery",
                    "appVersion": self.app_version,
                },
                headers={
                    "accept": "application/graphql-response+json,application/json;q=0.9",
                    "content-type": "application/json",
                    "origin": "https://techbookfest.org",
                    "referer": f"{self.search_page_url}?q={quote(keyword)}",
                    "x-xsrf-token": xsrf_token,
                },
                content=json.dumps(
                    {
                        "operationName": "MarketSearchQuery",
                        "variables": {
                            "first": min(ctx.limit, 30),
                            "query": keyword,
                            "orderBy": "SCORE",
                        },
                        "extensions": {
                            "clientLibrary": {
                                "name": "@apollo/client",
                                "version": "4.1.9",
                            }
                        },
                        "query": self.search_query,
                    }
                ).encode("utf-8"),
            )

        edges = (
            payload.get("data", {})
            .get("searchProducts", {})
            .get("edges", [])
        )
        candidates: list[ProductCandidate] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            product = node.get("product")
            if not isinstance(product, dict):
                continue

            organization = product.get("organization")
            brand = organization.get("name") if isinstance(organization, dict) else None
            cover_image = product.get("coverImage")
            image_url = cover_image.get("url") if isinstance(cover_image, dict) else None
            if isinstance(image_url, str) and image_url.startswith("/"):
                image_url = f"{self.site_origin}{image_url}"

            price = None
            ebook_variant = product.get("ebookVariant")
            if isinstance(ebook_variant, dict) and isinstance(ebook_variant.get("price"), int):
                price = ebook_variant["price"]
            realbook_variant = product.get("realbookVariant")
            if price is None and isinstance(realbook_variant, dict) and isinstance(realbook_variant.get("price"), int):
                price = realbook_variant["price"]

            database_id = product.get("databaseID")
            product_id = product.get("id")
            product_path_id = database_id or product_id
            if not isinstance(product_path_id, str):
                continue

            candidates.append(
                ProductCandidate(
                    source=self.name,
                    title=str(product.get("name") or ""),
                    url=f"https://techbookfest.org/product/{product_path_id}",
                    description=product.get("description") if isinstance(product.get("description"), str) else None,
                    price=price,
                    shop_name=brand,
                    image_url=image_url if isinstance(image_url, str) else None,
                    brand=brand if isinstance(brand, str) else None,
                    raw_payload=node,
                )
            )

        return candidates
