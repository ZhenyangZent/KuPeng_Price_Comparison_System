# B08 local price query v3 adapter

`PriceQueryV3App` is a local WSGI candidate. It preserves B06 Search, Detail, History and Affiliate V2 JSON exactly while exposing additive quality evidence at `GET /api/v3/quality/{series_key}`. It supports bounded SQL pagination and an ETag-like immutable snapshot version; only the quality route accepts `If-None-Match` for `304`.

There is no CORS header, redirect, outbound request, write endpoint, notification, affiliate click, coupon, cart, order, or payment action.

All normal, error and `304` responses include fail-closed CSP, no-referrer, deny-frame, nosniff and restrictive Permissions-Policy headers. No wildcard CORS header is emitted.

V2 `observation_period_min_twd` is defined only over the valid raw `history` items visible in the same response. The list is capped at 500 and may not represent an all-time low. V3 quality uses a separate completed-day representative-price low.
