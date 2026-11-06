# CDH Affiliate Provider Contract V1

這是 Role C 提供給 Role F 的機器可讀能力契約，並非 Coupang 官方 API schema。

## Current state

- `provider_state=PENDING_OFFICIAL_DOCS`
- `source_discovery_status=SOURCE_BLOCKED`
- `url_conversion=UNKNOWN`
- `affiliate_url=null`
- `verified_product_match=false`
- `cta_enabled=false`

台灣官方文件目前只允許把會員流程、連結歸因概念、收益／稅務流程標為 `VERIFIED`。它們不會自動通過 CTA 所需的 capability、account、host、exact-match、TTL/revocation、disclosure 或 user-intent gate。

## Fail-closed rule

只要 `provider_state != VERIFIED`，validator 要求：

- conversion disabled；endpoint、認證、rate limit、TTL 必須為 null；
- input/output host allowlist 必須為空；
- affiliate URL 與 disclosure 必須為 null；
- exact product match 與 CTA 必須為 false；
- coupon/cart/checkout/order/payment 全為 false；
- 不得以一般商品 URL 作聯盟 fallback。

即使未來單一 capability 被官方文件核實，也只能解鎖該 capability；不能把 link conversion 擴張成商品搜尋、圖片再展示、快取、歷史價或交易權限。

## Evidence rule

`VERIFIED` capability 必須至少有一筆：

- `market=TW`；
- `authority_class=COUPANG_OFFICIAL`；
- HTTPS 官方 URL；
- 具版本／生效日；
- `supports[]` 明確列出該 capability。

韓國官方文件只能保留為 reference，且需 `taiwan_applicability=UNKNOWN`；不得支援任何台灣 `VERIFIED` capability。Affiliates.One 資料只能標為第三方營運資訊，不能作 Coupang 技術 contract authority。

## Runtime integration

F 應先離線載入並驗證 `PROVIDER_CONTRACT_V1.json`。在目前契約下，`GET /api/v1/products/{id}/affiliate` 應回：

```json
{
  "state": "PENDING_OFFICIAL_DOCS",
  "click_url": null,
  "verified_product_match": false
}
```

UI 不顯示可點擊 CTA，也不得自動開啟或提供一般商品 URL 作「暫時聯盟連結」。
