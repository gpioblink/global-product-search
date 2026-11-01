"""Small shared helpers for credentialed commerce APIs."""
from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from .base import BaseExtractor


class _RedactQueryCredentials(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx logs complete request URLs at INFO, including Mouser's required
        # apiKey query parameter. Never emit those values, even with --debug.
        message = record.getMessage()
        record.msg = re.sub(
            r"(?i)([?&](?:apiKey|applicationId|accessKey|app_key|sign)=)[^&\s\"']+",
            r"\1[REDACTED]",
            message,
        )
        record.args = ()
        return True


logging.getLogger("httpx").addFilter(_RedactQueryCredentials())


def required_env(name: str, source: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for the {source} extractor")
    return value


def text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def product_url(value: Any, domains: tuple[str, ...]) -> str | None:
    url = text(value)
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower()
    if not any(host == domain or host.endswith("." + domain) for domain in domains):
        return None
    return url


def amount(value: Any) -> int | float | None:
    """Accept unambiguous nonnegative decimal amounts; never guess a range."""
    if isinstance(value, bool):
        return None
    raw = str(value).strip()
    if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", raw):
        return None
    number = float(raw.replace(",", ""))
    if number == float("inf"):
        return None
    return int(number) if number.is_integer() else number


def object_list(payload: dict[str, Any], key: str, source: str) -> list[dict[str, Any]]:
    items = payload.get(key)
    if not isinstance(items, list):
        raise RuntimeError(f"{source} returned an invalid {key} collection")
    return [item for item in items if isinstance(item, dict)]


class _CommerceExtractor(BaseExtractor):
    def request_json(self, url: str, *, method: str = "POST", **kwargs: Any) -> dict[str, Any]:
        # Response bodies and exception strings can contain reflected secrets.
        # Report only a source name and status/type, never those raw values.
        try:
            with httpx.Client(follow_redirects=False, timeout=10.0) as client:
                response = client.request(method, url, **kwargs)
                if not response.is_success:
                    raise RuntimeError(f"{self.name} API request failed (HTTP {response.status_code})")
                payload = response.json()
        except httpx.RequestError as exc:
            raise RuntimeError(f"{self.name} API request failed ({type(exc).__name__})") from None
        except ValueError:
            raise RuntimeError(f"{self.name} API returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise RuntimeError(f"{self.name} API returned a non-object JSON payload")
        return payload
