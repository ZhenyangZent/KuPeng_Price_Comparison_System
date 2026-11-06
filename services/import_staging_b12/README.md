# B12 isolated import staging

This module performs an immutable, offline preflight of explicitly provided CSV or JSON observations. It never writes B11 fixtures, a formal user database, or any SQLite file. It grants no collection or product-source authority.

## Default-deny dry run

```powershell
$env:PYTHONPATH='services/import_staging_b12'
python -m import_staging_b12 --input services/import_staging_b12/fixtures/synthetic_valid.json --allowed-root services/import_staging_b12 --as-of 2026-11-05T04:00:00Z
```

Without an exact C09 request bundle and release, every otherwise valid record receives `DENIED_PROVENANCE / C09_VERIFIER_UNAVAILABLE`. This is intentional.

The C09 bridge is invoked with both `--c09-request-bundle` and `--c09-release`. B12 verifies the release SHA-256, CRC, manifest and byte identity of the importable C09 gate before calling the exact `verify_request` interface. The included bridge fixtures are synthetic-only and produce a preview, never a database write.

## Formats and limits

- JSON input is an array of exact `CDH-B12-IMPORT-RECORD-1` objects.
- CSV uses the exact dotted headers exported as `CSV_FIELDS` in `staging.py`; missing or extra headers fail closed.
- Input must be below the explicit `--allowed-root`, must not traverse a symlink/reparse point, is limited to 2 MiB and 10,000 rows.
- `--as-of` is mandatory and UTC `Z`, making chronology validation reproducible.
- `--require-all-accepted` returns exit code 3 unless every row is uniquely accepted for preview.

The output is a versioned JSON report. `database_write_count` is always zero and `collection_authorized` is always false.
