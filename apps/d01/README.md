# CDH D01 local data foundation

This package is a standard-library-only, local SQLite ledger for `CDH-EXCHANGE-1`. It does not contain a browser, HTTP client, crawler, notification sender, Registry access, Firefox access, cart operation, coupon operation, or transaction operation.

## Commands

Run from the project root with Python 3.12 or a compatible Python 3 version:

```powershell
python apps/d01/d01_cli.py --db data/d01/observations.sqlite3 init-db
python apps/d01/d01_cli.py --db data/d01/observations.sqlite3 seed-permissions --matrix reports/D01/SOURCE_PERMISSION_MATRIX.csv
python apps/d01/d01_cli.py --db data/d01/observations.sqlite3 ingest C:\path\selected.json
python apps/d01/d01_cli.py --db data/d01/observations.sqlite3 ingest C:\path\selected.csv
python apps/d01/d01_cli.py --db data/d01/observations.sqlite3 scan-inbox data/exchange/inbox
python apps/d01/d01_cli.py --db data/d01/observations.sqlite3 snapshot --output data/exchange/snapshots
```

JSON is capped at 1 MiB. CSV is capped at 50 MiB and 10,000 rows and is processed row-by-row. Each bad row or document is quarantined without changing a previously accepted submission. An identical `(submission_id, raw SHA-256)` replay is a no-op; the same ID with different bytes is a conflict.

Money must be a JSON integer in TWD; booleans, floats, negative values, NaN, infinity, blank strings, and `null` observation prices are rejected. Zero is allowed only when explicitly supplied as integer `0`; it remains `UNVERIFIED`. Unknown shipping, stock, coupon, account eligibility, and mandatory fee values are never filled with favorable defaults.

CSV field text is never evaluated. Spreadsheet-formula-looking product names remain inert database strings. Reports that use CSV prefix formula-leading text with an apostrophe.

## Snapshot reader contract

D01 writes a same-directory temporary file, flushes it, and atomically replaces `latest.json`. Windows can briefly return a sharing violation if another process opens the path at the exact replacement instant. A01 readers must retry a transient `PermissionError`; any successful read is a complete old or new JSON document, never a half-written file. Versioned snapshots remain available for rollback.

## Authority boundary

`source_status.live_coupang_discovery` is always `SOURCE_BLOCKED`. `APPROVED_FEED` records must name a source whose current `AUTOMATED_INGEST` permission row is exactly `APPROVED`; this release contains no such row. Official announcements may be entered only as `PROMO_CLUE` and are excluded from observation history.

## D02 explicit local sync

From the project root, preview without persistent writes:

```powershell
scripts\d02\run_local_sync.ps1 --dry-run --pretty
```

The operator may then explicitly run one local cycle with the same command minus `--dry-run`. No watcher, service, Scheduled Task, external fetch, notification, or commerce action is installed or started. See `docs/D02/OPERATOR_GUIDE.md`.

