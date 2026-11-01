from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from urllib.parse import parse_qs

import httpx
import pytest

from global_product_search.context import SearchContext
from global_product_search.engine import SearchEngine
from global_product_search.extractors.aitendo import AitendoExtractor
from global_product_search.extractors.aliexpress import AliExpressExtractor
from global_product_search.extractors.digikey import DigiKeyExtractor
from global_product_search.extractors.mouser import MouserExtractor
from global_product_search.query import normalize_query


@pytest.fixture
def provider_env(monkeypatch):
    # Ephemeral test values, never live account keys or saved credentials.
    names = ["DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "MOUSER_API_KEY",
             "ALIEXPRESS_APP_KEY", "ALIEXPRESS_APP_SECRET", "ALIEXPRESS_TRACKING_ID"]
    values = {name: secrets.token_hex(16) for name in names}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in ["DIGIKEY_SANDBOX", "DIGIKEY_CURRENCY", "DIGIKEY_SITE", "DIGIKEY_LANGUAGE",
                 "ALIEXPRESS_CURRENCY", "ALIEXPRESS_LANGUAGE", "ALIEXPRESS_COUNTRY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(DigiKeyExtractor, "_tokens", {})
    return values


@pytest.fixture
def mock_http(monkeypatch):
    original_client = httpx.Client

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))

    return install


def test_digikey_oauth_locale_and_product_mapping(provider_env, mock_http, monkeypatch):
    requests = []
    token = secrets.token_urlsafe(12)
    monkeypatch.setenv("DIGIKEY_SITE", "JP")
    monkeypatch.setenv("DIGIKEY_LANGUAGE", "ja")
    monkeypatch.setenv("DIGIKEY_CURRENCY", "JPY")

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.host == "api.digikey.com"
        if request.url.path == "/v1/oauth2/token":
            data = parse_qs(request.content.decode())
            assert data["client_id"] == [provider_env["DIGIKEY_CLIENT_ID"]]
            assert data["client_secret"] == [provider_env["DIGIKEY_CLIENT_SECRET"]]
            assert data["grant_type"] == ["client_credentials"]
            return httpx.Response(200, json={"access_token": token, "expires_in": 600})
        assert request.url.path == "/products/v4/search/keyword"
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert request.headers["X-DIGIKEY-Locale-Site"] == "JP"
        assert request.headers["X-DIGIKEY-Locale-Language"] == "ja"
        assert json.loads(request.content) == {"Keywords": "NE555", "Limit": 2, "Offset": 0}
        return httpx.Response(200, json={"SearchLocaleUsed": {"Currency": "JPY"}, "Products": [
            {"ManufacturerProductNumber": "NE555P", "ProductUrl": "https://www.digikey.jp/ja/products/detail/ti/NE555P/123",
             "Description": {"ProductDescription": "Timer", "DetailedDescription": "Precision timer"},
             "Manufacturer": {"Name": "Texas Instruments"}, "PhotoUrl": "https://example.com/part.jpg", "UnitPrice": 85.5},
            {"ManufacturerProductNumber": "bad", "ProductUrl": "https://www.digikey.com/en/products?keywords=NE555"},
        ]})

    mock_http(handler)
    extractor = DigiKeyExtractor()
    results = extractor.search(normalize_query("source:digikey NE555"), SearchContext(limit=2))
    assert len(results) == 1
    assert results[0].price == 85.5
    assert results[0].currency == "JPY"
    assert results[0].brand == "Texas Instruments"
    assert results[0].description == "Precision timer"
    extractor.search(normalize_query("NE555"), SearchContext(limit=2))
    assert len(requests) == 3  # Cached token, two product requests.


def test_digikey_sandbox_is_explicit(provider_env, mock_http, monkeypatch):
    monkeypatch.setenv("DIGIKEY_SANDBOX", "true")

    def handler(request):
        assert request.url.host == "sandbox-api.digikey.com"
        payload = {"access_token": secrets.token_urlsafe(12), "expires_in": 600} if "oauth2" in request.url.path else {"Products": []}
        return httpx.Response(200, json=payload)

    mock_http(handler)
    assert DigiKeyExtractor().search(normalize_query("NE555"), SearchContext()) == []


