# CDH Affiliate Trust Envelope Candidate 1

STATUS: `CANDIDATE_FOR_ORCHESTRATOR_REVIEW`

## Authentication and binding

The envelope is canonical JSON authenticated with backend-only `HS256`; `kid` supports rotation, each key has an explicit permitted fixture class, and the key is injected by the future backend, never read from `.env` by this module and never sent to A. A fixture key cannot sign `OFFICIAL_RUNTIME`. Claims bind provider, market, canonical product, provider product, SKU, seller, original URL SHA-256, verified destination, issue/expiry, official evidence IDs, revocation event/readback, Taiwan disclosure and nonce.

## V2 preservation

`CDH-WEB-CONTRACT-V2` remains byte-field compatible at schema level. Its Affiliate object stays exactly `state`, `click_url`, `verified_product_match`, `bound_product_id` and remains disabled under current authority. F04 does not add trust fields to V2.

The proposed `CDH-AFFILIATE-TRUST-SIDECAR-CANDIDATE-1` is a separate backend view model keyed by canonical product ID. A future trusted backend verifies the envelope and returns only the sidecar decision; A must never receive or verify the HMAC key. B continues producing canonical V2 unchanged. No network endpoint is defined or authorized here.

## Fixture ceiling

All F04 mock hosts end in `.invalid`. `CONTRACT_FIXTURE_TEST_ONLY` can prove envelope mechanics but always returns null click URL and disabled CTA. `OFFICIAL_RUNTIME` explicitly denies reserved non-production hosts and also requires separately authorized runtime account, credentials, capabilities, host/path policies, evidence, expiry, revocation and disclosure.
