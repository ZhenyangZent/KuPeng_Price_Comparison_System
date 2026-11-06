# B08 price-quality adapter

This standard-library-only module opens an explicitly authorized SQLite snapshot using `mode=ro` and `PRAGMA query_only=ON`. A SHA-256-bound authority sidecar is mandatory. It refuses private data, mixed classifications, schema drift, contract drift, paths outside the allowed root, and link/reparse traversal.

The adapter preserves the exact B06 `CDH-WEB-CONTRACT-V2` response shapes. New quality information is available only through the additive `CDH-PRICE-QUALITY-ADAPTER-V3` route. Conditional/coupon prices, expired/revoked sources, incomplete identities, current Taipei day samples, future samples, and unverifiable observations fail closed.

R05 freezes two distinct low-price meanings. V2 `observation_period_min_twd` is the minimum valid raw price among the history records returned in that same response (at most 500); it is `null` when history is empty. V3 `period_low_twd` remains the minimum completed-day representative price. They must not be substituted for one another.

Daily quality metrics use a thread-safe 256-entry LRU cache keyed by series, UTC minute and current source-permission result. Permission expiry therefore invalidates the relevant entry. Raw history remains a direct indexed SQLite query and is never cached as an unbounded collection.

This is an offline candidate. It is not a public API, not a production database migration, and does not authorize Coupang collection or affiliate operation.
