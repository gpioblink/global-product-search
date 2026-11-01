# global-product-search

Minimal Python CLI and library for product lookup with `yt-dlp`-style extractors.

## Requirements

- Python 3.11+
- `uv`
- credentials for whichever extractor you use

As of May 2, 2026, the built-in `rakuten` extractor requires both `RAKUTEN_APP_ID` and `RAKUTEN_ACCESS_KEY`.

## Setup

```bash
uv sync
cat <<'EOF' > .env
RAKUTEN_APP_ID=your_app_id
RAKUTEN_ACCESS_KEY=your_access_key
EOF
```

Environment variables are loaded automatically from `.env` when the package is imported, so `uv run gps ...` and library usage both pick them up.
Unit tests use mocked upstream transport and require no account credentials.
Live extractor smoke tests are opt-in; see [testing](#testing).

## Usage

```bash
uv run gps --list-extractors
uv run gps search "4901234567894"
uv run gps search "SM-S928B" --json
uv run gps search "genre:techbook 組み込みLinux"
uv run gps search "genre:generic,books-general Raspberry Pi"
uv run gps serve --host 127.0.0.1 --port 8000
```

Genre directives can be placed at the beginning of the query with `genre:` or `genre=`.
Use exact categories from `--list-extractors`, for example `generic`, `books-general`, `techbook`, and `electronic-parts`.
If no genre is specified, the engine defaults to `generic`.

To search only specific upstream sources, put `source:` or `source=` directives
before the search text, using exact names from `gps --list-extractors` or
`GET /extractors`:

```bash
uv run gps search "source:techbookfest genre:books-general Python"
uv run gps search "source:rakuten,rakuten_books Python"
```

Explicit sources override genre routing. Repeated directives and comma-separated
names select their union. The engine filters before scoring or calling upstream
extractors, and never falls back to another source. Unknown names reject the whole
request (HTTP 400); malformed or empty source directives also fail. No results
returns `[]`; an upstream runtime failure with no results returns HTTP 503.
Directives appearing after the first search token are literal search text.
`GET /` advertises `capabilities: ["source_filter"]`; clients that require strict
scoping should check that capability before sending a source directive to older servers.

## Web API

The CLI can also expose the same search capabilities over HTTP:

```bash
uv run gps serve --host 127.0.0.1 --port 8000
curl 'http://127.0.0.1:8000/extractors'
curl 'http://127.0.0.1:8000/search?q=SM-S928B&limit=5'
curl 'http://127.0.0.1:8000/search?q=SM-S928B&include_raw_payload=false'
```

Available endpoints:

- `GET /extractors` returns the extractor metadata shown by `--list-extractors`.
- `GET /search?q=<query>&limit=10` returns the same candidate fields as `gps search --json`.
- `GET /search?...&include_raw_payload=false` omits upstream payload blobs when you want a lighter response.

If you want to embed the API in another WSGI server, import `global_product_search.create_app()`.
The OpenAPI document is available at [openapi.yaml](openapi.yaml).

Browser clients can use `fetch(url, { credentials: "omit" })`. CORS defaults to
`Access-Control-Allow-Origin: *` and never permits credentialed browser requests.
Set `GPS_CORS_ORIGINS=https://example.com,https://other.example` to allow only
those exact origins; an empty value disables cross-origin access. An allowlist
adds `Vary: Origin` to successful, error, and preflight responses. Embedded apps
can pass `create_app(cors_origins=["https://example.com"])` instead.
CORS controls browser access; it does not authenticate the service. Keep upstream
credentials in the service environment and apply any desired API access controls
at your hosting boundary.

## Electronics sources

```bash
uv run gps search "source:aitendo ESP32"
uv run gps search "source:digikey NE555"
uv run gps search "source:mouser NE555"
uv run gps search "source:aliexpress ESP32"
uv run gps search "genre:electronic-parts ESP32"
```

These new extractors belong to `electronic-parts`, so ordinary queries retain the
existing `generic` routing. Explicit `source:` works without a genre directive.
Only actual product detail pages become candidates. Empty results stay empty;
store search pages are never substituted as product candidates. Prices can be
integers or decimals, with an optional `currency` code. A missing currency is
unknown; do not assume all sources use JPY. Prices and availability are indicative,
not checkout quotes. See [source setup and verified limits](docs/sources.md) for
all six researched vendors, including unsupported stores.

## Testing

```bash
uv run pytest
uv run pyright
GPS_RUN_LIVE_TESTS=1 uv run pytest tests/test_extractors.py -k aitendo
```

The first two commands require no provider credentials. Live tests are skipped by
default; when enabled, credentialed tests also skip if their required environment
variables are absent. Run all configured live cases with
`GPS_RUN_LIVE_TESTS=1 uv run pytest tests/test_extractors.py`. They contact upstream
services and count against the operator's quotas.

## Adding extractors

Add new extractors directly under `src/global_product_search/extractors/`.
Modules whose filenames start with `_` are ignored. Public extractor classes must end with `Extractor`.
Extractor implementations can import the small SDK surface from `global_product_search.sdk`:

```python
from global_product_search.sdk import BaseExtractor, ProductCandidate


class ExampleExtractor(BaseExtractor):
    name = "example"

    def supports(self, query):
        return 100

    def search(self, query, ctx):
        return [
            ProductCandidate(
                source=self.name,
                title=f"Echo: {query.raw}",
                url="https://example.com",
            )
        ]
```
