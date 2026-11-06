# CDH-PRICE-QUALITY-READMODEL-1 schema

An accepted copy contains exactly one `price_quality_schema.version=1` row and an `observations` table with these required columns:

`observation_id`, `submission_id`, `observed_at_utc`, `source_kind`, `source_authorization`, `product_title`, `product_id`, `seller_id`, `variant_id`, `minimum_purchase_quantity`, `package_signature`, `item_condition`, `displayed_price_twd`, `price_basis`, `shipping_status`, `is_synthetic`.

The sidecar authorization descriptor uses `CDH-PRICE-QUALITY-AUTH-1` and binds the exact SQLite SHA-256. `contains_private_fields` must be false. User copies permit exactly `USER_ENTERED` and `USER_FILE` with `source_authorization=USER_AUTHORIZED` and `is_synthetic=0`; synthetic fixtures permit exactly `SYNTHETIC` with `source_authorization=SYNTHETIC_FIXTURE` and `is_synthetic=1`.

Exact identity requires product, seller, variant, positive quantity, package signature, known item condition and price basis. Missing/unknown evidence isolates the row by submission ID and sets `exact_match_claim_allowed=false`.

The current D01/D04/B06 fixture schema does not contain all B07 fields. It is intentionally rejected rather than guessed. A future B08 adapter may create a separately authorized B07 copy while preserving `UNKNOWN` and incomplete-identity semantics.
