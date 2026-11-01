# Source setup and verified limits

Research checked 2026-11-01. Credentials belong to the operator of the self-hosted
service. Set them in its environment or local `.env`; never send them from browser
clients or commit them. `GET /extractors` lists implemented extractors, not account
authorization status. Selecting an unconfigured credentialed source returns an
error. None of these integrations bypasses authentication, CAPTCHAs, or denied
access. HTTP 429 is reported without an automatic retry storm.

| Vendor | Extractor | Access | Verification |
| --- | --- | --- | --- |
| aitendo | `aitendo` | Keyless public HTML search | Live search and product cards verified |
| DigiKey | `digikey` | Official Product Information v4, OAuth2 | Official contract + mocked transport; no production account used |
| Mouser | `mouser` | Official Search API | Official contract + mocked transport; no production account used |
| AliExpress | `aliexpress` | Official TOP affiliate product query | Official contract + mocked signing/transport; no approved account used |
| Akizuki | Unsupported | Permission required for broader content reuse | Official search, robots, and terms reviewed |
| Marutsu | Unsupported | No verified usable public catalog API | Direct search returned HTTP 403; no bypass attempted |

## aitendo

No credentials are required. The extractor performs one `robots.txt` request and
one GET to the store's [public search form](https://www.aitendo.com/product-list?keyword=ESP32),
then reads product cards from the first page. It uses an identified
`global-product-search/0.1` user agent, respects applicable robots disallow rules,
and stops on denied access or an unrecognized page. There is no bulk crawl,
parallel pagination, cookie import, or anti-bot workaround.

The page's displayed tax-inclusive JPY price is used only when it is a single
unambiguous amount. Ranges and products without that amount have `price: null`.
The first page may contain at most 30 products even when a larger limit is asked
for. HTML is an unstable interface; a successful live check is not an uptime or
reuse guarantee. Review the store's [disclaimer](https://www.aitendo.com/page/26),
[usage guide](https://www.aitendo.com/help), and [robots policy](https://www.aitendo.com/robots.txt)
before operating a public service. The store does not publish an API SLA or a
numeric automation quota; keep usage modest and stop if access is restricted.

## DigiKey

Set `DIGIKEY_CLIENT_ID` and `DIGIKEY_CLIENT_SECRET` from an application subscribed
to Product Information v4. Production requires an organization and approved
production access. The extractor obtains a two-legged `client_credentials` token,
caches it in memory until shortly before expiry, then uses
`POST /products/v4/search/keyword`. Credentials and tokens are not stored in
candidate payloads or included in errors. Restarting the process clears tokens.

Optional settings: `DIGIKEY_SITE=US`, `DIGIKEY_LANGUAGE=en`,
`DIGIKEY_CURRENCY=USD`. For Japanese results, use `JP`, `ja`, and `JPY`.
`DIGIKEY_SANDBOX=true` explicitly selects the official sandbox host. Sandbox data
is for development and must not be treated as a live inventory or price check.

Requests return the first page, capped at 50 products. Keyword search includes
standard pricing, not account-specific MyPricing. Product Information's published
standard quotas are 120 requests/minute and 1,000/day; actual application limits
and response headers take precedence. See [OAuth2, organization access, and quotas](https://developer.digikey.com/documentation)
and the [v4 keyword request/response contract](https://developer.digikey.com/products/product-information-v4/productsearch/keywordsearch).

## Mouser

Set `MOUSER_API_KEY` to the Search API key issued for your My Mouser account.
The extractor uses `POST https://api.mouser.com/api/v1/search/keyword` with
`SearchByKeywordRequest`, requesting at most 50 results from the first page.
The documented service permits 30 calls/minute and 1,000/day. Account approval,
terms, regional pricing, and quota still apply.

The API requires the key in the URL query. The built-in HTTP logger redacts that
parameter, and errors omit response bodies, which could reflect secrets. Any
operator-provided HTTP tracing or outbound proxy must also protect query strings.
Price comes from the smallest quantity price break, and that quantity remains in
the raw product payload. Ambiguous localized number formats return `price: null`.
It is not a guarantee of single-unit availability or landed cost.

See [Search API enrollment, data, and limits](https://www.mouser.com/en/api-search/)
and the [official V1 OpenAPI contract](https://api.mouser.com/api/docs/V1).

## AliExpress

Set `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_APP_SECRET`, and `ALIEXPRESS_TRACKING_ID`
from an approved affiliate/publisher application. This integration searches the
affiliate catalog, not the entire consumer marketplace. A seller or dropshipping
application is not a substitute for affiliate product-query permission.

The extractor implements the official documented TOP method
`aliexpress.affiliate.product.query` over HTTPS at
`https://eco.taobao.com/router/rest`, signing sorted form parameters with HMAC-MD5
and a GMT+8 timestamp. The app secret is used locally and is never transmitted.
Optional settings are `ALIEXPRESS_CURRENCY=USD`, `ALIEXPRESS_LANGUAGE=EN`, and
`ALIEXPRESS_COUNTRY=US`. It requests the first page with at most 50 products and
returns the product detail URL, not a generated affiliate link.

Price uses the returned target sale amount and target currency. Shipping, stock,
variant selection, discounts, and checkout totals can differ. Permissions,
geography, quotas, and gateway compatibility depend on the approved application;
no universal quota is claimed. This was checked against the [official product query reference](https://developer.alibaba.com/docs/api.htm?apiId=45803)
and [official TOP signing documentation](https://developer.alibaba.com/docs/doc.htm?articleId=101617&docType=1&treeId=153).
Live account access was not available for verification.

## Akizuki — unsupported

The official [search page](https://akizukidenshi.com/catalog/goods/search.aspx) is
public and its [robots file](https://akizukidenshi.com/robots.txt) was reachable.
However, sections 8–10 of the [official terms](https://akizukidenshi.com/catalog/pages/terms_of_service.aspx)
restrict use, copying, and downloading beyond personal noncommercial use without
written permission, and limit modification and redistribution. No documented
product-search API or broader reuse permission was found in the reviewed official
materials. The project therefore does not ship a general-purpose extractor or
invent an Akizuki candidate from a search URL. Obtain appropriate permission and
a supported data interface before adding one.

## Marutsu — unsupported

The [official public search interface](https://www.marutsu.co.jp/GoodsListNavi.jsp?display=goodsname&q=ESP32)
and [terms](https://www.marutsu.co.jp/pc/static/large_order/riyoukiyaku) were reviewed.
Direct unauthenticated requests from the verification environment returned HTTP
403. The [robots policy](https://www.marutsu.co.jp/robots.txt) was reachable, but
robots visibility is not authorization to evade denied access. No documented,
usable product-search API was verified in official materials. This is a verified
access limitation, not a claim that Marutsu has no products or partner services.
No extractor, synthetic products, browser impersonation, or fallback search-link
candidates are supplied. Ask the vendor about authorized catalog access.
