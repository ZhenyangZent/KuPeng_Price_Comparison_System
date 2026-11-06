# N01 notification data contract

Contract: `CDH-N01-OFFLINE-ALERT-1`

## Boundary

N01 accepts only an in-process C01 `Decision` whose approval seal verifies, or
an I01 `IntegrationResult` with `status=QUEUED` containing that decision and its
exact `PurchaseScenario`. C01 approval is checked before persistence because the
seal is intentionally process-private. N01 then persists a derived, immutable
candidate and never claims that the persisted record can recreate the C01 seal.

The only allowed source kind is `SYNTHETIC`. Its `source_status` remains
`SOURCE_BLOCKED`; the synthetic test authorization does not upgrade real source
permission. `MockSink` and a path-confined local synthetic JSONL log are the only
enabled destinations.

## Required candidate fields

- Identity: `request_id`, `scenario_scope`, `user_policy_scope`, `offer_key`,
  `sku_id`, `quantity`, `minimum_quantity`.
- Authority: `decision_fingerprint`, `policy_evidence_fingerprint`,
  `cost_semantic_fingerprint`, `policy_epoch`, `source_revision`.
- Context: `membership_context`, `eligibility_profile_version`, stock and
  user/notification enablement.
- Complete cost: total, subtotal, shipping, fees, tax, coupon discount and
  coupon expiry. Unknown required values fail closed.
- Time: aware `observed_at`, message `expires_at`, and optional coupon expiry.
- Display: `decision_reason` and labels. `TARGET_REACHED`, verified discount and
  low absolute price remain separate categories.

## Shared gate

`free_shipping_gate()` is the sole gate used by both immediate dispatch and the
daily digest. It rereads the latest state and requires exact scenario, SKU,
quantity, membership, eligibility profile, policy epoch and source revision.
It also verifies stock, enablement, source availability, event/coupon expiry,
the complete-cost equation, minimum quantity and zero-total provenance.

Free shipping requires known shipping of zero. Paid shipping may pass only for
an upstream `O1` or `O2` decision with a reliable same-scenario baseline whose
complete total is greater than the current complete total.

## Delivery semantics

SQLite commits event identity, episode and outbox atomically. Request ID reuse
with different payload is a conflict. Identical requests are idempotent across
restart. A rebound closes the current episode; the next qualifying drop opens a
new episode. Workers use renewable leases, recover stale leases and persist
every retry. Local sinks deduplicate by `event_id`, but N01 explicitly makes no
external exactly-once claim.

## Proposed product integration

A future authorized adapter may map the frozen payload to Windows Toast or
Telegram. It must preserve `event_id` as the idempotency key, return accepted /
receipt / ambiguous states, and submit through this outbox. It may not bypass
the shared gate or read credentials until separately authorized.
