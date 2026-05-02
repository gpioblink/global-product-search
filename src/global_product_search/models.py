from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

QueryKind = Literal["barcode", "model", "keyword"]


class SearchQuery(BaseModel):
    raw: str
    kind: QueryKind
    normalized: list[str] = Field(default_factory=list)


class ProductCandidate(BaseModel):
    source: str
    title: str
    url: str
    description: str | None = None
    price: int | None = None
    shop_name: str | None = None
    image_url: str | None = None
    brand: str | None = None
    model: str | None = None
    gtins: list[str] = Field(default_factory=list)
    score: float = 0.0
    raw_payload: dict[str, Any] = Field(default_factory=dict)
