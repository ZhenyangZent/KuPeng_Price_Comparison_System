# CDH-COUPON-PRICE-V4 local API contract

## Search

`GET /api/v4/products?q=&page=1&limit=20`

Envelope fields: `schema_version`, `data_classification`, `items`, `page`, `limit`, `total`, `data_version`. Each item is a V4 product object defined by `schema/cdh_coupon_price_v4.schema.json`.

## Detail

`GET /api/v4/products/{series_key}`

Fields: `schema_version`, `data_classification`, `product`, `history`, `history_quality`, `data_version`.

Machine schemas are frozen in `schema/cdh_coupon_price_v4_search.schema.json`, `schema/cdh_coupon_price_v4_detail.schema.json`, and `schema/cdh_coupon_price_v4.schema.json`. Search items deliberately do not embed `schema_version`; Detail deliberately keeps history at the envelope level.

`history.before_coupon` and `history.confirmed_after_coupon` are distinct raw observations. Each quality object supplies `raw_sample_count`, `daily_representatives`, and `truncated`. Histories are limited to 500 items and a bounded scan of 5,000 rows.

The API is opt-in and synthetic/offline only. It does not replace or alter V2/V3 endpoints.

## Loopback boundary

The reference server binds only `127.0.0.1`. Host must be `127.0.0.1` or `localhost`. Browser Origin is rejected unless explicitly configured as an `http` loopback origin with a port. The recommended A-line integration is a strict same-origin proxy, in which case the proxy-to-B11 GET has no Origin header and B11 emits no CORS header. Configured CORS echoes the exact allowlisted origin and never emits `*`.
