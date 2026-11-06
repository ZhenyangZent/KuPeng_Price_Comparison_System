# B14 preview API contract

- DTO: `CDH-B14-STRICT-DRYRUN-PREVIEW-DTO-1`
- Status envelope: `CDH-B14-PREVIEW-STATUS-1`
- Endpoints: `GET /api/import-preview/v2/status` and `GET /api/import-preview/v2/history/<64-lowercase-hex>`
- Pagination: `page >= 1`, `1 <= limit <= 100`; unknown or repeated parameters fail closed.
- Host: `127.0.0.1` or `localhost`; server bind is fixed to `127.0.0.1`.
- Origin headers and all non-GET methods are rejected.
- Duplicate JSON member error: `JSON_DUPLICATE_KEY`; only full-input SHA-256 is returned.
- `ingress_policy.duplicate_json_keys_allowed` is always `false` for successful previews.
- Real source admission and CTA remain disabled.
