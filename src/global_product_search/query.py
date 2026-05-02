from __future__ import annotations

import re

from .models import SearchQuery

BARCODE_LENGTHS = {8, 12, 13, 14}
MODEL_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-_/+.() ]{1,63}$")


def normalize_query(text: str) -> SearchQuery:
    raw = text.strip()
    compact_digits = re.sub(r"\D", "", raw)

    if compact_digits and len(compact_digits) in BARCODE_LENGTHS and compact_digits == raw.replace(" ", ""):
        return SearchQuery(raw=raw, kind="barcode", normalized=[compact_digits])

    if MODEL_PATTERN.match(raw):
        normalized = [raw.upper()]
        compact = re.sub(r"[\s_./()]+", "", raw).upper()
        if compact and compact not in normalized:
            normalized.append(compact)
        return SearchQuery(raw=raw, kind="model", normalized=normalized)

    normalized = [part for part in {raw, " ".join(raw.split())} if part]
    return SearchQuery(raw=raw, kind="keyword", normalized=normalized or [raw])
