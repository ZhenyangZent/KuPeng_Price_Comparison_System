# B13 dry-run preview API and CLI

B13 consumes exact B12, C09 and B11 releases and produces a sanitized, immutable preview. It does not import into SQLite, B11 or any formal history database.

## Windows CLI

```powershell
$env:PYTHONPATH='services/import_staging_b13'
python -m import_staging_b13 `
  --input services/import_staging_b12/fixtures/synthetic_c09_bridge.json `
  --input-root services/import_staging_b12 `
  --dependency-root review/releases `
  --b12-release review/releases/CDH_B_R08_001_REVIEW.zip `
  --c09-release review/releases/CDH_C_R08_001_REVIEW.zip `
  --b11-release review/releases/CDH_B_R07_001_REVIEW.zip `
  --c09-request-bundle services/import_staging_b12/fixtures/synthetic_c09_request_bundle.json `
  --as-of 2026-11-05T06:00:00Z
```

Omit `--c09-request-bundle` to exercise the required default-deny behavior. `--require-all-accepted` returns exit code 3 if any record is invalid, denied, duplicate or conflicting.

## Loopback status API

Run `python -m import_staging_b13.server` with the same preview arguments plus `--port 8773`. The server binds only `127.0.0.1`; use `--check` to validate without opening a socket.

- `GET /api/import-preview/v1/status?page=1&limit=50`
- `GET /api/import-preview/v1/history/{identity_key}?page=1&limit=50`

The API is GET-only, default no-CORS, Host-restricted, paginated and no-store. It exposes source metadata and canonical record hashes, never the complete raw record or full local path.

Python 3.13 is the supported target syntax. The delivery environment had Python 3.12.7 only, so an actual 3.13 execution is reported `NOT_RUN_DEPENDENCY_UNAVAILABLE`; extracted replay remains independently reproducible with stdlib-only code.
