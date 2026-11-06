# F02 V2 Binding Contract

## Input boundaries

1. B06 input must be the exact nested `CDH-WEB-CONTRACT-V2` Affiliate envelope. Flattened V1, extra/missing fields, a pre-existing URL, verified claim, or non-null `bound_product_id` is rejected and produces no API response.
2. `CanonicalIdentity.canonical_product_id` is the B06 partition ID used for UI navigation. Provider product／variant／seller IDs are separate inputs from the selected exact B06 offer and never replace the canonical ID.
3. C03 and F01 are loaded from explicit regular local JSON files. Runtime code does not search for `.env`, credentials, browsers, Registry, or remote endpoints.

## Output

For structurally valid B06 input, output preserves its classification and exact nested shape:

```json
{
  "schema_version": "CDH-WEB-CONTRACT-V2",
  "product_id": "<B06 canonical ID>",
  "data_source_status": "USER_RECORDED_ONLY",
  "data_classification": "USER_RECORDED",
  "contract_compatibility": ["CDH-WEB-CONTRACT-V1"],
  "affiliate": {
    "state": "SOURCE_AUTHORIZATION_REQUIRED",
    "click_url": null,
    "verified_product_match": false,
    "bound_product_id": null
  }
}
```

`ui_cta_state` is returned separately by the binding result. Search/detail navigation may remain available while CTA is disabled. Only a fully verified outcome sets `bound_product_id` to the B06 canonical ID.

## Enable gates

All conditions are conjunctive: C03 provider state and six link capabilities must be `RUNTIME_VERIFIED`; each capability needs runtime enablement and evidence; account, market, official host/path, authority expiry, TTL/revocation, disclosure, provider source, user intent, and exact provider product/variant/seller must match. Any failure clears URL, match, and binding.

No V1 fallback, direct product URL, old affiliate URL, redirect parameter, redirect-alias path, wildcard host, userinfo, non-HTTPS scheme, non-443 port, fragment, or authority-expired link is accepted.

## Audit log

`audit_summary` contains stable reason codes, state, hashes of identities, URL host, a path hash, and a boolean indicating that query data was redacted. It never records the full URL, query values, disclosure text, raw IDs, cookies, credentials, or account identifiers.
