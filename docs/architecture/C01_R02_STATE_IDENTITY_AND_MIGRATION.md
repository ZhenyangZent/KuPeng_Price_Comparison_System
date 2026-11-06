# C01 R02 State, Identity, and Migration Contract

## Current-state ordering

`current_state` is ordered by the trusted source `observed_at` timestamp inside one `BEGIN IMMEDIATE` transaction. An older observation raises `StaleCurrentState`; an identical retry at the same timestamp is a no-op; a divergent payload at the same timestamp raises `CurrentStateConflict`. `received_at` cannot precede `observed_at`.

## Audit identity versus notification identity

`quote_fingerprint` retains evidence identity for audit and enqueue binding. `semantic_fingerprint` excludes volatile evidence IDs and clocks, but includes scenario scope, exact price components, validated adjustments, included fees, and pricing/coupon rule versions. Notification deduplication binds the semantic fingerprint, total, availability epoch, current-state rule revision, and the user-target reason class.

## Delivery revalidation

Every queued event stores the semantic fingerprint, availability epoch, and current-state rule revision seen at enqueue. Both pre-callback and post-callback validation compare those bindings with the current state. A mismatch becomes `SUPERSEDED` before the mock callback, or `DELIVERY_UNKNOWN` if state changed during the callback.

## Historical baseline provenance

Baseline freshness is derived from the latest observation in the completed Taipei calendar days that actually contribute to M30. The snapshot carries M7/M30/M90 coverage, contributing observation count, last contributing timestamp, last eligible local day, scenario/series bindings, and the approved calculation version. The policy boundary independently rejects insufficient, inconsistent, stale, future, or unapproved snapshots.

## Schema v3 migration

Schema v3 adds semantic quote identity and event epoch/rule bindings. Active v1 or v2 tables are renamed to versioned `_v1_archive` or `_v2_archive` tables within the migration transaction. A fresh v3 active schema is then created. Old queued rows are preserved for evidence but are not activated under incompatible semantics.
