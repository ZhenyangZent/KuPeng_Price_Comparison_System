# CDH-WEB-CONTRACT-V2 frozen B-side DTO

## Classification

Every successful Search, Detail and Affiliate response contains both fields. Consumers must display the received value and must not infer one from the other.

- `data_source_status`: `USER_RECORDED_ONLY | SYNTHETIC_FIXTURE_ONLY`
- `data_classification`: `USER_RECORDED | SYNTHETIC_DEMO_ONLY`

The normal copied-data adapter emits `USER_RECORDED_ONLY` plus `USER_RECORDED`. The explicit E2E fixture adapter emits `SYNTHETIC_FIXTURE_ONLY` plus `SYNTHETIC_DEMO_ONLY`. Synthetic rows are never returned by the normal adapter.

## Endpoints

- `GET /api/v2/products?q=&page=1&limit=20`
- `GET /api/v2/products/{id}`
- `GET /api/v2/products/{id}/affiliate`

Search matches title, exact recorded product ID, variant/SKU ID, seller ID and the displayed variant signature. Matching only selects an already partitioned identity; it never combines product, variant, seller, quantity or source price basis.

Detail adds the same classification fields, completed-calendar-day M7/M30/M90 coverage, raw observation history and `觀測期間最低價`. `item_condition` is `UNKNOWN` with `item_condition_source=NOT_RECORDED` because the B05 fixture schema has no condition evidence. Price zero remains zero; it does not imply free shipping or zero checkout total.

Affiliate response is always nested:

```json
{
  "schema_version": "CDH-WEB-CONTRACT-V2",
  "product_id": "p_...",
  "data_source_status": "USER_RECORDED_ONLY",
  "data_classification": "USER_RECORDED",
  "affiliate": {
    "state": "UNCONFIGURED",
    "click_url": null,
    "verified_product_match": false,
    "bound_product_id": null
  }
}
```

## V1 compatibility

`/api/v1` remains read-only and keeps the legacy flattened Affiliate response. Additive classification fields are present to prevent guessing. Unsafe unsupported evidence is not preserved: V1 also returns `item_condition=UNKNOWN`, never the former inferred `NEW`. V2 responses include `contract_compatibility=["CDH-WEB-CONTRACT-V1"]`.

No endpoint redirects, opens a URL, or emits a verified affiliate state.
