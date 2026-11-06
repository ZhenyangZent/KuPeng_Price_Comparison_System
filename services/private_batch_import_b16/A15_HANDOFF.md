# A15 fixed integration handoff

PINNED_B16_API_SCHEMA: `CDH-B16-PRIVATE-BATCH-API-1`

PREVIEW_ROUTE: `POST /api/private-observations/v1/batch-preview`

CONFIRM_ROUTE: `POST /api/private-observations/v1/batch-confirm`

The browser reads the user-selected file locally and sends its strict base64 bytes with the filename and one of the two allowed media types. A15 must not invent a filesystem path field or submit until the user presses the explicit confirmation control.

Preview HTTP `200` is confirmable and contains `preview_id` plus `confirm_token`. HTTP `422` contains row summaries and `row_errors`, has `can_confirm=false`, and must disable confirmation. HTTP `400`, `403`, and `409` are terminal request errors.

After confirm HTTP `201`, A15 can use the existing B15 product search and detail routes. HTTP `200` from confirm means the entire file was an idempotent replay and no new rows were inserted.

REV2 preserves every A15 request field and route. HTTP `409` with `CONFIRMATION_ALREADY_IN_PROGRESS` means another request already claimed the same token. HTTP `409` with `CONFIRMATION_FAILED_NEW_PREVIEW_REQUIRED` means the claimed database operation failed and the user must preview the file again; the failed token is never restored to reusable state.

REV3 changes only first-database initialization and does not alter A15 routes, request fields, response fields, or error handling.

Exact schemas, limits, CSV header, and response semantics are in `API_CONTRACT.md`, `openapi/b16.openapi.json`, and `examples/`.

