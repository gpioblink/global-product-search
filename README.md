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
Extractor self-tests use the real upstream APIs, so `uv run pytest` expects any required credentials to be present.

## Usage

```bash
uv run gps --list-extractors
uv run gps search "4901234567894"
uv run gps search "SM-S928B" --json
```

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
