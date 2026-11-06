# B16 fixed private batch import API contract

Contract version: `CDH-B16-PRIVATE-BATCH-API-1`

The B16 application delegates every existing B15 route unchanged and adds exactly two mutation routes:

- `POST /api/private-observations/v1/batch-preview`
- `POST /api/private-observations/v1/batch-confirm`

Both require an allowed loopback `Host`, an allowed `Origin` when supplied, `Content-Type: application/json`, and the existing session `X-CDH-CSRF-Token`. A missing Host is rejected. No request field can select a database or filesystem destination.

## Preview request

```json
{
  "schema_version": "CDH-B16-BATCH-PREVIEW-REQUEST-1",
  "filename": "observations.json",
  "media_type": "application/json",
  "content_base64": "<strict base64 of the selected local file>"
}
```

`text/csv` requires a `.csv` filename. `application/json` requires `.json`. The decoded file limit is `1048576` bytes and the row limit is `500`. Preview never writes the database. A successful preview returns HTTP `200`, `can_confirm=true`, normalized row summaries, a short-lived `preview_id`, and a one-time `confirm_token`. Row validation failure returns HTTP `422`, `can_confirm=false`, row errors, and no confirmation credentials.

JSON files must use:

```json
{"schema_version":"CDH-B16-BATCH-FILE-1","observations":[<B15 observation>, ...]}
```

Duplicate members are rejected at every JSON object depth. CSV requires the exact ordered header from `examples/valid_two_day.csv`. Empty nullable CSV values map to JSON null; integers must use unsigned base-10 syntax.

## Confirm request

```json
{
  "schema_version": "CDH-B16-BATCH-CONFIRM-REQUEST-1",
  "preview_id": "<preview response value>",
  "confirm_token": "<preview response value>",
  "explicit_confirm": true
}
```

Confirm atomically claims the preview token before entering the database write path. Only the request that changes the token from `AVAILABLE` to `IN_FLIGHT` may commit. A simultaneous reuse receives HTTP `409` with `CONFIRMATION_ALREADY_IN_PROGRESS`.

Confirm revalidates database state and commits all new unique observations in one SQLite transaction. A reused submission ID with different content rejects the entire transaction. Exact input duplicates and existing fingerprints are idempotent. A failure rolls back observation and audit writes, then terminalizes that token as `FAILED`; retrying it receives HTTP `409` with `CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED`. Recovery requires a new preview, whose confirm retains the existing idempotent replay semantics. Existing databases receive one integrity-checked pre-commit backup through the B15 REV2 path boundary.

REV3 first-write recovery: when no database exists, B16 durably creates and validates an empty B15 schema before beginning the observation/audit transaction. A later injected write failure therefore rolls back all batch rows while retaining a valid empty database; a fresh preview remains available. Existing databases and backups are never deleted by this recovery path.

REV2 compatibility: route names, request schemas, success responses and A15 integration fields are unchanged. Only concurrent or post-failure reuse of the same token gains the explicit HTTP `409` error contract.

Coupon values remain `USER_REPORTED`; `confirmed_after_coupon_price_twd` is always null and `platform_verified` is always false. Source is fixed to `USER_ENTERED` and `PRIVATE_LOCAL` by the inherited B15 validator.

