# C07 → B10 實際欄位映射

- C07 `series_identity` ↔ B10 `product.series_identity`，六欄必須完全相同。
- C07 scope evidence ↔ B10 `product.coupon.scope_evidence`。
- C07 eligibility profile ↔ B10 `product.coupon.eligibility_profile`。
- C07 valid until ↔ B10 `product.coupon.valid_until`。
- C07 source authorization ↔ B10 `product.source_permission`；兩者都通過才可 TEST_ONLY 展示。
- C07 rights 決定 history retention；B10 history 本身不能證明保存權。
- B10 `quality_flags` 非空時不可把 confirmed coupon 當已准入。
- Search item 無商品級 `schema_version`、無 history；Detail 的 history 位於 envelope，這是正常 wire，不得硬塞欄位。
- Deal notification 另要求 `shipping_status=KNOWN` 及 `required_total_twd` 已知。
- Affiliate CTA 永遠不由 coupon mapping 授權。
