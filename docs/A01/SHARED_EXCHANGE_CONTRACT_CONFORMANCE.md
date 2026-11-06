# Shared Exchange Contract Conformance

Contract: frozen `CDH-EXCHANGE-1` from `03_FROZEN_SHARED_EXCHANGE_CONTRACT_V1.md`. A01 did not alter the contract.

## A01 submission

| Field | A01 rule | Result |
|---|---|---|
| `schema_version` | exact `CDH-EXCHANGE-1` | PASS |
| `submission_id` | canonical lowercase UUID; filename derived only from validated UUID | PASS |
| `record_type` | `USER_PRICE_OBSERVATION` or contract `PROMO_CLUE` validation | PASS |
| `created_at_utc`, `observed_at_utc` | timezone-aware UTC; excessive future times rejected | PASS |
| `source.source_kind` | closed A01 set; manual form uses `USER_ENTERED`, CSV uses `USER_FILE` | PASS |
| `source.permission_scope` | strictly bound to source kind | PASS |
| `source.url` | optional; approved TW Coupang host only; never fetched or opened | PASS |
| `offer.displayed_price_twd` | integer TWD; explicit 0 allowed; null/blank/bool/float/NaN/Infinity rejected | PASS |
| `offer.price_basis` | manual evidence remains `DISPLAYED_UNKNOWN` | PASS |
| shipping/stock/coupon/account/fee | default `UNKNOWN`; consistency constraints reject contradictory fee evidence | PASS |
| `is_synthetic` | strictly bound to `SYNTHETIC_TEST`; UI labels synthetic rows | PASS |

Atomicity: the submission is serialized with `allow_nan=False`, bounded to 1 MiB, flushed and `fsync`ed to a same-directory temporary file, then created atomically without replacing an existing UUID. Windows uses the non-overwriting atomic rename behavior; POSIX uses same-filesystem link creation.

## D01 snapshot

A01 reads only `data/exchange/snapshots/latest.json`, bounded to 50 MiB. It requires contract version, `D01_LOCAL_LEDGER`, UTC generation time, non-negative counts, required item fields, and `SOURCE_BLOCKED`. Stale snapshots are labelled; equal or older snapshots cannot replace a newer in-memory view.

The test `test_independent_contract.py` intentionally validates A01 output with a parser that does not import A01's schema validator. The supplied synthetic D01 fixture is also parsed and rendered.
