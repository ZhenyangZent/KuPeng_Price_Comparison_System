# C01 R01 Identity, Migration, and Outbox Contract

## Identity chain

`OfferIdentity.key`, `PurchaseScenario.scope_key`, history series, quote fingerprint, decision fingerprint, current-state row and event semantic key use NFC-normalized canonical JSON and SHA-256. The scenario binds offer/seller/SKU, context, fixed quantity, membership, eligibility profile, coupon plan, price basis, purchase channel and payment method.

The policy requires a time-bounded `PolicyContext` bound to that same scope. `PricingInput` requires explicit evaluation/expiry times and a non-`UNVERIFIED` quote evidence ID. A baseline is usable only when its recomputed history-series key, full scenario fields, event time and freshness all validate.

## Schema 1 to schema 2

Migration is transactional. Existing schema-1 business tables are renamed to `*_v1_archive`; new schema-2 active tables start empty. This preserves old rows for audit while preventing an old queued event or partial identity from being silently interpreted using schema-2 semantics. The migration test checks retained archive payloads and an empty active event/outbox pair.

## Idempotency and deduplication

- The same `request_id` plus byte-equivalent canonical request payload returns the original event.
- The same `request_id` with a divergent payload raises `IdempotencyConflict` without mutation.
- Caller `dedupe_key` is retained only for audit. It does not define uniqueness.
- The semantic key binds scenario scope, quote fingerprint, total, and availability version. Same verified state remains deduplicated across restart and after 24 hours; elapsed time alone never forces a resend.
- A lower verified quote produces a different semantic key. A valid restock must carry a new evidence-backed `availability_version`. A policy severity-only change at the same quote does not create another event.
- Terminal event/outbox rows are retained for audit for at least 24 hours. This core does not implement automatic pruning; retention never authorizes replay.

## Delivery state machine

`QUEUED → IN_FLIGHT → DELIVERED | DELIVERY_UNKNOWN | FAILED`. Expiry or failed pre-send revalidation yields `EXPIRED` or `SUPERSEDED` before the sink is called.

The claim transaction stores a token and 30-second lease, commits, and releases the process writer lock before invoking the mock sink. Finalization checks the token and current state in a new transaction. If state changes after the claim while the sink may have accepted the payload, the safe result is `DELIVERY_UNKNOWN`.

No external channel can be atomically committed with SQLite. C01 therefore does not claim globally atomic or exactly-once delivery. Only `MockSink` exists in scope; retry/backoff and real notification adapters remain prohibited.