def test_mouser_mapping_limit_and_credential_redaction(provider_env, mock_http, caplog):
    caplog.set_level(logging.DEBUG)

    def handler(request):
        assert request.url.params["apiKey"] == provider_env["MOUSER_API_KEY"]
        body = json.loads(request.content)["SearchByKeywordRequest"]
        assert body == {"keyword": "NE555", "records": 50, "startingRecord": 0, "searchOptions": "None"}
        return httpx.Response(200, json={"Errors": [], "SearchResults": {"Parts": [
            {"ManufacturerPartNumber": "NE555P", "Description": "Timer", "Manufacturer": "Texas Instruments",
             "ProductDetailUrl": "https://www.mouser.com/ProductDetail/Texas-Instruments/NE555P", "ImagePath": "https://example.com/part.jpg",
             "PriceBreaks": [{"Quantity": 100, "Price": "$0.10", "Currency": "USD"},
                             {"Quantity": 1, "Price": "$0.85", "Currency": "USD"}]},
            {"ManufacturerPartNumber": "bad", "ProductDetailUrl": "https://www.mouser.com/c/?q=NE555"},
        ]}})

    mock_http(handler)
    results = MouserExtractor().search(normalize_query("NE555"), SearchContext(limit=100))
    assert len(results) == 1
    assert results[0].price == 0.85
    assert results[0].currency == "USD"
    assert provider_env["MOUSER_API_KEY"] not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_aliexpress_signed_official_request_and_product_mapping(provider_env, mock_http):
    def handler(request):
        assert str(request.url) == "https://eco.taobao.com/router/rest"
        data = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        assert data["app_key"] == provider_env["ALIEXPRESS_APP_KEY"]
        assert data["tracking_id"] == provider_env["ALIEXPRESS_TRACKING_ID"]
        assert data["keywords"] == "ESP32"
        assert data["method"] == "aliexpress.affiliate.product.query"
        assert data["page_size"] == "50"
        assert data["sign_method"] == "hmac"
        signature = data.pop("sign")
        canonical = "".join(key + data[key] for key in sorted(data))
        assert signature == hmac.new(provider_env["ALIEXPRESS_APP_SECRET"].encode(), canonical.encode(), hashlib.md5).hexdigest().upper()
        assert provider_env["ALIEXPRESS_APP_SECRET"] not in request.content.decode()
        return httpx.Response(200, json={"aliexpress_affiliate_product_query_response": {"resp_result": {
            "resp_code": 200, "result": {"products": {"product": [
                {"product_title": "ESP32 development board", "product_detail_url": "https://www.aliexpress.com/item/1005001234567.html",
                 "product_main_image_url": "https://example.com/part.jpg", "target_sale_price": "3.49", "target_sale_price_currency": "USD"},
                {"product_title": "Not a product", "product_detail_url": "https://www.aliexpress.com/w/wholesale-esp32.html"},
            ]}},
        }}})

    mock_http(handler)
    results = AliExpressExtractor().search(normalize_query("source:aliexpress ESP32"), SearchContext(limit=100))
    assert len(results) == 1
    assert results[0].price == 3.49
    assert results[0].currency == "USD"


@pytest.mark.parametrize("extractor,key", [(DigiKeyExtractor, "DIGIKEY_CLIENT_ID"), (MouserExtractor, "MOUSER_API_KEY"), (AliExpressExtractor, "ALIEXPRESS_APP_KEY")])
def test_missing_credentials_fail_before_network(monkeypatch, mock_http, extractor, key):
    monkeypatch.delenv(key, raising=False)
    mock_http(lambda request: pytest.fail("missing credentials must not make a request"))
    with pytest.raises(RuntimeError, match=key):
        extractor().search(normalize_query("ESP32"), SearchContext())


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_errors_never_echo_reflected_secrets(provider_env, mock_http, status):
    secret = provider_env["MOUSER_API_KEY"]
    mock_http(lambda request: httpx.Response(status, text=secret))
    with pytest.raises(RuntimeError, match=f"HTTP {status}") as exc:
        MouserExtractor().search(normalize_query("ESP32"), SearchContext())
    assert secret not in str(exc.value)


