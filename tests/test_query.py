from global_product_search.query import normalize_query


def test_normalize_query_detects_barcode() -> None:
    query = normalize_query("4901234567894")
    assert query.kind == "barcode"
    assert query.normalized == ["4901234567894"]
    assert "barcode:country:japan" in query.signals


def test_normalize_query_detects_model() -> None:
    query = normalize_query("SM-S928B")
    assert query.kind == "model"
    assert query.normalized[0] == "SM-S928B"
    assert "kind:model" in query.signals


def test_normalize_query_detects_keyword() -> None:
    query = normalize_query("Nintendo Switch")
    assert query.kind == "keyword"
    assert query.normalized[0] == "Nintendo Switch"
    assert "kind:keyword" in query.signals


def test_normalize_query_detects_isbn13() -> None:
    query = normalize_query("9784873115658")
    assert query.kind == "barcode"
    assert "isbn:13" in query.signals
    assert "product:book" in query.signals
