# B13 preview contract

DTO_SCHEMA: `CDH-B13-DRYRUN-PREVIEW-DTO-1`

STATUS_SCHEMA: `CDH-B13-PREVIEW-STATUS-1`

## Semantics

- Per-record `status`: `ACCEPTED_FOR_STAGING_PREVIEW`, `NOOP_DUPLICATE`, `CONFLICT`, `DENIED_PROVENANCE` or `INVALID_RECORD`.
- `field_errors` contains stable `{field, code}` objects only for rejected/conflicting records.
- `source` preserves bounded source candidate/evidence metadata; `raw_record_sha256` binds the source row while `raw_content_included` remains false.
- `history_candidates` contains only uniquely accepted records, grouped by exact identity hash and sorted by observation time. It is not canonical history.
- `safety.database_write_count`, `b11_write_count` and `formal_history_write_count` are always zero.
- `live_source_authorized`, `collection_authorized`, and `cta_enabled` are always false; `click_url` is null.
- CSV cells beginning after whitespace with `=`, `+`, `-`, or `@`, and undeclared extra columns, are per-row invalid.

The status API paginates records and history separately. It is a local read-only view of a precomputed preview, not an upload or mutation endpoint.
