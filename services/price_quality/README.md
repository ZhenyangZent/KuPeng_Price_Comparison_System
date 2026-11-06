# B07 History Quality Read Model

This is an isolated, offline, read-only analysis module. It does not modify or import `services/price_query`, D04, D01 or any formal user database.

The reader accepts only a normal SQLite file below an explicit allowed root plus a sidecar authorization descriptor whose SHA-256 exactly binds that copy. The descriptor must declare either `USER_AUTHORIZED_COPY` or `SYNTHETIC_FIXTURE`; mixed, unauthorized, private-field-bearing or schema-incompatible copies fail closed.

## CLI

```powershell
$env:PYTHONPATH = "services/price_quality"
python -m price_quality.cli --database-copy <isolated.sqlite3> --authorization <authorization.json> --allowed-root <isolated-root> --as-of 2026-11-05T04:00:00Z --output <isolated-root>\DATA_QUALITY_REPORT.json
```

The schema is documented in [SCHEMA.md](SCHEMA.md). Output contains only identity, aggregated price-quality information, source-kind counts and the database hash; it does not copy source URLs, account data, cookies, credentials or unselected columns.

The period low is labeled `觀測期間低點（非成交價）`. Zero remains a numeric price observation and never turns unknown shipping into free shipping. Current Taipei-day events are excluded from historical baselines.
