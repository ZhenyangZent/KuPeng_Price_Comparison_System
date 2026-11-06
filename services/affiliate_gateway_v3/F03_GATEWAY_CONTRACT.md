# F03 Gateway Contract

## Provider adapter

Input is `product + exact variant + seller + original platform URL`; output is status, official evidence IDs, verified destination, expiry, bound identity, disclosure and revocation readback. The interface defines no Taiwan API endpoint and never opens either URL.

## Production state

Current C04 readiness is `SOURCE_AUTHORIZATION_REQUIRED`. The gateway therefore does not call the adapter and preserves the B06 V2 nested wire with `click_url=null`, `verified_product_match=false`, and `bound_product_id=null`. `cta_enabled` is a separate backend decision and remains false.

## URL and cache boundaries

- Original platform URL and verified affiliate destination are distinct fields.
- Original URL rejects manually inserted affiliate/tracking parameters.
- Both URLs require exact approved HTTPS host/path, no userinfo, fragment, redirect parameter, redirect-alias path, malformed port, or host suffix trick.
- Cache key binds platform, provider product, variant, seller and original URL hash. A SKU or seller change is a miss.
- A cached result requires a future expiry plus a non-empty revocation event ID and fresh `ACTIVE` revocation readback. Missing/stale/revoked results are evicted and cannot be reused.

## B06/A06 compatibility

The external response keeps the exact B06 V2 nested four-field Affiliate object. A06 currently has an empty official-host policy, so current production remains non-clickable. Future frontend trust metadata requires Central Orchestrator approval; see `reports/F03/PROPOSED_CONTRACT_CHANGE.md`.

## Non-click proposal

UI may distinguish `GENERAL_OFFICIAL_PRODUCT_REFERENCE` from `VERIFIED_AFFILIATE_DESTINATION`, but neither is clickable under current authority. This proposal must not be interpreted as permission to enable a normal product-link CTA.
