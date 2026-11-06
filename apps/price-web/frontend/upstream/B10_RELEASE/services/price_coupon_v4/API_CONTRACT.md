# CDH-COUPON-PRICE-V4 local API contract

## Search

`GET /api/v4/products?q=&page=1&limit=20`

Envelope fields: `schema_version`, `data_classification`, `items`, `page`, `limit`, `total`, `data_version`. Each item is a V4 product object defined by `schema/cdh_coupon_price_v4.schema.json`.

## Detail

`GET /api/v4/products/{series_key}`

Fields: `schema_version`, `data_classification`, `product`, `history`, `history_quality`, `data_version`.

`history.before_coupon` and `history.confirmed_after_coupon` are distinct raw observations. Each quality object supplies `raw_sample_count`, `daily_representatives`, and `truncated`. Histories are limited to 500 items and a bounded scan of 5,000 rows.

The API is opt-in and synthetic/offline only. It does not replace or alter V2/V3 endpoints.
