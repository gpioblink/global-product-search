from global_product_search.query import normalize_query


def test_normalize_query_detects_barcode() -> None:
    query = normalize_query("4901234567894")
    assert query.kind == "barcode"
    assert query.normalized == ["4901234567894"]


def test_normalize_query_detects_model() -> None:
    query = normalize_query("SM-S928B")
    assert query.kind == "model"
    assert query.normalized[0] == "SM-S928B"


def test_normalize_query_detects_keyword() -> None:
    query = normalize_query("Nintendo Switch")
    assert query.kind == "keyword"
    assert query.normalized[0] == "Nintendo Switch"
