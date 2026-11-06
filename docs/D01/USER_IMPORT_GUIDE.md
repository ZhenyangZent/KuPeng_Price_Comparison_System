# D01 user import guide

Use only a local file that you selected or created. D01 never follows a product URL and never fills missing values from the network.

## JSON

JSON must follow the frozen `CDH-EXCHANGE-1` schema. The included synthetic fixture is at:

`input/orchestrator_bundles/D01/extracted/CDH_D01_001_INPUT_BUNDLE/10_SYNTHETIC_SUBMISSION_FIXTURE.json`

Set `is_synthetic=false` only for a genuine observation that you personally supplied. `USER_ENTERED` and `USER_FILE` mean user-provided evidence, not a verified checkout price.

## CSV

Required headers are `submission_id`, `created_at_utc`, `observed_at_utc`, `product_title`, `displayed_price_twd`, and `is_synthetic`. Supported optional headers are:

```text
record_type,published_at_utc,promo_claim,platform,product_id,variant_id,seller_id,
price_basis,minimum_purchase_quantity,shipping_status,shipping_fee_twd,stock_status,
coupon_status,account_eligibility_status,mandatory_fee_status,source_url,source_note,notes
```

Timestamps must be ISO-8601 with timezone; UTC `Z` is recommended. Money and quantity cells use decimal integer digits only. Blank nullable fields remain unknown; `0` is different from blank. `is_synthetic` is exactly `true` or `false`.

Each row is isolated. A bad row is quarantined while later rows continue. The file limit is 50 MiB and 10,000 rows. Text that starts with `=`, `+`, `-`, or `@` is stored as text and never evaluated.

Run:

```powershell
python apps/d01/d01_cli.py --db data/d01/observations.sqlite3 ingest C:\path\your-file.csv
```

Review quarantine reasons and regenerate the snapshot after import. Never place passwords, cookies, access tokens, addresses, payment data, or account identifiers in notes or URLs.

