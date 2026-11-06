# B15 minimal API contract

- `GET /api/private-observations/v1/session`
- `POST /api/private-observations/v1/preview`
- `POST /api/private-observations/v1/confirm`
- `GET /api/private-observations/v1/products?q=&page=1&limit=20`
- `GET /api/private-observations/v1/products/{series_key}`

Mutation requests require `Content-Type: application/json`, `X-CDH-CSRF-Token`, strict duplicate-key-free JSON and a body no larger than 128 KiB. Preview returns the exact normalized record that would be saved plus a short-lived one-time token. Confirm requires exactly `preview_id`, `confirm_token`, and `explicit_confirm=true`.

Replay is idempotent by submission ID and canonical observation fingerprint. A submission ID reused with different content returns conflict. New commits are transactional; an existing database is backed up with SQLite backup before each new commit. Restore is an offline operator action: stop the service, verify the selected backup with `PRAGMA integrity_check`, preserve the current database, then copy the backup into the fixed database location. No request can select or restore a path.

REV2 filesystem boundary: callers must bind `ObservationStore` to an explicit existing project root. All existing ancestors and targets are no-follow checked for symlinks, junctions and reparse points before and after creation/open operations. Lexical and resolved paths must remain under that root. Missing Host fails with `HOST_REQUIRED`.

Retention: previews default to 600 seconds, 128 entries and 2 MiB total. Backups default to 8 files, 30 days and 256 MiB total, with two newest recovery points preferred. Capacity failure aborts the new commit before observation mutation.
