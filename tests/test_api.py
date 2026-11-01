from __future__ import annotations

import httpx

from global_product_search.api import create_app
from global_product_search.models import ProductCandidate


class StubEngine:
    def list_extractor_infos(self):
        from types import SimpleNamespace

        return [
            SimpleNamespace(
                name="example",
                genres=("generic", "books-general"),
                flags=("kind:keyword", "kind:barcode"),
            )
        ]

    def search_text(self, text: str, *, limit: int = 10):
        assert text == "SM-S928B"
        assert limit == 5
        return [
            ProductCandidate(
                source="example",
                title="SM-S928B Case",
                url="https://example.com/item",
                raw_payload={"itemCaption": "Sample caption"},
            )
        ]


def test_api_lists_extractors() -> None:
    client = httpx.Client(
        transport=httpx.WSGITransport(app=create_app(engine=StubEngine())),
        base_url="http://testserver",
    )

    response = client.get("/extractors")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "example",
            "genres": ["generic", "books-general"],
            "flags": ["kind:keyword", "kind:barcode"],
        }
    ]


def test_api_advertises_strict_source_filter_capability() -> None:
    with httpx.Client(transport=httpx.WSGITransport(app=create_app(engine=StubEngine())), base_url="http://testserver") as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "source_filter" in response.json()["capabilities"]


def test_api_search_returns_results_without_raw_payload_when_disabled() -> None:
    client = httpx.Client(
        transport=httpx.WSGITransport(app=create_app(engine=StubEngine())),
        base_url="http://testserver",
    )

    response = client.get(
        "/search",
        params={"q": "SM-S928B", "limit": "5", "include_raw_payload": "false"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["title"] == "SM-S928B Case"
    assert "raw_payload" not in payload[0]


def test_api_search_requires_query_text() -> None:
    client = httpx.Client(
        transport=httpx.WSGITransport(app=create_app(engine=StubEngine())),
        base_url="http://testserver",
    )

    response = client.get("/search")

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required query parameter: q"


def test_api_search_maps_runtime_errors_to_service_unavailable() -> None:
    class FailingEngine:
        def list_extractor_infos(self):
            return []

        def search_text(self, text: str, *, limit: int = 10):
            raise RuntimeError("missing credentials")

    client = httpx.Client(
        transport=httpx.WSGITransport(app=create_app(engine=FailingEngine())),
        base_url="http://testserver",
    )

    response = client.get("/search", params={"q": "SM-S928B"})

    assert response.status_code == 503
    assert response.json()["detail"] == "missing credentials"


def test_api_sets_permissive_cors_headers() -> None:
    client = httpx.Client(
        transport=httpx.WSGITransport(app=create_app(engine=StubEngine())),
        base_url="http://testserver",
    )

    response = client.get("/extractors")

    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET, OPTIONS"
    assert response.headers["access-control-allow-headers"] == "*"


def test_api_answers_cors_preflight() -> None:
    client = httpx.Client(
        transport=httpx.WSGITransport(app=create_app(engine=StubEngine())),
        base_url="http://testserver",
    )

    response = client.options(
        "/search",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET, OPTIONS"
    assert response.headers["access-control-allow-headers"] == "*"


def test_api_rejects_unknown_sources_without_upstream_calls() -> None:
    client = httpx.Client(transport=httpx.WSGITransport(app=create_app()), base_url="http://testserver")
    response = client.get("/search", params={"q": "source:unknown Python"})
    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown source(s): unknown"}


def test_cors_allowlist_applies_to_success_errors_and_preflight() -> None:
    app = create_app(engine=StubEngine(), cors_origins=["https://example.com"])
    with httpx.Client(transport=httpx.WSGITransport(app=app), base_url="http://testserver") as client:
        for method, path in [("GET", "/extractors"), ("GET", "/missing"), ("GET", "/search"), ("OPTIONS", "/search")]:
            allowed = client.request(method, path, headers={"Origin": "https://example.com"})
            assert allowed.headers["access-control-allow-origin"] == "https://example.com"
            assert allowed.headers["vary"] == "Origin"
            assert "access-control-allow-credentials" not in allowed.headers
            denied = client.request(method, path, headers={"Origin": "https://other.example"})
            assert "access-control-allow-origin" not in denied.headers
            assert denied.headers["vary"] == "Origin"


def test_cors_can_be_configured_from_environment_or_disabled(monkeypatch) -> None:
    monkeypatch.setenv("GPS_CORS_ORIGINS", "https://example.com,https://other.example")
    with httpx.Client(transport=httpx.WSGITransport(app=create_app(engine=StubEngine())), base_url="http://testserver") as client:
        assert client.get("/", headers={"Origin": "https://other.example"}).headers["access-control-allow-origin"] == "https://other.example"
    monkeypatch.setenv("GPS_CORS_ORIGINS", "")
    with httpx.Client(transport=httpx.WSGITransport(app=create_app(engine=StubEngine())), base_url="http://testserver") as client:
        assert "access-control-allow-origin" not in client.get("/", headers={"Origin": "https://example.com"}).headers