@pytest.mark.parametrize("payload", [{"Errors": [{"Message": "account error"}]}, {"SearchResults": {}}, []])
def test_invalid_mouser_payload_is_an_error(provider_env, mock_http, payload):
    mock_http(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(RuntimeError):
        MouserExtractor().search(normalize_query("ESP32"), SearchContext())


def test_aliexpress_provider_error_is_not_an_empty_success(provider_env, mock_http):
    mock_http(lambda request: httpx.Response(200, json={"error_response": {"code": "bad-permission"}}))
    with pytest.raises(RuntimeError, match="permissions"):
        AliExpressExtractor().search(normalize_query("ESP32"), SearchContext())


@pytest.mark.parametrize("source,payload", [
    (MouserExtractor, {"Errors": [], "SearchResults": {"NumberOfResult": 0, "Parts": None}}),
    (AliExpressExtractor, {"aliexpress_affiliate_product_query_response": {"resp_result": {"resp_code": 200, "result": {"total_record_count": 0}}}}),
])
def test_apis_explicit_zero_results_remain_empty(provider_env, mock_http, source, payload):
    mock_http(lambda request: httpx.Response(200, json=payload))
    assert source().search(normalize_query("ESP32"), SearchContext()) == []


def test_mouser_ambiguous_localized_price_is_unknown(provider_env, mock_http):
    payload = {"Errors": [], "SearchResults": {"Parts": [{
        "ManufacturerPartNumber": "NE555P",
        "ProductDetailUrl": "https://www.mouser.de/ProductDetail/Texas-Instruments/NE555P",
        "PriceBreaks": [{"Quantity": 1, "Price": "0,125 €", "Currency": "EUR"}],
    }]}}
    mock_http(lambda request: httpx.Response(200, json=payload))
    result = MouserExtractor().search(normalize_query("NE555"), SearchContext())[0]
    assert result.price is None
    assert result.currency == "EUR"


AITENDO_CARD = '''<div class="itemlist_box"><div class="item_data" data-product-id="123">
  <a href="/product/123"><div class="global_photo"><img src="/part.jpg"></div></a>
  <span class="goods_name">ESP32 &amp; board</span><span class="model_number_value">ESP32-S3</span>
  <p class="tax_incl_price"><span class="figure">1,100円</span></p>
  <p class="item_desc">A <b>real</b> board</p></div></div>'''


def test_aitendo_public_search_robots_and_product_mapping(mock_http):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["User-Agent"] == "global-product-search/0.1"
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/")
        assert request.url.path == "/product-list"
        assert request.url.params["keyword"] == "ESP32"
        return httpx.Response(200, text=AITENDO_CARD)

    mock_http(handler)
    result = AitendoExtractor().search(normalize_query("ESP32"), SearchContext())[0]
    assert len(requests) == 2
    assert result.title == "ESP32 & board [ESP32-S3]"
    assert result.url == "https://www.aitendo.com/product/123"
    assert result.price == 1100
    assert result.currency == "JPY"
    assert result.description == "A real board"
    assert result.image_url == "https://www.aitendo.com/part.jpg"


def test_aitendo_respects_robots_disallow(mock_http):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/robots.txt"
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    mock_http(handler)
    with pytest.raises(RuntimeError, match="robots.txt"):
        AitendoExtractor().search(normalize_query("ESP32"), SearchContext())
    assert len(requests) == 1


def test_aitendo_ranges_and_empty_results_are_not_fabricated():
    extractor = AitendoExtractor()
    result = extractor._parse_results(AITENDO_CARD.replace("1,100円", "1,100円～2,200円"), 1)[0]
    assert result.price is None
    assert extractor._parse_results('<div class="itemlist_box"></div>', 5) == []
    with pytest.raises(RuntimeError, match="layout"):
        extractor._parse_results("<html>Access denied</html>", 5)


def test_new_sources_are_discoverable_and_do_not_change_default_genres():
    engine = SearchEngine()
    infos = {info.name: info for info in engine.list_extractor_infos()}
    for name in ["aitendo", "digikey", "mouser", "aliexpress"]:
        assert name in infos
        assert infos[name].genres == ("electronic-parts",)
    assert "akizuki" not in infos
    assert "marutsu" not in infos
