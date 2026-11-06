# D04 → A04 Local History Contract Proposal

CONTRACT: `CDH-LOCAL-HISTORY-1`

STATUS: `PROPOSAL_ONLY`

PRODUCER: `D04 read-only history query`

CONSUMER: `A04 optional display integration`

本提案不修改 A 工作線。A04 若採用，應以明確的新整合 authority 實作；不得由 GUI 直接寫 SQLite。

## 呼叫邊界

- 呼叫端必須明確傳入 SQLite 路徑與 timezone-aware `as_of`。
- D04 只用 SQLite URI `mode=ro` 與 `PRAGMA query_only=ON`；不 migration、不建立表、不 checkpoint、不寫 WAL。
- 僅讀 `USER_ENTERED`、`USER_FILE` 且 `is_synthetic=0` 的 `observations`。
- `source_status` 固定 `SOURCE_BLOCKED`；JSON 不構成自動來源、結帳價、免運或優惠資格證據。

## 必要欄位

- 頂層：`contract`, `calculation_version`, `timezone`, `generated_at_utc`, `as_of_utc`, `source`, `semantics`, `quality`, `series`, `export_sha256`。
- 每個 series：`series_key`, `identity`, `identity_state`, `observation_day_count`, `first_observed_at_utc`, `last_observed_at_utc`, `is_comparable`, `comparison_status`, `median_twd`, `historical_low_twd`, `window_day_counts`, `coverage`, `source_counts`, `quality_flags`。
- identity：`product_id`, `variant_id`, `seller_id`, `minimum_purchase_quantity`, `price_basis`。`package_signature` 在 D01 schema 不存在，因此固定 `null` 並帶 `package_signature_state=UNAVAILABLE_IN_D01_SCHEMA`。
- 安全欄位：`verified_checkout_low_claim_allowed=false`, `true_drop_claim_allowed=false`, `checkout_total_verified=false`, `free_shipping_inferred=false`。

## 可選顯示欄位

- `display_title` 僅供顯示，`title_identity_used=false`；不可用相似品牌或名稱合併序列。
- `source_counts`、`coverage`、`quality_flags` 可在進階資料品質面板顯示。

## 失效與比較規則

- M7/M30/M90 是 Asia/Taipei 完整日窗口，不含當日；時間均先正規化。
- 每 UTC 小時只取首個有效樣本，再求當日整數中位數（偶數向下取整），窗口值為每日中位數的整數中位數。
- `M30 < 7` 天為 `INSUFFICIENT_HISTORY`；最近有效樣本超過 7×24 小時為 `STALE_HISTORY`。
- 缺少任一必要身份、最低購買量或明確 price basis 時為 `NEEDS_IDENTITY_REVIEW`，每筆以 submission 隔離，不合併。
- coupon／account eligibility 條件沒有可綁定識別時為 `CONDITIONAL_PRICE_UNBOUND`。
- `REFERENCE_PRICE` 與 `COUPON_INCLUDED_DISPLAY` 不作 item-price 比較。
- 即使 `is_comparable=true`，也只代表同身份 displayed item price 的 exploratory summary，不可顯示「平台確認創歷史最低」、「真降幅」或「確認免運」。

## 建議 A04 呈現

- 顯示 `comparison_status` 與覆蓋日數，不只顯示一個價格。
- 0 元必須同時顯示 `ZERO_PRICE_UNVERIFIED_TOTAL`。
- `UNKNOWN` 保持 UNKNOWN，不轉成 0、免費、可用、符合資格或有貨。
