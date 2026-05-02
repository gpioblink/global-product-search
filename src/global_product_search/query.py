from __future__ import annotations

import re

from .models import SearchQuery

BARCODE_LENGTHS = {8, 12, 13, 14}
MODEL_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-_/+.() ]{1,63}$")


def normalize_query(text: str) -> SearchQuery:
    raw = text.strip()
    compact_digits = re.sub(r"\D", "", raw)

    if compact_digits and compact_digits == raw.replace(" ", ""):
        signals = [f"kind:barcode", f"barcode:length:{len(compact_digits)}"]

        if len(compact_digits) == 10:
            checksum = 0
            for index, char in enumerate(compact_digits):
                checksum += (10 - index) * (10 if char == "X" else int(char))
            if checksum % 11 == 0:
                signals.extend(["isbn:10", "product:book"])
                return SearchQuery(raw=raw, kind="barcode", normalized=[compact_digits], signals=signals)

        if len(compact_digits) in BARCODE_LENGTHS:
            if len(compact_digits) == 13:
                prefix3 = compact_digits[:3]
                signals.append(f"barcode:prefix3:{prefix3}")
                prefix3_value = int(prefix3)
                if 450 <= prefix3_value <= 459 or 490 <= prefix3_value <= 499:
                    signals.append("barcode:country:japan")
                elif prefix3 in {"978", "979"}:
                    checksum = 0
                    for index, char in enumerate(compact_digits[:12]):
                        checksum += int(char) * (1 if index % 2 == 0 else 3)
                    check_digit = (10 - (checksum % 10)) % 10
                    if check_digit == int(compact_digits[-1]):
                        signals.extend(["isbn:13", "product:book"])
                else:
                    signals.append("barcode:country:non-japan")
            elif len(compact_digits) == 12:
                signals.extend(["barcode:scheme:upc", "barcode:country:non-japan"])
            return SearchQuery(raw=raw, kind="barcode", normalized=[compact_digits], signals=signals)

    if MODEL_PATTERN.match(raw):
        normalized = [raw.upper()]
        compact = re.sub(r"[\s_./()]+", "", raw).upper()
        if compact and compact not in normalized:
            normalized.append(compact)
        return SearchQuery(
            raw=raw,
            kind="model",
            normalized=normalized,
            signals=["kind:model"],
        )

    normalized = [part for part in {raw, " ".join(raw.split())} if part]
    return SearchQuery(
        raw=raw,
        kind="keyword",
        normalized=normalized or [raw],
        signals=["kind:keyword"],
    )
