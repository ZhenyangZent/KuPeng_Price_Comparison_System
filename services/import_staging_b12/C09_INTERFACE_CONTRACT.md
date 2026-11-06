# B12 ↔ C09 provenance interface

PRIMARY_REQUEST_SCHEMA: `CDH-B12-C09-GATE-REQUEST-1`

PRIMARY_RECORD_SCHEMA: `CDH-B12-STAGING-RECORD-PROPOSAL-1`

PRIMARY_DECISION_SCHEMA: `CDH-C09-PROVENANCE-DECISION-1`

B12_BUNDLE_SCHEMA: `CDH-B12-C09-REQUEST-BUNDLE-1`

C09_RELEASE_SHA256_OBSERVED: `a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7`

This is the exact interface proposed by C09 R08. B12 consumes `research.import_provenance_c09.verify_request(request, now=aware_datetime)` only after verifying that the importable `gate.py` and `__init__.py` are byte-identical to the supplied C09 release and that its CRC and payload manifest pass.

The B12 bundle adds only transport binding: exact input-file SHA-256, exact C09 release SHA-256, evaluation time, B12 canonical record SHA-256 and the C09 request. Before calling C09, B12 cross-checks record ID, full product/SKU/seller/condition/package identity, quantity, observation time, coupon identity/validity/profile, evidence ID and synthetic source ID.

Only `ALLOW_SYNTHETIC_PREFLIGHT` is accepted, and only when C09 also returns:

- `fixture_only: true`
- `canonical_write_authorized: false`
- `b11_mutation_authorized: false`
- `runtime_authorized: false`
- `cta_enabled: false`
- `click_url: null`
- `source_state: SOURCE_BLOCKED`

Missing C09, hash mismatch, schema mismatch, cross-binding mismatch, exception, denial or weakened invariants all become B12 `DENIED_PROVENANCE`. Approval enables only an immutable synthetic staging preview; it never authorizes real source collection, canonical persistence, B11 mutation, public display, affiliate activation or commerce.
