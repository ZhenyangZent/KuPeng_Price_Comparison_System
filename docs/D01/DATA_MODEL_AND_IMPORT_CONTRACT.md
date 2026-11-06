# D01 data model and import contract

`raw_submissions`, `observations`, and `leads` are protected by SQLite triggers that reject update and delete operations. This is an application-level append-only control, not a claim that a person with filesystem access cannot modify SQLite bytes.

- `raw_submissions`: submission identity, exact incoming byte SHA-256, sanitized canonical JSON, source, receipt time, and schema.
- `observations`: price observation facts. Synthetic records remain marked. Qualification is fixed to `UNVERIFIED` in D01.
- `leads`: promotional claims, separate from observations and price history.
- `source_permissions`: versioned `(source, operation, reviewed_at)` evidence. Only exact `APPROVED` permits an automated feed operation.
- `ingest_attempts`: imported, duplicate, and quarantined attempts.
- `quarantine`: malformed or conflicting document evidence without overwriting accepted content.
- `snapshots`: versioned snapshot SHA-256 and file identity.

SQLite uses foreign keys, WAL, `synchronous=FULL`, explicit transactions, indexes, uniqueness constraints, and a busy timeout. A failed transaction is rolled back. Lock contention is reported instead of retrying indefinitely or writing partial records.

The canonical exchange version is `CDH-EXCHANGE-1`. UTC is stored; the UI may display Asia/Taipei. `created_at_utc`, `observed_at_utc`, `published_at_utc`, and `imported_at_utc` have distinct meanings. Late observations append to history and do not overwrite newer rows.

Product URL validation is syntax-only and performs no network request. Observation URLs are limited to Coupang Taiwan hosts; sensitive and tracking query keys are discarded, fragments are removed, and only `itemId`, `vendorItemId`, and `productId` may remain.

