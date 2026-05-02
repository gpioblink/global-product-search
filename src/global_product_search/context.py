from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SearchContext:
    limit: int = 10
    debug: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        limit: int = 10,
        debug: bool = False,
    ) -> "SearchContext":
        return cls(limit=limit, debug=debug)
