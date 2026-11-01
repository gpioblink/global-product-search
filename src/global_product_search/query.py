from __future__ import annotations

import re

from .models import SearchQuery

BARCODE_LENGTHS = {8, 12, 13, 14}
MODEL_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-_/+.() ]{1,63}$")
DEFAULT_PREFERRED_GENRES = ["generic"]


class InvalidQueryError(ValueError):
    """A query control directive cannot be satisfied safely."""


def normalize_query(text: str) -> SearchQuery:
    raw_input = text.strip()
    preferred_genres: list[str] = []
    requested_sources: list[str] = []
    content_parts: list[str] = []
    for part in raw_input.split():
        # Treat only leading directives as control syntax.
        # Once the actual query text starts, keep the remaining tokens verbatim.
        directive = re.match(r"^(genre|source)[:=](.*)$", part)
        if content_parts or directive is None:
            content_parts.append(part)
            continue

        kind, value = directive.groups()
        values = value.split(",")
        if kind == "source":
            if any(not re.fullmatch(r"[A-Za-z0-9_-]+", source) for source in values):
                raise InvalidQueryError("Source directives require comma-separated extractor names.")
            requested_sources.extend(source for source in values if source not in requested_sources)
        else:
            for genre in values:
                if genre and genre not in preferred_genres:
                    preferred_genres.append(genre)

    if requested_sources and not content_parts:
        raise InvalidQueryError("Source directives must be followed by search text.")

    # When the user does not request a genre explicitly, keep the search
    # conservative and stay within general stores by default.
    if not preferred_genres:
        preferred_genres = DEFAULT_PREFERRED_GENRES.copy()

    raw = " ".join(content_parts).strip() or raw_input
    compact_digits = re.sub(r"\D", "", raw)

    if compact_digits and compact_digits == raw.replace(" ", ""):
        # Pure numeric input is treated as a barcode-like query first, then
        # enriched with more specific signals such as ISBN or regional prefixes.
        signals = [f"kind:barcode", f"barcode:length:{len(compact_digits)}"]
        signals.extend(f"genre:{genre}" for genre in preferred_genres)

        if len(compact_digits) == 10:
            # ISBN-10 uses a modulo-11 checksum and may end in X, so validate
            # it before classifying the query as a book lookup.
            checksum = 0
            for index, char in enumerate(compact_digits):
                checksum += (10 - index) * (10 if char == "X" else int(char))
            if checksum % 11 == 0:
                signals.extend(["isbn:10", "product:book"])
                return SearchQuery(
                    raw=raw,
                    kind="barcode",
                    normalized=[compact_digits],
                    signals=signals,
                    preferred_genres=preferred_genres,
                    requested_sources=requested_sources,
                )

        if len(compact_digits) in BARCODE_LENGTHS:
            if len(compact_digits) == 13:
                prefix3 = compact_digits[:3]
                signals.append(f"barcode:prefix3:{prefix3}")
                prefix3_value = int(prefix3)
                if 450 <= prefix3_value <= 459 or 490 <= prefix3_value <= 499:
                    signals.append("barcode:country:japan")
                elif prefix3 in {"978", "979"}:
                    # ISBN-13 is encoded as EAN-13 with the 978/979 book prefix.
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
            return SearchQuery(
                raw=raw,
                kind="barcode",
                normalized=[compact_digits],
                signals=signals,
                preferred_genres=preferred_genres,
                requested_sources=requested_sources,
            )

    if MODEL_PATTERN.match(raw):
        # Model numbers benefit from both the original formatting and a compact
        # punctuation-stripped form for downstream matching.
        normalized = [raw.upper()]
        compact = re.sub(r"[\s_./()]+", "", raw).upper()
        if compact and compact not in normalized:
            normalized.append(compact)
        return SearchQuery(
            raw=raw,
            kind="model",
            normalized=normalized,
            signals=["kind:model", *[f"genre:{genre}" for genre in preferred_genres]],
            preferred_genres=preferred_genres,
            requested_sources=requested_sources,
        )

    # Everything else is treated as free text. Preserve the raw phrase and a
    # whitespace-normalized variant so full-text sources can use whichever form
    # works best.
    normalized = [part for part in {raw, " ".join(raw.split())} if part]
    return SearchQuery(
        raw=raw,
        kind="keyword",
        normalized=normalized or [raw],
        signals=["kind:keyword", *[f"genre:{genre}" for genre in preferred_genres]],
        preferred_genres=preferred_genres,
        requested_sources=requested_sources,
    )
