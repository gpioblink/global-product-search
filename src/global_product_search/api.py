from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol
from urllib.parse import parse_qs

from .models import ProductCandidate
from .query import InvalidQueryError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from wsgiref.types import StartResponse, WSGIEnvironment


class BadRequestError(ValueError):
    pass


class SearchApiEngine(Protocol):
    def list_extractor_infos(self) -> Iterable[object]: ...

    def search_text(self, text: str, *, limit: int = 10) -> list[ProductCandidate]: ...


def create_app(
    *, engine: SearchApiEngine | None = None, cors_origins: Sequence[str] | None = None,
) -> "GlobalProductSearchApi":
    from .engine import SearchEngine

    if cors_origins is None:
        cors_origins = os.getenv("GPS_CORS_ORIGINS", "*").split(",")
    return GlobalProductSearchApi(engine=engine or SearchEngine(), cors_origins=cors_origins)


class GlobalProductSearchApi:
    def __init__(self, *, engine: SearchApiEngine, cors_origins: Sequence[str] = ("*",)) -> None:
        self.engine = engine
        self.cors_origins = tuple(origin.strip() for origin in cors_origins if origin.strip())

    def __call__(self, environ: "WSGIEnvironment", start_response: "StartResponse") -> Iterable[bytes]:
        original_start_response = start_response

        def cors_start_response(status, headers, exc_info=None):
            origin = environ.get("HTTP_ORIGIN")
            if "*" in self.cors_origins:
                headers.append(("Access-Control-Allow-Origin", "*"))
            else:
                headers.append(("Vary", "Origin"))
                if origin in self.cors_origins:
                    headers.append(("Access-Control-Allow-Origin", origin))
            return original_start_response(status, headers, exc_info)

        start_response = cors_start_response
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "") or "/"

        try:
            if method == "OPTIONS":
                return self._preflight_response(start_response)

            if path == "/":
                if method != "GET":
                    return self._json_response(
                        start_response,
                        405,
                        {"detail": "Method not allowed."},
                        allow="GET",
                    )
                return self._json_response(
                    start_response,
                    200,
                    {
                        "name": "global-product-search",
                        "capabilities": ["source_filter"],
                        "endpoints": {
                            "extractors": "/extractors",
                            "search": "/search?q=<query>&limit=10&include_raw_payload=true",
                        },
                    },
                )

            if path == "/extractors":
                if method != "GET":
                    return self._json_response(
                        start_response,
                        405,
                        {"detail": "Method not allowed."},
                        allow="GET",
                    )
                return self._handle_extractors(start_response)

            if path == "/search":
                if method != "GET":
                    return self._json_response(
                        start_response,
                        405,
                        {"detail": "Method not allowed."},
                        allow="GET",
                    )
                return self._handle_search(environ, start_response)

            return self._json_response(start_response, 404, {"detail": "Not found."})
        except (BadRequestError, InvalidQueryError) as exc:
            return self._json_response(start_response, 400, {"detail": str(exc)})
        except RuntimeError as exc:
            return self._json_response(start_response, 503, {"detail": str(exc)})

    def _handle_extractors(self, start_response: "StartResponse") -> Iterable[bytes]:
        payload = [
            {
                "name": getattr(extractor, "name"),
                "genres": list(getattr(extractor, "genres", ()) or ()),
                "flags": list(getattr(extractor, "flags", ()) or ()),
            }
            for extractor in self.engine.list_extractor_infos()
        ]
        return self._json_response(start_response, 200, payload)

    def _handle_search(
        self,
        environ: "WSGIEnvironment",
        start_response: "StartResponse",
    ) -> Iterable[bytes]:
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False)
        text = self._first_value(params, "q") or self._first_value(params, "text")
        if not text:
            raise BadRequestError("Missing required query parameter: q")

        limit_value = self._first_value(params, "limit")
        if limit_value is None:
            limit = 10
        else:
            try:
                limit = int(limit_value)
            except ValueError as exc:
                raise BadRequestError("Query parameter 'limit' must be an integer.") from exc
            if limit < 1:
                raise BadRequestError("Query parameter 'limit' must be greater than or equal to 1.")

        include_raw_payload = self._parse_bool(
            self._first_value(params, "include_raw_payload"),
            default=True,
        )
        results = self.engine.search_text(text, limit=limit)
        payload = [
            self._serialize_candidate(candidate, include_raw_payload=include_raw_payload)
            for candidate in results
        ]
        return self._json_response(start_response, 200, payload)

    def _serialize_candidate(
        self,
        candidate: ProductCandidate,
        *,
        include_raw_payload: bool,
    ) -> dict[str, object]:
        payload = candidate.model_dump()
        if not include_raw_payload:
            payload.pop("raw_payload", None)
        return payload

    def _json_response(
        self,
        start_response: "StartResponse",
        status_code: int,
        payload: object,
        *,
        allow: str | None = None,
    ) -> Iterable[bytes]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Access-Control-Allow-Methods", "GET, OPTIONS"),
            ("Access-Control-Allow-Headers", "*"),
        ]
        if allow is not None:
            headers.append(("Allow", allow))
        start_response(f"{status_code} {self._reason_phrase(status_code)}", headers)
        return [body]

    def _preflight_response(self, start_response: "StartResponse") -> Iterable[bytes]:
        headers = [
            ("Content-Length", "0"),
            ("Access-Control-Allow-Methods", "GET, OPTIONS"),
            ("Access-Control-Allow-Headers", "*"),
        ]
        start_response("204 No Content", headers)
        return []

    def _first_value(self, params: dict[str, list[str]], key: str) -> str | None:
        values = params.get(key)
        if not values:
            return None
        value = values[0].strip()
        return value or None

    def _parse_bool(self, raw: str | None, *, default: bool) -> bool:
        if raw is None:
            return default
        normalized = raw.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise BadRequestError(
            "Query parameter 'include_raw_payload' must be one of: true, false, 1, 0."
        )

    def _reason_phrase(self, status_code: int) -> str:
        reason_phrases = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            204: "No Content",
            503: "Service Unavailable",
        }
        return reason_phrases.get(status_code, "OK")
