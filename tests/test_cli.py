from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from global_product_search.cli import app
from global_product_search.models import ProductCandidate

runner = CliRunner()


def test_cli_lists_extractors(monkeypatch) -> None:
    monkeypatch.setattr(
        "global_product_search.cli.SearchEngine.list_extractor_infos",
        lambda self: [
            SimpleNamespace(
                name="example",
                genres=("generic", "books-general"),
                flags=("keyword", "barcode"),
            )
        ],
    )

    result = runner.invoke(app, ["--list-extractors"], color=True)

    assert result.exit_code == 0
    assert "example" in result.stdout
    assert "categories: generic, books-general" in result.stdout
    assert "flags: keyword, barcode" in result.stdout


def test_cli_search_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "global_product_search.cli.SearchEngine.search_text",
        lambda self, text, limit=10: [
            ProductCandidate(
                source="example",
                title="SM-S928B Case",
                url="https://example.com/item",
                shop_name="Shop",
                score=99.0,
            )
        ],
    )

    result = runner.invoke(app, ["search", "SM-S928B", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["title"] == "SM-S928B Case"


def test_cli_search_human_output(monkeypatch) -> None:
    monkeypatch.setattr(
        "global_product_search.cli.SearchEngine.search_text",
        lambda self, text, limit=10: [
            ProductCandidate(
                source="example",
                title="Sample Product",
                url="https://example.com/item",
                description="Sample description",
                price=1200,
                shop_name="Shop",
                image_url="https://example.com/image.jpg",
                brand="ExampleBrand",
                model="SM-S928B",
                gtins=["4901234567894"],
                score=88.0,
                raw_payload={"itemCaption": "Sample caption", "itemCode": "example:sku"},
            )
        ],
    )

    result = runner.invoke(app, ["search", "4901234567894"], color=True)

    assert result.exit_code == 0
    assert "Sample Product" in result.stdout
    assert "source: example" in result.stdout
    assert "description: Sample description" in result.stdout
    assert "image_url: https://example.com/image.jpg" in result.stdout
    assert "brand: ExampleBrand" in result.stdout
    assert "model: SM-S928B" in result.stdout
    assert "gtins: 4901234567894" in result.stdout
    assert "score: 88.0" in result.stdout
    assert "raw_payload:" not in result.stdout
    assert '"itemCaption": "Sample caption"' not in result.stdout
    assert "\x1b[" in result.stdout


def test_cli_search_reports_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "global_product_search.cli.SearchEngine.search_text",
        lambda self, text, limit=10: (_ for _ in ()).throw(RuntimeError("missing credentials")),
    )
    result = runner.invoke(app, ["search", "4901234567894"])

    assert result.exit_code != 0
    assert "missing credentials" in result.stdout or "missing credentials" in result.stderr


def test_cli_search_shows_raw_payload_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "global_product_search.cli.SearchEngine.search_text",
        lambda self, text, limit=10: [
            ProductCandidate(
                source="example",
                title="Sample Product",
                url="https://example.com/item",
                raw_payload={"itemCaption": "Sample caption", "itemCode": "example:sku"},
            )
        ],
    )

    result = runner.invoke(app, ["search", "4901234567894", "--show-raw-payload"], color=True)

    assert result.exit_code == 0
    assert "raw_payload:" in result.stdout
    assert '"itemCaption": "Sample caption"' in result.stdout
